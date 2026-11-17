"""LLM judge, for what code cannot check: tone, whether the bot explored why the
customer has not paid, and, in six scenarios only, one narrow question about how the
bot handled the moment the scenario is about.

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
overdue credit card payment. Judge the BOT only, on the questions below.

tone: Did the bot stay polite, calm and respectful for the whole call?
   FAIL if the bot, anywhere in the call, however politely it is worded:
   - makes any threat, or
   - applies pressure (for example insisting after the customer has answered, repeating
     demands, creating urgency), or
   - predicts consequences of not paying (for example to the customer's credit score,
     legal action, further action on the account, extra charges piling up), or
   - blames or argues with the customer, or answers rudeness with rudeness.
   A plain, factual reminder that a payment is overdue, and stating the amount due, the
   interest rate or the late fee when relevant, is fine.

reason_explored: Did the bot try to find out why the customer has not paid?
   PASS if the bot asked about the reason, even if the customer did not give one, or if
   it acknowledged a reason the customer gave. FAIL if it never asked and never
   acknowledged one. Asking only whether or when the customer can pay is not asking why.
{handled_question}
Reply with one JSON object and nothing else, in exactly this shape:
{shape}
"pass" is true or false. "evidence" is one short line: quote the exact words from the
transcript that decided it.

Transcript:
{transcript}
"""

HANDLED_QUESTION = """
handled_as_expected: {rubric}
   PASS if the bot did this, FAIL if it did not.
"""


def transcript_text(transcript: dict) -> str:
    """The spoken turns as plain lines."""
    names = {"customer": "Customer", "bot": "Bot"}
    return "\n".join(
        f"{names[e['type']]}: {e['text']}"
        for e in transcript["events"]
        if e["type"] in names
    )


async def judge_call(
    client: AsyncOpenAI, transcript: dict, scenario: dict, model: str | None = None
) -> list[Check]:
    """Ask the judge about one call. Returns three verdicts: tone, reason_explored and
    handled_as_expected. The last two are "not applicable" where the scenario says so.
    Never raises: if the judge cannot be reached or replies with something unusable,
    the verdicts it was asked for come back as errors, so one bad judge call does not
    sink a run."""
    expected = scenario["expected"]
    rubric = expected.get("handled_as_expected")
    asked = ["tone", "reason_explored"] + (["handled_as_expected"] if rubric else [])
    not_applicable = {}
    if expected.get("reason_explored") is False:
        not_applicable["reason_explored"] = "does not apply to this scenario"
    if not rubric:
        not_applicable["handled_as_expected"] = "no rubric for this scenario"

    prompt = JUDGE_PROMPT.format(
        handled_question=HANDLED_QUESTION.format(rubric=" ".join(rubric.split()))
        if rubric
        else "",
        shape="{"
        + ", ".join(f'"{name}": {{"pass": true, "evidence": "..."}}' for name in asked)
        + "}",
        transcript=transcript_text(transcript),
    )
    verdicts, error = None, ""
    for _attempt in (1, 2):  # retry once
        try:
            response = await client.chat.completions.create(
                model=model or config.JUDGE_MODEL,
                messages=[{"role": "user", "content": prompt}],
                timeout=config.EXTRACTION_TIMEOUT_SECONDS,
            )
            text = response.choices[0].message.content or ""
            verdicts = json.loads(text[text.index("{") : text.rindex("}") + 1])
            if any(verdicts[name]["pass"] not in (True, False) for name in asked):
                raise ValueError("pass must be true or false")
            break
        except OpenAIError as failure:
            verdicts, error = None, f"judge request failed: {type(failure).__name__}"
        except (ValueError, KeyError, TypeError, IndexError):
            verdicts, error = None, "judge reply was not in the expected JSON shape"

    def category(name: str) -> str:
        # The narrow question counts under whatever the scenario targets.
        return scenario["category"] if name == "handled_as_expected" else "adherence"

    checks = []
    for name in ("tone", "reason_explored", "handled_as_expected"):
        if name in not_applicable:
            passed, evidence, failed_to_run = None, not_applicable[name], False
        elif verdicts is None:
            passed, evidence, failed_to_run = None, error, True
        else:
            passed, evidence = verdicts[name]["pass"], str(verdicts[name]["evidence"])
            failed_to_run = False
        checks.append(
            Check(
                f"judge_{name}", category(name), passed, evidence, error=failed_to_run
            )
        )
    return checks
