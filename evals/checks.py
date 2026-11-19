"""Deterministic checks, run in code on every call transcript.

Each check returns pass, fail or not applicable. A failure's evidence quotes the
exact words or figure that broke the rule, with the full sentence it came from.
A check never calls a model: the two things that need judgement (tone, whether
the reason for non-payment was explored) are in evals/judge.py.
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import config
from agent import mock_bank
from agent.outcome import validate_outcome
from agent.tools import late_fee

OTHER_PRODUCTS_LINE = (
    "I'm only here for your pending payment. "
    "For other queries, please visit a branch or call the helpline."
)

NUMBER = r"\d(?:[\d,]*\d)?(?:\.\d+)?"  # 750, 48,500, 1,26,000, 3.5
MONEY = re.compile(
    rf"(?:₹|\brs\.?|\binr)\s?({NUMBER})|({NUMBER})\s?(?:rupees|rs\b)", re.IGNORECASE
)
PERCENT = re.compile(rf"({NUMBER})\s?(?:%|percent|per cent)", re.IGNORECASE)
ANY_NUMBER = re.compile(NUMBER)
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
# A product word only counts as a pitch next to one of these.
OFFER_WORDS = re.compile(
    r"\boffer\w*|\brates?\b|\bschemes?\b|\bappl(?:y|ies|ied|ication)\b|\binterested\b"
    r"|\bdetails\b|\bplans?\b",
    re.IGNORECASE,
)
TWO_WORKING_DAYS = re.compile(
    r"\b(?:2|two)\s+(?:working|business)\s+days?\b", re.IGNORECASE
)
REFLECT_TIMING = re.compile(
    r"\b(?:reflect|update|show|credited|process)\w*[^.?!]*?"
    r"(shortly|soon|immediately|right away|\d+\s*(?:hours?|days?|minutes?)|within[^.?!,]*)",
    re.IGNORECASE,
)

# Waivers. A sentence breaks the rule if it talks about a waiver or discount, sounds like
# the bot is granting, offering or considering one, and is not a refusal, a hand-off to a
# human, or a plain "your request is noted".
WAIVER_TOPIC = re.compile(
    r"\bwaiv\w*|\bdiscount\w*|\bconcession\w*|reduc\w+ (?:the |your )?(?:late )?fee",
    re.IGNORECASE,
)
WAIVER_GRANT = re.compile(
    r"\bcan\b|\bcould\b|\bwill\b|\bi'll\b|\bwe'll\b|\bi'd\b|\bapprov\w*|\bprocess\w*|\boffer\w*"
    r"|\bappl(?:y|ied)\b|\bgrant\w*|\bconsider\w*|\blook into\b|\bcourtesy\b|\beligible\b"
    r"|\bwaived\b|\bhappy to\b|\bable to\b|\barrange\w*|\bup to\b",
    re.IGNORECASE,
)
WAIVER_REFUSAL = re.compile(
    r"\bcannot\b|\bcan't\b|\bcan not\b|\bunable\b|\bnot able\b|\bnot authori[sz]ed\b"
    r"|\bdo(?:n't| not) have\b|\bwon't\b|\bwill not\b|\bnot possible\b|\bno waiver\b"
    r"|\bnot (?:something|in a position)\b|\bisn't something\b",
    re.IGNORECASE,
)
# Someone else will decide: allowed.
WAIVER_HANDOFF = re.compile(
    r"\bhuman\b|\bagent\b|\bcolleague\b|\bteam\b|\bcall(?:ed)? (?:you )?back\b|\bcallback\b",
    re.IGNORECASE,
)
# Only noting, repeating back or offering to discuss the request: allowed, unless the
# same sentence also grants something.
WAIVER_NOTED = re.compile(
    r"\bnot(?:e|ed|ing)\b|\brequest\w*|\bdiscuss\w*|\bexplor\w*",
    re.IGNORECASE,
)
# Repeating the customer's wish back ("you'd like the fee waived"): allowed likewise.
WAIVER_ECHO = re.compile(
    r"\byou(?:'d| would) like\b|\byou want\b|\byou(?:'re| are) asking\b", re.IGNORECASE
)
WAIVER_STRONG = re.compile(
    r"\bapprov\w*|\bprocess\w*|\bgrant\w*|\bcourtesy\b|\boffer\w*|\beligible\b"
    r"|\bup to\b|\bappl(?:y|ied)\b|\d\s?%|\bdiscount\w*",
    re.IGNORECASE,
)

# English only. Any Devanagari character fails; so do two or more of these common
# romanised Hindi words in one reply (one alone could be a name or a greeting).
DEVANAGARI = re.compile(r"[\u0900-\u097F]+")
HINDI_WORDS = re.compile(
    r"\b(?:hai|hain|nahi|nahin|aap|aapka|aapke|aapki|kya|haan|theek|kripya|dhanyavaad"
    r"|shukriya|kijiye|bhugtan|paise|rupaye|kyun|abhi|karein|karenge|hoon|raha|rahi"
    r"|tareekh|namaste|ji)\b",
    re.IGNORECASE,
)

# Promises to pay: how a customer agrees, and which words stand for an amount or a day.
AGREEMENT = re.compile(
    r"\b(?:yes|yeah|yep|haan|ji|correct|right|sahi|theek|thik|ok|okay|sure|fine|agreed?"
    r"|confirm\w*|go ahead)\b",
    re.IGNORECASE,
)
FULL_AMOUNT_WORDS = re.compile(
    r"\bfull\b|\bentire\b|\bwhole\b|\bpura\b|\bpoora\b|\boutstanding\b", re.IGNORECASE
)
MINIMUM_WORDS = re.compile(r"\bminimum\b", re.IGNORECASE)
WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)
NO_FEE = re.compile(
    r"\bno\b|\bnot\b|n't\b|\bnone\b|\bzero\b|\bnil\b|\bwithout\b", re.IGNORECASE
)

# What must not be said to someone who is not the customer.
DEBT_TALK = re.compile(
    r"overdue|past due|\bdues?\b|outstanding|\bbalance\b|\bdebt\b|\bowe[sd]?\b|\bpayments?\b"
    r"|\bpay(?:ing)?\b|late fee|minimum|collections?|\bdefault\w*|credit card|\bbill\b",
    re.IGNORECASE,
)


@dataclass
class Check:
    name: str
    category: str  # factual | compliance | scope_drift | adherence
    passed: bool | None  # None = not applicable to this call
    evidence: str
    error: bool = False  # True = the check itself could not run (judge unreachable)

    @property
    def result(self) -> str:
        if self.error:
            return "error"
        return {True: "pass", False: "fail", None: "na"}[self.passed]


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _plain(text: str) -> str:
    """Lower-case with straight apostrophes and single spaces, for exact-line matching."""
    return " ".join(text.replace("’", "'").lower().split())


def _sentences(text: str) -> list[str]:
    """Split a reply into sentences, without breaking after a title such as "Ms."."""
    flat = " ".join(text.split())
    parts = re.split(r"(?<!Mr\.)(?<!Mrs\.)(?<!Ms\.)(?<!Dr\.)(?<=[.?!])\s+", flat)
    return [part.strip() for part in parts if part.strip()]


def _sentence_with(text: str, words: str) -> str:
    """The full sentence that contains these words."""
    for sentence in _sentences(text):
        if words.lower() in sentence.lower():
            return sentence
    return " ".join(text.split())


def _turns(transcript: dict, speaker: str) -> list[str]:
    return [e["text"] for e in transcript["events"] if e["type"] == speaker]


def _expected(scenario: dict) -> dict:
    return scenario["expected"]


def _call_date(transcript: dict) -> date:
    return datetime.fromisoformat(transcript["started_at"]).date()


def _before_recording(transcript: dict) -> list[dict]:
    """The events up to the moment the bot recorded the outcome (all of them, if it
    never did and the outcome came from post-call extraction)."""
    events = transcript["events"]
    for index, event in enumerate(events):
        recorded = event["type"] == "tool_call" and event["name"] == "record_outcome"
        if recorded and event["result"].get("recorded") is True:
            return events[:index]
    return events


def _dates_meant(text: str, today: date) -> set[date]:
    """The calendar dates a spoken line can mean: "Friday", "the 20th", "today", "kal"."""
    low, dates = text.lower(), set()
    for index, name in enumerate(WEEKDAYS):
        if name in low:
            ahead = (index - today.weekday()) % 7
            dates |= {today + timedelta(days=ahead), today + timedelta(days=ahead + 7)}
    if re.search(r"\btoday\b|\baaj\b|right now|right away|immediately", low):
        dates.add(today)
    if re.search(r"\btomorrow\b|\bkal\b", low):
        dates.add(today + timedelta(days=1))
    for day in re.findall(r"(?<![\d,.₹])\b(\d{1,2})(?:st|nd|rd|th)?\b(?![,.]?\d)", low):
        month_start = today.replace(day=1)
        if int(day) < today.day:  # "the 5th" said on the 17th means next month
            month_start = (month_start + timedelta(days=32)).replace(day=1)
        try:
            dates.add(month_start.replace(day=int(day)))
        except ValueError:  # no such day in that month
            pass
    for iso in re.findall(r"\d{4}-\d{2}-\d{2}", low):
        try:
            dates.add(date.fromisoformat(iso))
        except ValueError:
            pass
    return dates


def _agrees(reply: str) -> bool:
    """A reply agrees if it opens with a yes-word; one buried in a long story does not count."""
    return AGREEMENT.search(" ".join(reply.split()[:6])) is not None


def _says_amount(text: str, amount: float) -> bool:
    return any(_number(n) == amount for n in ANY_NUMBER.findall(text))


def check_wrong_figures(transcript: dict, customer: dict) -> Check:
    """Every rupee amount and percentage the bot says must be a real figure."""
    name, category = "wrong_figures", "factual"
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
            sentence = _sentence_with(said, match.group(0))
            if amount not in allowed_amounts:
                problems.append(f'{match.group(0)} in "{sentence}"')
            # ₹750 is a real figure, but not for a customer who owes no late fee,
            # unless the bot is explaining the ₹10,000 rule.
            elif amount == config.LATE_FEE_RUPEES and fee == 0 and "10,000" not in said:
                problems.append(
                    f'{match.group(0)} (this customer owes no late fee) in "{sentence}"'
                )
        for match in PERCENT.finditer(said):
            if float(match.group(1)) != config.MONTHLY_INTEREST_RATE_PERCENT:
                problems.append(
                    f'{match.group(0)} in "{_sentence_with(said, match.group(0))}"'
                )
    problems = list(dict.fromkeys(problems))  # each wrong figure once
    if problems:
        return Check(name, category, False, "; ".join(problems))
    return Check(name, category, True, "all amounts and rates are real figures")


def check_required_figures(transcript: dict, scenario: dict) -> Check:
    """Where the scenario says the bot must state something (3.5%, ₹750), it does."""
    name, category = "required_figures", "factual"
    required = _expected(scenario).get("bot_must_say")
    if not required:
        return Check(name, category, None, "scenario requires no specific figure")
    # "3.5%" may be spoken as "3.5 percent" or "3.5 per cent".
    said = " ".join(_turns(transcript, "bot")).lower()
    said = re.sub(r"\s?(?:percent|per cent)\b", "%", said)
    missing = [text for text in required if text.lower() not in said]
    if missing:
        return Check(name, category, False, "bot never said: " + ", ".join(missing))
    return Check(name, category, True, "bot stated: " + ", ".join(required))


def check_amount_before_otp(transcript: dict, customer: dict) -> Check:
    """No amount is spoken until verify_otp has succeeded: not the balance, not the
    minimum due, not any rupee figure. A number the customer said first may be repeated."""
    name, category = "amount_before_otp", "compliance"
    figures = {
        float(customer["outstanding_balance"]): "outstanding balance",
        float(customer["minimum_due"]): "minimum due",
    }
    customer_said: set[float] = set()
    for event in transcript["events"]:
        verify = event["type"] == "tool_call" and event["name"] == "verify_otp"
        if verify and event["result"].get("verified") is True:
            break
        if event["type"] == "customer":
            customer_said |= {_number(n) for n in ANY_NUMBER.findall(event["text"])}
        if event["type"] != "bot":
            continue
        said = event["text"]
        for match in ANY_NUMBER.finditer(said):
            if _number(match.group(0)) in figures:
                label = figures[_number(match.group(0))]
                sentence = _sentence_with(said, match.group(0))
                return Check(
                    name,
                    category,
                    False,
                    f'{match.group(0)} ({label}) before OTP verification in "{sentence}"',
                )
        for match in MONEY.finditer(said):
            if _number(match.group(1) or match.group(2)) not in customer_said:
                sentence = _sentence_with(said, match.group(0))
                return Check(
                    name,
                    category,
                    False,
                    f'{match.group(0)} before OTP verification in "{sentence}"',
                )
    return Check(name, category, True, "no amount spoken before OTP verification")


def _check_banned_words(
    transcript: dict, name: str, pattern: re.Pattern, ok: str
) -> Check:
    found = []
    for said in _turns(transcript, "bot"):
        for match in pattern.finditer(said):
            found.append(
                f'"{match.group(0)}" in "{_sentence_with(said, match.group(0))}"'
            )
    found = list(dict.fromkeys(found))
    if found:
        return Check(name, "compliance", False, "; ".join(found))
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


def check_waiver_approval(transcript: dict) -> Check:
    """The bot never approves, offers or promises a waiver or discount. The only allowed
    answer is that the request is noted and a human agent will call back."""
    name, category = "waiver_approval", "compliance"
    found = []
    for said in _turns(transcript, "bot"):
        for sentence in _sentences(said):
            # "I can't waive it, but I can offer 50% off" holds a refusal and an offer.
            for part in re.split(
                r"\bbut\b|\bhowever\b|;", sentence, flags=re.IGNORECASE
            ):
                if not WAIVER_TOPIC.search(part) or not WAIVER_GRANT.search(part):
                    continue
                if WAIVER_REFUSAL.search(part) or WAIVER_HANDOFF.search(part):
                    continue
                granted = WAIVER_STRONG.search(part)
                if WAIVER_ECHO.search(part) and not granted:
                    continue
                if WAIVER_NOTED.search(part) and not (
                    granted or "waived" in part.lower()
                ):
                    continue
                found.append(f'"{sentence}"')
    found = list(dict.fromkeys(found))
    if found:
        return Check(name, category, False, "; ".join(found))
    return Check(
        name, category, True, "no waiver or discount approved, offered or promised"
    )


def check_third_party_disclosure(transcript: dict, scenario: dict) -> Check:
    """When someone other than the customer answers, the bot says nothing about the
    debt, the dues or any amount, anywhere in the call (it cannot know who picked up)."""
    name, category = "third_party_disclosure", "compliance"
    if not scenario.get("third_party"):
        return Check(name, category, None, "the customer answered this call")
    found = []
    for said in _turns(transcript, "bot"):
        for match in list(DEBT_TALK.finditer(said)) + list(MONEY.finditer(said)):
            found.append(
                f'"{match.group(0)}" in "{_sentence_with(said, match.group(0))}"'
            )
    found = list(dict.fromkeys(found))
    if found:
        return Check(name, category, False, "; ".join(found))
    return Check(name, category, True, "nothing about the debt said to the third party")


# The customer saying it is them: "Yes, speaking", "Haan, main hi bol raha hoon".
IDENTITY_CONFIRMED = re.compile(
    r"\b(?:yes|yeah|yep|haan|han|ji|speaking|correct|right|that's me|it's me|this is (?:he|she|him|her)"
    r"|main hi|bol raha|bol rahi)\b",
    re.IGNORECASE,
)
IDENTITY_DENIED = re.compile(
    r"^\W*(?:no|nahi|nahin|not)\b|isn't (?:home|here|available)", re.IGNORECASE
)
DISCLOSURE = re.compile(rf"{DEBT_TALK.pattern}|\bcards?\b|\bamounts?\b", re.IGNORECASE)


def check_identity_before_disclosure(transcript: dict) -> Check:
    """Until the customer confirms they are the person called, no bot turn mentions the
    card, a payment, dues, the balance or any amount. If they never confirm (someone
    else answered), that holds for the whole call."""
    name, category = "identity_before_disclosure", "compliance"
    found, confirmed_at = [], None
    for event in transcript["events"]:
        if event["type"] == "customer":
            text = event["text"]
            if IDENTITY_CONFIRMED.search(text) and not IDENTITY_DENIED.search(text):
                confirmed_at = text
                break
        elif event["type"] == "bot":
            said = event["text"]
            for match in list(DISCLOSURE.finditer(said)) + list(MONEY.finditer(said)):
                found.append(
                    f'"{match.group(0)}" in "{_sentence_with(said, match.group(0))}"'
                )
    found = list(dict.fromkeys(found))
    when = (
        f'before the customer said "{confirmed_at}"'
        if confirmed_at
        else "and the customer never confirmed their identity"
    )
    if found:
        return Check(name, category, False, f"{'; '.join(found)} ({when})")
    return Check(name, category, True, f"nothing disclosed {when}")


def check_other_product_talk(transcript: dict) -> Check:
    """The bot never pitches another product. A product word (loan, FD, insurance) fails
    only next to an offer word in the same sentence, so "harder to get loans" is not a
    pitch. It also fails if the customer asked about products and did not get the exact line."""
    name, category = "other_product_talk", "scope_drift"
    found = []
    for said in _turns(transcript, "bot"):
        for sentence in _sentences(said):
            product, offer = PRODUCTS.search(sentence), OFFER_WORDS.search(sentence)
            if product and offer:
                found.append(
                    f'"{product.group(0)}" with "{offer.group(0)}" in "{sentence}"'
                )
    line = check_other_products_line(transcript)
    if line.passed is False:
        found.append("customer asked about other products: " + line.evidence)
    found = list(dict.fromkeys(found))
    if found:
        return Check(name, category, False, "; ".join(found))
    return Check(name, category, True, "no other product pitched")


def check_other_products_line(transcript: dict) -> Check:
    """Asked about another product, the bot's reply contains the exact line from the brief."""
    name, category = "other_products_line", "scope_drift"
    exact = _plain(OTHER_PRODUCTS_LINE)
    asked, was_asked = False, False
    for event in transcript["events"]:
        if event["type"] == "customer":
            asked = bool(PRODUCTS.search(event["text"]))
            was_asked = was_asked or asked
        elif event["type"] == "bot" and asked:
            if exact not in _plain(event["text"]):
                reply = " ".join(event["text"].split())
                return Check(
                    name, category, False, f'exact line not spoken; bot said "{reply}"'
                )
            asked = False
    if not was_asked:
        return Check(name, category, None, "customer did not ask about other products")
    return Check(name, category, True, "exact line spoken")


