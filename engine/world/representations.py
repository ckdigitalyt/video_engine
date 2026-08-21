"""Representation selection (JADE_TO_DO v0.3 §8).

The VisualDirector decides the BEST visual representation for a topic
BEFORE any rendering.  Deterministic rule layer (first match wins); the LLM
is only a tie-breaker.  KINETIC_TEXT is an explicit last resort — never the
default (spec §9).

Renderer is selected AFTER representation:
PHYSICAL_MODEL / SIMULATION / MATHEMATICAL_TRANSFORMATION / SIGNAL_FLOW /
EXPERIMENT / CAUSE_EFFECT / DIRECT_DIAGRAM / COMPARISON / TIMELINE / GRAPH /
NETWORK / METAPHOR / HYBRID -> manim
REAL_MEDIA -> media renderer (reserved)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class RepType(str, Enum):
    DIRECT_DIAGRAM = "DIRECT_DIAGRAM"
    SIMULATION = "SIMULATION"
    PHYSICAL_MODEL = "PHYSICAL_MODEL"
    MATHEMATICAL_TRANSFORMATION = "MATHEMATICAL_TRANSFORMATION"
    CAUSE_EFFECT = "CAUSE_EFFECT"
    SIGNAL_FLOW = "SIGNAL_FLOW"
    COMPARISON = "COMPARISON"
    TIMELINE = "TIMELINE"
    GRAPH = "GRAPH"
    NETWORK = "NETWORK"
    CHARACTER_ACTION = "CHARACTER_ACTION"
    EXPERIMENT = "EXPERIMENT"
    METAPHOR = "METAPHOR"
    KINETIC_TEXT = "KINETIC_TEXT"
    REAL_MEDIA = "REAL_MEDIA"
    HYBRID = "HYBRID"


MANIM_REPS = {
    RepType.DIRECT_DIAGRAM, RepType.SIMULATION, RepType.PHYSICAL_MODEL,
    RepType.MATHEMATICAL_TRANSFORMATION, RepType.CAUSE_EFFECT,
    RepType.SIGNAL_FLOW, RepType.COMPARISON, RepType.TIMELINE,
    RepType.GRAPH, RepType.NETWORK, RepType.EXPERIMENT, RepType.METAPHOR,
    RepType.HYBRID,
}


@dataclass
class Representation:
    primary: RepType
    secondary: list[RepType]
    renderer: str                       # "manim" | "media" | "vector"
    rationale: str


# Deterministic rules: (matched keyword set, primary, secondary, rationale)
# Order matters — first match wins.
_RULES: list[tuple[frozenset[str], RepType, tuple[RepType, ...], str]] = [
    (frozenset({"mcgurk", "illusion", "perception", "hearing", "listening",
                "lip", "lipreading", "audio-visual", "audiovisual"}),
     RepType.SIGNAL_FLOW, (RepType.EXPERIMENT, RepType.CHARACTER_ACTION),
     "perception/illusion topics: signal flow + experiment"),
    (frozenset({"orbit", "orbital", "satellite", "gravity", "kepler",
                "planet", "planetary", "ballistic", "projectile",
                "mechanics", "celestial", "space", "trajectory"}),
     RepType.PHYSICAL_MODEL, (RepType.SIMULATION,),
     "mechanics topics: physical model + simulation"),
    (frozenset({"kaprekar", "collatz", "number", "sequence", "converge",
                "convergence", "constant", "mathematics", "math", "proof",
                "theorem", "trajectory"}),
     RepType.MATHEMATICAL_TRANSFORMATION, (RepType.GRAPH,),
     "number-theory topics: transformation + graph"),
    (frozenset({"sky", "blue", "scatter", "scattering", "atmosphere",
                "atmospheric", "optics", "light", "refraction", "color",
                "colour", "rayleigh", "sunset", "wavelength", "rainbow",
                "prism", "lens"}),
     RepType.SIMULATION, (RepType.SIGNAL_FLOW,),
     "optics/atmosphere topics: simulation + signal flow"),
    (frozenset({"wave", "sound", "audio", "frequency", "oscillation",
                "vibration", "resonance", "acoustic"}),
     RepType.SIMULATION, (RepType.SIGNAL_FLOW,),
     "wave topics: simulation + signal flow"),
    (frozenset({"noise", "cancell", "cancellation", "headphone",
                "headphones", "interference", "anti-phase", "silence",
                "active noise"}),
     RepType.SIMULATION, (RepType.SIGNAL_FLOW,),
     "noise-cancelling topics: simulation + signal flow (wave → mic → "
     "processor → inverse wave → superposition)"),
    (frozenset({"popcorn", "pop", "steam", "pressure", "explosion",
                "burst", "kernel", "boil", "vaporiz", "vaporis"}),
     RepType.EXPERIMENT, (RepType.CAUSE_EFFECT,),
     "phase-change/explosion topics: experiment + cause-effect (heat → "
     "pressure → burst → fluff)"),
    (frozenset({"history", "historical", "event", "timeline", "century",
                "era", "origin", "discovery of"}),
     RepType.TIMELINE, (RepType.REAL_MEDIA,),
     "historical topics: timeline (+ real media when available)"),
    (frozenset({"versus", "vs", "compared", "comparison", "difference",
                "similarities", "faster than", "better than"}),
     RepType.COMPARISON, (RepType.DIRECT_DIAGRAM,),
     "comparison topics: side-by-side"),
    (frozenset({"network", "neural", "internet", "connected", "graph of",
                "links", "relationships between"}),
     RepType.NETWORK, (RepType.GRAPH,),
     "network topics: graph/network"),
    (frozenset({"brain", "memory", "attention", "psychology", "emotion",
                "cognitive", "mind"}),
     RepType.CAUSE_EFFECT, (RepType.SIGNAL_FLOW,),
     "psychology topics: cause-effect + signal flow"),
    (frozenset({"why", "because", "reason", "cause", "explain", "how does",
                "how do", "what happens"}),
     RepType.CAUSE_EFFECT, (RepType.EXPERIMENT,),
     "explanation topics: cause-effect + experiment"),
]


def _normalize(topic: str) -> str:
    return (topic or "").lower().strip()


def select_representation(topic: str,
                          llm_override: str | None = None) -> Representation:
    """Choose the visual representation for a topic (deterministic rules).

    ``llm_override`` (optional) may pick among the rule-suggested secondary
    representations — it can never select KINETIC_TEXT unless the rules
    themselves conclude no mechanism exists.
    """
    t = _normalize(topic)
    for keywords, primary, secondary, rationale in _RULES:
        if any(k in t for k in keywords):
            return Representation(primary, list(secondary),
                                  "manim", rationale)
    # no mechanism keyword matched -> weakest useful default
    return Representation(RepType.CAUSE_EFFECT,
                          [RepType.DIRECT_DIAGRAM],
                          "manim",
                          "no mechanism keywords: cause-effect + diagram")


def is_kinetic_text_only(rep: Representation) -> bool:
    """True when the chosen representation is pure text (spec §9 fallback)."""
    return rep.primary == RepType.KINETIC_TEXT
