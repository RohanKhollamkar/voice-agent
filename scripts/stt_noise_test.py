"""Check what speech-to-text heard on recorded calls against what was actually said.

For each recorded call you list the customer's lines, in order, as spoken. The script
lines them up with the customer turns in the call's transcript (one line split into
two turns, or two lines merged into one, is handled) and reports, for each line,
whether these came through correctly:

  digits   codes and other digit strings ("482913", "four eight two ...")
  amounts  rupee amounts, and "the full amount" / "the minimum due"
  dates    the calendar dates meant ("Friday", "the 20th", "20 tareekh"), resolved
           as the bot resolves them (agent/dates.py)
  intent   what the customer was doing: confirming, giving the code, promising,
           saying they paid, asking for a waiver, and so on

A check is "-" when the line has nothing for it to check (no digits, no amount ...).

Run from the repo root:
    python -m scripts.stt_noise_test calls.yaml

calls.yaml lists the calls (see scripts/stt_noise_example.yaml):
    - transcript: runs/transcripts/<call_id>.json
      said:
        - "Yes, speaking."
        - "four eight two nine one three"
        - text: "Mujhe court mein mat ghaseetna"
          intent: legal_question      # optional: override the inferred intent
"""

import argparse
import difflib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml

from agent.dates import date_notes
from agent.guardrails import transfer_trigger

DIGIT_WORDS = {
    "zero": "0", "oh": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    # Hindi, in Latin script and in Devanagari
    "shunya": "0", "ek": "1", "do": "2", "teen": "3", "char": "4", "chaar": "4",
    "paanch": "5", "panch": "5", "chhe": "6", "chhah": "6", "che": "6", "saat": "7",
    "aath": "8", "nau": "9",
    "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4", "पांच": "5", "पाँच": "5",
    "छह": "6", "छः": "6", "सात": "7", "आठ": "8", "नौ": "9",
}  # fmt: skip
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
SMALL = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90,
}  # fmt: skip
SCALES = {"hundred": 100, "thousand": 1000, "lakh": 100_000, "lakhs": 100_000}

# Most specific first: the first intent whose words appear wins.
INTENTS = [
    ("already_paid", r"already paid|i paid|paid (?:it|yesterday|today|on)|kar diya|bhar diya|de diya|jama kar"),
    ("dispute", r"never made|not mine|didn't make|did not make|wrong charge|don't recogni[sz]e|galat"),
    ("waiver", r"waive|waiver|maaf|discount|reduce the (?:late )?fee"),
    ("other_product", r"\bloan\b|\bfd\b|fixed deposit|insurance|interest rate on"),
    ("credit_question", r"cibil|credit score"),
    ("legal_question", r"\bcourt\b|\blegal\b|police|lawyer"),
    ("callback", r"call (?:me )?(?:back|later)|busy|driving|baad mein|later"),
    ("promise_to_pay", r"\bpay\b|bhar dunga|bhar doonga|de dunga|kar dunga|jama karunga"),
    ("question", r"\?|how much|kitna|what is|kya hai"),
    ("yes", r"\b(?:yes|yeah|haan|han|ji|speaking|correct|right|sahi|theek|okay|ok)\b|bol raha|bol rahi"),
    ("no", r"\b(?:no|nahi|nahin|not)\b"),
]  # fmt: skip
AMOUNT = re.compile(
    r"(?:₹|\brs\.?|\binr)\s?(\d[\d,]*)|(\d[\d,]*)\s?(?:rupees|rupaye|rs\b)",
    re.IGNORECASE,
)
AMOUNT_WORDS = re.compile(
    r"\bfull\b|\bpura\b|\bpoora\b|\boutstanding\b|\bminimum\b", re.IGNORECASE
)


def normalise(text: str) -> str:
    return text.translate(DEVANAGARI_DIGITS)


def words_to_digits(text: str) -> str:
    """Runs of spoken single digits ("four eight two") written as digits ("482")."""
    out, run = [], []

    def flush() -> None:
        if len(run) >= 3:  # three or more digit words in a row: a code, read out
            out.append("".join(DIGIT_WORDS[word] for word in run))
        else:  # one or two ("do din", "one moment"): ordinary words
            out.extend(run)
        run.clear()

    for token in re.findall(r"[\wऀ-ॿ]+|\S", normalise(text).lower()):
        if token in DIGIT_WORDS:
            run.append(token)
            continue
        flush()
        out.append(token)
    flush()
    return " ".join(out)


def spoken_number(text: str) -> int | None:
    """ "two thousand five hundred" -> 2500 (English words only)."""
    total, current, found = 0, 0, False
    for word in re.findall(r"[a-z]+", text.lower()):
        if word in SMALL:
            current += SMALL[word]
            found = True
        elif word in SCALES:
            current = max(current, 1) * SCALES[word]
            if SCALES[word] >= 1000:
                total, current = total + current, 0
            found = True
        elif word not in ("and",) and found:
            break
    return total + current if found else None


