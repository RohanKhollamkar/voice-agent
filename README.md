# Mumbai Bank collections voicebot

An outbound voicebot for Mumbai Bank (fictional) that calls credit card customers who missed their minimum payment, finds out why, and nudges them toward a resolution. Every call ends with one structured outcome posted to a webhook.

Status: repo scaffold only. No agent logic yet. See `CLAUDE.md` for the rules and stack, and `docs/BUILD_PLAN.md` for the build stages.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in the keys
```

Local audio uses PyAudio, which needs the PortAudio system library (`brew install portaudio` or `apt install portaudio19-dev`).

## Layout

```
config.py     settings loaded from .env
agent/        agent core: prompts, tools, outcome, mocked bank (no audio code)
voice/        Pipecat pipeline around the agent core
evals/        text-mode eval harness
scripts/      the voice spike, the LLM latency check, and the voice test
runs/         transcripts, outcomes, recordings, results (created at run time, not committed)
```

## Running

The full guide is written in the last stage. For now:

### Voice test without a microphone

`scripts/voice_test.py` runs a whole voice call with no mic or speaker. A scripted customer (identity, the OTP, a promise to pay, a yes to the read-back) is synthesized and played into the real pipeline in real time: Sarvam speech-to-text, the agent, the reply check, the normaliser and speech. It prints the call, its outcome and the latency of each stage per turn, and saves the transcript and a WAV recording as any voice call does.

```bash
python -m scripts.voice_test
```

```bash
python -m scripts.voice_test --barge-in
```

```bash
python -m scripts.voice_test --otp-pause 0.8
```

`--barge-in` speaks the promise over the bot, to test interruptions. `--otp-pause` reads the OTP in two halves with a pause, to test that it still arrives as one code. Turn-taking settings can be tried from the environment, for example `SARVAM_STT_SILENCE_MS=500 python -m scripts.voice_test`; see `docs/results/latency.md`. It needs the Sarvam, ElevenLabs and NVIDIA keys; if ElevenLabs refuses (its free plan has a monthly quota), the customer speaks with a Sarvam voice, and `TTS_PROVIDER=sarvam` moves the bot to Sarvam too.
