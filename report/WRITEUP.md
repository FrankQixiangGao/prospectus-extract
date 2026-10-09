# Fund Prospectus Extraction — Write-up

**System:** `identify → locate → extract (LLM) → normalize`. Only `extract` calls a model; everything else is
deterministic Python, so every stage emits an artifact that can be scored against ground truth.
**Data:** 13 PDFs, 7 fund families, 15 targets, 220 scored keys (186 labeled + 34 derived). Includes an
11-fund umbrella (Select Sector SPDR), 2–5 share classes, no-load ETFs, `—` cells, a reported 0.00 net expense
(T. Rowe Z class), and second-date documents for TRBCX and DODGX. Field definitions: `eval/spec.md`.

## 1. Fields and design choices

| field | type | varies by class | periods |
|---|---|---|---|
| `net_expense_ratio` | direct (fee table) | yes | current |
| `total_return_before_tax` | direct (Avg. Annual Total Returns) | yes | 1y / 5y / 10y / since inception, keyed with as-of date |
| `fee_waiver` = gross − net | derived | yes | current |

- **The LLM reads; code finds, converts, checks and decides.** The model copies `raw_value` verbatim; Python
  parses signs and units, computes the derived field, and applies the governing-document rule. Policy lives in
  `config.py`, not in prompts.
- **Locate makes token cost independent of document length.** Form N-1A fixes the table headings, so keyword
  anchors find them; 2–4 pages go to the model whether the PDF has 4 or 170 pages.
- **No embeddings.** In the umbrella document the 11 fee tables are near-identical except for the fund name;
  semantic retrieval would invite wrong-fund errors. Identify slices the target's section first
  (`Investment Objective` heading + fund name), so other funds' tables are never sent.
- **Fee waiver is derived, not read.** Dodge & Cox prints the waiver as `–0.05%` in 2026 and `0.05%` in 2025;
  gross − net is sign-stable.

## 2. Budgets and how they were derived

**Scenario:** an analyst uploads one prospectus and waits. **Latency target: p95 ≤ 10 s end to end** (PDF bytes →
final values, parsing included). 10 s is the usual limit for keeping a user's attention on a blocking wait; past it,
users switch tasks. **Token budget: ≤ 12k input, ≤ 4k output per document.** Derivation: 2 tables × up to 2 pages
× ~2.5k tokens/page + ~1.2k system prompt ≈ 11k; output: largest grid (5 classes × 6 values) ≈ 1k tokens, 4× headroom.
Pages beyond the budget are dropped lowest-rank first and logged.

**Measured (C1, iteration 3):** p95 **4.4 s**, mean **6.9k tokens/doc** (6.2k in incl. cached, 0.7k out). Both met.

| doc size | n | p50 s | p95 s | parse | identify | locate | extract | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|
| ≤20 pages | 8 | 3.34 | 5.32 | 0.03 | 0.00 | 0.00 | 3.16 | 6.7k | 0.87k |
| 21–100 | 1 | 2.25 | 2.25 | 0.13 | 0.00 | 0.00 | 2.12 | 4.6k | 0.58k |
| >100 pages | 6 | 2.08 | 3.79 | 0.40 | 0.00 | 0.00 | 1.91 | 5.8k | 0.44k |

**Large documents are not slower.** Latency follows *output* tokens, i.e. the number of share classes × periods,
not page count; parsing a 170-page PDF costs 0.4 s. Every LLM call is logged (`runs/*/trace.jsonl`): stage, model,
input / output / cache-read / cache-write tokens, wall-clock, stop reason.

## 3. Results

**Per-stage (C1, iteration 3):** identify found the right section 15/15 · locate surfaced the labeled page 186/186 ·
extraction given the correct page 186/186 · derived `fee_waiver` 34/34 · cross-document resolution (keys in 2+
documents → governing value) 52/52.

**Trade-off** (`report/tradeoff.png`):

| config | e2e accuracy | precision (answered) | tokens/doc | $/doc | p95 s |
|---|---|---|---|---|---|
| C1 Haiku, keyword locate | **100%** | 100% | 6.9k | $0.00086 | 4.4 |
| C2 Sonnet, keyword locate | 100% | 100% | 6.8k | $0.0172 | 8.4 |
| C3 Haiku, whole section (no locate) | 100% | 100% | 9.0k | $0.00107 | 5.0 |
| C1s C1 + one parallel call per table | 98.6% | 100% | 9.7k | $0.00107 | 3.7 |
| **C4 C1 + escalate to C3 when label-free checks fail** | **100%** | 100% | 7.6k | **$0.00096** | 5.5 |

Cost is computed from logged tokens (incl. cache reads/writes) at list prices. The whole 15-target run costs
about 1.5 cents on C4.

**Operating point: C4** (C1 by default; on a failed self-check, re-extract from the whole section). On this set it
escalated 1 of 15 targets (T. Rowe 2026, a false alarm caused by `—` cells): +10% tokens and p95 5.5 s vs C1's
4.4 s, both inside budget; the escalated document took 9.5 s, the closest any document came to the 10 s target. I pay that because the test set is unseen and
adversarial: the likeliest failure there is a table the keyword locate misses, which is exactly what the
completeness check catches (it flagged the one real failure we saw, C1s/XLK) and what C3 recovers. On this set
alone C1 is equally accurate and cheaper; the choice is a bet on generalization, bounded by the budget.

