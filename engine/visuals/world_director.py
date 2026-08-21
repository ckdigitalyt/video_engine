"""World Director — autonomous v2 VisualSpec builder (JADE_TO_DO v0.3 §26).

Given ONLY a topic, this module (deterministically, with optional LLM
enhancement) produces the full v2 VisualSpec:

    research -> story template + hero mechanism -> script (narration)
    -> world model -> per-beat visual plan (semantic actions on world
    entities) -> explanation scores -> v2 VisualSpec

No topic-specific hardcoded scene selection: beat plans are derived from
the WORLD MODEL structure (entity types, relationships, signals,
representation), not from topic names.  Topic CONTENT (facts, script
lines) lives in engine.world.knowledge as data.

Beat-planning families are chosen by representation:
  SIGNAL_FLOW            -> pulses through a causal chain (McGurk, brain)
  PHYSICAL_MODEL         -> fall / miss / orbit + vectors (satellite)
  SIMULATION (optics)    -> light source -> scatter (hero) -> observer
                            -> sunset extreme (sky blue)
  MATHEMATICAL_TRANSFORMATION -> proven v1 number visuals (Kaprekar,
                            Collatz) wrapped into v2 with scores
  CAUSE_EFFECT / default -> cause -> effect chain + measure
"""

from __future__ import annotations

import json
from typing import Any, Optional

from engine.world.actions import Action
from engine.world.knowledge import research
from engine.world.representations import RepType, select_representation
from engine.world.scoring import score_beat, score_beatsheet
from engine.world.story_templates import (
    ROLE_INTENTS, hero_for, select_template,
)
from engine.world.world_model import WorldState

# ────────────────────────────────────────────────────────────────────────
# script: role -> narration sentence (generic defaults; topics may carry
# their own script lines in knowledge._KNOWLEDGE["script"])
# ────────────────────────────────────────────────────────────────────────
ROLE_SENTENCES: dict[str, str] = {
    "hook": "What is really going on here?",
    "question": "Let's answer it with one simple experiment.",
    "mystery": "Something strange is happening — watch closely.",
    "simple_experiment": "Here is the setup.",
    "change_variable": "Now change one thing at a time.",
    "observe": "Watch what changes.",
    "push_extreme": "Push it to the extreme.",
    "discover_principle": "A clear rule emerges.",
    "explain_principle": "Here is the principle behind it.",
    "general_rule": "The same rule explains every case.",
    "evidence": "The evidence is right in front of us.",
    "resolution": "Mystery solved.",
    "payoff": "Now you know.",
    "close": "And that is the whole story.",
    "prediction": "What do you predict will happen?",
    "test": "Let's test it.",
    "surprise": "Not what you expected, right?",
    "simple_case": "Start with the simplest case.",
    "extreme_case": "Now take it to an extreme.",
    "problem": "There is a puzzle here.",
    "failure": "The obvious answer fails.",
    "insight": "The insight changes everything.",
    "solution": "The solution is elegant.",
    "demonstration": "Watch the demonstration.",
    "counterintuitive_claim": "This looks impossible — but it is real.",
    "visual_proof": "The proof is visual.",
    "comparison": "Compare the two.",
}


def script_for(topic: str, plan_roles: list[str],
               world: WorldState) -> list[dict]:
    """Build narration lines for the story roles.

    Prefers topic-specific script data (knowledge._KNOWLEDGE['script'],
    a dict of role -> line); falls back to generic role sentences with
    topic/fact injection.  Deterministic; no LLM needed.
    """
    from engine.world.knowledge import _KNOWLEDGE, _resolve_topic
    entry = _KNOWLEDGE.get(_resolve_topic(topic), {})
    topic_script = entry.get("script", {}) or {}
    facts = world.facts
    out: list[dict] = []
    used_fact = 0
    for role in plan_roles:
        line = topic_script.get(role)
        if line is None:
            line = ROLE_SENTENCES.get(role, "")
            line = line.replace("{topic}", topic.strip("? "))
            if role in ("explain_principle", "discover_principle",
                        "general_rule", "evidence", "visual_proof") \
                    and facts and used_fact < len(facts):
                line = facts[used_fact].claim
                used_fact += 1
        if line:
            out.append({"role": role, "narration": line})
    return out