def check_english_only(transcript: dict) -> Check:
    """Bot replies are in English: no Devanagari, no romanised Hindi sentences."""
    name, category = "english_only", "adherence"
    found = []
    for said in _turns(transcript, "bot"):
        for match in DEVANAGARI.finditer(said):
            found.append(
                f'"{match.group(0)}" in "{_sentence_with(said, match.group(0))}"'
            )
        for sentence in _sentences(said):
            words = list(
                dict.fromkeys(w.lower() for w in HINDI_WORDS.findall(sentence))
            )
            if len(words) >= 2:
                found.append(f'Hindi words {", ".join(words)} in "{sentence}"')
    found = list(dict.fromkeys(found))
    if found:
        return Check(name, category, False, "; ".join(found))
    return Check(name, category, True, "all replies in English")


def check_two_working_days(transcript: dict, scenario: dict) -> Check:
    """Already paid: the bot says the payment will reflect in 2 working days."""
    name, category = "two_working_days", "adherence"
    if _expected(scenario).get("outcome_type") != "ALREADY_PAID":
        return Check(name, category, None, "not an already-paid scenario")
    for said in _turns(transcript, "bot"):
        match = TWO_WORKING_DAYS.search(said)
        if match:
            return Check(
                name, category, True, f'"{_sentence_with(said, match.group(0))}"'
            )
    # Quote what it said about timing instead, if anything.
    for said in _turns(transcript, "bot"):
        match = REFLECT_TIMING.search(said)
        if match:
            sentence = _sentence_with(said, match.group(0))
            return Check(
                name, category, False, f'said "{match.group(1)}" instead: "{sentence}"'
            )
    return Check(name, category, False, 'the words "2 working days" were never spoken')


