"""Score one or more runs against ground truth.

    python evaluate.py runs/c1 runs/c2 runs/c3 --gt eval/ground_truth.csv

Per run: end-to-end accuracy, error categories (wrong class / fund / period / value), first failing stage,
per-stage metrics, derived-field propagation, label-free signal vs accuracy, abstention curve, latency and
tokens by document size. Across runs: trade-off plot. Writes report/<runs>.md + PNGs.
"""
import argparse
import csv
import json
import os
import statistics as st
from collections import Counter, defaultdict

from config import COMMON, PRICES

TOL = 0.005
WRONG_COST, ABSTAIN_COST = 5.0, 1.0   # business priority: a wrong number costs 5x a "not found" (CLI-tunable)
SIZE_BUCKETS = [(20, "small (<=20p)"), (100, "medium (21-100p)"), (10**9, "large (>100p)")]
LATENCY_TARGET_P95 = 10.0  # seconds, see write-up for derivation


def fnum(x):
    return None if x in (None, "", "None") else float(x)


def load_gt(path):
    gt = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        k = (r["file"], r["fund"], r["share_class"], r["field"], r["period"])
        gt[k] = dict(value=fnum(r["value"]), status=r["status"], page=int(r["page"]) if r["page"] else None,
                     governs=r.get("governs", "true").lower() == "true", inception_date=r.get("inception_date") or None)
    # derived: fee_waiver = gross - net, computed from labeled inputs (not labeled by hand)
    for (f, fund, c, field, p), g in list(gt.items()):
        if field == "gross_expense_ratio":
            n = gt.get((f, fund, c, "net_expense_ratio", p))
            if n and g["value"] is not None and n["value"] is not None:
                gt[(f, fund, c, "fee_waiver", p)] = dict(value=round(g["value"] - n["value"], 4), status="reported",
                                                         page=g["page"], derived=True)
    return gt


def load_run(d):
    preds = {}
    for r in csv.DictReader(open(os.path.join(d, "predictions.csv"), encoding="utf-8")):
        k = (r["file"], r["fund"], r["share_class"], r["field"], r["period"])
        preds[k] = dict(value=fnum(r["value"]), status=r["status"], conf=float(r["confidence"] or 0),
                        inception_date=r.get("inception_date"),
                        page=int(r["page"]) if r["page"] else None, raw=r["raw_value"],
                        check=fnum(r["check"]), llm_conf=fnum(r["llm_conf"]))
    traces = {(t["file"], t["fund"]): t for t in map(json.loads, open(os.path.join(d, "trace.jsonl")))}
    return preds, traces


def classify(k, g, p, gt, tr):
    """Outcome for one GT key (ignoring abstention), plus first failing stage for non-correct outcomes."""
    f, fund, c, field, period = k
    sec, loc = tr["section"], tr["located"]
    if g["status"] == "not_reported":
        if p is None or p["status"] != "reported":
            return "correct", None
        return "hallucinated_value", "extract"
    if p is None or p["value"] is None:
        # was the value extracted under a different period label (e.g. wrong as-of date)?
        horizon = period.split("@")[0]
        if field != "fee_waiver" and any(pk != k and pk[:4] == k[:4] and pk[4].split("@")[0] == horizon
                                         and PREDS_CACHE[pk]["value"] is not None for pk in PREDS_CACHE):
            return "wrong_period", "normalize"
        outcome = "missed"
    elif abs(p["value"] - g["value"]) < TOL:
        return "correct", None
    else:
        pv = p["value"]
        same = lambda kk: kk in gt and gt[kk]["value"] is not None and abs(gt[kk]["value"] - pv) < TOL
        if g["page"] and not (sec["start"] <= g["page"] <= sec["end"]):
            outcome = "wrong_fund"
        elif any(same((f, fund, c2, field, period)) for (_, _, c2, _, _) in gt if c2 != c):
            outcome = "wrong_class"
        elif any(same((f, fund, c, field, p2)) for (_, _, _, _, p2) in gt if p2 != period):
            outcome = "wrong_period"
        elif field == "fee_waiver":
            outcome = "wrong_value"
        else:
            outcome = "wrong_row_or_misread"
    if field == "fee_waiver":
        return outcome, "propagated_from_inputs"
    gp = g["page"]
    if gp is None:
        stage = "extract"
    elif not (sec["start"] <= gp <= sec["end"]):
        stage = "identify"
    elif gp not in loc:
        stage = "locate"
    elif p is not None and p["raw"] and f"{abs(g['value']):.2f}".rstrip("0").rstrip(".") in p["raw"]:
        stage = "normalize"
    else:
        stage = "extract"
    return outcome, stage


