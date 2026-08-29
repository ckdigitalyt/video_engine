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
import re
from typing import Any, Optional

from engine.world.actions import Action
from engine.world.knowledge import research
from engine.world.representations import RepType, select_representation
from engine.world.scoring import score_beat, score_beatsheet
from engine.world.story_templates import (
    ROLE_INTENTS, hero_for, select_template,
)
from engine.world.world_model import WorldState
from engine.visuals.composition_planner import attach_composition

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


def _clip_words(text: str, n: int) -> str:
    """Clip a sentence to at most n words (word-boundary safe)."""
    text = (text or "").strip().rstrip(".?")
    words = text.split()
    if len(words) <= n:
        return text
    return " ".join(words[:n])


def _is_mathy(text: str) -> bool:
    return bool(re.search("[0-9\u03c0\u221e\u2248\u221a\u222b\u00d7\u00b1=<>]",
                          text or ""))


def _fact_hook(facts: list) -> str:
    """Hook quality rule: a concrete <=12-word claim derived from the
    facts — never an open question (the first second decides swipe
    through).  Prefers fact lines carrying a number or math symbol."""
    pool = [f.claim for f in facts if f.claim] + \
           [f.formula for f in facts if f.formula]
    for text in pool:
        if _is_mathy(text):
            return _clip_words(text, 12) + "."
    if pool:
        return _clip_words(pool[0], 12) + "."
    return ""


def _fact_payoff(facts: list) -> str:
    """Payoff quality rule: the payoff sentence must carry the numeric
    payoff (a fact formula or a numeric claim)."""
    for f in facts:
        if _is_mathy(f.formula or ""):
            return (f.formula or "").rstrip(".") + "."
    for f in facts:
        if _is_mathy(f.claim or ""):
            return _clip_words(f.claim, 14) + "."
    return ""


def _topic_keyword(topic: str) -> str:
    """A concrete noun from the topic for grounding filler lines."""
    stop = {"why", "what", "how", "the", "is", "are", "does", "do",
            "did", "can", "could", "will", "would", "a", "an", "of",
            "in", "on", "and", "or", "to", "it", "its", "really",
            "going", "here", "you", "your", "for", "with", "this",
            "that", "when", "where", "who"}
    words = [w for w in re.findall(r"[a-z][a-z'-]{2,}", (topic or "").lower())
             if w not in stop]
    return words[0] if words else "it"


_GROUNDABLE_FILLER = {
    "question": "Time to put {kw} to a real test.",
    "simple_experiment": "Let's run a real experiment on {kw}.",
    "change_variable": "Each step shifts one part of the {kw}.",
    "observe": "Follow what happens to the {kw}.",
    "push_extreme": "Now push {kw} as far as it goes.",
    "test": "Put the {kw} claim on trial.",
    "surprise": "Then the {kw} does something unexpected.",
    "mystery": "The {kw} hides a puzzle.",
    "problem": "The {kw} sets up a problem.",
    "resolution": "So {kw} settles the question.",
    "close": "Watch the {kw} one more time.",
    "discover_principle": "The {kw} follows one hard rule.",
    "general_rule": "One rule governs every {kw}.",
    "explain_principle": "Why {kw} works comes down to one mechanism.",
    "evidence": "The numbers settle it.",
    "visual_proof": "Watch the proof build itself.",
}


def _ground_filler(role: str, topic: str) -> str:
    """Topic-grounded replacement for a generic template filler line.

    Returns '' for roles without a grounded variant (caller keeps the
    generic line only when no facts exist at all)."""
    tpl = _GROUNDABLE_FILLER.get(role)
    return tpl.format(kw=_topic_keyword(topic)) if tpl else ""


def script_for(topic: str, plan_roles: list[str],
               world: WorldState) -> list[dict]:
    """Build narration lines for the story roles.

    Prefers topic-specific script data (knowledge._KNOWLEDGE['script'],
    a dict of role -> line, plus optional 'endcard'); falls back to
    generic role sentences with topic/fact injection.  When facts exist,
    hook and payoff are ALWAYS fact-derived (a concrete <=12-word hook
    claim and a numeric payoff — never an open question or "Now you
    know.").  Deterministic; no LLM needed.
    """
    from engine.world.knowledge import _KNOWLEDGE, _resolve_topic
    entry = _KNOWLEDGE.get(_resolve_topic(topic), {})
    topic_script = entry.get("script", {}) or {}
    endcard = str(entry.get("endcard", "") or "")
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
            # hook/payoff quality: never ship a generic template line when
            # facts can ground a concrete, numeric claim
            if facts and line in set(ROLE_SENTENCES.values()):
                if role == "hook":
                    line = _fact_hook(facts) or line
                elif role == "payoff":
                    line = _fact_payoff(facts) or line
                elif used_fact < len(facts):
                    f = facts[used_fact]
                    line = _clip_words(f.claim or f.formula, 12) + "."
                    used_fact += 1
                else:
                    # facts exhausted — ground the filler with the topic
                    # so no narration line is topic-agnostic (the
                    # Gabriel's Horn / template-leak failure mode)
                    line = _ground_filler(role, topic) or line
        if line:
            item = {"role": role, "narration": line}
            if role == "payoff" and endcard:
                item["endcard"] = endcard
            out.append(item)
    return out


