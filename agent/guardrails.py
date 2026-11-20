"""Code guardrails for v2 that do not rely on the prompt.

- check_reply: runs on every bot reply before it is spoken. Strips tool-call markup
  the model sometimes writes as text. Blocks figures that do
  not come from tools, config or the customer, credit-score talk, legal talk and
  waiver approval, replacing each offending sentence with a safe line.
- transfer_trigger: reads the customer's words for abuse, a medical emergency or
  job loss, so the call is handed to a human even if the model misses it.
- promise_problems: a promise to pay is only recorded if the customer said the date
  and amount and has just agreed to it.
- closing_line: the one line spoken after the outcome is recorded, built from the
  outcome itself.
- spoken_seconds: the call timer's clock in text mode, estimated from words spoken.

These are written separately from the eval checks in evals/checks.py on purpose, so
the evals still measure the bot rather than repeat the guardrail's own patterns.
"""

import re
from datetime import date, datetime, timedelta

import config

# Lines spoken in place of a blocked sentence.
SAFE_LINES = {
    "credit_score": "I'm not able to comment on that. I can help you with the payment itself.",
    "legal": "I'm not able to advise on that. I'm here to help you settle the payment.",
    "waiver": "I've noted your request. A colleague from the bank will call you back about the late fee.",
    "figure_before_otp": "I can share the details as soon as you're verified.",
    "figure": "A colleague will confirm the exact figure.",
}

CREDIT_SCORE = re.compile(
    r"cibil|credit\s*(?:score|rating|report|history|record|bureau)s?|creditworth\w*",
    re.IGNORECASE,
)
LEGAL = re.compile(
    r"\blegal\w*|\bcourts?\b|lawsuit|\bsue[sd]?\b|lawyer|advocate|police|arrest|\bjail\b"
    r"|recovery agent",
    re.IGNORECASE,
)
WAIVER = re.compile(
    r"\bwaiv\w*|\bdiscount\w*|\bconcession\w*|\bsettlement\b|reduc\w* (?:the |your )?(?:late )?fee",
    re.IGNORECASE,
)
# A waiver sentence is allowed only if it hands the request to a person or refuses it.
WAIVER_ALLOWED = re.compile(
    r"\bnoted\b|\bcolleague\b|\bcall you back\b|\bcallback\b|\bnot able\b|\bcannot\b"
    r"|\bcan't\b|\bunable\b",
    re.IGNORECASE,
)

# Tool-call markup some models write into their text, e.g. "<|tool_call>begin?x<end|>".
MARKUP = re.compile(r"<\|[^<>]*>[^<>]*<[^<>]*\|>|<\|[^<>]*\|?>|<[^<>]*\|>")
GOODBYE = re.compile(
    r"\bgood ?bye\b|\bbye\b|have a (?:good|great|nice) day", re.IGNORECASE
)

NUMBER = r"\d(?:[\d,]*\d)?(?:\.\d+)?"
MONEY = re.compile(
    rf"(?:₹|\brs\.?\s?|\binr\s?)\s?({NUMBER})|({NUMBER})\s?rupees", re.IGNORECASE
)
PERCENT = re.compile(rf"({NUMBER})\s?(?:%|percent|per cent)", re.IGNORECASE)
MONTHS = (
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?"
    r"|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
)
# Dates and times are read back to the customer, so their numbers are allowed.
DATES_AND_TIMES = re.compile(
    rf"\b\d{{4}}-\d{{2}}-\d{{2}}(?:T[\d:+.]+)?"  # 2026-11-20, 2026-11-17T18:00:00+05:30
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:of\s+)?(?:{MONTHS})\b"  # 20 November, 20th of Nov
    rf"|\b(?:{MONTHS})\s+\d{{1,2}}(?:st|nd|rd|th)?\b"  # November 20th
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)\b"  # the 20th
    rf"|\b\d{{1,2}}(?::\d{{2}})?\s*(?:a\.?m\.?|p\.?m\.?)"  # 6 pm, 6:30 pm
    rf"|\b\d{{1,2}}:\d{{2}}\b"  # 18:00
    rf"|\b20\d{{2}}\b",  # a year
    re.IGNORECASE,
)

MEDICAL = re.compile(
    r"medical emergency|\bicu\b|surgery|operation|heart attack|accident|\bemergency\b"
    r"|hospital\w*\W+(?:\w+\W+){0,4}(?:admit\w*|bharti|serious|critical)"
    r"|(?:admit\w*|bharti)\W+(?:\w+\W+){0,4}hospital",
    re.IGNORECASE,
)
JOB_LOSS = re.compile(
    r"lost (?:my|the|his|her) job|lost my work|laid off|been fired|got fired|unemployed"
    r"|no job|jobless|no income|without (?:a )?job|(?:job|naukri)\s+(?:chali|chhoot|chhut|chut|gayi)",
    re.IGNORECASE,
)
ABUSE = re.compile(
    r"\bidiots?\b|\bstupid\b|\bthie(?:f|ves)\b|\bfools?\b|\bbloody\b|shut up|get lost"
    r"|\bbastards?\b|damn you|\bchor\b|\bbakwas\b|\bpagal\b|\bkamine\w*|\bharami\b|\bsaala\b"
    r"|\bgadha\b|\bbewakoof\b|\bdeaf\b",
    re.IGNORECASE,
)

