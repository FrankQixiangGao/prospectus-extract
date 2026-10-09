# prospectus-extract

Extract per-share-class numbers from mutual fund / ETF prospectuses, and prove how well it works.

> **TL;DR — C4 (operating point): 100% on 220 keys · ~$0.001 per document · p95 5.5 s end to end**
> (15 targets, 13 PDFs, 7 fund families; budget: p95 ≤ 10 s, ≤ 12k input tokens per document)

---

## 1. The idea in one line

**The LLM reads; code finds, converts, checks, and decides.**

```
PDF + (fund name, ticker)
   │
   ▼
[identify]   find the target fund's section          deterministic  (heading "Investment Objective" + fund name)
   ▼
[locate]     find the fee table + returns table        deterministic  (form-mandated headings, 2–4 pages)
   ▼
[extract]    read the tables → raw strings             the ONLY LLM call (Claude Haiku, tool use)
   ▼
[normalize]  parse, check, derive, resolve             deterministic  (signs, units, fee waiver, latest doc wins)
   │
   └─ C4: if self-checks fail → re-extract from the whole section (escalation, not default)
```

Why this shape:
- **Cost does not grow with page count.** 4 pages or 170 pages, the model sees 2–4 pages. Parsing 170 pages = 0.4 s.
- **Every stage is scorable**, so every error is attributed to the first stage that failed.
- **No embeddings.** An umbrella prospectus has 11 near-identical fee tables; semantic search invites wrong-fund errors.
- **Agent as escalation path, not default path.** Pay for the expensive path only when the cheap one looks wrong.

## 2. Fields (spec: `eval/spec.md`)

| field | where | varies by class | periods |
|---|---|---|---|
| `net_expense_ratio` | fee table | yes | current |
| `total_return_before_tax` | Average Annual Total Returns | yes | 1y / 5y / 10y / since inception, keyed by as-of date |
| `fee_waiver` (derived) | gross − net | yes | current |

Rules that matter: latest cover date governs across documents · `—` = not reported, `0.00` = reported zero ·
parentheses = negative · target not in document → `target_not_found` (never another fund's numbers).

## 3. Results

| config | accuracy | $/doc | p95 s | verdict |
|---|---|---|---|---|
| C1 Haiku + keyword locate | 100% | $0.00086 | 4.4 | cheapest |
| C2 Sonnet + keyword locate | 100% | $0.0172 | 8.4 | **didn't help**: 20× cost, 2× latency |
| C3 Haiku + whole section | 100% | $0.00107 | 5.0 | robust, pricier |
| C1s parallel per-table calls | 98.6% | $0.00107 | 3.7 | **didn't help**: faster but less accurate |
| **C4 C1 + escalate on failed checks** | **100%** | **$0.00096** | **5.5** | **chosen** |

Per stage (C4): identify 15/15 · locate 186/186 · extract given right page 186/186 · fee waiver 34/34 ·
cross-document resolution 52/52 · inception dates 10/10. Plot: `report/tradeoff.png`.

## 4. How we got there (failure-driven iterations)

| iteration | accuracy | what broke → fix |
|---|---|---|
| 1 | 91.4% | bar-chart caption hid the as-of date (15) · "Net Expenses" row skipped (2) |
| 2 | 97.3% | model sometimes returned the array as a JSON string → coerce + one retry |
| 3 | 100% | (honest: partly run-to-run variance; the retry didn't fire that run) |
| 4 | 100% + 10/10 dates | inception date in its own column was skipped → read it off the value's line |

**Label-free signal:** grid completeness (every class has every field/period seen). Completeness = 1 never hid an
error; it false-alarms on legitimate `—` cells, which only costs one escalation.

**Weakest evidence:** ground truth was AI-drafted from the text layer and not yet fully hand-verified.

## 5. Run it

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env                      # gitignored

python run.py <pdf_dir> <manifest.csv>                          # one command, default config = c4
python run.py sources sources/manifest.csv --dry-run            # identify + locate only, no API calls
python evaluate.py runs/c1 runs/c2 runs/c3-iter3 runs/c1s runs/c4   # metrics + plots → report/
```

Manifest: `file,fund_name,ticker`. Output in `runs/<config>/`: `predictions.csv` (per document), `resolved.csv`
(one value per key, latest document wins), `trace.jsonl` (stage timings, every LLM call with tokens incl. cache).

## 6. Live changes

| change | where |
|---|---|
| model / budget | `config.py` → `CONFIGS`, `COMMON` |
| new field | `config.py` → `FIELDS`, `FIELD_RANGES`, `FIELD_INSTRUCTIONS` (+ `TABLES` anchor if new table) |
| business priority | `python evaluate.py runs/c4 --wrong-cost 10` → best threshold → `COMMON["abstain_threshold"]` |
| compare before/after | `python run.py sources sources/manifest.csv --tag live` then `python evaluate.py runs/c4 runs/c4-live` |

## 7. Files

`pipeline.py` four stages · `config.py` all knobs · `run.py` CLI · `evaluate.py` scoring + plots ·
`eval/spec.md` field spec · `eval/ground_truth.csv` labels with pages · `report/WRITEUP.md` full write-up
