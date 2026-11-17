"""Run the scenarios against one bot version, in text mode, and score the calls.

Run from the repo root:
    python -m evals.run_evals --version v1
    python -m evals.run_evals --version v1 --priority core
    python -m evals.run_evals --version v1 --scenario S03
    python -m evals.run_evals --version v1 --runs 3

Writes runs/results/<version>_<timestamp>.csv (one row per scenario and check) and
a summary next to it. Transcripts go to runs/transcripts/ as for any call.
The scenario file format is described in evals/scenarios/README.md.
"""

import argparse
import asyncio
import csv
import json
import re
from pathlib import Path

import yaml
from openai import AsyncOpenAI, OpenAIError

import config
from agent import mock_bank
from agent.core import Agent, now
from agent.retry import retry_on_rate_limit
from agent.tools import TOOLS
from evals.checks import Check, run_checks
from evals.judge import judge_call

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
CATEGORIES = ("factual", "compliance", "scope_drift", "adherence")
HANGUP = "[HANGUP]"

# Scripted customers: a line can wait for a trigger. While it waits, the customer
# says WAITING_LINE to let the bot carry on. After this many bot turns without
# the trigger, the line is played anyway and logged, so a run never stalls.
MAX_WAIT_BOT_TURNS = 3
WAITING_LINE = "Okay."
TRIGGER_KEYS = ("after_tool", "after_bot_says", "after_bot_has_said")

CUSTOMER_PROMPT = """\
You are playing a bank customer in a phone call, to test the bank's collections bot.
You are {name}. The bank is calling about your overdue credit card payment.

Who you are and how you behave:
{persona}

Stay inside this description. Do not invent new facts about yourself (an illness, a
job loss, a payment you have made) unless the description says so.
If you are asked for a one-time password, it is {otp}.
Reply with only the words the customer says, as spoken on a phone call.
When the call is over, or you would hang up, reply with exactly {hangup}.
"""


def load_scenarios(only: str | None = None, priority: str = "all") -> list[dict]:
    """Read and check every scenario file. A broken file stops the run with a clear error."""
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in (
            "id",
            "title",
            "customer_id",
            "source",
            "category",
            "priority",
            "expected",
        ):
            if key not in scenario:
                raise ValueError(f"{path.name}: missing '{key}'")
        if scenario["source"] not in ("brief", "inferred"):
            raise ValueError(f"{path.name}: source must be brief or inferred")
        if scenario["category"] not in CATEGORIES:
            raise ValueError(f"{path.name}: category must be one of {list(CATEGORIES)}")
        if scenario["priority"] not in ("core", "extra"):
            raise ValueError(f"{path.name}: priority must be core or extra")
        if ("customer_turns" in scenario) == ("persona" in scenario):
            raise ValueError(f"{path.name}: give customer_turns or persona, not both")
        if "customer_turns" in scenario:
            scenario["customer_turns"] = [
                _scripted_line(turn, path.name) for turn in scenario["customer_turns"]
            ]
        for reply in scenario.get("customer_replies", []):
            allowed = {"when_bot_says", "say", "after_tool"}
            if not {"when_bot_says", "say"} <= set(reply) <= allowed:
                raise ValueError(
                    f"{path.name}: a customer reply needs when_bot_says and say, "
                    "and may have after_tool"
                )
            if reply.get("after_tool", "send_otp") not in TOOLS:
                raise ValueError(
                    f"{path.name}: after_tool must be one of {list(TOOLS)}"
                )
            re.compile(reply["when_bot_says"])  # raises on a broken pattern
            if isinstance(reply["say"], str):
                reply["say"] = [reply["say"]]
        if "behaviour" not in scenario["expected"]:
            raise ValueError(f"{path.name}: expected needs a 'behaviour' line")
        mock_bank.get_customer(scenario["customer_id"])  # raises if unknown
        scenarios.append(scenario)
    if priority == "core":
        scenarios = [s for s in scenarios if s["priority"] == "core"]
    if only:
        scenarios = [s for s in scenarios if s["id"] == only]
        if not scenarios:
            raise ValueError(f"No scenario with id '{only}'")
    return scenarios


