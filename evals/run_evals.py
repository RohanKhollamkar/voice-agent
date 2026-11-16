"""Run every scenario against one bot version, in text mode, and score the calls.

Run from the repo root:
    python -m evals.run_evals --version v1
    python -m evals.run_evals --version v1 --scenario placeholder_persona_waiver

Writes runs/results/<version>_<timestamp>.csv (one row per scenario and check) and
a summary of failure rate by bucket next to it. Transcripts go to runs/transcripts/
as for any call.
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
from agent.tools import TOOLS
from evals.checks import Check, run_checks
from evals.judge import judge_call

SCENARIOS_DIR = Path(__file__).parent / "scenarios"
BUCKETS = ("factual", "compliance", "scope_drift", "adherence")
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
Reply with only the words the customer says: one or two short sentences, as spoken on
a phone call. Never more than two sentences.
When the call is over, or you would hang up, reply with exactly {hangup}.
"""


def load_scenarios(only: str | None = None) -> list[dict]:
    """Read and check every scenario file. A broken file stops the run with a clear error."""
    scenarios = []
    for path in sorted(SCENARIOS_DIR.glob("*.yaml")):
        scenario = yaml.safe_load(path.read_text(encoding="utf-8"))
        for key in ("id", "title", "customer_id", "source", "bucket", "expected"):
            if key not in scenario:
                raise ValueError(f"{path.name}: missing '{key}'")
        if scenario["source"] not in ("brief", "inferred"):
            raise ValueError(f"{path.name}: source must be brief or inferred")
        if scenario["bucket"] not in BUCKETS:
            raise ValueError(f"{path.name}: bucket must be one of {list(BUCKETS)}")
        if ("customer_turns" in scenario) == ("persona" in scenario):
            raise ValueError(f"{path.name}: give customer_turns or persona, not both")
        if "customer_turns" in scenario:
            scenario["customer_turns"] = [
                _scripted_line(turn, path.name) for turn in scenario["customer_turns"]
            ]
        if "behaviour" not in scenario["expected"]:
            raise ValueError(f"{path.name}: expected needs a 'behaviour' line")
        mock_bank.get_customer(scenario["customer_id"])  # raises if unknown
        scenarios.append(scenario)
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


async def play_script(
    agent: Agent, scenario: dict, bot_reply: str, pace: float
) -> list[str]:
    """Play the scripted customer lines, each at its trigger. Returns the lines whose
    trigger never fired and which were played anyway (trigger_missed)."""
    otp = mock_bank.get_customer(scenario["customer_id"])["otp"]
    missed = []
    for line in scenario["customer_turns"]:
        bot_turns = 1  # the reply the customer has just heard counts as the first
        while not agent.ended and not trigger_fired(line, agent, bot_reply):
            if bot_turns >= MAX_WAIT_BOT_TURNS:
                trigger = next(
                    f"{key}: {line[key]}" for key in TRIGGER_KEYS if key in line
                )
                missed.append(f'"{line["say"]}" ({trigger})')
                break
            await asyncio.sleep(pace)
            bot_reply = await agent.respond(line.get("while_waiting", WAITING_LINE))
            bot_turns += 1
        if agent.ended:
            break
        await asyncio.sleep(pace)  # stay under the provider's requests-per-minute limit
        bot_reply = await agent.respond(line["say"].replace("{otp}", otp))
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
        response = await client.chat.completions.create(
            model=config.CUSTOMER_MODEL,
            messages=messages,
            timeout=config.EXTRACTION_TIMEOUT_SECONDS,
            extra_body=config.LLM_EXTRA_BODY,
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


def summarise(rows: list[dict], version: str) -> str:
    """Failure rate by bucket: the share of scenarios with at least one failed check
    in that bucket."""
    scenario_ids = sorted({row["scenario_id"] for row in rows})
    lines = [
        f"Eval summary: bot {version}, {len(scenario_ids)} scenarios",
        "",
        "Failure rate by bucket (scenarios with at least one failed check in the bucket):",
    ]
    for bucket in BUCKETS:
        failed = {
            r["scenario_id"]
            for r in rows
            if r["bucket"] == bucket and r["result"] == "fail"
        }
        rate = len(failed) / len(scenario_ids) if scenario_ids else 0
        lines.append(f"  {bucket:12} {len(failed)}/{len(scenario_ids)}  ({rate:.0%})")

    lines += ["", "Failed checks:"]
    failures = [r for r in rows if r["result"] == "fail"]
    for row in failures:
        lines.append(f"  {row['scenario_id']}  {row['check']}: {row['evidence']}")
    if not failures:
        lines.append("  none")

    missed = {
        r["scenario_id"]: r["trigger_missed"] for r in rows if r["trigger_missed"]
    }
    if missed:
        lines += ["", "trigger_missed (scripted lines played without their trigger):"]
        lines += [f"  {scenario_id}  {text}" for scenario_id, text in missed.items()]

    errors = [r for r in rows if r["result"] == "error"]
    if errors:
        lines += ["", f"Checks that could not run: {len(errors)} (see the CSV)"]
    backup = sorted({r["scenario_id"] for r in rows if r["backup_model_used"] == "yes"})
    if backup:
        lines += [
            "",
            "Calls where the backup model answered a turn: " + ", ".join(backup),
        ]
    return "\n".join(lines)


async def main(version: str, only: str | None, pace: float, post_webhook: bool) -> None:
    if not post_webhook:
        config.WEBHOOK_URL = (
            ""  # eval calls are not real outcomes; keep them off the webhook
        )
    scenarios = load_scenarios(only)
    client = AsyncOpenAI(
        api_key=config.NVIDIA_API_KEY, base_url=config.NVIDIA_BASE_URL, max_retries=0
    )

    rows = []
    for number, scenario in enumerate(scenarios, start=1):
        print(f"[{number}/{len(scenarios)}] {scenario['id']}")
        transcript, missed = await run_call(client, scenario, version, pace)
        for line in missed:
            print(f"    trigger_missed {line}")
        checks: list[Check] = run_checks(transcript, scenario)
        checks += await judge_call(client, transcript, scenario)
        backup_used = any(e["type"] == "llm_error" for e in transcript["events"])
        for check in checks:
            if check.result in ("fail", "error"):
                print(f"    {check.result.upper():5} {check.name}: {check.evidence}")
            rows.append(
                {
                    "scenario_id": scenario["id"],
                    "title": scenario["title"],
                    "source": scenario["source"],
                    "scenario_bucket": scenario["bucket"],
                    "bot_version": version,
                    "check": check.name,
                    "kind": "judge" if check.name.startswith("judge_") else "code",
                    "bucket": check.bucket,
                    "result": check.result,
                    "evidence": check.evidence,
                    "backup_model_used": "yes" if backup_used else "no",
                    "trigger_missed": "; ".join(missed),
                    "call_id": transcript["call_id"],
                    "transcript_path": f"runs/transcripts/{transcript['call_id']}.json",
                }
            )

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
    asyncio.run(main(args.version, args.scenario, args.pace, args.post_webhook))