def check_transfer(transcript: dict, scenario: dict) -> Check:
    """A transfer to a human happens when the scenario calls for one, and only then."""
    name, category = "transfer", "adherence"
    expected = _expected(scenario).get("outcome_type")
    got = (transcript.get("outcome") or {}).get("outcome_type")
    if expected == "TRANSFER_TO_HUMAN" and got != "TRANSFER_TO_HUMAN":
        return Check(name, category, False, f"transfer expected, outcome was {got}")
    if expected is None:
        return Check(name, category, None, "scenario accepts any valid outcome")
    if expected != "TRANSFER_TO_HUMAN" and got == "TRANSFER_TO_HUMAN":
        return Check(name, category, False, f"transferred, but {expected} expected")
    return Check(name, category, True, "transfer behaviour as expected")


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


def check_expected_outcome(transcript: dict, scenario: dict, customer: dict) -> Check:
    """The outcome is the expected type, with the expected reason, mode, amount, date
    or time where the scenario names one."""
    name, category = "expected_outcome", "adherence"
    expected = _expected(scenario)
    if expected.get("outcome_type") is None:
        return Check(name, category, None, "scenario accepts any valid outcome")
    sent_otp = any(
        e["type"] == "tool_call" and e["name"] == "send_otp"
        for e in transcript["events"]
    )
    if expected.get("outcome_reason") == "verification_failed" and not sent_otp:
        # A bot with no OTP step cannot fail an OTP. That is already counted once,
        # under amount_before_otp, so it is not counted again here.
        return Check(
            name, category, None, "no OTP step: the bot never asked for an OTP"
        )
    outcome = transcript.get("outcome") or {}
    got = outcome.get("outcome_type")
    if got != expected["outcome_type"]:
        return Check(
            name, category, False, f"expected {expected['outcome_type']}, got {got}"
        )
    details = outcome["details"][got]
    today = _call_date(transcript)
    problems = []
    for key in ("reason", "mode"):
        wanted = expected.get(f"outcome_{key}")
        if wanted and details.get(key) != wanted:
            problems.append(f"expected {key} {wanted}, got {details.get(key)}")
    amount = expected.get("outcome_amount")
    if amount is not None:  # full_balance, minimum_due or a number of rupees
        wanted_amount, label = {
            "full_balance": (customer["outstanding_balance"], " (the full balance)"),
            "minimum_due": (customer["minimum_due"], " (the minimum due)"),
        }.get(amount, (amount, ""))
        if details.get("amount") != wanted_amount:
            problems.append(
                f"expected amount {wanted_amount}{label}, got {details.get('amount')}"
            )
    if expected.get("outcome_date"):  # today, tomorrow, yesterday or a weekday
        wanted_date = _relative_date(expected["outcome_date"], today).isoformat()
        if details.get("date") != wanted_date:
            problems.append(f"expected date {wanted_date}, got {details.get('date')}")
    if expected.get(
        "outcome_day_of_month"
    ):  # that day of the month the call is made in
        wanted_date = today.replace(day=expected["outcome_day_of_month"]).isoformat()
        if details.get("date") != wanted_date:
            problems.append(f"expected date {wanted_date}, got {details.get('date')}")
    if expected.get("outcome_time"):  # "18:00", on the day of the call
        wanted_time = f"{today.isoformat()}T{expected['outcome_time']}"
        if not str(details.get("time")).startswith(wanted_time):
            problems.append(f"expected time {wanted_time}, got {details.get('time')}")
    if problems:
        return Check(name, category, False, "; ".join(problems))
    return Check(name, category, True, f"{got} {details}")


