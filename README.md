# Mumbai Bank collections voicebot

An outbound collections voicebot for a fictional bank. It calls credit card customers who are 1–30 days past their minimum payment, reminds them, finds out why they haven't paid, and steers them to a resolution: a promise to pay, a callback, or a transfer to a person. Every call ends with one structured outcome posted to a webhook. It is built from separate speech-to-text, language model and speech APIs, glued together in Python with Pipecat, and runs on a laptop mic and speakers or in a browser; there is no telephony. The bank's rules are in [`CLAUDE.md`](CLAUDE.md).

## Architecture

```
 mic ─▶ Sarvam speech-to-text ─▶ agent core ─────────────▶ reply check ─▶ normaliser ─▶ Sarvam speech ─▶ speaker
        (Hinglish, real time)    prompt + tools             (no figures    (₹750 → "seven
                                 (OTP, account summary,      before OTP,     hundred and
                                 record_outcome)             no CIBIL, no    fifty rupees")
                                 + code guardrails           legal, no tool
                                 (identity first, promise    names)
                                 read-back, forced transfer,
                                 call timer)
                                        │
                                        └─▶ outcome JSON ─▶ webhook (and runs/outcomes/)
```

The conversation logic (`agent/`) has no audio code and is shared by text mode and voice mode, so the text-mode evals test exactly what runs on a voice call; `voice/` only adds speech around it.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Framework | Pipecat (Python) | Handles the audio pipeline, turn-taking and barge-in, with swappable services |
| Speech-to-text | Sarvam, real time (`saaras:v3-realtime`) | Built for Indian languages: transcribes Hindi, English and Hinglish in one stream |
| Speech | Sarvam Bulbul v4 Flash | An Indian English voice. ElevenLabs Flash v2.5 is supported too and swapped in with `TTS_PROVIDER=elevenlabs` |
| Bot model | Nemotron 3.5 Super on the NVIDIA API, thinking off | Fast enough for live turns (about 1 s per call) and reliable at tool calls. Nemotron 3 Ultra is the backup on a timeout or error |
| Eval judge | Kimi K3.1 Pro on the NVIDIA API | A different model family from the bot, so it doesn't grade its own kind; chosen in [`judge_choice.md`](docs/results/final/judge_choice.md) |

Model IDs and voices live in `config.py` and `.env`, never in the logic.

## Versions

| Version | What changed | Results |
|---|---|---|
| v1 | The bank's prompt, unchanged. The baseline | `docs/results/final/`, `docs/results/final-3way/` |
| v2 | A rewritten prompt plus code guardrails: a fixed opening line, the reply check, the OTP gate, the promise read-back, forced transfers, the call timer and outcome evidence rules | `docs/results/final/` (judged), `docs/results/final-3way/` |
| v2.1 | Fixes from live voice testing: the brief's other-products line spoken by code, "kal" resolved by tense, payment modes noted, tool names blocked, a promise recorded only after the bot has read it back and the customer agreed, past callback times moved to the next day, a helpline closing line, and wrong-party callbacks | `docs/results/final-3way/`; its evidence is live voice calls (transcripts in [`samples/`](samples/)) |

`v2` is kept unchanged so its results stay reproducible. `BOT_VERSION` (default `v2.1`) picks the version.

## Results

### Main result: v1 against v2

From [`docs/results/final/`](docs/results/final/headline.md): main set S01–S19, 3 runs per version (57 calls), every call scored by code checks and the judge; commit `de12c92`.

| | v1 | v2 |
|---|---|---|
| Calls with any failed check | 100% (57/57) | 21% (12/57) |
| Failed checks, out of applicable | 47% (399/858) | 2% (17/909) |
| Held-out H01–H05 (1 run), calls with any failed check | 100% (5/5) | 20% (1/5) |
| Held-out, failed checks | 39% (32/82) | 1% (1/87) |

