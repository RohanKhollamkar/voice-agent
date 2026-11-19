"""Stage 6 report: writes docs/results/final/*.md from the final run CSVs.

Run from the repo root, with the four result files of the final pass:
    python -m scripts.final_report V1_MAIN.csv V2_MAIN.csv V1_HELDOUT.csv V2_HELDOUT.csv

Writes comparison.md, held_out.md, guardrails.md, outcomes.md and headline.md, and
copies the four CSVs next to them. Every number comes from the CSVs and the
transcripts they point to; nothing is typed in by hand.
"""

import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT = Path("docs/results/final")
BUCKETS = ("factual", "compliance", "scope_drift", "adherence")


def load(path: str) -> list[dict]:
    return list(csv.DictReader(open(path, encoding="utf-8")))


def scored(rows):
    return [r for r in rows if r["result"] in ("pass", "fail")]


def pct(failed: int, applied: int) -> str:
    return f"{failed / applied:.0%} ({failed}/{applied})" if applied else "n/a"


def rate(rows) -> tuple[int, int]:
    s = scored(rows)
    return sum(r["result"] == "fail" for r in s), len(s)


def calls(rows) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[(r["run"], r["scenario_id"])].append(r)
    return by


def mean_range(values: list[float]) -> str:
    if not values:
        return "n/a"
    mean = sum(values) / len(values)
    if len(values) == 1:
        return f"{mean:.0%}"
    return f"{mean:.0%} [{min(values):.0%}–{max(values):.0%}]"


def per_run(rows, fn) -> list[float]:
    """fn(rows of one run) -> (failed, applied); the rate in each run."""
    out = []
    for run in sorted({r["run"] for r in rows}):
        failed, applied = fn([r for r in rows if r["run"] == run])
        if applied:
            out.append(failed / applied)
    return out


def scenario_level(rows) -> tuple[int, int]:
    c = calls(rows)
    return sum(any(r["result"] == "fail" for r in v) for v in c.values()), len(c)