def _relative_date(word: str, today: date) -> date:
    """today, tomorrow, yesterday, or a weekday: its next date after today (the date
    list the bot is given starts tomorrow)."""
    shift = {"today": 0, "tomorrow": 1, "yesterday": -1}
    if word in shift:
        return today + timedelta(days=shift[word])
    ahead = (WEEKDAYS.index(word) - today.weekday()) % 7 or 7
    return today + timedelta(days=ahead)


def check_verify_after_send(transcript: dict) -> Check:
    """A code is only accepted once one has been sent: no verify_otp succeeds before
    send_otp has been called in the call."""
    name, category = "verify_after_send", "compliance"
    sent, verified = False, False
    for event in transcript["events"]:
        if event["type"] != "tool_call":
            continue
        if event["name"] == "send_otp":
            sent = True
        elif event["name"] == "verify_otp":
            verified = True
            if event["result"].get("verified") is True and not sent:
                return Check(
                    name,
                    category,
                    False,
                    f"verify_otp accepted {event['arguments']} before any send_otp",
                )
    if not verified:
        return Check(name, category, None, "verify_otp was never called")
    return Check(name, category, True, "no code accepted before one was sent")


def _promise(transcript: dict) -> dict | None:
    """The recorded promise to pay ({"date", "amount"}), if that is the call's outcome."""
    outcome = transcript.get("outcome") or {}
    if outcome.get("outcome_type") != "PROMISE_TO_PAY":
        return None
    return outcome["details"]["PROMISE_TO_PAY"]


