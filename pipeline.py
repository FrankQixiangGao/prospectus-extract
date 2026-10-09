"""Four stages: identify -> locate -> extract (the only LLM stage) -> normalize.

Every stage returns an artifact that evaluate.py can score against ground truth:
  identify -> section page range, locate -> page list, extract -> raw strings, normalize -> values.
"""
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date

import pymupdf

from config import COMMON, DATED_FIELDS, FIELD_INSTRUCTIONS, FIELD_RANGES, FIELDS, PERIODS, TABLES

# ----------------------------------------------------------------------------- tracing


class Trace:
    """Wall-clock per stage + one record per LLM call."""

    def __init__(self):
        self.stages = {}
        self.llm_calls = []

    @contextmanager
    def stage(self, name):
        t = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + time.perf_counter() - t


# ----------------------------------------------------------------------------- text utils

MONTHS = {m: i + 1 for i, m in enumerate(
    "january february march april may june july august september october november december".split())}


def norm(s):
    s = s.replace("®", "").replace("™", "").replace("’", "'").replace("‘", "'")
    return re.sub(r"\s+", " ", s).strip().lower()


def find_dates(text):
    out = []
    for m in re.finditer(r"(january|february|march|april|may|june|july|august|september|october|november|december)"
                         r"\s+(\d{1,2}),?\s+(\d{4})", text, re.I):
        try:
            out.append(date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})\s+(january|february|march|april|may|june|july|august|september|october|"
                         r"november|december),?\s+(\d{4})", text, re.I):
        try:
            out.append(date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))))
        except ValueError:
            pass
    for m in re.finditer(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            out.append(date(y, int(m.group(1)), int(m.group(2))))
        except ValueError:
            pass
    return out


def cover_date(pages):
    """Prospectus/supplement date: latest date that follows 'dated', 'prospectus', 'revised', 'supplement'."""
    found = []
    for t in pages:
        for m in re.finditer(r"(dated|prospectus|revised|supplement(ed)?|as of)\b", t, re.I):
            found += find_dates(t[m.end(): m.end() + 60])
    if not found:
        found = find_dates(pages[0])[:1]
    return max(found) if found else None


def layout_text(page, cw=5.5, ytol=2.5):
    """Rebuild a page as text with columns aligned by x-position, so table cells stay under their headers."""
    words = page.get_text("words")
    words.sort(key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    lines = []
    for w in words:
        yc = (w[1] + w[3]) / 2
        if lines and abs(lines[-1][0] - yc) <= ytol:
            lines[-1][1].append(w)
        else:
            lines.append([yc, [w]])
    out = []
    for _, ws in lines:
        s = ""
        for w in sorted(ws, key=lambda w: w[0]):
            col = int(w[0] / cw)
            if len(s) < col:
                s += " " * (col - len(s))
            elif s:
                s += " "
            s += w[4]
        out.append(s.rstrip())
    return "\n".join(out)


# ----------------------------------------------------------------------------- stage 0: parse


class Doc:
    def __init__(self, path):
        self.path = path
        self.pdf = pymupdf.open(path)
        self.n = len(self.pdf)
        self.raw = [p.get_text() for p in self.pdf]          # 0-indexed
        self.text = [norm(t) for t in self.raw]
        self._layout = {}
        self.doc_date = cover_date(self.raw[:2])

    def layout(self, pno):                                    # pno is 1-indexed
        if pno not in self._layout:
            self._layout[pno] = layout_text(self.pdf[pno - 1])
        return self._layout[pno]


# ----------------------------------------------------------------------------- stage 1: identify

HEADING = re.compile(r"^\s*(the\s+fund.s\s+)?investment\s+objectives?(\s*\(s\))?\s*:?\s*$", re.I)


def identify(doc, fund_name, ticker):
    """Find the page range of the target fund's summary section.

    Summary sections (Form N-1A Item 2-8) start with an 'Investment Objective' heading. Umbrella docs repeat it
    once per fund. The target's section is the heading with the fund name (or ticker) right before it.
    Tickers often appear only on the cover, so the name is the primary signal.
    """
    name = norm(fund_name)
    tick = re.compile(r"\b" + re.escape(ticker.lower()) + r"\b")
    if sum(len(t) for t in doc.text) < 100 * doc.n:
        return dict(start=None, end=None, method="no_text_layer")      # scanned PDF: no OCR path, say so
    if not any(name in t or tick.search(t) for t in doc.text):
        return dict(start=None, end=None, method="target_not_found")   # never extract another fund's numbers
    heads = [i + 1 for i, r in enumerate(doc.raw) if any(HEADING.match(l) for l in r.splitlines())]

    best = None
    for h in heads:
        t = doc.text[h - 1]
        pos = re.search(r"investment objective", t)
        p0 = pos.start() if pos else 0
        near = t[max(0, p0 - 600): p0 + 300]      # name is either a header above or the first sentence below
        prev_tail = doc.text[h - 2][-800:] if h > 1 else ""
        if name in near:
            score, start = 0, h
        elif name in prev_tail:
            score, start = 1, h - 1
        elif tick.search(near):
            score, start = 2, h
        else:
            continue
        if best is None or score < best[0]:
            best = (score, start, h)

    if best:
        _, start, h = best
        nxt = [x for x in heads if x > h]
        end = min(nxt[0] - 1 if nxt else doc.n, start + COMMON["max_section_pages"] - 1, doc.n)
        return dict(start=start, end=end, method=f"heading(score={best[0]})")

    # Fallbacks: short doc -> whole doc; else first page mentioning the name/ticker after the cover.
    if doc.n <= 20:
        return dict(start=1, end=doc.n, method="whole_doc")
    hits = [i + 1 for i, t in enumerate(doc.text) if i > 0 and (name in t or tick.search(t))]
    if hits:
        return dict(start=hits[0], end=min(hits[0] + COMMON["max_section_pages"] - 1, doc.n), method="name_hit")
    return dict(start=1, end=min(COMMON["max_section_pages"], doc.n), method="not_found")


# ----------------------------------------------------------------------------- stage 2: locate


def _score(doc, p, spec):
    t = doc.text[p - 1]
    anchor = any(re.search(a, t) for a in spec["anchors"])
    cues = sum(bool(re.search(c, t)) for c in spec["cues"])
    return anchor, cues


def locate(doc, section, mode):
    pages = list(range(section["start"], section["end"] + 1))
    if mode == "section":
        return dict(pages=pages[: COMMON["max_pages_section_mode"]], best={})
    picked, best = set(), {}
    for tname, spec in TABLES.items():
        scored = []
        for p in pages:
            a, c = _score(doc, p, spec)
            a_prev = p > pages[0] and _score(doc, p - 1, spec)[0]
            if not (a or a_prev):
                continue                     # a table page needs its heading on it or on the page before
            c_next = _score(doc, p + 1, spec)[1] if p < pages[-1] else 0
            scored.append((3 * a + c + 0.5 * c_next, -p, p, a))
        if not scored:
            continue
        _, _, b, has_anchor = max(scored)
        best[tname] = b
        picked.add(b)
        if b < pages[-1]:
            picked.add(b + 1)                # tables run onto the next page
        if not has_anchor and b > pages[0]:
            picked.add(b - 1)                # heading (and as-of date) is on the previous page
    return dict(pages=sorted(picked), best=best)


# ----------------------------------------------------------------------------- stage 3: extract (LLM)

TOOL = {
    "name": "record_values",
    "description": "Record the extracted table values for the target fund.",
    "input_schema": {
        "type": "object",
        "properties": {
            "share_classes": {"type": "array", "items": {"type": "string"}},
            "values": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "share_class": {"type": "string"},
                        "field": {"type": "string",
                                  "enum": FIELDS},
                        "period": {"type": "string", "enum": PERIODS},
                        "raw_value": {"type": "string"},
                        "page": {"type": "integer"},
                        "inception_date": {"type": ["string", "null"]},
                        "confidence": {"type": "number"},
                    },
                    "required": ["share_class", "field", "period", "raw_value", "page", "confidence"],
                },
            },
        },
        "required": ["share_classes", "values"],
    },
}

