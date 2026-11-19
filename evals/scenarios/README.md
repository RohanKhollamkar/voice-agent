# Scenario files

One file per scenario, S01–S19, taken from `docs/scenarios.csv`. The held-out scenarios H01–H05 (`docs/scenarios_heldout.csv`) are in `evals/scenarios_heldout/`, in the same format with `priority: heldout`; run them with `run_evals.py --set heldout`. v2 is never changed because of them. The comment at the top of each file quotes the CSV's customer setup and lines, and says which lines were added here so the call can reach an end.

## Fields

| Field | Meaning |
|---|---|
| `id`, `title` | From the CSV |
| `customer_id` | A customer in `agent/mock_bank.py` that matches the CSV's customer setup |
| `source` | `brief` (the bank's brief says this must work) or `inferred` (we think it will come up) |
| `category` | The failure the scenario targets: `factual`, `compliance`, `scope_drift` or `adherence` |
| `priority` | `core` or `extra`; `run_evals.py --priority core` runs only the core ones |
| `third_party` | `true` when someone other than the customer answers |
| `customer_turns` | The scripted customer's lines, in order (see below) |
| `customer_replies` | Answers the customer gives only if the bot asks (see below) |
| `persona`, `max_turns` | Instead of a script: a description for a simulated customer |
| `expected` | `behaviour` and `outcome` are the CSV's words, for people. The other keys are what gets checked (see below) |
| `checks`, `notes` | From the CSV, for people |

## What `expected` checks

With no `outcome_type`, any valid outcome passes.

| Key | Checked in code |
|---|---|
| `outcome_type`, `outcome_reason`, `outcome_mode` | The recorded outcome's type, and its reason or payment mode |
| `outcome_amount: full_balance` | The promised amount is the customer's full outstanding balance (also `minimum_due`, or a number of rupees such as `1000`) |
| `outcome_date: today` | The outcome's date is today, tomorrow, yesterday, or the next date of a weekday (`friday`) |
| `outcome_day_of_month: 20` | The promised date is that day of the month the call is made in |
| `outcome_time: "18:00"` | The callback time is that time on the day of the call |
| `follow_ups` | The outcome's `follow_ups` list has each entry, with its reason |
| `bot_must_say` | Each text (such as `3.5%`) appears in something the bot says |
| `no_late_fee: true` | Asked about the late fee, the bot says there is none |
| `readback_before_record: true` | A bot turn before recording states the promised date and amount |
| `bot_ends_at_time_limit: true` | The bot itself ends the call as `CALLBACK_REQUEST` `call_time_limit`, by an estimated 3:30 |

| Key | Used by the judge |
|---|---|
| `reason_explored: false` | The "did the bot explore why the customer has not paid" question does not apply |
| `handled_as_expected` | One rubric sentence; the judge passes or fails the call on it. Absent in most scenarios |

## Scripted customers

`customer_turns` is the ordered script. Each turn is a plain line, said on the customer's next turn, or a line with one trigger:

```yaml
- say: "I already paid it yesterday."
  after_bot_has_said: "₹\\s?\\d"     # wait until any bot reply so far matches (the dues are stated)
- say: "OK, I'll pay on Friday."
  after_bot_says: "review|noted"     # wait until the bot's last reply matches
- say: "..."
  after_tool: send_otp               # wait until the bot has called this tool
```

While a line waits, the customer says "Okay." (or the line's `while_waiting`). If the trigger has not fired after 3 bot turns, the line is said anyway and the run logs `trigger_missed`.

`customer_replies` are answers given only when the bot's last reply asks for them, such as the OTP. They take priority over the script and do not count as waiting. `say` can be a list, used one per ask: a wrong OTP, then another. `after_tool` holds a reply back until the bot has called that tool, so the OTP is read out only once `send_otp` has been called. Scenarios where the customer promises to pay also answer a read-back (the bot stating an amount in rupees and a date) with "Yes, that's right.".

A simulated customer (`persona`) is likewise only told the OTP once `send_otp` has been called.

```yaml
customer_replies:
  - when_bot_says: "\\bOTP\\b|one[- ]time|\\bcode\\b"
    say: "{otp}"                     # {otp} becomes the customer's one-time password
    after_tool: send_otp             # only once the code has actually been sent
```

Patterns are regular expressions and ignore case.