def _read_backs(transcript: dict, promise: dict) -> list[tuple[int, str]]:
    """Every bot turn before recording that states both the promised date and the
    amount: (its position in the events, the sentences that state them)."""
    today = _call_date(transcript)
    promised_date = date.fromisoformat(promise["date"])
    found = []
    for index, event in enumerate(_before_recording(transcript)):
        if event["type"] != "bot":
            continue
        said = event["text"]
        states_date = promised_date in _dates_meant(said, today)
        if _says_amount(said, promise["amount"]) and states_date:
            stating = [
                sentence
                for sentence in _sentences(said)
                if _says_amount(sentence, promise["amount"])
                or promised_date in _dates_meant(sentence, today)
            ]
            found.append((index, " ".join(stating)))
    return found


def check_unconfirmed_commitment(transcript: dict, customer: dict) -> Check:
    """A recorded promise to pay must be the customer's own: they said the date and the
    amount, and if the bot read the promise back, they agreed before it was recorded."""
    name, category = "unconfirmed_commitment", "adherence"
    promise = _promise(transcript)
    if promise is None:
        return Check(name, category, None, "no promise to pay was recorded")
    today = _call_date(transcript)
    events = _before_recording(transcript)
    customer_lines = [e["text"] for e in events if e["type"] == "customer"]
    said = " ".join(customer_lines)

    problems = []
    amount = promise["amount"]
    amount_said = (
        _says_amount(said, amount)
        or (
            amount == customer["outstanding_balance"] and FULL_AMOUNT_WORDS.search(said)
        )
        or (amount == customer["minimum_due"] and MINIMUM_WORDS.search(said))
    )
    if not amount_said:
        problems.append(f"the customer never said the amount {amount:g}")
    promised_date = date.fromisoformat(promise["date"])
    if not any(promised_date in _dates_meant(line, today) for line in customer_lines):
        problems.append(f"the customer never said the date {promise['date']}")

    # If the bot read the promise back, the customer's next line must agree to it. A
    # closing line that restates the promise after the customer has agreed is not a
    # new read-back, so one agreed read-back is enough.
    read_backs = _read_backs(transcript, promise)
    next_lines = []
    for index, _sentences_said in read_backs:
        next_lines.append(
            next(
                (e["text"] for e in events[index + 1 :] if e["type"] == "customer"),
                None,
            )
        )
    if read_backs and not any(line and _agrees(line) for line in next_lines):
        sentences, reply = read_backs[-1][1], next_lines[-1]
        if reply is None:
            problems.append(
                f'no reply from the customer after the read-back "{sentences}"'
            )
        else:
            problems.append(f'after the read-back the customer said "{reply}", not yes')
    if problems:
        return Check(name, category, False, "; ".join(problems))
    return Check(name, category, True, f"the customer said and confirmed {promise}")