# ────────────────────────────────────────────────────────────────────────
# beat planners per representation family
# ────────────────────────────────────────────────────────────────────────
def _mkbeat(bid: str, role: str, narration: str, duration: float,
            objects: list[dict], actions: list[dict], visual_type: str = "",
            camera: Optional[dict] = None, importance: str = "medium",
            kinetic_words: list[str] | None = None) -> dict:
    intent = ROLE_INTENTS.get(role, "explanation")
    beat = {
        "beat_id": bid, "intent": intent, "role": role,
        "narration": narration, "duration": round(duration, 2),
        "importance": importance,
        "objects": objects, "transformations": [],
        "semantic_actions": actions,
        "visual_type": visual_type,
        "camera": camera or {"type": "static"},
        "kinetic_words": kinetic_words or [],
    }
    scored = score_beat(beat)
    beat["explanation_score"] = scored.level
    beat["text_primary"] = scored.text_primary
    return beat


def _entity_objs(world: WorldState, *ids: str) -> list[dict]:
    out = []
    for eid in ids:
        ent = world.entity(eid)
        if ent is not None:
            out.append({"id": eid, "type": ent.type,
                        "properties": ent.properties})
    return out


def _plan_signal_flow(topic: str, world: WorldState,
                      script: list[dict]) -> list[dict]:
    """Pulses through a causal chain (McGurk/brain/psychology)."""
    beats: list[dict] = []
    bid = [0]
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.4,
                             objects, actions, vtype, camera, imp))
    # find signal sources (ear/eye/mouth), hub (brain), sink (perception)
    sources = [e for e in world.entities
               if e.type in ("ear", "eye", "mouth")]
    hub = next((e for e in world.entities if e.type == "brain"), None)
    sink = next((e for e in world.entities
                 if e.type in ("perception", "reveal", "payoff")), None)

    nxt("hook", script[0]["narration"] if script else "Look at this.",
        [], [{"action": "focus_on", "target": hub.id if hub else ""}],
        "kinetic_title", {"type": "zoom_to", "target": hub.id if hub else ""},
        "high")
    nxt("question", script[1]["narration"] if len(script) > 1 else
        "Two signals, one sound.",
        _entity_objs(world, *[s.id for s in sources]),
        [{"action": "flow", "target": s.id,
          "params": {"nodes": [{"position": [-4, 1.5, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}
         for s in sources] or
        [{"action": "focus_on", "target": ""}],
        camera={"type": "pan"})
    # integration at the hub (merge)
    if hub is not None:
        nxt("observe", script[3]["narration"] if len(script) > 3 else
            "The brain fuses both signals.",
            _entity_objs(world, hub.id),
            [{"action": "merge", "target": hub.id,
              "params": {"from": [[-4, 1.5, 0], [4, 1.5, 0]]}}],
            camera={"type": "zoom_to", "target": hub.id}, imp="high")
    # perception result
    if sink is not None:
        nxt("discover_principle",
            script[5]["narration"] if len(script) > 5 else
            "One integrated perception.",
            _entity_objs(world, sink.id),
            [{"action": "reveal", "target": sink.id,
              "params": {"text": "da"}}],
            "reveal", {"type": "zoom_to", "target": sink.id}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "You hear what you see.",
        [], [], "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_physical(topic: str, world: WorldState,
                   script: list[dict]) -> list[dict]:
    """Fall -> miss -> orbit hero -> vectors -> equation (satellite)."""
    beats: list[dict] = []
    bid = [0]
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.6,
                             objects, actions, vtype, camera, imp))
    earth = next((e for e in world.entities
                  if e.type == "celestial_body"), None)
    body = next((e for e in world.entities
                 if e.type == "moving_body"), None)
    orbit = next((e for e in world.entities
                  if e.type == "orbit_path"), None)
    b = body.id if body else "satellite"
    e = earth.id if earth else "earth"

    nxt("hook", script[0]["narration"] if script else
        "How does it stay up there?",
        _entity_objs(world, e),
        [], "kinetic_title", {"type": "zoom_to", "target": e}, "high")
    nxt("question", script[1]["narration"] if len(script) > 1 else
        "It is falling — and missing.",
        _entity_objs(world, b),
        [{"action": "fall", "target": b,
          "params": {"height": 2.6, "g": 5.0, "land_y": -2.2}}],
        camera={"type": "follow", "target": b})
    nxt("simple_experiment", script[2]["narration"] if len(script) > 2 else
        "Throw it sideways. Faster.",
        _entity_objs(world, b),
        [{"action": "miss", "target": b, "params": {"past": e,
                                                    "offset": 0.7}}],
        camera={"type": "follow", "target": b})
    # hero: orbit generation
    nxt("discover_principle", script[3]["narration"] if len(script) > 3 else
        "It keeps falling, but the ground curves away.",
        _entity_objs(world, e, b),
        [{"action": "orbit", "target": b,
          "params": {"center": e, "radius": 3.2, "laps": 1.2,
                     "vec_len": 1.2}}],
        camera={"type": "follow", "target": b}, imp="high")
    nxt("explain_principle", script[4]["narration"] if len(script) > 4 else
        "Gravity pulls it in; its speed carries it forward.",
        _entity_objs(world, b),
        [{"action": "measure", "target": b,
          "params": {"value": "v = √(GM/r)", "label": "orbital speed"}}],
        "reveal", {"type": "zoom_to", "target": b}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is what an orbit is.",
        [], [], "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_simulation(topic: str, world: WorldState,
                     script: list[dict]) -> list[dict]:
    """Light source -> scatter hero -> observer -> sunset extreme (sky)."""
    beats: list[dict] = []
    bid = [0]
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.8,
                             objects, actions, vtype, camera, imp))
    sun = next((e for e in world.entities
                if e.type == "light_source"), None)
    atm = next((e for e in world.entities if e.type == "medium"), None)
    mol = next((e for e in world.entities
                if e.type == "scatterer"), None)
    eye = next((e for e in world.entities if e.type == "eye"), None)
    s = sun.id if sun else "sun"
    m = mol.id if mol else "molecule"
    o = eye.id if eye else "observer"

    nxt("hook", script[0]["narration"] if script else
        "Why is the sky blue?",
        _entity_objs(world, s),
        [], "kinetic_title", {"type": "zoom_to", "target": s}, "high")
    nxt("question", script[1]["narration"] if len(script) > 1 else
        "White light meets the air.",
        _entity_objs(world, s, atm),
        [{"action": "flow", "target": atm.id,
          "params": {"nodes": [{"position": [-4.5, 0, 0]},
                               {"position": [-1, 0, 0]},
                               {"position": [2.5, 0, 0]}]}}],
        camera={"type": "pan"})
    # HERO: wavelength-dependent scattering (the action owns its molecule)
    nxt("discover_principle", script[3]["narration"] if len(script) > 3 else
        "Shorter wavelengths scatter far more.",
        [],
        [{"action": "scatter", "target": m,
          "params": {"blue_nm": 450.0, "red_nm": 650.0}}],
        camera={"type": "zoom_to", "target": m}, imp="high")
    # observer sees blue from everywhere
    nxt("observe", script[4]["narration"] if len(script) > 4 else
        "Blue reaches your eyes from every direction.",
        _entity_objs(world, m, o),
        [{"action": "flow", "target": o,
          "params": {"nodes": [{"position": [-2, -1, 0]},
                               {"position": [0, 0.5, 0]},
                               {"position": [2, 2.2, 0]}]}},
         {"action": "measure", "target": o,
          "params": {"value": "≈ 4×", "label": "blue vs red"}}],
        camera={"type": "zoom_to", "target": o})
    # sunset: push to extreme (scatter action renders its own molecule)
    nxt("push_extreme", script[5]["narration"] if len(script) > 5 else
        "At sunset, the path through the air grows ~38× longer.",
        _entity_objs(world, s, atm, o),
        [{"action": "scatter", "target": m,
          "params": {"blue_nm": 450.0, "red_nm": 650.0,
                     "label": "long path"}},
         {"action": "measure", "target": o,
          "params": {"value": "~38×", "label": "air path"}}],
        camera={"type": "pull_out"})
    nxt("explain_principle", script[6]["narration"] if len(script) > 6 else
        "Blue is scattered away; red travels on to you.",
        _entity_objs(world, o),
        [{"action": "measure", "target": o,
          "params": {"value": "I ∝ 1/λ⁴", "label": "Rayleigh"}}],
        "reveal", {"type": "zoom_to", "target": o}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is why the sky is blue.",
        [], [], "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_math(topic: str, world: WorldState,
               script: list[dict]) -> list[dict]:
    """Number transformation (Kaprekar/Collatz): wraps the PROVEN v1
    deterministic director output into a v2 spec (spec §1 — never replace
    proven correctness work)."""
    from engine.visuals.visual_director import _direct_deterministic
    narration = " ".join(s["narration"] for s in script) or "Math."
    bs, sl = _direct_deterministic(topic, narration)
    beats = []
    for b in bs["beats"]:
        shot = next((s for s in sl["shots"] if s["beat_id"] == b["beat_id"]),
                    None)
        visual_type = shot["visual_type"] if shot else "highlight"
        objects = shot["objects"] if shot else []
        actions = shot["actions"] if shot else []
        beat = _mkbeat(b["beat_id"], b.get("intent", "explanation"),
                       b["narration"], b["duration"], objects,
                       [dict(a, type=a["type"]) for a in actions
                        if isinstance(a, dict) and a.get("type")],
                       visual_type, shot.get("camera") if shot else None,
                       b.get("importance", "medium"))
        beats.append(beat)
    return beats


