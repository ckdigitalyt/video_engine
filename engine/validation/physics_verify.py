"""Deterministic physics/science verifiers (JADE_TO_DO v0.3 §16, §18, §19).

Extends engine.validation.math_verify with generic physics verifiers used by
the world model + compiler.  DeepSeek is NEVER the authority for physics:
every quantitative claim in a WorldState fact or a beat transformation is
re-verified here before rendering.

All functions are pure/deterministic (no I/O, no RNG) and return a
Verification with per-check details.
"""

from __future__ import annotations

import math

from engine.validation.math_verify import Verification


# ── constants (verified values) ──────────────────────────────────────────
GRAVITATIONAL_CONSTANT = 6.67430e-11     # m^3 kg^-1 s^-2 (CODATA 2018)
EARTH_MASS = 5.9722e24                   # kg (NASA fact sheet)
EARTH_RADIUS = 6.371e6                   # m
VISIBLE_BLUE_NM = 450.0
VISIBLE_RED_NM = 650.0


def verify_rayleigh_ratio(lambda_a_nm: float = VISIBLE_BLUE_NM,
                          lambda_b_nm: float = VISIBLE_RED_NM) -> Verification:
    """Verify the Rayleigh scattering ratio between two wavelengths.

    I ∝ 1/λ⁴, so the ratio of scattering of λ_a vs λ_b is (λ_b/λ_a)⁴.
    For blue 450 nm vs red 650 nm this is ≈ 4.3 — the standard
    "blue scatters ~4x more than red" claim.
    """
    v = Verification(ok=True)
    if lambda_a_nm <= 0 or lambda_b_nm <= 0:
        v.add("wavelengths_positive", False, "wavelengths must be > 0")
        return v
    ratio = (lambda_b_nm / lambda_a_nm) ** 4
    v.add("ratio_positive", ratio > 1, f"ratio = {ratio:.2f}")
    # sanity: the known blue/red pair must land in the expected band
    if abs(lambda_a_nm - VISIBLE_BLUE_NM) < 1 and abs(lambda_b_nm - VISIBLE_RED_NM) < 1:
        v.add("blue_red_known_value", 3.5 < ratio < 5.0,
              f"blue/red Rayleigh ratio ≈ {ratio:.2f} (expected ≈4.3)")
    return v


def verify_orbital_speed(r_m: float, m_kg: float = EARTH_MASS,
                         g: float = GRAVITATIONAL_CONSTANT) -> Verification:
    """Verify circular orbital speed v = sqrt(G M / r).

    Returns the speed in m/s via a check detail (deterministic recompute).
    """
    v = Verification(ok=True)
    if r_m <= 0 or m_kg <= 0:
        v.add("inputs_positive", False, "radius and mass must be > 0")
        return v
    speed = math.sqrt(g * m_kg / r_m)
    v.add("formula", True, f"v = sqrt(G M / r) = {speed:.2f} m/s "
                           f"at r = {r_m:.3g} m")
    # LEO sanity: ~7.6-7.8 km/s at ~6800 km from center (r = R + 400 km)
    if abs(r_m - (EARTH_RADIUS + 400e3)) < 1e5:
        v.add("leo_sanity", 7000 < speed < 9000,
              f"LEO speed ≈ {speed/1000:.2f} km/s (expected ~7.7)")
    return v


def verify_kepler_third_law(period_s: float, radius_m: float,
                            m_kg: float = EARTH_MASS,
                            g: float = GRAVITATIONAL_CONSTANT) -> Verification:
    """Verify Kepler's third law for circular orbits: T² = (4π²/GM) r³."""
    v = Verification(ok=True)
    if period_s <= 0 or radius_m <= 0:
        v.add("inputs_positive", False, "period and radius must be > 0")
        return v
    expected = 2 * math.pi * math.sqrt(radius_m ** 3 / (g * m_kg))
    rel = abs(expected - period_s) / expected
    v.add("period_matches", rel < 0.01,
          f"T = {period_s:.1f} s vs Kepler T = {expected:.1f} s (rel err {rel:.4f})")
    return v


def collatz_step(n: int) -> int:
    """One Collatz step (deterministic)."""
    return n // 2 if n % 2 == 0 else 3 * n + 1


def verify_collatz_sequence(start: int, max_steps: int = 200) -> Verification:
    """Verify a Collatz trajectory reaches 1 (with step count + peak)."""
    v = Verification(ok=True)
    if start <= 0:
        v.add("positive_start", False, f"start must be a positive integer")
        return v
    n = start
    steps = 0
    peak = n
    seq = [n]
    for _ in range(max_steps):
        if n == 1:
            break
        n = collatz_step(n)
        seq.append(n)
        peak = max(peak, n)
        steps += 1
    v.add("reaches_one", n == 1,
          f"{start} -> 1 in {steps} steps (peak {peak})")
    v.add("step_count", True, str(steps))
    v.add("peak", True, str(peak))
    v.add("sequence", True, " -> ".join(str(x) for x in seq[:12]) +
          ("..." if len(seq) > 12 else ""))
    return v


def verify_collatz_example(start: int, expected_steps: int,
                           expected_peak: int) -> Verification:
    """Deterministic guard for a specific Collatz claim (e.g. n=27)."""
    v = verify_collatz_sequence(start)
    steps = next((c["detail"] for c in v.checks if c["name"] == "step_count"), "")
    peak = next((c["detail"] for c in v.checks if c["name"] == "peak"), "")
    v.add("steps_match", str(steps) == str(expected_steps),
          f"steps {steps} vs expected {expected_steps}")
    v.add("peak_match", str(peak) == str(expected_peak),
          f"peak {peak} vs expected {expected_peak}")
    return v


def verify_free_fall_time(height_units: float, g_units: float,
                          expected_time: float) -> Verification:
    """Verify t = sqrt(2h/g) for a drop (scene units)."""
    v = Verification(ok=True)
    if height_units <= 0 or g_units <= 0:
        v.add("inputs_positive", False, "height and g must be > 0")
        return v
    t = math.sqrt(2 * height_units / g_units)
    rel = abs(t - expected_time) / t
    v.add("time_matches", rel < 0.02,
          f"t = sqrt(2h/g) = {t:.3f} vs {expected_time:.3f} (rel err {rel:.4f})")
    return v


if __name__ == "__main__":
    r = verify_rayleigh_ratio()
    print("rayleigh:", r.ok, [c["detail"] for c in r.checks])
    r = verify_orbital_speed(6.771e6)
    print("orbital:", r.ok, [c["detail"] for c in r.checks])
    r = verify_collatz_example(27, 111, 9232)
    print("collatz27:", r.ok, [c["detail"] for c in r.checks])
