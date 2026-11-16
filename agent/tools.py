"""Tools the model can call, and the call state they read and change.

The model never passes a customer ID: every tool acts on the customer this call
is for, so the bot cannot be talked into opening someone else's account.
"""

from dataclasses import dataclass
from datetime import datetime

import config
from agent import mock_bank
from agent.outcome import (
    CALLBACK_REASONS,
    OUTCOME_TYPES,
    PAYMENT_MODES,
    TRANSFER_REASONS,
    validate_details,
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
    outcome_type: str | None = None
    outcome_details: dict | None = None


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
    if not state.otp_sent:
        return {
            "verified": False,
            "error": "No OTP has been sent yet. Call send_otp first.",
        }
    customer = mock_bank.get_customer(state.customer_id)
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if digits != customer["otp"]:
        return {"verified": False, "error": "The code does not match."}
    state.otp_verified = True
    return {"verified": True}


def get_account_summary(state: CallState) -> dict:
    if config.ENFORCE_OTP and not state.otp_verified:
        return {
            "error": "Refused: the customer has not passed OTP verification. "
            "Account figures must not be shared before that. "
            "Call send_otp, ask the customer for the code, then call verify_otp."
        }
    customer = mock_bank.get_customer(state.customer_id)
    return {
        "outstanding_balance_rupees": customer["outstanding_balance"],
        "minimum_due_rupees": customer["minimum_due"],
        "days_past_due": customer["days_past_due"],
        "late_fee_rupees": late_fee(customer["outstanding_balance"]),
        "monthly_interest_rate_percent": config.MONTHLY_INTEREST_RATE_PERCENT,
    }


def record_outcome(state: CallState, outcome_type: str, details: dict) -> dict:
    """Record the call's single outcome. Recording it ends the call."""
    if state.outcome_type is not None:
        return {
            "recorded": False,
            "error": "An outcome is already recorded for this call.",
        }
    errors = validate_details(outcome_type, details)
    if errors:
        return {"recorded": False, "error": "Fix and call again: " + "; ".join(errors)}
    state.outcome_type = outcome_type
    state.outcome_details = details
    return {"recorded": True, "next": "Say a short goodbye. The call ends after it."}


TOOLS = {
    "send_otp": send_otp,
    "verify_otp": verify_otp,
    "get_account_summary": get_account_summary,
    "record_outcome": record_outcome,
}


def run_tool(state: CallState, name: str, arguments: dict) -> dict:
    """Run one tool call from the model. Bad calls come back as an error, not a crash."""
    if name not in TOOLS:
        return {"error": f"Unknown tool '{name}'."}
    try:
        return TOOLS[name](state, **arguments)
    except TypeError as error:  # the model sent missing or unexpected arguments
        return {"error": f"Bad arguments for {name}: {error}"}


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
        },
        ["outcome_type", "details"],
    ),
]
