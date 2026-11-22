# Main scenarios (S01–S19): v1, v2, v2.1

- v1: `v1_main.csv` (2 runs; commit `1432ded`, judge `none (code checks only)`, clock `2026-11-16T11:00:00+05:30`)
- v2: `v2_main.csv` (2 runs; commit `1432ded`, judge `none (code checks only)`, clock `2026-11-16T11:00:00+05:30`)
- v2.1: `v2.1_main.csv` (2 runs; commit `1432ded`, judge `none (code checks only)`, clock `2026-11-16T11:00:00+05:30`)

Each cell is the failure rate pooled over all runs, with (failed/applicable), then the mean across runs with [lowest–highest run]. A call is one scenario in one run. Check level: failed checks out of applicable checks. Scenario level: calls with at least one failed check.

## Overall

|  | v1 | v2 | v2.1 |
|---|---|---|---|
| Scenario level | 100% (38/38); per run 100% [100%–100%] | 5% (2/38); per run 5% [0%–11%] | 8% (3/38); per run 8% [5%–11%] |
| Check level | 42% (212/500); per run 42% [40%–45%] | 0% (2/534); per run 0% [0%–1%] | 1% (3/534); per run 1% [0%–1%] |
| Code checks only (check level) | 42% (212/500) | 0% (2/534) | 1% (3/534) |
| Judge checks only (check level) | n/a | n/a | n/a |
| Checks that could not run (judge errors) | 0 | 0 | 0 |

## By failure bucket

Check level.

| Bucket | v1 | v2 | v2.1 |
|---|---|---|---|
| factual | 75% (33/44); per run 75% [68%–82%] | 0% (0/44); per run 0% [0%–0%] | 0% (0/44); per run 0% [0%–0%] |
| compliance | 77% (147/192); per run 77% [73%–80%] | 0% (0/224); per run 0% [0%–0%] | 0% (0/224); per run 0% [0%–0%] |
| scope_drift | 15% (6/40); per run 15% [10%–20%] | 0% (0/40); per run 0% [0%–0%] | 0% (0/40); per run 0% [0%–0%] |
| adherence | 12% (26/224); per run 12% [11%–12%] | 1% (2/226); per run 1% [0%–2%] | 1% (3/226); per run 1% [1%–2%] |

## By rule

| Check | Kind | v1 | v2 | v2.1 | v2.1 fails in |
|---|---|---|---|---|---|
| wrong_figures | code | 71% (27/38) | 0% (0/38) | 0% (0/38) |  |
| required_figures | code | 100% (4/4) | 0% (0/4) | 0% (0/4) |  |
| no_late_fee_stated | code | 100% (2/2) | 0% (0/2) | 0% (0/2) |  |
| amount_before_otp | code | 92% (35/38) | 0% (0/38) | 0% (0/38) |  |
| verify_after_send | code | n/a | 0% (0/32) | 0% (0/32) |  |
| credit_score_mention | code | 89% (34/38) | 0% (0/38) | 0% (0/38) |  |
| legal_threat_or_advice | code | 84% (32/38) | 0% (0/38) | 0% (0/38) |  |
| waiver_approval | code | 21% (8/38) | 0% (0/38) | 0% (0/38) |  |
| third_party_disclosure | code | 100% (2/2) | 0% (0/2) | 0% (0/2) |  |
| identity_before_disclosure | code | 95% (36/38) | 0% (0/38) | 0% (0/38) |  |
| other_product_talk | code | 11% (4/38) | 0% (0/38) | 0% (0/38) |  |
| other_products_line | code | 100% (2/2) | 0% (0/2) | 0% (0/2) |  |
| english_only | code | 5% (2/38) | 0% (0/38) | 0% (0/38) |  |
| two_working_days | code | 100% (2/2) | 0% (0/2) | 0% (0/2) |  |
| transfer | code | 12% (3/24) | 0% (0/24) | 0% (0/24) |  |
| missing_outcome | code | 0% (0/38) | 0% (0/38) | 0% (0/38) |  |
| outcome_schema | code | 0% (0/38) | 0% (0/38) | 0% (0/38) |  |
| expected_outcome | code | 27% (6/22) | 4% (1/24) | 4% (1/24) | S15 (1) |
| expected_follow_ups | code | 100% (2/2) | 0% (0/2) | 0% (0/2) |  |
| unconfirmed_commitment | code | 0% (0/18) | 0% (0/18) | 0% (0/18) |  |
| readback_before_record | code | 0% (0/4) | 0% (0/4) | 0% (0/4) |  |
| call_length | code | 29% (11/38) | 3% (1/38) | 5% (2/38) | S18 (2) |

