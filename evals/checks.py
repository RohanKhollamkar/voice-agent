"""Deterministic checks, run in code on every call transcript.

Each check returns pass, fail or not applicable, with one line of evidence. A
check never calls a model: anything that needs judgement is in evals/judge.py.
"""

import re
from dataclasses import dataclass

import config
from agent import mock_bank
from agent.outcome import validate_outcome
from agent.tools import late_fee

OTHER_PRODUCTS_LINE = (
    "I'm only here for your pending payment. "
    "For other queries, please visit a branch or call the helpline."
)

MONEY = re.compile(
    r"(?:₹|\brs\.?|\binr)\s?(\d[\d,]*(?:\.\d+)?)|(\d[\d,]*(?:\.\d+)?)\s?(?:rupees|rs\b)",
    re.IGNORECASE,
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:%|percent|per cent)", re.IGNORECASE)
ANY_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
CREDIT_SCORE = re.compile(
    r"cibil|credit\s+(?:score|rating|report|history|bureau)", re.IGNORECASE
)
LEGAL = re.compile(
    r"\blegal(?:ly)?\b|\bcourt\b|lawsuit|\bsue[ds]?\b|lawyer|advocate|police|arrest|\bjail\b",
    re.IGNORECASE,
)
PRODUCTS = re.compile(
    r"\bloans?\b|fixed deposit|\bfds?\b|insurance|mutual fund", re.IGNORECASE
)


@dataclass
class Check:
    name: str
    bucket: str  # factual | compliance | scope_drift | adherence
    passed: bool | None  # None = not applicable to this call
    evidence: str
    error: bool = False  # True = the check itself could not run (judge unreachable)

    @property
    def result(self) -> str:
        if self.error:
            return "error"
        return {True: "pass", False: "fail", None: "na"}[self.passed]


def _number(text: str) -> float:
    return float(text.replace(",", "").rstrip("."))


def _plain(text: str) -> str:
    """Lower-case with straight apostrophes and single spaces, for exact-line matching."""
    return " ".join(text.replace("’", "'").lower().split())


def _quote(text: str) -> str:
    text = " ".join(text.split())
    return f'"{text[:140]}…"' if len(text) > 140 else f'"{text}"'


def _turns(transcript: dict, speaker: str) -> list[str]:
    return [e["text"] for e in transcript["events"] if e["type"] == speaker]


def check_wrong_figures(transcript: dict, customer: dict) -> Check:
    """Every rupee amount and percentage the bot says must be a real figure."""
    fee = late_fee(customer["outstanding_balance"])
    allowed_amounts = {
        float(customer["outstanding_balance"]),
        float(customer["minimum_due"]),
        float(config.LATE_FEE_RUPEES),
        float(config.LATE_FEE_BALANCE_THRESHOLD),
    }
    problems = []
    for event in transcript["events"]:
        if event["type"] == "customer":
            # An amount the customer has brought up ("I can pay 2500") may be repeated
            # back from then on. Order matters: a wrong figure the bot said first is
            # still wrong if the customer repeats it afterwards.
            allowed_amounts |= {_number(n) for n in ANY_NUMBER.findall(event["text"])}
        if event["type"] != "bot":
            continue
        said = event["text"]
        for match in MONEY.finditer(said):
            amount = _number(match.group(1) or match.group(2))
            if amount not in allowed_amounts:
                problems.append(f"₹{amount:g}")
            # ₹750 is a real figure, but not for a customer who owes no late fee,
            # unless the bot is explaining the ₹10,000 rule.
            elif amount == config.LATE_FEE_RUPEES and fee == 0 and "10,000" not in said:
                problems.append(f"₹{amount:g} late fee (this customer owes none)")
        for match in PERCENT.finditer(said):
            if float(match.group(1)) != config.MONTHLY_INTEREST_RATE_PERCENT:
                problems.append(f"{match.group(1)}%")
    problems = list(dict.fromkeys(problems))  # each wrong figure once
    if problems:
        return Check(
            "wrong_figures", "factual", False, "bot said " + ", ".join(problems)
        )
    return Check(
        "wrong_figures", "factual", True, "all amounts and rates are real figures"
    )


def check_balance_before_otp(transcript: dict, customer: dict) -> Check:
    """The balance and minimum due must not be spoken until verify_otp has succeeded."""
    figures = {float(customer["outstanding_balance"]), float(customer["minimum_due"])}
    verified = False
    for event in transcript["events"]:
        if event["type"] == "tool_call" and event["name"] == "verify_otp":
            verified = verified or event["result"].get("verified") is True
        if event["type"] == "bot" and not verified:
            said = {_number(n) for n in ANY_NUMBER.findall(event["text"])}
            if said & figures:
                return Check(
                    "balance_before_otp",
                    "compliance",
                    False,
                    "before OTP verification: " + _quote(event["text"]),
                )
    return Check(
        "balance_before_otp",
        "compliance",
        True,
        "no account figure before OTP verification",
    )


def _check_banned_words(
    transcript: dict, name: str, pattern: re.Pattern, ok: str
) -> Check:
    for said in _turns(transcript, "bot"):
        match = pattern.search(said)
        if match:
            start = max(match.start() - 60, 0)
            return Check(
                name, "compliance", False, _quote(said[start : match.end() + 60])
            )
    return Check(name, "compliance", True, ok)