def amounts(text: str) -> set[str]:
    text = normalise(text)
    found = {(a or b).replace(",", "") for a, b in AMOUNT.findall(text)}
    for match in re.finditer(r"([a-z ]+?)\s+(?:rupees|rupaye)", text.lower()):
        number = spoken_number(match.group(1))
        if number:
            found.add(str(number))
    for word in AMOUNT_WORDS.findall(text):
        word = word.lower()
        found.add("minimum" if word == "minimum" else "full")
    return found


def digits(text: str) -> str:
    """The code-like digits: every digit outside amounts and dates, in order."""
    text = AMOUNT.sub(" ", words_to_digits(text))
    text = re.sub(
        r"\b\d{1,2}(?:st|nd|rd|th)\b|\b\d{1,2}\s+(?:tareekh|tarikh)\b", " ", text
    )
    run = "".join(re.findall(r"\d", text))
    return run if len(run) >= 3 else ""


def dates(text: str, day: date) -> set[str]:
    return {
        note.rsplit("(", 1)[1].rstrip(")]") for note in date_notes(normalise(text), day)
    }


def intent(text: str) -> str:
    text = words_to_digits(text)
    trigger = transfer_trigger(text)
    if trigger:
        return trigger
    if len(digits(text)) >= 4 and not re.search(r"[a-z]{4,}", AMOUNT.sub("", text)):
        return "otp"
    for name, pattern in INTENTS:
        if re.search(pattern, text):
            return name
    return "other"


def similarity(a: str, b: str) -> float:
    a, b = words_to_digits(a).lower(), words_to_digits(b).lower()
    return difflib.SequenceMatcher(None, a, b).ratio()


def align(said: list[str], heard: list[str]) -> list[str]:
    """For each line said, the text heard for it. A line split over two turns gets
    both; two lines merged into one turn both get that turn; a line that was lost
    (the next line matches this turn better) gets nothing."""
    result, h = [], 0
    for index, line in enumerate(said):
        if h >= len(heard):
            result.append("")
            continue
        alone = similarity(line, heard[h])
        if (
            index + 1 < len(said)
            and similarity(said[index + 1], heard[h]) > alone + 0.3
        ):
            result.append("")  # nothing was heard for this line
            continue
        with_next = (
            similarity(line, heard[h] + " " + heard[h + 1]) if h + 1 < len(heard) else 0
        )
        merged_with_next_line = (
            similarity(line + " " + said[index + 1], heard[h])
            if index + 1 < len(said)
            else 0
        )
        if merged_with_next_line > alone + 0.15:
            result.append(heard[h])  # this line and the next were heard as one turn
            continue
        if with_next > alone + 0.15:
            result.append(heard[h] + " " + heard[h + 1])  # this line was split in two
            h += 2
            continue
        result.append(heard[h])
        h += 1
    return result


def check(expected, heard) -> str:
    if not expected:
        return "-"
    return "ok" if expected == heard else "WRONG"


def report(calls: list[dict]) -> int:
    totals = {name: [0, 0] for name in ("digits", "amounts", "dates", "intent")}
    for call in calls:
        transcript = json.loads(Path(call["transcript"]).read_text(encoding="utf-8"))
        day = datetime.fromisoformat(transcript["started_at"]).date()
        heard_turns = [
            e["text"] for e in transcript["events"] if e["type"] == "customer"
        ]
        said = [s if isinstance(s, dict) else {"text": s} for s in call["said"]]
        heard = align([s["text"] for s in said], heard_turns)
        print(f"\n{call['transcript']}")
        for line, text in zip(said, heard, strict=True):
            wanted_intent = line.get("intent") or intent(line["text"])
            results = {
                "digits": check(digits(line["text"]), digits(text)),
                "amounts": check(amounts(line["text"]), amounts(text)),
                "dates": check(dates(line["text"], day), dates(text, day)),
                "intent": "ok" if intent(text) == wanted_intent else "WRONG",
            }
            for name, result in results.items():
                if result != "-":
                    totals[name][1] += 1
                    totals[name][0] += result == "ok"
            marks = "  ".join(f"{name} {result}" for name, result in results.items())
            print(f"  said:  {line['text']}")
            print(f"  heard: {text or '(nothing)'}")
            detail = (
                ""
                if results["intent"] == "ok"
                else f" (said {wanted_intent}, heard {intent(text)})"
            )
            print(f"         {marks}{detail}")
    print("\nCorrect, out of the lines each check applied to:")
    wrong = 0
    for name, (good, applied) in totals.items():
        print(f"  {name:8} {good}/{applied}")
        wrong += applied - good
    return wrong


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check speech-to-text on recorded calls."
    )
    parser.add_argument(
        "calls", help="YAML file listing transcripts and the lines said"
    )
    args = parser.parse_args()
    calls = yaml.safe_load(Path(args.calls).read_text(encoding="utf-8"))
    sys.exit(1 if report(calls) else 0)


if __name__ == "__main__":
    main()
