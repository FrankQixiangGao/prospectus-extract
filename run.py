"""Run the pipeline on a directory of PDFs + manifest.

    python run.py sources sources/manifest.csv --config c1
    python run.py sources sources/manifest.csv --config c1 --dry-run   # identify+locate only, no API calls

Writes runs/<config>/predictions.csv (one value per key per document), resolved.csv (one value per key
across documents), and trace.jsonl (stage timings, pages, every LLM call).
"""
import argparse
import csv
import json
import os

from config import COMMON, CONFIGS
from pipeline import resolve, run_target

COLS = ["file", "doc_date", "fund", "share_class", "field", "period", "value", "status", "confidence",
        "abstained", "page", "raw_value", "inception_date", "llm_conf", "check", "grounded"]


def load_dotenv(path=".env"):
    """Read KEY=VALUE lines from .env (gitignored) so the API key never lives in code."""
    if os.path.exists(path):
        for line in open(path):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip().removeprefix("export ").strip()
                if not os.environ.get(k):          # an empty exported var must not shadow .env
                    os.environ[k] = v.strip().strip('"').strip("'")


def main():
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf_dir")
    ap.add_argument("manifest")
    ap.add_argument("--config", default="c1", choices=sorted(CONFIGS))
    ap.add_argument("--out", default="runs")
    ap.add_argument("--tag", default="", help="suffix for the run folder, e.g. iter2")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not a.dry_run and not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY not set: put 'ANTHROPIC_API_KEY=sk-ant-...' in .env (project root)")
    cfg = CONFIGS[a.config]
    out_dir = os.path.join(a.out, a.config + (f"-{a.tag}" if a.tag else ""))
    os.makedirs(out_dir, exist_ok=True)
    manifest = list(csv.DictReader(open(a.manifest, encoding="utf-8")))

    all_rows, traces = [], []
    for i, m in enumerate(manifest, 1):
        try:
            rows, meta = run_target(os.path.join(a.pdf_dir, m["file"]), m["fund_name"], m["ticker"], cfg, a.dry_run)
        except Exception as e:                     # one bad document must not kill the batch
            print(f"[{i}/{len(manifest)}] {m['ticker']} FAILED: {type(e).__name__}: {e}")
            continue
        meta["config"] = a.config
        traces.append(meta)
        all_rows += rows
        toks = sum(c["input_tokens"] + c["output_tokens"] for c in meta["llm_calls"])
        print(f"[{i}/{len(manifest)}] {m['ticker']:6} {meta['file'][:42]:42} section={meta['section']['start']}-"
              f"{meta['section']['end']} pages={meta['located']} values={len(rows)} {meta['total_s']:.1f}s {toks} tok")

    thr = COMMON["abstain_threshold"]
    for r in all_rows:
        r["abstained"] = r["status"] == "reported" and r["confidence"] < thr

    with open(os.path.join(out_dir, "trace.jsonl"), "w") as f:
        for t in traces:
            f.write(json.dumps(t) + "\n")
    for name, rows in [("predictions.csv", all_rows), ("resolved.csv", resolve(all_rows))]:
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=COLS, extrasaction="ignore")
            w.writeheader()
            w.writerows(sorted(rows, key=lambda r: (r["fund"], r["file"], r["field"], r["share_class"], r["period"])))
    print(f"wrote {out_dir}/")


if __name__ == "__main__":
    main()