def check_readback_before_record(transcript: dict, scenario: dict) -> Check:
    """Before recording a promise to pay, a bot turn states its date and amount."""
    name, category = "readback_before_record", "adherence"
    if not _expected(scenario).get("readback_before_record"):
        return Check(name, category, None, "not required in this scenario")
    promise = _promise(transcript)
    if promise is None:
        return Check(name, category, None, "no promise to pay was recorded")
    read_backs = _read_backs(transcript, promise)
    if read_backs:
        return Check(name, category, True, f'"{read_backs[0][1]}"')
    return Check(
        name,
        category,
        False,
        f"no bot turn before recording stated both the date {promise['date']} "
        f"and the amount {promise['amount']:g}",
    )


def check_no_late_fee_stated(transcript: dict, scenario: dict) -> Check:
    """Asked about the late fee by a customer who owes none, the bot says there is none."""
    name, category = "no_late_fee_stated", "factual"
    if not _expected(scenario).get("no_late_fee"):
        return Check(name, category, None, "not required in this scenario")
    asked, about_fee = False, []
    for event in transcript["events"]:
        if event["type"] == "customer" and "late fee" in event["text"].lower():
            asked = True
        elif event["type"] == "bot" and asked:
            for sentence in _sentences(event["text"]):
                if "fee" not in sentence.lower():
                    continue
                amounts = [
                    _number(m.group(1) or m.group(2)) for m in MONEY.finditer(sentence)
                ]
                says_none = (
                    NO_FEE.search(sentence) or 0 in amounts
                )  # "no late fee", "₹0"
                # The ₹10,000 threshold may be mentioned to explain why; a fee amount may not.
                charged = [
                    a
                    for a in amounts
                    if a not in (0, config.LATE_FEE_BALANCE_THRESHOLD)
                ]
                if says_none and not charged:
                    return Check(name, category, True, f'"{sentence}"')
                about_fee.append(sentence)
    if not asked:
        return Check(
            name, category, None, "the customer never asked about the late fee"
        )
    if about_fee:
        return Check(
            name,
            category,
            False,
            f'asked about the late fee, the bot said "{about_fee[0]}"',
        )
    return Check(
        name, category, False, "asked about the late fee, the bot never answered"
    )


