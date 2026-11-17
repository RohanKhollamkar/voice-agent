"""Compare two eval runs (for example v1 and v2) and write runs/results/comparison.md.

Run from the repo root:
    python -m evals.compare runs/results/v1_<stamp>.csv runs/results/v2_<stamp>.csv

Both runs must have been scored by the same checks. Rates are means across the
runs in each file, as in the run summaries.
"""

import argparse
import csv
import json
from pathlib import Path

import config
from evals.run_evals import CATEGORIES


def _load(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def _scored(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["result"] in ("pass", "fail")]


def _failed(rows: list[dict]) -> int:
    return sum(r["result"] == "fail" for r in rows)


def _pct(failed: int, applied: int) -> str:
    return f"{failed / applied:.0%} ({failed}/{applied})" if applied else "n/a"


def _scenario_level(rows: list[dict]) -> tuple[int, int]:
    """Calls (scenario × run) with at least one failed check, out of all calls."""
    calls = {(r["run"], r["scenario_id"]) for r in rows}
    failed = {(r["run"], r["scenario_id"]) for r in rows if r["result"] == "fail"}
    return len(failed), len(calls)


def _interventions(rows: list[dict]) -> dict[str, int]:
    """How often v2's code guardrails acted, counted from the transcripts."""
    counts = {
        "reply sentences blocked": 0,
        "transfers forced": 0,
        "time-limit closes": 0,
    }
    counts["promises refused"] = 0
    counts["goodbyes without an outcome, nudged"] = 0
    counts["nudges that led to a recorded outcome"] = 0
    for path in dict.fromkeys(r["transcript_path"] for r in rows):
        try:
            events = json.loads(Path(path).read_text(encoding="utf-8"))["events"]
        except FileNotFoundError:
            continue
        for event in events:
            if event["type"] == "guardrail_block":
                counts["reply sentences blocked"] += 1
            if event["type"] == "outcome_nudge":
                counts["goodbyes without an outcome, nudged"] += 1
                recorded_after = any(
                    e["type"] == "tool_call"
                    and e["name"] == "record_outcome"
                    and e["result"].get("recorded") is True
                    for e in events[events.index(event) :]
                )
                counts["nudges that led to a recorded outcome"] += recorded_after
            if event["type"] == "tool_call" and event.get("recorded_by") == "guardrail":
                reason = event["arguments"]["details"]["reason"]
                key = (
                    "time-limit closes"
                    if reason == "call_time_limit"
                    else "transfers forced"
                )
                counts[key] += 1
            if (
                event["type"] == "tool_call"
                and event["name"] == "record_outcome"
                and "Not recorded" in str(event["result"].get("error", ""))
            ):
                counts["promises refused"] += 1
    return counts


def compare(old_path: str, new_path: str) -> str:
    old, new = _load(old_path), _load(new_path)
    a, b = old[0]["bot_version"], new[0]["bot_version"]
    runs_a, runs_b = len({r["run"] for r in old}), len({r["run"] for r in new})
    so, sn = _scored(old), _scored(new)
    lines = [
        f"# {a} vs {b}",
        "",
        f"- {a}: `{old_path}` ({runs_a} runs)",
        f"- {b}: `{new_path}` ({runs_b} runs)",
        "",
        "Each cell is the failure rate with (failed/applicable) counted over all runs.",
        "A call is one scenario in one run.",
        "",
        "## Overall",
        "",
        f"| | {a} | {b} |",
        "|---|---|---|",
        (
            f"| Calls with at least one failed check | {_pct(*_scenario_level(old))} "
            f"| {_pct(*_scenario_level(new))} |"
        ),
        (
            f"| Failed checks out of applicable checks | {_pct(_failed(so), len(so))} "
            f"| {_pct(_failed(sn), len(sn))} |"
        ),
        "",
        "## By failure bucket",
        "",
        (
            "Check level: failed checks of that bucket, out of applicable checks of that bucket,"
            " across all scenarios."
        ),
        "",
        f"| Bucket | {a} | {b} |",
        "|---|---|---|",
    ]
    for category in CATEGORIES:
        mine_a = [r for r in so if r["check_category"] == category]
        mine_b = [r for r in sn if r["check_category"] == category]
        lines.append(
            f"| {category} | {_pct(_failed(mine_a), len(mine_a))} "
            f"| {_pct(_failed(mine_b), len(mine_b))} |"
        )

    lines += [
        "",
        "## By scenario",
        "",
        (
            "Failed checks out of applicable checks, and in how many runs the scenario passed"
            " every check."
        ),
        "",
        (
            f"| Scenario | Bucket | {a} failed checks | {a} clean runs | {b} failed checks "
            f"| {b} clean runs |"
        ),
        "|---|---|---|---|---|---|",
    ]
    for scenario_id in dict.fromkeys(r["scenario_id"] for r in new):
        cells = []
        for rows, runs in ((so, runs_a), (sn, runs_b)):
            mine = [r for r in rows if r["scenario_id"] == scenario_id]
            dirty = {r["run"] for r in mine if r["result"] == "fail"}
            cells += [_pct(_failed(mine), len(mine)), f"{runs - len(dirty)}/{runs}"]
        title = next(r["title"] for r in new if r["scenario_id"] == scenario_id)
        category = next(r["category"] for r in new if r["scenario_id"] == scenario_id)
        lines.append(
            f"| {scenario_id} {title} | {category} | " + " | ".join(cells) + " |"
        )

    lines += [
        "",
        "## By rule",
        "",
        f"| Check | {a} | {b} | {b} fails in |",
        "|---|---|---|---|",
    ]
    for check in dict.fromkeys(r["check"] for r in new):
        mine_a = [r for r in so if r["check"] == check]
        mine_b = [r for r in sn if r["check"] == check]
        where = sorted({r["scenario_id"] for r in mine_b if r["result"] == "fail"})
        lines.append(
            f"| {check} | {_pct(_failed(mine_a), len(mine_a))} "
            f"| {_pct(_failed(mine_b), len(mine_b))} | {' '.join(where)} |"
        )

    extracted = {
        version: sum(
            r["check"] == "missing_outcome" and "post_call_extraction" in r["evidence"]
            for r in rows
        )
        for version, rows in ((a, old), (b, new))
    }
    calls = {
        a: runs_a * len({r["scenario_id"] for r in old}),
        b: runs_b * len({r["scenario_id"] for r in new}),
    }
    lines += [
        "",
        "## How the outcomes were captured",
        "",
        (
            f"- Outcome not recorded by the bot itself (read off the transcript after the call): "
            f"{a} {extracted[a]} of {calls[a]} calls, {b} {extracted[b]} of {calls[b]} calls."
        ),
        "",
        f"## {b}'s code guardrails in action",
        "",
        (
            "Counted from the transcripts: every place where code acted instead of the model."
            " Blocks, refusals and nudges show the prompt not holding; forced transfers and"
            " time-limit closes act before the model is asked."
        ),
        "",
    ]
    lines += [f"- {name}: {count}" for name, count in _interventions(new).items()]
    lines += [
        "",
        "## Notes",
        "",
        (
            "- Call length is estimated from words spoken, because text mode has no audio; "
            "real timing is tested in voice."
        ),
        (
            "- A forced transfer is recorded before the model is asked, so in those calls the"
            " transfer checks pass because of code, not the prompt."
        ),
        (
            "- The code checks and v2's guardrails target the same rules. They were written "
            "separately, but a guardrail that blocks a sentence also stops the matching check "
            "from failing, so read the guardrail counts above next to the pass rates."
        ),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compare two eval runs.")
    parser.add_argument("old")
    parser.add_argument("new")
    parser.add_argument(
        "--out", default=str(config.RUNS_DIR / "results" / "comparison.md")
    )
    args = parser.parse_args()
    Path(args.out).write_text(compare(args.old, args.new), encoding="utf-8")
    print(f"Wrote {args.out}")