SYSTEM = ("You extract numbers from mutual fund and ETF prospectus tables for a compliance analyst. "
          "Accuracy matters more than coverage: copy values verbatim and never guess.\n" + FIELD_INSTRUCTIONS)


class LLM:
    def __init__(self, model, trace):
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.trace = trace

    FORCED_UNSUPPORTED = set()                     # models that reject tool_choice type "tool"

    def call(self, stage, user, max_tokens):
        import anthropic
        t = time.perf_counter()
        kw = dict(model=self.model, max_tokens=max_tokens,
                  system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                  tools=[TOOL], messages=[{"role": "user", "content": user}])
        if self.model in LLM.FORCED_UNSUPPORTED:
            kw["tool_choice"] = {"type": "auto"}
            kw["messages"][0]["content"] = user + "\n\nRespond ONLY by calling the record_values tool."
            r = self.client.messages.create(**kw)
        else:
            try:
                r = self.client.messages.create(**kw, tool_choice={"type": "tool", "name": TOOL["name"]})
            except anthropic.BadRequestError as e:
                if "tool_choice" not in str(e):
                    raise
                LLM.FORCED_UNSUPPORTED.add(self.model)
                return self.call(stage, user, max_tokens)
        u = r.usage
        self.trace.llm_calls.append(dict(
            stage=stage, model=self.model, latency_s=round(time.perf_counter() - t, 3),
            input_tokens=u.input_tokens, output_tokens=u.output_tokens,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
            stop_reason=r.stop_reason))
        for block in r.content:
            if block.type == "tool_use":
                return coerce_tool_input(block.input)
        return {"share_classes": [], "values": []}