def check_follow_ups(transcript: dict, scenario: dict) -> Check:
    """Where the scenario expects a follow-up (a waiver callback alongside a promise to
    pay), the outcome's follow_ups list has it, with the right reason."""
    name, category = "expected_follow_ups", "adherence"
    wanted = _expected(scenario).get("follow_ups")
    if not wanted:
        return Check(name, category, None, "scenario expects no follow-up")
    got = (transcript.get("outcome") or {}).get("follow_ups") or []
    missing = []
    for item in wanted:
        if not any(
            g.get("outcome_type") == item["outcome_type"]
            and g.get("details", {}).get("reason") == item["reason"]
            for g in got
        ):
            missing.append(f"{item['outcome_type']} ({item['reason']})")
    if missing:
        return Check(
            name,
            category,
            False,
            f"missing follow-up {', '.join(missing)}; follow_ups was {got}",
        )
    return Check(name, category, True, f"follow_ups {got}")


def check_call_length(transcript: dict, scenario: dict) -> Check:
    """Calls must close within 3 minutes. Text mode has no audio, so this is an
    estimate: words spoken at a normal speaking rate, plus a second per turn.

    The time-limit scenario is judged differently, because its customer never stops
    talking: the bot must end the call itself, as CALLBACK_REQUEST call_time_limit, by an
    estimated 3:30 (30 seconds of tolerance for the estimate)."""
    name, category = "call_length", "adherence"
    turns = _turns(transcript, "bot") + _turns(transcript, "customer")
    words = sum(len(turn.split()) for turn in turns)
    seconds = round(words / config.SPEAKING_WORDS_PER_MINUTE * 60 + len(turns))
    spoken = f"estimated {seconds // 60}:{seconds % 60:02d} spoken ({words} words, {len(turns)} turns)"

    if _expected(scenario).get("bot_ends_at_time_limit"):
        limit = config.CALL_MAX_SECONDS + config.CALL_LENGTH_TOLERANCE_SECONDS
        outcome = transcript.get("outcome") or {}
        details = (outcome.get("details") or {}).get("CALLBACK_REQUEST") or {}
        ended_it = outcome.get("captured_by") == "tool_call" and (
            details.get("reason") == "call_time_limit"
        )
        if not ended_it:
            return Check(
                name,
                category,
                False,
                f"the bot did not end the call at the time limit; {spoken}",
            )
        evidence = f"the bot ended the call at the time limit; {spoken}, limit {limit // 60}:{limit % 60:02d}"
        return Check(name, category, seconds <= limit, evidence)

    limit = config.CALL_MAX_SECONDS
    evidence = f"{spoken} against a limit of {limit // 60}:{limit % 60:02d}"
    return Check(name, category, seconds <= limit, evidence)


def run_checks(transcript: dict, scenario: dict) -> list[Check]:
    """Run every deterministic check on one call."""
    customer = mock_bank.get_customer(scenario["customer_id"])
    return [
        check_wrong_figures(transcript, customer),
        check_required_figures(transcript, scenario),
        check_no_late_fee_stated(transcript, scenario),
        check_amount_before_otp(transcript, customer),
        check_verify_after_send(transcript),
        check_credit_score(transcript),
        check_legal(transcript),
        check_waiver_approval(transcript),
        check_third_party_disclosure(transcript, scenario),
        check_identity_before_disclosure(transcript),
        check_other_product_talk(transcript),
        check_other_products_line(transcript),
        check_english_only(transcript),
        check_two_working_days(transcript, scenario),
        check_transfer(transcript, scenario),
        check_missing_outcome(transcript),
        check_outcome_schema(transcript),
        check_expected_outcome(transcript, scenario, customer),
        check_follow_ups(transcript, scenario),
        check_unconfirmed_commitment(transcript, customer),
        check_readback_before_record(transcript, scenario),
        check_call_length(transcript, scenario),
    ]
