"""Tools the model can call, and the call state they read and change.

The model never passes a customer ID: every tool acts on the customer this call
is for, so the bot cannot be talked into opening someone else's account.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import config
from agent import mock_bank
from agent.guardrails import (
    callback_problems,
    future_callback_time,
    promise_problems,
    readback_problems,
)
from agent.outcome import (
    CALLBACK_REASONS,
    OUTCOME_TYPES,
    PAYMENT_MODES,
    TRANSFER_REASONS,
    validate_details,
    validate_follow_ups,
)


@dataclass
class CallState:
    """What is true about this call so far."""

    call_id: str
    customer_id: str
    bot_version: str
    started_at: datetime
    otp_sent: bool = False
    otp_verified: bool = False
    otp_failed_attempts: int = 0
    outcome_type: str | None = None
    outcome_details: dict | None = None
    follow_ups: list | None = None
    guarded: bool = False  # v2: code guardrails on (see agent/guardrails.py)
    tools_done: set[str] = field(default_factory=set)  # tools that ran without error
    # The spoken turns so far, in order: ("bot" or "customer", text).
    turns: list[tuple[str, str]] = field(default_factory=list)
    # The call's clock: real time, or the evals' simulated clock (agent.core).
    clock: Callable[[], datetime] = field(
        default=lambda: datetime.now(ZoneInfo(config.TIMEZONE))
    )

    @property
    def v2_1(self) -> bool:
        """The fixes made after the final evaluation are on (v2 keeps the evaluated
        behaviour)."""
        return self.bot_version == "v2.1"

    customer_turns: list[str] = field(
        default_factory=list
    )  # what the customer has said


def late_fee(outstanding_balance: float) -> int:
    """The brief's rule: ₹750 if the balance is over ₹10,000, otherwise nothing."""
    if outstanding_balance > config.LATE_FEE_BALANCE_THRESHOLD:
        return config.LATE_FEE_RUPEES
    return 0


def send_otp(state: CallState) -> dict:
    """Mocked: nothing is sent. The customer's OTP is fixed in mock_bank."""
    customer = mock_bank.get_customer(state.customer_id)
    state.otp_sent = True
    return {"sent": True, "to_phone_ending": customer["phone"][-4:]}


def verify_otp(state: CallState, code: str) -> dict:
    """Check the code. After MAX_OTP_ATTEMPTS wrong codes it refuses, even a right one."""
    if not state.otp_sent:
        # Not counted as a failed attempt: the customer cannot have a code yet.
        return {
            "verified": False,
            "error": "Refused: no code has been sent in this call, so there is nothing to "
            "check. Call send_otp now, tell the customer a code has been sent to their "
            "registered mobile, and ask them to read it out. Then call verify_otp.",
        }
    refused = {
        "verified": False,
        "attempts_left": 0,
        "error": "Verification failed: no attempts left. Share no account details. "
        "End the call: record CALLBACK_REQUEST with reason verification_failed.",
    }
    if state.otp_failed_attempts >= config.MAX_OTP_ATTEMPTS:
        return refused
    customer = mock_bank.get_customer(state.customer_id)
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if digits == customer["otp"]:
        state.otp_verified = True
        return {"verified": True}
    state.otp_failed_attempts += 1
    attempts_left = config.MAX_OTP_ATTEMPTS - state.otp_failed_attempts
    if attempts_left == 0:
        return refused
    return {
        "verified": False,
        "attempts_left": attempts_left,
        "error": "The code does not match.",
    }


def get_account_summary(state: CallState) -> dict:
    if config.ENFORCE_OTP and not state.otp_verified:
        return {
            "error": "Refused: the customer has not passed OTP verification. "
            "Account figures must not be shared before that. "
            "Call send_otp, ask the customer for the code, then call verify_otp."
        }
    customer = mock_bank.get_customer(state.customer_id)
    return {
        # Field names as the v2 prompt refers to them. Amounts are in rupees.
        "outstanding_balance": customer["outstanding_balance"],
        "minimum_due": customer["minimum_due"],
        "days_past_due": customer["days_past_due"],
        "late_fee": late_fee(customer["outstanding_balance"]),
        "monthly_interest_rate_percent": config.MONTHLY_INTEREST_RATE_PERCENT,
    }


