# Evaluation report

| run | keys | e2e acc | precision (answered) | coverage | tokens/doc | p95 s |
|---|---|---|---|---|---|---|
| c1-iter3 | 220 | 1.0 | 1.0 | 1.0 | 6911 | 4.405 |
| c2 | 220 | 1.0 | 1.0 | 1.0 | 6834 | 8.396 |
| c3-iter3 | 220 | 1.0 | 1.0 | 1.0 | 9034 | 5.018 |
| c1s | 220 | 0.986 | 1.0 | 1.0 | 9704 | 3.657 |
| c4 | 220 | 1.0 | 1.0 | 1.0 | 7816 | 5.417 |

## c1-iter3

**Outcome categories**: {"correct": 220, "spurious_key": 0}

**First failing stage**: {}

**Per-stage**: {"identify_section_correct": "15/15", "locate_page_recall": "186/186", "extract_accuracy_given_correct_page": "186/186"}

**Derived (fee_waiver) propagation**: {"inputs_wrong=0 -> waiver_correct": 34}

**Cross-document resolution**: 52/52 keys present in 2+ documents resolved to the governing value

**Label-free signal**: {"check=1 (grounded on cited page)": "174/174 correct", "check<1": "0/0 correct", "targets with completeness<1": "1 (their mean accuracy 1)", "targets with completeness=1": "14 (their mean accuracy 1)"}

**Examples**:

| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|
| large (>100p) | 6 | 2.075 | 3.787 | 0.402 | 0.001 | 0.001 | 1.905 | 0.001 | 5818 | 439 |
| all | 15 | 2.252 | 4.405 | 0.188 | 0.001 | 0.001 | 2.588 | 0.001 | 6232 | 679 |
| small (<=20p) | 8 | 3.338 | 5.319 | 0.034 | 0.0 | 0.001 | 3.159 | 0.001 | 6744 | 871 |
| medium (21-100p) | 1 | 2.252 | 2.252 | 0.13 | 0.0 | 0.001 | 2.119 | 0.001 | 4609 | 581 |

## c2

**Outcome categories**: {"correct": 220, "spurious_key": 0}

**First failing stage**: {}

**Per-stage**: {"identify_section_correct": "15/15", "locate_page_recall": "186/186", "extract_accuracy_given_correct_page": "186/186"}

**Derived (fee_waiver) propagation**: {"inputs_wrong=0 -> waiver_correct": 34}

**Cross-document resolution**: 52/52 keys present in 2+ documents resolved to the governing value

**Label-free signal**: {"check=1 (grounded on cited page)": "174/174 correct", "check<1": "0/0 correct", "targets with completeness<1": "0 (their mean accuracy -)", "targets with completeness=1": "15 (their mean accuracy 1)"}

**Examples**:

| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|
| large (>100p) | 6 | 2.472 | 5.973 | 0.408 | 0.001 | 0.001 | 2.868 | 0.001 | 5712 | 476 |
| all | 15 | 3.174 | 8.396 | 0.188 | 0.001 | 0.001 | 3.771 | 0.001 | 6125 | 709 |
| small (<=20p) | 8 | 4.618 | 8.397 | 0.031 | 0.0 | 0.001 | 4.54 | 0.001 | 6637 | 904 |
| medium (21-100p) | 1 | 3.174 | 3.174 | 0.128 | 0.0 | 0.001 | 3.045 | 0.0 | 4502 | 540 |

## c3-iter3

**Outcome categories**: {"correct": 220, "spurious_key": 0}

**First failing stage**: {}

**Per-stage**: {"identify_section_correct": "15/15", "locate_page_recall": "186/186", "extract_accuracy_given_correct_page": "186/186"}

**Derived (fee_waiver) propagation**: {"inputs_wrong=0 -> waiver_correct": 34}

**Cross-document resolution**: 52/52 keys present in 2+ documents resolved to the governing value

