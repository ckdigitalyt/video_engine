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
    "nasa": "NASA", "esa": "ESA", "jpl": "JPL",
    "vs.": "versus", "etc.": "etcetera", "e.g.": "for example",
    "i.e.": "that is", "approx.": "approximately",
    "km/h": "kilometers per hour", "light-years": "light-years",
}

# Uppercase-only expansions (applied case-sensitively so the pronoun
# "us" is never expanded to "U.S." — fixes recurring review finding).
_UPPER_ABBREVIATIONS = {
    "US": "U.S.", "U.S": "U.S.", "USA": "U.S.A.", "UK": "U.K.",
    "NASA": "NASA", "ESA": "ESA", "JPL": "JPL",
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

# ── Prosody ───────────────────────────────────────────────────────────

_PAUSE_HINTS = {
    "hook":        "... ",
    "emotion":     "... ",
    "conclusion":  "... ",
    "reveal":      ", ",
    "scale":       ", ",
    "explanation": ", ",
    "default":     ", ",
}


def apply_prosody(text: str, intent: str = "default") -> str:
    """Tune narration for natural spoken delivery.

    - ensure sentence-level pauses exist (periods/commas)
    - add a breath pause before the final sentence for dramatic beats
    - avoid over-pausing: only insert when punctuation is missing
    """
    if not text:
        return text
    out = text.strip()
    # Ensure terminal punctuation
    if out and out[-1] not in ".!?":
        out += "."
    # Dramatic pause before the last sentence for hook/emotion/conclusion
    if intent in ("hook", "emotion", "conclusion"):
        sentences = [s.strip() for s in out.split(".") if s.strip()]
        if len(sentences) > 1:
            head = ". ".join(sentences[:-1])
            out = f"{head}. ... {sentences[-1]}."
    return out


# ── Language-aware units & symbols (v10, expert rec 3) ──────────────
# Extends the abbreviation table with the units/symbols documentary
# scripts actually use; applied before generic number conversion so
# "1.3 million km" becomes "one point three million kilometers".
_LANG_UNITS = {
    "km/s": "kilometers per second", "km/h": "kilometers per hour",
    "m/s": "meters per second", "mph": "miles per hour",
    "light-years": "light-years", "light-year": "light-year",
    "light-seconds": "light-seconds", "light-minutes": "light-minutes",
    "million": "million", "billion": "billion", "trillion": "trillion",
    "ghz": "gigahertz", "mhz": "megahertz", "khz": "kilohertz", "hz": "hertz",
    "mb": "megabytes", "gb": "gigabytes", "tb": "terabytes",
    "kbps": "kilobits per second", "mbps": "megabits per second",
    "psi": "pounds per square inch", "bar": "bar",
    "n": "newtons", "j": "joules", "w": "watts", "kw": "kilowatts",
    "mw": "megawatts", "gw": "gigawatts",
    "volts": "volts", "kv": "kilovolts",
    "sq km": "square kilometers", "sq km": "square kilometers",
    "fps": "frames per second", "rpm": "revolutions per minute",
}

_LANG_SYMBOLS = [
    (r"\s*&\s*", " and "),
    (r"\s*\+\s*", " plus "),
    (r"\s*=\s*", " equals "),
    (r"\s*±\s*", " plus or minus "),
    (r"\s*→\s*", " to "),
    (r"\s*–\s*(?=\d)", " to "),   # en-dash numeric range: 24–26 -> 24 to 26
    (r"\s*—\s*", ", "),           # em-dash -> pause
    (r"\bvs\.?\b", " versus "),
    (r"\bapprox\.?\b", " approximately "),
]


def apply_language_layer(text: str) -> str:
    """Language-aware preprocessing: unit words, math/typography symbols,
    numeric ranges — before number-to-word conversion (rec 3)."""
    if not text:
        return text
    out = text
    # unit words attached to numbers: "1.3 million km" -> "1.3 million kilometers"
    for unit, full in sorted(_LANG_UNITS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b(\d+(?:\.\d+)?)\s*{re.escape(unit)}\b",
                     lambda m, u=full: f"{m.group(1)} {u}", out,
                     flags=re.IGNORECASE)
    for pat, repl in _LANG_SYMBOLS:
        out = re.sub(pat, repl, out)
    return out


_TECH_RE = re.compile(
    r"\d+(?:\.\d+)?\s*(?:million|billion|trillion|thousand)?\s*(?:km|kg|m|s|au|w|mw|hz|ghz|mhz|kbps|mph|°[cf])\b"
    r"|\b(?:19|20)\d{2}\b"
    r"|[×x^%°]",
    re.IGNORECASE,
)


def apply_pacing_pauses(text: str, pause_density: str = "medium") -> str:
    """Insert natural spoken pauses for comprehension (rec 1/3).

    heavy  : after every sentence containing a number/unit/year, and before
             the final clause (space after key facts)
    medium : pause after sentences with technical terms
    light  : no inserted pauses (hook keeps momentum)
    """
    if not text or pause_density == "light":
        return text
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) < 2:
        return text
    out = []
    for i, s in enumerate(sents):
        out.append(s)
        if i == len(sents) - 1:
            break
        technical = bool(_TECH_RE.search(s))
        if pause_density == "heavy" and technical:
            out.append("... ")
        elif pause_density == "heavy" and len(s.split()) > 16:
            out.append("... ")
        elif pause_density == "medium" and technical and len(s.split()) > 12:
            out.append("... ")
    # avoid double spaces / stray ellipsis spacing
    joined = " ".join(out)
    return re.sub(r"\s+", " ", joined)


