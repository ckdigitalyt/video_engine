"""Semantic action vocabulary + registry (JADE_TO_DO v0.3 §7).

The action system is richer than fade/move/transform/highlight.  Semantic
actions describe WHAT the world does ("the satellite keeps falling"), and
the compiler resolves each action through the ActionRegistry to trusted
primitives.  A sentence such as "the satellite keeps falling, but Earth's
surface curves away" maps to satellite.fall() + surface.curve_away() +
camera.follow(satellite) — not to on-screen text.
"""

from __future__ import annotations

from dataclasses import dataclass, field


class Action:
    # physics / motion
    ORBIT = "orbit"
    FALL = "fall"
    ACCELERATE = "accelerate"
    DECELERATE = "decelerate"
    COLLIDE = "collide"
    MISS = "miss"
    CURVE = "curve"
    FOLLOW = "follow"
    TRACE = "trace"
    # structure
    BRANCH = "branch"
    MERGE = "merge"
    CONVERGE = "converge"
    OSCILLATE = "oscillate"
    FLOW = "flow"
    SCATTER = "scatter"
    ASSEMBLE = "assemble"
    DISASSEMBLE = "disassemble"
    # compare / measure
    COMPARE = "compare"
    MEASURE = "measure"
    # wave / signal processing (§46: noise-cancelling)
    INTERFERE = "interfere"
    CANCEL = "cancel"
    # phase-change / burst (§46: popcorn)
    BURST = "burst"
    # phase-change / burst (§46: popcorn)
    BURST = "burst"
    # camera
    ZOOM_INTO = "zoom_into"
    ZOOM_OUT_OF = "zoom_out_of"
    FOCUS_ON = "focus_on"
    CROSS_SECTION = "cross_section"
    REVEAL_INSIDE = "reveal_inside"
    # legacy (kept for backwards compatibility with v1 specs)
    HIGHLIGHT = "highlight"
    REVEAL = "reveal"
    SORT = "sort"
    SUBTRACT = "subtract"
    MORPH = "morph"
    TRANSFORM = "transform"
    COUNT_DOWN = "count_down"


ALL_ACTIONS: frozenset[str] = frozenset(v for v in vars(Action).values()
                                        if isinstance(v, str))

# Actions that are camera-only (no entity mutation).
CAMERA_ACTIONS: frozenset[str] = frozenset({
    Action.ZOOM_INTO, Action.ZOOM_OUT_OF, Action.FOCUS_ON,
    Action.CROSS_SECTION, Action.REVEAL_INSIDE,
})

# Legacy digit/number transforms that require math verification.
MATH_VERIFIED_ACTIONS: frozenset[str] = frozenset({
    Action.SORT, Action.SUBTRACT, Action.MORPH, Action.TRANSFORM,
})


@dataclass
class ActionSpec:
    """How one semantic action resolves to trusted primitives."""
    action: str
    primitives: list[str]              # ordered primitive names (try in order)
    requires: tuple[str, ...] = ()     # entity types the target must have
    camera: str = "static"             # default camera move for this action
    explanation_level: int = 3         # default visual-explanation contribution


