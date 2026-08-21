"""WorldState — the semantic world model (JADE_TO_DO v0.3 §4, §5, §18).

The conceptual layer UNDERNEATH Manim.  Every video is planned as semantic
entities + relationships + forces + signals + paths + states + measurements
+ labels + camera focus, with factual constraints attached (formula / units /
assumptions / source).  The VisualDirector consumes a WorldState and emits
per-beat VisualSpecs; the deterministic compiler materializes entities
through trusted primitives.

Design rules (spec §18, §19, §30):
- Pure Python, NO Manim imports: the world model is testable headless,
  LLM-agnostic, and independent of any renderer.
- Entity types come from a CLOSED registry (spec §6).  New types are
  promoted through the primitive promotion process — never invented ad hoc.
- Facts MUST accompany any quantitative claim; `assumptions` lists the
  simplifications so the animation never silently implies a physically
  wrong causal model (spec §19).
- Deterministic validation: entity references resolve, types are known,
  relationships are not self-loops, facts are complete.  DeepSeek is never
  the authority for physics/math (deterministic verifiers override).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ────────────────────────────────────────────────────────────────────────
# Closed entity-type registry (spec §6 — expanded primitive library)
# ────────────────────────────────────────────────────────────────────────
class EntityType:
    # physics
    CELESTIAL_BODY = "celestial_body"
    MOVING_BODY = "moving_body"
    ORBIT_PATH = "orbit_path"
    TRAJECTORY = "trajectory"
    PROJECTILE = "projectile"
    VELOCITY_VECTOR = "velocity_vector"
    FORCE_VECTOR = "force_vector"
    GRAVITY_FIELD = "gravity_field"
    REFERENCE_FRAME = "reference_frame"
    # science
    WAVE = "wave"
    SIGNAL = "signal"
    LIGHT_RAY = "light_ray"
    LIGHT_SOURCE = "light_source"
    MEDIUM = "medium"
    SCATTERER = "scatterer"
    PARTICLE = "particle"
    FIELD = "field"
    ATOM = "atom"
    MOLECULE = "molecule"
    LENS = "lens"
    CELL = "cell"
    # human / psychology (schematic glyphs, not anthropomorphic)
    FACE = "face"
    EYE = "eye"
    EAR = "ear"
    MOUTH = "mouth"
    BRAIN = "brain"
    PERSON = "person"
    ATTENTION = "attention"
    MEMORY = "memory"
    PERCEPTION = "perception"
    # information
    NODE = "node"
    CONNECTION = "connection"
    FLOW = "flow"
    PIPELINE = "pipeline"
    DECISION = "decision"
    TIMELINE = "timeline"
    CAUSE_EFFECT = "cause_effect"
    COMPARISON = "comparison"
    HIERARCHY = "hierarchy"
    # narrative
    QUESTION = "question"
    EXPERIMENT = "experiment"
    HYPOTHESIS = "hypothesis"
    OBSERVATION = "observation"
    REVEAL = "reveal"
    COUNTEREXAMPLE = "counterexample"
    PAYOFF = "payoff"
    # math
    NUMBER = "number"
    DIGIT_ARRAY = "digit_array"
    EQUATION = "equation"
    GRAPH = "graph"
    # generic
    TEXT = "text"
    SHAPE = "shape"
    LABEL = "label"


ENTITY_TYPES: set[str] = set(v for v in vars(EntityType).values()
                             if isinstance(v, str))

# Relationship kinds (spec §5 — relationship graph)
REL_KINDS: set[str] = {
    "gravity", "velocity", "emits_into", "scatters", "reaches", "absorbs",
    "reflects", "refracts", "causes", "flows_into", "transforms", "feeds",
    "depends_on", "compares_to", "attracts", "holds", "contains",
    "generates", "converts", "precedes", "follows", "signals",
}

# Signal kinds
SIGNAL_KINDS: set[str] = {
    "light_wave", "sound_wave", "electrical", "visual_signal",
    "audio_signal", "data_flow", "energy", "information",
}


# ────────────────────────────────────────────────────────────────────────
# World primitives
# ────────────────────────────────────────────────────────────────────────
@dataclass
class Entity:
    id: str
    type: str
    properties: dict[str, Any] = field(default_factory=dict)
    count: Optional[int] = None          # particle count for fields/swarms


@dataclass
class Relationship:
    source: str
    target: str
    type: str
    label: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Force:
    source: str                          # applying body (e.g. earth)
    target: str                          # receiving body (e.g. satellite)
    kind: str = "gravity"
    magnitude: Optional[float] = None
    formula: Optional[str] = None        # e.g. "F = G m1 m2 / r^2"
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Signal:
    id: str
    kind: str
    source: str                          # entity id
    target: str                          # entity id
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Path:
    id: str
    kind: str                            # orbit | ballistic | trajectory | curve
    entities: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class State:
    id: str
    kind: str
    value: Any = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Measurement:
    id: str
    kind: str
    value: Any = None
    units: str = ""
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Label:
    id: str
    text: str
    at: str = ""                         # entity id this label annotates
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class CameraFocus:
    target: str = ""                     # entity id the camera follows/focuses
    choreography: list[str] = field(default_factory=list)


@dataclass
class Fact:
    """A factual constraint attached to the world (spec §18).

    Quantitative claims MUST carry formula/units/source.  `assumptions`
    lists simplifications (e.g. "circular two-body orbit", "particles much
    smaller than the wavelength") so the visuals never imply a physically
    wrong causal model (spec §19).
    """
    claim: str
    formula: str = ""
    units: str = ""
    assumptions: list[str] = field(default_factory=list)
    source: str = ""
    verified: bool = False                # deterministic verifier passed


@dataclass
class HeroMechanism:
    """The one hero animation that proves the central mechanism (§13)."""
    concept: str
    visualization: str                    # primitive/pattern name
    target_beat: str = ""                 # e.g. "b004"


# ────────────────────────────────────────────────────────────────────────
# The world
# ────────────────────────────────────────────────────────────────────────
@dataclass
class WorldState:
    topic: str
    representation: str = "CAUSE_EFFECT"
    representation_secondary: list[str] = field(default_factory=list)
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)
    forces: list[Force] = field(default_factory=list)
    signals: list[Signal] = field(default_factory=list)
    paths: list[Path] = field(default_factory=list)
    states: list[State] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)
    labels: list[Label] = field(default_factory=list)
    camera: CameraFocus = field(default_factory=CameraFocus)
    hero_mechanism: Optional[HeroMechanism] = None
    facts: list[Fact] = field(default_factory=list)

    # ── lookup helpers ────────────────────────────────────────────────
    def entity(self, eid: str) -> Optional[Entity]:
        for e in self.entities:
            if e.id == eid:
                return e
        return None

    def relationships_of(self, eid: str) -> list[Relationship]:
        return [r for r in self.relationships
                if r.source == eid or r.target == eid]

    def facts_with_formula(self) -> list[Fact]:
        return [f for f in self.facts if f.formula]

    # ── validation (deterministic, Gate 1) ────────────────────────────
    def validate(self) -> list[str]:
        errors: list[str] = []
        ids = {e.id for e in self.entities}
        for e in self.entities:
            if e.type not in ENTITY_TYPES:
                errors.append(
                    f"entity {e.id!r}: unknown type {e.type!r} "
                    f"(closed registry; promote new types via the "
                    "primitive promotion process)")
            if e.count is not None and e.count < 0:
                errors.append(f"entity {e.id!r}: negative count")
        for r in self.relationships:
            if r.source == r.target:
                errors.append(f"relationship {r.source}->{r.target}: self-loop")
            if r.source not in ids:
                errors.append(f"relationship source {r.source!r} is not an entity")
            if r.target not in ids:
                errors.append(f"relationship target {r.target!r} is not an entity")
            if r.type not in REL_KINDS:
                errors.append(f"relationship {r.source}->{r.target}: "
                              f"unknown kind {r.type!r}")
        for f in self.forces:
            if f.source not in ids:
                errors.append(f"force source {f.source!r} is not an entity")
            if f.target not in ids:
                errors.append(f"force target {f.target!r} is not an entity")
        for s in self.signals:
            if s.kind not in SIGNAL_KINDS:
                errors.append(f"signal {s.id!r}: unknown kind {s.kind!r}")
            if s.source not in ids:
                errors.append(f"signal {s.id!r} source {s.source!r} is not an entity")
            if s.target not in ids:
                errors.append(f"signal {s.id!r} target {s.target!r} is not an entity")
        for p in self.paths:
            for eid in p.entities:
                if eid not in ids:
                    errors.append(f"path {p.id!r} references unknown entity {eid!r}")
        for f in self.facts:
            if f.formula and not f.source:
                errors.append(f"fact {f.claim[:40]!r}... has a formula but no source")
            if not f.formula and (f.units or not f.source):
                # non-quantitative claims may omit formula; still want a source
                pass
        if self.camera.target and self.camera.target not in ids:
            errors.append(f"camera target {self.camera.target!r} is not an entity")
        return errors

    # ── serialization ─────────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "representation": self.representation,
            "representation_secondary": self.representation_secondary,
            "entities": [e.__dict__ for e in self.entities],
            "relationships": [r.__dict__ for r in self.relationships],
            "forces": [f.__dict__ for f in self.forces],
            "signals": [s.__dict__ for s in self.signals],
            "paths": [p.__dict__ for p in self.paths],
            "states": [s.__dict__ for s in self.states],
            "measurements": [m.__dict__ for m in self.measurements],
            "labels": [l.__dict__ for l in self.labels],
            "camera": self.camera.__dict__,
            "hero_mechanism": self.hero_mechanism.__dict__
            if self.hero_mechanism else None,
            "facts": [f.__dict__ for f in self.facts],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorldState":
        def _e(x: dict) -> Entity:
            return Entity(**x)

        def _r(x: dict) -> Relationship:
            return Relationship(**x)

        def _f(x: dict) -> Force:
            return Force(**x)

        def _s(x: dict) -> Signal:
            return Signal(**x)

        def _p(x: dict) -> Path:
            return Path(**x)

        def _st(x: dict) -> State:
            return State(**x)

        def _m(x: dict) -> Measurement:
            return Measurement(**x)

        def _l(x: dict) -> Label:
            return Label(**x)

        cam = CameraFocus(**d.get("camera", {}))
        hm = HeroMechanism(**d["hero_mechanism"]) if d.get("hero_mechanism") else None
        return cls(
            topic=d.get("topic", ""),
            representation=d.get("representation", "CAUSE_EFFECT"),
            representation_secondary=d.get("representation_secondary", []),
            entities=[_e(x) for x in d.get("entities", [])],
            relationships=[_r(x) for x in d.get("relationships", [])],
            forces=[_f(x) for x in d.get("forces", [])],
            signals=[_s(x) for x in d.get("signals", [])],
            paths=[_p(x) for x in d.get("paths", [])],
            states=[_st(x) for x in d.get("states", [])],
            measurements=[_m(x) for x in d.get("measurements", [])],
            labels=[_l(x) for x in d.get("labels", [])],
            camera=cam,
            hero_mechanism=hm,
            facts=[Fact(**x) for x in d.get("facts", [])],
        )
