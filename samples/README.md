# Samples

Five calls, each with its transcript as plain text (`.txt`: who said what, when, and the
outcome) and as the full log (`.json`: turns, tool calls, guardrail actions, latencies,
outcome). Voice calls also have their recording.

| Call | Shows | Bot | Outcome | Kind |
|---|---|---|---|---|
| `v2.1_promise_to_pay_voice` | Identity, OTP, the dues and the ₹750 late fee, a full-balance promise read back and confirmed, then the helpline closing line. Time to the bot's first audio 2.6–3.6 s per turn | v2.1 | PROMISE_TO_PAY 2026-11-27, ₹48,500 | Works well |
| `v2_S16_waiver_promise_text` | A late-fee waiver request noted without approving it, then a promise read back, recorded with the waiver as a follow-up | v2 | PROMISE_TO_PAY 2026-11-20, ₹48,500, follow-up CALLBACK_REQUEST waiver_request | Works well |
| `v1_S15_wrong_person_text` | The customer's wife answers. v1 names the credit card account and the balance in its first line, repeats the dues to her, and mentions the credit score and legal action | v1 | CALLBACK_REQUEST busy (should be wrong_party) | Where it broke |
| `v2_hang_up_recorded_busy_voice` | The customer hangs up after the OTP request; the bot recorded "busy", which nobody said. Fixed afterwards: such a call now records call_dropped | v2 | CALLBACK_REQUEST busy | Where it broke |
| `v2.1_tool_name_spoken_voice` | The bot says "I'll call send_otp now" aloud. Found in this test and fixed in v2.1 afterwards: tool names are now blocked by the reply check | v2.1 (before that fix) | PROMISE_TO_PAY 2026-11-27, ₹48,500 | Where it broke |

## About the recordings

- Stereo, 24 kHz: the customer on the left channel, the bot on the right.
- The two recordings over 5 MB are MP3 at 96 kbit/s (`.mp3`). The one under 5 MB is the
  original WAV (`.wav`).
- `v2.1_promise_to_pay_voice` and `v2.1_tool_name_spoken_voice` are automated voice tests
  (`python -m scripts.voice_test`). The customer's lines are synthesised speech, played
  into the real pipeline in real time: Sarvam speech-to-text, the agent, the reply check,
  the normaliser and Sarvam speech. `v2_hang_up_recorded_busy_voice` went through the
  demo console's browser connection.
- The `_text` calls are from the final evaluation pass (`docs/results/final/`, commit
  `de12c92`), run in text mode, so they have no audio.

The `transcript_path` inside each `.json` points to where the call was first written
(`runs/transcripts/`, not committed).