# ── ActionRegistry: semantic action -> trusted primitive(s) ─────────────
# The registry is the single bridge between the action grammar and the
# deterministic primitive library.  Adding a primitive requires an entry
# here AND a visual regression test (promotion process, spec §23).
ACTION_REGISTRY: dict[str, ActionSpec] = {
    Action.ORBIT: ActionSpec(
        Action.ORBIT, ["OrbitBody"], ("celestial_body", "moving_body"),
        camera="follow", explanation_level=5),
    Action.FALL: ActionSpec(
        Action.FALL, ["FallBody", "ForceVector"],
        ("moving_body",), camera="follow", explanation_level=5),
    Action.ACCELERATE: ActionSpec(
        Action.ACCELERATE, ["AccelerateBody"], ("moving_body",),
        camera="zoom_to", explanation_level=4),
    Action.DECELERATE: ActionSpec(
        Action.DECELERATE, ["AccelerateBody"], ("moving_body",),
        camera="zoom_out_of", explanation_level=4),
    Action.COLLIDE: ActionSpec(
        Action.COLLIDE, ["CollideBodies", "ImpactBurst"], (),
        camera="zoom_to", explanation_level=5),
    Action.MISS: ActionSpec(
        Action.MISS, ["MissBody"], ("moving_body",),
        camera="follow", explanation_level=5),
    Action.CURVE: ActionSpec(
        Action.CURVE, ["CurvePath"], (),
        camera="pan", explanation_level=4),
    Action.FOLLOW: ActionSpec(
        Action.FOLLOW, ["FollowBody"], ("moving_body",),
        camera="follow", explanation_level=3),
    Action.TRACE: ActionSpec(
        Action.TRACE, ["TracePath"], ("moving_body",),
        camera="follow", explanation_level=4),
    Action.BRANCH: ActionSpec(
        Action.BRANCH, ["BranchFlow"], ("flow",), camera="pan",
        explanation_level=4),
    Action.MERGE: ActionSpec(
        Action.MERGE, ["MergeFlow"], ("flow",), camera="pan",
        explanation_level=4),
    Action.CONVERGE: ActionSpec(
        Action.CONVERGE, ["AttractorDiagram", "ConvergenceParticles"], (),
        camera="pull_out", explanation_level=5),
    Action.OSCILLATE: ActionSpec(
        Action.OSCILLATE, ["OscillateBody"], ("moving_body",),
        camera="static", explanation_level=4),
    Action.FLOW: ActionSpec(
        Action.FLOW, ["FlowThrough"], ("flow", "pipeline", "node"),
        camera="pan", explanation_level=4),
    Action.SCATTER: ActionSpec(
        Action.SCATTER, ["ScatteringField"], ("scatterer",),
        camera="zoom_into", explanation_level=5),
    Action.ASSEMBLE: ActionSpec(
        Action.ASSEMBLE, ["AssembleBodies"], (), camera="pull_out",
        explanation_level=4),
    Action.DISASSEMBLE: ActionSpec(
        Action.DISASSEMBLE, ["DisassembleBodies"], (), camera="zoom_out_of",
        explanation_level=4),
    Action.COMPARE: ActionSpec(
        Action.COMPARE, ["Comparison"], (), camera="static",
        explanation_level=3),
    Action.MEASURE: ActionSpec(
        Action.MEASURE, ["MeasureValue"], (), camera="zoom_to",
        explanation_level=4),
    Action.INTERFERE: ActionSpec(
        Action.INTERFERE, ["InterferencePattern", "WaveSuperposition"],
        ("wave", "interference"), camera="zoom_to", explanation_level=5),
    Action.CANCEL: ActionSpec(
        Action.CANCEL, ["WaveSuperposition", "InterferencePattern"],
        ("wave", "interference"), camera="zoom_to", explanation_level=5),
    Action.BURST: ActionSpec(
        Action.BURST, ["PressureKernel", "BurstExplosion"],
        ("kernel", "explosion"), camera="zoom_to", explanation_level=5),
    Action.BURST: ActionSpec(
        Action.BURST, ["PressureKernel", "BurstExplosion"],
        ("kernel", "explosion"), camera="zoom_to", explanation_level=5),
    Action.ZOOM_INTO: ActionSpec(
        Action.ZOOM_INTO, [], (), camera="zoom_to", explanation_level=2),
    Action.ZOOM_OUT_OF: ActionSpec(
        Action.ZOOM_OUT_OF, [], (), camera="zoom_out_of", explanation_level=2),
    Action.FOCUS_ON: ActionSpec(
        Action.FOCUS_ON, [], (), camera="focus", explanation_level=2),
    Action.CROSS_SECTION: ActionSpec(
        Action.CROSS_SECTION, ["CrossSection"], (), camera="zoom_to",
        explanation_level=4),
    Action.REVEAL_INSIDE: ActionSpec(
        Action.REVEAL_INSIDE, ["RevealInside"], (), camera="zoom_to",
        explanation_level=4),
    # legacy mappings (v1 compat — kept, math-verified)
    Action.HIGHLIGHT: ActionSpec(
        Action.HIGHLIGHT, ["HighlightTarget"], (), camera="static",
        explanation_level=1),
    Action.REVEAL: ActionSpec(
        Action.REVEAL, ["FixedPointReveal", "QuestionReveal"], (),
        camera="focus", explanation_level=3),
    Action.SORT: ActionSpec(
        Action.SORT, ["reorder_digits"], ("digit_array",), camera="follow",
        explanation_level=4),
    Action.SUBTRACT: ActionSpec(
        Action.SUBTRACT, ["apply_kaprekar_step"], ("number",),
        camera="zoom_to", explanation_level=5),
    Action.MORPH: ActionSpec(
        Action.MORPH, ["morph_number"], ("number", "digit_array"),
        camera="focus", explanation_level=4),
    Action.TRANSFORM: ActionSpec(
        Action.TRANSFORM, ["morph_number"], ("number", "digit_array"),
        camera="focus", explanation_level=4),
    Action.COUNT_DOWN: ActionSpec(
        Action.COUNT_DOWN, ["ConvergenceParticles"], (), camera="focus",
        explanation_level=3),
}


def resolve(action: str) -> ActionSpec | None:
    """Resolve a semantic action to its ActionSpec (None if unknown)."""
    return ACTION_REGISTRY.get(action)


def unknown_actions(actions: list[str]) -> list[str]:
    return [a for a in actions if a not in ACTION_REGISTRY]
