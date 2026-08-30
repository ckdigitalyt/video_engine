"""reedit.py — Re-edit rather than merely regenerate (directive §21).

Preferred order: trim → shorten → rearrange → replace → regenerate.

The §20 creative critic returns ``recommended_cuts``; this module turns
them into ACTUAL re-edit operations on the shotlist — before any
regeneration is considered:

  trim       cut the dead tail (static hold) off a shot; the default
             repair for frozen/overlong shots (25 % of duration, min 1.5 s)
  shorten    halve the shot toward a 2.0 s floor (pacing repair)
  rearrange  move a shot before/after another (order repair)
  replace    swap renderer/subject (visual repair without regeneration)
  regenerate mark for regeneration — ONLY when no cheaper operation
             addresses the problem (the critic asked for it and the shot
             is already short and central)

Regeneration requests are automatically demoted to trim/replace when the
shot exhibits the static/slideshow pathology (it is long or carries a long
static hold) — implementing the §21 preference order mechanically.

Pure functions over shot dicts; deterministic; narration timings are
re-chained after every op so downstream TTS/assembly stays consistent.
"""

from __future__ import annotations

from typing import Any

# §21 preference order — ops are applied in this order regardless of the
# order the critic listed them in.
REEDIT_ORDER = ("trim", "shorten", "rearrange", "replace", "regenerate")

REEDIT_ACTIONS = set(REEDIT_ORDER)

_MIN_DURATION = 1.5
_SHORTEN_FLOOR = 2.0


def _retime(shots: list[dict]) -> None:
    """Re-chain narration_start/end after ops (planned timing contract)."""
    t = 0.0
    for s in shots:
        dur = float(s.get("duration_sec") or 0)
        s["narration_start"] = round(t, 2)
        s["narration_end"] = round(t + dur, 2)
        t += dur


def _normalize_action(action: str, detail: str, shot: dict | None) -> str:
    """Map the critic's wording onto a §21 action; demote regenerate."""
    a = str(action or "").lower()
    if a not in REEDIT_ACTIONS:
        # infer from the detail text before defaulting
        low = str(detail or "").lower()
        if "regener" in a or "regener" in low:
            a = "regenerate"
        elif "reorder" in low or "move" in low or "swap" in low:
            a = "rearrange"
        elif "renderer" in low or "replace" in low or "re-shoot" in low:
            a = "replace"
        elif "halve" in low or "tighten" in low or "shorten" in low:
            a = "shorten"
        else:
            a = "trim"
    # §21 mechanical demotion: regenerate is last resort. When the shot is
    # long or frozen, a trim addresses the same problem cheaply.
    if a == "regenerate" and shot is not None:
        dur = float(shot.get("duration_sec") or 0)
        longest_hold = float((shot.get("metadata", {}).get("audit") or {})
                             .get("longest_hold_sec", 0) or 0)
        if dur > 2 * _MIN_DURATION + 0.5 or longest_hold > 2.5:
            return "trim"
        return "replace"
    return a


def plan_reedit(critic: dict, shots: list[dict]) -> list[dict]:
    """Convert critic recommended_cuts into ordered re-edit ops.

    Ops carry {"shot_id", "action", "detail", plus action-specific params}.
    Actions are stabilized to the §21 order; unknown shots are dropped;
    regenerate is demoted per the mechanical rule in _normalize_action."""
    by_id = {str(s.get("shot_id")): s for s in shots}
    ops: list[dict] = []
    for cut in critic.get("recommended_cuts", []) or []:
        sid = str(cut.get("shot_id", ""))
        if sid == "master":
            # master-level cut: apply the trim to the longest-shot offender
            if not shots:
                continue
            sid = max(shots, key=lambda s: float(s.get("duration_sec") or 0))[
                "shot_id"]
        shot = by_id.get(sid)
        if shot is None:
            continue
        action = _normalize_action(cut.get("action"), cut.get("detail", ""),
                                   shot)
        op: dict[str, Any] = {"shot_id": sid, "action": action,
                              "detail": str(cut.get("detail", ""))[:200]}
        if action == "rearrange":
            op["before_shot_id"] = str(cut.get("before_shot_id") or "")
        elif action == "replace":
            op["renderer"] = str(cut.get("renderer") or "") or None
        elif action == "trim":
            op["amount_sec"] = None  # resolved at apply time from duration
        ops.append(op)
    # §21: stabilize to the preferred order, keeping first-mention priority
    # within the same action.
    ops.sort(key=lambda o: REEDIT_ORDER.index(o["action"]))
    return ops


def apply_reedit(shots: list[dict], ops: list[dict]) -> tuple[list[dict], list[dict], list[dict]]:
    """Apply re-edit ops to the shotlist.

    Returns (new_shots, applied_ops, skipped_ops). Deterministic; the input
    list is not mutated."""
    working = [dict(s) for s in shots]
    by_id = {str(s.get("shot_id")): s for s in working}
    applied: list[dict] = []
    skipped: list[dict] = []

    for op in ops:
        sid = str(op.get("shot_id"))
        shot = by_id.get(sid)
        if shot is None or shot not in working:
            skipped.append({**op, "reason": "shot already removed"})
            continue
        action = op.get("action")
        dur = float(shot.get("duration_sec") or 0)
        if action == "trim":
            amount = op.get("amount_sec")
            if amount is None:
                amount = round(max(0.5, dur * 0.25), 2)
            new_dur = round(max(_MIN_DURATION, dur - float(amount)), 2)
            if new_dur >= dur:
                skipped.append({**op, "reason": f"nothing to trim "
                                                f"({dur:.1f}s at floor)"})
                continue
            shot["duration_sec"] = new_dur
            shot.setdefault("metadata", {})["reedited"] = "trim"
            applied.append({**op, "from_sec": dur, "to_sec": new_dur})
        elif action == "shorten":
            new_dur = round(max(_SHORTEN_FLOOR, dur * 0.5), 2)
            if new_dur >= dur:
                skipped.append({**op, "reason": f"already short ({dur:.1f}s)"})
                continue
            shot["duration_sec"] = new_dur
            shot.setdefault("metadata", {})["reedited"] = "shorten"
            applied.append({**op, "from_sec": dur, "to_sec": new_dur})
        elif action == "rearrange":
            target = str(op.get("before_shot_id") or "")
            target_idx = next(
                (i for i, s in enumerate(working)
                 if str(s.get("shot_id")) == target), None)
            if target_idx is None:
                skipped.append({**op, "reason": f"target {target!r} not found"})
                continue
            working.remove(shot)
            tgt = next(i for i, s in enumerate(working)
                       if str(s.get("shot_id")) == target)
            working.insert(tgt, shot)
            shot.setdefault("metadata", {})["reedited"] = "rearrange"
            applied.append({**op, "moved_before": target})
        elif action == "replace":
            new_renderer = op.get("renderer") or shot.get("fallback_renderer")
            if new_renderer:
                shot["fallback_renderer"] = shot.get("renderer")
                shot["renderer"] = new_renderer
            shot["subject"] = str(op.get("subject")
                                  or shot.get("subject"))[:300]
            shot.setdefault("metadata", {})["reedited"] = "replace"
            applied.append({**op, "to_renderer": shot["renderer"]})
        elif action == "regenerate":
            shot.setdefault("metadata", {})["regenerate"] = True
            shot.setdefault("metadata", {})["reedited"] = "regenerate"
            applied.append({**op})

    _retime(working)
    return working, applied, skipped