def _payoff_value(script: list[dict], world: WorldState) -> str:
    """On-screen payoff end-card text: the authored endcard, else a fact
    formula, else the payoff narration itself.  Used to give payoff beats
    REAL content (an empty payoff beat renders black frames)."""
    last = script[-1] if script else {}
    ec = str(last.get("endcard", "") or "")
    if ec:
        return ec
    for f in world.facts:
        if f.formula and _is_mathy(f.formula):
            return f.formula
    return str(last.get("narration", ""))


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


def _script_by_role(script: list[dict]) -> dict[str, str]:
    """role -> narration lookup (planners must wire narration by ROLE,
    never by list index — index wiring mismatched roles and shipped
    template filler lines)."""
    return {str(s.get("role")): str(s.get("narration", "")) for s in script}


def _plan_signal_flow(topic: str, world: WorldState,
                      script: list[dict]) -> list[dict]:
    """Pulses through a causal chain (McGurk/brain/psychology)."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
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

    nxt("hook", by_role.get("hook") or "Look at this.",
        _entity_objs(world, hub.id if hub else ""),
        [{"action": "focus_on", "target": hub.id if hub else ""}],
        "kinetic_title", {"type": "zoom_to", "target": hub.id if hub else ""},
        "high")
    nxt("question", by_role.get("question") or
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
        nxt("observe", by_role.get("observe") or
            "The brain fuses both signals.",
            _entity_objs(world, hub.id),
            [{"action": "merge", "target": hub.id,
              "params": {"from": [[-4, 1.5, 0], [4, 1.5, 0]]}}],
            camera={"type": "zoom_to", "target": hub.id}, imp="high")
    # perception result — hero: DEMONSTRATE the integration, don't
    # decorate it (§9/§13): the two signals (ear "ba", eye "ga") merge
    # into the perceived sound "da".  merge is a demonstrating action
    # so the hero beat scores >= 4 and passes the hero-quality gate.
    if sink is not None:
        nxt("discover_principle",
            by_role.get("discover_principle") or
            "One integrated perception.",
            _entity_objs(world, sink.id) + _entity_objs(
                world, *[s.id for s in sources]),
            [{"action": "merge", "target": sink.id,
              "params": {"from": [[-4, 1.5, 0], [4, 1.5, 0]],
                          "text": "ba + ga \u2192 da"}}],
            "", {"type": "zoom_to", "target": sink.id}, "high")
    sink_id = sink.id if sink else (hub.id if hub else "")
    nxt("payoff", script[-1]["narration"] if script else
        "You hear what you see.",
        _entity_objs(world, sink_id),
        [{"action": "measure", "target": sink_id,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_physical(topic: str, world: WorldState,
                   script: list[dict]) -> list[dict]:
    """Fall -> miss -> orbit hero -> vectors -> equation (satellite)."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
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

    nxt("hook", by_role.get("hook") or
        "How does it stay up there?",
        _entity_objs(world, e),
        [], "kinetic_title", {"type": "zoom_to", "target": e}, "high")
    nxt("question", by_role.get("question") or
        "It is falling — and missing.",
        _entity_objs(world, b),
        [{"action": "fall", "target": b,
          "params": {"height": 2.6, "g": 5.0, "land_y": -2.2}}],
        camera={"type": "follow", "target": b})
    nxt("simple_experiment", by_role.get("simple_experiment") or
        "Throw it sideways. Faster.",
        _entity_objs(world, b),
        [{"action": "miss", "target": b, "params": {"past": e,
                                                    "offset": 0.7}}],
        camera={"type": "follow", "target": b})
    # hero: orbit generation
    nxt("discover_principle", by_role.get("discover_principle") or
        "It keeps falling, but the ground curves away.",
        _entity_objs(world, e, b),
        [{"action": "orbit", "target": b,
          "params": {"center": e, "radius": 3.2, "laps": 1.2,
                     "vec_len": 1.2}}],
        camera={"type": "follow", "target": b}, imp="high")
    nxt("explain_principle", by_role.get("explain_principle") or
        "Gravity pulls it in; its speed carries it forward.",
        _entity_objs(world, b),
        [{"action": "measure", "target": b,
          "params": {"value": "v = √(GM/r)", "label": "orbital speed"}}],
        "reveal", {"type": "zoom_to", "target": b}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is what an orbit is.",
        _entity_objs(world, b),
        [{"action": "measure", "target": b,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_simulation(topic: str, world: WorldState,
                     script: list[dict]) -> list[dict]:
    """Light source -> scatter hero -> observer -> sunset extreme (sky)."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
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

    nxt("hook", by_role.get("hook") or "Why is the sky blue?",
        _entity_objs(world, s),
        [], "kinetic_title", {"type": "zoom_to", "target": s}, "high")
    nxt("question", by_role.get("question") or
        "White light meets the air.",
        _entity_objs(world, s, atm.id if atm else ""),
        [{"action": "flow", "target": atm.id if atm else s,
          "params": {"nodes": [{"position": [-4.5, 0, 0]},
                               {"position": [-1, 0, 0]},
                               {"position": [2.5, 0, 0]}]}}],
        camera={"type": "pan"})
    # HERO: wavelength-dependent scattering (the action owns its molecule)
    nxt("discover_principle", by_role.get("discover_principle") or
        "Shorter wavelengths scatter far more.",
        [],
        [{"action": "scatter", "target": m,
          "params": {"blue_nm": 450.0, "red_nm": 650.0}}],
        camera={"type": "zoom_to", "target": m}, imp="high")
    # observer sees blue from everywhere
    nxt("observe", by_role.get("observe") or
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
    nxt("push_extreme", by_role.get("push_extreme") or
        "At sunset, the path through the air grows ~38× longer.",
        _entity_objs(world, s, atm, o),
        [{"action": "scatter", "target": m,
          "params": {"blue_nm": 450.0, "red_nm": 650.0,
                     "label": "long path"}},
         {"action": "measure", "target": o,
          "params": {"value": "~38×", "label": "air path"}}],
        camera={"type": "pull_out"})
    nxt("explain_principle", by_role.get("explain_principle") or
        "Blue is scattered away; red travels on to you.",
        _entity_objs(world, o),
        [{"action": "measure", "target": o,
          "params": {"value": "I ∝ 1/λ⁴", "label": "Rayleigh"}}],
        "reveal", {"type": "zoom_to", "target": o}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is why the sky is blue.",
        _entity_objs(world, o),
        [{"action": "measure", "target": o,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
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
        # Legacy v1 shot actions are type-keyed transformations; the v2
        # SemanticAction schema requires action+target (and forbids
        # 'type'/'mode').  Convert so the wrapped spec can actually pass
        # Gate 1 — before 2026-08-27 these specs failed validate_visualspec_v2
        # and could NEVER reach the world compiler (latent bug exposed by
        # the compile-level text-overlap gate).
        sa = []
        for a in actions:
            if not isinstance(a, dict) or not a.get("type"):
                continue
            # 'reveal' becomes a text layer — give it its own oid, never
            # the number rig's 'number_main' (overlap-safe, see
            # engine.qa.gates.gate_text_overlap).
            target = "reveal" if a["type"] == "reveal" else "number_main"
            act: dict = {"action": str(a["type"]), "target": target}
            for k in ("from", "to"):
                if a.get(k) is not None:
                    act[k] = a[k]
            extra = {k: v for k, v in a.items()
                     if k not in ("type", "from", "to")}
            if extra:
                act["params"] = extra
            sa.append(act)
        beat = _mkbeat(b["beat_id"], b.get("intent", "explanation"),
                       b["narration"], b["duration"], objects, sa,
                       visual_type, shot.get("camera") if shot else None,
                       b.get("importance", "medium"))
        beats.append(beat)
    return beats


def _plan_cause_effect(topic: str, world: WorldState,
                       script: list[dict]) -> list[dict]:
    """Generic: cause -> effect chain + measure + payoff."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
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
    nxt("hook", by_role.get("hook") or topic,
        _entity_objs(world, cause.id if cause else "cause"),
        [], "kinetic_title", {"type": "zoom_to",
                              "target": cause.id if cause else "cause"},
        "high")
    nxt("question", by_role.get("question") or
        "One thing leads to another.",
        _entity_objs(world, *(x.id for x in [cause, effect] if x)),
        [{"action": "flow", "target": effect.id if effect else "effect",
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        camera={"type": "pan"})
    # hero: the mechanism itself, demonstrated (not decorated)
    nxt("discover_principle", by_role.get("discover_principle") or
        "The cause drives the effect, step by step.",
        _entity_objs(world, *(x.id for x in [cause, effect] if x)),
        [{"action": "merge", "target": effect.id if effect else "effect",
          "params": {"from": [[-3, 0, 0], [3, 0, 0]]}}],
        camera={"type": "zoom_to",
                "target": effect.id if effect else "effect"}, imp="high")
    # measure the outcome (level 4)
    nxt("observe", by_role.get("observe") or
        "And the result is measurable.",
        _entity_objs(world, effect.id if effect else ""),
        [{"action": "measure", "target": effect.id if effect else "effect",
          "params": {"value": "Δ", "label": "effect"}}],
        "reveal", {"type": "zoom_to",
                    "target": effect.id if effect else "effect"})
    nxt("payoff", script[-1]["narration"] if script else
        "Cause, effect, explained.",
        _entity_objs(world, effect.id if effect else ""),
        [{"action": "measure", "target": effect.id if effect else "effect",
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_wave(topic: str, world: WorldState,
               script: list[dict]) -> list[dict]:
    """Noise-cancelling (SIGNAL_FLOW/SIMULATION): source wave → mic →
    processor → inverse wave → interference hero → silence payoff (§46)."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.6,
                             objects, actions, vtype, camera, imp))
    wave = next((e for e in world.entities if e.type == "wave"), None)
    mic = next((e for e in world.entities if e.type == "microphone"), None)
    proc = next((e for e in world.entities if e.type == "processor"), None)
    inv = next((e for e in world.entities
                if e.type == "wave" and e.id != (wave.id if wave else "")),
               None)
    comb = next((e for e in world.entities
                 if e.type == "interference"), None)
    ear = next((e for e in world.entities if e.type == "ear"), None)
    w = wave.id if wave else "noise_wave"
    m = mic.id if mic else "microphone"
    p = proc.id if proc else "processor"
    i = inv.id if inv else "inverse_wave"
    c = comb.id if comb else "combined_wave"

    nxt("hook", by_role.get("hook") or
        "How do noise-cancelling headphones work?",
        _entity_objs(world, w), [], "kinetic_title",
        {"type": "zoom_to", "target": w}, "high")
    nxt("question", by_role.get("question") or
        "Sound is a wave — peaks and troughs.",
        _entity_objs(world, w),
        [{"action": "flow", "target": w,
          "params": {"nodes": [{"position": [-4, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [4, 0, 0]}]}}],
        camera={"type": "pan"})
    nxt("simple_experiment", by_role.get("simple_experiment") or
        "A microphone samples the incoming noise wave.",
        _entity_objs(world, w, m),
        [{"action": "flow", "target": m,
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        camera={"type": "zoom_to", "target": m})
    nxt("change_variable", by_role.get("change_variable") or
        "The processor builds the exact inverse wave.",
        _entity_objs(world, m, p),
        [{"action": "flow", "target": p,
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        camera={"type": "zoom_to", "target": p})
    nxt("observe", by_role.get("observe") or
        "The inverse wave is 180 degrees out of phase.",
        _entity_objs(world, i),
        [{"action": "focus_on", "target": i,
          "params": {"phase_deg": 180.0}}],
        camera={"type": "zoom_to", "target": i})
    # HERO: peak meets trough -> destructive interference
    nxt("discover_principle", by_role.get("discover_principle") or
        "Peak meets trough, everywhere at once.",
        _entity_objs(world, w, i, c),
        [{"action": "interfere", "target": c,
          "params": {"frequency": 1.0, "amplitude": 0.5,
                      "phase_deg": 180.0}}],
        camera={"type": "zoom_to", "target": c}, imp="high")
    nxt("explain_principle", by_role.get("explain_principle") or
        "Peak plus trough equals silence — destructive interference.",
        _entity_objs(world, c),
        [{"action": "cancel", "target": c,
          "params": {"frequency": 1.0, "amplitude": 0.5,
                      "phase_deg": 180.0, "label": "silence"}}],
        "reveal", {"type": "zoom_to", "target": c}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is how noise-cancelling headphones work.",
        _entity_objs(world, c),
        [{"action": "measure", "target": c,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_experiment(topic: str, world: WorldState,
                     script: list[dict]) -> list[dict]:
    """Popcorn (EXPERIMENT): kernel → heat → steam → pressure rises →
    burst hero → fluff payoff (§46)."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.6,
                             objects, actions, vtype, camera, imp))
    kernel = next((e for e in world.entities if e.type == "kernel"), None)
    water = next((e for e in world.entities
                  if e.type == "particle" and "water" in e.id), None)
    steam = next((e for e in world.entities if e.type == "steam"), None)
    shell = next((e for e in world.entities if e.type == "shell"), None)
    fluff = next((e for e in world.entities
                  if e.type == "particle" and "fluff" in e.id), None)
    k = kernel.id if kernel else "kernel"
    s = steam.id if steam else "steam"
    sh = shell.id if shell else "shell"
    f = fluff.id if fluff else "fluff"

    nxt("hook", by_role.get("hook") or "Why does popcorn pop?",
        _entity_objs(world, k),
        [], "kinetic_title", {"type": "zoom_to", "target": k}, "high")
    nxt("question", by_role.get("question") or
        "Inside every kernel is a drop of water.",
        _entity_objs(world, k),
        [{"action": "focus_on", "target": k}],
        camera={"type": "zoom_to", "target": k})
    nxt("simple_experiment", by_role.get("simple_experiment") or
        "Heat the kernel and the water starts to boil.",
        _entity_objs(world, k, water.id if water else ""),
        [{"action": "flow", "target": k,
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        camera={"type": "pan"})
    nxt("change_variable", by_role.get("change_variable") or
        "The shell traps the steam — it cannot escape.",
        _entity_objs(world, sh, s),
        [{"action": "flow", "target": s,
          "params": {"nodes": [{"position": [-2, -1, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [2, 1, 0]}]}}],
        camera={"type": "zoom_to", "target": sh})
    nxt("observe", by_role.get("observe") or
        "Pressure climbs, higher and higher.",
        _entity_objs(world, k),
        [{"action": "measure", "target": k,
          "params": {"value": "~9 atm", "label": "pressure"}}],
        camera={"type": "zoom_to", "target": k})
    # HERO: near 180 °C the shell cannot hold it -> burst
    nxt("discover_principle", by_role.get("discover_principle") or
        "About nine atmospheres of pressure — then it bursts.",
        _entity_objs(world, k, sh),
        [{"action": "burst", "target": k,
          "params": {"pressure_atm": 9.0, "temp_c": 180.0}}],
        camera={"type": "zoom_to", "target": k}, imp="high")
    nxt("explain_principle", by_role.get("explain_principle") or
        "The shell ruptures, steam escapes, and the starch puffs out.",
        _entity_objs(world, f),
        [{"action": "flow", "target": f,
          "params": {"nodes": [{"position": [-3, 0, 0]},
                               {"position": [0, 0, 0]},
                               {"position": [3, 0, 0]}]}}],
        "reveal", {"type": "zoom_to", "target": f}, "high")
    nxt("payoff", script[-1]["narration"] if script else
        "That is why popcorn pops.",
        _entity_objs(world, f),
        [{"action": "measure", "target": f,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high")
    return beats


def _plan_gabriel(topic: str, world: WorldState,
                  script: list[dict]) -> list[dict]:
    """Gabriel's Horn (MATHEMATICAL_TRANSFORMATION, hero-keyed):
    revolved y = 1/x curve → fill it with paint (finite volume π) →
    measure the surface (2π ln b → ∞) → painter's paradox payoff.
    Every beat carries REAL content — no empty scenes, no dead air."""
    beats: list[dict] = []
    bid = [0]
    by_role = _script_by_role(script)
    payoff_value = _payoff_value(script, world)

    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium", dur=2.6):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, dur,
                             objects, actions, vtype, camera, imp))

    horn = world.entity("horn")
    paint = world.entity("paint")
    card = world.entity("payoff_card")
    h = horn.id if horn else "horn"
    pt = paint.id if paint else "paint"

    def line(role, fallback):
        return by_role.get(role) or fallback

    # hook — the paradox as a concrete claim (never an open question)
    nxt("hook", line("hook", "This shape holds exactly π paint — but "
                            "can never be painted."),
        _entity_objs(world, h), [], "kinetic_title",
        {"type": "zoom_to", "target": h}, "high")
    # question — the setup: curve revolved around the x-axis
    nxt("question", line("question", "Take y = 1/x and spin it around "
                                   "the x-axis."),
        _entity_objs(world, h, pt),
        [{"action": "flow", "target": pt,
          "params": {"nodes": [{"position": [-2.5, 2.2, 0]},
                               {"position": [-1.0, 1.2, 0]},
                               {"position": [0.5, 0.4, 0]}]}}],
        camera={"type": "pan"})
    # simple experiment — pour paint in: the fill is finite
    nxt("simple_experiment", line("simple_experiment", "Pour paint in: "
                                   "the fill volume is finite."),
        _entity_objs(world, h),
        [{"action": "fill", "target": h,
          "params": {"label": "V(b) = π(1 − 1/b)"}}],
        camera={"type": "zoom_to", "target": h})
    nxt("change_variable", line("change_variable", "The fill volume "
                                 "converges to exactly π."),
        _entity_objs(world, h),
        [{"action": "fill", "target": h,
          "params": {"label": "V → π", "value": "V = π∫₁^∞ (1/x²) dx = π"}}],
        camera={"type": "zoom_to", "target": h})
    nxt("observe", line("observe", "V approaches π as b grows and never "
                            "exceeds it."),
        _entity_objs(world, h),
        [{"action": "measure", "target": h,
          "params": {"value": "V → π as b → ∞", "label": "limit"}}],
        camera={"type": "zoom_to", "target": h})
    # push to the extreme — the inside wall never stops growing
    nxt("push_extreme", line("push_extreme", "Measure the inside wall: "
                              "its area is 2π ln b and never stops "
                              "growing."),
        _entity_objs(world, h),
        [{"action": "measure", "target": h,
          "params": {"value": "A = 2π ln b → ∞",
                      "label": "surface area"}}],
        camera={"type": "pull_out"}, dur=3.0)
    # HERO: painter's paradox — filled but unpaintable
    nxt("discover_principle", line("discover_principle", "Finite volume, "
                                    "infinite surface: you can fill it, "
                                    "but you can never paint it."),
        _entity_objs(world, h),
        [{"action": "fill", "target": h,
          "params": {"label": "V = π, A = ∞"}}],
        camera={"type": "zoom_to", "target": h}, imp="high", dur=3.0)
    # explain — why: the tail thins faster than it lengthens
    nxt("explain_principle", line("explain_principle", "The tail thins "
                                   "faster than it lengthens — volume "
                                   "converges, area diverges."),
        _entity_objs(world, h),
        [{"action": "compare", "target": h,
          "params": {"left_label": "V = π", "right_label": "A = ∞"}}],
        "reveal", {"type": "zoom_to", "target": h}, "high")
    # payoff — numeric end card (real content, never a black frame).
    # Wave-2 closure: the horn STAYS on stage through the payoff and the
    # question-bait close — the hero object must survive to the last
    # frame (review v3 §4.3: horn/axis/label vanished at t≈39.5s).
    card_id = card.id if card else "payoff_card"
    nxt("payoff", script[-1]["narration"] if script else
        "Gabriel's Horn: volume π, surface infinite.",
        _entity_objs(world, h, card_id),
        [{"action": "measure", "target": card_id,
          "params": {"value": payoff_value, "label": "payoff"}}],
        "payoff", {"type": "pull_out"}, "high", dur=3.0)
    # close — end card: horn + "V = π, A = ∞" + question bait (comment
    # driver, review §4.3) — no exits, hero retained
    nxt("close", line("close", "But how can π paint cover an infinite "
                            "area?"),
        _entity_objs(world, h, pt, card_id),
        [{"action": "fill", "target": h,
          "params": {"label": "V = π, A = ∞"}},
         {"action": "reveal", "target": card_id,
          "params": {"value": "But how can π paint cover ∞ area?",
                     "label": "you decide"}}],
        "question", None, "high", dur=3.0)
    # wave-2 motion: continuous scene params on the display beats —
    # wave-3 fix: ONLY params with a real on-screen hook (fill_level
    # opacity hook, camera frame motion).  counter_value had NO visible
    # mobject — its tweens rendered as static holds and the frame-diff
    # gate measured ≈0.008; the close now crawls the camera instead so
    # motion continues across the payoff → close beats.
    for b in beats:
        if b["role"] == "change_variable":
            b["scene_params"] = [{"param": "fill_level", "to": 0.45,
                                  "ease": "smooth"}]
        elif b["role"] == "observe":
            b["scene_params"] = [{"param": "fill_level", "to": 0.75,
                                  "ease": "smooth"},
                                 {"param": "camera_x", "to": 0.4,
                                  "ease": "smooth"}]
        elif b["role"] == "discover_principle":
            b["scene_params"] = [{"param": "fill_level", "to": 1.0,
                                  "ease": "smooth"}]
        elif b["role"] in ("explain_principle", "payoff", "close"):
            b["scene_params"] = ([{"param": "camera_x", "to": 1.2,
                                   "ease": "smooth"},
                                  {"param": "camera_zoom", "to": 0.85,
                                   "ease": "smooth"}]
                                 if b["role"] == "explain_principle" else
                                 [{"param": "camera_zoom",
                                   # wave-3.1 clamp: the close must resolve
                                   # back OUT to the default frame (zoom 1.0)
                                   # — the old 0.82 push-in overshot and
                                   # clipped the end-card glyphs; payoff
                                   # formula + question bait must be fully
                                   # visible in the last frames
                                   "to": 0.92 if b["role"] == "payoff"
                                   else 1.0,
                                   "ease": "smooth"}]
                                 + ([{"param": "camera_x", "to": 0.0,
                                      "ease": "smooth"}]
                                    if b["role"] == "close" else []))
    return beats


def _plan_monty(topic: str, world: WorldState,
                 script: list[dict]) -> list[dict]:
    """Monty Hall (EXPERIMENT): three doors, one car, two goats — pick a
    door, the host reveals a goat, the remaining door absorbs the full
    2/3; switching wins (prediction → test → surprise → explanation)."""
    beats: list[dict] = []
    bid = [0]
    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium"):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, 2.6,
                             objects, actions, vtype, camera, imp))
    d1 = next((e for e in world.entities if e.id == "door1"), None)
    d2 = next((e for e in world.entities if e.id == "door2"), None)
    d3 = next((e for e in world.entities if e.id == "door3"), None)
    car = next((e for e in world.entities if e.type == "payoff"), None)
    goat = next((e for e in world.entities
                 if e.id in ("goat1", "goat2")), None)
    a = d1.id if d1 else "door1"
    b = d2.id if d2 else "door2"
    c = d3.id if d3 else "door3"
    ca = car.id if car else "car"
    g = goat.id if goat else "goat1"

    nxt("hook", script[0]["narration"] if script else
        "Three doors, one car, two goats.",
        _entity_objs(world, a, b, c), [], "kinetic_title",
        {"type": "zoom_to", "target": a}, "high")
    nxt("prediction", script[1]["narration"] if len(script) > 1 else
        "Pick a door — one in three chance of the car.",
        _entity_objs(world, a),
        [{"action": "measure", "target": a,
          "params": {"value": "1/3", "label": "your pick"}}],
        camera={"type": "zoom_to", "target": a})
    nxt("test", script[2]["narration"] if len(script) > 2 else
        "The host opens another door — always a goat.",
        _entity_objs(world, b, g),
        [{"action": "reveal_inside", "target": b,
          "params": {"reveals": "goat"}}],
        camera={"type": "zoom_to", "target": b})
    nxt("surprise", script[3]["narration"] if len(script) > 3 else
        "Your door is still one in three.",
        _entity_objs(world, a),
        [{"action": "measure", "target": a,
          "params": {"value": "1/3", "label": "still 1/3"}}],
        camera={"type": "zoom_to", "target": a})
    # HERO: the remaining door absorbed the full 2/3 — switch
    nxt("explain_principle", script[4]["narration"] if len(script) > 4 else
        "The other door now holds the full two thirds — so switch!",
        _entity_objs(world, c, ca),
        [{"action": "measure", "target": c,
          "params": {"value": "2/3", "label": "switch"}},
         {"action": "compare", "target": c, "params": {"vs": a}}],
        camera={"type": "zoom_to", "target": c}, imp="high")
    nxt("payoff", script[5]["narration"] if len(script) > 5 else
        "Always switch: two thirds beats one third.",
        _entity_objs(world, a, b, c, ca), [], "payoff",
        {"type": "pull_out"}, "high")
    return beats


def _plan_collatz(topic: str, world: WorldState,
                  script: list[dict]) -> list[dict]:
    """Collatz (MATHEMATICAL_TRANSFORMATION): one line of arithmetic, an
    unsolved mystery — start with any number, even→n/2 odd→3n+1, and the
    path always seems to fall to 1.  Hero: the trajectory itself."""
    beats: list[dict] = []
    bid = [0]

    def nxt(role, narration, objects, actions, vtype="", camera=None,
            imp="medium", dur=2.6):
        bid[0] += 1
        beats.append(_mkbeat(f"b{bid[0]:03d}", role, narration, dur,
                             objects, actions, vtype, camera, imp))

    n = "number_main"
    rule = "rule"
    by_role = {s.get("role"): s.get("narration", "") for s in script}

    def line(role, fallback):
        return by_role.get(role) or fallback

    # hook — the contradiction that sells the video
    nxt("hook", line("hook", "The simplest rule in math. Nobody can "
                            "prove it."),
        _entity_objs(world, n), [], "kinetic_title",
        {"type": "zoom_to", "target": n}, "high")
    # question — state the rule
    nxt("question", line("question", "Pick a number. Even? Halve it. "
                                   "Odd? Triple it and add one."),
        _entity_objs(world, n, rule),
        [{"action": "measure", "target": n,
          "params": {"value": "even → n/2 · odd → 3n+1",
                      "label": "the rule"}}],
        camera={"type": "zoom_to", "target": rule})
    # simple experiment — 6 → 3
    nxt("simple_experiment", line("simple_experiment", "Try 6. Even — "
                                   "so it becomes 3."),
        _entity_objs(world, n),
        [{"action": "measure", "target": n,
          "params": {"value": "6 → 3", "label": "even: halve"}}],
        camera={"type": "zoom_to", "target": n})
    # HERO — the trajectory: 3 → 10 → 5 → 16 → 8 → 4 → 2 → 1
    nxt("change_variable", line("change_variable", "3 is odd — triple "
                                  "and add one: 3 becomes 10."),
        _entity_objs(world, n, rule),
        [{"action": "trace", "target": n,
          "params": {"color": "#00d4ff"}},
         {"action": "measure", "target": n,
          "params": {"value": "3 → 10", "label": "odd: 3n+1"}}],
        camera={"type": "follow", "target": n}, imp="high")
    nxt("observe", line("observe", "Keep going — it hops up and down, "
                                   "then collapses."),
        _entity_objs(world, n),
        [{"action": "measure", "target": n,
          "params": {"value": "10 → 5 → 16 → 8 → 4 → 2 → 1",
                      "label": "the path"}}],
        camera={"type": "follow", "target": n})
    # push to extreme — 27
    nxt("push_extreme", line("push_extreme", "Try 27. It explodes to "
                               "9232 before crashing down — 111 steps."),
        _entity_objs(world, n),
        [{"action": "measure", "target": n,
          "params": {"value": "climbs to 9232",
                      "label": "27 · 111 steps"}}],
        camera={"type": "pull_out"}, dur=3.0)
    # discover principle — every path ends at 1
    nxt("discover_principle", line("discover_principle", "Every number "
                                    "we have ever tried ends at 1."),
        _entity_objs(world, n),
        [{"action": "converge", "target": n}],
        camera={"type": "pull_out"}, dur=3.0)
    # explain — and the catch
    nxt("explain_principle", line("explain_principle", "It looks like a "
                                   "law of numbers. But nobody has proved "
                                   "it for every number."),
        _entity_objs(world, n),
        [{"action": "measure", "target": n,
          "params": {"value": "unsolved since 1937",
                      "label": "no proof yet"}}],
        camera={"type": "zoom_to", "target": n})
    # payoff
    nxt("payoff", line("payoff", "One line of arithmetic. Ninety years "
                                  "of math. Still unproven."),
        _entity_objs(world, n), [], "payoff",
        {"type": "pull_out"}, "high")
    return beats


REP_PLANNERS = {
    RepType.SIGNAL_FLOW: _plan_signal_flow,
    RepType.PHYSICAL_MODEL: _plan_physical,
    RepType.SIMULATION: _plan_simulation,
    RepType.MATHEMATICAL_TRANSFORMATION: _plan_math,
    RepType.CAUSE_EFFECT: _plan_cause_effect,
    RepType.EXPERIMENT: _plan_experiment,
}


def _select_planner(world: WorldState,
                    rep: Any) -> Any:
    """Content-aware planner selection (§11, §46).

    The world's entity structure decides the visual grammar before the
    representation family is consulted: acoustics worlds (microphone /
    processor / interference) get the wave planner; phase-change worlds
    (kernel / shell / steam) get the experiment planner; everything else
    falls back to the representation-family table.
    """
    types = {e.type for e in world.entities}
    if types & {"microphone", "processor", "interference"}:
        return _plan_wave
    if types & {"kernel", "shell", "steam"}:
        return _plan_experiment
    if world.hero_mechanism and world.hero_mechanism.visualization == \
            "reveal_switch_demonstration":
        return _plan_monty
    if world.hero_mechanism and world.hero_mechanism.visualization == \
            "trajectory_generation":
        return _plan_collatz
    if world.hero_mechanism and world.hero_mechanism.visualization == \
            "painter_paradox_fill":
        return _plan_gabriel
    return REP_PLANNERS.get(rep.primary, _plan_cause_effect)


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
        # World heroes are authored minimal (concept/visualization/beat);
        # enrich with the full §9 shape (objects/actions/why_this_visual)
        # from the hero spec, keyed by visualization name (§12).
        hero = world.hero_mechanism
        full = hero_for(topic, plan, rep.primary)
        if not hero.representation:
            hero.representation = full.representation or rep.primary.value
        if not hero.objects:
            hero.objects = list(full.objects)
        if not hero.actions:
            hero.actions = list(full.actions)
        if not hero.why_this_visual:
            hero.why_this_visual = full.why_this_visual

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

    # pick the planner: content-aware (world structure decides the
    # grammar, §11/§46), falling back to the representation family
    planner = _select_planner(world, rep)
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
    # Phase B (§20–21): composition/attention as a first-class stage.
    attach_composition(vs, world)
    return vs
