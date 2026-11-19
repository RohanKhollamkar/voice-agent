# Run notes: final evaluation pass

## Code under test

- Before the pass: `aab17ca`.
- Frozen (step 3) at `481d0b1`: the judge change, the held-out scenarios, `--set`, and the new outcome keys and `verify_after_send` check.
- The runs record `de12c92`: `481d0b1` plus `scripts/final_report.py` and a README section, committed while the runs were in progress. `git diff 481d0b1 de12c92 -- agent voice evals config.py` is empty, so the code under test is the frozen code.
- Nothing in `agent/`, `voice/`, the prompts or the checks changed after the freeze, and no run crashed.
- Judge: `moonshotai/kimi-k3.1-pro`. Post-call extraction and the simulated customer: `nvidia/nemotron-3-ultra-550b-a55b`. Bot: `nvidia/nemotron-3.5-super-vl-120b-a12b`.

## Unit tests

The repository has no unit-test suite. Before the pass, the offline scratch tests for the v2 guards were run against the current code. The claim nudges, announcement dropping and bot name passed. One older scratch test still asserts the old model-generated opening, so it is out of date rather than failing on a regression.

## Runs

| Run | File (raw) | Calls |
|---|---|---|
| v1 main, S01–S19 × 3 | `v1_main_raw.csv` | 57 |
| v2 main, S01–S19 × 3 | `v2_main_raw.csv` | 57 |
| v1 held-out, H01–H05 × 1 | `v1_heldout.csv` | 5 |
| v2 held-out, H01–H05 × 1 | `v2_heldout.csv` | 5 |

## Calls lost or rerun

- No call was lost: every call ran to an outcome or a hang-up, and none was replayed.
- In two v2 calls the bot model failed one turn and the backup model answered it: run 2 S09 (HTTP 502) and run 3 S06 (timeout).
- The judge request failed on five calls: four timeouts at the 60-second limit, and one rate limit. These calls were re-judged on the same saved transcript with the same judge, not replayed. `v1_main.csv` and `v2_main.csv` are the raw files with those verdicts filled in, and each one says "[re-judged: the first judge request failed]".

| Version | Run | Scenario | First failure | Re-judged |
|---|---|---|---|---|
| v1 | 1 | S14 | timeout | still timed out after three more tries; its 3 judge checks count as "could not run" |
| v1 | 3 | S14 | timeout | yes |
| v1 | 3 | S18 | timeout | yes |
| v2 | 2 | S12 | timeout | yes |
| v2 | 3 | S12 | rate limit | yes |
