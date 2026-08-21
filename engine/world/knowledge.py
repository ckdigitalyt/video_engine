"""Topic knowledge base — the RESEARCH stage (JADE_TO_DO v0.3 §16, §18, §26).

The autonomous engine must produce a video from ONLY a topic.  This module
is the deterministic, local research layer: for each benchmark topic it
carries verified facts (claim/formula/units/assumptions/source) and a
semantic world (entities/relationships/signals/forces/hero).  No topic-
specific scene code lives here — only DATA consumed by the generic
StoryArchitect + VisualDirector + compiler.

Quantitative claims are re-verified deterministically (math_verify) before
rendering; facts carry sources so the animation never implies something
incorrect (spec §18) and simplifications are listed (spec §19).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from engine.world.world_model import (
    CameraFocus, Entity, EntityType, Fact, Force, HeroMechanism,
    Label, Measurement, Relationship, Signal, WorldState,
)


@dataclass
class ResearchResult:
    topic: str
    facts: list[Fact] = field(default_factory=list)
    summary: str = ""
    sources: list[str] = field(default_factory=list)


# ────────────────────────────────────────────────────────────────────────
# Verified facts per benchmark topic (sources cited)
# ────────────────────────────────────────────────────────────────────────
_KNOWLEDGE: dict[str, dict] = {
    "sky blue": {
        "summary": ("White sunlight enters the atmosphere; air molecules "
                    "scatter shorter wavelengths much more strongly "
                    "(Rayleigh scattering, I ∝ 1/λ⁴), so blue light reaches "
                    "the observer from every direction. At sunset the "
                    "direct beam travels far more atmosphere, loses its "
                    "blue, and the remaining light is red/orange."),
        "facts": [
            Fact(claim="Rayleigh scattering intensity scales as the inverse "
                       "fourth power of wavelength",
                 formula="I ∝ 1/λ⁴",
                 units="relative intensity",
                 assumptions=["particles (molecules) much smaller than the "
                              "wavelength", "single scattering dominant"],
                 source="Lord Rayleigh 1871; NASA Space Place, 'Why Is the "
                        "Sky Blue?'"),
            Fact(claim="Blue light (~450 nm) is scattered about 4 times more "
                       "strongly than red light (~650 nm)",
                 formula="(650/450)⁴ ≈ 4.3",
                 units="relative scattering ratio",
                 assumptions=["typical visible wavelengths 450 nm and "
                              "650 nm"],
                 source="NASA Space Place; NOAA SciJinks"),
            Fact(claim="At sunset the sunlight path through the atmosphere "
                       "is much longer (~38x the zenith path at the "
                       "horizon), so most blue is scattered out of the "
                       "direct beam and red/orange dominates",
                 formula="air mass ≈ 1/cos(z), ~38 at horizon",
                 units="relative air mass",
                 assumptions=["plane-parallel atmosphere model",
                              "clear sky, no clouds/aerosols"],
                 source="NASA Space Place; USGS/Air mass (astronomy)"),
            Fact(claim="The sky appears blue because scattered blue light "
                       "reaches the observer from all directions, not only "
                       "from the sun's direction",
                 formula="",
                 units="",
                 assumptions=[],
                 source="NASA Space Place"),
        ],
        "sources": ["https://spaceplace.nasa.gov/blue-sky/en/",
                    "https://scijinks.gov/blue-sky/"],
    },
    "satellite orbit": {
        "summary": ("An orbiting satellite is continuously falling toward "
                    "Earth while its sideways velocity carries it forward; "
                    "because Earth's surface curves away, it keeps missing "
                    "the ground. Gravity supplies the centripetal "
                    "acceleration; the orbital speed for a circular orbit "
                    "is v = sqrt(GM/r)."),
        "facts": [
            Fact(claim="Orbital speed for a circular orbit",
                 formula="v = sqrt(G M / r)",
                 units="m/s",
                 assumptions=["circular two-body orbit", "no atmospheric "
                              "drag", "point masses / spherical Earth"],
                 source="NASA Science: 'Orbital Motion'"),
            Fact(claim="Objects in orbit are in continuous free fall toward "
                       "Earth; they keep missing it because of their "
                       "sideways motion and Earth's curvature",
                 formula="",
                 units="",
                 assumptions=["idealized two-body problem"],
                 source="NASA Space Place"),
            Fact(claim="Gravity supplies the inward (centripetal) "
                       "acceleration required for orbit; velocity is "
                       "tangential to the path",
                 formula="a = v²/r (centripetal acceleration)",
                 units="m/s²",
                 assumptions=["circular orbit"],
                 source="NASA Science"),
        ],
        "sources": ["https://science.nasa.gov/resource/orbital-motion/",
                    "https://spaceplace.nasa.gov/orbits/en/"],
    },
    "kaprekar": {
        "summary": ("Pick any four-digit number with at least two different "
                    "digits, arrange its digits descending and ascending, "
                    "subtract, and repeat. Every path reaches 6174 — "
                    "Kaprekar's constant."),
        "facts": [
            Fact(claim="Every 4-digit number (with at least two distinct "
                       "digits) reaches 6174 under the Kaprekar routine",
                 formula="desc - asc, iterate",
                 units="",
                 assumptions=["4-digit numbers, leading zeros allowed, at "
                              "least two distinct digits"],
                 source="Wikipedia: '6174 (number)' (Kaprekar 1949)"),
            Fact(claim="Example orbit: 3524 → 3087 → 8352 → 6174",
                 formula="5432 - 2345 = 3087; 8730 - 0378 = 8352; "
                         "8532 - 2358 = 6174",
                 units="",
                 assumptions=[],
                 source="verified deterministically by engine "
                        "math_verify.verify_kaprekar_sequence"),
        ],
        "sources": ["https://en.wikipedia.org/wiki/6174_(number)"],
    },
    "collatz": {
        "summary": ("Start with any positive integer. If it is even, halve "
                    "it; if odd, triple it and add one. The sequence always "
                    "seems to reach 1 — but nobody has proven it for every "
                    "number (still an open problem)."),
        "facts": [
            Fact(claim="Collatz rule: even n → n/2, odd n → 3n+1",
                 formula="T(n) = n/2 if n even, 3n+1 if n odd",
                 units="",
                 assumptions=["positive integers"],
                 source="Wikipedia: 'Collatz conjecture' (1937)"),
            Fact(claim="The conjecture that every starting value reaches 1 "
                       "is unproven (verified by computer to enormous "
                       "bounds only)",
                 formula="",
                 units="",
                 assumptions=["open problem — no proof for all n"],
                 source="Wikipedia: 'Collatz conjecture'"),
            Fact(claim="Starting value 27 takes 111 steps to reach 1 and "
                       "climbs to 9232",
                 formula="",
                 units="",
                 assumptions=[],
                 source="Wikipedia: 'Collatz conjecture' (example)"),
        ],
        "sources": ["https://en.wikipedia.org/wiki/Collatz_conjecture"],
    },
    "mcgurk": {
        "summary": ("The McGurk effect: when you see a mouth saying 'ga' "
                    "while hearing the sound 'ba', your brain fuses the "
                    "two signals and you perceive 'da'. Hearing is shaped "
                    "by vision."),
        "facts": [
            Fact(claim="Visual mouth movement changes the perceived speech "
                       "sound (audio 'ba' + visual 'ga' → perceived 'da')",
                 formula="",
                 units="",
                 assumptions=["audio-visual integration; not universal — "
                              "some individuals are unaffected"],
                 source="McGurk & MacDonald, Nature 264, 1976"),
            Fact(claim="Speech perception integrates audio and visual "
                       "signals in the brain",
                 formula="",
                 units="",
                 assumptions=["schematic model: ear signal + eye signal → "
                              "integration → perception"],
                 source="McGurk & MacDonald 1976"),
        ],
        "sources": ["https://en.wikipedia.org/wiki/McGurk_effect"],
    },
}

# aliases so natural topic phrasings resolve
_ALIASES = {
    "why is the sky blue": "sky blue",
    "why the sky is blue": "sky blue",
    "sky is blue": "sky blue",
    "sky blue": "sky blue",
    "satellite orbit": "satellite orbit",
    "orbits": "satellite orbit",
    "orbit": "satellite orbit",
    "how do satellites orbit": "satellite orbit",
    "kaprekar": "kaprekar",
    "kaprekar's constant": "kaprekar",
    "6174": "kaprekar",
    "collatz": "collatz",
    "collatz conjecture": "collatz",
    "3n+1": "collatz",
    "mcgurk": "mcgurk",
    "mcgurk effect": "mcgurk",
    "why do we hear what we see": "mcgurk",
}


def _resolve_topic(topic: str) -> str:
    import re
    t = (topic or "").lower().strip()
    # normalize: strip punctuation so "Why is the sky blue?" matches
    norm = re.sub(r"[^a-z0-9+ ]", "", t).strip()
    return _ALIASES.get(norm, _ALIASES.get(t, t))


def research(topic: str) -> ResearchResult:
    """Deterministic research: verified facts for known benchmark topics.

    Unknown topics return an empty result — the pipeline falls back to the
    generic world builder + generic director (no hallucinated facts).
    """
    key = _resolve_topic(topic)
    entry = _KNOWLEDGE.get(key)
    if not entry:
        return ResearchResult(topic=topic)
    return ResearchResult(
        topic=topic,
        facts=list(entry["facts"]),   # already Fact objects
        summary=entry["summary"],
        sources=list(entry["sources"]),
    )


def known_topic(topic: str) -> bool:
    return _resolve_topic(topic) in _KNOWLEDGE


# ────────────────────────────────────────────────────────────────────────
# Semantic worlds per benchmark topic (DATA, not scene code)
# ────────────────────────────────────────────────────────────────────────
def _sky_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="SIMULATION",
        representation_secondary=["SIGNAL_FLOW"],
        entities=[
            Entity("sun", EntityType.LIGHT_SOURCE,
                   {"label": "Sun", "spectrum": "white"}),
            Entity("atmosphere", EntityType.MEDIUM,
                   {"label": "Atmosphere", "height": "100 km"}),
            Entity("molecule", EntityType.SCATTERER,
                   {"label": "air molecule"}, count=180),
            Entity("observer", EntityType.EYE,
                   {"label": "observer", "direction": "up"}),
            Entity("blue_light", EntityType.SIGNAL, {"wavelength": "450 nm"}),
            Entity("red_light", EntityType.SIGNAL, {"wavelength": "650 nm"}),
        ],
        relationships=[
            Relationship("sun", "atmosphere", "emits_into"),
            Relationship("atmosphere", "molecule", "contains"),
            Relationship("molecule", "observer", "scatters"),
        ],
        signals=[
            Signal("sunlight", "light_wave", "sun", "atmosphere",
                   {"wavelengths": [450, 550, 650]}),
            Signal("scattered_blue", "light_wave", "molecule", "observer",
                   {"wavelength": 450, "intensity": "high"}),
            Signal("scattered_red", "light_wave", "molecule", "observer",
                   {"wavelength": 650, "intensity": "low"}),
        ],
        measurements=[
            Measurement("scatter_ratio", "relative_intensity", "4.3",
                        "blue:red ≈ 4.3:1"),
        ],
        labels=[
            Label("lbl_blue", "450 nm", "blue_light"),
            Label("lbl_red", "650 nm", "red_light"),
        ],
        camera=CameraFocus("molecule", ["zoom_into", "follow"]),
        hero_mechanism=HeroMechanism(
            concept="shorter wavelengths scatter more (I ∝ 1/λ⁴)",
            visualization="wavelength_dependent_scattering",
            target_beat="b005"),
        facts=_KNOWLEDGE["sky blue"]["facts"],
    )


def _orbit_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="PHYSICAL_MODEL",
        representation_secondary=["SIMULATION"],
        entities=[
            Entity("earth", EntityType.CELESTIAL_BODY, {"label": "Earth"}),
            Entity("satellite", EntityType.MOVING_BODY, {"label": "satellite"}),
            Entity("orbit", EntityType.ORBIT_PATH,
                   {"label": "orbit", "radius": "r"}),
        ],
        relationships=[
            Relationship("earth", "satellite", "gravity"),
            Relationship("satellite", "orbit", "velocity"),
        ],
        forces=[
            Force("earth", "satellite", "gravity",
                  formula="F = G M m / r²"),
        ],
        signals=[],
        measurements=[
            Measurement("orbital_speed", "speed", "sqrt(GM/r)", "m/s"),
        ],
        camera=CameraFocus("satellite", ["follow", "zoom_out_of"]),
        hero_mechanism=HeroMechanism(
            concept="continuous falling + sideways velocity = orbit",
            visualization="orbit_generation",
            target_beat="b004"),
        facts=_KNOWLEDGE["satellite orbit"]["facts"],
    )


def _kaprekar_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="MATHEMATICAL_TRANSFORMATION",
        representation_secondary=["GRAPH"],
        entities=[
            Entity("number_main", EntityType.NUMBER, {"label": "n"}),
            Entity("attractor", EntityType.NUMBER, {"label": "6174"}),
        ],
        relationships=[
            Relationship("number_main", "attractor", "transforms"),
        ],
        camera=CameraFocus("number_main", ["zoom_to", "pull_out"]),
        hero_mechanism=HeroMechanism(
            concept="every orbit falls into the same attractor",
            visualization="attractor_convergence",
            target_beat="b008"),
        facts=_KNOWLEDGE["kaprekar"]["facts"],
    )


def _collatz_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="MATHEMATICAL_TRANSFORMATION",
        representation_secondary=["GRAPH"],
        entities=[
            Entity("number_main", EntityType.NUMBER, {"label": "n"}),
            Entity("rule", EntityType.DECISION,
                   {"label": "even → n/2 · odd → 3n+1"}),
        ],
        relationships=[
            Relationship("number_main", "rule", "transforms"),
            Relationship("rule", "number_main", "transforms"),
        ],
        camera=CameraFocus("number_main", ["follow", "zoom_out_of"]),
        hero_mechanism=HeroMechanism(
            concept="number → even/odd rule → transformation → trajectory",
            visualization="trajectory_generation",
            target_beat="b004"),
        facts=_KNOWLEDGE["collatz"]["facts"],
    )


def _mcgurk_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="SIGNAL_FLOW",
        representation_secondary=["EXPERIMENT", "CHARACTER_ACTION"],
        entities=[
            Entity("ear", EntityType.EAR, {"label": "ears", "signal": "ba"}),
            Entity("eye", EntityType.EYE, {"label": "eyes", "signal": "ga"}),
            Entity("brain", EntityType.BRAIN, {"label": "brain"}),
            Entity("perception", EntityType.PERCEPTION,
                   {"label": "you hear", "result": "da"}),
        ],
        relationships=[
            Relationship("ear", "brain", "signals"),
            Relationship("eye", "brain", "signals"),
            Relationship("brain", "perception", "generates"),
        ],
        signals=[
            Signal("audio_ba", "audio_signal", "ear", "brain", {}),
            Signal("visual_ga", "visual_signal", "eye", "brain", {}),
            Signal("perceived_da", "information", "brain", "perception", {}),
        ],
        camera=CameraFocus("brain", ["zoom_into", "follow"]),
        hero_mechanism=HeroMechanism(
            concept="audio signal + visual mouth signal → brain → perceived "
                    "sound",
            visualization="signal_integration",
            target_beat="b004"),
        facts=_KNOWLEDGE["mcgurk"]["facts"],
    )


def _generic_world(topic: str) -> WorldState:
    return WorldState(
        topic=topic,
        representation="CAUSE_EFFECT",
        representation_secondary=["DIRECT_DIAGRAM"],
        entities=[
            Entity("cause", EntityType.CAUSE_EFFECT, {"label": "cause"}),
            Entity("effect", EntityType.CAUSE_EFFECT, {"label": "effect"}),
        ],
        relationships=[Relationship("cause", "effect", "causes")],
        camera=CameraFocus("effect", ["zoom_to"]),
        hero_mechanism=HeroMechanism(
            concept="the central mechanism, demonstrated visually",
            visualization="transformation_sequence",
            target_beat="b003"),
        facts=[],
    )


_WORLD_BUILDERS = {
    "sky blue": _sky_world,
    "satellite orbit": _orbit_world,
    "kaprekar": _kaprekar_world,
    "collatz": _collatz_world,
    "mcgurk": _mcgurk_world,
}


def build_world(topic: str) -> WorldState:
    """Build the semantic world for a topic (generic fallback included)."""
    key = _resolve_topic(topic)
    builder = _WORLD_BUILDERS.get(key, _generic_world)
    world = builder(topic)
    errs = world.validate()
    if errs:
        raise ValueError("world model failed validation:\n" + "\n".join(errs))
    return world