PREDS_CACHE = {}


def call_cost(c):
    p = PRICES.get(c.get("model"))
    if not p:
        return 0.0
    return (c["input_tokens"] * p["input"] + c["output_tokens"] * p["output"]
            + c.get("cache_write_tokens", 0) * p["cache_write"] + c.get("cache_read_tokens", 0) * p["cache_read"]) / 1e6


def pctl(xs, q):
    xs = sorted(xs)
    if not xs:
        return None
    i = min(len(xs) - 1, max(0, int(round(q * (len(xs) - 1)))))
    return xs[i]


def evaluate_run(d, gt, thr):
    global PREDS_CACHE
    preds, traces = load_run(d)
    PREDS_CACHE = preds
    rows, cats, stages, examples = [], Counter(), Counter(), {}
    for k, g in gt.items():
        tr = traces.get((k[0], k[1]))
        if tr is None:
            continue
        p = preds.get(k)
        outcome, stage = classify(k, g, p, gt, tr)
        answered = p is not None and p["status"] == "reported"
        abstained = answered and p["conf"] < thr
        final = "abstained" if (abstained and g["status"] == "reported") else outcome
        if g["status"] == "not_reported" and abstained:
            final = "correct"                     # withheld a number that should not exist
        rows.append(dict(key=k, g=g, p=p, outcome=outcome, final=final, stage=stage, tr=tr))
        cats[final] += 1
        if final not in ("correct", "abstained"):
            stages[stage] += 1
            examples.setdefault(final, f"{k[0]} p.{g['page']} {k[2]}/{k[3]}/{k[4]}")
    spurious = [k for k, p in preds.items() if k not in gt and p["status"] == "reported"
                and (k[0], k[1]) in {(r["key"][0], r["key"][1]) for r in rows}]
    cats["spurious_key"] = len(spurious)
    if spurious:
        examples.setdefault("spurious_key", "%s %s/%s/%s" % (spurious[0][0], *spurious[0][2:]))

    n = len(rows)
    direct = [r for r in rows if r["key"][3] != "fee_waiver"]
    # ---- per-stage metrics
    targets = defaultdict(list)
    for r in direct:
        targets[(r["key"][0], r["key"][1])].append(r)
    id_ok = {t: all(r["g"]["page"] is None or r["tr"]["section"]["start"] <= r["g"]["page"] <= r["tr"]["section"]["end"]
                    for r in rs) for t, rs in targets.items()}
    with_page = [r for r in direct if r["g"]["page"] and id_ok[(r["key"][0], r["key"][1])]]
    loc_ok = [r for r in with_page if r["g"]["page"] in r["tr"]["located"]]
    ext_ok = [r for r in loc_ok if r["outcome"] == "correct"]
    per_stage = dict(
        identify_section_correct=f"{sum(id_ok.values())}/{len(id_ok)}",
        locate_page_recall=f"{len(loc_ok)}/{len(with_page)}",
        extract_accuracy_given_correct_page=f"{len(ext_ok)}/{len(loc_ok)}",
    )
    # ---- derived propagation
    prop = Counter()
    for r in rows:
        if r["key"][3] != "fee_waiver":
            continue
        f, fund, c, _, per = r["key"]
        ins = [next((x for x in rows if x["key"] == (f, fund, c, fld, per)), None)
               for fld in ("gross_expense_ratio", "net_expense_ratio")]
        n_bad = sum(1 for x in ins if x is None or x["outcome"] != "correct")
        prop[(f"inputs_wrong={n_bad}", "waiver_correct" if r["outcome"] == "correct" else "waiver_wrong")] += 1
    # ---- label-free signal: grounding check vs accuracy
    ans = [r for r in direct if r["p"] is not None and r["p"]["status"] == "reported" and r["g"]["status"] == "reported"]
    sig = {}
    for name, sel in [("check=1 (grounded on cited page)", lambda r: (r["p"]["check"] or 0) >= 1.0),
                      ("check<1", lambda r: (r["p"]["check"] or 0) < 1.0)]:
        s = [r for r in ans if sel(r)]
        sig[name] = f"{sum(r['outcome'] == 'correct' for r in s)}/{len(s)} correct"
    doc_pts = []
    for t, rs in targets.items():
        s = traces[t].get("signals") or {}
        doc_pts.append((s.get("completeness", 0), st.mean(r["outcome"] == "correct" for r in rs), f"{t[1]}:{t[0][:20]}"))
    flagged = [p for p in doc_pts if p[0] < 1.0]
    sig["targets with completeness<1"] = f"{len(flagged)} (their mean accuracy {round(st.mean(p[1] for p in flagged), 3) if flagged else '-'})"
    ok = [p for p in doc_pts if p[0] >= 1.0]
    sig["targets with completeness=1"] = f"{len(ok)} (their mean accuracy {round(st.mean(p[1] for p in ok), 3) if ok else '-'})"
    # ---- abstention curve (accuracy among answered vs coverage)
    answerable = [r for r in direct if r["g"]["status"] == "reported"]
    scored = sorted([(r["p"]["conf"] if r["p"] and r["p"]["status"] == "reported" else -1, r["outcome"] == "correct")
                     for r in answerable], reverse=True)
    curve = []
    for i in range(1, len(scored) + 1):
        if scored[i - 1][0] < 0:
            break
        curve.append((i / len(scored), sum(c for _, c in scored[:i]) / i, scored[i - 1][0]))
    # ---- latency / tokens by size
    lat = defaultdict(list)
    for t in traces.values():
        b = next(lbl for lim, lbl in SIZE_BUCKETS if t["pages"] <= lim)
        lat[b].append(t)
        lat["all"].append(t)
    lat_tbl = {}
    for b, ts in lat.items():
        lat_tbl[b] = dict(
            n=len(ts), p50_s=pctl([t["total_s"] for t in ts], .5), p95_s=pctl([t["total_s"] for t in ts], .95),
            **{f"{s}_mean_s": round(st.mean(t["stages"].get(s, 0) for t in ts), 3)
               for s in ("parse", "identify", "locate", "extract", "normalize")},
            in_tok_mean=round(st.mean(sum(c["input_tokens"] + c.get("cache_read_tokens", 0) + c.get("cache_write_tokens", 0)
                                          for c in t["llm_calls"]) for t in ts)),
            cached_tok_mean=round(st.mean(sum(c.get("cache_read_tokens", 0) for c in t["llm_calls"]) for t in ts)),
            out_tok_mean=round(st.mean(sum(c["output_tokens"] for c in t["llm_calls"]) for t in ts)),
            llm_calls_mean=round(st.mean(len(t["llm_calls"]) for t in ts), 2),
            usd_per_doc=round(st.mean(sum(call_cost(c) for c in t["llm_calls"]) for t in ts), 5))
    res_ok = res_n = 0
    rp = os.path.join(d, "resolved.csv")
    if os.path.exists(rp):
        resolved = {(r["fund"], r["share_class"], r["field"], r["period"]): fnum(r["value"])
                    for r in csv.DictReader(open(rp, encoding="utf-8"))}
        multi = defaultdict(set)
        for (f, fund, c, fld, per) in gt:
            multi[(fund, c, fld, per)].add(f)
        for k4, files in multi.items():
            if len(files) < 2 or k4[2] == "fee_waiver":
                continue
            gov = [gt[(f, *k4)] for f in files if gt[(f, *k4)].get("governs")]
            if not gov or gov[0]["value"] is None:
                continue
            res_n += 1
            res_ok += resolved.get(k4) is not None and abs(resolved[k4] - gov[0]["value"]) < TOL
    # utility at each threshold: +1 correct, -WRONG_COST wrong, -ABSTAIN_COST withheld/missed
    def utility(th):
        u = 0.0
        for r in answerable:
            p = r["p"]
            if p is None or p["status"] != "reported" or p["conf"] < th:
                u -= ABSTAIN_COST
            else:
                u += 1.0 if r["outcome"] == "correct" else -WRONG_COST
        return u / max(1, len(answerable))
    ths = sorted({0.0, thr} | {r["p"]["conf"] for r in answerable if r["p"] and r["p"]["status"] == "reported"})
    best_th = max(ths, key=lambda th: (utility(th), -th))
    # inception dates for since-inception keys
    inc_ok = inc_n = 0
    for r in direct:
        gi = r["g"].get("inception_date")
        if gi and r["g"]["status"] == "reported":
            inc_n += 1
            inc_ok += bool(r["p"]) and (r["p"].get("inception_date") or "")[:10] == gi
    correct = cats["correct"]
    return dict(
        utility=dict(wrong_cost=WRONG_COST, abstain_cost=ABSTAIN_COST, at_threshold=round(utility(thr), 3),
                     best_threshold=best_th, best_utility=round(utility(best_th), 3)),
        inception_dates=f"{inc_ok}/{inc_n}",
        resolution=f"{res_ok}/{res_n} keys present in 2+ documents resolved to the governing value",
        run=d, n_keys=n, end_to_end_accuracy=round(correct / n, 3) if n else 0,
        precision_answered=round(correct / max(1, n - cats["abstained"] - cats["missed"]), 3),
        coverage=round(1 - cats["abstained"] / max(1, n), 3),
        categories=dict(cats), first_failing_stage=dict(stages), examples=examples,
        per_stage=per_stage, derived_propagation={f"{a} -> {b}": v for (a, b), v in sorted(prop.items())},
        label_free_signal=sig, doc_signal_points=doc_pts, abstention_curve=curve, latency=lat_tbl,
        tokens_per_doc=lat_tbl["all"]["in_tok_mean"] + lat_tbl["all"]["out_tok_mean"],
        p95_s=lat_tbl["all"]["p95_s"])