Rules with at least 38 calls behind them (failure rate, main set):

| Rule | v1 | v2 |
|---|---|---|
| Amount stated before OTP | 96% (55/57) | 0% (0/57) |
| Credit score mentioned | 95% (54/57) | 0% (0/57) |
| Tone (judge) | 96% (54/56) | 12% (7/57) |
| Legal threat or advice | 91% (52/57) | 0% (0/57) |
| Account details before identity confirmed | 86% (49/57) | 0% (0/57) |
| Wrong figures (rate, fee or amount not from the tools) | 67% (38/57) | 2% (1/57) |
| Waiver approved by the bot | 26% (15/57) | 0% (0/57) |
| Call length over the limit | 14% (8/57) | 5% (3/57) |
| Talked about other products | 11% (6/57) | 0% (0/57) |
| Replied in Hindi | 4% (2/57) | 0% (0/57) |
| No outcome recorded | 0% (0/57) | 2% (1/57) |

The held-out scenarios were written after v2 was frozen, and v2 was never changed for them.

### Supporting result: v1, v2 and v2.1

From [`docs/results/final-3way/`](docs/results/final-3way/headline.md): main set S01–S19, 2 runs per version (38 calls), code checks only, every call on a fixed clock (Monday 16 November 2026, 11:00 IST); commit `1432ded`. The third run, the held-out set and the judge were dropped when the NVIDIA free tier rate-limited the account ([`run_notes.md`](docs/results/final-3way/run_notes.md)).

| | v1 | v2 | v2.1 |
|---|---|---|---|
| Calls with any failed check | 100% (38/38) | 5% (2/38) | 8% (3/38) |
| Failed checks, out of applicable | 42% (212/500) | 0% (2/534) | 1% (3/534) |
| Account details before identity confirmed | 95% (36/38) | 0% | 0% |
| Amount stated before OTP | 92% (35/38) | 0% | 0% |
| Credit score mentioned | 89% (34/38) | 0% | 0% |
| Legal threat or advice | 84% (32/38) | 0% | 0% |
| Wrong figures | 71% (27/38) | 0% | 0% |
| Call length over the limit | 29% (11/38) | 3% (1/38) | 5% (2/38) |
| Waiver approved by the bot | 21% (8/38) | 0% | 0% |

v2.1 does not score better than v2 here, and isn't expected to: its fixes target behaviour the code checks don't measure (the exact products line, "kal", payment modes, the helpline close, tool names said aloud on a voice call). Its evidence comes from live voice calls; their transcripts are in [`samples/`](samples/). The v2.1 fixes made after this run (wrong-party callbacks, the callback time, the goodbye fallback, a repeated question after a refusal) are in no results table.

Every check for every scenario and version, from both passes, is in [`docs/results/test_results.csv`](docs/results/test_results.csv), with a column for the run set.

## The outcome

Each call produces exactly one outcome, posted to `WEBHOOK_URL` and written to `runs/outcomes/`. This one is from a v2.1 voice call (transcript in `samples/`):

```json
{
  "call_id": "874100eb-b823-46bd-9f01-d42d93d253e0",
  "customer_id": "C001",
  "bot_version": "v2.1",
  "started_at": "2026-11-22T12:03:03+05:30",
  "ended_at": "2026-11-22T12:04:24+05:30",
  "duration_seconds": 81,
  "otp_verified": true,
  "outcome_type": "PROMISE_TO_PAY",
  "details": {"PROMISE_TO_PAY": {"date": "2026-11-27", "amount": 48500}},
  "follow_ups": [],
  "captured_by": "tool_call",
  "transcript_path": "runs/transcripts/874100eb-b823-46bd-9f01-d42d93d253e0.json"
}
```

The five outcome types:

| Type | Details | When |
|---|---|---|
| `PROMISE_TO_PAY` | date, amount | The customer commits to a date and amount, read back and confirmed |
| `ALREADY_PAID` | date, mode (UPI, net banking, card, cash, other) | The customer says they have paid; the bot says it reflects in 2 working days |
| `CALLBACK_REQUEST` | time or null, reason: busy, waiver_request, wrong_party, call_time_limit, verification_failed, call_dropped | Asked to call later, a late-fee waiver request, someone else answered, out of time, two failed OTPs, or the call ended with nothing agreed |
| `DISPUTE` | reason (free text) | The customer disputes the dues |
| `TRANSFER_TO_HUMAN` | reason: abusive, medical_emergency, job_loss, customer_request | The bot stops and hands over (the transfer itself is not built) |

`follow_ups` holds a second outcome a person must act on, such as a waiver request alongside a promise to pay. `captured_by` says whether the bot recorded the outcome during the call (`tool_call`) or it was read off the transcript afterwards (`post_call_extraction`).

## How to run

### Windows one-click setup

Two files in [`scripts/windows/`](scripts/windows/) set up and start the demo on Windows without typing commands. They need Git and Python 3.11–3.13 installed (Python with "Add python.exe to PATH" ticked).

1. Download `setup_voice_agent.bat` and `start_demo.bat` into an empty folder.
2. Double-click `setup_voice_agent.bat`. It clones the repo's `main` branch into a `voice-agent` folder next to it, creates a Python environment, installs the requirements, and opens `.env` in Notepad: fill in `SARVAM_API_KEY`, `NVIDIA_API_KEY` and, if you have one, `WEBHOOK_URL`, then save. Running it again updates the code and leaves `.env` alone.
3. Double-click `start_demo.bat`. It starts the demo console and opens http://localhost:7860/demo in the browser. Keep its window open during the call; close it to stop the demo.

### Manual setup

