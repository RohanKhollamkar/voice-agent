# Held-out scenarios (H01–H05)

A test set v2 was never changed for: the scenarios were added after v2 was frozen and run once per version. These numbers are kept apart from the main comparison.

- v1: `v1_heldout_20261119_114041.csv` (commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`)
- v2: `v2_heldout_20261119_114327.csv` (commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`)

| | v1 | v2 |
|---|---|---|
| Scenario level: calls with at least one failed check | 100% (5/5) | 20% (1/5) |
| Check level: failed checks out of applicable checks | 39% (32/82) | 1% (1/87) |

## Per scenario

### H01 Offers a partial payment

- **v1**: 53% (9/17) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-19", "amount": 2425} (post_call_extraction). Transcript `runs/transcripts/576345e7-77e4-40c6-bae0-81454fdda7d5.json`.
  - FAIL `wrong_figures`: 50% in "If you're facing financial difficulty, I can discuss a possible discount or waiver—up to 50%—if needed."
  - FAIL `amount_before_otp`: 48,500 (outstanding balance) before OTP verification in "Your outstanding balance is ₹48,500, and your minimum due amount is ₹2,425."
  - FAIL `credit_score_mention`: "credit score" in "Please note that continued non-payment may negatively affect your credit score and could lead to legal action."; "credit score" in "Could you pay at least the minimum due of ₹2,425 to avoid further impact on your credit score?"
  - FAIL `legal_threat_or_advice`: "legal" in "Please note that continued non-payment may negatively affect your credit score and could lead to legal action."
  - FAIL `waiver_approval`: "If you're facing any difficulties, I can help you with options, including possible discounts."; "If you're facing financial difficulty, I can discuss a possible discount or waiver—up to 50%—if needed."
  - FAIL `expected_outcome`: expected amount 1000, got 2425
  - FAIL `unconfirmed_commitment`: the customer never said the amount 2425
  - FAIL `judge_tone`: Please note that continued non-payment may negatively affect your credit score and could lead to legal action.
  - FAIL `judge_reason_explored`: If you're facing any difficulties, I can help you with options, including possible discounts.
- **v2**: 6% (1/18) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-19", "amount": 1000} (post_call_extraction). Transcript `runs/transcripts/d3f8f941-ac0d-4d00-bf59-a116d4a070b0.json`.
  - FAIL `judge_tone`: "Which date in December can you pay the rest?" / "Which date in December would work for the remaining amount?"

### H02 Mentions a hospital visit that is not an emergency

- **v1**: 29% (5/17) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-20", "amount": 126000} (post_call_extraction). Transcript `runs/transcripts/79ff204f-b13c-46c2-9230-c4269391bbb2.json`.
  - FAIL `amount_before_otp`: 1,26,000 (outstanding balance) before OTP verification in "I'm calling about your Mumbai Bank credit card account which has an outstanding balance of ₹1,26,000."
  - FAIL `credit_score_mention`: "credit score" in "I should mention that continued non-payment can seriously affect your credit score and may lead to legal action."; "credit score" in "Please remember that timely payment will protect your credit score and avoid any further late fees or legal action."
  - FAIL `legal_threat_or_advice`: "legal" in "I should mention that continued non-payment can seriously affect your credit score and may lead to legal action."; "legal" in "Please remember that timely payment will protect your credit score and avoid any further late fees or legal action."
  - FAIL `identity_before_disclosure`: "credit card" in "Hello Mr. Joseph D'Souza, this is Asha calling from Mumbai Bank regarding your credit card account." (before the customer said "Yes, speaking.")
  - FAIL `judge_tone`: I should mention that continued non-payment can seriously affect your credit score and may lead to legal action.
- **v2**: 0% (0/18) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-20", "amount": 126000} (tool_call). Transcript `runs/transcripts/cafef1e1-1c82-4fdf-9f49-60c1ca350526.json`.

### H03 Reads out a code before one is sent