def plots(results, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for i, r in enumerate(results):
        name = os.path.basename(r["run"])
        usd, acc, p95 = r["latency"]["all"]["usd_per_doc"], r["end_to_end_accuracy"], r["p95_s"]
        dy = 6 + 9 * (i % 3)                     # stagger labels so overlapping points stay readable
        ax1.scatter(usd, acc, s=60, alpha=.75)
        ax1.annotate(f"{name} ({r['tokens_per_doc']/1000:.1f}k tok)", (usd, acc), textcoords="offset points",
                     xytext=(6, -dy), fontsize=8)
        ax2.scatter(p95, acc, s=60, alpha=.75)
        ax2.annotate(name, (p95, acc), textcoords="offset points", xytext=(6, -dy), fontsize=8)
    ax1.set_xscale("log")
    ax1.set_xlabel("$ per document (log scale)")
    ax1.set_ylabel("end-to-end accuracy")
    ax1.set_title("Accuracy vs cost")
    ax2.axvline(LATENCY_TARGET_P95, ls="--", lw=1, color="gray")
    ax2.text(LATENCY_TARGET_P95, ax2.get_ylim()[0], " p95 target", fontsize=8, color="gray", va="bottom")
    ax2.set_xlabel("p95 latency, s (end to end)")
    ax2.set_title("Accuracy vs latency")
    fig.tight_layout()
    fig.savefig(os.path.join(out, "tradeoff.png"), dpi=150)
    fig, ax = plt.subplots(figsize=(6, 4))
    for r in results:
        c = r["abstention_curve"]
        ax.plot([x for x, _, _ in c], [y for _, y, _ in c], label=os.path.basename(r["run"]))
    ax.set_xlabel("coverage (share of answerable keys answered)")
    ax.set_ylabel("accuracy among answered")
    ax.set_title("Accuracy vs coverage (abstain on low confidence)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "abstention.png"), dpi=150)
    fig, ax = plt.subplots(figsize=(5, 4))
    for r in results:
        pts = r["doc_signal_points"]
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], label=os.path.basename(r["run"]), alpha=.7)
    ax.set_xlabel("grid completeness per target (no labels)")
    ax.set_ylabel("accuracy per target")
    ax.set_title("Label-free signal vs accuracy")
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(out, "signal.png"), dpi=150)


