"""V11 P1 §7 — viewer value density (Jade_todo_v11).

Core editorial metric. For every ~5-second interval the question is:
"What does the viewer now know/understand/feel that they did not
before?"

Value per interval (deterministic, from the edit plan):
  +2 counted semantic visual event (reveal/flow/fill_state/consequence)
  +1 question opened, +1 question resolved (curiosity ladder)
  +novelty share of the narration (new content tokens vs everything
   the viewer has already read/heard)

Penalties (the directive's list):
  - decorative motion: interval sits in a C-class (decorative) shot
  - repeated information: narration novelty below 1/3 new tokens
  - repeated diagrams: an asset re-shown after its first appearance
  - generic hero plates: no v8 states, no counted events, not the
    opening/payoff — a pretty plate that explains nothing
  - filler narration: filler markers in the interval's narration
  - redundant labels: the same number/label popped twice
  - generic transitions: A/B/C motion tag with no living event and no
    visual_mode change (transition carries no information)

Verdict per interval: strong >= 1.0, ok >= 0.5, weak < 0.5.
Gate: mean value >= 0.6 AND weak share <= 25%.
"""
from __future__ import annotations

import re

from engine.editorial8 import COUNTED, _shot_starts

WINDOW = 5.0
NOVELTY_MIN = 1 / 3
WEAK_SHARE_MAX = 0.25
MEAN_MIN = 0.6

_STOP = set("a an the of in on at to for and or is are was were it its as "
            "with that this these those by from but not you your can will "
            "be been has have had do does did so no yes what why how when "
            "where which who whom than then there here one two".split())

_FILLER_RE = re.compile(
    r"\b(as you can see|needless to say|basically|of course|obviously|"
    r"as it turns out|at the end of the day|simply put|in fact)\b", re.I)


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if t not in _STOP and len(t) > 2}


def _prev_shot(shots: list, starts: list, t0: float) -> dict | None:
    """The shot immediately before t0 (None at the plan opening)."""
    prev = None
    for s, st in zip(shots, starts):
        if abs(st - t0) < 1e-6:
            return prev
        prev = s
    return None


