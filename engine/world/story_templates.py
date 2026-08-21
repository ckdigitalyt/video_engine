"""Story template library + StoryArchitect + hero mechanism (v0.3 §13–15).

The satellite video is strong because it used an experiment: drop -> slow
throw -> faster throw -> orbital speed -> why it works.  That is one of the
default story templates.  The StoryArchitect picks a template from the
topic + facts + representation and emits the hero_mechanism — the one
animation that proves the central mechanism (§13).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from engine.world.representations import RepType, select_representation
from engine.world.world_model import HeroMechanism

# ── Beat roles (used to derive per-beat intents) ─────────────────────────
ROLE_INTENTS = {
    "hook": "hook",
    "question": "pose_question",
    "simple_experiment": "demonstrate_transformation",
    "change_variable": "demonstrate_transformation",
    "observe": "discovery",
    "push_extreme": "build_intuition",
    "discover_principle": "show_convergence",
    "explain_principle": "explanation",
    "hero": "reveal",
    "evidence": "discovery",
    "mystery": "tension",
    "test": "demonstrate_transformation",
    "surprise": "tension",
    "general_rule": "explanation",
    "problem": "tension",
    "failure": "discovery",
    "insight": "reveal",
    "solution": "show_convergence",
    "resolution": "explanation",
    "comparison": "demonstrate_arithmetic",
    "payoff": "build_intuition",
    "close": "tension",
}


@dataclass
class StoryTemplate:
    name: str
    roles: list[str]                     # ordered beat roles
    description: str = ""
    default_for: str = ""                # "science" | "math" | "psychology" | ...


TEMPLATES: dict[str, StoryTemplate] = {
    "mystery_experiment_reveal": StoryTemplate(
        "mystery_experiment_reveal",
        ["hook", "mystery", "simple_experiment", "evidence", "reveal",
         "resolution", "payoff"],
        "Mystery -> Experiment -> Reveal"),
    "question_demonstration_explanation": StoryTemplate(
        "question_demonstration_explanation",
        ["hook", "question", "demonstration", "evidence", "explain_principle",
         "general_rule", "payoff"],
        "Question -> Demonstration -> Explanation"),
    "counterintuitive_proof_resolution": StoryTemplate(
        "counterintuitive_proof_resolution",
        ["hook", "counterintuitive_claim", "visual_proof", "evidence",
         "resolution", "payoff"],
        "Counterintuitive fact -> Visual proof -> Resolution"),
    "prediction_test_surprise_explanation": StoryTemplate(
        "prediction_test_surprise_explanation",
        ["hook", "prediction", "test", "surprise", "explain_principle",
         "payoff"],
        "Prediction -> Test -> Surprise -> Explanation"),
    "simple_extreme_general": StoryTemplate(
        "simple_extreme_general",
        ["hook", "simple_case", "extreme_case", "general_rule", "payoff"],
        "Simple case -> Extreme case -> General rule"),
    "problem_failure_insight_solution": StoryTemplate(
        "problem_failure_insight_solution",
        ["hook", "problem", "failure", "insight", "solution", "payoff"],
        "Problem -> Failure -> Insight -> Solution"),
    # EXPERIMENT-DRIVEN — the v0.2 satellite pattern (spec §14); default for
    # science/math/physics topics.
    "experiment_driven": StoryTemplate(
        "experiment_driven",
        ["hook", "question", "simple_experiment", "change_variable",
         "observe", "push_extreme", "discover_principle",
         "explain_principle", "payoff"],
        "QUESTION -> SIMPLE EXPERIMENT -> CHANGE ONE VARIABLE -> OBSERVE "
        "-> PUSH TO EXTREME -> DISCOVER PRINCIPLE -> EXPLAIN PRINCIPLE -> "
        "PAYOFF (the v0.2 satellite pattern)",
        default_for="science"),
}

# Keyword -> template preference (first match wins).
_TEMPLATE_RULES: list[tuple[frozenset[str], str]] = [
    (frozenset({"why", "because", "reason", "explain", "how", "physics",
                "orbit", "gravity", "sky", "scatter", "light", "wave",
                "sound", "number", "math"}), "experiment_driven"),
    (frozenset({"mystery", "secret", "hidden", "strange", "surprising",
                "weird"}), "mystery_experiment_reveal"),
    (frozenset({"prediction", "predict", "guess", "test", "experiment"}),
     "prediction_test_surprise_explanation"),
    (frozenset({"problem", "fail", "failure", "broken", "fix", "solution"}),
     "problem_failure_insight_solution"),
    (frozenset({"versus", "vs", "compare", "compared", "difference"}),
     "simple_extreme_general"),
]


@dataclass
class StoryPlan:
    topic: str
    template_name: str
    roles: list[str]
    hero_mechanism: Optional[HeroMechanism] = None
    rationale: str = ""


def select_template(topic: str, rep: RepType | None = None) -> StoryPlan:
    """Pick a story template for the topic (deterministic, spec §15)."""
    t = (topic or "").lower().strip()
    name = "experiment_driven"
    rationale = "default: experiment-driven (v0.2 satellite pattern)"
    for keywords, candidate in _TEMPLATE_RULES:
        if any(k in t for k in keywords):
            name = candidate
            rationale = f"matched keywords: {sorted(keywords & set(t.split()))}"
            break
    template = TEMPLATES[name]
    return StoryPlan(topic=topic, template_name=name,
                     roles=list(template.roles), rationale=rationale)


def _hero_visualization_for(topic: str, rep: RepType | None) -> str:
    """Map topic -> hero visualization primitive/pattern (spec §13)."""
    t = (topic or "").lower()
    if "sky" in t or "blue" in t or "scatter" in t:
        return "wavelength_dependent_scattering"
    if "orbit" in t or "satellite" in t or "gravity" in t:
        return "orbit_generation"
    if "mcgurk" in t or "illusion" in t:
        return "signal_integration"
    if "noise" in t or "cancell" in t or "headphone" in t \
            or "interference" in t or "anti-phase" in t:
        return "wave_inverse_interference"
    if "popcorn" in t or "pop" in t or "steam" in t \
            or "pressure" in t or "burst" in t or "kernel" in t:
        return "pressure_build_up_explosion"
    if "collatz" in t:
        return "trajectory_generation"
    if "kaprekar" in t:
        return "attractor_convergence"
    if rep == RepType.SIMULATION:
        return "deterministic_simulation"
    if rep == RepType.SIGNAL_FLOW:
        return "signal_flow"
    return "transformation_sequence"


def hero_for(topic: str, plan: StoryPlan,
             rep: RepType | None = None) -> HeroMechanism:
    """Emit the hero_mechanism for a plan (spec §13).

    The hero beat is the template's "explain_principle"/"visual_proof" role
    — the core visual proof of the central mechanism.
    """
    visualization = _hero_visualization_for(topic, rep)
    # hero beat index: the role that proves the principle; for the
    # experiment-driven template that is "explain_principle" (role 7 of 9).
    hero_idx = max(0, len(plan.roles) - 2)
    concept = {
        "wavelength_dependent_scattering":
            "shorter wavelengths scatter more strongly (I ∝ 1/λ⁴)",
        "orbit_generation":
            "continuous falling + sideways velocity = orbit",
        "signal_integration":
            "audio signal + visual mouth signal -> brain -> perceived sound",
        "wave_inverse_interference":
            "sound wave + inverse wave (180° anti-phase) -> destructive "
            "interference -> silence",
        "pressure_build_up_explosion":
            "heat -> water vaporizes (~100 °C) -> steam pressure rises -> "
            "shell bursts (~9 atm near ~180 °C) -> fluff",
        "trajectory_generation":
            "number -> even/odd rule -> transformation -> trajectory",
        "attractor_convergence":
            "every orbit falls into the same attractor",
        "deterministic_simulation":
            "state evolves according to deterministic rules",
        "signal_flow": "signal travels through a causal chain",
        "transformation_sequence": "one state transforms into the next",
    }.get(visualization, "the central mechanism, demonstrated visually")
    return HeroMechanism(
        concept=concept,
        visualization=visualization,
        target_beat=f"b{hero_idx + 1:03d}",
    )
