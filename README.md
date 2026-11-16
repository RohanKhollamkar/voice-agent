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
scripts/      spike scripts
runs/         transcripts, outcomes, recordings, results (created at run time, not committed)
```

## Running

To be written as the stages land.
