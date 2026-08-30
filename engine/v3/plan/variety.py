"""variety.py — Visual-variety policy enforcement (directive §2B/§16).

Director-level deterministic pass over a planned shotlist:

  V1  no more than 2 consecutive shots on the same renderer;
  V2  no identical composition on consecutive shots, and no composition
      held longer than ~3s (composition string + cumulative duration);
  V3  alternate shot scale / camera behaviour between consecutive shots;
  V4  pattern interrupts: at least one visible change (renderer, music
      state, text overlay, or composition class) per ~5 shots — the
      director-level enforcement of the §16 pattern_interrupts bucket.

Narrative coherence overrides arbitrary cutting (§2B): hero shots and the
first (hook) shot are only touched when strictly necessary, and every
change is logged in the returned report.

Pure functions over shot dicts — no LLM, no network, fully deterministic.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_SAME_RENDERER = 2
PATTERN_INTERRUPT_TARGET_DIVISOR = 5.0
COMPOSITION_HOLD_LIMIT_SEC = 3.0

# Deterministic alternation vocabulary for camera/scale rewriting.
CAMERA_ALTERNATIVES = [
    "slow push in", "wide static hold", "gentle drift left",
    "close-up with shallow focus", "pull out reveal",
]
SCALE_ALTERNATIVES = ["wide", "medium", "close", "medium", "wide"]

# Renderer used for inserted pattern interrupts: cheap, offline-capable,
# text-friendly (kinetic typography) — never consumes AI quota.
INTERRUPT_RENDERER = "MOTION_CANVAS"


def _set_renderer(shot: dict, rid: str, reason: str,
                  changes: list[dict]) -> None:
    old = shot.get("renderer")
    if old == rid:
        return
    shot["renderer"] = rid
    if rid != shot.get("fallback_renderer"):
        shot["fallback_renderer"] = old or rid
    changes.append({"shot_id": shot.get("shot_id"), "field": "renderer",
                    "from": old, "to": rid, "reason": reason})


def _same(a: Any, b: Any) -> bool:
    return str(a or "").strip().lower() == str(b or "").strip().lower()


def analyze_variety(shots: list[dict]) -> dict:
    """Report on the shotlist's variety health (deterministic)."""
    histogram: dict[str, int] = {}
    max_run = 0
    run = 0
    prev: str | None = None
    comp_repeats = 0
    prev_comp: str | None = None
    interrupts = 0
    prev_change_key: tuple | None = None
    for s in shots:
        rid = s.get("renderer", "?")
        histogram[rid] = histogram.get(rid, 0) + 1
        run = run + 1 if rid == prev else 1
        max_run = max(max_run, run)
        prev = rid
        comp = str(s.get("composition") or s.get("camera") or "")
        if prev_comp is not None and _same(comp, prev_comp):
            comp_repeats += 1
        prev_comp = comp
        change_key = (rid, s.get("music_state"),
                      bool(s.get("text_overlay")),
                      _composition_class(s))
        if prev_change_key is not None and change_key != prev_change_key:
            interrupts += 1
        prev_change_key = change_key
    n = len(shots)
    target = max(1, round(n / PATTERN_INTERRUPT_TARGET_DIVISOR))
    return {
        "shots": n,
        "renderer_histogram": histogram,
        "distinct_renderers": len(histogram),
        "max_consecutive_same_renderer": max_run,
        "composition_repeats": comp_repeats,
        "pattern_interrupt_count": interrupts,
        "pattern_interrupt_target": target,
        "issues": _issues(histogram, max_run, comp_repeats, interrupts,
                          target),
    }


def _issues(histogram: dict, max_run: int, comp_repeats: int,
            interrupts: int, target: int) -> list[str]:
    issues: list[str] = []
    if max_run > MAX_CONSECUTIVE_SAME_RENDERER:
        issues.append(
            f"renderer run of {max_run} > {MAX_CONSECUTIVE_SAME_RENDERER}")
    if comp_repeats:
        issues.append(f"{comp_repeats} identical consecutive compositions")
    if n_hist := len(histogram):
        if n_hist >= 6 and len(histogram) < 3:
            issues.append("renderer histogram too narrow for a long video")
    if interrupts < target:
        issues.append(
            f"pattern interrupts {interrupts} < target {target}")
    return issues


