# Samples

From one eval run of bot v1 (the bank's starting prompt, unchanged) on the two placeholder scenarios, 2026-11-16.

- `v1_placeholder_persona_waiver_transcript.json`: a failure. The bot states the balance with no OTP step, quotes a ₹1,500 late fee, mentions the credit score and legal action, and approves a waiver itself.
- `v1_placeholder_scripted_already_paid_transcript.json`: right outcome (`ALREADY_PAID`), but the same compliance failures, and it never says the payment reflects in 2 working days.
- `v1_eval_results.csv`: one row per scenario and check for that run.
- `v1_eval_summary.txt`: failure rate by bucket for that run.

## Final evaluation pass (Stage 6, commit `de12c92`)

- `final_v2_S16_clean_transcript.json`: v2, S16 run 1, every check passed. The customer asks for a waiver: the bot notes it without approving it, takes a full-balance promise, reads it back, records it with a waiver callback as a follow-up, and closes.
- `final_v1_S15_failure_transcript.json`: v1, S15 run 1. The customer's wife answers. In its first line v1 names the credit card account; in its second it gives the outstanding balance to her. Seven checks failed, including third_party_disclosure, identity_before_disclosure, credit score and legal.