AGREEMENT = re.compile(
    r"\b(?:yes|yeah|yep|haan|han|ji|correct|right|sahi|theek|thik|ok|okay|sure|fine"
    r"|agreed?|confirm\w*|done|go ahead)\b",
    re.IGNORECASE,
)
FULL_BALANCE_WORDS = re.compile(
    r"\bfull\b|\bentire\b|\bwhole\b|\bpura\b|\bpoora\b|\boutstanding\b|\btotal\b",
    re.IGNORECASE,
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


def _number(text: str) -> float:
    return float(text.replace(",", ""))


def _sentences(text: str) -> list[str]:
    flat = " ".join(text.split())
    parts = re.split(r"(?<!Mr\.)(?<!Mrs\.)(?<!Ms\.)(?<!Dr\.)(?<=[.?!])\s+", flat)
    return [part for part in parts if part]


def numbers_in(text: str) -> set[float]:
    return {_number(n) for n in re.findall(NUMBER, text)}


def check_reply(
    text: str, allowed: set[float], verified: bool
) -> tuple[str, list[dict]]:
    """Check a reply sentence by sentence before it is spoken.

    allowed: the numbers the bot may say, from config, tool results and the customer.
    Returns the reply to speak and one entry per blocked sentence.
    """
    spoken, blocks = [], []
    for sentence in _sentences(MARKUP.sub(" ", text)):
        rule = None
        if CREDIT_SCORE.search(sentence):
            rule = "credit_score"
        elif LEGAL.search(sentence):
            rule = "legal"
        elif WAIVER.search(sentence) and not WAIVER_ALLOWED.search(sentence):
            rule = "waiver"
        else:
            money = [
                _number(m.group(1) or m.group(2)) for m in MONEY.finditer(sentence)
            ]
            percents = {_number(p) for p in PERCENT.findall(sentence)}
            if not verified and any(amount not in allowed for amount in money):
                rule = "figure_before_otp"
            elif percents - {float(config.MONTHLY_INTEREST_RATE_PERCENT)}:
                rule = "figure"  # the only rate the bot may quote is 3.5% a month
            elif numbers_in(DATES_AND_TIMES.sub(" ", sentence)) - allowed:
                rule = "figure"
        if rule is None:
            spoken.append(sentence)
            continue
        blocks.append(
            {"rule": rule, "sentence": sentence, "replaced_with": SAFE_LINES[rule]}
        )
        if SAFE_LINES[rule] not in spoken:  # say each safe line once
            spoken.append(SAFE_LINES[rule])
    return " ".join(spoken), blocks


def config_numbers() -> set[float]:
    """The figures from config the bot may always say: 3.5, 750, 10,000 and 2."""
    return {
        float(config.MONTHLY_INTEREST_RATE_PERCENT),
        float(config.LATE_FEE_RUPEES),
        float(config.LATE_FEE_BALANCE_THRESHOLD),
        2.0,  # "2 working days"
    }


def transfer_trigger(customer_text: str) -> str | None:
    """The TRANSFER_TO_HUMAN reason the customer's words call for, if any."""
    if MEDICAL.search(customer_text):
        return "medical_emergency"
    if JOB_LOSS.search(customer_text):
        return "job_loss"
    if ABUSE.search(customer_text):
        return "abusive"
    return None


def dates_meant(text: str, today: date) -> set[date]:
    """The calendar dates a customer's words can mean: "Friday", "20 tareekh", "kal"."""
    low, dates = text.lower(), set()
    for index, name in enumerate(WEEKDAYS):
        if name in low:
            ahead = (index - today.weekday()) % 7
            dates |= {today + timedelta(days=ahead), today + timedelta(days=ahead + 7)}
    if re.search(r"\btoday\b|\baaj\b|right now|right away", low):
        dates.add(today)
    if re.search(r"\btomorrow\b|\bkal\b", low):
        dates.add(today + timedelta(days=1))
    for day in re.findall(r"(?<![\d,.₹])\b(\d{1,2})(?:st|nd|rd|th)?\b(?![,.]?\d)", low):
        month_start = today.replace(day=1)
        if int(day) < today.day:  # "the 5th" said on the 17th means next month
            month_start = (month_start + timedelta(days=32)).replace(day=1)
        try:
            dates.add(month_start.replace(day=int(day)))
        except ValueError:
            pass
    for iso in re.findall(r"\d{4}-\d{2}-\d{2}", low):
        try:
            dates.add(date.fromisoformat(iso))
        except ValueError:
            pass
    return dates


def promise_problems(
    details: dict, customer_turns: list[str], customer: dict, today: date
) -> list[str]:
    """Why a promise to pay may not be recorded yet ([] if it may).

    The customer must have said the date and the amount, and their last turn must
    be an agreement (a yes-word in its first few words)."""
    problems = []
    said = " ".join(customer_turns)
    amount = details.get("amount")
    amount_said = (
        amount in numbers_in(said)
        or (
            amount == customer["outstanding_balance"]
            and FULL_BALANCE_WORDS.search(said)
        )
        or (amount == customer["minimum_due"] and MINIMUM_WORDS.search(said))
    )
    if not amount_said:
        problems.append(f"the customer has not said the amount {amount}")
    try:
        promised = date.fromisoformat(str(details.get("date")))
    except ValueError:
        promised = None
    if promised is None or not any(
        promised in dates_meant(t, today) for t in customer_turns
    ):
        problems.append(f"the customer has not said the date {details.get('date')}")
    last = customer_turns[-1] if customer_turns else ""
    if not AGREEMENT.search(" ".join(last.split()[:6])):
        problems.append(
            "the customer's last reply was not a yes to the date and amount"
        )
    return problems


def spoken_seconds(turns: list[str]) -> int:
    """How long the call has taken, estimated from the words spoken: the same estimate
    the evals use, at a normal speaking rate plus a second per turn."""
    words = sum(len(turn.split()) for turn in turns)
    return round(words / config.SPEAKING_WORDS_PER_MINUTE * 60 + len(turns))


def rupees(amount: float) -> str:
    """₹48,500 and ₹1,26,000: Indian digit grouping."""
    whole = round(amount)
    text = str(whole)
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        head = ",".join(re.findall(r"\d{1,2}", head[::-1]))[
            ::-1
        ]  # pairs from the right
        text = f"{head},{tail}"
    return f"₹{text}"


def _spoken_date(iso: str, today: date) -> str:
    """When, as said in a sentence: "today", "tomorrow", "yesterday" or "on Friday,
    20 November" (the preposition is part of it, so "on today" never comes out)."""
    day = date.fromisoformat(iso)
    near = {0: "today", 1: "tomorrow", -1: "yesterday"}.get((day - today).days)
    return near or f"on {day:%A}, {day.day} {day:%B}"


def _spoken_time(iso: str | None, today: date) -> str:
    if not iso:
        return "later"
    moment = datetime.fromisoformat(iso)
    clock = f"{moment:%I:%M %p}".lstrip("0").replace(":00", "").lower()
    day = (
        "today"
        if moment.date() == today
        else f"on {moment:%A}, {moment.day} {moment:%B}"
    )
    return f"{day} at {clock}"


def closing_line(
    outcome_type: str, details: dict, follow_ups: list, today: date
) -> str:
    """The last thing the bot says, built from the recorded outcome. It restates what
    was agreed and never asks if there is anything else."""
    reason = details.get("reason")
    if outcome_type == "PROMISE_TO_PAY":
        line = (
            f"Thank you. I've noted that you will pay {rupees(details['amount'])} "
            f"{_spoken_date(details['date'], today)}."
        )
        if any(
            f.get("details", {}).get("reason") == "waiver_request" for f in follow_ups
        ):
            line += " A colleague will call you back about the late fee."
        return line + " Goodbye."
    if outcome_type == "ALREADY_PAID":
        return (
            f"Thank you. Your {details['mode']} payment "
            f"{_spoken_date(details['date'], today)} may take up to 2 working days to "
            "reflect. Goodbye."
        )
    if outcome_type == "DISPUTE":
        return (
            "Thank you. I've noted that you are disputing a charge, and a colleague will "
            "look into it and get back to you. Goodbye."
        )
    if outcome_type == "TRANSFER_TO_HUMAN":
        if reason in ("medical_emergency", "job_loss"):
            return "I'm sorry to hear that. I'm connecting you with a colleague who can help."
        return "I'm connecting you with a colleague now."
    # CALLBACK_REQUEST
    if reason == "waiver_request":
        return (
            "Thank you. I've noted your request, and a colleague from the bank will call "
            "you back about the late fee. Goodbye."
        )
    if reason == "verification_failed":
        return "I'm sorry, I couldn't verify you, so a colleague will call you back. Goodbye."
    if reason == "call_time_limit":
        return "We're out of time for today, so a colleague will call you back. Thank you, goodbye."
    return f"Thank you. We'll call back {_spoken_time(details.get('time'), today)}. Goodbye."
