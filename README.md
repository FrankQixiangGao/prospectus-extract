# prospectus-extract

Extract per-share-class numbers from mutual fund / ETF prospectuses, with stage-wise evaluation,
abstention, and explicit latency/token budgets.

Pipeline: `identify → locate → extract (LLM) → normalize`. Only `extract` calls an LLM.

```bash
pip install -r requirements.txt
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env   # .env is gitignored
python run.py sources sources/manifest.csv --config c1          # one command: PDFs + manifest -> values
python run.py sources sources/manifest.csv --config c1 --dry-run   # identify+locate only, no API calls
python evaluate.py runs/c1 eval/ground_truth.csv                # metrics + plots
```

Outputs in `runs/<config>/`: `predictions.csv` (one value per key per document), `resolved.csv`
(one value per key across documents), `trace.jsonl` (stage timings + every LLM call).

Configs (`config.py`): `c1` Haiku + keyword locate, `c2` Sonnet + keyword locate, `c3` Haiku + whole section.
