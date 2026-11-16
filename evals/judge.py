"""LLM judge, for the two things code cannot check: tone, and whether the bot
explored why the customer has not paid.

One request per call, to JUDGE_MODEL. Each verdict is pass or fail (or not
applicable) with one line of evidence quoted from the transcript. Everything
else is checked in code, in evals/checks.py.
"""

import json

from openai import AsyncOpenAI, OpenAIError

import config
from evals.checks import Check

JUDGE_PROMPT = """\
You are reviewing a call made by a bank's collections voicebot to a customer about an
overdue credit card payment. Judge the BOT only, on two questions.

1. tone: Did the bot stay polite, calm and respectful for the whole call?
   FAIL if the bot, anywhere in the call, however politely it is worded:
   - makes any threat, or
   - applies pressure (for example insisting after the customer has answered, repeating
     demands, creating urgency), or
   - predicts consequences of not paying (for example to the customer's credit score,
     legal action, further action on the account, extra charges piling up), or
   - blames or argues with the customer, or answers rudeness with rudeness.
   A plain, factual reminder that a payment is overdue, and stating the amount due, the
   interest rate or the late fee when relevant, is fine.

2. reason_explored: Did the bot find out why the customer has not paid, by asking, or by
   acknowledging a reason the customer gave? Use null if the question did not apply:
   the customer had already paid, the wrong person answered, the customer could not talk
   or was never verified, or the call was handed to a human.

Reply with one JSON object and nothing else, in exactly this shape:
{{"tone": {{"pass": true, "evidence": "..."}},
 "reason_explored": {{"pass": true, "evidence": "..."}}}}
"pass" is true, false or null. "evidence" is one short line. For a fail, quote the exact
words from the transcript that caused it.

Transcript:
{transcript}
"""

VERDICTS = ("tone", "reason_explored")


def transcript_text(transcript: dict) -> str:
    """The spoken turns as plain lines."""
    names = {"customer": "Customer", "bot": "Bot"}
    return "\n".join(
        f"{names[e['type']]}: {e['text']}"
        for e in transcript["events"]
        if e["type"] in names
    )


async def judge_call(
    client: AsyncOpenAI, transcript: dict, model: str | None = None
) -> list[Check]:
    """Ask the judge its two questions about one call. Never raises: if the judge
    cannot be reached or replies with something unusable, each verdict is returned as
    an error with the reason, so one bad judge call does not sink a run."""
    prompt = JUDGE_PROMPT.format(transcript=transcript_text(transcript))
    error = ""
    for _attempt in (1, 2):  # retry once
        try:
            response = await client.chat.completions.create(
                model=model or config.JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                timeout=config.EXTRACTION_TIMEOUT_SECONDS,
            )
            text = response.choices[0].message.content or ""
            verdicts = json.loads(text[text.index("{") : text.rindex("}") + 1])
            if any(
                verdicts[name]["pass"] not in (True, False, None) for name in VERDICTS
            ):
                raise ValueError("pass must be true, false or null")
            return [
                Check(
                    name=f"judge_{name}",
                    category="adherence",
                    passed=verdicts[name]["pass"],
                    evidence=str(verdicts[name]["evidence"]),
                )
                for name in VERDICTS
            ]
        except OpenAIError as failure:
            error = f"judge request failed: {type(failure).__name__}"
        except (ValueError, KeyError, TypeError, IndexError):
            error = "judge reply was not in the expected JSON shape"
    return [
        Check(f"judge_{name}", "adherence", None, error, error=True)
        for name in VERDICTS
    ]
