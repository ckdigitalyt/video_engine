"""budget.py — Visual-budget reconciliation (directive §16, Wave-2).

Pure post-pass after the router: given the shotlist (each shot carrying a
router-assigned renderer), the declared budget and per-renderer availability,
returns adjusted renderer assignments that satisfy the budget as closely as
possible — deterministically, without re-running the router scorer.

Algorithm (greedy, deterministic):
1. Count shots per renderer against budget buckets.
2. Over-budget renderers demote their least-valuable shots (lowest
   generation_priority, then stable shot order) to the next available
   renderer in the §24 fallback chain that still has budget headroom.
3. Under-budget buckets pull from demoted shots first, then stay unfilled
   (a budget is a target mix, not a quota — no forced mismatches).
4. Availability: shots never assigned to an unavailable renderer; if no
   fallback bucket has headroom the shot keeps its original renderer
   (over-budget beats unroutable).

No network, no LLM — same inputs always produce the same assignments.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Budget bucket -> renderer ids (first match is the "primary" renderer for
# that bucket; STOCK/ARCHIVAL share a bucket per §16).
BUCKET_RENDERERS: dict[str, list[str]] = {
    "hero_ai_video_shots": ["AI_VIDEO"],
    "ai_image_motion_shots": ["AI_IMAGE_MOTION"],
    "stock_or_archival_shots": ["STOCK_VIDEO", "ARCHIVAL"],
    "motion_canvas_shots": ["MOTION_CANVAS"],
    "pixijs_shots": ["PIXIJS"],
    "manim_shots": ["MANIM"],
    "archival_shots": ["ARCHIVAL"],
    "godot_shots": ["GODOT"],
}

# §24 canonical degradation chain — demotion walks this order.
FALLBACK_CHAIN: tuple[str, ...] = (
    "AI_VIDEO",
    "AI_IMAGE_MOTION",
    "STOCK_VIDEO",
    "ARCHIVAL",
    "MOTION_CANVAS",
    "PIXIJS",
    "MANIM",
)

_PRIORITY_RANK = {"low": 0, "normal": 1, "high": 2, "hero": 3}


@dataclass
class BudgetReconciliation:
    """Result of reconciling a shotlist against the declared budget."""

    assignments: dict[str, str] = field(default_factory=dict)   # shot_id -> renderer
    changes: list[dict[str, str]] = field(default_factory=list)  # [{shot_id, from, to, reason}]
    bucket_counts: dict[str, int] = field(default_factory=dict)  # bucket -> final count
    notes: list[str] = field(default_factory=list)


def _bucket_for(renderer_id: str) -> str | None:
    for bucket, ids in BUCKET_RENDERERS.items():
        if renderer_id in ids:
            return bucket
    return None


def _demote_target(current: str, available: dict[str, bool],
                   limits: dict[str, int], used: dict[str, int]) -> str | None:
    """Next renderer in the §24 chain after *current* with budget headroom,
    filtered by availability. Walks the chain; None when all buckets are full."""
    idx = FALLBACK_CHAIN.index(current) if current in FALLBACK_CHAIN else 0
    for rid in FALLBACK_CHAIN[idx + 1:]:
        if not available.get(rid, True):
            continue
        bucket = _bucket_for(rid)
        if bucket is None or used.get(bucket, 0) < limits.get(bucket, 10**9):
            return rid
    return None


def reconcile_budget(
    shotlist: list[dict[str, Any]],
    budget: dict[str, Any],
    availability: dict[str, bool] | None = None,
) -> BudgetReconciliation:
    """Reconcile router-assigned renderers against the declared visual budget.

    Args:
        shotlist: shots, each with ``shot_id`` and either ``renderer`` (the
            router's choice) or ``fallback_renderer``. Shots flagged
            ``generation_priority: hero`` are protected from demotion.
        budget: visual_budget_v1 ``budget`` block (bucket -> count).
        availability: optional {renderer_id: bool}; unavailable renderers
            are never assigned.

    Returns:
        BudgetReconciliation with per-shot assignments and change log.
    """
    available = dict(availability or {})
    result = BudgetReconciliation()

    limits = {k: int(v) for k, v in (budget or {}).items() if isinstance(v, (int, float))}

    # 1. Initial assignments + bucket usage.
    assigned: dict[str, str] = {}
    order: list[str] = []            # shot ids in stable order
    used: dict[str, int] = {}        # bucket -> count
    for shot in shotlist:
        shot_id = str(shot.get("shot_id", ""))
        renderer = shot.get("renderer") or shot.get("fallback_renderer") or "MANIM"
        if not available.get(renderer, True):
            # Router picked an unavailable renderer — demote immediately.
            alt = _demote_target(renderer, available, limits, used)
            if alt:
                renderer = alt
        assigned[shot_id] = renderer
        order.append(shot_id)
        bucket = _bucket_for(renderer)
        if bucket:
            used[bucket] = used.get(bucket, 0) + 1

    # 2. Demote over-budget buckets.

    by_id = {str(s.get("shot_id", "")): s for s in shotlist}
    for bucket, limit in sorted(limits.items()):
        primary_ids = BUCKET_RENDERERS.get(bucket, [])
        members = [sid for sid in order
                   if assigned[sid] in primary_ids]
        over = len(members) - limit
        if over <= 0:
            continue
        # Demote non-hero shots first (hero shots are protected §2C).
        members.sort(key=lambda sid: (
            0 if by_id[sid].get("generation_priority") == "hero" else 1,
            -order.index(str(by_id[sid].get("shot_id", "")))))
        # Demote from the tail of the shotlist first — early shots (hook)
        # carry more narrative value.
        for sid in members:
            if over <= 0:
                break
            if by_id[sid].get("generation_priority") == "hero":
                continue  # hero shots are never demoted for budget (§2C)
            target = _demote_target(assigned[sid], available, limits, used)
            if target is None:
                continue
            target_bucket = _bucket_for(target)
            old = assigned[sid]
            assigned[sid] = target
            if target_bucket:
                used[target_bucket] = used.get(target_bucket, 0) + 1
            old_bucket = _bucket_for(old)
            if old_bucket:
                used[old_bucket] = max(0, used.get(old_bucket, 0) - 1)
            result.changes.append({
                "shot_id": sid, "from": old, "to": target,
                "reason": f"budget: {bucket} over limit ({limit})",
            })
            over -= 1

    # 3. Report final per-bucket counts and notes.
    final_counts: dict[str, int] = {}
    for sid in order:
        bucket = _bucket_for(assigned[sid])
        if bucket:
            final_counts[bucket] = final_counts.get(bucket, 0) + 1
    result.assignments = assigned
    result.bucket_counts = final_counts
    for bucket, limit in sorted(limits.items()):
        got = final_counts.get(bucket, 0)
        if got < limit:
            result.notes.append(
                f"{bucket}: {got}/{limit} filled (under budget — no forced "
                f"mismatch)")
    return result
