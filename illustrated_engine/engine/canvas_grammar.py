"""V12 P0 — Story-driven canvas grammar registry (Jade_todo_v12 §P0).

V11's stress test proved three *different* story_types render as one shared
template (cream/gray presentation panel, central info panel, black
annotation chips, navy rails, narration strip).  Story_type packs
(story_grammar.GRAMMAR) vary evidence vocabulary but not CANVAS
ARCHITECTURE — so the architecture never changes.

This registry makes visual grammar story-dependent at the level that
matters: composition type, background treatment, panel usage, chrome
density, caption architecture, transition vocabulary and camera behavior.
Brand (palette/typography) persists; structural interchangeability must
not (directive: "Do NOT force all stories into the same
presentation-panel grammar").

Kits cover the six upcoming stress categories:
  science mechanism      -> mechanism_flow
  biology mechanism      -> scale_descent
  geography phenomenon   -> map_first
  historical event       -> timeline_band
  engineering phenomenon -> cutaway_reveal
  counterintuitive
  everyday science       -> before_after
  climate/earth propagation -> field_propagation

A kit is a PROFILE, not a renderer: the planner (planv9) annotates every
shot with a `canvas` dict consumed by composev5 (chrome/panel seams),
caption_place (authored caption_zone) and the anti-template fingerprint.
Selection is declared (`story.visual_grammars`) or classified from
story_type/subject/keywords — never randomized.
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# Valid PRIMARY information-gain transformations (directive: what the viewer
# SEES change).  Camera moves (zoom/pan/drift), particles, number pops and
# generic highlights are presentation, never primary gain.
VALID_TRANSFORMATIONS = (
    "scale_change",           # macro -> micro / micro -> macro
    "hidden_layer_revealed",  # cutaway / below-surface / interior shown
    "object_transforms",      # the subject itself changes state
    "cause_to_consequence",   # cause and its visible effect in one frame chain
    "geography_expands",      # zoom out to region/planet context
    "geography_contracts",    # planet -> region -> location
    "timeline_advances",      # the band/date moves, consequence follows
    "comparison_resolves",    # A-vs-B resolves into a verdict
    "mechanism_visible",      # internal mechanism becomes visible
    "hypothesis_branches",    # competing explanations split the frame
    "before_after",           # state A -> state B flip
)

# Directive examples of camera-only/decorative change — invalid as PRIMARY.
INVALID_TRANSFORMATIONS = (
    "zoom", "pan", "drift", "particles", "number_pop",
    "generic_highlight", "decorative_sweep",
)

# ---------------------------------------------------------------------------
# Kit fields (all required; planner validates):
#   composition         dominant canvas layout for the kit
#   background          background treatment family
#   panel_usage         "none" (art fills canvas) | "hero_island" (legacy
#                       presentation panel — only when semantically apt)
#   chrome_density      "none" | "minimal" | "rail"  (header/footer chrome)
#   caption_architecture  maps to caption_place zones + styling intent
#   transition_vocab    valid shot-to-shot transitions for this grammar
#   camera              camera doctrine string
#   beat_composition    beat function -> composition variant
#   default_transform   transformation the kit leans on per beat function
#   story_types / subject_keywords  classification hints
#
# caption_architecture values map onto caption_place zones():
#   "edge_band"   -> below_card (art owns the frame, captions at the edge)
#   "top_band"    -> top_band   (map/timeline keeps the lower art clear)
#   "in_scene"    -> below_card, labels live in the art (chips become
#                    part of the composition, caption stays low)

KITS: dict[str, dict] = {
    "mechanism_flow": {
        "covers": "science mechanism",
        "composition": "full_canvas_diagram",
        "background": "edge_to_edge_dark",
        "panel_usage": "none",
        "chrome_density": "minimal",
        "caption_architecture": "edge_band",
        "transition_vocab": ["cut_on_state", "flow_carry"],
        "camera": "track the force/flow path; hold the mechanism readable",
        "beat_composition": {
            "HOOK": "mechanism_mid_action",
            "CURIOSITY": "flow_path_full_bleed",
            "REVEAL": "cutaway_open",
            "EXPLANATION": "flow_path_full_bleed",
            "ESCALATION": "consequence_spread",
            "PAYOFF": "mechanism_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "mechanism_visible",
            "REVEAL": "hidden_layer_revealed",
            "EXPLANATION": "cause_to_consequence",
            "ESCALATION": "cause_to_consequence",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("science_process", "science_explainer"),
        "subject_keywords": ("force", "flow", "heat", "pressure", "circuit",
                             "energy", "wave", "current", "lift", "drag"),
    },
    "scale_descent": {
        "covers": "biology mechanism / macro-to-micro",
        "composition": "vertical_descent",
        "background": "depth_gradient",
        "panel_usage": "none",
        "chrome_density": "none",
        "caption_architecture": "edge_band",
        "transition_vocab": ["scale_dive", "cut_on_state"],
        "camera": "descend through scale layers; each layer a full canvas",
        "beat_composition": {
            "HOOK": "subject_surface_full_bleed",
            "CURIOSITY": "descent_entry",
            "REVEAL": "micro_layer_full_bleed",
            "EXPLANATION": "interface_layer",
            "ESCALATION": "deeper_layer",
            "PAYOFF": "scale_ladder_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "scale_change",
            "REVEAL": "hidden_layer_revealed",
            "EXPLANATION": "mechanism_visible",
            "ESCALATION": "scale_change",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("biology_process",),
        "subject_keywords": ("cell", "molecule", "bacteria", "skin", "tongue",
                             "taste", "dna", "virus", "ice", "crystal",
                             "microscopic", "pigment", "chlorophyll"),
    },
    "map_first": {
        "covers": "geography phenomenon",
        "composition": "map_first",
        "background": "terrain_field",
        "panel_usage": "none",
        "chrome_density": "minimal",
        "caption_architecture": "top_band",
        "transition_vocab": ["map_jump", "cut_on_state"],
        "camera": "hold the geography readable; overlays annotate, never crop",
        "beat_composition": {
            "HOOK": "place_full_bleed",
            "CURIOSITY": "region_zoom",
            "REVEAL": "overlay_reveal",
            "EXPLANATION": "comparison_overlay",
            "ESCALATION": "propagation_spread",
            "PAYOFF": "map_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "geography_contracts",
            "REVEAL": "hidden_layer_revealed",
            "EXPLANATION": "comparison_resolves",
            "ESCALATION": "geography_expands",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("geography_process", "geography_place"),
        "subject_keywords": ("lake", "desert", "ocean", "river", "mountain",
                             "island", "forest", "sea", "ice", "plateau"),
    },
    "timeline_band": {
        "covers": "historical event",
        "composition": "timeline_band",
        "background": "era_field",
        "panel_usage": "none",
        "chrome_density": "none",
        "caption_architecture": "top_band",
        "transition_vocab": ["time_jump", "cut_on_state"],
        "camera": "drift along the event chain; dates anchor the spine",
        "beat_composition": {
            "HOOK": "scene_in_media_res",
            "CURIOSITY": "date_anchor",
            "REVEAL": "event_propagation",
            "EXPLANATION": "cause_chain",
            "ESCALATION": "consequence_cascade",
            "PAYOFF": "aftermath_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "timeline_advances",
            "REVEAL": "cause_to_consequence",
            "EXPLANATION": "cause_to_consequence",
            "ESCALATION": "cause_to_consequence",
            "PAYOFF": "before_after",
        },
        "story_types": ("history_event",),
        "subject_keywords": ("war", "eruption", "empire", "century",
                             "expedition", "voyage", "revolution", "disaster"),
    },
    "cutaway_reveal": {
        "covers": "engineering phenomenon",
        "composition": "layered_cutaway",
        "background": "edge_to_edge_dark",
        "panel_usage": "none",
        "chrome_density": "minimal",
        "caption_architecture": "edge_band",
        "transition_vocab": ["cut_on_state", "reveal_carry"],
        "camera": "hold the object; layers open, the camera does not wander",
        "beat_composition": {
            "HOOK": "object_exterior_full_bleed",
            "CURIOSITY": "skin_of_the_object",
            "REVEAL": "cutaway_open",
            "EXPLANATION": "layer_by_layer",
            "ESCALATION": "failure_propagation",
            "PAYOFF": "cutaway_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "hidden_layer_revealed",
            "REVEAL": "hidden_layer_revealed",
            "EXPLANATION": "mechanism_visible",
            "ESCALATION": "cause_to_consequence",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("engineering_failure",),
        "subject_keywords": ("lock", "gate", "engine", "bridge", "tower",
                             "machine", "turbine", "hull", "wing", "phone",
                             "battery", "cable"),
    },
    "before_after": {
        "covers": "counterintuitive everyday science",
        "composition": "split_before_after",
        "background": "split_field",
        "panel_usage": "none",
        "chrome_density": "none",
        "caption_architecture": "edge_band",
        "transition_vocab": ["flip", "cut_on_state"],
        "camera": "two states, one hinge; the flip IS the information",
        "beat_composition": {
            "HOOK": "state_a_full_bleed",
            "CURIOSITY": "hinge_split",
            "REVEAL": "state_b_full_bleed",
            "EXPLANATION": "split_with_cause",
            "ESCALATION": "split_intensifies",
            "PAYOFF": "states_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "before_after",
            "REVEAL": "before_after",
            "EXPLANATION": "cause_to_consequence",
            "ESCALATION": "before_after",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("everyday_science", "science_process"),
        "subject_keywords": ("honey", "chili", "spice", "sleep", "yawn",
                             "coffee", "phone", "battery", "glasses",
                             "sticky", "slippery", "spin", "dizzy"),
    },
    "field_propagation": {
        "covers": "climate / earth-system propagation",
        "composition": "field_flow",
        "background": "atmosphere_field",
        "panel_usage": "none",
        "chrome_density": "minimal",
        "caption_architecture": "top_band",
        "transition_vocab": ["flow_carry", "map_jump"],
        "camera": "the field moves, the frame holds",
        "beat_composition": {
            "HOOK": "field_in_motion",
            "CURIOSITY": "source_isolate",
            "REVEAL": "propagation_field",
            "EXPLANATION": "layer_interaction",
            "ESCALATION": "global_spread",
            "PAYOFF": "field_resolved",
        },
        "default_transform": {
            "HOOK": "object_transforms",
            "CURIOSITY": "hidden_layer_revealed",
            "REVEAL": "cause_to_consequence",
            "EXPLANATION": "mechanism_visible",
            "ESCALATION": "geography_expands",
            "PAYOFF": "comparison_resolves",
        },
        "story_types": ("climate_process",),
        "subject_keywords": ("climate", "monsoon", "volcano", "ash", "storm",
                             "atmosphere", "temperature", "current", "el nino"),
    },
}

DEFAULT_KIT = "mechanism_flow"

# The universal presentation architecture that V11 actually rendered for
# every story regardless of grammar (verified on the autumn_red /
# tambora_1816 / baikal_deep frames).  planv9 REMOVES this default: a plan
# only carries these values when its planner never assigned a grammar
# (pre-V12 legacy plans).  Declared here once so the anti-template
# fingerprint can compare legacy plans as what they are — the shared
# template — instead of comparing empty fields.
LEGACY_DEFAULT = {
    "grammar": "universal_presentation_panel",
    "composition": "central_horizontal_panel",
    "background": "grid_paper",
    "panel_usage": "hero_island",
    "chrome_density": "rail",
    "caption_architecture": "edge_band",
}

# Rotation order used by the planner's regeneration loop: when the
# cross-video template test flags the plan, the next kit for this story is
# the next declared grammar that has not been tried (directive: regenerate
# with a DIFFERENT valid story-specific grammar, bounded).

# ---------------------------------------------------------------------------
# Classification

_KW_CACHE: dict[str, list] = {}


def _keywords_for(kit_id: str) -> list:
    if kit_id not in _KW_CACHE:
        _KW_CACHE[kit_id] = [w for w in KITS[kit_id]["subject_keywords"]]
    return _KW_CACHE[kit_id]


def classify_story(story: dict, visual_plan: dict | None = None) -> list:
    """Ordered kit candidates for a story: declared wins, then classified.

    Declaration (backward compatible): `story.visual_grammars: ["map_first"]`
    or the legacy singular `story.visual_grammar`.  Classification scores
    story_type (strong) + subject/beat-text keywords (weak).  Deterministic.
    """
    declared = story.get("visual_grammars") or []
    if isinstance(declared, str):
        declared = [declared]
    declared = [str(g).strip() for g in declared if str(g).strip()]
    declared = [g for g in declared if g in KITS]
    if declared:
        return declared

    stype = str(story.get("story_type") or "")
    text = " ".join([
        str(story.get("subject") or ""), str(story.get("title") or ""),
        str(story.get("subject_domain") or ""),
    ])
    for b in (story.get("beats") or []):
        text += " " + str(b.get("narration") or "") + " " + str(b.get("claim") or "")
    text_l = text.lower()

    scores: dict[str, float] = {}
    for kid, kit in KITS.items():
        s = 0.0
        if stype in kit["story_types"]:
            s += 3.0
        for w in _keywords_for(kid):
            if re.search(rf"\b{re.escape(w)}", text_l):
                s += 1.0
        if s:
            scores[kid] = s
    # The story_type default pack keeps a floor so a bare story_type still
    # selects deterministically even with no keyword overlap.
    for kid, kit in KITS.items():
        if stype in kit["story_types"]:
            scores.setdefault(kid, 1.0)
    ranked = [k for k, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]
    return ranked or [DEFAULT_KIT]


# ---------------------------------------------------------------------------
# Per-shot canvas architecture


def beat_function_of(shot: dict, beats: dict) -> str:
    return str((beats.get(str(shot.get("beat_id"))) or {}).get("function") or "")


def shot_canvas(shot: dict, beat: dict, kit_id: str) -> dict:
    """The `canvas` dict for one shot: the grammar's architecture profile,
    varied by beat function (composition variants) — never randomized."""
    kit = KITS[kit_id]
    fn = str(beat.get("function") or "").upper()
    comp = kit["beat_composition"].get(fn, kit["composition"])
    transform = kit["default_transform"].get(fn, "cause_to_consequence")
    # A beat may override its transformation explicitly (story schema:
    # beat.transformation).  Validated by planv9 against VALID/INVALID.
    declared_t = str(beat.get("transformation") or "").strip()
    if declared_t:
        transform = declared_t
    canvas = {
        "grammar": kit_id,
        "composition": comp,
        "background": kit["background"],
        "panel_usage": kit["panel_usage"],
        "chrome_density": kit["chrome_density"],
        "caption_architecture": kit["caption_architecture"],
        "transition": _transition_for(shot, kit),
        "primary_transformation": transform,
        "beat_function": fn,
    }
    if kit["caption_architecture"] == "edge_band":
        canvas["caption_zone"] = "below_card"
    elif kit["caption_architecture"] == "top_band":
        canvas["caption_zone"] = "top_band"
    return canvas


def _transition_for(shot: dict, kit: dict) -> str:
    vocab = kit["transition_vocab"]
    cur = str(shot.get("transition_in") or "").strip()
    if cur and cur in vocab:
        return cur
    # First shot never opens on a fade/black (hook engine: no unnecessary
    # black/fade at 0.5s) — the kit's opener carries the subject immediately.
    if shot.get("opening"):
        return "cut_on_state" if "cut_on_state" in vocab else vocab[0]
    return vocab[0]


def transition_vocab(kit_id: str) -> tuple:
    return tuple(KITS[kit_id]["transition_vocab"])


def kit_covers(kit_id: str) -> str:
    return str(KITS.get(kit_id, {}).get("covers", ""))


def validate() -> list:
    """Registry self-check: every kit declares all required fields, every
    default_transform is a VALID transformation, and the six stress
    categories are covered."""
    problems = []
    required = ("covers", "composition", "background", "panel_usage",
                "chrome_density", "caption_architecture", "transition_vocab",
                "camera", "beat_composition", "default_transform")
    covered = set()
    for kid, kit in KITS.items():
        for f in required:
            if f not in kit:
                problems.append(f"{kid}: missing field {f}")
        for fn, t in (kit.get("default_transform") or {}).items():
            if t not in VALID_TRANSFORMATIONS:
                problems.append(f"{kid}: default_transform {fn}={t} not valid")
        covered.add(str(kit.get("covers", "")).lower())
    for cat in ("science mechanism", "biology", "geography", "historical",
                "engineering", "counterintuitive"):
        if not any(cat in c for c in covered):
            problems.append(f"no kit covers stress category '{cat}'")
    return problems
