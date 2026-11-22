"""Reports comparing any number of bot versions, one column each.

Run from the repo root, one --version per bot, each with its main-set and held-out CSV:
    python -m scripts.compare_report --out docs/results/final-3way \\
        --version v1 V1_MAIN.csv V1_HELDOUT.csv \\
        --version v2 V2_MAIN.csv V2_HELDOUT.csv \\
        --version v2.1 V21_MAIN.csv V21_HELDOUT.csv

Writes comparison.md, held_out.md, guardrails.md, outcomes.md and headline.md, and
copies the CSVs next to them. A held-out CSV given as "-" means no held-out run: then
held_out.md is not written and the other reports leave held-out out. Every number comes from the CSVs and the transcripts they
point to. The helpers are shared with scripts/final_report.py (the two-version report
of docs/results/final/, kept as it was).
"""

import argparse
import json
import shutil
from collections import Counter
from pathlib import Path

from scripts.final_report import (
    BUCKETS,
    actions,
    calls,
    capture,
    load,
    mean_range,
    pct,
    per_run,
    rate,
    scenario_level,
    transcript,
)


def meta(rows) -> str:
    return (
        f"commit `{rows[0]['commit']}`, judge `{rows[0]['judge_model']}`, "
        f"clock `{rows[0].get('clock', 'real')}`"
    )


def table(header: list[str]) -> list[str]:
    return ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]


def comparison(versions: dict) -> str:
    names = list(versions)
    L = ["# Main scenarios (S01–S19): " + ", ".join(names), ""]
    for name, v in versions.items():
        runs = len({r["run"] for r in v["main"]})
        L.append(
            f"- {name}: `{Path(v['main_path']).name}` ({runs} runs; {meta(v['main'])})"
        )
    L += [
        "",
        (
            "Each cell is the failure rate pooled over all runs, with (failed/applicable), then "
            "the mean across runs with [lowest–highest run]. A call is one scenario in one run. "
            "Check level: failed checks out of applicable checks. Scenario level: calls with "
            "at least one failed check."
        ),
        "",
        "## Overall",
        "",
        *table(["", *names]),
    ]
    for label, fn in (
        ("Scenario level", scenario_level),
        ("Check level", rate),
    ):
        cells = [
            f"{pct(*fn(v['main']))}; per run {mean_range(per_run(v['main'], fn))}"
            for v in versions.values()
        ]
        L.append(f"| {label} | " + " | ".join(cells) + " |")
    for label, kind in (("Code checks only", "code"), ("Judge checks only", "judge")):
        cells = [
            pct(*rate([r for r in v["main"] if r["kind"] == kind]))
            for v in versions.values()
        ]
        L.append(f"| {label} (check level) | " + " | ".join(cells) + " |")
    errors = [sum(r["result"] == "error" for r in v["main"]) for v in versions.values()]
    L.append(
        "| Checks that could not run (judge errors) | "
        + " | ".join(map(str, errors))
        + " |"
    )

    L += [
        "",
        "## By failure bucket",
        "",
        "Check level.",
        "",
        *table(["Bucket", *names]),
    ]
    for bucket in BUCKETS:
        cells = []
        for v in versions.values():
            sub = [r for r in v["main"] if r["check_category"] == bucket]
            cells.append(f"{pct(*rate(sub))}; per run {mean_range(per_run(sub, rate))}")
        L.append(f"| {bucket} | " + " | ".join(cells) + " |")

    L += [
        "",
        "## By rule",
        "",
        *table(["Check", "Kind", *names, f"{names[-1]} fails in"]),
    ]
    checks = list(
        dict.fromkeys(r["check"] for v in versions.values() for r in v["main"])
    )
    last = versions[names[-1]]["main"]
    for check in checks:
        cells = [
            pct(*rate([r for r in v["main"] if r["check"] == check]))
            for v in versions.values()
        ]
        kind = next(
            r["kind"]
            for v in versions.values()
            for r in v["main"]
            if r["check"] == check
        )
        where = Counter(
            r["scenario_id"]
            for r in last
            if r["check"] == check and r["result"] == "fail"
        )
        L.append(
            f"| {check} | {kind} | "
            + " | ".join(cells)
            + " | "
            + ", ".join(f"{s} ({n})" for s, n in sorted(where.items()))
            + " |"
        )

    header = ["Scenario", "Bucket"]
    for name in names:
        header += [f"{name} failed checks", f"{name} clean runs"]
    L += [
        "",
        "## By scenario",
        "",
        (
            "Failed checks out of applicable checks, and in how many runs the scenario passed "
            "every check."
        ),
        "",
        *table(header),
    ]
    all_rows = [r for v in versions.values() for r in v["main"]]
    for sid in sorted({r["scenario_id"] for r in all_rows}):
        first = next(r for r in all_rows if r["scenario_id"] == sid)
        cells = []
        for v in versions.values():
            sub = [r for r in v["main"] if r["scenario_id"] == sid]
            c = calls(sub)
            clean = sum(not any(r["result"] == "fail" for r in x) for x in c.values())
            cells += [pct(*rate(sub)), f"{clean}/{len(c)}"]
        L.append(
            f"| {sid} {first['title']} | {first['category']} | "
            + " | ".join(cells)
            + " |"
        )

    for name in names[1:]:
        L += [
            "",
            f"## Every {name} failure",
            "",
            *table(["Run", "Scenario", "Check", "Evidence"]),
        ]
        for r in versions[name]["main"]:
            if r["result"] == "fail":
                evidence = r["evidence"].replace("|", "/").replace("\n", " ")[:220]
                L.append(
                    f"| {r['run']} | {r['scenario_id']} | {r['check']} | {evidence} |"
                )
    return "\n".join(L) + "\n"