def _composition_class(shot: dict) -> str:
    """Coarse composition class used for interrupt detection."""
    comp = str(shot.get("composition") or "").lower()
    for marker in ("wide", "close", "overhead", "profile", "macro",
                   "aerial", "diagram", "typography"):
        if marker in comp:
            return marker
    return "default"


def enforce_variety(shots: list[dict], *,
                    availability: dict[str, bool] | None = None,
                    protect_hero: bool = True) -> tuple[list[dict], list[dict], dict]:
    """Enforce the §2B variety policy in place. Returns (shots, changes,
    report). Deterministic; narrative coherence wins over the policy."""
    availability = availability or {}
    changes: list[dict] = []

    _v1_consecutive_renderer(shots, changes, availability, protect_hero)
    _v2_composition(shots, changes)
    _v3_scale_camera(shots, changes)
    _v4_pattern_interrupts(shots, changes, availability, protect_hero)

    report = analyze_variety(shots)
    report["changes"] = changes
    return shots, changes, report


def _protected(shot: dict, protect_hero: bool, index: int) -> bool:
    return protect_hero and (
        shot.get("generation_priority") == "hero" or index == 0)


def _available(rid: str, availability: dict[str, bool]) -> bool:
    return availability.get(rid, True)


def _v1_consecutive_renderer(shots: list[dict], changes: list[dict],
                             availability: dict[str, bool],
                             protect_hero: bool) -> None:
    """Break runs of >2 identical renderers by re-assigning the middle
    shot to its fallback chain (or the interrupt renderer)."""
    run_start = 0
    i = 1
    while i <= len(shots):
        if i == len(shots) or shots[i].get("renderer") \
                != shots[run_start].get("renderer"):
            run_len = i - run_start
            if run_len > MAX_CONSECUTIVE_SAME_RENDERER:
                # Re-assign every 3rd shot inside the run (indices
                # run_start+2, run_start+4, ...), skipping protected shots.
                for j in range(run_start + MAX_CONSECUTIVE_SAME_RENDERER,
                               i, MAX_CONSECUTIVE_SAME_RENDERER):
                    if _protected(shots[j], protect_hero, j):
                        continue
                    prev_rid = shots[j - 1].get("renderer")
                    next_rid = shots[j + 1].get("renderer") if j + 1 < i else None
                    alt = _pick_alternate(shots[j], prev_rid, next_rid,
                                          availability)
                    if alt:
                        _set_renderer(shots[j], alt,
                                      "variety V1: break same-renderer run",
                                      changes)
            run_start = i
        i += 1


def _pick_alternate(shot: dict, prev_rid: str | None, next_rid: str | None,
                    availability: dict[str, bool]) -> str | None:
    """Deterministically choose a replacement renderer that differs from
    both neighbours, preferring the shot's own fallback chain (§24 keeps
    coherence) then the interrupt renderer."""
    chain: list[str] = []
    if shot.get("fallback_renderer"):
        chain.append(shot["fallback_renderer"])
    chain.extend(["STOCK_VIDEO", "PIXIJS", INTERRUPT_RENDERER])
    seen: set[str] = set()
    for rid in chain:
        if rid in seen:
            continue
        seen.add(rid)
        if rid == prev_rid or rid == next_rid:
            continue
        if _available(rid, availability):
            return rid
    return None


def _v2_composition(shots: list[dict], changes: list[dict]) -> None:
    """No identical composition on consecutive shots; no composition held
    longer than ~3s. Rewrites camera/composition text deterministically."""
    hold = 0.0
    prev_comp: str | None = None
    for idx, s in enumerate(shots):
        comp = str(s.get("composition") or "")
        dur = float(s.get("duration_sec") or 0)
        if prev_comp is not None and _same(comp, prev_comp):
            hold += dur
            alt = CAMERA_ALTERNATIVES[idx % len(CAMERA_ALTERNATIVES)]
            new_comp = f"{comp} — {alt}" if comp else alt
            if not comp:
                new_comp = alt
                s["composition"] = alt
                changes.append({
                    "shot_id": s.get("shot_id"), "field": "composition",
                    "from": "", "to": alt,
                    "reason": "variety V2: empty composition filled"})
            else:
                s["composition"] = new_comp
                changes.append({
                    "shot_id": s.get("shot_id"), "field": "composition",
                    "from": comp, "to": new_comp,
                    "reason": "variety V2: identical consecutive composition"
                              " (hold >3s)" if hold > COMPOSITION_HOLD_LIMIT_SEC
                              else "variety V2: identical consecutive "
                                   "composition"})
            comp = s["composition"]
        else:
            hold = dur
        prev_comp = comp


