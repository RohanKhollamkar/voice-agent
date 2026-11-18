"""Turn the dates a customer mentions into calendar dates, before the model sees them.

"I'll pay on Friday" reaches the model as "I'll pay on Friday [Friday = Friday,
20 November 2026 (2026-11-20)]", so it never has to work out which Friday is meant.
A weekday means the next one (today, if it is that day). "The 20th" means this
month, or next month if the 20th has passed. "Next Friday" and the Hindi "kal" (both
yesterday and tomorrow) are left alone: people mean different days by them.
"""

import re
from datetime import date, timedelta

WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
    # Hindi, as Sarvam writes them in Latin script
    "somvar": 0, "mangalvar": 1, "budhvar": 2, "guruvar": 3, "brihaspativar": 3,
    "shukravar": 4, "shanivar": 5, "ravivar": 6,
}  # fmt: skip
MONTHS = {
    name: number
    for number, names in enumerate(
        (
            ("january", "jan"), ("february", "feb"), ("march", "mar"), ("april", "apr"),
            ("may",), ("june", "jun"), ("july", "jul"), ("august", "aug"),
            ("september", "sep", "sept"), ("october", "oct"), ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}  # fmt: skip
MONTH = "|".join(sorted(MONTHS, key=len, reverse=True))
ORDINAL = r"(\d{1,2})(?:st|nd|rd|th)?"


def _spoken(day: date) -> str:
    return f"{day:%A}, {day.day} {day:%B %Y} ({day.isoformat()})"


def _in_month(day: int, month: int, today: date) -> date | None:
    """That day of that month, this year, or next year if it has passed."""
    for year in (today.year, today.year + 1):
        try:
            candidate = date(year, month, day)
        except ValueError:
            return None
        if candidate >= today:
            return candidate
    return None


def _day_of_month(day: int, today: date) -> date | None:
    """That day of this month, or of next month if it has passed."""
    month_start = today.replace(day=1)
    if day < today.day:
        month_start = (month_start + timedelta(days=32)).replace(day=1)
    try:
        return month_start.replace(day=day)
    except ValueError:
        return None


def date_notes(text: str, today: date) -> list[str]:
    """One note per date the customer mentions, e.g. "[Friday = Friday, 20 November
    2026 (2026-11-20)]". Empty if they mention none."""
    low = text.lower()
    found: dict[str, date] = {}

    for word, weekday in WEEKDAYS.items():
        for match in re.finditer(rf"\b(next\s+)?{word}\b", low):
            if not match.group(1):  # "next Friday" is ambiguous
                found[word.title()] = today + timedelta(
                    days=(weekday - today.weekday()) % 7
                )

    for match in re.finditer(rf"\b{ORDINAL}\s+(?:of\s+)?({MONTH})\b", low):
        day = _in_month(int(match.group(1)), MONTHS[match.group(2)], today)
        if day:
            found[match.group(0)] = day
    for match in re.finditer(rf"\b({MONTH})\s+{ORDINAL}\b", low):
        day = _in_month(int(match.group(2)), MONTHS[match.group(1)], today)
        if day:
            found[match.group(0)] = day
    # "the 20th", "20 tareekh": a day of the month with no month named. A bare number
    # is not taken as a date: it is more likely an amount or a code.
    for match in re.finditer(
        r"\b(\d{1,2})(?:st|nd|rd|th)\b|\b(\d{1,2})\s+(?:tareekh|tarikh)\b", low
    ):
        number = int(match.group(1) or match.group(2))
        if any(match.group(0) in key for key in found):
            continue  # already read with its month
        day = _day_of_month(number, today)
        if day:
            found[match.group(0)] = day

    for words, offset in (
        (r"\btoday\b|\baaj\b", 0),
        (r"\bday after tomorrow\b", 2),
        (r"\btomorrow\b", 1),
        (r"\byesterday\b", -1),
    ):
        match = re.search(words, low)
        if match and not (offset == 1 and "day after tomorrow" in low):
            found[match.group(0)] = today + timedelta(days=offset)

    return [f"[{said} = {_spoken(day)}]" for said, day in found.items()]