def coerce_tool_input(x):
    """Models occasionally return a nested array as a JSON string; accept both, drop malformed items."""
    x = dict(x)
    vals = x.get("values", [])
    if isinstance(vals, str):
        try:
            vals = json.loads(vals)
        except json.JSONDecodeError:
            vals = []
    x["values"] = [v for v in vals if isinstance(v, dict) and {"share_class", "field", "period"} <= v.keys()]
    return x


def _page_block(doc, pages, budget_tokens):
    """Concatenate pages until the (estimated) token budget is hit. ~3.5 chars per token."""
    parts, used, dropped = [], 0, []
    for p in pages:
        txt = f"=== PAGE {p} ===\n{doc.layout(p)}\n"
        est = len(txt) / 3.5
        if used + est > budget_tokens and parts:
            dropped.append(p)
            continue
        parts.append(txt)
        used += est
    return "".join(parts), dropped


def extract(doc, located, fund_name, ticker, cfg, llm):
    budget = COMMON["max_input_tokens_section"] if cfg["locate"] == "section" else COMMON["max_input_tokens"]
    header = f"TARGET FUND: {fund_name} (ticker {ticker})\n\n"

    def one(stage, pages):
        body, dropped = _page_block(doc, pages, budget)
        out = llm.call(stage, header + body, COMMON["max_output_tokens"])
        if not out.get("values"):                  # iter3: malformed/empty tool output -> one bounded retry
            out = llm.call(stage + ":retry", header + body, COMMON["max_output_tokens"])
        out["_dropped_pages"] = dropped
        return out

    if cfg.get("split_calls") and located["best"]:
        groups = {}
        for tname, b in located["best"].items():
            groups[tname] = [p for p in located["pages"] if abs(p - b) <= 1]
        with ThreadPoolExecutor(len(groups)) as ex:
            outs = list(ex.map(lambda kv: one(f"extract:{kv[0]}", kv[1]), groups.items()))
        merged = {"share_classes": [], "values": [], "_dropped_pages": []}
        for o in outs:
            merged["share_classes"] += [c for c in o.get("share_classes", []) if c not in merged["share_classes"]]
            merged["values"] += o.get("values", [])
            merged["_dropped_pages"] += o["_dropped_pages"]
        return merged
    return one("extract", located["pages"])


# ----------------------------------------------------------------------------- stage 4: normalize

DASHES = {"", "—", "–", "-", "n/a", "na", "none", "n.a.", "*"}


def canon_class(s):
    """'Investor Class'->investor, 'Class A shares'->a, 'Stock – Class X'->x, 'Admiral Shares'->admiral, ETF->single."""
    s = norm(s)
    m = (re.search(r"\bclass\s+([a-z0-9]+)\b", s) or re.search(r"\b([a-z0-9]+)\s+class\b", s)
         or re.search(r"\b([a-z0-9]+)\s+shares?\b", s))
    tok = m.group(1) if m else s.strip(" :")
    return "single" if tok in ("", "single", "etf", "fund", "the", "n/a") else tok


def parse_value(raw):
    """'(0.55 )b' -> -0.55 ; '24.60%' -> 24.6 ; '—' -> None. Returns (value, numeric_string)."""
    s = raw.strip().replace(" ", "")
    if s.lower().rstrip("%") in DASHES:
        return None, None
    m = re.search(r"(\()?([-−–]?)(\d+(?:\.\d+)?)", s)
    if not m:
        return None, None
    v = float(m.group(3))
    if m.group(1) or m.group(2):
        v = -v
    return v, m.group(3)


