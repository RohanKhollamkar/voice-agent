"""The call outcome: validate it, save it, POST it, and extract it if the bot forgot.

The schema is the one in CLAUDE.md. A webhook failure never crashes the call.
"""

import json
from datetime import date, datetime

import httpx
from openai import AsyncOpenAI, OpenAIError

import config
from agent.retry import retry_on_rate_limit

OUTCOME_TYPES = (
    "PROMISE_TO_PAY",
    "ALREADY_PAID",
    "CALLBACK_REQUEST",
    "DISPUTE",
    "TRANSFER_TO_HUMAN",
)
PAYMENT_MODES = ("UPI", "net banking", "card", "cash", "other")
CALLBACK_REASONS = (
    "busy",
    "waiver_request",
    "wrong_party",
    "call_time_limit",
    "verification_failed",
)
TRANSFER_REASONS = ("abusive", "medical_emergency", "job_loss", "customer_request")
CAPTURED_BY = ("tool_call", "post_call_extraction")

# The keys each outcome type's details must have, no more and no fewer.
DETAIL_KEYS = {
    "PROMISE_TO_PAY": {"date", "amount"},
    "ALREADY_PAID": {"date", "mode"},
    "CALLBACK_REQUEST": {"time", "reason"},
    "DISPUTE": {"reason"},
    "TRANSFER_TO_HUMAN": {"reason"},
}


def _is_date(value: object) -> bool:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return len(value) == 10  # YYYY-MM-DD only


def _is_datetime(value: object) -> bool:
    try:
        datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return False
    return "T" in value


def validate_details(outcome_type: str, details: object) -> list[str]:
    """Return what is wrong with the details for this outcome type ([] if nothing)."""
    if outcome_type not in OUTCOME_TYPES:
        return [f"outcome_type must be one of {list(OUTCOME_TYPES)}"]
    if not isinstance(details, dict):
        return ["details must be an object"]
    expected = DETAIL_KEYS[outcome_type]
    if set(details) != expected:
        return [
            f"details for {outcome_type} must have exactly the keys {sorted(expected)}"
        ]

    errors = []
    if outcome_type == "PROMISE_TO_PAY":
        if not _is_date(details["date"]):
            errors.append("date must be YYYY-MM-DD")
        amount = details["amount"]
        if (
            isinstance(amount, bool)
            or not isinstance(amount, int | float)
            or amount <= 0
        ):
            errors.append("amount must be a number above zero")
    elif outcome_type == "ALREADY_PAID":
        if not _is_date(details["date"]):
            errors.append("date must be YYYY-MM-DD")
        if details["mode"] not in PAYMENT_MODES:
            errors.append(f"mode must be one of {list(PAYMENT_MODES)}")
    elif outcome_type == "CALLBACK_REQUEST":
        # A waiver or wrong-party callback often has no agreed time, so null is allowed.
        if details["time"] is not None and not _is_datetime(details["time"]):
            errors.append(
                "time must be an ISO-8601 date-time, or null if none was agreed"
            )
        if details["reason"] not in CALLBACK_REASONS:
            errors.append(f"reason must be one of {list(CALLBACK_REASONS)}")
    elif outcome_type == "DISPUTE":
        if not isinstance(details["reason"], str) or not details["reason"].strip():
            errors.append("reason must be a non-empty sentence")
    elif outcome_type == "TRANSFER_TO_HUMAN":
        if details["reason"] not in TRANSFER_REASONS:
            errors.append(f"reason must be one of {list(TRANSFER_REASONS)}")
    return errors


def validate_follow_ups(follow_ups: object) -> list[str]:
    """follow_ups is optional: a list of secondary outcomes a human must act on, each
    {"outcome_type": ..., "details": {...}} with the same details rules as the main one."""
    if follow_ups is None:
        return []
    if not isinstance(follow_ups, list):
        return ["follow_ups must be a list"]
    errors = []
    for number, item in enumerate(follow_ups, start=1):
        if not isinstance(item, dict) or set(item) != {"outcome_type", "details"}:
            errors.append(
                f"follow_ups[{number}] must have exactly outcome_type and details"
            )
            continue
        for error in validate_details(item["outcome_type"], item["details"]):
            errors.append(f"follow_ups[{number}]: {error}")
    return errors


def build_outcome(
    *,
    call_id: str,
    customer_id: str,
    bot_version: str,
    started_at: datetime,
    ended_at: datetime,
    otp_verified: bool,
    outcome_type: str | None,
    details: dict | None,
    follow_ups: list | None,
    captured_by: str,
    transcript_path: str,
) -> dict:
    """Assemble the outcome record in the CLAUDE.md shape."""
    return {
        "call_id": call_id,
        "customer_id": customer_id,
        "bot_version": bot_version,
        "started_at": started_at.isoformat(timespec="seconds"),
        "ended_at": ended_at.isoformat(timespec="seconds"),
        "duration_seconds": round((ended_at - started_at).total_seconds()),
        "otp_verified": otp_verified,
        "outcome_type": outcome_type,
        # details holds only the key that matches outcome_type
        "details": {outcome_type: details} if outcome_type else {},
        "follow_ups": follow_ups or [],
        "captured_by": captured_by,
        "transcript_path": transcript_path,
    }


