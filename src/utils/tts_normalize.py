"""
tts_normalize.py — Narration text normalization for TTS.

Fixes the v2 regression where Kokoro read "Sept 5, 1977" as "Sept five"
instead of "September fifth, nineteen seventy-seven".  Expands
abbreviations, formats numbers/dates/years for spoken narration, and
normalizes units.

Pipeline usage: apply to each scene's narration BEFORE TTS generation.
"""

from __future__ import annotations

import re

# ── Abbreviation expansion ──────────────────────────────────────────────

_ABBREVIATIONS = {
    # months
    "jan.": "January", "feb.": "February", "mar.": "March", "apr.": "April",
    "jun.": "June", "jul.": "July", "aug.": "August", "sep.": "September",
    "sept.": "September", "oct.": "October", "nov.": "November", "dec.": "December",
    "jan": "January", "feb": "February", "mar": "March", "apr": "April",
    "jun": "June", "jul": "July", "aug": "August", "sep": "September",
    "sept": "September", "oct": "October", "nov": "November", "dec": "December",
    # units
    "km": "kilometers", "km/s": "kilometers per second",
    "kg": "kilograms", "g": "grams", "m": "meters", "cm": "centimeters",
    "mm": "millimeters", "au": "astronomical units",
    "mph": "miles per hour", "kbps": "kilobits per second",
    "w": "watts", "kw": "kilowatts", "mw": "megawatts",
    "sec": "seconds", "sec.": "seconds", "min": "minutes", "hr": "hours",
    "hrs": "hours", "yr": "years", "yrs": "years",
    # misc
    "nasa": "NASA", "esa": "ESA", "jpl": "JPL", "us": "U.S.",
    "vs.": "versus", "etc.": "etcetera", "e.g.": "for example",
    "i.e.": "that is", "approx.": "approximately",
    "km/h": "kilometers per hour", "light-years": "light-years",
}

# Years: 1977 -> "nineteen seventy-seven"; 2000 -> "two thousand"; 2012 -> "twenty twelve"
def _year_to_words(year: int) -> str:
    if 2000 <= year <= 2009:
        return f"two thousand {_two_digit(year - 2000)}" if year != 2000 else "two thousand"
    if 2010 <= year <= 2099:
        return f"twenty {_two_digit(year - 2000)}"
    if 1900 <= year <= 1999:
        y = year - 1900
        if y < 10:
            return f"nineteen oh {_digit(y)}"
        return f"nineteen {_two_digit(y)}"
    if 1000 <= year <= 1899:
        return _group_year(year)
    return str(year)


def _group_year(year: int) -> str:
    s = str(year)
    return f"{_number_to_words(int(s[:2]))} {_two_digit(int(s[2:]))}" if len(s) == 4 else _number_to_words(year)


def _digit(d: int) -> str:
    return ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"][d]


def _two_digit(n: int) -> str:
    if n < 10:
        return _digit(n)
    return _number_to_words(n)


def _number_to_words(n: int) -> str:
    """Convert an integer to spoken words (supports 0..999999)."""
    ones = ["", "one", "two", "three", "four", "five", "six", "seven",
            "eight", "nine", "ten", "eleven", "twelve", "thirteen",
            "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty",
            "seventy", "eighty", "ninety"]
    if n < 20:
        return ones[n]
    if n < 100:
        return f"{tens[n // 10]}-{ones[n % 10]}" if n % 10 else tens[n // 10]
    if n < 1000:
        return f"{ones[n // 100]} hundred" + (f" {_number_to_words(n % 100)}" if n % 100 else "")
    if n < 1_000_000:
        return f"{_number_to_words(n // 1000)} thousand" + (f" {_number_to_words(n % 1000)}" if n % 1000 else "")
    return str(n)


# ── Main normalization ──────────────────────────────────────────────────

def normalize_narration(text: str) -> str:
    """Normalize a narration string for spoken TTS delivery."""
    if not text:
        return text
    out = text

    # Expand abbreviations (word-boundary aware)
    for abbr, full in sorted(_ABBREVIATIONS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(abbr)}\b", full, out, flags=re.IGNORECASE)

    # Dates: "Sept 5, 1977" / "September 5, 1977" -> spoken
    out = re.sub(
        r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\b",
        lambda m: f"{m.group(1)} {_number_to_words(int(m.group(2)))}, {_year_to_words(int(m.group(3)))}",
        out, flags=re.IGNORECASE,
    )

    # Bare years (4-digit, 1000-2099) not already handled
    out = re.sub(
        r"\b(1[89]\d{2}|20[01]\d)\b",
        lambda m: _year_to_words(int(m.group(0))),
        out,
    )

    # Percentages: "23%" -> "twenty-three percent"
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)%\b",
        lambda m: f"{_decimal_to_words(m.group(1))} percent",
        out,
    )

    # Large numbers with commas: "24,000" -> "twenty-four thousand"
    out = re.sub(
        r"\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b",
        lambda m: _decimal_to_words(m.group(1).replace(",", "")),
        out,
    )

    # Decimals: "22.9" -> "twenty-two point nine" (before integer pass)
    out = re.sub(
        r"\b(\d+\.\d+)\b",
        lambda m: _decimal_to_words(m.group(1)),
        out,
    )

    # Small whole numbers in text (1-999999), standalone
    out = re.sub(
        r"\b(\d{1,6})\b",
        lambda m: _number_to_words(int(m.group(1))) if int(m.group(1)) < 1000000 else m.group(0),
        out,
    )

    # Fix spacing artifacts
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out.strip()


def _decimal_to_words(s: str) -> str:
    if "." in s:
        whole, frac = s.split(".", 1)
        w = _number_to_words(int(whole)) if whole else "zero"
        f = " ".join(_digit(int(d)) for d in frac if d.isdigit())
        return f"{w} point {f}"
    return _number_to_words(int(s))


if __name__ == "__main__":
    tests = [
        "Voyager 1 was launched on Sept 5, 1977 from Cape Canaveral.",
        "It travels at 61,000 km/h and is 24 billion km from Earth.",
        "Its signal takes 22.9 hours to reach Earth.",
        "By 2030, its power will fade after 53 years.",
        "The probe weighs 722 kg and carries a 23-watt transmitter.",
    ]
    for t in tests:
        print(f"IN : {t}\nOUT: {normalize_narration(t)}\n")