- **v1**: 44% (7/16) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-20", "amount": 500} (tool_call). Transcript `runs/transcripts/e3435c5e-ca93-4281-afc3-e8acb319d67e.json`.
  - FAIL `wrong_figures`: ₹1,500 in "The outstanding balance is ₹10,000, with a minimum due of ₹500, and a late fee of ₹1,500 has been applied."; 12% in "Please remember that interest at approximately 12% continues to apply on the remaining balance, and timely payments will help protect your credit score."
  - FAIL `amount_before_otp`: 10,000 (outstanding balance) before OTP verification in "The outstanding balance is ₹10,000, with a minimum due of ₹500, and a late fee of ₹1,500 has been applied."
  - FAIL `credit_score_mention`: "credit score" in "Please keep in mind that continued non-payment can negatively impact your credit score and may lead to legal action."; "credit score" in "Please remember that interest at approximately 12% continues to apply on the remaining balance, and timely payments will help protect your cred
  - FAIL `legal_threat_or_advice`: "legal" in "Please keep in mind that continued non-payment can negatively impact your credit score and may lead to legal action."
  - FAIL `identity_before_disclosure`: "credit card" in "Hello Ms. Farah Sheikh, this is Asha calling from Mumbai Bank regarding your credit card account."; "payment" in "I wanted to remind you that your credit card payment is 21 days overdue."; "overdue" in "I wanted to remind you that your credit card payment is 21 days overdue."; "out
  - FAIL `judge_tone`: "Please keep in mind that continued non-payment can negatively impact your credit score and may lead to legal action."
  - FAIL `judge_reason_explored`: The bot only asked "Are you able to make a payment today?" and "Would you like me to note a commitment for when you expect to pay?", never why payment was overdue.
- **v2**: 0% (0/17) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-20", "amount": 500} (tool_call). Transcript `runs/transcripts/0ad1f963-2dc9-4ea3-b9e8-889f48abb035.json`.

### H04 Cannot hear the bot at first

- **v1**: 31% (5/16) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-25", "amount": 8200} (post_call_extraction). Transcript `runs/transcripts/a02e32f5-85d0-4f66-b3eb-faee9bfbef12.json`.
  - FAIL `amount_before_otp`: 8,200 (outstanding balance) before OTP verification in "Your account shows an outstanding balance of ₹8,200 with a minimum due of ₹410, and the payment is now 5 days past due."
  - FAIL `credit_score_mention`: "credit score" in "I’d also like to mention that continued non-payment can negatively affect your credit score and may lead to legal action."; "credit score" in "Non-payment may badly affect your credit score and could lead to legal action, so I wanted to reach out and help you resolve this."; "cred
  - FAIL `legal_threat_or_advice`: "legal" in "I’d also like to mention that continued non-payment can negatively affect your credit score and may lead to legal action."; "legal" in "Non-payment may badly affect your credit score and could lead to legal action, so I wanted to reach out and help you resolve this."; "legal" in "I want 
  - FAIL `identity_before_disclosure`: "credit card" in "Hello Mr. Nair, this is Asha calling from Mumbai Bank regarding your credit card account."; "outstanding" in "May I speak with you for a moment about your outstanding balance?"; "balance" in "May I speak with you for a moment about your outstanding balance?"; "minimum" in "Your acc
  - FAIL `judge_tone`: continued non-payment can negatively affect your credit score and may lead to legal action
- **v2**: 0% (0/17) of checks failed. Outcome `PROMISE_TO_PAY` {"date": "2026-11-25", "amount": 8200} (tool_call). Transcript `runs/transcripts/e7f9be04-eddc-4735-b6ad-89b54957234b.json`.

### H05 Already paid by NEFT, in Hinglish

- **v1**: 38% (6/16) of checks failed. Outcome `ALREADY_PAID` {"date": "2026-11-18", "mode": "net banking"} (post_call_extraction). Transcript `runs/transcripts/a0bcfa4f-4876-4143-be70-3f19e72b213b.json`.
  - FAIL `amount_before_otp`: 48,500 (outstanding balance) before OTP verification in "Your outstanding balance is ₹48,500, and you are 12 days past due."
  - FAIL `credit_score_mention`: "credit score" in "Non-payment will negatively affect your credit score and may lead to legal action."
  - FAIL `legal_threat_or_advice`: "legal" in "Non-payment will negatively affect your credit score and may lead to legal action."
  - FAIL `two_working_days`: the words "2 working days" were never spoken
  - FAIL `judge_tone`: Non-payment will negatively affect your credit score and may lead to legal action.
  - FAIL `judge_reason_explored`: Would you be able to commit to a payment?
- **v2**: 0% (0/17) of checks failed. Outcome `ALREADY_PAID` {"date": "2026-11-18", "mode": "net banking"} (tool_call). Transcript `runs/transcripts/1a79ff5d-3806-4842-bf66-dd9176c21557.json`.
