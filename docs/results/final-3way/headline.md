# Headline numbers

Main set S01–S19, 2 runs per version; no held-out run. commit `1432ded`, judge `none (code checks only)`, clock `2026-11-16T11:00:00+05:30`.
v2.1's changes came from live voice tests, not from the held-out set.

|  | v1 | v2 | v2.1 |
|---|---|---|---|
| Main, scenario level (calls with any failed check) | 100% (38/38) | 5% (2/38) | 8% (3/38) |
| Main, check level (failed out of applicable) | 42% (212/500) | 0% (2/534) | 1% (3/534) |

Rules with 38 calls behind them in every version (failure rate):

| Rule | v1 | v2 | v2.1 |
|---|---|---|---|
| wrong_figures | 71% (27/38) | 0% (0/38) | 0% (0/38) |
| amount_before_otp | 92% (35/38) | 0% (0/38) | 0% (0/38) |
| credit_score_mention | 89% (34/38) | 0% (0/38) | 0% (0/38) |
| legal_threat_or_advice | 84% (32/38) | 0% (0/38) | 0% (0/38) |
| waiver_approval | 21% (8/38) | 0% (0/38) | 0% (0/38) |
| identity_before_disclosure | 95% (36/38) | 0% (0/38) | 0% (0/38) |
| other_product_talk | 11% (4/38) | 0% (0/38) | 0% (0/38) |
| english_only | 5% (2/38) | 0% (0/38) | 0% (0/38) |
| missing_outcome | 0% (0/38) | 0% (0/38) | 0% (0/38) |
| outcome_schema | 0% (0/38) | 0% (0/38) | 0% (0/38) |
| call_length | 29% (11/38) | 3% (1/38) | 5% (2/38) |
