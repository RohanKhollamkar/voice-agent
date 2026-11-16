# Scenario files

One file per scenario, S01–S19, taken from `docs/scenarios.csv`. The comment at the top of each file quotes the CSV's customer setup and lines, and says which lines were added here so the call can reach an end.

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
| `expected` | `behaviour` and `outcome` are the CSV's words, for people. Code checks `outcome_type`, `outcome_reason`, `outcome_mode`, `outcome_time`, `follow_ups` and `bot_must_say` (exact text the bot must say) where given. With no `outcome_type`, any valid outcome passes |
| `checks`, `notes` | From the CSV, for people |

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

`customer_replies` are answers given only when the bot's last reply asks for them, such as the OTP. They take priority over the script and do not count as waiting. `say` can be a list, used one per ask: a wrong OTP, then another.

```yaml
customer_replies:
  - when_bot_says: "\\bOTP\\b|one[- ]time"
    say: "{otp}"                     # {otp} becomes the customer's one-time password
```

Patterns are regular expressions and ignore case.