def validate_outcome(outcome: dict) -> list[str]:
    """Check a whole outcome record against the schema. Returns the problems found."""
    errors = []
    for key in ("call_id", "customer_id", "bot_version", "transcript_path"):
        if not isinstance(outcome.get(key), str) or not outcome[key]:
            errors.append(f"{key} must be a non-empty string")
    for key in ("started_at", "ended_at"):
        if not _is_datetime(outcome.get(key)):
            errors.append(f"{key} must be an ISO-8601 date-time")
    if (
        not isinstance(outcome.get("duration_seconds"), int)
        or outcome["duration_seconds"] < 0
    ):
        errors.append("duration_seconds must be a whole number, zero or above")
    if not isinstance(outcome.get("otp_verified"), bool):
        errors.append("otp_verified must be true or false")
    if outcome.get("captured_by") not in CAPTURED_BY:
        errors.append(f"captured_by must be one of {list(CAPTURED_BY)}")

    outcome_type = outcome.get("outcome_type")
    details = outcome.get("details")
    if outcome_type not in OUTCOME_TYPES:
        errors.append(f"outcome_type must be one of {list(OUTCOME_TYPES)}")
    elif not isinstance(details, dict) or set(details) != {outcome_type}:
        errors.append("details must hold only the key that matches outcome_type")
    else:
        errors.extend(validate_details(outcome_type, details[outcome_type]))
    errors.extend(validate_follow_ups(outcome.get("follow_ups")))
    return errors


def save_outcome(outcome: dict) -> str:
    """Write the outcome to runs/outcomes/<call_id>.json and return the path."""
    folder = config.RUNS_DIR / "outcomes"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{outcome['call_id']}.json"
    path.write_text(json.dumps(outcome, indent=2, ensure_ascii=False), encoding="utf-8")
    return path.as_posix()


async def post_to_webhook(outcome: dict) -> dict:
    """POST the outcome to WEBHOOK_URL, retrying once. Reports the result; never raises."""
    if not config.WEBHOOK_URL:
        return {"posted": False, "attempts": 0, "error": "WEBHOOK_URL is not set"}
    error = ""
    for attempt in (1, 2):
        try:
            async with httpx.AsyncClient(timeout=5) as http:
                response = await http.post(config.WEBHOOK_URL, json=outcome)
                response.raise_for_status()
            return {"posted": True, "attempts": attempt, "status": response.status_code}
        except (httpx.HTTPError, httpx.InvalidURL) as failure:
            error = f"{type(failure).__name__}: {failure}"
    return {"posted": False, "attempts": 2, "error": error}


EXTRACTION_PROMPT = """\
Below is the transcript of a call from a bank's collections bot to a customer about an
overdue credit card payment. Today's date is {today}. Decide the single outcome of the call.

Reply with one JSON object and nothing else:
{{"outcome_type": "...", "details": {{...}}, "follow_ups": []}}

outcome_type and its details must be one of:
- PROMISE_TO_PAY: {{"date": "YYYY-MM-DD", "amount": number}}
- ALREADY_PAID: {{"date": "YYYY-MM-DD", "mode": one of {modes}}}
- CALLBACK_REQUEST: {{"time": ISO-8601 date-time or null, "reason": one of {callback}}}
- DISPUTE: {{"reason": "free text"}}
- TRANSFER_TO_HUMAN: {{"reason": one of {transfer}}}

follow_ups is usually empty. Use it only for a second thing a human must act on. The one
case so far: the customer asked for a late-fee waiver AND promised to pay. Then the
outcome is PROMISE_TO_PAY and follow_ups is
[{{"outcome_type": "CALLBACK_REQUEST", "details": {{"time": null, "reason": "waiver_request"}}}}].

Transcript:
{transcript}
"""


async def extract_outcome(
    client: AsyncOpenAI, transcript_text: str, today: str
) -> tuple[str | None, dict | None, list, str | None]:
    """Ask JUDGE_MODEL for the outcome of a call that ended without record_outcome.

    Returns (outcome_type, details, follow_ups, error). On failure the first two are
    None and the error says why; the call still produces an outcome record, marked invalid.
    """
    prompt = EXTRACTION_PROMPT.format(
        today=today,
        modes=list(PAYMENT_MODES),
        callback=list(CALLBACK_REASONS),
        transfer=list(TRANSFER_REASONS),
        transcript=transcript_text,
    )
    error = None
    for _attempt in (1, 2):  # the judge endpoint is sometimes slow or busy: retry once
        try:
            response = await retry_on_rate_limit(
                lambda: client.chat.completions.create(
                    model=config.JUDGE_MODEL,
                    messages=[{"role": "user", "content": prompt}],
                    timeout=config.EXTRACTION_TIMEOUT_SECONDS,
                )
            )
            reply = (response.choices or [None])[0]
            text = (reply.message.content or "") if reply else ""
            # Models often wrap JSON in a code fence or a sentence; take the outer braces.
            found = json.loads(text[text.index("{") : text.rindex("}") + 1])
            outcome_type, details = found.get("outcome_type"), found.get("details")
            follow_ups = found.get("follow_ups") or []
            break
        except OpenAIError as failure:
            error = f"extraction request failed: {type(failure).__name__}: {failure}"
        except (ValueError, AttributeError):
            error = "extraction reply was not a JSON object"
    else:
        return None, None, [], error

    errors = validate_details(outcome_type, details) + validate_follow_ups(follow_ups)
    if errors:
        return (
            None,
            None,
            [],
            "extraction reply failed validation: " + "; ".join(errors),
        )
    return outcome_type, details, follow_ups, None
