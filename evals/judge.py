"""LLM judge, for what code cannot check: tone, whether the bot explored why the
customer has not paid, and whether the call matched the scenario's expected behaviour.

One request per call, to JUDGE_MODEL. Each verdict is pass or fail (or not
applicable) with one line of evidence quoted from the transcript.
"""

import json

from openai import AsyncOpenAI, OpenAIError

import config
from evals.checks import Check

JUDGE_PROMPT = """\
You are reviewing a call made by a bank's collections voicebot to a customer about an
overdue credit card payment. Judge the BOT only, on three questions.

1. tone: Was the bot polite and respectful throughout, without pressure, threats or
   blame? Firm reminders are fine.
2. reason_explored: Did the bot find out why the customer has not paid, by asking or by
   acknowledging a reason the customer gave? Use null if the question did not apply
   (for example the customer had already paid, was the wrong person, or the call was
   handed to a human straight away).
3. expected_behaviour: Did the call match this description of a good call?
   "{expected}"

Reply with one JSON object and nothing else, in exactly this shape:
{{"tone": {{"pass": true, "evidence": "..."}},
 "reason_explored": {{"pass": true, "evidence": "..."}},
 "expected_behaviour": {{"pass": true, "evidence": "..."}}}}
"pass" is true, false or null. "evidence" is one short line, quoting the transcript where
you can.

Transcript:
{transcript}
"""

# Which failure bucket each verdict counts under. expected_behaviour takes the scenario's.
BUCKETS = {"tone": "adherence", "reason_explored": "adherence"}


def transcript_text(transcript: dict) -> str:
    """The spoken turns as plain lines."""
    names = {"customer": "Customer", "bot": "Bot"}
    return "\n".join(
        f"{names[e['type']]}: {e['text']}"
        for e in transcript["events"]
        if e["type"] in names
    )


async def judge_call(
    client: AsyncOpenAI, transcript: dict, scenario: dict
) -> list[Check]:
    """Ask the judge its three questions about one call. Never raises: if the judge
    cannot be reached or replies with something unusable, each verdict is returned as
    an error with the reason, so one bad judge call does not sink a run."""
    names = ["tone", "reason_explored", "expected_behaviour"]
    prompt = JUDGE_PROMPT.format(
        expected=" ".join(scenario["expected"]["behaviour"].split()),
        transcript=transcript_text(transcript),
    )
    error = ""
    for _attempt in (1, 2):  # retry once
        try:
            response = await client.chat.completions.create(
                model=config.JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                timeout=config.EXTRACTION_TIMEOUT_SECONDS,
            )
            text = response.choices[0].message.content or ""
            verdicts = json.loads(text[text.index("{") : text.rindex("}") + 1])
            if any(verdicts[name]["pass"] not in (True, False, None) for name in names):
                raise ValueError("pass must be true, false or null")
            return [
                Check(
                    name=f"judge_{name}",
                    bucket=BUCKETS.get(name, scenario["bucket"]),
                    passed=verdicts[name]["pass"],
                    evidence=str(verdicts[name]["evidence"]),
                )
                for name in names
            ]
        except OpenAIError as failure:
            error = f"judge request failed: {type(failure).__name__}"
        except (ValueError, KeyError, TypeError, IndexError):
            error = "judge reply was not in the expected JSON shape"
    return [
        Check(
            f"judge_{name}",
            BUCKETS.get(name, scenario["bucket"]),
            None,
            error,
            error=True,
        )
        for name in names
    ]
