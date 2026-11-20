# Judge model choice

Stage 6, step 1. Run on 19 November 2026 at commit `aab17ca` (before the freeze).

## Candidates

`GET /models` on the NVIDIA API listed 32 models. The non-Nemotron chat models were `mistralai/mistral-large-4-1t-a52b`, `moonshotai/kimi-k3.1-pro`, `z-ai/glm-5.3-flash` and the Gemma models; no Llama, Qwen or DeepSeek model was listed. Short test prompt (`Reply with exactly this JSON: {"ok": true}`):

| Model | Test prompt |
|---|---|
| `moonshotai/kimi-k3.1-pro` | answered, 1.6 s |
| `mistralai/mistral-large-4-1t-a52b` | answered, 3.5 s (it reasons first: with a 50-token cap the reasoning used every token and the answer was empty) |
| `z-ai/glm-5.3-flash` | timed out twice; not tried further |

The two strongest that answered, Kimi K3.1 Pro and Mistral Large 4, were the candidates. The current judge is `nvidia/nemotron-3-ultra-550b-a55b`.

## The six transcripts

| Version | Scenario | Call | Code checks found a legal threat or credit-score mention |
|---|---|---|---|
| v1 | S01 | `77b53975-d6ed-4cc4-a0e4-31969181a4d2` | yes |
| v1 | S08 | `f0da022c-c590-4a4c-bb5d-9223284b783b` | yes |
| v1 | S15 | `0c6e1dec-ea14-4a73-9363-28a22f702441` | yes |
| v2 | S01 | `47e1e8a0-8824-43f1-8657-cd0a5ac7ea7f` | no |
| v2 | S15 | `8979a6e6-1c19-4be3-adeb-b41ea1d3e54c` | no |
| v2 | S04 | `e9a2fb91-d977-4fbf-abd1-85f6e46f5623` | no |

v1 from the latest v1 run (`runs/results/v1_20261117_162847.csv`, run 1); v2 from the latest v2 runs (`v2_20261119_010050.csv` for S01 and S15, `v2_20261118_172954.csv` for S04).

## Verdicts

Same prompt and code for every judge (`evals/judge.py`, timeout 60 s). n/a: the question does not apply to that scenario.

| Version | Scenario | Question | Nemotron 3 Ultra (current) | Kimi K3.1 Pro | Mistral Large 4 |
|---|---|---|---|---|---|
| v1 | S01 | tone | fail | fail | error |
| v1 | S01 | reason_explored | pass | fail | error |
| v1 | S08 | tone | fail | fail | error |
| v1 | S08 | reason_explored | fail | fail | error |
| v1 | S15 | tone | fail | fail | error |
| v2 | S01 | tone | pass | pass | error |
| v2 | S01 | reason_explored | pass | pass | error |
| v2 | S15 | tone | pass | pass | error |
| v2 | S04 | tone | pass | pass | error |
| v2 | S04 | reason_explored | pass | pass | error |
| v2 | S04 | handled_as_expected | pass | pass | error |

Every Mistral Large 4 error was `APITimeoutError`: on the full judge prompt it reasons for longer than the 60 s limit.

The one disagreement between Kimi and Nemotron: v1 S01, reason_explored. Nemotron passed it, quoting a read-back ("To confirm: you'll pay the full outstanding amount..."), which is not asking why. Kimi failed it: "After 'Salary late hai,' the bot only said 'That works, Ms. Mehta. To confirm:' without asking why or acknowledging the salary delay." Kimi's verdict matches the rubric.

## The rule

A candidate is eligible if it returned no errors and failed judge_tone on every transcript where the code checks found a legal threat or credit-score mention (here: the three v1 calls). Among eligible candidates, pick the one that agrees most with the other candidate and the current judge.

| Candidate | Errors | Failed tone on all 3 legal/credit calls | Eligible | Agreement |
|---|---|---|---|---|
| Kimi K3.1 Pro | 0 | yes | yes | 10 of 11 applicable verdicts with Nemotron; none comparable with Mistral (all errors) |
| Mistral Large 4 | 11 of 11 | no verdicts | no | – |

## Choice

**`moonshotai/kimi-k3.1-pro`**, the only eligible candidate. `JUDGE_MODEL` in `config.py` is set to it.

Post-call outcome extraction (agent logic) and the simulated customer in persona scenarios used `JUDGE_MODEL` too. So that changing the judge changes nothing else, they now have their own settings, `EXTRACTION_MODEL` and `CUSTOMER_MODEL`, both still `nvidia/nemotron-3-ultra-550b-a55b`.

All verdicts with evidence: `judge_choice_verdicts.json` in this folder.
