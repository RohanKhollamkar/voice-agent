"""Turn the bot's written reply into words a speech service reads correctly.

Runs after the reply check and before speech. ₹750 becomes "seven hundred and fifty
rupees", 3.5% becomes "three point five percent", 20 November becomes "the twentieth
of November", 6 pm becomes "six p m", and a code such as 0001 is read digit by digit.
"""

import re
from datetime import date

from num2words import num2words

NUMBER = r"\d(?:[\d,]*\d)?(?:\.\d+)?"
MONTHS = [
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
]
MONTH = r"(?:" + "|".join(m for m in MONTHS) + r")"


def _words(number: str) -> str:
    """Digits to words, with Indian grouping (lakh, crore) and no commas, which TTS
    would read as pauses."""
    value = float(number.replace(",", ""))
    if value.is_integer():
        value = int(value)
    return num2words(value, lang="en_IN").replace(",", "")


def _day(day: str) -> str:
    return "the " + num2words(int(day), to="ordinal")


def _iso_date(match: re.Match) -> str:
    try:
        day = date.fromisoformat(match.group(0))
    except ValueError:
        return match.group(0)
    return f"{_day(str(day.day))} of {day:%B} {num2words(day.year, to='year')}"


def _time(match: re.Match) -> str:
    hour, minute, half = match.group(1), match.group(2), match.group(3)
    spoken = num2words(int(hour))
    if minute and minute != "00":
        spoken += " " + (
            f"oh {num2words(int(minute))}"
            if minute.startswith("0")
            else num2words(int(minute))
        )
    stop = "." if match.group(4) else ""  # the full stop the pattern took with "pm."
    return f"{spoken} {'a m' if half.lower().startswith('a') else 'p m'}{stop}"


def _clock(match: re.Match) -> str:
    hour, minute = int(match.group(1)), int(match.group(2))
    half = "a m" if hour < 12 else "p m"
    spoken = num2words(hour % 12 or 12)
    return f"{spoken}{' ' + num2words(minute) if minute else ''} {half}"


def speakable(text: str) -> str:
    """The reply as it should be spoken."""
    # Dates first, so their numbers are not read as amounts.
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}\b", _iso_date, text)
    text = re.sub(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({MONTH})\b",
        lambda m: f"{_day(m.group(1))} of {m.group(2).title()}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"\b({MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b",
        lambda m: f"{_day(m.group(2))} of {m.group(1).title()}",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"\b(20\d{2})\b", lambda m: num2words(int(m.group(1)), to="year"), text
    )
    text = re.sub(r"\bthe (\d{1,2})(?:st|nd|rd|th)\b", lambda m: _day(m.group(1)), text)
    text = re.sub(r"\b(\d{1,2})(?:st|nd|rd|th)\b", lambda m: _day(m.group(1)), text)
    # Times: 6 pm, 6:30 p.m., 18:00.
    text = re.sub(
        r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s?m(\.?)(?=\W|$)",
        _time,
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", _clock, text)
    # Money: ₹750, Rs. 750, INR 750, 750 rupees.
    text = re.sub(
        rf"(?:₹|\bRs\.?|\bINR)\s?({NUMBER})",
        lambda m: f"{_words(m.group(1))} rupees",
        text,
    )
    text = re.sub(
        rf"\b({NUMBER})\s?rupees\b",
        lambda m: f"{_words(m.group(1))} rupees",
        text,
        flags=re.IGNORECASE,
    )
    # Percentages.
    text = re.sub(
        rf"\b({NUMBER})\s?(?:%|per ?cent\b)",
        lambda m: f"{_words(m.group(1))} percent",
        text,
    )
    # A number with a leading zero is a code or part of a phone number: digit by digit.
    text = re.sub(
        r"\b0\d+\b", lambda m: " ".join(num2words(int(d)) for d in m.group(0)), text
    )
    # Any other number.
    text = re.sub(rf"\b{NUMBER}\b", lambda m: _words(m.group(0)), text)
    return re.sub(r"\s{2,}", " ", text).strip()
