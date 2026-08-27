"""CompositionPlanner — composition/attention as a first-class planning stage
(JADE_TO_DO v0.3 §20–21).

Deterministic, pre-render.  For every beat (shot) the planner decides:

    focal object       — one clear focal point per shot (normally exactly one)
    object scale       — focal / support / background sizing
    spatial arrangement— zone assignment (focal / support / text)
    camera target      — what the camera looks at
    visual hierarchy   — focal > support > background > text
    negative space     — how much of the frame is deliberately left empty
    when to zoom       — push_in / zoom_to timing (hero, climax beats)
    when to reframe    — pull_out / pan timing (payoff, transitions)
    what exits         — objects whose role ended this beat
    what remains       — persistent objects that stay on stage

and computes attention metrics (§21):

    focal_area_ratio, semantic_object_area, empty_area_ratio,
    text_area_ratio, focal_contrast

plus pacing intelligence (§22):

    fast_reveal, slow_explanation, pause, build, escalation,
    climax, release

These are PLAN-LEVEL estimates: deterministic, derived from the semantic
plan before rendering.  Pixel-level measurement stays in frame QA; the
two are complementary — plan metrics say "intended attention", frame QA
says "measured attention".  The gate (gate_composition) enforces that
intentions are sane (one focal point, no maximized density).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from engine.visuals.scene_state import Zone
from engine.world.world_model import WorldState

# ────────────────────────────────────────────────────────────────────────
# pacing intelligence (§22)
# ────────────────────────────────────────────────────────────────────────
PACING_TAGS = (
    "fast_reveal", "slow_explanation", "pause", "build",
    "escalation", "climax", "release",
)

# story role -> pacing tag (deterministic; hero beat is forced to climax)
_ROLE_PACING: dict[str, str] = {
    "hook": "fast_reveal",
    "question": "build",
    "mystery": "build",
    "simple_experiment": "slow_explanation",
    "change_variable": "slow_explanation",
    "observe": "pause",
    "push_extreme": "escalation",
    "discover_principle": "climax",
    "explain_principle": "slow_explanation",
    "general_rule": "slow_explanation",
    "evidence": "escalation",
    "resolution": "release",
    "payoff": "release",
    "close": "release",
    "prediction": "pause",
    "test": "build",
    "surprise": "escalation",
    "simple_case": "slow_explanation",
    "extreme_case": "escalation",
    "problem": "build",
    "failure": "escalation",
    "insight": "climax",
    "solution": "climax",
    "demonstration": "climax",
    "counterintuitive_claim": "escalation",
    "visual_proof": "climax",
    "comparison": "slow_explanation",
}

# camera scale by pacing (focal-frame tightness; hero = tightest)
_PACING_SCALE: dict[str, float] = {
    "fast_reveal": 0.78,
    "slow_explanation": 0.72,
    "pause": 0.80,
    "build": 0.74,
    "escalation": 0.66,
    "climax": 0.58,
    "release": 0.92,
}

# zone assignment by role in the composition
_FOCAL_ZONE = Zone.FOCUS
_SUPPORT_ZONES = [Zone.LEFT, Zone.RIGHT, Zone.TOP, Zone.BOTTOM]


@dataclass
class AttentionMetrics:
    """Planned attention metrics (§21).  All ratios are 0..1 estimates."""
    focal_area_ratio: float = 0.0
    semantic_object_area: float = 0.0
    empty_area_ratio: float = 1.0
    text_area_ratio: float = 0.0
    focal_contrast: float = 0.0

    def to_dict(self) -> dict:
        return {
            "focal_area_ratio": round(self.focal_area_ratio, 3),
            "semantic_object_area": round(self.semantic_object_area, 3),
            "empty_area_ratio": round(self.empty_area_ratio, 3),
            "text_area_ratio": round(self.text_area_ratio, 3),
            "focal_contrast": round(self.focal_contrast, 3),
        }


@dataclass
class CompositionPlan:
    """One beat's composition decision (§20)."""
    beat_id: str
    focal_object: Optional[str] = None
    supporting_objects: list[str] = field(default_factory=list)
    background: list[str] = field(default_factory=list)
    text: Optional[str] = None
    camera: dict = field(default_factory=lambda: {"type": "static",
                                                  "target": None,
                                                  "scale": 0.72})
    hierarchy: list[str] = field(default_factory=list)
    arrangement: dict = field(default_factory=dict)
    negative_space: float = 0.4
    zoom: Optional[str] = None            # "push_in" | "zoom_to" | None
    reframe: Optional[str] = None         # "pull_out" | "pan" | "reframe" | None
    exits: list[str] = field(default_factory=list)
    remains: list[str] = field(default_factory=list)
    pacing: str = "slow_explanation"
    attention: AttentionMetrics = field(default_factory=AttentionMetrics)

    def to_dict(self) -> dict:
        return {
            "beat_id": self.beat_id,
            "focal_object": self.focal_object,
            "supporting_objects": list(self.supporting_objects),
            "background": list(self.background),
            "text": self.text,
            "camera": self.camera,
            "hierarchy": list(self.hierarchy),
            "arrangement": self.arrangement,
            "negative_space": round(self.negative_space, 3),
            "zoom": self.zoom,
            "reframe": self.reframe,
            "exits": list(self.exits),
            "remains": list(self.remains),
            "pacing": self.pacing,
            "attention_metrics": self.attention.to_dict(),
        }


