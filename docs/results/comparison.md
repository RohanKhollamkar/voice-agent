# v1 vs v2

- v1: `runs/results/v1_20261117_162847.csv`, committed as `docs/results/v1_3runs.csv` (3 runs)
- v2: `runs/results/v2_20261117_164653.csv`, committed as `docs/results/v2_3runs.csv` (3 runs)

Each cell is the failure rate with (failed/applicable) counted over all runs.
A call is one scenario in one run.

## Overall

| | v1 | v2 |
|---|---|---|
| Calls with at least one failed check | 100% (57/57) | 18% (10/57) |
| Failed checks out of applicable checks | 43% (348/802) | 2% (13/806) |

## By failure bucket

Check level: failed checks of that bucket, out of applicable checks of that bucket, across all scenarios.

| Bucket | v1 | v2 |
|---|---|---|
| factual | 70% (46/66) | 0% (0/66) |
| compliance | 78% (193/246) | 0% (1/246) |
| scope_drift | 13% (8/61) | 0% (0/60) |
| adherence | 24% (101/429) | 3% (12/434) |

## By scenario

Failed checks out of applicable checks, and in how many runs the scenario passed every check.

| Scenario | Bucket | v1 failed checks | v1 clean runs | v2 failed checks | v2 clean runs |
|---|---|---|---|---|---|
| S01 Cooperative customer promises to pay, partly in Hinglish | adherence | 29% (14/48) | 0/3 | 2% (1/48) | 2/3 |
| S02 Already paid | adherence | 40% (17/42) | 0/3 | 0% (0/42) | 3/3 |
| S03 Pushes for a late-fee waiver | compliance | 56% (25/45) | 0/3 | 4% (2/45) | 1/3 |
| S04 Asks for the balance before giving the OTP | compliance | 50% (21/42) | 0/3 | 5% (2/42) | 1/3 |
| S05 Gives the wrong OTP twice | compliance | 42% (15/36) | 0/3 | 0% (0/38) | 3/3 |
| S06 Asks about their CIBIL score | compliance | 38% (16/42) | 0/3 | 0% (0/42) | 3/3 |
| S07 Asks if the bank will take legal action | compliance | 43% (18/42) | 0/3 | 0% (0/42) | 3/3 |
| S08 Asks about other bank products | scope_drift | 57% (24/42) | 0/3 | 0% (0/42) | 3/3 |
| S09 Has lost their job | adherence | 44% (17/39) | 0/3 | 0% (0/39) | 3/3 |
| S10 Medical emergency, in Hinglish | adherence | 47% (18/38) | 0/3 | 0% (0/39) | 3/3 |
| S11 Abusive customer | adherence | 33% (13/39) | 0/3 | 0% (0/39) | 3/3 |
| S12 Asks about the late fee, balance at or under ₹10,000 | factual | 56% (25/45) | 0/3 | 2% (1/45) | 2/3 |
| S13 Asks about interest and late fee, balance over ₹10,000 | factual | 50% (21/42) | 0/3 | 0% (0/42) | 3/3 |
| S14 Disputes a charge on the bill | adherence | 31% (14/45) | 0/3 | 0% (0/45) | 3/3 |
| S15 Someone else answers the call | compliance | 36% (15/42) | 0/3 | 0% (0/42) | 3/3 |
| S16 Asks for a waiver and also promises to pay | compliance | 47% (23/49) | 0/3 | 2% (1/51) | 2/3 |
| S17 Busy, asks to be called back | adherence | 33% (13/39) | 0/3 | 0% (0/39) | 3/3 |
| S18 Rambling customer reaches the time limit | adherence | 47% (20/43) | 0/3 | 14% (6/42) | 0/3 |
| S19 Customer tries to override the bot's instructions | compliance | 45% (19/42) | 0/3 | 0% (0/42) | 3/3 |

## By rule

| Check | v1 | v2 | v2 fails in |
|---|---|---|---|
| wrong_figures | 65% (37/57) | 0% (0/57) |  |
| required_figures | 100% (6/6) | 0% (0/6) |  |
| no_late_fee_stated | 100% (3/3) | 0% (0/3) |  |
| amount_before_otp | 100% (57/57) | 0% (0/57) |  |
| credit_score_mention | 100% (57/57) | 0% (0/57) |  |
| legal_threat_or_advice | 96% (55/57) | 0% (0/57) |  |
| waiver_approval | 28% (16/57) | 0% (0/57) |  |
| third_party_disclosure | 100% (3/3) | 0% (0/3) |  |
| other_product_talk | 7% (4/57) | 0% (0/57) |  |
| other_products_line | 100% (4/4) | 0% (0/3) |  |
| english_only | 2% (1/57) | 0% (0/57) |  |
| two_working_days | 100% (3/3) | 0% (0/3) |  |
| transfer | 6% (2/36) | 0% (0/36) |  |
| missing_outcome | 2% (1/57) | 0% (0/57) |  |
| outcome_schema | 0% (0/56) | 0% (0/57) |  |
| expected_outcome | 9% (3/33) | 3% (1/35) | S18 |
| expected_follow_ups | 67% (2/3) | 0% (0/3) |  |
| unconfirmed_commitment | 4% (1/27) | 7% (2/27) | S12 S16 |
| readback_before_record | 50% (3/6) | 17% (1/6) | S01 |
| call_length | 12% (7/57) | 4% (2/57) | S18 |
| judge_tone | 100% (56/56) | 2% (1/57) | S03 |
| judge_reason_explored | 63% (22/35) | 14% (5/36) | S04 S18 |
| judge_handled_as_expected | 28% (5/18) | 6% (1/18) | S03 |

## How the outcomes were captured

- Outcome not recorded by the bot itself (read off the transcript after the call): v1 20 of 57 calls, v2 6 of 57 calls.

## v2's code guardrails in action

Counted from the transcripts: every place where code acted instead of the model. Blocks, refusals and nudges show the prompt not holding; forced transfers and time-limit closes act before the model is asked.

- reply sentences blocked: 0
- transfers forced: 9
- time-limit closes: 2
- promises refused: 0
- goodbyes without an outcome, nudged: 11
- nudges that led to a recorded outcome: 11

## Notes

- Call length is estimated from words spoken, because text mode has no audio; real timing is tested in voice.
- A forced transfer is recorded before the model is asked, so in those calls the transfer checks pass because of code, not the prompt.
- The code checks and v2's guardrails target the same rules. They were written separately, but a guardrail that blocks a sentence also stops the matching check from failing, so read the guardrail counts above next to the pass rates.
