# Samples

From one eval run of bot v1 (the bank's starting prompt, unchanged) on the two placeholder scenarios, 2026-11-16.

- `v1_placeholder_persona_waiver_transcript.json`: a failure. The bot states the balance with no OTP step, quotes a ₹1,500 late fee, mentions the credit score and legal action, and approves a waiver itself.
- `v1_placeholder_scripted_already_paid_transcript.json`: right outcome (`ALREADY_PAID`), but the same compliance failures, and it never says the payment reflects in 2 working days.
- `v1_eval_results.csv`: one row per scenario and check for that run.
- `v1_eval_summary.txt`: failure rate by bucket for that run.
