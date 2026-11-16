# Build plan: Mumbai Bank collections voicebot

Phase 1 (development) plan. Testing strategy (phase 2) and the final writeup (phase 3) are planned separately.

## 1. Locked decisions and why

| Decision | Choice | Why |
|---|---|---|
| Framework | Pipecat | Readable pipeline, runs on a laptop mic and speaker with no media server, and a guardrail can be added as one visible step between the model and speech. LiveKit Agents is stronger for telephony at scale, which is out of scope. OpenAI Realtime merges the three stages the brief asks to see separately |
| Speech-to-text | Sarvam real-time | Built for Indian languages and code-mixed speech; free credits cover development |
| Model provider | NVIDIA API (build.nvidia.com), called directly | Free tier of about 40 requests a minute and 10,000 a day per model (third-party trackers, check your console), so eval runs are not rate-limited. Pipecat has a built-in NVIDIA service. Replaces OpenRouter, whose free tier allows 50 requests a day |
| Bot model | Nemotron 3 Super 120B, thinking off | 97.0% of turns passed and ~0.69 s median to first answer in Pipecat's voice-readiness benchmark, inside its 0.7 s guideline |
| Backup model | Nemotron 3 Ultra | Top score (100%) in the same benchmark; slower, so used only when the bot model times out or errors |
| Judge model | gpt-oss-120b on the NVIDIA API | A different model family from the bot, so the bot is not grading itself. Speed does not matter for judging |
| Speech | ElevenLabs Flash v2.5, swappable | ~100 ms model latency; Sarvam Bulbul V4 Flash is the comparison |
| Demo | Laptop mic and speaker | Telephony is days of plumbing; listed under "what we cut" |
| OTP | Mocked, with an enforce on/off switch | Lets us reproduce the "balance without OTP" failure on demand |
| Waiver request | Callback request, reason `waiver_request` | The brief says a human agent will call back |
| Before OTP | Confirm identity and that a payment is overdue, no amounts | The brief bans only the balance; a reminder needs some context |
| Outcome | POST to a webhook.site URL, plus a local copy | The brief says a webhook is enough |

Accounts needed: Sarvam, ElevenLabs, NVIDIA (join the free NVIDIA Developer Program and create an API key on build.nvidia.com), webhook.site.

Before stage 1, confirm on build.nvidia.com that all three model IDs are available to your key, and note how each model's thinking is switched off. NVIDIA logs requests on its free endpoints; that is acceptable because all customer data here is fictional.

## 2. Architecture

```
Voice mode
  mic → Sarvam STT → [turn manager] → LLM (NVIDIA API) ⇄ tools → [guardrail] → [speech normaliser] → ElevenLabs TTS → speaker
                                                   │
                                                   └→ record_outcome → outcome builder → webhook + runs/outcomes/

Text mode (evals)
  scripted or simulated customer text → same agent core → bot text
```

- **Agent core** (`agent/`): system prompt by version, tools, call state (OTP verified, elapsed time, outcome), outcome builder. No audio code here.
- **Voice pipeline** (`voice/`): Pipecat pipeline that wraps the agent core.
- **Tools** (mocked bank backend):
  - `send_otp(customer_id)` and `verify_otp(customer_id, code)`
  - `get_account_summary(customer_id)`: balance, minimum due, days past due, late fee (computed in code from the ₹10,000 rule), monthly interest rate. Gated by OTP when `ENFORCE_OTP=true`
  - `record_outcome(outcome_type, details)`: validates against the schema in `CLAUDE.md`, then ends the call
- **Bot versions**: `v1` = the bank's starting prompt, unchanged. `v2` = our rewritten prompt plus code guardrails. Same model for both so the comparison measures our changes only.

Repo layout:

```
CLAUDE.md
README.md
.env.example
requirements.txt
config.py
agent/        core.py  prompts/v1.md  prompts/v2.md  tools.py  outcome.py  mock_bank.py
voice/        pipeline.py  tts.py  normaliser.py  guardrail.py
evals/        scenarios/  run_evals.py  judge.py  checks.py
runs/         transcripts/  outcomes/  recordings/  results/
scripts/      spike.py
```

## 3. Build stages

| # | Stage | Done when |
|---|---|---|
| 1 | Voice spike | One spoken round trip works; latency of each stage logged; both models measured |
| 2 | Agent core in text, v1 | A full call runs in the terminal on the v1 prompt; outcome reaches the webhook |
| 3 | Eval harness | Scenarios run in text mode, scored, results saved as CSV; v1 baseline recorded |
| 4 | v2 | New prompt plus guardrails; evals rerun; v1 vs v2 table produced |
| 5 | Voice wrap | Full calls by voice, call timer, recordings and transcripts saved |
| 6 | Repo polish | README, sample transcripts, `.env.example`, clean history |

