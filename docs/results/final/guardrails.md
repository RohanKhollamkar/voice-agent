# v2 code guardrails: how often each acted

Counted from the transcripts of the main v2 run (`v2_20261119_112556_rejudged.csv`, 57 calls; commit `de12c92`, judge `moonshotai/kimi-k3.1-pro`).

| Guardrail action | Times | Calls it acted in |
|---|---|---|
| fixed opening line | 57 | 57/57 |
| forced transfer | 9 | 9/57 |
| time-limit close | 0 | 0/57 |
| outcome nudge (goodbye) | 2 | 2/57 |
| outcome nudge (claimed_record_outcome) | 2 | 2/57 |
| outcome nudge (time_limit) | 3 | 3/57 |
| outcome nudge (hang_up) | 2 | 2/57 |
| outcome nudge that led to a recorded outcome | 8 | 8/57 |
| claim nudge (send_otp) | 1 | 1/57 |
| claim nudge (get_account_summary) | 0 | 0/57 |
| sentence blocked (figure) | 1 | 1/57 |
| sentence blocked (figure_before_otp) | 0 | 0/57 |
| sentence blocked (credit_score) | 0 | 0/57 |
| sentence blocked (legal) | 0 | 0/57 |
| sentence blocked (waiver) | 0 | 0/57 |
| promise refused (not yet agreed) | 8 | 1/57 |
| verify_otp refused (no code sent) | 0 | 0/57 |
| get_account_summary refused before OTP | 0 | 0/57 |
| announcement line dropped | 16 | 15/57 |
| date note added | 41 | 36/57 |
| time note at 2:30 | 3 | 3/57 |
| after-call extraction rejected | 1 | 1/57 |

## Passes that come from code, not the prompt

A v2 pass is marked as coming from code when, in that same call, a code guardrail acted on what the check tests: for example `identity_before_disclosure` passes in every call because the opening line is fixed in code, and a `credit_score_mention` pass in a call where a sentence was blocked for credit-score talk is the reply check's work, not the prompt's. The remaining passes are the model following the prompt (with the code guardrails standing by).

| Check | v2 passes | of which code acted in that call | Guardrail actions behind them |
|---|---|---|---|
| third_party_disclosure | 3 | 3 | fixed opening line (3) |
| identity_before_disclosure | 57 | 57 | fixed opening line (57) |
| transfer | 36 | 9 | forced transfer (9) |
| missing_outcome | 56 | 8 | outcome nudge that led to a recorded outcome (8) |
| expected_outcome | 34 | 16 | forced transfer (9), outcome nudge that led to a recorded outcome (7) |

Checks not listed had no v2 pass in a call where a related guardrail acted, so their passes come from the model following the prompt.

## Held-out run (H01–H05, v2), for reference

| Guardrail action | Times |
|---|---|
| announcement line dropped | 2 |
| date note added | 4 |
| fixed opening line | 5 |
| outcome nudge (hang_up) | 2 |
| outcome nudge that led to a recorded outcome | 1 |
| promise refused (not yet agreed) | 1 |