def returns_as_of(doc, pages):
    """Deterministic as-of date for the performance table: 'periods ended December 31, 2025' etc."""
    for p in pages:
        t = doc.raw[p - 1]
        # iter2: scan EVERY "periods ended" match; the first one is often the bar-chart caption with no date
        for m in re.finditer(r"periods?\s+end(?:ed|ing)\s*:?\s*(.{0,40})", t, re.I | re.S):
            ds = find_dates(m.group(1))
            if ds:
                return ds[0]
    return None


def normalize(doc, raw_out, located, fund_ticker):
    rows = []
    perf_pages = [p for p in located["pages"]
                  if any(re.search(a, doc.text[p - 1]) for a in TABLES["performance"]["anchors"])] or located["pages"]
    as_of = returns_as_of(doc, perf_pages)
    for v in raw_out.get("values", []):
        value, digits = parse_value(v.get("raw_value", ""))
        page = v.get("page")
        on_page = bool(digits) and page in located["pages"] and digits in doc.layout(page)
        on_any = bool(digits) and any(digits in doc.layout(p) for p in located["pages"])
        period = v["period"]
        inception = v.get("inception_date")
        if period == "since_inception" and not inception and digits and page in located["pages"]:
            # iter4: the model often skips a separate "Inception Date" column; read it off the value's own line
            for line in doc.layout(page).splitlines():
                if digits in line and find_dates(line):
                    inception = find_dates(line)[0].isoformat()
                    break
        if v["field"] in DATED_FIELDS:
            period = f"{period}@{as_of.isoformat() if as_of else 'unknown'}"
        rows.append(dict(
            fund=fund_ticker, share_class=canon_class(v["share_class"]), field=v["field"], period=period,
            value=value, raw_value=v.get("raw_value"), page=page, inception_date=inception,
            status="reported" if value is not None else "not_reported",
            llm_conf=float(v.get("confidence", 0.5)), grounded=on_page, grounded_any=on_any))

    # net = gross when the table has no "after waiver" row at all (rule from the field spec).
    # If the row exists but a class is missing, we do NOT fill it: that is an extraction miss, not a zero waiver.
    if not any(r["field"] == "net_expense_ratio" for r in rows):
        for r in [r for r in rows if r["field"] == "gross_expense_ratio"]:
            rows.append({**r, "field": "net_expense_ratio", "note": "no_waiver_row:net=gross"})

    # checks -> confidence (the label-free quality signal)
    gross = {r["share_class"]: r["value"] for r in rows if r["field"] == "gross_expense_ratio"}
    for r in rows:
        if r["status"] == "not_reported":
            pg = r["page"] if r["page"] in located["pages"] else None
            check = 1.0 if pg and r["raw_value"] is not None and r["raw_value"].strip() in doc.layout(pg) else 0.5
        else:
            check = 1.0 if r["grounded"] else (0.6 if r["grounded_any"] else 0.0)
            lo, hi = FIELD_RANGES.get(r["field"], (-1e9, 1e9))
            if not (lo <= r["value"] <= hi):
                check -= 0.5
            if r["field"] in DATED_FIELDS and r["period"].endswith("@unknown"):
                check -= 0.5                       # iter2: period label is incomplete -> not trustworthy as a key
            if r["field"] == "net_expense_ratio" and gross.get(r["share_class"]) is not None \
                    and r["value"] > gross[r["share_class"]] + 1e-9:
                check -= 0.5
        r["check"] = max(check, 0.0)
        r["confidence"] = round(0.5 * r["llm_conf"] + 0.5 * r["check"], 3)
    return rows


# ----------------------------------------------------------------------------- derive + resolve (spec rules)


def derive(rows):
    """fee_waiver = gross - net, per class. Confidence = min of inputs."""
    out = []
    by = {(r["share_class"], r["field"]): r for r in rows}
    for cls in sorted({r["share_class"] for r in rows if "expense" in r["field"]}):
        g, n = by.get((cls, "gross_expense_ratio")), by.get((cls, "net_expense_ratio"))
        base = dict(fund=rows[0]["fund"], share_class=cls, field="fee_waiver", period="current", raw_value=None,
                    page=None, inception_date=None, llm_conf=None, grounded=None, grounded_any=None, check=None)
        if g and n and g["value"] is not None and n["value"] is not None:
            out.append({**base, "value": round(g["value"] - n["value"], 4), "status": "reported",
                        "confidence": min(g["confidence"], n["confidence"])})
        else:
            out.append({**base, "value": None, "status": "not_computable", "confidence": 0.0})
    return out


