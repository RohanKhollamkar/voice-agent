# Mumbai Bank Collections Voicebot

Context for Claude Code. Read this before every task in this repo. The build is done in stages; the stage prompts are in `docs/BUILD_PLAN.md`. Do only the stage you are asked to do.

## What this is

A take-home assignment for an AI PM role. An outbound voicebot for Mumbai Bank (fictional) calls credit card customers who missed their minimum payment by 1–30 days, reminds them, understands why they haven't paid, and nudges them toward a resolution. Every call ends with one structured outcome posted to a webhook.

The reviewers will read the code and ask us to walk through it. Prefer small, readable modules over clever abstractions. Do not over-build: the assignment is 3–4 days and "what you cut" is graded.

## Business rules (from the bank's brief, do not change)

1. The bot speaks English only. Customers may reply in Hindi, English or a mix; the bot still replies in English.
2. Already paid → ask when and through which mode; tell them it will reflect in 2 working days.
3. Late-fee waiver request → say it will be noted and a human agent will call back. The bot cannot approve waivers. Outcome: `CALLBACK_REQUEST` with reason `waiver_request`.
4. Customer is abusive, or mentions a medical emergency or job loss → stop the pitch, transfer to a human. Outcome: `TRANSFER_TO_HUMAN` with the reason. The transfer flow itself is not built.
5. Credit card interest: 3.5% per month. Late fee: ₹750 if the outstanding balance is over ₹10,000, otherwise no late fee.
6. Never reveal the account balance without OTP verification.
7. Never mention the customer's CIBIL score or predict what it will become.
8. Never give legal advice or threaten legal action.
9. Asked about other products (FDs, new loans, insurance) → say exactly: "I'm only here for your pending payment. For other queries, please visit a branch or call the helpline."
10. Each call closes in 2–3 minutes with a clear outcome.

## Our own decisions (where the brief is silent)

- Before OTP the bot may confirm it is speaking to the right person and say a credit card payment is overdue. It gives no amounts before OTP.
- OTP is mocked. `ENFORCE_OTP=false` disables the code-level gate so the "balance without OTP" failure can be reproduced on demand.
- The bot says it is an automated assistant calling from Mumbai Bank in its first line.
- Figures (rate, fee, balance, minimum due) come from tools or config, never from the model's memory.

## Locked stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | Pipecat (Python) | Local mic and speaker transport for the demo; no telephony |
| Speech-to-text | Sarvam, real-time | Hinglish input |
| Language model (bot) | `google/gemma-4-31b-it:free` on OpenRouter, thinking off | Verify the model ID on OpenRouter before use |
| Backup bot model | `nvidia/nemotron-3-ultra-550b-a55b:free` | Used on timeout or error |
| Judge model (evals) | `nvidia/nemotron-3-ultra-550b-a55b:free` | Different family from the bot on purpose |
| Speech | ElevenLabs Flash v2.5 | Behind a swappable interface; Sarvam Bulbul V4 Flash is the alternative |
| Outcome sink | HTTP POST to `WEBHOOK_URL` (webhook.site) | Also written to `runs/outcomes/` |

Model IDs, voices and provider settings live in config (`.env` and `config.py`), never hard-coded in logic. Check current Pipecat docs for exact service class names and parameters rather than guessing.

## Outcome schema

Every call produces exactly one outcome:

```json
{
  "call_id": "uuid",
  "customer_id": "C001",
  "bot_version": "v1",
  "started_at": "ISO-8601",
  "ended_at": "ISO-8601",
  "duration_seconds": 142,
  "otp_verified": true,
  "outcome_type": "PROMISE_TO_PAY | ALREADY_PAID | CALLBACK_REQUEST | DISPUTE | TRANSFER_TO_HUMAN",
  "details": {
    "PROMISE_TO_PAY": {"date": "YYYY-MM-DD", "amount": 4500},
    "ALREADY_PAID": {"date": "YYYY-MM-DD", "mode": "UPI | net banking | card | cash | other"},
    "CALLBACK_REQUEST": {"time": "ISO-8601", "reason": "busy | waiver_request | wrong_party | call_time_limit"},
    "DISPUTE": {"reason": "free text"},
    "TRANSFER_TO_HUMAN": {"reason": "abusive | medical_emergency | job_loss | customer_request"}
  },
  "captured_by": "tool_call | post_call_extraction",
  "transcript_path": "runs/transcripts/<call_id>.json"
}
```

`details` holds only the key that matches `outcome_type`.

## Conventions

- Python 3.11+, `uv` or `pip` with `requirements.txt`, type hints, `ruff` formatting.
- Secrets only in `.env` (never committed). Keep `.env.example` current.
- Every call writes a transcript JSON (turns, tool calls, latencies, outcome) to `runs/transcripts/`.
- The conversation logic must run in text mode (no audio) as well as voice mode, from the same code. Evals use text mode.
- Commit at the end of each stage with a clear message. Do not push unless asked.