def _scripted_line(turn: str | dict, file_name: str) -> dict:
    """Check one scripted customer line and return it as {"say": ..., trigger...}."""
    line = {"say": turn} if isinstance(turn, str) else turn
    allowed = {"say", "while_waiting", *TRIGGER_KEYS}
    if "say" not in line or set(line) - allowed:
        raise ValueError(
            f"{file_name}: a customer turn needs 'say' and only {sorted(allowed)}"
        )
    if sum(key in line for key in TRIGGER_KEYS) > 1:
        raise ValueError(f"{file_name}: a customer turn can have only one trigger")
    if "after_tool" in line and line["after_tool"] not in TOOLS:
        raise ValueError(f"{file_name}: after_tool must be one of {list(TOOLS)}")
    for key in ("after_bot_says", "after_bot_has_said"):
        if key in line:
            re.compile(line[key])  # raises on a broken pattern
    return line


def trigger_fired(line: dict, agent: Agent, bot_reply: str) -> bool:
    """Has the moment this scripted line is waiting for arrived?"""
    if "after_tool" in line:  # the bot has called this tool at some point in the call
        return any(
            e["type"] == "tool_call" and e["name"] == line["after_tool"]
            for e in agent.events
        )
    if "after_bot_says" in line:  # the bot's last reply matches this pattern
        return re.search(line["after_bot_says"], bot_reply, re.IGNORECASE) is not None
    if "after_bot_has_said" in line:  # any bot reply so far in the call matches
        pattern = re.compile(line["after_bot_has_said"], re.IGNORECASE)
        return any(
            e["type"] == "bot" and pattern.search(e["text"]) for e in agent.events
        )
    return True  # no trigger: play on the next turn


def reply_to_question(
    scenario: dict, used: dict, bot_reply: str, agent: Agent
) -> str | None:
    """customer_replies are answers the customer gives only if asked ("the OTP, when the
    bot asks for it"). If the bot's last reply asks, return the next unused answer. A
    reply with after_tool waits until the bot has called that tool: a customer cannot
    read out a code that has not been sent."""
    for number, reply in enumerate(scenario.get("customer_replies", [])):
        if used.get(number, 0) >= len(reply["say"]):
            continue
        sent = (
            any(
                e["type"] == "tool_call" and e["name"] == reply["after_tool"]
                for e in agent.events
            )
            if "after_tool" in reply
            else True
        )
        if not sent:
            continue
        if re.search(reply["when_bot_says"], bot_reply, re.IGNORECASE):
            used[number] = used.get(number, 0) + 1
            return reply["say"][used[number] - 1]
    return None


async def play_script(
    agent: Agent, scenario: dict, bot_reply: str, pace: float
) -> list[str]:
    """Play the scripted customer. Each turn the customer first answers a question the
    bot has just asked (customer_replies), otherwise says the next line in order, at its
    trigger. Returns the lines whose trigger never fired and which were played anyway."""
    otp = mock_bank.get_customer(scenario["customer_id"])["otp"]

    async def say(text: str) -> str:
        await asyncio.sleep(pace)  # stay under the provider's requests-per-minute limit
        return await agent.respond(text.replace("{otp}", otp))

    missed, used = [], {}
    for line in scenario["customer_turns"]:
        waited = (
            1  # bot turns this line has waited through; the one just heard is the first
        )
        while not agent.ended:
            answer = reply_to_question(scenario, used, bot_reply, agent)
            if answer is not None:  # answering a question does not count as waiting
                bot_reply = await say(answer)
            elif trigger_fired(line, agent, bot_reply):
                break
            elif waited >= MAX_WAIT_BOT_TURNS:
                trigger = next(
                    f"{key}: {line[key]}" for key in TRIGGER_KEYS if key in line
                )
                missed.append(f'"{line["say"]}" ({trigger})')
                break
            else:
                bot_reply = await say(line.get("while_waiting", WAITING_LINE))
                waited += 1
        if agent.ended:
            break
        bot_reply = await say(line["say"])

    # The script is done; keep answering direct questions (a last OTP or mode) if asked.
    while not agent.ended:
        answer = reply_to_question(scenario, used, bot_reply, agent)
        if answer is None:
            break
        bot_reply = await say(answer)
    return missed