def record_outcome(
    state: CallState, outcome_type: str, details: dict, follow_ups: list | None = None
) -> dict:
    """Record the call's single outcome. Recording it ends the call."""
    if state.outcome_type is not None:
        return {
            "recorded": False,
            "error": "An outcome is already recorded for this call.",
        }
    errors = validate_details(outcome_type, details) + validate_follow_ups(follow_ups)
    if errors:
        return {"recorded": False, "error": "Fix and call again: " + "; ".join(errors)}
    if state.guarded and outcome_type == "PROMISE_TO_PAY":
        # A promise must be the customer's own words, and they must have just said yes.
        problems = promise_problems(
            details,
            state.customer_turns,
            mock_bank.get_customer(state.customer_id),
            state.started_at.date(),
        )
        if state.v2_1:  # the customer's yes must answer a read-back
            problems += readback_problems(details, state.turns, state.started_at.date())
        if problems:
            return {
                "recorded": False,
                "error": "Not recorded: "
                + "; ".join(problems)
                + ". Read the date and amount back to the customer, ask them to confirm, "
                "and record only after they say yes.",
            }
    if state.guarded and outcome_type == "CALLBACK_REQUEST":
        # A callback reason must come from the call, not be guessed ("busy").
        problems = callback_problems(
            details,
            state.customer_turns,
            state.otp_failed_attempts,
            third_party=state.v2_1,
        )
        if problems:
            return {
                "recorded": False,
                "error": "Not recorded: "
                + "; ".join(problems)
                + ". Record a callback only with a reason the customer gave. If the call "
                "ends with nothing agreed, the system records it.",
            }
    moved = ""
    if state.v2_1 and outcome_type == "CALLBACK_REQUEST" and details.get("time"):
        # A callback time already past moves to the same time the next day.
        later = future_callback_time(details["time"], state.clock())
        if later != details["time"]:
            moved = f"The time {details['time']} had passed, so it is {later}. "
            details = {**details, "time": later}
    state.outcome_type = outcome_type
    state.outcome_details = details
    state.follow_ups = follow_ups or []
    if state.guarded:  # the closing line is spoken by code, from the outcome
        return {
            "recorded": True,
            "next": moved + "Say nothing more. The call is closing.",
        }
    return {"recorded": True, "next": "Say a short goodbye. The call ends after it."}


TOOLS = {
    "send_otp": send_otp,
    "verify_otp": verify_otp,
    "get_account_summary": get_account_summary,
    "record_outcome": record_outcome,
}


# Which tools each bot version is given. v1 is the bank's prompt as written: it
# never mentions an OTP and "knows everything about the customer's account", so
# it gets no OTP or account tools, only the one that records the outcome.
TOOLS_BY_VERSION = {
    "v1": ("record_outcome",),
    "v2": ("send_otp", "verify_otp", "get_account_summary", "record_outcome"),
    "v2.1": ("send_otp", "verify_otp", "get_account_summary", "record_outcome"),
}


def tool_schemas(version: str) -> list[dict]:
    """The tool definitions sent to the model for this bot version."""
    allowed = TOOLS_BY_VERSION[version]
    return [schema for schema in TOOL_SCHEMAS if schema["function"]["name"] in allowed]


def run_tool(state: CallState, name: str, arguments: dict) -> dict:
    """Run one tool call from the model. Bad calls come back as an error, not a crash."""
    if name not in TOOLS_BY_VERSION[state.bot_version]:
        return {"error": f"Unknown tool '{name}'."}
    try:
        result = TOOLS[name](state, **arguments)
    except TypeError as error:  # the model sent missing or unexpected arguments
        return {"error": f"Bad arguments for {name}: {error}"}
    if "error" not in result:
        state.tools_done.add(name)
    return result


def _tool(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


# What the model is told about each tool (OpenAI-style tool calling).
TOOL_SCHEMAS = [
    _tool(
        "send_otp",
        "Send a one-time password to the customer's registered phone.",
        {},
        [],
    ),
    _tool(
        "verify_otp",
        "Check the one-time password the customer read out.",
        {"code": {"type": "string", "description": "The digits the customer said."}},
        ["code"],
    ),
    _tool(
        "get_account_summary",
        "Get the customer's outstanding balance, minimum due, days past due, "
        "late fee and monthly interest rate.",
        {},
        [],
    ),
    _tool(
        "record_outcome",
        "Record the single outcome of this call. Call it once, when the call is ending.",
        {
            "outcome_type": {"type": "string", "enum": list(OUTCOME_TYPES)},
            "details": {
                "type": "object",
                "description": (
                    "Depends on outcome_type. "
                    'PROMISE_TO_PAY: {"date": "YYYY-MM-DD", "amount": number}. '
                    'ALREADY_PAID: {"date": "YYYY-MM-DD", "mode": one of '
                    f"{list(PAYMENT_MODES)}}}. "
                    'CALLBACK_REQUEST: {"time": ISO-8601 date-time or null if no time '
                    f'was agreed, "reason": one of {list(CALLBACK_REASONS)}}}. '
                    'DISPUTE: {"reason": free text}. '
                    f'TRANSFER_TO_HUMAN: {{"reason": one of {list(TRANSFER_REASONS)}}}.'
                ),
            },
            "follow_ups": {
                "type": "array",
                "description": (
                    "Optional, usually omitted. A second thing a human must act on, "
                    "each item shaped like the main outcome. Example: the customer "
                    "asks for a waiver and also promises to pay, so the outcome is "
                    'PROMISE_TO_PAY with follow_ups [{"outcome_type": "CALLBACK_REQUEST", '
                    '"details": {"time": null, "reason": "waiver_request"}}].'
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "outcome_type": {"type": "string", "enum": list(OUTCOME_TYPES)},
                        "details": {"type": "object"},
                    },
                    "required": ["outcome_type", "details"],
                },
            },
        },
        ["outcome_type", "details"],
    ),
]
