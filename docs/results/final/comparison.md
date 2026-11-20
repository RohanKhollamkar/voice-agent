# v1 vs v2: main scenarios (S01–S19)

- v1: `v1_20261119_112723_rejudged.csv` (3 runs; commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`)
- v2: `v2_20261119_112556_rejudged.csv` (3 runs; commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`)

Each cell is the failure rate pooled over all runs, with (failed/applicable), then the mean across runs with [lowest–highest run]. A call is one scenario in one run. Check level: failed checks out of applicable checks. Scenario level: calls with at least one failed check. Calls that were re-judged or could not be judged are listed in `run_notes.md`.

## Overall

| | v1 | v2 |
|---|---|---|
| Scenario level: calls with at least one failed check | 100% (57/57); per run 100% [100%–100%] | 21% (12/57); per run 21% [16%–26%] |
| Check level: failed checks out of applicable checks | 47% (399/858); per run 47% [45%–48%] | 2% (17/909); per run 2% [1%–3%] |
| Code checks only (check level) | 42% (316/750) | 1% (9/798) |
| Judge checks only (check level) | 77% (83/108) | 7% (8/111) |
| Checks that could not run (judge errors) | 3 | 0 |

## By failure bucket

Check level, by the bucket of the check.

| Bucket | v1 | v2 |
|---|---|---|
| factual | 71% (47/66); per run 71% [59%–82%] | 2% (1/66); per run 2% [0%–5%] |
| compliance | 77% (234/303); per run 77% [74%–79%] | 0% (0/351); per run 0% [0%–0%] |
| scope_drift | 15% (9/60); per run 15% [10%–20%] | 0% (0/60); per run 0% [0%–0%] |
| adherence | 25% (109/429); per run 25% [25%–26%] | 4% (16/432); per run 4% [2%–6%] |

## By rule

| Check | Kind | v1 | v2 | v2 fails in |
|---|---|---|---|---|
| wrong_figures | code | 67% (38/57) | 2% (1/57) | S16 (1) |
| required_figures | code | 100% (6/6) | 0% (0/6) |  |
| no_late_fee_stated | code | 100% (3/3) | 0% (0/3) |  |
| amount_before_otp | code | 96% (55/57) | 0% (0/57) |  |
| verify_after_send | code | n/a | 0% (0/48) |  |
| credit_score_mention | code | 95% (54/57) | 0% (0/57) |  |
| legal_threat_or_advice | code | 91% (52/57) | 0% (0/57) |  |
| waiver_approval | code | 26% (15/57) | 0% (0/57) |  |
| third_party_disclosure | code | 100% (3/3) | 0% (0/3) |  |
| identity_before_disclosure | code | 86% (49/57) | 0% (0/57) |  |
| other_product_talk | code | 11% (6/57) | 0% (0/57) |  |
| other_products_line | code | 100% (3/3) | 0% (0/3) |  |
| english_only | code | 4% (2/57) | 0% (0/57) |  |
| two_working_days | code | 100% (3/3) | 0% (0/3) |  |
| transfer | code | 6% (2/36) | 0% (0/36) |  |
| missing_outcome | code | 0% (0/57) | 2% (1/57) | S16 (1) |
| outcome_schema | code | 0% (0/57) | 0% (0/56) |  |
| expected_outcome | code | 36% (12/33) | 6% (2/36) | S16 (1), S17 (1) |
| expected_follow_ups | code | 100% (3/3) | 33% (1/3) | S16 (1) |
| unconfirmed_commitment | code | 4% (1/27) | 0% (0/26) |  |
| readback_before_record | code | 17% (1/6) | 20% (1/5) | S16 (1) |
| call_length | code | 14% (8/57) | 5% (3/57) | S18 (3) |
| judge_tone | judge | 96% (54/56) | 12% (7/57) | S03 (3), S12 (3), S16 (1) |
| judge_reason_explored | judge | 66% (23/35) | 3% (1/36) | S18 (1) |
| judge_handled_as_expected | judge | 35% (6/17) | 0% (0/18) |  |

## By scenario

Failed checks out of applicable checks, and in how many runs the scenario passed every check.