def held_out(versions: dict) -> str:
    names = list(versions)
    L = [
        "# Held-out scenarios (H01–H05)",
        "",
        (
            "A test set none of the bots was changed for: run once per version, kept apart from "
            "the main comparison. v2.1's changes came from live voice tests, not from this set."
        ),
        "",
    ]
    for name, v in versions.items():
        L.append(f"- {name}: `{Path(v['heldout_path']).name}` ({meta(v['heldout'])})")
    L += [
        "",
        *table(["", *names]),
        "| Scenario level | "
        + " | ".join(pct(*scenario_level(v["heldout"])) for v in versions.values())
        + " |",
        "| Check level | "
        + " | ".join(pct(*rate(v["heldout"])) for v in versions.values())
        + " |",
        "",
        "## Per scenario",
        "",
    ]
    all_rows = [r for v in versions.values() for r in v["heldout"]]
    for sid in sorted({r["scenario_id"] for r in all_rows}):
        first = next(r for r in all_rows if r["scenario_id"] == sid)
        L += [f"### {sid} {first['title']}", ""]
        for name, v in versions.items():
            sub = [r for r in v["heldout"] if r["scenario_id"] == sid]
            outcome = transcript(sub[0]["transcript_path"]).get("outcome") or {}
            details = (outcome.get("details") or {}).get(
                outcome.get("outcome_type"), {}
            )
            L.append(
                f"- **{name}**: {pct(*rate(sub))} of checks failed. Outcome "
                f"`{outcome.get('outcome_type')}` {json.dumps(details, ensure_ascii=False)} "
                f"({outcome.get('captured_by')}). Transcript `{sub[0]['transcript_path']}`."
            )
            for r in sub:
                if r["result"] in ("fail", "error"):
                    evidence = r["evidence"].replace("\n", " ")[:300]
                    L.append(f"  - {r['result'].upper()} `{r['check']}`: {evidence}")
        L.append("")
    return "\n".join(L)


def guardrails(versions: dict) -> str:
    guarded = {name: v for name, v in versions.items() if name != "v1"}
    totals, in_calls, counts = {}, {}, {}
    for name, v in guarded.items():
        t, c = Counter(), Counter()
        paths = list(dict.fromkeys(r["transcript_path"] for r in v["main"]))
        for path in paths:
            a = actions(transcript(path))
            events = transcript(path)["events"]
            for kind, label in (
                ("other_products_line", "products line spoken by code (v2.1)"),
                ("mode_note", "payment-mode note added (v2.1)"),
            ):
                n = sum(e["type"] == kind for e in events)
                if n:
                    a[label] += n
            for e in events:
                error = (
                    str(e.get("result", {}).get("error", ""))
                    if e["type"] == "tool_call"
                    else ""
                )
                if (
                    "have not read the date and amount back" in error
                    or "yes to your read-back" in error
                ):
                    a["of which: no read-back yet, or no yes to it (v2.1)"] += 1
                if (
                    "busy or asked to be called later" in error
                    or "failed verification" in error
                ):
                    a["callback reason refused: not supported by the call"] += 1
                if e["type"] == "outcome_fallback":
                    a[f"outcome recorded by code after extraction: {e['reason']}"] += 1
            t.update(a)
            c.update(set(a))
        totals[name], in_calls[name], counts[name] = t, c, len(paths)
    keys = sorted(
        {k for t in totals.values() for k in t}, key=lambda k: (k.endswith("(v2.1)"), k)
    )
    names = list(guarded)
    L = [
        "# Code guardrails: how often each acted (" + ", ".join(names) + ")",
        "",
        (
            "Counted from the transcripts of the main runs. Each cell: times it acted, then the "
            "calls it acted in."
        ),
        "",
        *table(["Guardrail action", *names]),
    ]
    for key in keys:
        L.append(
            f"| {key} | "
            + " | ".join(
                f"{totals[n][key]} ({in_calls[n][key]}/{counts[n]} calls)"
                for n in names
            )
            + " |"
        )
    return "\n".join(L) + "\n"