def normalize_narration(text: str) -> str:
    """Normalize a narration string for spoken TTS delivery."""
    if not text:
        return text
    out = apply_language_layer(text)

    # Markdown emphasis first: "*our*" / "**bold**" -> "our" / "bold".
    # LLM-written narration often keeps emphasis markers, which TTS reads
    # aloud as "asterisk" and subtitles render literally (Andromeda v5
    # review finding: subtitle at 1:14 showed '*our*').  Only PAIRED
    # asterisks/underscores are stripped — the single "*" used as a
    # multiplication sign in scientific notation below survives.
    out = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", out)
    out = re.sub(r"\*([^*\n]+)\*", r"\1", out)
    out = re.sub(r"`([^`\n]+)`", r"\1", out)
    out = re.sub(r"__([^_\n]+)__", r"\1", out)
    out = re.sub(r"_([^_\n]+)_", r"\1", out)

    # Temperature units BEFORE generic numbers: "127°C" -> "one hundred
    # twenty-seven degrees Celsius" (Chatterbox read raw °C as "jerry C").
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)°\s*C\b",
        lambda m: f"{_decimal_to_words(m.group(1))} degrees Celsius",
        out, flags=re.IGNORECASE,
    )
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)°\s*F\b",
        lambda m: f"{_decimal_to_words(m.group(1))} degrees Fahrenheit",
        out, flags=re.IGNORECASE,
    )

    # Scientific notation: "7.3×10^22" / "7.3 x 10^22" -> "seven point
    # three times ten to the twenty-two" (Chatterbox garbled ^/× symbols).
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)\s*[×xX*]\s*10\s*[\^\^]\s*(\d+)\b",
        lambda m: f"{_decimal_to_words(m.group(1))} times ten to the "
                  f"{_number_to_words(int(m.group(2))) if int(m.group(2)) < 100 else m.group(2)}",
        out,
    )
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)e([+-]?\d+)\b",
        lambda m: f"{_decimal_to_words(m.group(1))} times ten to the "
                  f"{_number_to_words(abs(int(m.group(2)))) if abs(int(m.group(2))) < 100 else m.group(2)}",
        out, flags=re.IGNORECASE,
    )

    # Fractions: "one/six" -> "one sixth" (slash math reads terribly).
    out = re.sub(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s*[/]\s*(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b",
        lambda m: f"{m.group(1)} {_fraction_word(m.group(2))}",
        out, flags=re.IGNORECASE,
    )

    # Tilde before numbers: "~16.7" -> "about sixteen point seven".
    out = re.sub(r"~\s*(\d+(?:\.\d+)?)", lambda m: f"about {m.group(1)}", out)
    # Expand abbreviations (word-boundary aware)
    for abbr, full in sorted(_ABBREVIATIONS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(abbr)}\b", full, out, flags=re.IGNORECASE)

    # Uppercase-only expansions (case-sensitive — never "us" -> "U.S.")
    for abbr, full in sorted(_UPPER_ABBREVIATIONS.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{re.escape(abbr)}\b", full, out)

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
    # (no trailing \b — % is a non-word char; boundary must be lookahead)
    out = re.sub(
        r"\b(\d+(?:\.\d+)?)%(?=\s|[.,;:!?]|$)",
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

    # ── Second pass: symbols attached to WORD numbers (the first pass
    #    only caught digit forms).  "twenty-seven°C", "~seven",
    #    "three×10^22", "one/six" all survive pass 1 because the numbers
    #    have already become words by the time the symbol rules run.
    out = re.sub(
        r"([a-z]+(?:[- ]?[a-z]+)?)°\s*C\b",
        lambda m: f"{m.group(1)} degrees Celsius", out, flags=re.IGNORECASE,
    )
    out = re.sub(
        r"([a-z]+(?:[- ]?[a-z]+)?)°\s*F\b",
        lambda m: f"{m.group(1)} degrees Fahrenheit", out, flags=re.IGNORECASE,
    )
    out = re.sub(r"~\s*([a-z-]+)\b", r"about \1", out, flags=re.IGNORECASE)
    # word-number × 10^word-number (e.g. "three times ten to the twenty-two")
    out = re.sub(
        r"\b([a-z-]+)\s*[×xX*]\s*ten\s*[\^\^]\s*([a-z-]+)\b",
        lambda m: f"{m.group(1)} times ten to the {m.group(2)}", out,
        flags=re.IGNORECASE,
    )
    # fraction word forms: "one sixths" -> "one sixth", "two sixths" stays
    out = re.sub(
        r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\s+(\w+ths)\b",
        lambda m: f"{m.group(1)} {_fraction_singular(m.group(1), m.group(2))}",
        out, flags=re.IGNORECASE,
    )

    # Fix spacing artifacts
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return out.strip()


def _fraction_singular(numerator: str, ths_word: str) -> str:
    """'one sixths' -> 'one sixth'; plural stays for other numerators."""
    if numerator.strip().lower() in ("one", "1"):
        return ths_word[:-1]  # drop the s
    return ths_word


def _fraction_word(s: str) -> str:
    """Map a denominator to its spoken ordinal ('six' -> 'sixth')."""
    words = {"one": "first", "two": "halves", "three": "thirds",
             "four": "fourths", "five": "fifths", "six": "sixths",
             "seven": "sevenths", "eight": "eighths", "nine": "ninths",
             "ten": "tenths"}
    low = s.lower()
    if low in words:
        return words[low]
    if low.isdigit() and int(low) <= 20:
        return _number_to_words(int(low)) + "ths"
    return s


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
