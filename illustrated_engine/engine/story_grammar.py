"""V8 subject-specific visual grammar packs (engine/story_grammar.py).

NOTE: named `story_grammar` because `engine/grammar.py` is an existing
planv2-era module (build_events) imported by composev2/composev5/planv2/qa2 —
a name collision was caught and fixed 2026-09-06.

A grammar pack declares, per story_type, the visual vocabulary a story in
that domain should speak: expected evidence classes, the state vocabulary
for the visual state machine, anchor requirements (hero recognizability),
and the living-diagram event vocabulary. The planner validates against the
pack; anti-template variation must emerge from grammar, never from random
layout changes (brief §4, §16).
"""

from __future__ import annotations

# States allowed in the visual state machine (brief §1). A shot does not
# need every state; the planner picks by duration, manifest elements and
# beat function.
STATE_VOCAB = ("ESTABLISH", "FOCUS", "TRANSFORM", "CONSEQUENCE", "PAYOFF")

# Living-diagram event kinds (brief §3). number_pop/highlight/pulse exist
# since V7; the rest are new renderer events that mutate the information
# itself rather than move the camera.
EVENT_VOCAB = ("number_pop", "highlight", "pulse",
               "reveal", "isolate", "flow", "fill_state", "consequence")

GRAMMAR = {
    "science": {
        "evidence_classes": ["diagram", "cutaway", "flow", "particle_field",
                             "energy_split", "scale_change", "chart"],
        "state_patterns": {
            "ESTABLISH": "structure/plate with progressive reveal",
            "FOCUS": "isolate the component the beat is about",
            "TRANSFORM": "flow along connectors / fill_state (current, chemistry)",
            "CONSEQUENCE": "effect on the dependent element (heat, failure)",
            "PAYOFF": "key figure or verdict on the split/limit chart",
        },
        "anchors": {"min_labels": 2, "require_named_structure": True},
        "event_vocab": ["reveal", "isolate", "flow", "fill_state",
                        "consequence", "number_pop", "highlight"],
        "camera": "slow push into the mechanism; scale changes allowed",
    },
    "history": {
        "evidence_classes": ["map", "timeline", "event_chain", "document",
                             "portrait", "reconstruction"],
        "state_patterns": {
            "ESTABLISH": "scene/map/timeline with progressive reveal",
            "FOCUS": "isolate the actor/element (ship, compartment, date)",
            "TRANSFORM": "event chain advances (boundary/sequence reveal)",
            "CONSEQUENCE": "cascade propagates (flooding, loss)",
            "PAYOFF": "the resolved count/outcome",
        },
        "anchors": {"min_labels": 2, "require_named_structure": True},
        "event_vocab": ["reveal", "isolate", "flow", "consequence",
                        "number_pop", "highlight"],
        "camera": "drift along the event chain; no decorative zoom",
    },
    "geography": {
        "evidence_classes": ["map", "regional_overlay", "terrain",
                             "atmospheric", "satellite_evidence", "comparison"],
        "state_patterns": {
            "ESTABLISH": "recognizable silhouette with regional overlay",
            "FOCUS": "isolate the band/region the beat is about",
            "TRANSFORM": "fill_state (vegetation/rainfall spread) or boundary_shift",
            "CONSEQUENCE": "comparison state (rim vs core, then vs now)",
            "PAYOFF": "overlay resolves on the silhouette",
        },
        "anchors": {"min_labels": 2, "require_silhouette": True},
        "event_vocab": ["reveal", "isolate", "fill_state", "flow",
                        "consequence", "number_pop", "highlight"],
        "camera": "hold the silhouette readable; overlay, don't crop it out",
    },
    "engineering": {
        "evidence_classes": ["cross_section", "exploded_view", "force_diagram",
                             "stress_propagation", "chart"],
        "state_patterns": {
            "ESTABLISH": "cross-section with progressive reveal",
            "FOCUS": "isolate the loaded component",
            "TRANSFORM": "flow (force path) / fill_state (stress region)",
            "CONSEQUENCE": "failure propagation on the downstream part",
            "PAYOFF": "the limit figure",
        },
        "anchors": {"min_labels": 2, "require_named_structure": True},
        "event_vocab": ["reveal", "isolate", "flow", "fill_state",
                        "consequence", "number_pop"],
        "camera": "track the force path; scale changes allowed",
    },
}

# story_type aliases used across the pipeline
_ALIASES = {
    "science_process": "science", "science_explainer": "science",
    "history_event": "history", "geography_process": "geography",
    "engineering_failure": "engineering",
}

DEFAULT_PACK = {
    "evidence_classes": ["diagram", "map", "chart"],
    "state_patterns": {s: "per beat intent" for s in STATE_VOCAB},
    "anchors": {"min_labels": 2},
    "event_vocab": list(EVENT_VOCAB),
    "camera": "eased; parallax on evidence",
}


def pack_for(story_type: str) -> dict:
    """Return the grammar pack for a story_type (with alias + fallback)."""
    key = _ALIASES.get((story_type or "").strip().lower(),
                       (story_type or "").strip().lower())
    return GRAMMAR.get(key, DEFAULT_PACK)


def grammar_key(story_type: str) -> str:
    key = _ALIASES.get((story_type or "").strip().lower(),
                       (story_type or "").strip().lower())
    return key if key in GRAMMAR else "default"


def validate_states(story_type: str, states: list) -> list:
    """Findings for any state/event outside the pack's vocabulary."""
    pack = pack_for(story_type)
    out = []
    for st in states or []:
        name = str(st.get("name") or "")
        if name and name not in STATE_VOCAB:
            out.append(f"state '{name}' outside STATE_VOCAB")
        for ev in st.get("events") or []:
            if str(ev.get("kind")) not in EVENT_VOCAB:
                out.append(f"event '{ev.get('kind')}' not in EVENT_VOCAB")
    return out


def check_anchors(story_type: str, hero_asset: str, hero_elements: list,
                  plate_bible_note: str = "") -> dict:
    """Hero recognizability (brief §5): the muted first-frame test.

    Structural proxies: enough labeled elements, and for geography a
    silhouette-bearing asset name (recognizable outline is an authoring
    contract enforced here, not an abstract-shape allowance).
    """
    pack = pack_for(story_type)
    req = pack.get("anchors", {})
    labels = [str(e.get("text") or "") for e in (hero_elements or [])
              if len(str(e.get("text") or "").strip()) >= 3]
    findings, ok = [], True
    if len(labels) < int(req.get("min_labels", 2)):
        ok = False
        findings.append(f"hero has {len(labels)} labels < {req.get('min_labels')}")
    asset = (hero_asset or "").lower() + " " + plate_bible_note.lower()
    if req.get("require_silhouette") and not any(
            k in asset for k in ("silhouette", "map", "outline", "africa",
                                 "continent", "shape", "land")):
        ok = False
        findings.append("geography hero lacks a recognizable silhouette anchor")
    if req.get("require_named_structure") and not labels:
        ok = False
        findings.append("hero lacks named-structure labels")
    return {"ok": ok, "anchors": labels[:8], "findings": findings}
