# prospectus-extract

Extract per-share-class numbers from mutual fund / ETF prospectuses, with stage-wise evaluation,
abstention, and explicit latency/token budgets.

Pipeline: `identify → locate → extract (LLM) → normalize`. Only `extract` calls an LLM.

```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env            # .env is gitignored

python run.py <pdf_dir> <manifest.csv>                  # one command; default config c4 (operating point)
python run.py sources sources/manifest.csv --config c1 --dry-run   # identify+locate only, no API calls
python evaluate.py runs/c4 --gt eval/ground_truth.csv  # metrics, $ cost, plots -> report/
python evaluate.py runs/c4 --wrong-cost 10 --abstain-cost 1        # change the business priority
```

Manifest columns: `file,fund_name,ticker`. Outputs in `runs/<config>/`: `predictions.csv` (one value per key per
document), `resolved.csv` (one value per key across documents; latest cover date governs), `trace.jsonl`
(stage timings, every LLM call with tokens incl. cache, label-free signals).

| config | what it is |
|---|---|
| c1 | Haiku + keyword locate (2–4 pages) |
| c2 | Sonnet + keyword locate |
| c3 | Haiku + whole fund section (no locate) |
| c1s | c1 with one parallel call per table |
| **c4** | **c1, escalate to c3 when label-free checks fail (default)** |

Target not in the document → one row with `status=target_not_found` (no LLM call). Scanned PDF without a text
layer → `status=no_text_layer`.

**Live changes:** model or budget → `config.py` (`CONFIGS`, `COMMON`). New field → add to `FIELDS`,
`FIELD_RANGES`, describe it in `FIELD_INSTRUCTIONS`, and add a `TABLES` anchor if it lives outside the fee or
performance table. Business priority → `evaluate.py --wrong-cost/--abstain-cost` (reports the utility-maximizing
abstention threshold), then set `COMMON["abstain_threshold"]`.

Docs: `eval/spec.md` (field spec), `eval/ground_truth.csv`, `report/WRITEUP.md`.