Stage 3's scenario list and scoring rules are decided in phase 2 before that stage runs.

## 4. Claude Code prompts

Paste one prompt per session. Each assumes `CLAUDE.md` is in the repo root.

### Stage 0: Repo setup

```
Set up this repo for the project described in CLAUDE.md.
- Create the folder layout from docs/BUILD_PLAN.md section 2, with empty modules and a README stub.
- Add requirements.txt with pipecat-ai and the extras needed for Sarvam, ElevenLabs, NVIDIA (pipecat-ai[nvidia]) and local audio. Check Pipecat's current docs for the exact extras names.
- Add .env.example with SARVAM_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, NVIDIA_API_KEY, NVIDIA_BASE_URL, BOT_MODEL, BACKUP_MODEL, JUDGE_MODEL, WEBHOOK_URL, ENFORCE_OTP, BOT_VERSION, TTS_PROVIDER.
- Add config.py that loads these with sensible defaults (NVIDIA_BASE_URL=https://integrate.api.nvidia.com/v1, models from CLAUDE.md, ENFORCE_OTP=true, BOT_VERSION=v2, TTS_PROVIDER=elevenlabs).
- Add .gitignore covering .env, runs/, __pycache__, audio files.
Commit as "Repo scaffold". Do not write any agent logic yet.
```

### Stage 1: Voice spike

```
Build scripts/spike.py: the smallest Pipecat pipeline that proves the stack works end to end.
- Local mic and speaker transport, Sarvam STT, Pipecat's NvidiaLLMService using BOT_MODEL and NVIDIA_BASE_URL with a one-line system prompt ("You are a polite assistant. Reply in one short English sentence."), ElevenLabs Flash v2.5 TTS. Pass the model through the service's settings object, not the deprecated model argument.
- Turn thinking off for the model. Check NVIDIA's API docs for how this model does it (for example a system-prompt flag or a chat template setting) and tell me what you found. Confirm no thinking text reaches the speech step.
- Enable Pipecat metrics and print, per turn: STT final transcript time, LLM time to first token, TTS time to first audio, and total time from end of my speech to first bot audio.
- Add a --model flag so I can rerun with BACKUP_MODEL.
- Also write scripts/llm_latency.py that sends the same 10 short prompts to BOT_MODEL, BACKUP_MODEL and JUDGE_MODEL through the NVIDIA API and reports median and p95 time to first token, plus any errors or empty replies. Include one prompt with a tool definition to confirm each model returns a proper tool call.
Do not build the collections logic. Show me how to run both scripts.
```

After this stage: record the latency numbers, and check whether Sarvam returns Hindi words in Devanagari or Latin script.

### If stages 0–1 were already built on OpenRouter

```
We are moving model calls from OpenRouter to the NVIDIA API directly. Read the updated CLAUDE.md first.
- Replace OpenRouter everywhere with Pipecat's NvidiaLLMService (pipecat-ai[nvidia]) and, outside Pipecat, an OpenAI-compatible client pointed at NVIDIA_BASE_URL.
- In .env.example and config.py: remove OPENROUTER_API_KEY; add NVIDIA_API_KEY and NVIDIA_BASE_URL (default https://integrate.api.nvidia.com/v1); set BOT_MODEL, BACKUP_MODEL and JUDGE_MODEL defaults to the IDs in CLAUDE.md.
- Update scripts/spike.py and scripts/llm_latency.py to match the stage 1 prompt in docs/BUILD_PLAN.md, then show me how to rerun them.
- Search the repo for any remaining "openrouter" references and remove them.
Commit as "Switch model provider to NVIDIA API".
```

### Stage 2: Agent core in text mode, v1

