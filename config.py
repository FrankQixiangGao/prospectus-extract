"""All tunable knobs live here. A live requirement change should be an edit to this file."""

# ---- Pipeline configurations compared in the trade-off study ----
CONFIGS = {
    # C1: keyword locate, small model, one LLM call per target
    "c1": dict(model="claude-haiku-5-5", locate="keyword", split_calls=False),
    # C2: same pipeline, larger model
    "c2": dict(model="claude-sonnet-5-5", locate="keyword", split_calls=False),
    # C3: skip locate, send the whole fund section to the small model
    "c3": dict(model="claude-haiku-5-5", locate="section", split_calls=False),
    # C1-split: C1 with one parallel call per table (latency experiment)
    "c1s": dict(model="claude-haiku-5-5", locate="keyword", split_calls=True),
}

COMMON = dict(
    max_section_pages=15,       # cap on the target fund's section length
    max_pages_section_mode=12,  # pages sent to the LLM in C3
    max_input_tokens=12_000,    # per-document input budget (keyword mode)
    max_input_tokens_section=40_000,
    max_output_tokens=4_000,
    abstain_threshold=0.6,      # final output abstains below this confidence
)

# ---- Locate: anchors (must appear) and cues (table-like words that raise a page's score) ----
TABLES = {
    "fees": dict(
        anchors=[r"annual\s+fund\s+operating\s+expenses", r"fees\s+and\s+expenses\s+of\s+the\s+fund"],
        cues=[r"management\s+fees?", r"other\s+expenses", r"total\s+annual\s+(fund\s+)?operating\s+expenses",
              r"fee\s+waiver", r"expense\s+reimbursement", r"12b-1"],
    ),
    "performance": dict(
        anchors=[r"average\s+annual\s+total\s+returns?"],
        cues=[r"return\s+before\s+taxes", r"\b(1|one)[\s-]+year", r"\b(5|five)[\s-]+years?", r"\b(10|ten)[\s-]+years?",
              r"since\s+inception", r"periods?\s+end(ed|ing)"],
    ),
}

# ---- Fields: what the extractor is told (the field spec, condensed) ----
FIELD_INSTRUCTIONS = """
Extract these values for the TARGET fund only, for EVERY share class of the target fund shown in the tables.

1. gross_expense_ratio (period "current"): the "Total annual fund operating expenses" row, i.e. BEFORE any
   fee waiver / expense reimbursement.
2. net_expense_ratio (period "current"): the row AFTER fee waiver and/or expense reimbursement (labels vary:
   "Total annual fund operating expenses after fee waiver...", "Net Expenses", "Net annual operating expenses").
   ONLY output it if such a row exists. If it exists, output it for EVERY class, including classes whose
   waiver cell is "None" or "—".
3. total_return_before_tax: from the "Average Annual Total Returns" table, the "Return Before Taxes" row for
   each share class (if the table has no before/after-tax split, the share class's own row).
   NEVER use after-tax rows, index/benchmark rows, the bar chart, or best/worst quarter figures.
   One value per column the table presents: period "1y", "5y", "10y", or "since_inception".
   For since_inception, also give the inception_date if printed (YYYY-MM-DD).

Rules:
- raw_value: copy the cell EXACTLY as printed (e.g. "0.70", "(0.55)", "-12.31%", "—"). Do not compute anything.
- If a cell is blank or shows a dash / N/A for that class, still output the row with raw_value as printed.
- page: the page number from the "=== PAGE n ===" marker where the value is printed.
- share_class: as printed in the column/row header (e.g. "Investor Class", "Class A", "Admiral Shares").
  If the fund has a single unlabeled class (typical for ETFs), use "single".
- confidence: your probability (0-1) that the value is correct for this exact class, field and period.
- Ignore every fund other than the target, even if its tables are on the same pages.
"""