def outcomes(versions: dict) -> str:
    order = [
        "recorded by the bot on its own (record_outcome)",
        "recorded by the bot after a nudge from code",
        "recorded by code (forced transfer)",
        "recorded by code (time-limit close)",
        "read off the transcript after the call (post_call_extraction)",
        "no outcome",
    ]
    columns = []
    for name, v in versions.items():
        for label, key in (("main", "main"), ("held-out", "heldout")):
            rows = v[key]
            if not rows:
                continue
            columns.append(
                (
                    f"{name} {label}",
                    capture(rows),
                    len({r["transcript_path"] for r in rows}),
                )
            )
    L = [
        "# How outcomes were captured",
        "",
        (
            "Recorded during the call (`captured_by: tool_call`), or read off the transcript "
            "afterwards by the extraction model (`post_call_extraction`). Since commit ccd671c an "
            "unsupported extraction in v2 and v2.1 falls back to CALLBACK_REQUEST call_dropped, "
            "also counted under post_call_extraction."
        ),
        "",
        *table(["How", *(c[0] for c in columns)]),
    ]
    for key in order:
        L.append(
            f"| {key} | " + " | ".join(pct(c[key], n) for _, c, n in columns) + " |"
        )
    dropped = []
    for name, v in versions.items():
        n = sum(
            ((transcript(p).get("outcome") or {}).get("details") or {})
            .get("CALLBACK_REQUEST", {})
            .get("reason")
            == "call_dropped"
            for p in dict.fromkeys(r["transcript_path"] for r in v["main"])
        )
        dropped.append(f"{name} {n}")
    L += [
        "",
        "Main-set calls ending as CALLBACK_REQUEST call_dropped: "
        + ", ".join(dropped)
        + ".",
    ]
    return "\n".join(L) + "\n"


def headline(versions: dict) -> str:
    names = list(versions)
    first = versions[names[0]]["main"]
    runs = len({r["run"] for r in first})
    full = runs * len({r["scenario_id"] for r in first})
    has_heldout = all(v["heldout"] for v in versions.values())
    L = [
        "# Headline numbers",
        "",
        (
            f"Main set S01–S19, {runs} runs per version; "
            + ("held-out H01–H05, 1 run. " if has_heldout else "no held-out run. ")
            + f"{meta(versions[names[-1]]['main'])}."
        ),
        "v2.1's changes came from live voice tests, not from the held-out set.",
        "",
        *table(["", *names]),
        "| Main, scenario level (calls with any failed check) | "
        + " | ".join(pct(*scenario_level(v["main"])) for v in versions.values())
        + " |",
        "| Main, check level (failed out of applicable) | "
        + " | ".join(pct(*rate(v["main"])) for v in versions.values())
        + " |",
    ]
    if has_heldout:
        L += [
            "| Held-out, scenario level | "
            + " | ".join(pct(*scenario_level(v["heldout"])) for v in versions.values())
            + " |",
            "| Held-out, check level | "
            + " | ".join(pct(*rate(v["heldout"])) for v in versions.values())
            + " |",
        ]
    L += [
        "",
        f"Rules with {full} calls behind them in every version (failure rate):",
        "",
        *table(["Rule", *names]),
    ]
    checks = list(dict.fromkeys(r["check"] for r in first))
    for check in checks:
        counts = [
            rate([r for r in v["main"] if r["check"] == check])
            for v in versions.values()
        ]
        if all(applied == full for _, applied in counts):
            L.append(f"| {check} | " + " | ".join(pct(*c) for c in counts) + " |")
    return "\n".join(L) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare bot versions.")
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--version",
        nargs=3,
        action="append",
        metavar=("NAME", "MAIN_CSV", "HELDOUT_CSV"),
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    versions = {}
    for name, main_path, heldout_path in args.version:
        versions[name] = {
            "main": load(main_path),
            "heldout": load(heldout_path) if heldout_path != "-" else [],
            "main_path": main_path,
            "heldout_path": heldout_path,
        }
        shutil.copy(main_path, out / f"{name}_main.csv")
        if heldout_path != "-":
            shutil.copy(heldout_path, out / f"{name}_heldout.csv")
    has_heldout = all(v["heldout"] for v in versions.values())
    for file_name, build in (
        ("comparison.md", comparison),
        *((("held_out.md", held_out),) if has_heldout else ()),
        ("guardrails.md", guardrails),
        ("outcomes.md", outcomes),
        ("headline.md", headline),
    ):
        (out / file_name).write_text(build(versions), encoding="utf-8")
    print((out / "headline.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
