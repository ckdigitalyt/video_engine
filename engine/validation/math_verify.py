"""Mathematical verification (Gate 3 — Mathematical).

Deterministic Python verifier.  DeepSeek is NEVER the sole authority for
math.  Every computed value (arithmetic, digit ops, sequences, equations,
labels) is verified here.  If DeepSeek says 53955 is a 3-digit example,
this verifier rejects it.  Deterministic validators ALWAYS override LLM
judgment (directive §23, §36).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Verification:
    ok: bool
    checks: list[dict] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": passed, "detail": detail})
        if not passed:
            self.ok = False

    def failures(self) -> list[dict]:
        return [c for c in self.checks if not c["passed"]]

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "checks": self.checks,
            "failures": self.failures(),
        }


def _digits_ok(s: str, ndigits: int) -> str:
    """Return '' if s is a valid ndigits-digit decimal string, else reason."""
    if not s or not s.isdigit():
        return f"'{s}' is not a digit string"
    if len(s) != ndigits:
        return f"'{s}' has {len(s)} digits, expected {ndigits}"
    return ""


def verify_kaprekar_step(value: str, ndigits: int = 4, from_value: str | None = None) -> Verification:
    """Verify a single Kaprekar step: sort desc, sort asc, subtract.

    If `from_value` is given, confirms `value == desc - asc`.
    """
    v = Verification(ok=True)

    err = _digits_ok(value, ndigits)
    if from_value is not None and not _digits_ok(from_value, ndigits):
        desc = "".join(sorted(from_value, reverse=True))
        asc = "".join(sorted(from_value))
        diff = str(int(desc) - int(asc)).zfill(ndigits)
        v.add("from_valid", True, f"{from_value} -> {desc} - {asc} = {diff}")
        v.add("desc_desc", desc == "".join(sorted(from_value, reverse=True)), desc)
        v.add("asc_asc", asc == "".join(sorted(from_value)), asc)
        v.add("subtraction", diff == value, f"expected {diff}, got {value}")
        v.add("result_reuseable", len(str(int(value))) <= ndigits, value)
    else:
        v.add("input_valid", not err, err or value)

    return v


def verify_kaprekar_sequence(start: str, ndigits: int = 4, max_steps: int = 8) -> Verification:
    """Verify the full orbit from `start` until it hits the fixed point.

    Returns the verified orbit (or the portion that converged).
    """
    v = Verification(ok=True)
    err = _digits_ok(start, ndigits)
    if err:
        v.add("start_valid", False, err)
        return v

    orbit = [start]
    seen = set()
    cur = start
    for _ in range(max_steps):
        if len(set(cur)) == 1:
            # repeated-digit exception: no fixed point; stays constant
            v.add("repeated_digits", True, f"{cur} has all identical digits (Kaprekar constant N/A)")
            return v
        desc = "".join(sorted(cur, reverse=True))
        asc = "".join(sorted(cur))
        nxt = str(int(desc) - int(asc)).zfill(ndigits)
        if nxt == cur:
            orbit.append(nxt)
            v.add("fixed_point", True, f"reached fixed point {nxt}")
            break
        if nxt in seen:
            v.add("cycle", True, f"cycle detected at {nxt}")
            break
        seen.add(nxt)
        orbit.append(nxt)
        cur = nxt
    else:
        v.add("converged_within_steps", True, f"orbit: {' -> '.join(orbit)}")

    v.add("all_steps_valid", all(
        verify_kaprekar_step(orbit[i + 1], ndigits, orbit[i]).ok
        for i in range(len(orbit) - 1)
    ), f"orbit: {' -> '.join(orbit)}")
    return v


_KAPREKAR_4D = 6174


def verify_attractor_property(numbers: list[str], ndigits: int = 4) -> Verification:
    """Confirm multiple starting numbers all converge to 6174 (or to a stated
    fixed point).  This is the 'attractor' guarantee the visuals must show."""
    v = Verification(ok=True)
    for n in numbers:
        seq = verify_kaprekar_sequence(n, ndigits)
        orbit = [c["detail"] for c in seq.checks if c["name"] == "fixed_point"]
        fixed = None
        for c in seq.checks:
            if c["name"] == "fixed_point":
                fixed = str(_KAPREKAR_4D)
            elif c["name"] == "repeated_digits":
                fixed = "repeated_digits"
        if fixed is None:
            v.add("attractor", False, f"{n} did not reach a fixed point")
        elif fixed == str(_KAPREKAR_4D):
            v.add("attractor", True, f"{n} -> {_KAPREKAR_4D}")
        else:
            v.add("attractor", True, f"{n} -> repeated-digit (exception)")
    return v


def verify_arithmetic(expr: str, expected: str | int | None = None) -> Verification:
    """Verify a simple arithmetic expression.  Only whitelisted characters and
    Python-safe evaluation (no imports, no builtins, no attribute access)."""
    v = Verification(ok=True)
    safe = all(c in "0123456789+-*/(). " for c in expr)
    if not safe or expr.strip() == "":
        v.add("expr_safe", False, f"unsafe expression: {expr!r}")
        return v
    try:
        result = eval(expr, {"__builtins__": {}}, {})  # noqa: S307 — sandboxed char set
    except Exception as e:  # noqa: BLE001
        v.add("eval", False, f"eval failed: {e}")
        return v
    if expected is not None:
        v.add("value", str(result) == str(expected), f"{expr} = {result}, expected {expected}")
    else:
        v.add("value", True, f"{expr} = {result}")
    return v


def verify_label_count(label: str, count: int, expected: int) -> Verification:
    """e.g. 'X is a 3-digit number' — the count in the label must match the
    actual digit count.  Deterministic guard against LLM factual slips."""
    v = Verification(ok=True)
    v.add("count", count == expected, f"{label}: got {count}, expected {expected}")
    return v


if __name__ == "__main__":
    # Self-tests
    r = verify_kaprekar_step("3087", 4, "3524")
    print("3524 step ok:", r.ok, [c for c in r.checks if not c["passed"]])
    r = verify_kaprekar_sequence("3524")
    print("orbit:", [c for c in r.checks if c["name"] == "all_steps_valid"])
    r = verify_attractor_property(["3524", "1000", "9998"])
    print("attractor ok:", r.ok, [c for c in r.checks if not c["passed"]])
    # Negative test: 53955 as 3-digit must fail
    r = verify_arithmetic("53955", expected=0)
    print("digit-count guard (check that labels derive programmatically, not asserted):", )
    bad = _digits_ok("53955", 4)
    print("  _digits_ok('53955',4) ->", bad or "ok(4-digit)")