async def simulated_customer_line(
    client: AsyncOpenAI, scenario: dict, spoken: list[tuple[str, str]]
) -> str:
    """Ask CUSTOMER_MODEL for the customer's next line. Hangs up if the model fails."""
    customer = mock_bank.get_customer(scenario["customer_id"])
    messages = [
        {
            "role": "system",
            "content": CUSTOMER_PROMPT.format(
                name=customer["name"],
                persona=" ".join(scenario["persona"].split()),
                otp=customer["otp"],
                hangup=HANGUP,
            ),
        }
    ]
    # From the simulated customer's side, the bot is the "user" it is replying to.
    for speaker, text in spoken:
        messages.append(
            {"role": "user" if speaker == "bot" else "assistant", "content": text}
        )
    try:
        response = await retry_on_rate_limit(
            lambda: client.chat.completions.create(
                model=config.CUSTOMER_MODEL,
                messages=messages,
                timeout=config.EXTRACTION_TIMEOUT_SECONDS,
                extra_body=config.LLM_EXTRA_BODY,
            )
        )
        return (response.choices[0].message.content or "").strip() or HANGUP
    except (OpenAIError, IndexError) as failure:
        print(f"    simulated customer failed ({type(failure).__name__}); hanging up")
        return HANGUP


async def run_call(
    client: AsyncOpenAI, scenario: dict, version: str, pace: float
) -> tuple[dict, list[str]]:
    """Play one scenario against the bot. Returns the finished transcript and any
    scripted lines that were played without their trigger."""
    agent = Agent(scenario["customer_id"], version, client=client)
    bot_reply = await agent.start()

    missed = []
    if "customer_turns" in scenario:
        missed = await play_script(agent, scenario, bot_reply, pace)
    else:
        spoken = [("bot", bot_reply)]
        for _ in range(scenario.get("max_turns", 10)):
            if agent.ended:
                break
            await asyncio.sleep(pace)
            line = await simulated_customer_line(client, scenario, spoken)
            if HANGUP in line:
                break
            spoken.append(("customer", line))
            spoken.append(("bot", await agent.respond(line)))

    await agent.finish()
    return json.loads(agent.transcript_path.read_text(encoding="utf-8")), missed


def _rate(failed: int, applied: int) -> float | None:
    return failed / applied if applied else None


def _mean_range(rates: list[float | None]) -> str:
    """ "47% [45%–50%]": the mean across runs, then the lowest and highest run."""
    rates = [rate for rate in rates if rate is not None]
    if not rates:
        return "not applicable"
    mean = sum(rates) / len(rates)
    if len(rates) == 1:
        return f"{mean:.0%}"
    return f"{mean:.0%} [{min(rates):.0%}–{max(rates):.0%}]"