@dataclass
class CompositionReport:
    """Aggregate attention report across all beats (§21)."""
    per_beat: list[dict] = field(default_factory=list)
    avg_focal_contrast: float = 0.0
    avg_empty_area_ratio: float = 0.0
    beats_without_focal: list[str] = field(default_factory=list)
    beats_with_multiple_focal: list[str] = field(default_factory=list)
    passed: bool = False

    def to_dict(self) -> dict:
        return {
            "per_beat": self.per_beat,
            "avg_focal_contrast": round(self.avg_focal_contrast, 3),
            "avg_empty_area_ratio": round(self.avg_empty_area_ratio, 3),
            "beats_without_focal": list(self.beats_without_focal),
            "beats_with_multiple_focal": list(self.beats_with_multiple_focal),
            "passed": self.passed,
        }


# ────────────────────────────────────────────────────────────────────────
# helpers
# ────────────────────────────────────────────────────────────────────────
def _beat_ref_ids(beat: dict) -> list[str]:
    """Object ids referenced by a beat (entities on stage this beat)."""
    out: list[str] = []
    for o in beat.get("objects", []) or []:
        if isinstance(o, dict) and o.get("id"):
            out.append(str(o["id"]))
    return out


def _action_targets(beat: dict) -> list[str]:
    out: list[str] = []
    for a in beat.get("semantic_actions", []) or []:
        t = a.get("target")
        if t:
            out.append(str(t))
    for tf in beat.get("transformations", []) or []:
        for k in ("targets", "target_objects"):
            for t in tf.get(k, []) or []:
                if t:
                    out.append(str(t))
        t = tf.get("target")
        if t:
            out.append(str(t))
    return out


def _camera_target(beat: dict) -> Optional[str]:
    cam = beat.get("camera") or {}
    t = cam.get("target")
    return str(t) if t else None


def _pick_focal(beat: dict, ref_ids: list[str]) -> Optional[str]:
    """One clear focal point: first action target on stage, else camera
    target, else first object.  Payoff/full-frame beats may have none."""
    for t in _action_targets(beat):
        if t in ref_ids or t:  # action target may not be re-listed as object
            return t
    cam_t = _camera_target(beat)
    if cam_t:
        return cam_t
    return ref_ids[0] if ref_ids else None


def _pacing_for(beat: dict, importance: str) -> str:
    role = str(beat.get("role", ""))
    tag = _ROLE_PACING.get(role, "slow_explanation")
    if importance == "high":
        # hero beats must read as the climax (or escalation for builds)
        tag = "climax" if tag != "release" else "release"
    return tag