def dedupe(rows):
    """One value per key within a document: keep the highest-confidence candidate."""
    best = {}
    for r in rows:
        k = (r["fund"], r["share_class"], r["field"], r["period"])
        if k not in best or r["confidence"] > best[k]["confidence"]:
            best[k] = r
    return list(best.values())


def resolve(all_rows):
    """Across documents: the latest-dated document governs; ties -> higher confidence."""
    best = {}
    for r in all_rows:
        k = (r["fund"], r["share_class"], r["field"], r["period"])
        rank = (r.get("doc_date") or "", r["confidence"])
        if k not in best or rank > best[k][0]:
            best[k] = (rank, r)
    return [r for _, r in best.values()]


def label_free_signals(rows):
    """Computable on any document, no ground truth needed.
    completeness: share of the expected grid (every class x {gross, net, every return horizon seen}) that has a row.
    grounded: share of reported values whose digits appear on the cited page.
    as_of_found: the returns table's as-of date was parsed."""
    direct = [r for r in rows if r["field"] != "fee_waiver"]
    if not direct:
        return dict(completeness=0.0, grounded=0.0, as_of_found=False)
    classes = {r["share_class"] for r in direct}
    slots = {(r["field"], r["period"]) for r in direct}          # every (field, period) seen for any class
    expected = len(classes) * len(slots)
    got = len({(r["share_class"], r["field"], r["period"]) for r in direct})
    rep = [r for r in direct if r["status"] == "reported"]
    return dict(completeness=round(min(got / expected, 1.0), 3),
                grounded=round(sum(bool(r["grounded"]) for r in rep) / max(len(rep), 1), 3),
                as_of_found=not any(r["period"].endswith("@unknown") for r in direct))


# ----------------------------------------------------------------------------- one target, end to end


def run_target(path, fund_name, ticker, cfg, dry_run=False):
    trace = Trace()
    t0 = time.perf_counter()
    with trace.stage("parse"):
        doc = Doc(path)
    with trace.stage("identify"):
        section = identify(doc, fund_name, ticker)
    rows = []
    if section["start"] is None:
        located = dict(pages=[], best={})
        rows = [dict(fund=ticker, share_class="*", field="*", period="*", value=None, status=section["method"],
                     confidence=1.0, page=None, raw_value=None, inception_date=None, llm_conf=None, check=None,
                     grounded=None, grounded_any=None)]
        dry_run = True                                                  # nothing to send to the model
    else:
        with trace.stage("locate"):
            located = locate(doc, section, cfg["locate"])
    if not dry_run:
        llm = LLM(cfg["model"], trace)
        with trace.stage("extract"):
            raw_out = extract(doc, located, fund_name, ticker, cfg, llm)
        with trace.stage("normalize"):
            rows = normalize(doc, raw_out, located, ticker)
            rows = dedupe(rows)
            rows += derive(rows) if rows else []
        # C4: escalate to the whole section only when the cheap path fails its own label-free checks
        sig = label_free_signals(rows)
        if cfg.get("escalate") and (sig["completeness"] < 1.0 or not sig["as_of_found"]):
            located2 = locate(doc, section, "section")
            n_before = len(trace.llm_calls)
            with trace.stage("extract"):
                raw2 = extract(doc, located2, fund_name, ticker, {**cfg, "locate": "section"}, llm)
            for c in trace.llm_calls[n_before:]:
                c["escalated"] = True
            with trace.stage("normalize"):
                rows2 = dedupe(normalize(doc, raw2, located2, ticker))
                rows2 += derive(rows2) if rows2 else []
            if label_free_signals(rows2)["completeness"] >= sig["completeness"]:
                rows, located = rows2, located2
    total = time.perf_counter() - t0
    signals = label_free_signals([r for r in rows if r["field"] != "*"])
    signals["escalated"] = any(c.get("escalated") for c in trace.llm_calls)
    meta = dict(file=path.split("/")[-1], fund=ticker, pages=doc.n,
                doc_date=doc.doc_date.isoformat() if doc.doc_date else None,
                section=section, located=located["pages"], best=located["best"],
                stages={k: round(v, 3) for k, v in trace.stages.items()}, total_s=round(total, 3), signals=signals,
                llm_calls=trace.llm_calls)
    for r in rows:
        r["file"], r["doc_date"] = meta["file"], meta["doc_date"]
    return rows, meta