def summarise(rows: list[dict], version: str) -> str:
    """The run as text: overall and by category at scenario level and check level, by
    rule, a spot-check list, and every failure with its evidence. With several runs,
    each rate is the mean across runs with the range across runs."""
    runs = sorted({row["run"] for row in rows})
    scenario_ids = list(dict.fromkeys(row["scenario_id"] for row in rows))
    scored = [r for r in rows if r["result"] in ("pass", "fail")]
    failed = [r for r in scored if r["result"] == "fail"]

    def per_run(of: list[dict]) -> list[list[dict]]:
        return [[r for r in of if r["run"] == run] for run in runs]

    def scenarios_in(of: list[dict]) -> int:
        return len({r["scenario_id"] for r in of})

    def check_level(of: list[dict]) -> str:
        return _mean_range(
            [_rate(sum(r["result"] == "fail" for r in a), len(a)) for a in per_run(of)]
        )

    scenario_level = _mean_range(
        [_rate(scenarios_in(f), len(scenario_ids)) for f in per_run(failed)]
    )
    overall = f"{check_level(scored)}  ({len(failed)} of {len(scored)} over all runs)"
    lines = [
        f"Eval summary: bot {version}, {len(scenario_ids)} scenarios, {len(runs)} run(s)",
        "Rates are the mean across runs, with [lowest–highest run] when there are several.",
        "",
        "Overall",
        f"  scenario level (scenarios with at least one failed check):  {scenario_level}",
        f"  check level (failed checks out of applicable checks):       {overall}",
        "",
        "By category (scenarios that target it; scenario level = failed a check in that",
        "category; check level = failed checks out of applicable checks on those scenarios)",
        f"  {'category':12} {'scenarios':>9}  {'scenario level':22} check level",
    ]
    for category in CATEGORIES:
        targeting = [r for r in scored if r["category"] == category]
        if not targeting:
            lines.append(
                f"  {category:12} untested (no scenario in this run targets it)"
            )
            continue
        count = scenarios_in(targeting)
        in_category = [
            r
            for r in targeting
            if r["check_category"] == category and r["result"] == "fail"
        ]
        level = _mean_range(
            [_rate(scenarios_in(f), count) for f in per_run(in_category)]
        )
        lines.append(f"  {category:12} {count:>9}  {level:22} {check_level(targeting)}")

    lines += [
        "",
        "By rule (failure rate; failed/applied in each run; then the scenarios it failed",
        "in, with the number of runs)",
    ]
    for check in dict.fromkeys(row["check"] for row in rows):
        mine = [r for r in scored if r["check"] == check]
        counts = " ".join(
            f"{sum(r['result'] == 'fail' for r in a)}/{len(a)}" for a in per_run(mine)
        )
        where = []
        for scenario_id in scenario_ids:
            times = sum(
                r["result"] == "fail" for r in mine if r["scenario_id"] == scenario_id
            )
            if times:
                where.append(f"{scenario_id}×{times}" if len(runs) > 1 else scenario_id)
        line = f"  {check:27} {check_level(mine):18} {counts:18} {' '.join(where)}"
        lines.append(line.rstrip())

    lines += [
        "",
        "Spot-check list (every waiver_approval and other_product_talk flag, to review by hand)",
    ]
    flags = [
        r for r in failed if r["check"] in ("waiver_approval", "other_product_talk")
    ]
    lines += [
        f"  run {r['run']} {r['scenario_id']} {r['check']}: {r['evidence']}"
        for r in flags
    ]
    if not flags:
        lines.append("  none")

    lines += ["", "Failed checks"]
    lines += [
        f"  run {r['run']} {r['scenario_id']} {r['check']}: {r['evidence']}"
        for r in failed
    ]
    if not failed:
        lines.append("  none")

    missed = {
        (r["run"], r["scenario_id"]): r["trigger_missed"]
        for r in rows
        if r["trigger_missed"]
    }
    if missed:
        lines += ["", "trigger_missed (scripted lines played without their trigger)"]
        lines += [f"  run {run} {sid}  {text}" for (run, sid), text in missed.items()]
    extracted = [
        r
        for r in rows
        if r["check"] == "missing_outcome" and "post_call_extraction" in r["evidence"]
    ]
    calls = len(runs) * len(scenario_ids)
    lines += [
        "",
        f"Outcomes the bot did not record itself: {len(extracted)} of {calls} calls. In those the",
        "outcome was read off the transcript after the call, so a pass on expected_outcome or",
        "transfer there shows what the customer said, not that the bot acted on it.",
    ]
    errors = [r for r in rows if r["result"] == "error"]
    if errors:
        lines += ["", f"Checks that could not run: {len(errors)} (see the CSV)"]
    backup = sorted(
        {
            f"run {r['run']} {r['scenario_id']}"
            for r in rows
            if r["backup_model_used"] == "yes"
        }
    )
    if backup:
        lines += [
            "",
            "Calls where the backup model answered a turn: " + ", ".join(backup),
        ]
    lines += [
        "",
        "Note: call length is estimated from the words spoken, because text mode has no audio.",
        "Real timing, including the 2:30 and 3:00 marks, is tested in voice.",
    ]
    return "\n".join(lines)