def value_density(plan: dict, story: dict | None = None) -> dict:
    shots = plan.get("shots") or []
    starts, total = _shot_starts(plan)
    n = max(int(total // WINDOW), 1)
    seen_tokens: set = set()
    seen_assets: set = set()
    seen_pops: set = set()
    # per-window items: a shot spanning several ~5s windows contributes to
    # EVERY window it occupies (its text novelty counts once, where it starts)
    rows: list = [[] for _ in range(n)]
    for s, t0 in zip(shots, starts):
        dur = float(s.get("duration_s") or 0)
        w0 = min(int(t0 // WINDOW), n - 1)
        w1 = min(int(max(t0 + dur - 0.01, t0) // WINDOW), n - 1)
        asset = str(s.get("asset") or "")
        repeated_asset = asset in seen_assets
        seen_assets.add(asset)
        # counted semantic events, placed in the window where they occur
        ev_windows = []
        for st in (s.get("v8") or {}).get("states") or []:
            if st.get("event") in COUNTED:
                ew = min(int((t0 + float(st.get("t") or 0)) // WINDOW), n - 1)
                ev_windows.append(ew)
        decorative = (str(s.get("motion_class")) == "A"
                      and not ev_windows)  # V12 2 fix: A is the DECORATIVE
        # class (planv5._motion_class: C explanatory / B structural / A
        # decorative) — the V11 code penalized C, punishing exactly the
        # explanatory shots the metric exists to reward.
        generic_plate = (not ev_windows
                         and not (s.get("v8") or {}).get("states")
                         and str(s.get("shot_type", "")).upper() not in
                         ("HOOK", "PAYOFF", "REVEAL"))
        # V12 P1 — generic transition: the cut INTO this shot carries no
        # information (same visual mode, no living event, camera-only tag).
        prev_mode = prev.get("visual_mode") if (prev := _prev_shot(
            shots, starts, t0)) else None
        generic_transition = (
            prev_mode is not None
            and str(prev_mode) == str(s.get("visual_mode"))
            and not ev_windows
            and str(s.get("motion_class")) == "A")
        # narration novelty (story text + captions carry the words)
        narration = str((s.get("v8") or {}).get("intent") or "")
        for b in (story or {}).get("beats", []):
            if str(b.get("beat_id")) == str(s.get("beat_id")):
                narration = str(b.get("narration") or "")
        toks = _tokens(narration)
        for c in s.get("captions") or []:
            toks |= _tokens(c.get("text"))
        novel = toks - seen_tokens
        novelty = (len(novel) / len(toks)) if toks else 0.0
        seen_tokens |= toks
        filler = bool(_FILLER_RE.search(narration))
        # redundant labels: same key number text popped again
        redundant = False
        for ev in s.get("events") or []:
            if ev.get("kind") == "number_pop":
                txt = str((ev.get("spec") or {}).get("text") or "")
                if txt and txt in seen_pops:
                    redundant = True
                seen_pops.add(txt)
        for w in range(w0, w1 + 1):
            rows[w].append({"shot_id": s.get("shot_id"),
                            "events": ev_windows.count(w),
                            "novelty": novelty if w == w0 else 0.0,
                            "decorative": decorative,
                            "generic_plate": generic_plate,
                            "generic_transition": (generic_transition
                                                   if w == w0 else False),
                            "repeated_asset": repeated_asset,
                            "redundant_label": redundant, "filler": filler})
    intervals = []
    for w, items in enumerate(rows):
        value = 0.0
        penalties = []
        gains = []
        for it in items:
            value += 2.0 * it["events"]
            if it["events"]:
                gains.append(f"events:{it['events']}")
            if it["decorative"]:
                value -= 0.75
                penalties.append("decorative_motion")
            if it.get("generic_transition"):
                value -= 0.5
                penalties.append("generic_transition")
            if it["generic_plate"]:
                value -= 0.75
                penalties.append("generic_hero_plate")
            if it["repeated_asset"]:
                value -= 0.5
                penalties.append("repeated_diagram")
            if it["redundant_label"]:
                value -= 0.5
                penalties.append("redundant_label")
            if it["filler"]:
                value -= 0.5
                penalties.append("filler_narration")
            if it["novelty"] > 0:
                value += 1.0 * it["novelty"]
                gains.append(f"novelty:{it['novelty']}")
            if it["novelty"] > 0 and it["novelty"] < NOVELTY_MIN:
                value -= 0.5
                penalties.append("repeated_information")
        opens = sum(len((s.get("v8") or {}).get("opens") or [])
                    for s, t0 in zip(shots, starts)
                    if min(int(t0 // WINDOW), n - 1) == w)
        resolves = sum(len((s.get("v8") or {}).get("resolves") or [])
                       for s, t0 in zip(shots, starts)
                       if min(int(t0 // WINDOW), n - 1) == w)
        value += 1.0 * opens + 1.0 * resolves
        if opens:
            gains.append(f"opens:{opens}")
        if resolves:
            gains.append(f"resolves:{resolves}")
        intervals.append({
            "t": [round(w * WINDOW, 1), round((w + 1) * WINDOW, 1)],
            "value": round(value, 2),
            "verdict": ("strong" if value >= 1.0
                        else "ok" if value >= 0.5 else "weak"),
            "gains": gains, "penalties": sorted(set(penalties)),
            "shots": [it["shot_id"] for it in items]})
    weak = [iv for iv in intervals if iv["verdict"] == "weak"]
    mean = sum(iv["value"] for iv in intervals) / max(len(intervals), 1)
    gate = (mean >= MEAN_MIN
            and len(weak) / max(len(intervals), 1) <= WEAK_SHARE_MAX)
    return {"window_s": WINDOW, "intervals": intervals,
            "mean_value": round(mean, 2),
            "weak_intervals": [iv["t"] for iv in weak],
            "gate": gate,
            "verdict": "pass" if gate else "thin"}