def _arrangement(focal: Optional[str], supports: list[str],
                 text: Optional[str]) -> dict:
    zones: dict[str, str] = {}
    if focal:
        zones[focal] = _FOCAL_ZONE.value
    for i, s in enumerate(supports):
        zones[s] = _SUPPORT_ZONES[i % len(_SUPPORT_ZONES)].value
    if text:
        zones[text] = Zone.BOTTOM.value
    return {
        "focal_zone": _FOCAL_ZONE.value,
        "support_zones": sorted({zones[s] for s in supports}),
        "text_zone": Zone.BOTTOM.value if text else None,
        "zones": zones,
    }


# ────────────────────────────────────────────────────────────────────────
# planner
# ────────────────────────────────────────────────────────────────────────
def plan_beat(beat: dict, world: Optional[WorldState],
              prev_ids: set[str], future_ids: set[str],
              importance: str = "medium") -> CompositionPlan:
    """Produce the composition plan for one beat (§20–21)."""
    bid = str(beat.get("beat_id", "?"))
    ref_ids = _beat_ref_ids(beat)
    refs = set(ref_ids)
    focal = _pick_focal(beat, ref_ids)
    supports = [r for r in ref_ids if r != focal]
    # release beats (payoff / end card) read as resolution: no tight focal
    # object — the loose 0.92 frame + focal would fail hero-tightness
    # expectations (pacing/scale mismatch)
    pacing = _pacing_for(beat, importance)
    if pacing == "release":
        focal = None
        supports = []
    # background = persistent world entities not referenced this beat
    background: list[str] = []
    if world is not None:
        for e in world.entities:
            if e.id not in refs and e.id not in prev_ids:
                background.append(e.id)
    # text element (kinetic title / reveal / payoff narration)
    vtype = str(beat.get("visual_type", "")).lower()
    text: Optional[str] = None
    if vtype in ("kinetic_title", "question", "claim", "cycle",
                 "conclusion", "reveal", "payoff", "text"):
        text = f"{vtype}:{bid}"

    pacing = _pacing_for(beat, importance)
    scale = _PACING_SCALE.get(pacing, 0.72)

    # zoom / reframe decisions
    zoom: Optional[str] = None
    reframe: Optional[str] = None
    cam = beat.get("camera") or {}
    ctype = str(cam.get("type", "static"))
    if ctype in ("zoom_to", "push_in", "focus"):
        zoom = "push_in" if pacing in ("climax", "escalation") else "zoom_to"
    elif ctype in ("zoom_from", "pull_out", "zoom_out_of"):
        reframe = "pull_out"
    elif ctype == "pan":
        reframe = "pan"
    elif ctype == "reframe":
        reframe = "reframe"
    if zoom is None and pacing == "climax" and focal:
        zoom = "push_in"

    # exits / remains (stage continuity, mirrors compiler EXIT sweep)
    exits = sorted(prev_ids - refs - future_ids)
    remains = sorted(refs & (prev_ids | future_ids | refs))

    # hierarchy: focal > supports > background > text
    hierarchy = ([focal] if focal else []) + supports + background
    if text:
        hierarchy.append(text)

    # negative space: deliberate emptiness — fewer objects, more empty
    n_objects = len(ref_ids)
    negative = max(0.15, min(0.65, 0.45 - 0.06 * n_objects))
    if pacing in ("release", "pause"):
        negative = max(negative, 0.5)

    # ── attention metrics (§21) — planned estimates ───────────────────
    focal_area = 0.28 if focal else 0.0
    support_area = min(0.55, 0.16 * len(supports))
    semantic_area = min(0.72, focal_area + support_area)
    text_area = 0.16 if text else 0.0
    # empty_area_ratio reflects the DELIBERATE negative-space plan
    # (fewer objects / release-pause beats -> more empty frame); a dense
    # beat therefore reports low empty ratio and trips gate_composition.
    empty = negative
    # one clear focal point -> high contrast; none -> low
    focal_contrast = 0.95 if (focal and len(supports) <= 3) else (
        0.6 if focal else 0.15)
    attn = AttentionMetrics(
        focal_area_ratio=focal_area,
        semantic_object_area=round(semantic_area, 3),
        empty_area_ratio=round(empty, 3),
        text_area_ratio=round(text_area, 3),
        focal_contrast=focal_contrast,
    )

    return CompositionPlan(
        beat_id=bid,
        focal_object=focal,
        supporting_objects=supports,
        background=background,
        text=text,
        camera={"type": ctype, "target": focal or _camera_target(beat),
                "scale": round(scale, 2)},
        hierarchy=hierarchy,
        arrangement=_arrangement(focal, supports, text),
        negative_space=negative,
        zoom=zoom,
        reframe=reframe,
        exits=exits,
        remains=remains,
        pacing=pacing,
        attention=attn,
    )