Python 3.11 or later.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
```

```bash
cp .env.example .env
```

Then put your keys in `.env`: `SARVAM_API_KEY` and `NVIDIA_API_KEY` are required, and `WEBHOOK_URL` is optional (a webhook.site URL works). Every other setting is listed there with its default. Voice calls on the laptop's own mic use PyAudio, which needs PortAudio (`brew install portaudio` or `apt install portaudio19-dev`); the demo console's browser mode does not.

### Demo console

```bash
python -m voice.demo --open
```

It serves http://localhost:7860/demo (localhost only). Pick a customer, the bot version and a mode, then press Start call. **Voice** uses the browser's mic and speakers, so the browser's echo cancellation applies and barge-in works; **Text** takes typed customer turns and costs no speech credits.

![Demo console after a v2.1 text-mode call](docs/results/demo_console.png)

A v2.1 text call with customer C001: identity, the OTP, a promise in Hinglish ("20 tareekh ko pura outstanding amount bhar dunga"), the read-back, and the close. What is on screen:

- **Top bar.** The customer, the bot version (v1, v2 or v2.1), the mode (Voice or Text), Start call and End call (End call is the customer hanging up), and on the right the call's status.
- **Conversation.** The call timer, with marks at 2:30 (the bot is told to wrap up) and 3:00 (the limit); in text mode it is estimated from the words spoken. Each turn is timestamped. Under each bot turn, `agent` is the time the agent took to reply, amber above 2.5 s (here 7.1 s, while the main model was rate-limited and the backup answered). In voice mode a second label gives the time from the customer's last word to the bot's first audio. `closing line` marks the goodbye that code builds from the recorded outcome.
- **Behind the scenes.** Everything the agent did, in order, with the time since the call started: tool calls in blue (`send_otp`, `verify_otp`, `get_account_summary`, `record_outcome`, with arguments and result) and guardrail actions in purple: here a date note ("20 tareekh = Sunday, 20 December 2026") and text dropped by code (an announcement before a tool call, and what the model wrote with its `record_outcome` call, which the closing line replaces). The count is the number of entries.
- **Outcome.** The outcome type, how it was captured (by the bot's `record_outcome` call or read off the transcript after the call) and whether it matches the schema, then the outcome JSON and the webhook's result.
- **Call files.** The files to download once the call ends: the transcript as text and as the full JSON log, and, for voice calls, the recording (WAV, customer on the left channel, bot on the right). They are also saved in `runs/exports/<call_id>/`.

The webhook in this screenshot was a local test receiver.

### A text call

```bash
python -m agent.chat --customer C001 --version v2.1
```

You type the customer's lines; `/end` hangs up.

### A voice call

```bash
python -m voice.call --customer C001 --version v2.1 --echo browser
```

Then open http://localhost:7860/client and press Connect. `--echo half-duplex` uses the laptop mic and speakers directly, muting the mic while the bot speaks (no barge-in); `--echo none` needs headphones. `python -m scripts.voice_test` runs a whole voice call with no mic, with a synthesised customer, and reports latency per stage.

### Evals

```bash
python -m evals.run_evals --version v2.1 --runs 3 --concurrency 3
```

```bash
python -m evals.run_evals --version v2.1 --set heldout --no-judge
```

`--set main` (the default) runs S01–S19 and `--set heldout` runs H01–H05. `--no-judge` skips the judge and scores with code checks only. `--concurrency` sets how many calls run at once; lower it if the API rate-limits you. Every call runs on a fixed simulated clock (`--clock`, default Monday 16 November 2026, 11:00 IST), so dates such as "Friday" resolve the same way on every run. Results go to `runs/results/`; each row records the commit, the judge model and the clock.

## Where things are

| Path | What |
|---|---|
| `agent/` | The conversation logic: prompts (`agent/prompts/`), tools, code guardrails, dates, the outcome, the mocked bank |
| `voice/` | The Pipecat pipeline, the normaliser, the demo console |
| `evals/` | The eval harness: scenarios, code checks, the judge |
| `docs/` | The build plan and the scenario lists (`scenarios.csv`, `scenarios_heldout.csv`, with failure categories and brief or inferred tags) |
| `docs/results/` | `final/` (v1 against v2, judged), `final-3way/` (all three versions, code checks), `test_results.csv`, `latency.md`. The older Stage 4 comparison (`comparison.md`, `v1_3runs.csv`, `v2_3runs.csv`) is kept for the record |
| `samples/` | Five call transcripts (`.txt` and `.json`), what each shows and whether it works well or broke; see its README |
| `scripts/` | Report generators, the voice test, the speech-to-text check, the Stage 1 spike and latency check, and the Windows setup (`scripts/windows/`) |
| `runs/` | Transcripts, outcomes, recordings and results written at run time; git-ignored |

Call recordings are not stored in the repo; they are shared separately with the submission.

## Known limitations

- **S18's call length.** In text mode the call length is estimated from the words spoken, and for S18 the estimate (3:56–4:13) disagrees with the call timer, which closed the call at the limit.
- **A small held-out set.** H01–H05 is 5 scenarios, run once per version.
- **A short 3-way run.** The v1, v2 and v2.1 comparison is 2 runs with no judge and no held-out set, cut short by NVIDIA free-tier rate limits.
- **Reply latency.** About 2–3 s from the customer's last word to the bot's first audio; turns with tool calls are covered by "One moment." ([`latency.md`](docs/results/latency.md)).
- **Barge-in is slow to land.** About 2.5 s: the bot stops only once speech-to-text has transcribed two of the customer's words (a yes, a no or digits interrupt at once).
- **Phone audio untested.** Only browser and laptop audio was tested, not 8 kHz phone-line audio.
- **Echo cancellation needed.** The browser demo relies on the browser's echo cancellation; on plain speakers without it the bot hears itself.
- **Speech errors aren't scored.** The evals run in text mode, so speech-to-text mistakes don't show up in the scores; `scripts/stt_noise_test.py` checks them separately on recorded calls.