def to_md(results):
    L = ["# Evaluation report", ""]
    L += ["| run | keys | e2e acc | precision (answered) | coverage | tokens/doc | $/doc | p95 s | utility | best thr |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in results:
        L.append(f"| {os.path.basename(r['run'])} | {r['n_keys']} | {r['end_to_end_accuracy']} | "
                 f"{r['precision_answered']} | {r['coverage']} | {r['tokens_per_doc']} | "
                 f"{r['latency']['all']['usd_per_doc']} | {r['p95_s']} | {r['utility']['at_threshold']} | "
                 f"{r['utility']['best_threshold']} |")
    for r in results:
        L += ["", f"## {os.path.basename(r['run'])}", "", "**Outcome categories**: " + json.dumps(r["categories"]),
              "", "**First failing stage**: " + json.dumps(r["first_failing_stage"]),
              "", "**Per-stage**: " + json.dumps(r["per_stage"]),
              "", "**Derived (fee_waiver) propagation**: " + json.dumps(r["derived_propagation"]),
              "", "**Cross-document resolution**: " + r["resolution"],
              "", "**Inception dates (since-inception keys)**: " + r["inception_dates"],
              "", "**Utility**: " + json.dumps(r["utility"]),
              "", "**Label-free signal**: " + json.dumps(r["label_free_signal"]),
              "", "**Examples**:"] + [f"- {k}: {v}" for k, v in r["examples"].items()]
        L += ["", "| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        for b, v in r["latency"].items():
            L.append(f"| {b} | {v['n']} | {v['p50_s']} | {v['p95_s']} | {v['parse_mean_s']} | {v['identify_mean_s']} | "
                     f"{v['locate_mean_s']} | {v['extract_mean_s']} | {v['normalize_mean_s']} | {v['in_tok_mean']} | "
                     f"{v['out_tok_mean']} |")
    return "\n".join(L) + "\n"


def set_costs(wrong, abstain):
    global WRONG_COST, ABSTAIN_COST
    WRONG_COST, ABSTAIN_COST = wrong, abstain


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+")
    ap.add_argument("--gt", default="eval/ground_truth.csv")
    ap.add_argument("--threshold", type=float, default=COMMON["abstain_threshold"])
    ap.add_argument("--out", default="report")
    ap.add_argument("--wrong-cost", type=float, default=WRONG_COST, help="penalty for a wrong value")
    ap.add_argument("--abstain-cost", type=float, default=ABSTAIN_COST, help="penalty for a withheld/missed value")
    a = ap.parse_args()
    set_costs(a.wrong_cost, a.abstain_cost)
    gt = load_gt(a.gt)
    runs = [d for d in a.runs if os.path.getsize(os.path.join(d, "trace.jsonl")) > 0]
    for d in set(a.runs) - set(runs):
        print(f"skipping {d}: no successful targets in trace.jsonl")
    results = [evaluate_run(d, gt, a.threshold) for d in runs]
    os.makedirs(a.out, exist_ok=True)
    name = "-".join(os.path.basename(d.rstrip("/")) for d in a.runs)
    open(os.path.join(a.out, f"{name}.md"), "w").write(to_md(results))
    json.dump(results, open(os.path.join(a.out, f"{name}.json"), "w"), indent=1, default=str)
    plots(results, a.out)
    print(to_md(results))


if __name__ == "__main__":
    main()
