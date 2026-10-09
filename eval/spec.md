# Field specification

Applies to both the ground truth and the extractor. One output value per key
`(fund, share_class, field, period)`.

## Identification
- **Fund** = the manifest row's `(file, fund_name, ticker)`. The `fund` key is the manifest ticker. Values are taken
  only from the target fund's **summary section** (the block that starts at its "Investment Objective" heading).
  Tables belonging to any other fund in the same document are out of scope.
- **Share class** = the class label printed in the table header, canonicalized: lowercase, words "class"/"shares"
  removed (`Investor Class → investor`, `Class A → a`, `Admiral Shares → admiral`). A fund with one unlabeled
  class (typical ETF) is `single`.
- Target fund not found in the document → no rows for it, run log records `identify=not_found`.
  A class the target does not offer → no row (absence of a key, not a value).

## Fields
| field | definition | period |
|---|---|---|
| `gross_expense_ratio` | "Total annual fund operating expenses" row of the fee table (before waivers/reimbursements) | `current` |
| `net_expense_ratio` | "Total annual fund operating expenses after fee waiver and/or expense reimbursement" row. **If the fee table has no such row, net = gross** (no waiver exists). | `current` |
| `total_return_before_tax` | Average Annual Total Returns table, "Return Before Taxes" row of each class (or the class's only row if there is no tax split). Never after-tax rows, index rows, bar chart, or best/worst quarter. | one per column presented |
| `fee_waiver` (derived) | `gross_expense_ratio − net_expense_ratio`, same class | `current` |

## Periods
- Fee-table values: `current` = the expense ratios the prospectus presents as current, tied to that document's date.
- Returns: `<horizon>@<as_of>`, horizon ∈ {`1y`, `5y`, `10y`, `since_inception`}, `as_of` = the table's
  "for periods ended …" date (ISO). Since-inception rows also carry the class's `inception_date` when printed;
  classes of one fund may have different inception dates. Only horizons the table presents are keys.

## Units and signs
- `page` is the 1-based PDF page index (not the printed page label).
- All values are **percent points as printed** (0.55 means 0.55%), rounded as printed, no conversion to bps.
- Losses are negative; parentheses mean negative (`(0.55)` → −0.55). Fee waiver is reported positive
  (gross − net).
- Footnote markers (`a`, `b`, `*`, `†`) are ignored.

## Multiple candidates
- **Within one document:** the summary-section fee table and Average Annual Total Returns table are the only
  sources. Financial highlights, bar charts, and statutory "more about" sections are never used, even if they show
  the same field.
- **Across documents:** the document with the **latest cover date** (including "as revised/supplemented" dates)
  governs. Returns with different `as_of` dates are different keys, so in practice the rule only decides fee-table
  values. Same date → the higher-confidence value (the documents should agree; a disagreement is logged).

## Not reported vs zero
- Cell printed as `—`, `N/A`, `None` or blank for a class → `status=not_reported`, `value` empty.
- A printed `0.00` is a **reported zero** (`status=reported, value=0`). Example: T. Rowe Price Blue Chip Growth
  Z Class, net expense ratio 0.00 after a 0.55 waiver.
- `fee_waiver = 0` when net = gross (including the no-waiver-row rule) is a reported zero.
- `fee_waiver` with a missing input → `status=not_computable`.
- System output below the confidence threshold → `abstained` (the value is withheld; scored separately from wrong).
