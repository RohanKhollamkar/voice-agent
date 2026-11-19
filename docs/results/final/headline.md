# Headline numbers

- Main set (S01–S19, 3 runs each), scenario level (calls with any failed check): v1 100% (57/57), v2 21% (12/57).
- Main set, check level (failed checks out of applicable): v1 47% (399/858), v2 2% (17/909).
- Biggest rule improvements, v1 → v2: required_figures 100% (6/6) → 0% (0/6); two_working_days 100% (3/3) → 0% (0/3); third_party_disclosure 100% (3/3) → 0% (0/3).
- Held-out set (H01–H05, 1 run each), scenario level: v1 100% (5/5), v2 20% (1/5); check level: v1 39% (32/82), v2 1% (1/87).
- Judge model: `moonshotai/kimi-k3.1-pro` (chosen in judge_choice.md).
- Commit: `de12c92`.