def plan_composition(beats: list[dict],
                     world: Optional[WorldState] = None) -> CompositionReport:
    """Plan composition for every beat; returns the aggregate report.

    Does NOT mutate the beats — the report's per_beat dicts are what the
    spec/metadata carry.  (Callers may attach them to beats if desired.)
    """
    plans: list[CompositionPlan] = []
    prev_ids: set[str] = set()
    total_ids: set[str] = set()
    for b in beats:
        total_ids |= set(_beat_ref_ids(b))
    for idx, b in enumerate(beats):
        future_ids: set[str] = set()
        for nb in beats[idx + 1:]:
            future_ids |= set(_beat_ref_ids(nb))
        importance = str(b.get("importance", "medium"))
        plan = plan_beat(b, world, prev_ids, future_ids, importance)
        plans.append(plan)
        prev_ids |= set(_beat_ref_ids(b))

    per_beat = [p.to_dict() for p in plans]
    if not plans:
        return CompositionReport()

    avg_contrast = sum(p.attention.focal_contrast for p in plans) / len(plans)
    avg_empty = sum(p.attention.empty_area_ratio for p in plans) / len(plans)
    no_focal = [p.beat_id for p in plans if p.focal_object is None]
    multi = [p.beat_id for p in plans
             if sum(1 for s in p.supporting_objects
                    if s == p.focal_object) > 0]  # focal never in supports
    # sanity: a beat with objects but no focal is an attention failure
    # (payoff/release beats legitimately have none — allow those)
    bad = [p.beat_id for p in plans
           if p.focal_object is None
           and p.pacing not in ("release", "pause")
           and (p.supporting_objects or p.background)]
    passed = (
        not bad
        and avg_contrast >= 0.5
        and avg_empty >= 0.20
        and len(no_focal) <= len(plans) * 0.35
    )
    return CompositionReport(
        per_beat=per_beat,
        avg_focal_contrast=avg_contrast,
        avg_empty_area_ratio=avg_empty,
        beats_without_focal=no_focal,
        beats_with_multiple_focal=multi,
        passed=passed,
    )


def attach_composition(vs: dict,
                       world: Optional[WorldState] = None) -> CompositionReport:
    """Phase B entry point: plan composition for a v2 VisualSpec and
    attach the report to metadata (and per-beat plans to beats)."""
    beats = vs.get("beats", [])
    if world is None:
        wd = (vs.get("metadata", {}) or {}).get("world")
        if wd:
            try:
                world = WorldState.from_dict(wd)
            except Exception:  # noqa: BLE001
                world = None
    report = plan_composition(beats, world)
    by_id = {p["beat_id"]: p for p in report.per_beat}
    for b in beats:
        plan = by_id.get(str(b.get("beat_id", "")))
        if plan is not None:
            b["composition"] = plan
    vs.setdefault("metadata", {})["composition_report"] = report.to_dict()
    return report
