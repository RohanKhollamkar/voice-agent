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
- Two failed OTP attempts end the call: no account details, outcome `CALLBACK_REQUEST` with reason `verification_failed`.
- If someone other than the customer answers, the bot says nothing about the debt or dues and asks for a good time to call back: `CALLBACK_REQUEST` with reason `wrong_party`.
- If the customer asks for a waiver and also promises to pay, the outcome is `PROMISE_TO_PAY` and the waiver goes in `follow_ups` as a `CALLBACK_REQUEST` with reason `waiver_request`.
- The test scenarios are listed in `docs/scenarios.csv` (S01–S19).

## Locked stack

| Layer | Choice | Notes |
|---|---|---|
| Framework | Pipecat (Python) | Local mic and speaker transport for the demo; no telephony |
| Speech-to-text | Sarvam, real-time | Hinglish input |
| Model provider | NVIDIA API (build.nvidia.com), called directly | Pipecat `NvidiaLLMService`; base URL `https://integrate.api.nvidia.com/v1`; key in `NVIDIA_API_KEY`. No OpenRouter |
| Language model (bot) | `nvidia/nemotron-3.5-super-vl-120b-a12b`, thinking off | Nemotron 3 Super was retired on the NVIDIA API (16 Nov) |
| Backup bot model | Nemotron 3 Ultra | Used on timeout or error |
| Judge model (evals) | Nemotron 3 Ultra | Same model family as the bot, which weakens the judge's independence. Replace with a non-Nemotron model from the NVIDIA API when one is confirmed working |

`config.py` is the source of truth for exact model IDs. If a model ID here and in `config.py` disagree, `config.py` wins; update this table, never the reverse.
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
    "CALLBACK_REQUEST": {"time": "ISO-8601 or null", "reason": "busy | waiver_request | wrong_party | call_time_limit | verification_failed"},
    "DISPUTE": {"reason": "free text"},
    "TRANSFER_TO_HUMAN": {"reason": "abusive | medical_emergency | job_loss | customer_request"}
  },
  "follow_ups": [
    {"outcome_type": "CALLBACK_REQUEST", "details": {"time": null, "reason": "waiver_request"}}
  ],
  "captured_by": "tool_call | post_call_extraction",
  "transcript_path": "runs/transcripts/<call_id>.json"
}
```

`details` holds only the key that matches `outcome_type`. `follow_ups` is optional and usually empty; each entry is a secondary outcome a human must act on, in the same shape as the main one.

## Conventions

- Python 3.11+, `uv` or `pip` with `requirements.txt`, type hints, `ruff` formatting.
- Secrets only in `.env` (never committed). Keep `.env.example` current.
- Every call writes a transcript JSON (turns, tool calls, latencies, outcome) to `runs/transcripts/`.
- The conversation logic must run in text mode (no audio) as well as voice mode, from the same code. Evals use text mode.
- Commit at the end of each stage with a clear message. Do not push unless asked.