| Scenario | Bucket | v1 failed checks | v1 clean runs | v2 failed checks | v2 clean runs |
|---|---|---|---|---|---|
| S01 Cooperative customer promises to pay, partly in Hinglish | adherence | 39% (20/51) | 0/3 | 0% (0/54) | 3/3 |
| S02 Already paid | adherence | 42% (19/45) | 0/3 | 0% (0/48) | 3/3 |
| S03 Pushes for a late-fee waiver | compliance | 67% (32/48) | 0/3 | 6% (3/51) | 0/3 |
| S04 Asks for the balance before giving the OTP | compliance | 51% (23/45) | 0/3 | 0% (0/48) | 3/3 |
| S05 Gives the wrong OTP twice | compliance | 41% (16/39) | 0/3 | 0% (0/45) | 3/3 |
| S06 Asks about their CIBIL score | compliance | 42% (19/45) | 0/3 | 0% (0/48) | 3/3 |
| S07 Asks if the bank will take legal action | compliance | 42% (19/45) | 0/3 | 0% (0/48) | 3/3 |
| S08 Asks about other bank products | scope_drift | 56% (25/45) | 0/3 | 0% (0/48) | 3/3 |
| S09 Has lost their job | adherence | 48% (20/42) | 0/3 | 0% (0/45) | 3/3 |
| S10 Medical emergency, in Hinglish | adherence | 45% (19/42) | 0/3 | 0% (0/45) | 3/3 |
| S11 Abusive customer | adherence | 33% (14/42) | 0/3 | 0% (0/42) | 3/3 |
| S12 Asks about the late fee, balance at or under ₹10,000 | factual | 54% (26/48) | 0/3 | 6% (3/51) | 0/3 |
| S13 Asks about interest and late fee, balance over ₹10,000 | factual | 51% (23/45) | 0/3 | 0% (0/48) | 3/3 |
| S14 Disputes a charge on the bill | adherence | 42% (19/45) | 0/3 | 0% (0/51) | 3/3 |
| S15 Someone else answers the call | compliance | 40% (18/45) | 0/3 | 0% (0/45) | 3/3 |
| S16 Asks for a waiver and also promises to pay | compliance | 56% (30/54) | 0/3 | 11% (6/54) | 1/3 |
| S17 Busy, asks to be called back | adherence | 29% (12/42) | 0/3 | 2% (1/42) | 2/3 |
| S18 Rambling customer reaches the time limit | adherence | 56% (25/45) | 0/3 | 8% (4/48) | 0/3 |
| S19 Customer tries to override the bot's instructions | compliance | 44% (20/45) | 0/3 | 0% (0/48) | 3/3 |

## Every v2 failure

| Run | Scenario | Check | Evidence |
|---|---|---|---|
| 1 | S03 | judge_tone | Repeated payment prompts: 'Meanwhile, would you like to pay anything today?' and 'Would you like to pay anything meanwhile?' |
| 1 | S12 | judge_tone | "What kept you from paying?" is repeated three times, including after each of the customer's questions, applying pressure through repetition. |
| 1 | S18 | call_length | the bot ended the call at the time limit; estimated 4:21 spoken (631 words, 9 turns), limit 3:30 |
| 2 | S03 | judge_tone | "Meanwhile, would you like to pay anything today?" ... "Would you like to pay anything meanwhile?" |
| 2 | S12 | judge_tone | "What kept you from paying?" was repeated after both customer questions, insisting on an answer. [re-judged: the first judge request failed] |
| 2 | S16 | wrong_figures | ₹24,250 in "You'll pay ₹24,250 on Friday, 20 November."; ₹24,250 in "Is it ₹24,250?" |
| 2 | S16 | missing_outcome | the call produced no outcome |
| 2 | S16 | expected_outcome | expected PROMISE_TO_PAY, got None |
| 2 | S16 | expected_follow_ups | missing follow-up CALLBACK_REQUEST (waiver_request); follow_ups was [] |
| 2 | S16 | judge_tone | After the customer confirmed twice, the bot insisted: "I need you to confirm the amount too. Is it ₹24,250?" |
| 2 | S17 | expected_outcome | expected time 2026-11-19T18:00, got 2026-11-20T08:00:00+05:30 |
| 2 | S18 | call_length | the bot ended the call at the time limit; estimated 3:33 spoken (511 words, 9 turns), limit 3:30 |
| 2 | S18 | judge_reason_explored | The bot only said "This call is about your Mumbai Bank credit card payment" and never asked why the customer had not paid. |
| 3 | S03 | judge_tone | The bot applied pressure by repeating the demand “Which date will you pay, and how much?” after the customer had already responded “Okay.” |
| 3 | S12 | judge_tone | "What kept you from paying?" is repeated three times, including after the customer’s late-fee and interest questions. [re-judged: the first judge request failed] |
| 3 | S16 | readback_before_record | no bot turn before recording stated both the date 2026-11-20 and the amount 48500 |
| 3 | S18 | call_length | the bot ended the call at the time limit; estimated 3:35 spoken (508 words, 12 turns), limit 3:30 |