def _v3_scale_camera(shots: list[dict], changes: list[dict]) -> None:
    """Alternate shot scale/camera: consecutive shots must not share the
    exact same camera string."""
    prev_cam: str | None = None
    for idx, s in enumerate(shots):
        cam = str(s.get("camera") or "")
        if prev_cam is not None and cam and _same(cam, prev_cam):
            alt = SCALE_ALTERNATIVES[idx % len(SCALE_ALTERNATIVES)]
            new_cam = f"{cam}, {alt} scale"
            s["camera"] = new_cam
            changes.append({
                "shot_id": s.get("shot_id"), "field": "camera",
                "from": cam, "to": new_cam,
                "reason": "variety V3: alternate shot scale/camera"})
        prev_cam = str(s.get("camera") or "")


def _v4_pattern_interrupts(shots: list[dict], changes: list[dict],
                           availability: dict[str, bool],
                           protect_hero: bool) -> None:
    """Ensure ≥1 pattern interrupt per ~5 shots. When the natural interrupt
    count is under target, insert deterministic interrupts: a kinetic
    typography cutaway (MOTION_CANVAS) carrying the shot's narration as
    text_overlay, at the middle of the longest same-renderer stretch."""
    target = max(1, round(len(shots) / PATTERN_INTERRUPT_TARGET_DIVISOR))
    for _ in range(len(shots)):  # bounded attempts
        report = analyze_variety(shots)
        if report["pattern_interrupt_count"] >= target:
            return
        if not _insert_interrupt(shots, availability, protect_hero, changes):
            return  # nothing insertable — report the shortfall honestly
    return


def _insert_interrupt(shots: list[dict], availability: dict[str, bool],
                      protect_hero: bool, changes: list[dict]) -> bool:
    """Convert one candidate shot into a pattern interrupt. Prefers the
    middle of the longest same-renderer run; skips protected shots."""
    # Find the longest run of identical renderers.
    best = (-1, 0, 0)  # (length, start, mid)
    run_start = 0
    for i in range(1, len(shots) + 1):
        if i == len(shots) or shots[i].get("renderer") \
                != shots[run_start].get("renderer"):
            length = i - run_start
            if length > best[0]:
                best = (length, run_start,
                        run_start + length // 2)
            run_start = i
    length, _start, mid = best
    if length < 1:
        return False
    # Walk outward from the run middle for an insertable shot.
    order = [mid] + [m + k for k in range(1, length)
                     for m in (mid,) if True]
    candidates: list[int] = []
    seen: set[int] = set()
    for c in [mid, *range(len(shots))]:
        if 0 <= c < len(shots) and c not in seen:
            seen.add(c)
            candidates.append(c)
    for c in candidates:
        s = shots[c]
        if _protected(s, protect_hero, c):
            continue
        if s.get("renderer") == INTERRUPT_RENDERER:
            continue  # already an interrupt-shaped shot
        if not _available(INTERRUPT_RENDERER, availability):
            return False
        old_rid = s.get("renderer")
        narration = str(s.get("narration") or s.get("visual_goal") or
                        s.get("subject") or "")
        overlay = (narration[:90] + "…") if len(narration) > 90 else narration
        s["renderer"] = INTERRUPT_RENDERER
        if s.get("fallback_renderer") != old_rid:
            s["fallback_renderer"] = old_rid or s.get("fallback_renderer")
        s["text_overlay"] = overlay or s.get("text_overlay")
        s.setdefault("metadata", {})
        s["metadata"]["pattern_interrupt"] = True
        changes.append({
            "shot_id": s.get("shot_id"), "field": "renderer",
            "from": old_rid, "to": INTERRUPT_RENDERER,
            "reason": "variety V4: pattern interrupt (kinetic typography "
                      "cutaway)"})
        return True
    return False
