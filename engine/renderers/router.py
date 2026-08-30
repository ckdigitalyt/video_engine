"""router.py — Deterministic renderer-selection layer (directive §5).

Pure Python scoring, no LLM calls, no network. Given a shot's requirement
flags, cost priority, renderer availability and provider quota state, returns
a ranked renderer choice plus the §24 fallback chain.

Scoring model (see docs/architecture/v3_multi_renderer_design.md §5):

    score(r) = Σ_d w_d · q_d(r) − cost_penalty(r) − quota_penalty(r)
               + hero_bonus(r) − variation_penalty(r)

- w_d = 1.0 for every dimension flagged in shot["requirements"], 0.15
  baseline otherwise (keeps unflagged dimensions as a stable tie-breaker).
- cost_penalty pushes HIGH/HERO-cost renderers down for cheap shots.
- quota_penalty scales remote renderers by remaining provider quota.
- unavailable renderers are excluded from the primary choice but kept
  (marked) in the fallback chain so the degradation order stays visible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from engine.renderers.base import QUALITY_DIMENSIONS
from engine.renderers.registry import all_capabilities, fallback_chain

# Shot requirement flag -> quality dimension (same names, §5 list).
REQUIREMENT_FLAGS: tuple[str, ...] = (
    "realism",
    "physical_motion",
    "math_precision",
    "character_interaction",
    "emotional_impact",
    "historical_authenticity",
    "diagrammatic",
    "camera_movement",
    "text_heavy",
)

_BASELINE_WEIGHT = 0.15
_PRIORITY_TO_TIER = {"low": "LOW", "normal": "MEDIUM", "high": "HIGH", "hero": "HERO"}
_TIER_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "HERO": 3}


@dataclass
class RouterDecision:
    renderer_id: str
    score: float
    ranked: list[tuple[str, float]] = field(default_factory=list)
    fallback_chain: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)


def _requirements(shot: dict) -> dict[str, bool]:
    req = shot.get("requirements") or {}
    return {dim: bool(req.get(dim, False)) for dim in REQUIREMENT_FLAGS}


def _weights(req: dict[str, bool]) -> dict[str, float]:
    return {dim: (1.0 if req[dim] else _BASELINE_WEIGHT) for dim in REQUIREMENT_FLAGS}


def _cost_penalty(shot: dict, renderer_cost_tier: str) -> float:
    priority = shot.get("generation_priority", "normal")
    shot_tier = _PRIORITY_TO_TIER.get(priority, "MEDIUM")
    renderer_rank = _TIER_RANK.get(renderer_cost_tier, 1)
    shot_rank = _TIER_RANK[shot_tier]
    if renderer_rank <= shot_rank:
        return 0.0
    steps = renderer_rank - shot_rank
    # Premium requirements (realism/impact/characters) are exactly what
    # expensive renderers exist for — the visual budget (not the router)
    # enforces how often they run, so the penalty is soft there. Without
    # premium requirements, expensive renderers are genuinely wasteful.
    premium = any(
        shot.get("requirements", {}).get(f, False)
        for f in ("realism", "physical_motion", "character_interaction",
                  "emotional_impact", "historical_authenticity")
    )
    per_step = 0.15 if premium else 0.3
    return per_step * steps


def _hero_bonus(shot: dict, renderer_cost_tier: str) -> float:
    if shot.get("generation_priority") == "hero" and renderer_cost_tier in ("HIGH", "HERO"):
        return 0.25
    return 0.0


def _quota_penalty(quota: dict[str, float] | None, renderer_id: str, cap) -> float:
    """Quota fraction (0..1) per *provider-ish* key; a renderer is penalised
    when any matching quota entry is low. Keys may be renderer ids (AI_VIDEO)
    or provider ids; renderer id takes precedence."""
    if not quota:
        return 0.0
    fraction: float | None = None
    if renderer_id in quota:
        fraction = float(quota[renderer_id])
    elif cap.requires_network and "__remote__" in quota:
        fraction = float(quota["__remote__"])
    if fraction is None or fraction >= 1.0:
        return 0.0
    # Fully exhausted → effectively unavailable (1.2 penalty dwarfs scores).
    return (1.0 - max(0.0, fraction)) * 1.2


def _is_available(renderer_id: str, cap, availability: dict[str, bool] | None) -> bool:
    if availability is not None and renderer_id in availability:
        return bool(availability[renderer_id])
    return cap.enabled


def select_renderer(
    shot: dict,
    *,
    availability: dict[str, bool] | None = None,
    quota: dict[str, float] | None = None,
    style: dict[str, Any] | None = None,
) -> RouterDecision:
    """Choose the best renderer for *shot*.

    Args:
        shot: Shot v3 dict (uses `requirements`, `generation_priority`,
            `renderer` as soft hint, `narrative_role`).
        availability: optional explicit availability overrides
            {renderer_id: bool}. When absent, registry `enabled` flags apply.
        quota: optional remaining-quota fractions {id: 0..1}. Renderer ids or
            the special `__remote__` key (applies to network renderers).
        style: VideoStyleSpec dict (reserved for style-affinity bonuses;
            deterministic only — never an LLM call).

    Returns:
        RouterDecision with primary choice, full ranking and fallback chain.
    """
    req = _requirements(shot)
    weights = _weights(req)
    caps = all_capabilities()
    reasons: list[str] = []
    ranked: list[tuple[str, float]] = []
    excluded: list[str] = []

    for renderer_id, cap in caps.items():
        if not _is_available(renderer_id, cap, availability):
            excluded.append(renderer_id)
            continue
        q = cap.quality_dimensions
        score = sum(weights[dim] * q[dim] for dim in REQUIREMENT_FLAGS)
        cost_pen = _cost_penalty(shot, cap.cost_tier)
        hero_bon = _hero_bonus(shot, cap.cost_tier)
        quota_pen = _quota_penalty(quota, renderer_id, cap)
        score += hero_bon - cost_pen - quota_pen

        if shot.get("requirements", {}).get("historical_authenticity") and renderer_id == "ARCHIVAL":
            score += 0.2
            reasons.append("historical_authenticity: ARCHIVAL bonus")
        if hero_bon:
            reasons.append(f"{renderer_id}: hero-priority bonus")
        if cost_pen:
            reasons.append(
                f"{renderer_id}: cost penalty {cost_pen:.1f} (tier {cap.cost_tier} "
                f"vs priority {shot.get('generation_priority', 'normal')})"
            )
        if quota_pen >= 1.2:
            reasons.append(f"{renderer_id}: quota exhausted")
        ranked.append((renderer_id, round(score, 6)))

    ranked.sort(key=lambda pair: (-pair[1], pair[0]))  # deterministic tie-break by id

    if not ranked:
        raise ValueError("no available renderer for shot")

    best_id, best_score = ranked[0]

    # Soft hint: a director-chosen renderer gets a small affinity bonus
    # re-check — if the hint ranks within 0.5 of the winner, honour it.
    hint = shot.get("renderer")
    if hint and hint != best_id:
        hint_scores = dict(ranked)
        if hint in hint_scores and best_score - hint_scores[hint] <= 0.5:
            best_id, best_score = hint, hint_scores[hint]
            reasons.append(f"director hint {hint} honoured (within 0.5 of top score)")

    chain = _build_fallback_chain(best_id, req, ranked, availability, caps)
    return RouterDecision(
        renderer_id=best_id,
        score=best_score,
        ranked=ranked,
        fallback_chain=chain,
        reasons=reasons,
    )


def _build_fallback_chain(
    chosen: str,
    req: dict[str, bool],
    ranked: list[tuple[str, float]],
    availability: dict[str, bool] | None,
    caps: dict,
) -> list[str]:
    """Chosen renderer first, then §24 canonical chain filtered by
    availability; ARCHIVAL splices in for historical shots; unavailable
    renderers are appended at the end, explicitly marked 'off:'."""
    canonical = fallback_chain()
    available_ids = {rid for rid, _ in ranked}
    chain = [chosen]
    for rid in canonical:
        if rid == chosen or rid in chain:
            continue
        if req.get("historical_authenticity") and rid == "ARCHIVAL" and rid not in chain:
            # splice right after STOCK_VIDEO if present
            if "STOCK_VIDEO" in chain:
                chain.insert(chain.index("STOCK_VIDEO") + 1, rid)
                continue
        if rid in available_ids:
            chain.append(rid)
    # Any remaining available renderers not in the canonical chain.
    for rid, _ in ranked:
        if rid not in chain and rid in available_ids:
            chain.append(rid)
    # Mark unavailable ones so operators see the intended order.
    for rid in canonical:
        if rid not in chain:
            cap = caps[rid]
            if not _is_available(rid, cap, availability):
                chain.append(f"off:{rid}")
    return chain
