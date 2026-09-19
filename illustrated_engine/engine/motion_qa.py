"""V6 motion smoothness QA — frame-to-frame displacement, jitter, reversals.

Brief P0:
  measure:  displacement, velocity, acceleration, high-frequency oscillation,
            direction reversals
  detect:   direction reversals (→→←→→←)
  emit:     motion_jitter_score, motion_direction_reversal_score

Kept intentionally small (the brief: "Do NOT let this become another huge QA
subsystem. It should simply identify visible camera instability.").

Public entry: motion_smoothness(edit_plan) -> dict
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable

from engine.motion_v6 import sample_trajectory


def _velocities(samples: list) -> list:
    """Per-step velocity (deltas per progress unit). samples is a list of
    (w, cx, cy) tuples. Returns a list of velocity vectors
    (dw/dt, dcx/dt, dcy/dt) computed as first differences."""
    if len(samples) < 2:
        return []
    out = []
    for i in range(1, len(samples)):
        a = samples[i - 1]
        b = samples[i]
        out.append((b[0] - a[0], b[1] - a[1], b[2] - a[2]))
    return out


def _speed(v: tuple) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _dot(a: tuple, b: tuple) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _reversal_count(velocities: list) -> int:
    """Count direction reversals: v[i] . v[i+1] < 0 means the trajectory
    changed direction. A smooth pan has at most 1 reversal (start -> end).
    Anything more is visible micro-jitter."""
    if len(velocities) < 2:
        return 0
    n = 0
    for i in range(len(velocities) - 1):
        a, b = velocities[i], velocities[i + 1]
        sa, sb = _speed(a), _speed(b)
        if sa < 1e-6 or sb < 1e-6:
            continue
        # direction-reversal: dot product negative
        if _dot(a, b) < 0:
            n += 1
    return n


def _acceleration_energy(velocities: list) -> float:
    """Sum of squared acceleration magnitudes. High energy = jitter."""
    if len(velocities) < 2:
        return 0.0
    acc = 0.0
    for i in range(1, len(velocities)):
        dvx = velocities[i][0] - velocities[i - 1][0]
        dvy = velocities[i][1] - velocities[i - 1][1]
        dvz = velocities[i][2] - velocities[i - 1][2]
        acc += dvx * dvx + dvy * dvy + dvz * dvz
    return acc / max(1, len(velocities))


def _high_freq_energy(velocities: list) -> float:
    """Energy in the *second derivative* of velocity, normalized to velocity
    magnitude. High values mean the velocity direction is wobbling at high
    frequency (visible tremble)."""
    if len(velocities) < 3:
        return 0.0
    mean_speed = sum(_speed(v) for v in velocities) / len(velocities)
    if mean_speed < 1e-6:
        return 0.0
    return _acceleration_energy(velocities) / (mean_speed * mean_speed)


def _score_shot(camera: dict, duration_s: float) -> dict:
    """Score a single shot's camera motion. Static-by-design HOLD returns
    zero motion + a structural note."""
    prim = (camera or {}).get("primitive", "HOLD")
    if prim == "HOLD" or float(duration_s) <= 0.05:
        return {
            "primitive": prim,
            "static": True,
            "samples": 0,
            "reversals": 0,
            "high_freq_energy": 0.0,
            "motion_jitter_score": 0.0,
            "motion_direction_reversal_score": 0.0,
            "mean_speed": 0.0,
            "max_speed": 0.0,
        }
    ws, cxs, cys = sample_trajectory(camera, duration_s)
    samples = list(zip(ws, cxs, cys))
    vels = _velocities(samples)
    revs = _reversal_count(vels)
    hfe = _high_freq_energy(vels)
    speeds = [_speed(v) for v in vels]
    mean_speed = sum(speeds) / max(1, len(speeds))
    max_speed = max(speeds) if speeds else 0.0
    # Score scales: jitter is 0..1 where 1 = terrible, reversal score
    # is reversals-per-second-of-shot. Brief: should be near zero for a
    # clean pan. We map both to a 0..100 PASS-band score.
    # jitter_pass: hfe < 0.05 -> 100; 0.5 -> 0 (linear cap)
    if hfe <= 0.05:
        jitter_score = 100.0
    elif hfe >= 0.5:
        jitter_score = 0.0
    else:
        jitter_score = 100.0 * (0.5 - hfe) / 0.45
    # reversal_pass: 0 reverses = 100; each reversal costs 25
    reversal_score = max(0.0, 100.0 - 25.0 * revs)
    return {
        "primitive": prim,
        "static": False,
        "samples": len(samples),
        "reversals": revs,
        "high_freq_energy": round(hfe, 6),
        "motion_jitter_score": round(jitter_score, 1),
        "motion_direction_reversal_score": round(reversal_score, 1),
        "mean_speed": round(mean_speed, 6),
        "max_speed": round(max_speed, 6),
    }


def motion_smoothness(edit_plan: dict) -> dict:
    """Run per-shot motion QA on an edit_plan (the rendered shot list).

    Returns a dict:
        {
          "shots": [per-shot rows],
          "mean_jitter": float (0..100, higher = better),
          "mean_reversal": float (0..100),
          "ok": bool (any shot below 60 jitter OR with >=3 reversals -> False)
        }
    Brief CAN_PUBLISH rule: any obvious motion tremble -> False.
    """
    rows = []
    for s in (edit_plan.get("shots") or []):
        cam = s.get("camera") or {}
        dur = float(s.get("duration_s", 0))
        row = _score_shot(cam, dur)
        row["shot_id"] = s.get("shot_id")
        rows.append(row)
    n = max(1, len(rows))
    moving = [r for r in rows if not r.get("static")]
    mean_jitter = sum(r["motion_jitter_score"] for r in moving) / max(1, len(moving)) \
        if moving else 100.0
    mean_reversal = sum(r["motion_direction_reversal_score"] for r in moving) / max(1, len(moving)) \
        if moving else 100.0
    # CAN_PUBLISH gate: any moving shot with jitter < 60 or >=3 reversals fails
    bad = [r for r in moving
           if r["motion_jitter_score"] < 60.0 or r["reversals"] >= 3]
    return {
        "shots": rows,
        "mean_jitter": round(mean_jitter, 1),
        "mean_reversal": round(mean_reversal, 1),
        "bad_shots": [r["shot_id"] for r in bad],
        "ok": len(bad) == 0,
    }
