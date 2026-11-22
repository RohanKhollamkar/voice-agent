# Samples

Five call transcripts. Each comes as plain text (`.txt`: who said what, when, and the
outcome) and as the full log (`.json`: turns, tool calls, guardrail actions, latencies,
outcome). Call recordings are not stored in the repo; they are shared separately with the
submission.

| Transcript | Shows | Bot | Outcome | Kind |
|---|---|---|---|---|
| `v2.1_promise_to_pay_voice` | A voice call. Identity, OTP, the dues and the ₹750 late fee, a full-balance promise read back and confirmed, then the helpline closing line. First audio 2.6–3.6 s after each customer turn | v2.1 | PROMISE_TO_PAY 2026-11-27, ₹48,500 | Works well |
| `v2_S16_waiver_promise_text` | A late-fee waiver request noted without approving it, then a promise read back and recorded with the waiver as a follow-up | v2 | PROMISE_TO_PAY 2026-11-20, ₹48,500; follow-up CALLBACK_REQUEST waiver_request | Works well |
| `v1_S15_wrong_person_text` | The customer's wife answers. v1 names the credit card account and the balance in its first line, repeats the dues to her, and mentions the credit score and legal action | v1 | CALLBACK_REQUEST busy (should be wrong_party) | Where it broke |
| `v2_hang_up_recorded_busy_voice` | A voice call. The customer hangs up after the OTP request, and the bot records "busy", which nobody said. Fixed later: such a call now records call_dropped | v2 | CALLBACK_REQUEST busy | Where it broke |
| `v2.1_tool_name_spoken_voice` | A voice call. The bot says "I'll call send_otp now" aloud. Found in this call and fixed in v2.1 afterwards: the reply check now blocks tool names | v2.1 (before that fix) | PROMISE_TO_PAY 2026-11-27, ₹48,500 | Where it broke |

## Where they come from

- `_voice`: voice calls through the real pipeline (Sarvam speech-to-text, the agent, the
  reply check, the normaliser, Sarvam speech). The two v2.1 calls are automated voice
  tests (`python -m scripts.voice_test`), with the customer's lines synthesised and played
  in real time. The v2 call went through the demo console's browser connection.
- `_text`: text-mode calls from the final evaluation pass (`docs/results/final/`, commit
  `de12c92`).

The `transcript_path` and `recording` entries inside each `.json` point to where the
call was first written (`runs/`, which is not committed).
