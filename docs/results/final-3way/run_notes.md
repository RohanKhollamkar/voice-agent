# Run notes: three-way comparison (v1, v2, v2.1)

## What was run

- Code frozen at commit `1432ded` (clean tree). Every row in the CSVs records it.
- Fixed simulated clock: Monday 16 November 2026, 11:00 IST (`run_evals.py --clock` default).
- Main set S01–S19, **2 runs per version** (38 calls per version), concurrency 3.
- Raw results: `runs/results/v1_20261121_192851.csv`, `v2_20261121_192523.csv`,
  `v2.1_20261121_192425.csv` (runs 1–2 of each). The CSVs here are those rows.
- v2.1's changes came from live voice tests, not from the held-out set.

## What differs from the plan, and why

The plan was 3 runs of S01–S19 and 1 run of H01–H05 per version, with the judge on.
The NVIDIA API throttled the account (HTTP 429) for the rest of the session, so only
part of that could be run:

1. **Run 3 dropped.** In run 3, 60–63% of bot turns went to the backup model, and the
   judge timed out on almost every call. Run 3 was replayed 15 times, one call at a time,
   from 16:35 to 02:00 UTC. Every attempt sent 31–39% of bot turns to the backup model
   (the threshold to accept a run was 10%). A one-line test request to the bot model
   failed 14 times out of 15, even with 3 seconds between requests.
2. **Held-out dropped.** The H01–H05 calls had 26–50% of bot turns on the backup model,
   and one further retry was no better (35%). There is no held-out column here.
   Held-out results for v1 and v2 are in `docs/results/final/held_out.md` (Stage 6).
3. **Judge skipped.** The judge (`moonshotai/kimi-k3.1-pro`) took about 3.3 minutes per
   call with errors, at 2 or 4 calls at a time; judging 114 calls would have taken
   about 6 hours. **These reports use code checks only.** The judged v1-vs-v2
   comparison is in `docs/results/final/` (Stage 6, 57 calls per version).

Runs 1–2 are clean: the backup model answered 3 of 221 bot turns in v1, 2 of 244 in v2,
and 1 of 258 in v2.1.

## What the code checks cover

Figures quoted, amount before OTP, CIBIL mentions, legal threats, waiver approval,
identity before disclosure, other-products line, English only, outcome present and
well-formed, expected outcome, call length, and the other code checks in
`evals/checks.py`. Tone, empathy and handling quality are judge checks and are not
measured here.

## Checks asked for in the v2.1 follow-ups

- S01 ("20 tareekh") expects 2026-11-20 on the fixed clock: passes in v2 and v2.1.
- S17 ("after 6 pm") expects 2026-11-16T18:00: passes in v2 and v2.1.