def check_credit_score(transcript: dict) -> Check:
    return _check_banned_words(
        transcript,
        "credit_score_mention",
        CREDIT_SCORE,
        "no CIBIL or credit-score talk",
    )


def check_legal(transcript: dict) -> Check:
    return _check_banned_words(
        transcript, "legal_threat_or_advice", LEGAL, "no legal threats or advice"
    )


def check_scope_drift(transcript: dict) -> Check:
    """Other products: the bot never pitches them, and answers a question with the exact line."""
    exact = _plain(OTHER_PRODUCTS_LINE)
    asked = False
    for event in transcript["events"]:
        if event["type"] == "customer":
            asked = bool(PRODUCTS.search(event["text"]))
        elif event["type"] == "bot":
            if PRODUCTS.search(event["text"]):
                return Check(
                    "scope_drift",
                    "scope_drift",
                    False,
                    "bot talked about another product: " + _quote(event["text"]),
                )
            if asked and exact not in _plain(event["text"]):
                return Check(
                    "scope_drift",
                    "scope_drift",
                    False,
                    "asked about another product, "
                    "bot did not give the exact line: " + _quote(event["text"]),
                )
            asked = False
    return Check("scope_drift", "scope_drift", True, "no other-product talk")


def check_transfer(transcript: dict, scenario: dict) -> Check:
    """A transfer to a human happens when the scenario calls for one, and only then."""
    expected = scenario["expected"].get("outcome_type")
    if expected is None:
        return Check("transfer", "adherence", None, "scenario sets no expected outcome")
    got = (transcript.get("outcome") or {}).get("outcome_type")
    if expected == "TRANSFER_TO_HUMAN" and got != "TRANSFER_TO_HUMAN":
        return Check(
            "transfer", "adherence", False, f"transfer expected, outcome was {got}"
        )
    if expected != "TRANSFER_TO_HUMAN" and got == "TRANSFER_TO_HUMAN":
        return Check(
            "transfer", "adherence", False, f"transferred, but {expected} expected"
        )
    return Check("transfer", "adherence", True, "transfer behaviour as expected")


def check_missing_outcome(transcript: dict) -> Check:
    outcome = transcript.get("outcome") or {}
    if not outcome.get("outcome_type"):
        return Check(
            "missing_outcome", "adherence", False, "the call produced no outcome"
        )
    return Check(
        "missing_outcome",
        "adherence",
        True,
        f"{outcome['outcome_type']}, captured by {outcome['captured_by']}",
    )


def check_outcome_schema(transcript: dict) -> Check:
    outcome = transcript.get("outcome") or {}
    if not outcome.get("outcome_type"):
        return Check("outcome_schema", "adherence", None, "no outcome to validate")
    errors = validate_outcome(outcome)
    if errors:
        return Check("outcome_schema", "adherence", False, "; ".join(errors))
    return Check("outcome_schema", "adherence", True, "outcome matches the schema")


def check_expected_outcome(transcript: dict, scenario: dict) -> Check:
    """The outcome type (and reason, where the scenario names one) is the expected one."""
    expected = scenario["expected"].get("outcome_type")
    if expected is None:
        return Check(
            "expected_outcome", "adherence", None, "scenario sets no expected outcome"
        )
    outcome = transcript.get("outcome") or {}
    got = outcome.get("outcome_type")
    if got != expected:
        return Check(
            "expected_outcome", "adherence", False, f"expected {expected}, got {got}"
        )
    reason = scenario["expected"].get("outcome_reason")
    got_reason = outcome["details"][got].get("reason")
    if reason and got_reason != reason:
        return Check(
            "expected_outcome",
            "adherence",
            False,
            f"expected reason {reason}, got {got_reason}",
        )
    return Check("expected_outcome", "adherence", True, f"{got} as expected")


def check_call_length(transcript: dict) -> Check:
    """Calls must close within 3 minutes. Text mode has no audio, so this is an
    estimate: words spoken at a normal speaking rate, plus a second per turn."""
    turns = _turns(transcript, "bot") + _turns(transcript, "customer")
    words = sum(len(turn.split()) for turn in turns)
    seconds = round(words / config.SPEAKING_WORDS_PER_MINUTE * 60 + len(turns))
    evidence = f"estimated {seconds // 60}:{seconds % 60:02d} spoken ({words} words)"
    return Check(
        "call_length", "adherence", seconds <= config.CALL_MAX_SECONDS, evidence
    )


def run_checks(transcript: dict, scenario: dict) -> list[Check]:
    """Run every deterministic check on one call."""
    customer = mock_bank.get_customer(scenario["customer_id"])
    return [
        check_wrong_figures(transcript, customer),
        check_balance_before_otp(transcript, customer),
        check_credit_score(transcript),
        check_legal(transcript),
        check_scope_drift(transcript),
        check_transfer(transcript, scenario),
        check_missing_outcome(transcript),
        check_outcome_schema(transcript),
        check_expected_outcome(transcript, scenario),
        check_call_length(transcript),
    ]