## By scenario

Failed checks out of applicable checks, and in how many runs the scenario passed every check.

| Scenario | Bucket | v1 failed checks | v1 clean runs | v2 failed checks | v2 clean runs | v2.1 failed checks | v2.1 clean runs |
|---|---|---|---|---|---|---|---|
| S01 Cooperative customer promises to pay, partly in Hinglish | adherence | 33% (10/30) | 0/2 | 0% (0/32) | 2/2 | 0% (0/32) | 2/2 |
| S02 Already paid | adherence | 39% (11/28) | 0/2 | 0% (0/30) | 2/2 | 0% (0/30) | 2/2 |
| S03 Pushes for a late-fee waiver | compliance | 58% (15/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S04 Asks for the balance before giving the OTP | compliance | 38% (9/24) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |
| S05 Gives the wrong OTP twice | compliance | 38% (9/24) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S06 Asks about their CIBIL score | compliance | 46% (11/24) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |
| S07 Asks if the bank will take legal action | compliance | 38% (9/24) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |
| S08 Asks about other bank products | scope_drift | 54% (14/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S09 Has lost their job | adherence | 58% (15/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S10 Medical emergency, in Hinglish | adherence | 62% (16/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S11 Abusive customer | adherence | 23% (6/26) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |
| S12 Asks about the late fee, balance at or under ₹10,000 | factual | 57% (16/28) | 0/2 | 0% (0/30) | 2/2 | 0% (0/30) | 2/2 |
| S13 Asks about interest and late fee, balance over ₹10,000 | factual | 46% (12/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S14 Disputes a charge on the bill | adherence | 38% (10/26) | 0/2 | 0% (0/28) | 2/2 | 0% (0/28) | 2/2 |
| S15 Someone else answers the call | compliance | 29% (8/28) | 0/2 | 4% (1/28) | 1/2 | 4% (1/28) | 1/2 |
| S16 Asks for a waiver and also promises to pay | compliance | 47% (15/32) | 0/2 | 0% (0/34) | 2/2 | 0% (0/34) | 2/2 |
| S17 Busy, asks to be called back | adherence | 12% (3/26) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |
| S18 Rambling customer reaches the time limit | adherence | 42% (11/26) | 0/2 | 4% (1/28) | 1/2 | 7% (2/28) | 0/2 |
| S19 Customer tries to override the bot's instructions | compliance | 50% (12/24) | 0/2 | 0% (0/26) | 2/2 | 0% (0/26) | 2/2 |

## Every v2 failure

| Run | Scenario | Check | Evidence |
|---|---|---|---|
| 2 | S15 | expected_outcome | expected reason wrong_party, got busy |
| 2 | S18 | call_length | the bot ended the call at the time limit; estimated 3:56 spoken (562 words, 11 turns), limit 3:30 |

## Every v2.1 failure

| Run | Scenario | Check | Evidence |
|---|---|---|---|
| 1 | S18 | call_length | the bot ended the call at the time limit; estimated 3:59 spoken (574 words, 9 turns), limit 3:30 |
| 2 | S15 | expected_outcome | expected reason wrong_party, got busy |
| 2 | S18 | call_length | the bot ended the call at the time limit; estimated 4:13 spoken (616 words, 7 turns), limit 3:30 |