def _plan_cause_effect(topic: str, world: WorldState,
                       script: list[dict]) -> list[dict]:
    """Generic: cause -> effect chain + measure + payoff."""
    beats: list[dict] = []
    bid = [0]
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.4,
                             objects, actions, vtype, camera, imp))
    cause = next((e for e in world.entities
                  if e.type == "cause_effect"), None)
    effect = next((e for e in world.entities
                   if e.type == "cause_effect" and e.id != cause.id),
                  None) if cause else None
    nxt("hook", script[0]["narration"] if script else topic,
        [], [], "kinetic_title", {"type": "zoom_to"}, "high")
    nxt("question", script[1]["narration"] if len(script) > 1 else
        "One thing leads to another.",
        _entity_objs(world, *(x.id for x in [cause, effect] if x)),
        [{"action": "flow", "target": "",
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        camera={"type": "pan"})
    nxt("payoff", script[-1]["narration"] if script else
        "Cause, effect, explained.",
        [], [], "payoff", {"type": "pull_out"}, "high")
    return beats


REP_PLANNERS = {
    RepType.SIGNAL_FLOW: _plan_signal_flow,
    RepType.PHYSICAL_MODEL: _plan_physical,
    RepType.SIMULATION: _plan_simulation,
    RepType.MATHEMATICAL_TRANSFORMATION: _plan_math,
    RepType.CAUSE_EFFECT: _plan_cause_effect,
}


# ────────────────────────────────────────────────────────────────────────
# public entry
# ────────────────────────────────────────────────────────────────────────
def build_visualspec(topic: str, world: WorldState,
                     narration_override: str | None = None,
                     story_plan: Any = None,
                     rep_override: str | None = None) -> dict:
    """Build a complete v2 VisualSpec for a topic (deterministic).

    Autonomous path: representation -> story template -> hero -> script
    -> beats -> v2 spec with world + scores.
    """
    rep = select_representation(topic, rep_override)
    plan = story_plan or select_template(topic, rep.primary)
    hero = hero_for(topic, plan, rep.primary)
    if world.hero_mechanism is not None:
        hero = world.hero_mechanism

    # script (narration)
    if narration_override:
        script = [{"role": r, "narration": s}
                  for r, s in zip(plan.roles, narration_override.split("."))
                  if s.strip()]
        if not script:
            script = [{"role": "hook", "narration": narration_override}]
    else:
        script = script_for(topic, plan.roles, world)
        if not script:
            script = [{"role": "hook", "narration": topic},
                      {"role": "payoff", "narration": "That is the story."}]

    # pick the planner for the representation family
    planner = REP_PLANNERS.get(rep.primary, _plan_cause_effect)
    beats = planner(topic, world, script)
    if not beats:
        beats = _plan_cause_effect(topic, world, script)

    # hero beat must carry the world's hero action: ensure the hero beat
    # exists and is marked importance=high
    for b in beats:
        if b["beat_id"] == hero.target_beat:
            b["importance"] = "high"

    vs = {
        "version": "v2",
        "beats": beats,
        "metadata": {
            "topic": topic,
            "representation": rep.primary.value,
            "representation_secondary": [r.value for r in rep.secondary],
            "story_template": plan.template_name,
            "hero_mechanism": hero.__dict__,
            "world": world.to_dict(),
            "facts": [f.__dict__ for f in world.facts],
        },
    }
    report = score_beatsheet(beats, world)
    vs["metadata"]["explanation_report"] = report.to_dict()
    return vs