async def run_once(
    client: AsyncOpenAI, scenarios: list[dict], version: str, run: int, pace: float
) -> list[dict]:
    """Play every scenario once and return one row per scenario and check."""
    rows = []
    for number, scenario in enumerate(scenarios, start=1):
        transcript, missed = await run_call(client, scenario, version, pace)
        checks: list[Check] = run_checks(transcript, scenario)
        checks += await judge_call(client, transcript, scenario)
        backup_used = any(e["type"] == "llm_error" for e in transcript["events"])
        print(
            f"[run {run}: {number}/{len(scenarios)}] {scenario['id']} {scenario['title']}"
        )
        for line in missed:
            print(f"    trigger_missed {line}")
        for check in checks:
            if check.result in ("fail", "error"):
                print(f"    {check.result.upper():5} {check.name}: {check.evidence}")
            rows.append(
                {
                    "run": run,
                    "scenario_id": scenario["id"],
                    "title": scenario["title"],
                    "source": scenario["source"],
                    "category": scenario["category"],
                    "priority": scenario["priority"],
                    "bot_version": version,
                    "check": check.name,
                    "kind": "judge" if check.name.startswith("judge_") else "code",
                    "check_category": check.category,
                    "result": check.result,
                    "evidence": check.evidence,
                    "backup_model_used": "yes" if backup_used else "no",
                    "trigger_missed": "; ".join(missed),
                    "call_id": transcript["call_id"],
                    "transcript_path": f"runs/transcripts/{transcript['call_id']}.json",
                }
            )
    return rows


async def main(
    version: str,
    only: str | None,
    priority: str,
    runs: int,
    pace: float,
    post_webhook: bool,
) -> None:
    if not post_webhook:
        config.WEBHOOK_URL = (
            ""  # eval calls are not real outcomes; keep them off the webhook
        )
    scenarios = load_scenarios(only, priority)
    client = AsyncOpenAI(
        api_key=config.NVIDIA_API_KEY, base_url=config.NVIDIA_BASE_URL, max_retries=0
    )
    # The runs go side by side to save time; each one plays its scenarios in order. If the
    # summary lists many backup-model calls, the provider is rate-limiting: raise --pace.
    per_run = await asyncio.gather(
        *(run_once(client, scenarios, version, run, pace) for run in range(1, runs + 1))
    )
    rows = [row for run_rows in per_run for row in run_rows]

    results_dir = config.RUNS_DIR / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{version}_{now():%Y%m%d_%H%M%S}"
    csv_path = results_dir / f"{stem}.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    summary = summarise(rows, version)
    (results_dir / f"{stem}_summary.txt").write_text(summary + "\n", encoding="utf-8")
    print(f"\n{summary}\n\nResults: {csv_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the eval scenarios against one bot."
    )
    parser.add_argument("--version", required=True, choices=["v1", "v2"])
    parser.add_argument("--scenario", help="run only the scenario with this id")
    parser.add_argument(
        "--priority",
        choices=["core", "all"],
        default="all",
        help="core runs only the core scenarios; all (the default) adds the extra ones",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="play every scenario this many times; rates are then means with a range",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=1.5,
        help="seconds to wait before each customer turn (provider rate limit)",
    )
    parser.add_argument(
        "--post-webhook",
        action="store_true",
        help="also POST each eval call's outcome to WEBHOOK_URL (off by default)",
    )
    args = parser.parse_args()
    asyncio.run(
        main(
            args.version,
            args.scenario,
            args.priority,
            args.runs,
            args.pace,
            args.post_webhook,
        )
    )