**Derived-field propagation.** Errors in `fee_waiver` came only from its inputs: in iteration 1, 2 missing Dodge &
Cox Class I net values → 2 waiver errors; with correct inputs, 34/34 waivers are correct. Confidence of a derived
value is the minimum of its inputs.

**Label-free quality signal.** *Grid completeness*: every share class seen should have gross, net, and every
return horizon seen for any class. Across C1-iter3, C2, C3, C1s, all **56 targets with completeness = 1 were 100%
correct** (no missed errors). Completeness < 1 flagged the real failure (C1s, XLK: 60% complete, 40% correct)
plus false alarms where a class legitimately shows `—` (T. Rowe Z class). False alarms cost only an escalation,
which is why C4 uses it as a trigger. The second signal, *grounding* (cited digits appear on the cited page),
never fired: no value was ever hallucinated. It cannot catch a correctly copied number under the wrong key.

**Abstention.** From iteration 2 on, every answered value was correct; all residual errors were omissions. So
accuracy-vs-coverage is flat on this set (`report/abstention.png`): abstaining buys nothing here. The mechanism
is in place (confidence = ½ model confidence + ½ verifiable checks; threshold 0.6), but this set cannot show the
curve's shape, and we do not claim it.

## 4. Iterations and failure taxonomy

| category (first failing stage) | iter 1 | iter 2 | iter 3 | example |
|---|---|---|---|---|
| as-of date unparsed → wrong period key (normalize) | 15 | 0 | 0 | IVV statutory p.7, Davis p.3 |
| net row skipped when waiver is "None" (extract) | 2 | 0 | 0 | Dodge & Cox 2026 p.2 |
| derived waiver wrong via input (propagated) | 2 | 1 | 0 | Dodge & Cox 2026 p.2 |
| malformed tool output → no values (extract) | 0 | 5 | 0 | XLU in SPDR umbrella p.87 |
| **end-to-end accuracy** | 91.4% | 97.3% | 100% | |
| since-inception date missing (extract → fixed in normalize, iter 4) | – | 6/10 missed | 0/10 | Artisan Mid Cap p.5 |

- **Iter 1 → 2:** both IVV and Davis put a bar-chart caption ("Period Ending") before the table header, and the
  parser stopped at the first match. Fix: scan every "periods ended" match; penalize confidence when no as-of is
  found. Prompt: net-row labels vary ("Net Expenses"); output it for every class when the row exists.
- **Iter 2 → 3:** the model occasionally returns the `values` array as a JSON string. Fix: coerce strings, drop
  malformed items, retry once on an empty result. **Caveat:** in the iteration-3 run the retry never fired; XLU
  succeeded on the first call. Part of 97.3% → 100% is run-to-run variance, not the fix. The retry did fire in
  the C1s run.
- **Iter 4:** after adding inception dates to the ground truth, 6 of 10 were missing: Artisan prints them in a
  separate "Inception Date" column the model skipped. Fix: if the model omits it, read the date off the value's own
  line (deterministic). C4: 10/10.

**Changes that did not help.**
1. **A bigger model (C2, Sonnet):** same accuracy, p95 8.4 s vs 4.4 s. Once the right page is selected, reading
   a table is not the bottleneck; selection and normalization are. Operational note: Sonnet rejects forced
   `tool_choice`, so the client now falls back to `auto` + instruction.
2. **Parallel per-table calls (C1s):** p95 −17%, but +40% tokens (system prompt and headers sent twice) and one
   umbrella target lost its fee values. Latency was already within budget, so this traded accuracy and cost for
   slack we did not need.

**Adversarial inputs.** Target not in the document → one `target_not_found` row and no LLM call (never another
fund's numbers); scanned PDF → `no_text_layer`. Business priorities are a CLI knob: `evaluate.py --wrong-cost 10`
scores utility (+1 correct, −w wrong, −1 withheld) and reports the utility-maximizing abstention threshold.

## 5. Limitations and what changes at scale

- **Ground truth** was drafted from each PDF's text layer by an AI assistant, independently of the pipeline's
  outputs, following `eval/spec.md`, with page numbers for every value. It has **not yet been fully
  human-verified**; agreement between an AI-drafted label set and an AI extractor is weaker evidence than
  hand labels, and the first thing I would do with more time is verify every `not_reported` row and a sample
  per document against the PDFs.
- 15 targets is a small set; 100% here is not a generalization claim. Untested: scanned PDFs (no OCR path),
  tables rendered as images, documents without N-1A section headings.
- **10k documents:** the per-document path parallelizes as-is; the changes are a queue with content-hash
  idempotency, a parse cache (umbrella documents serve many targets), results in Postgres keyed by
  `(fund, class, field, period, doc_id)` with the governing rule as a view, and monitoring by label-free signals
  per fund family plus sampled audits, since nobody labels 10k documents.
