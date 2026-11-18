# Voice latency: where the time goes, and what changed

Measured on 18 November 2026 with `scripts/voice_test.py`: a scripted customer is played into the real pipeline (Sarvam speech-to-text, the v2 agent on `nvidia/nemotron-3.5-super-vl-120b-a12b`, the reply check, the normaliser, speech) through a fake transport, in real time. Each call has three to four answered customer turns. The figures are medians over all answered turns of the calls in each group: 7 to 15 turns per group, a small sample.

"Latency" is the time from the end of the customer's speech to the bot's first audio.

## Where the time goes (before)

| Stage | Median | What it is |
|---|---|---|
| End of speech | 0.20 s | The local VAD's silence wait |
| Speech-to-text | 1.45–1.51 s | From the end of speech to Sarvam's final transcript. Most of it is Sarvam's own end-of-speech wait, which runs after the local VAD has already decided: two end-of-speech signals in a row |
| Turn detection | 0.00 s | The turn ends the moment the transcript arrives |
| Agent | 1.05 s (one model call), 2.4–2.5 s (turns with tools) | The model is not streamed, so a model call's time is its time to first token. Turns that verify the OTP and fetch the account make three model calls |
| Speech | 0.18 s (ElevenLabs), 0.44 s (Sarvam) | Text to first audio |
| **Total** | **3.0 s (one model call), 4.4–4.5 s (turns with tools)** | |

## What was tried

| Change | Speech-to-text | Kept? | Why |
|---|---|---|---|
| Sarvam `stream_type=fast` | 1.49 s (no change) | No | No effect |
| Sarvam end-of-speech silence 300 ms | 0.76 s | No | A code read with a 0.45 s pause was split ("482", then "913"), counted as a wrong OTP, and the call ended as verification failed |
| Silence 500 ms | 0.98 s | No | Same split at a 0.45 s pause |
| Silence 700 ms | 1.15 s | **Yes** | Keeps a code read with a 0.8 s pause together, with the joining below |
| One end-of-speech signal (`STT_ENDPOINTING=manual`: the local VAD ends speech and tells Sarvam) | 0.4–0.55 s | No | The fastest, but Sarvam only got the audio after the VAD had confirmed speech, so the start of every utterance was lost: "Yes, speaking" vanished, the OTP came through as "82913" |
| Code joining in the voice step | – | **Yes** | While the bot waits for the OTP, a turn that is only part of a code waits up to 4 s for the rest |
| "One moment." when the agent takes over 1.5 s | – | **Yes** | Covers the slow tool-calling turns. It commits to nothing, so it cannot contradict the reply ("Okay." could, before a refusal). It is sent as a speak request, because a lone sentence otherwise waits in the speech service's buffer until the reply arrives |

## Before and after

Speech on Sarvam in both (the ElevenLabs free quota ran out during the tests), so the speech stage is 0.44 s in both columns.

| | Before | After |
|---|---|---|
| Speech-to-text | 1.45 s | 1.15 s |
| Agent, turns with one model call | 0.88 s | 1.15 s (model variance between runs) |
| First audio, turns with one model call | 3.02 s | 2.98 s |
| First audio, turns with tools | 4.54 s | 3.42 s ("One moment."; the reply follows when the agent finishes) |

The speech-to-text saving (about 0.3 s per turn) is real and consistent; on turns with one model call it was cancelled out here by the model happening to be slower in the later runs. With ElevenLabs speech (0.18 s instead of 0.44 s) every figure would be about a quarter of a second lower.

## What is left, and what would cut it

- **The model, about 1 s per call.** Streaming the reply and speaking its first sentence while the rest is generated would cut the wait to the time to first token. That needs the agent core to hand over sentences as they arrive, which it does not do now.
- **Speech-to-text, about 1.15 s.** Most of it is Sarvam's end-of-speech wait. Shorter waits split codes and sentences, and joining only covers codes. A turn-completion model (Pipecat's smart-turn) could judge whether the customer has finished, at the cost of a heavier install.
- **Tool turns** make three model calls in a row. Fetching the account summary in code right after a successful OTP would save one.

## Settings

All in `config.py`, overridable from the environment: `SARVAM_STT_SILENCE_MS` (700), `SARVAM_STT_STREAM_TYPE` (balanced), `STT_ENDPOINTING` (vad), `VAD_STOP_SECS` (0.2), `USER_SPEECH_TIMEOUT` (manual mode only), `VOICE_ACK_AFTER_SECONDS` (1.5; 0 turns it off). Each experiment above can be rerun with `scripts/voice_test.py` and these settings, for example `SARVAM_STT_SILENCE_MS=300 python -m scripts.voice_test --otp-pause 0.45`.
