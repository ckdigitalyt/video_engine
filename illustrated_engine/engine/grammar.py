"""Shot grammar (P1) + novelty controller (P1-8).

Every shot declares a semantic type; camera behaviour follows the type, never
randomness. The novelty controller guarantees meaningful visual evolution at
least every ~3–5 s (camera re-target, highlight, callout, number pop, text
emphasis) and reuses assets — it never asks for new images.
"""

from __future__ import annotations

# Camera defaults per shot type: (from_scale, to_scale, pan_bias)
#   pan_bias: None=center, or ("x", from, to) normalized windows for lateral drift
SHOT_TYPES = {
    "ESTABLISH": {"cam": (1.00, 1.10, None), "desc": "wide push-in, settle"},
    "REVEAL":    {"cam": (1.04, 1.22, None), "desc": "push toward subject"},
    "EXPLAIN":   {"cam": (1.10, 1.10, ("x", 0.30, 0.62)), "desc": "lateral drift across annotations"},
    "COMPARE":   {"cam": (1.00, 1.06, None), "desc": "hold the comparison, gentle push"},
    "DETAIL":    {"cam": (1.30, 1.48, None), "desc": "tight zoom on the detail"},
    "DIAGRAM":   {"cam": (1.00, 1.05, None), "desc": "near-static, events build the story"},
    "TIMELINE":  {"cam": (1.06, 1.06, ("x", 0.25, 0.72)), "desc": "travel the timeline"},
    "TRANSITION":{"cam": (1.00, 1.00, None), "desc": "brief breath, fade"},
    "PAYOFF":    {"cam": (1.16, 1.00, None), "desc": "pull back, land the scale"},
}

KNOWN_TYPES = set(SHOT_TYPES)


def camera_for(shot: dict) -> dict:
    """Resolve camera params from shot type (+ explicit overrides win)."""
    st = str(shot.get("shot_type", "EXPLAIN")).upper()
    if st not in SHOT_TYPES:
        st = "EXPLAIN"
    fs, ts, pan = SHOT_TYPES[st]["cam"]
    cam = {
        "primitive": "zoompan",
        "from_scale": float(shot.get("cam_from_scale", fs)),
        "to_scale": float(shot.get("cam_to_scale", ts)),
        "pan": pan,
        "cx": shot.get("cam_cx"),   # optional focus point (normalized)
        "cy": shot.get("cam_cy"),
        "from_cx": shot.get("cam_from_cx"),
        "from_cy": shot.get("cam_from_cy"),
    }
    return cam


# ------------------------------------------------------------ novelty -------

AUTO_KINDS = ("highlight", "callout", "number_pop", "camera_retgt", "text_emphasis")


def build_events(shot: dict, duration: float) -> list:
    """Collect a shot's explicit visual events from its overlays/typography."""
    events = []
    for ov in shot.get("overlays", []) or []:
        k = str(ov.get("kind", "")).upper()
        if k in ("HIGHLIGHT", "CALLOUT", "ARROW_DRAW", "NUMBER_POP"):
            events.append({"t": float(ov.get("at", 0.4)) * duration,
                           "kind": k.lower(), "spec": ov})
    for tp in shot.get("typography", []) or []:
        k = str(tp.get("kind", "")).upper()
        if k == "NUMBER_POP":
            events.append({"t": float(tp.get("at", 0.5)) * duration,
                           "kind": "number_pop", "spec": tp})
        elif k == "TEXT_REVEAL":
            events.append({"t": float(tp.get("at", 0.5)) * duration,
                           "kind": "text_emphasis", "spec": tp})
    events.sort(key=lambda e: e["t"])
    return events


def validate_novelty(events: list, duration: float, max_gap: float = 5.0) -> dict:
    """Find gaps between meaningful changes (shot start counts as one)."""
    times = [0.0] + sorted(e["t"] for e in events if 0 < e["t"] < duration)
    gaps = []
    for a, b in zip(times, times[1:] + ([duration] if times else [])):
        if b - a > max_gap + 1e-3:
            gaps.append({"from": round(a, 2), "to": round(b, 2),
                         "gap": round(b - a, 2)})
    return {"gaps": gaps, "ok": not gaps}


def fill_novelty(shot: dict, events: list, duration: float,
                 max_gap: float = 5.0) -> list:
    """Insert deterministic auto-events until every gap <= max_gap.

    Reuses the shot's own regions/plate — never requests new assets. Choice
    rotates by shot index so different shots evolve differently.
    """
    st = str(shot.get("shot_type", "EXPLAIN")).upper()
    idx = int(str(shot.get("shot_id", "S0"))[1:] or 0)
    stypes = ["camera_retgt", "highlight", "text_emphasis"]
    added = []
    if st in ("DIAGRAM", "TIMELINE", "COMPARE"):
        stypes = ["highlight", "camera_retgt", "text_emphasis"]
    for gap in validate_novelty(events, duration, max_gap)["gaps"]:
        t = round(gap["from"] + gap["gap"] * 0.55, 2)
        kind = stypes[(idx + len(added)) % len(stypes)]
        if kind == "highlight":
            spec = {"kind": "HIGHLIGHT", "target": shot.get("focus_region", "center"),
                    "style": "circle", "at": t / duration}
        elif kind == "camera_retgt":
            spec = {"kind": "CAMERA_RETGT", "cx": shot.get("cam_cx", 0.5),
                    "cy": shot.get("cam_cy", 0.42), "at": t / duration}
        else:
            spec = {"kind": "TEXT_EMPHASIS", "at": t / duration}
        events.append({"t": t, "kind": kind.lower(), "spec": spec, "auto": True})
        added.append({"t": t, "kind": kind})
    events.sort(key=lambda e: e["t"])
    return added


def novelty_report(shots: list) -> dict:
    """Whole-video novelty coverage summary (for QA)."""
    out = {"shots": 0, "auto_filled": 0, "gaps_remaining": 0, "per_shot": []}
    for s in shots:
        dur = float(s.get("duration_s", 4.0))
        evs = s.get("events") or build_events(s, dur)
        filled = fill_novelty(s, evs, dur)
        v = validate_novelty(evs, dur)
        s["events"] = evs
        out["shots"] += 1
        out["auto_filled"] += len(filled)
        out["gaps_remaining"] += len(v["gaps"])
        out["per_shot"].append({"shot_id": s.get("shot_id"),
                                "events": len(evs), "auto": len(filled),
                                "ok": v["ok"]})
    out["ok"] = out["gaps_remaining"] == 0
    return out