**Label-free signal**: {"check=1 (grounded on cited page)": "171/171 correct", "check<1": "3/3 correct", "targets with completeness<1": "1 (their mean accuracy 1)", "targets with completeness=1": "14 (their mean accuracy 1)"}

**Examples**:

| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|
| large (>100p) | 6 | 1.957 | 3.787 | 0.398 | 0.001 | 0.0 | 1.957 | 0.0 | 8356 | 443 |
| all | 15 | 2.454 | 5.018 | 0.184 | 0.001 | 0.0 | 2.596 | 0.0 | 8349 | 685 |
| small (<=20p) | 8 | 3.146 | 5.506 | 0.032 | 0.0 | 0.0 | 3.108 | 0.0 | 8486 | 880 |
| medium (21-100p) | 1 | 2.454 | 2.454 | 0.121 | 0.0 | 0.0 | 2.332 | 0.0 | 7212 | 581 |

## c1s

**Outcome categories**: {"correct": 217, "missed": 3, "spurious_key": 0}

**First failing stage**: {"extract": 2, "propagated_from_inputs": 1}

**Per-stage**: {"identify_section_correct": "15/15", "locate_page_recall": "186/186", "extract_accuracy_given_correct_page": "184/186"}

**Derived (fee_waiver) propagation**: {"inputs_wrong=0 -> waiver_correct": 33, "inputs_wrong=2 -> waiver_wrong": 1}

**Cross-document resolution**: 52/52 keys present in 2+ documents resolved to the governing value

**Label-free signal**: {"check=1 (grounded on cited page)": "169/169 correct", "check<1": "3/3 correct", "targets with completeness<1": "2 (their mean accuracy 0.8)", "targets with completeness=1": "13 (their mean accuracy 1)"}

**Examples**:
- missed: statestreet_XLC_statutory_2026-01-31.pdf p.79 single/gross_expense_ratio/current

| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|
| large (>100p) | 6 | 1.957 | 3.406 | 0.408 | 0.001 | 0.001 | 1.886 | 0.0 | 8878 | 624 |
| all | 15 | 2.047 | 3.657 | 0.191 | 0.001 | 0.001 | 2.214 | 0.0 | 8880 | 824 |
| small (<=20p) | 8 | 2.94 | 3.991 | 0.037 | 0.0 | 0.002 | 2.497 | 0.001 | 9230 | 996 |
| medium (21-100p) | 1 | 2.047 | 2.047 | 0.128 | 0.0 | 0.001 | 1.917 | 0.0 | 6085 | 654 |

## c4

**Outcome categories**: {"correct": 220, "spurious_key": 0}

**First failing stage**: {}

**Per-stage**: {"identify_section_correct": "15/15", "locate_page_recall": "186/186", "extract_accuracy_given_correct_page": "186/186"}

**Derived (fee_waiver) propagation**: {"inputs_wrong=0 -> waiver_correct": 34}

**Cross-document resolution**: 52/52 keys present in 2+ documents resolved to the governing value

**Label-free signal**: {"check=1 (grounded on cited page)": "174/174 correct", "check<1": "0/0 correct", "targets with completeness<1": "1 (their mean accuracy 1)", "targets with completeness=1": "14 (their mean accuracy 1)"}

**Examples**:

| size | n | p50 s | p95 s | parse | identify | locate | extract | normalize | in tok | out tok |
|---|---|---|---|---|---|---|---|---|---|---|
| large (>100p) | 6 | 2.491 | 3.991 | 0.406 | 0.001 | 0.001 | 2.22 | 0.001 | 6529 | 488 |
| all | 15 | 2.879 | 5.417 | 0.191 | 0.001 | 0.001 | 2.942 | 0.001 | 7049 | 767 |
| small (<=20p) | 8 | 3.23 | 8.783 | 0.037 | 0.0 | 0.002 | 3.591 | 0.001 | 7744 | 1007 |
| medium (21-100p) | 1 | 2.218 | 2.218 | 0.135 | 0.0 | 0.001 | 2.081 | 0.0 | 4609 | 526 |