```
Build the agent core described in CLAUDE.md and docs/BUILD_PLAN.md section 2, runnable in text mode only.
- agent/mock_bank.py: 4 fictional customers with name, phone, outstanding balance, minimum due, days past due (between 1 and 30) and a valid OTP. At least one balance at or below ₹10,000 and one above, so the late-fee rule is exercised.
- agent/tools.py: send_otp, verify_otp, get_account_summary, record_outcome. The late fee is computed in code from the rule in CLAUDE.md. When ENFORCE_OTP=true, get_account_summary refuses before OTP is verified and says why; when false it always answers.
- agent/outcome.py: validate the outcome against the schema in CLAUDE.md, write it to runs/outcomes/, POST it to WEBHOOK_URL with one retry, never crash the call if the webhook fails.
- If a call ends without record_outcome being called, run a post-call extraction with JUDGE_MODEL over the transcript and mark captured_by as post_call_extraction.
- agent/prompts/v1.md: the bank's starting prompt, copied exactly from the assignment (I will paste it). v1 receives the account summary in its context because the prompt says it "knows everything about the customer's account".
- agent/core.py: one Agent class that takes customer text and returns bot text, calls tools through the NVIDIA API's OpenAI-compatible tool calling, strips any thinking text from replies, falls back to BACKUP_MODEL on timeout (8 s) or error, and logs every turn, tool call and latency to runs/transcripts/<call_id>.json.
- A CLI: python -m agent.chat --customer C001 --version v1 for a typed conversation.
Commit as "Agent core and v1". Show me one sample transcript.
```

### Stage 3: Eval harness

```
Build the eval harness in evals/, in text mode, using the agent core unchanged.
- A scenario file format (YAML): id, title, customer_id, source (brief or inferred), failure bucket (factual, compliance, scope_drift, adherence), customer turns or a persona for a simulated customer, and expected behaviour.
- Deterministic checks in evals/checks.py, run on every transcript: wrong figures, balance spoken before OTP verified, CIBIL or credit-score mentions, legal threats or legal advice, other-product scope drift, missing or wrong transfer, missing outcome, outcome schema errors, call length.
- An LLM judge in evals/judge.py using JUDGE_MODEL for what code cannot check (tone, whether the reason for non-payment was explored), returning pass/fail plus one line of evidence.
- run_evals.py --version v1|v2 runs every scenario, saves transcripts, and writes runs/results/<version>_<timestamp>.csv with one row per scenario and check, plus a summary of failure rate by bucket.
I will give you the scenario list separately. Start with two placeholder scenarios so the harness can be tested.
Commit as "Eval harness".
```

### Stage 4: v2

```
Build v2 based on the v1 eval results in runs/results/ (read the latest v1 CSV first and summarise the failures before changing anything).
- agent/prompts/v2.md: a rewritten prompt that encodes every rule in CLAUDE.md, the call flow (identify, verify OTP, state dues, find the reason, resolve, confirm, record outcome) and the exact other-products line.
- Code guardrails that do not rely on the prompt:
  - OTP gate on get_account_summary (ENFORCE_OTP).
  - A reply check before speech: every number spoken must come from tool results or config (3.5, 750, 10,000, 2); block CIBIL or credit-score talk, legal threats or advice, and waiver approval. On a violation, replace the sentence with a safe line and log the block.
  - A trigger check on the customer's words for abuse, medical emergency and job loss that forces TRANSFER_TO_HUMAN even if the model misses it.
  - A call timer: at 2:30 the bot moves to close; at 3:00 it records CALLBACK_REQUEST with reason call_time_limit.
- Keep the same model as v1.
Rerun run_evals.py for v2 and produce runs/results/comparison.md: a v1 vs v2 table by scenario and by failure bucket.
Commit as "v2 prompt and guardrails".
```

### Stage 5: Voice wrap

```
Wrap the agent core in a Pipecat voice pipeline in voice/pipeline.py, reusing the agent core unchanged.
- Local mic and speaker, Sarvam STT, the agent core as the LLM step, the v2 reply check as a pipeline step before speech, ElevenLabs Flash v2.5.
- voice/tts.py: a small interface so TTS_PROVIDER=elevenlabs|sarvam switches the speech service with no other code changes.
- voice/normaliser.py: turn ₹, %, dates and amounts into speakable English after the reply check and before speech (for example ₹750 → "seven hundred and fifty rupees").
- Handle barge-in (customer interrupts the bot) using Pipecat's built-in support.
- Save a WAV recording of each call to runs/recordings/ and the transcript as in text mode.
- python -m voice.call --customer C001 --version v2 starts a call.
Commit as "Voice pipeline".
```

### Stage 6: Repo polish

```
Prepare the repo for reviewers.
- README: what it is, the architecture diagram from docs/BUILD_PLAN.md, setup, how to run a text call, a voice call and the evals, and where outcomes, transcripts and results go.
- Copy 2–3 representative transcripts into samples/ (at least one good call and one failure), with a one-line note on each.
- Check .env.example is complete, no secrets are committed, and the code passes ruff.
Commit as "Docs and samples". Do not push until I confirm.
```