def transcript(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def meta(rows) -> str:
    return f"commit `{rows[0]['commit']}`, judge `{rows[0]['judge_model']}`"


# ---------------------------------------------------------------- comparison.md


def comparison(v1, v2, p1, p2) -> str:
    runs = len({r["run"] for r in v1})
    L = [
        "# v1 vs v2: main scenarios (S01–S19)",
        "",
        f"- v1: `{Path(p1).name}` ({runs} runs; {meta(v1)})",
        f"- v2: `{Path(p2).name}` ({len({r['run'] for r in v2})} runs; {meta(v2)})",
        "",
        (
            "Each cell is the failure rate pooled over all runs, with (failed/applicable), then the "
            "mean across runs with [lowest–highest run]. A call is one scenario in one run. "
            "Check level: failed checks out of applicable checks. Scenario level: calls with at "
            "least one failed check. Calls that were re-judged or could not be judged are listed "
            "in `run_notes.md`."
        ),
        "",
        "## Overall",
        "",
        "| | v1 | v2 |",
        "|---|---|---|",
    ]
    for label, fn in (
        ("Scenario level: calls with at least one failed check", scenario_level),
        ("Check level: failed checks out of applicable checks", rate),
    ):
        cells = [
            f"{pct(*fn(rows))}; per run {mean_range(per_run(rows, fn))}"
            for rows in (v1, v2)
        ]
        L.append(f"| {label} | {cells[0]} | {cells[1]} |")
    for label, kind in (("Code checks only", "code"), ("Judge checks only", "judge")):
        cells = [
            pct(*rate([r for r in rows if r["kind"] == kind])) for rows in (v1, v2)
        ]
        L.append(f"| {label} (check level) | {cells[0]} | {cells[1]} |")
    errors = [sum(r["result"] == "error" for r in rows) for rows in (v1, v2)]
    L.append(
        f"| Checks that could not run (judge errors) | {errors[0]} | {errors[1]} |"
    )

    L += [
        "",
        "## By failure bucket",
        "",
        "Check level, by the bucket of the check.",
        "",
        "| Bucket | v1 | v2 |",
        "|---|---|---|",
    ]
    for b in BUCKETS:
        cells = []
        for rows in (v1, v2):
            sub = [r for r in rows if r["check_category"] == b]
            cells.append(f"{pct(*rate(sub))}; per run {mean_range(per_run(sub, rate))}")
        L.append(f"| {b} | {cells[0]} | {cells[1]} |")

    L += [
        "",
        "## By rule",
        "",
        "| Check | Kind | v1 | v2 | v2 fails in |",
        "|---|---|---|---|---|",
    ]
    checks = list(dict.fromkeys(r["check"] for r in v1 + v2))
    for name in checks:
        a = [r for r in v1 if r["check"] == name]
        b = [r for r in v2 if r["check"] == name]
        where = Counter(r["scenario_id"] for r in b if r["result"] == "fail")
        kind = (a or b)[0]["kind"]
        L.append(
            f"| {name} | {kind} | {pct(*rate(a))} | {pct(*rate(b))} | "
            + ", ".join(f"{s} ({n})" for s, n in sorted(where.items()))
            + " |"
        )

    L += [
        "",
        "## By scenario",
        "",
        (
            "Failed checks out of applicable checks, and in how many runs the scenario passed "
            "every check."
        ),
        "",
        "| Scenario | Bucket | v1 failed checks | v1 clean runs | v2 failed checks | v2 clean runs |",
        "|---|---|---|---|---|---|",
    ]
    for sid in sorted({r["scenario_id"] for r in v1 + v2}):
        cells = []
        for rows in (v1, v2):
            sub = [r for r in rows if r["scenario_id"] == sid]
            c = calls(sub)
            clean = sum(not any(r["result"] == "fail" for r in v) for v in c.values())
            cells += [pct(*rate(sub)), f"{clean}/{len(c)}"]
        first = next(r for r in v1 + v2 if r["scenario_id"] == sid)
        L.append(
            f"| {sid} {first['title']} | {first['category']} | "
            + " | ".join(cells)
            + " |"
        )

    L += [
        "",
        "## Every v2 failure",
        "",
        "| Run | Scenario | Check | Evidence |",
        "|---|---|---|---|",
    ]
    for r in v2:
        if r["result"] == "fail":
            ev = r["evidence"].replace("|", "/").replace("\n", " ")[:220]
            L.append(f"| {r['run']} | {r['scenario_id']} | {r['check']} | {ev} |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- held_out.md


def held_out(h1, h2, p1, p2) -> str:
    L = [
        "# Held-out scenarios (H01–H05)",
        "",
        (
            "A test set v2 was never changed for: the scenarios were added after v2 was frozen and "
            "run once per version. These numbers are kept apart from the main comparison."
        ),
        "",
        f"- v1: `{Path(p1).name}` ({meta(h1)})",
        f"- v2: `{Path(p2).name}` ({meta(h2)})",
        "",
        "| | v1 | v2 |",
        "|---|---|---|",
        f"| Scenario level: calls with at least one failed check | {pct(*scenario_level(h1))} | {pct(*scenario_level(h2))} |",
        f"| Check level: failed checks out of applicable checks | {pct(*rate(h1))} | {pct(*rate(h2))} |",
        "",
        "## Per scenario",
        "",
    ]
    for sid in sorted({r["scenario_id"] for r in h1 + h2}):
        first = next(r for r in h1 + h2 if r["scenario_id"] == sid)
        L += [f"### {sid} {first['title']}", ""]
        for version, rows in (("v1", h1), ("v2", h2)):
            sub = [r for r in rows if r["scenario_id"] == sid]
            fails = [r for r in sub if r["result"] == "fail"]
            outcome = transcript(sub[0]["transcript_path"]).get("outcome") or {}
            details = (outcome.get("details") or {}).get(
                outcome.get("outcome_type"), {}
            )
            L.append(
                f"- **{version}**: {pct(*rate(sub))} of checks failed. Outcome "
                f"`{outcome.get('outcome_type')}` {json.dumps(details, ensure_ascii=False)} "
                f"({outcome.get('captured_by')}). Transcript `{sub[0]['transcript_path']}`."
            )
            for r in fails:
                ev = r["evidence"].replace("\n", " ")[:300]
                L.append(f"  - FAIL `{r['check']}`: {ev}")
            for r in sub:
                if r["result"] == "error":
                    L.append(f"  - ERROR `{r['check']}`: {r['evidence']}")
        L.append("")
    return "\n".join(L)


# ---------------------------------------------------------------- guardrails.md

# Which check a guardrail action protects, to mark passes that came from code.
PROTECTS = {
    "fixed opening line": ["identity_before_disclosure", "third_party_disclosure"],
    "forced transfer": ["transfer", "expected_outcome"],
    "time-limit close": ["call_length", "missing_outcome", "expected_outcome"],
    "outcome nudge that led to a recorded outcome": [
        "missing_outcome",
        "expected_outcome",
    ],
    "sentence blocked (credit_score)": ["credit_score_mention"],
    "sentence blocked (legal)": ["legal_threat_or_advice"],
    "sentence blocked (waiver)": ["waiver_approval"],
    "sentence blocked (figure_before_otp)": ["amount_before_otp"],
    "sentence blocked (figure)": ["wrong_figures"],
    "get_account_summary refused before OTP": ["amount_before_otp"],
    "promise refused (not yet agreed)": ["unconfirmed_commitment"],
    "verify_otp refused (no code sent)": ["verify_after_send"],
}


def actions(t: dict) -> Counter:
    """Every code guardrail action in one v2 call."""
    c = Counter()
    events = t["events"]
    bots = [e for e in events if e["type"] == "bot"]
    if (
        bots
        and bots[0].get("models") == []
        and "an automated assistant from Mumbai Bank" in bots[0]["text"]
    ):
        c["fixed opening line"] += 1
    for i, e in enumerate(events):
        kind = e["type"]
        if kind == "guardrail_block":
            c[f"sentence blocked ({e['rule']})"] += 1
        elif kind == "outcome_nudge":
            c[f"outcome nudge ({e.get('reason', 'goodbye')})"] += 1
            if any(
                x["type"] == "tool_call"
                and x["name"] == "record_outcome"
                and x["result"].get("recorded") is True
                and x.get("recorded_by") != "guardrail"
                for x in events[i:]
            ):
                c["outcome nudge that led to a recorded outcome"] += 1
        elif kind == "action_nudge":
            c[f"claim nudge ({e['tool']})"] += 1
        elif kind == "discarded_text" and e.get("reason") == "announcement":
            c["announcement line dropped"] += 1
        elif kind == "date_note":
            c["date note added"] += 1
        elif kind == "timer_note":
            c["time note at 2:30"] += 1
        elif kind == "extraction_rejected":
            c["after-call extraction rejected"] += 1
        elif kind == "tool_call":
            res, name = e["result"], e["name"]
            err = str(res.get("error", ""))
            if e.get("recorded_by") == "guardrail":
                reason = e["arguments"]["details"].get("reason")
                c[
                    "time-limit close"
                    if reason == "call_time_limit"
                    else "forced transfer"
                ] += 1
            elif name == "record_outcome" and err.startswith("Not recorded"):
                c["promise refused (not yet agreed)"] += 1
            elif name == "verify_otp" and err.startswith("Refused: no code"):
                c["verify_otp refused (no code sent)"] += 1
            elif name == "get_account_summary" and err.startswith("Refused"):
                c["get_account_summary refused before OTP"] += 1
    return c


def guardrails(v2, h2, p2) -> str:
    totals, in_calls, by_call = Counter(), Counter(), {}
    for path in dict.fromkeys(r["transcript_path"] for r in v2):
        a = actions(transcript(path))
        by_call[path] = a
        totals.update(a)
        in_calls.update(set(a))
    n = len(by_call)
    order = [
        "fixed opening line",
        "forced transfer",
        "time-limit close",
        "outcome nudge (goodbye)",
        "outcome nudge (claimed_record_outcome)",
        "outcome nudge (time_limit)",
        "outcome nudge (hang_up)",
        "outcome nudge that led to a recorded outcome",
        "claim nudge (send_otp)",
        "claim nudge (get_account_summary)",
        "sentence blocked (figure)",
        "sentence blocked (figure_before_otp)",
        "sentence blocked (credit_score)",
        "sentence blocked (legal)",
        "sentence blocked (waiver)",
        "promise refused (not yet agreed)",
        "verify_otp refused (no code sent)",
        "get_account_summary refused before OTP",
        "announcement line dropped",
        "date note added",
        "time note at 2:30",
        "after-call extraction rejected",
    ]
    order += sorted(set(totals) - set(order))
    L = [
        "# v2 code guardrails: how often each acted",
        "",
        f"Counted from the transcripts of the main v2 run (`{Path(p2).name}`, {n} calls; {meta(v2)}).",
        "",
        "| Guardrail action | Times | Calls it acted in |",
        "|---|---|---|",
    ]
    for k in order:
        L.append(f"| {k} | {totals[k]} | {in_calls[k]}/{n} |")

    L += [
        "",
        "## Passes that come from code, not the prompt",
        "",
        (
            "A v2 pass is marked as coming from code when, in that same call, a code guardrail "
            "acted on what the check tests: for example `identity_before_disclosure` passes in "
            "every call because the opening line is fixed in code, and a `credit_score_mention` "
            "pass in a call where a sentence was blocked for credit-score talk is the reply "
            "check's work, not the prompt's. The remaining passes are the model following the "
            "prompt (with the code guardrails standing by)."
        ),
        "",
        "| Check | v2 passes | of which code acted in that call | Guardrail actions behind them |",
        "|---|---|---|---|",
    ]
    by_check = defaultdict(lambda: [0, 0, Counter()])
    for r in v2:
        if r["result"] != "pass":
            continue
        entry = by_check[r["check"]]
        entry[0] += 1
        acted = [
            k
            for k, checks in PROTECTS.items()
            if r["check"] in checks and by_call[r["transcript_path"]][k]
        ]
        if acted:
            entry[1] += 1
            entry[2].update(acted)
    for name in dict.fromkeys(r["check"] for r in v2):
        if name not in by_check:
            continue
        passes, from_code, why = by_check[name]
        if not from_code:
            continue
        L.append(
            f"| {name} | {passes} | {from_code} | "
            + ", ".join(f"{k} ({v})" for k, v in why.most_common())
            + " |"
        )
    L += [
        "",
        (
            "Checks not listed had no v2 pass in a call where a related guardrail acted, so their "
            "passes come from the model following the prompt."
        ),
    ]
    if h2:
        ht = Counter()
        for path in dict.fromkeys(r["transcript_path"] for r in h2):
            ht.update(actions(transcript(path)))
        L += [
            "",
            "## Held-out run (H01–H05, v2), for reference",
            "",
            "| Guardrail action | Times |",
            "|---|---|",
        ] + [f"| {k} | {v} |" for k, v in sorted(ht.items())]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- outcomes.md


def capture(rows) -> Counter:
    c = Counter()
    for path in dict.fromkeys(r["transcript_path"] for r in rows):
        t = transcript(path)
        outcome = t.get("outcome") or {}
        events = t["events"]
        if not outcome.get("outcome_type"):
            c["no outcome"] += 1  # also when after-call extraction was rejected
            continue
        if outcome.get("captured_by") == "post_call_extraction":
            c["read off the transcript after the call (post_call_extraction)"] += 1
            continue
        rec = next(
            (
                e
                for e in events
                if e["type"] == "tool_call"
                and e["name"] == "record_outcome"
                and e["result"].get("recorded") is True
            ),
            None,
        )
        if rec and rec.get("recorded_by") == "guardrail":
            reason = rec["arguments"]["details"].get("reason")
            c[
                "recorded by code (time-limit close)"
                if reason == "call_time_limit"
                else "recorded by code (forced transfer)"
            ] += 1
        elif rec and any(
            e["type"] == "outcome_nudge" for e in events[: events.index(rec)]
        ):
            c["recorded by the bot after a nudge from code"] += 1
        else:
            c["recorded by the bot on its own (record_outcome)"] += 1
    return c


def outcomes(v1, v2, h1, h2) -> str:
    order = [
        "recorded by the bot on its own (record_outcome)",
        "recorded by the bot after a nudge from code",
        "recorded by code (forced transfer)",
        "recorded by code (time-limit close)",
        "read off the transcript after the call (post_call_extraction)",
        "no outcome",
    ]
    sets = [("v1 main", v1), ("v2 main", v2), ("v1 held-out", h1), ("v2 held-out", h2)]
    counts = [
        (name, capture(rows), len({r["transcript_path"] for r in rows}))
        for name, rows in sets
    ]
    L = [
        "# How outcomes were captured",
        "",
        (
            f"Main runs: {meta(v1)}. A call's outcome is either recorded during the call "
            "(`captured_by: tool_call`) or read off the transcript after it by the extraction "
            "model (`captured_by: post_call_extraction`). v1 has a record_outcome tool but no "
            "nudges or code-recorded outcomes."
        ),
        "",
        "| How | " + " | ".join(name for name, _, _ in counts) + " |",
        "|---|" + "---|" * len(counts),
    ]
    for k in order:
        L.append(f"| {k} | " + " | ".join(pct(c[k], n) for _, c, n in counts) + " |")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- headline.md


def headline(v1, v2, h1, h2) -> str:
    rules = []
    for name in dict.fromkeys(r["check"] for r in v1):
        f1, a1 = rate([r for r in v1 if r["check"] == name])
        f2, a2 = rate([r for r in v2 if r["check"] == name])
        if a1 and a2:
            rules.append((round(f1 / a1 - f2 / a2, 2), a1, name, (f1, a1), (f2, a2)))
    rules.sort(
        reverse=True
    )  # biggest drop first; ties go to the rule with more evidence
    top = "; ".join(f"{n} {pct(*a)} → {pct(*b)}" for _, _, n, a, b in rules[:3])
    s1, s2 = scenario_level(v1), scenario_level(v2)
    c1, c2 = rate(v1), rate(v2)
    hs1, hs2 = scenario_level(h1), scenario_level(h2)
    hc1, hc2 = rate(h1), rate(h2)
    runs = len({r["run"] for r in v1})
    lines = [
        "# Headline numbers",
        "",
        f"- Main set (S01–S19, {runs} runs each), scenario level (calls with any failed check): v1 {pct(*s1)}, v2 {pct(*s2)}.",
        f"- Main set, check level (failed checks out of applicable): v1 {pct(*c1)}, v2 {pct(*c2)}.",
        f"- Biggest rule improvements, v1 → v2: {top}.",
        f"- Held-out set (H01–H05, 1 run each), scenario level: v1 {pct(*hs1)}, v2 {pct(*hs2)}; check level: v1 {pct(*hc1)}, v2 {pct(*hc2)}.",
        f"- Judge model: `{v2[0]['judge_model']}` (chosen in judge_choice.md).",
        f"- Commit: `{v2[0]['commit']}`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    p1, p2, ph1, ph2 = sys.argv[1:5]
    v1, v2, h1, h2 = load(p1), load(p2), load(ph1), load(ph2)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "comparison.md").write_text(comparison(v1, v2, p1, p2), encoding="utf-8")
    (OUT / "held_out.md").write_text(held_out(h1, h2, ph1, ph2), encoding="utf-8")
    (OUT / "guardrails.md").write_text(guardrails(v2, h2, p2), encoding="utf-8")
    (OUT / "outcomes.md").write_text(outcomes(v1, v2, h1, h2), encoding="utf-8")
    (OUT / "headline.md").write_text(headline(v1, v2, h1, h2), encoding="utf-8")
    for path, name in (
        (p1, "v1_main.csv"),
        (p2, "v2_main.csv"),
        (ph1, "v1_heldout.csv"),
        (ph2, "v2_heldout.csv"),
    ):
        shutil.copy(path, OUT / name)
    print((OUT / "headline.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
