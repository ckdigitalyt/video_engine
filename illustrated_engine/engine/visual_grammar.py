"""V6 subject-specific visual grammar resolver.

Brief P1:
  Maintain global identity (palette / typography / grain / graphic language /
  caption language) but allow the INTERNAL visual grammar to depend on the
  subject. Examples:
    AIRCRAFT   -> engineering blueprint / structural diagram / cutaway
    BIOLOGY    -> macro detail / cellular diagram / molecular process
    GEOLOGY    -> map / climate reconstruction / geographic transformation
    SPACE      -> astronomical scale / orbital diagram / dark cinematic imagery
    HISTORY    -> timeline / archival illustration / map transformation

  And before generating a decorative cinematic plate, ask: can this fact be
  communicated more powerfully through comparison / transformation / scale /
  timeline / map / cutaway / before-after / process diagram / cause-effect /
  animation of a physical relationship?

This module is a pure resolver: given (subject, beat, shot), return the
recommended visual mode and grammar. It is NOT a renderer — diagrams_v4 etc.
already know how to draw the modes; this module picks which to use.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Subject -> default grammar hint (a tuple of mode preferences)
SUBJECT_GRAMMAR = {
    "aircraft":   ("BLUEPRINT", "STRUCTURAL_DIAGRAM", "CUTAWAY", "SCALE"),
    "aviation":   ("BLUEPRINT", "STRUCTURAL_DIAGRAM", "SCALE", "TIMELINE"),
    "biology":    ("MACRO_DETAIL", "CELLULAR_DIAGRAM", "MOLECULAR_PROCESS", "SCALE"),
    "geology":    ("MAP", "GEOGRAPHIC_TRANSFORMATION", "TIMELINE", "CLIMATE_RECON"),
    "space":      ("ASTRONOMICAL_SCALE", "ORBITAL_DIAGRAM", "DARK_CINEMATIC", "SCALE"),
    "history":    ("TIMELINE", "ARCHIVAL_ILLUSTRATION", "MAP_TRANSFORMATION", "COMPARISON"),
    "physics":    ("FORCE_DIAGRAM", "SCALE", "TRANSFORMATION", "ANIMATION"),
    "ocean":      ("CROSS_SECTION", "SCALE", "MAP", "CUTAWAY"),
    "climate":    ("MAP", "TIMELINE", "COMPARISON", "CLIMATE_RECON"),
    "engineering":("BLUEPRINT", "STRUCTURAL_DIAGRAM", "CUTAWAY", "COMPARISON"),
    "technology": ("DIAGRAM", "TRANSFORMATION", "SCALE", "COMPARISON"),
    "biology_medicine": ("MACRO_DETAIL", "CELLULAR_DIAGRAM", "COMPARISON"),
    # V11 P1 §3 — brand ≠ visual vocabulary: topic grammars from the V11
    # directive. GEOGRAPHY = real geographic silhouettes / terrain /
    # regional overlays; ASTRONOMY = spatial scale / orbits / spacetime /
    # light cones (alias of space).
    "geography":  ("MAP", "GEOGRAPHIC_TRANSFORMATION", "CLIMATE_RECON", "SCALE"),
    "astronomy":  ("ASTRONOMICAL_SCALE", "ORBITAL_DIAGRAM", "DARK_CINEMATIC", "SCALE"),
    "materials":  ("CUTAWAY", "MACRO_DETAIL", "MOLECULAR_PROCESS", "SCALE"),
}

# Words that hint at the subject (used when the story doesn't declare a
# subject tag explicitly)
SUBJECT_HINTS = [
    ("aircraft",   ("aircraft", "plane", "jet", "airplane", "wing", "karman", "boeing", "airbus", "747", "rocket", "shuttle")),
    ("aviation",   ("aviation", "airline", "pilot", "cockpit", "airport", "altitude", "atmosphere")),
    ("biology",    ("cell", "organism", "species", "dna", "gene", "protein", "virus", "bacteria", "neuron", "brain", "anatomy")),
    ("geology",    ("sahara", "desert", "continent", "plate", "volcano", "rock", "tectonic", "fossil", "glacier")),
    ("space",      ("space", "orbit", "karman", "satellite", "iss", "station", "astronaut", "moon", "mars", "rocket", "atmosphere")),
    ("history",    ("history", "ancient", "century", "empire", "war", "civilization", "dynasty", "archaeolog")),
    ("physics",    ("force", "energy", "mass", "velocity", "acceleration", "gravity", "relativity", "quantum")),
    ("ocean",      ("ocean", "sea", "wave", "current", "tide", "marine", "reef", "deep")),
    ("climate",    ("climate", "weather", "temperature", "greenhouse", "ice age", "rainfall", "monsoon")),
    ("engineering",("engineer", "blueprint", "structure", "design", "schematic", "mechanism")),
    ("technology", ("computer", "chip", "circuit", "ai", "neural", "software", "robot", "processor")),
    # V11 P1 §3 — geography / astronomy hint words
    ("geography",  ("geography", "terrain", "continent", "region", "river", "delta", "coastline", "peninsula", "border", "silhouette", "landscape", "island")),
    ("astronomy",  ("astronomy", "galaxy", "nebula", "spacetime", "black hole", "light cone", "cosmic", "star", "supernova")),
]


# ------------------------------------------------------------------ #
# V13B M2 — story-domain model (docs/directives/
# JADE_V13B_STORY_SPECIFIC_VISUAL_GRAMMAR.md P0 STORY-SPECIFIC VISUAL
# GRAMMAR).  Before choosing compositions the planner classifies the STORY
# into one of seven deterministic domains.  Each domain carries:
#   compositions  ordered preference list — world classes first, "panel"
#                 last and only for justified data/list/comparison beats
#   overlays      semantic overlay vocabulary (evidence, never decoration)
#   accent        per-domain accent guidance; non-general domains NEVER
#                 default to the RUST/orange house accent
#   keywords      weighted keyword model (prefix match, canvas_grammar
#                 semantics) consumed by detect_domain
# Deterministic throughout: no randomness, no per-story hacks.

STORY_DOMAINS: dict[str, dict] = {
    "biology": {
        "covers": "organisms, cells, medicine, living-scale dives",
        "compositions": ("macro_world", "cutaway", "process_zoom", "panel"),
        "overlays": ("scale_bar", "structure_label", "membrane_callout",
                     "process_arrow", "magnitude_compare"),
        "accent": {"name": "deep_teal_olive", "rgb": (23, 92, 84),
                   "secondary_rgb": (98, 108, 52),
                   "note": "deep teal primary, olive secondary; never "
                           "RUST/orange"},
        "keywords": {
            "cell": 3, "cellular": 3, "organism": 3, "dna": 3,
            "mitochondr": 3, "organelle": 3, "membrane": 3, "nucleus": 3,
            "bacteria": 3, "virus": 3, "gene": 3, "protein": 2,
            "tissue": 2, "neuron": 3, "brain": 2, "micrometer": 2,
            "micron": 2, "microscopic": 2, "microscope": 2, "immune": 3,
            "enzyme": 3, "blood": 2, "anatomy": 2, "species": 2,
            "biology": 3, "chlorophyll": 3, "cristae": 3, "skin": 1,
            "hair": 1, "medicine": 2, "medical": 2,
        },
    },
    "physics_mechanism": {
        "covers": "physical objects in contact, forces, material response",
        "compositions": ("object_contact", "force_deformation",
                         "macro_reveal", "panel"),
        "overlays": ("force_arrow", "contact_point", "friction_vector",
                     "state_label", "cause_chain"),
        "accent": {"name": "cool_slate", "rgb": (74, 90, 110),
                   "secondary_rgb": (110, 124, 138),
                   "note": "cool slate blue-grey; never RUST/orange"},
        "keywords": {
            "force": 3, "pressure": 3, "friction": 3, "gravity": 3,
            "velocity": 2, "acceleration": 3, "momentum": 3, "ice": 3,
            "frozen": 3, "freeze": 3, "melt": 3, "crystal": 3,
            "lattice": 3, "molecule": 2, "bond": 2, "quantum": 3,
            "relativity": 3, "mass": 2, "energy": 2, "physics": 3,
            "glide": 2, "slide": 2, "slip": 2, "surface": 2,
            "lubricant": 3, "blade": 2, "skate": 2, "nanometer": 2,
            "liquid film": 3, "heat": 2, "wave": 2, "field": 1,
            "materials": 2, "solid": 2,
        },
    },
    "geography_environment": {
        "covers": "landscapes, climate, terrain, environmental phenomena",
        "compositions": ("landscape", "map", "atmosphere_reconstruction",
                         "panel"),
        "overlays": ("region_label", "climate_band", "wind_arrow",
                     "elevation_tint", "flow_path"),
        "accent": {"name": "sky_terrain", "rgb": (70, 118, 128),
                   "secondary_rgb": (128, 118, 84),
                   "note": "desaturated sky blue over terrain ochre; never "
                           "RUST/orange"},
        "keywords": {
            "desert": 3, "oasis": 3, "fog": 3, "climate": 3, "terrain": 3,
            "coast": 3, "ocean": 2, "sea": 2, "lake": 2, "river": 3,
            "mountain": 2, "valley": 3, "erosion": 3, "atmosphere": 2,
            "weather": 3, "monsoon": 3, "glacier": 3, "plateau": 3,
            "island": 2, "rain": 2, "rainfall": 3, "drought": 3,
            "region": 2, "continent": 3, "geography": 3, "geology": 3,
            "landscape": 3, "wind": 2, "humidity": 3, "vegetation": 3,
            "green": 1,
        },
    },
    "history": {
        "covers": "events, places and consequences reconstructed in time",
        "compositions": ("place_reconstruction", "map", "timeline",
                         "before_after", "panel"),
        "overlays": ("date_marker", "site_label", "route_line",
                     "before_after_pair", "impact_radius"),
        "accent": {"name": "sepia_ink", "rgb": (112, 84, 48),
                   "secondary_rgb": (46, 42, 38),
                   "note": "sepia brown with ink black; never RUST/orange"},
        "keywords": {
            "history": 3, "ancient": 3, "century": 3, "empire": 3,
            "war": 3, "civilization": 3, "dynasty": 3, "archaeolog": 3,
            "expedition": 3, "voyage": 3, "revolution": 3, "ruins": 3,
            "witness": 2, "event": 1, "explosion": 2, "eruption": 2,
            "battle": 3, "treaty": 3, "king": 2, "year": 1,
            "years ago": 3, "disaster": 2, "aftermath": 3,
        },
    },
    "engineering": {
        "covers": "machines, structures, load paths, failure and consequence",
        "compositions": ("machine_cutaway", "load_path", "exploded",
                         "deformation", "panel"),
        "overlays": ("load_path_line", "material_callout", "measurement",
                     "failure_point", "section_label"),
        "accent": {"name": "steel_graphite_warm", "rgb": (58, 62, 68),
                   "secondary_rgb": (184, 106, 64),
                   "note": "graphite/steel primary with ONE warm signal "
                           "secondary, not a global orange identity"},
        "keywords": {
            "engineer": 3, "blueprint": 3, "structure": 2, "machine": 3,
            "engine": 3, "turbine": 3, "bridge": 3, "tower": 2,
            "crumple": 3, "crash": 3, "chassis": 3, "steel": 2,
            "load": 3, "stress": 3, "deform": 3, "collapse": 3,
            "failure": 2, "battery": 2, "cable": 2, "gate": 2,
            "lock": 2, "wing": 2, "aircraft": 2, "plane": 2,
            "hull": 3, "schematic": 3, "mechanism": 2, "component": 2,
            "assembly": 2, "weld": 3, "safety": 2,
        },
    },
    "everyday_science": {
        "covers": "counterintuitive everyday objects and interactions",
        "compositions": ("real_object", "interaction", "macro_zoom",
                         "mechanism_reveal", "panel"),
        "overlays": ("object_label", "state_change", "temperature_tag",
                     "cause_arrow", "result_tag"),
        "accent": {"name": "warm_neutral", "rgb": (146, 116, 90),
                   "secondary_rgb": (96, 88, 78),
                   "note": "warm neutral umber — keeps the household "
                           "register without the orange house accent"},
        "keywords": {
            "kitchen": 3, "microwave": 3, "coffee": 3, "honey": 3,
            "chili": 3, "spice": 3, "sleep": 3, "yawn": 3, "phone": 2,
            "toast": 3, "boil": 3, "everyday": 3, "daily": 2,
            "sticky": 2, "slippery": 2, "household": 3, "cup": 2,
            "shower": 3, "brush": 2, "soap": 3, "refrigerator": 3,
        },
    },
    "general": {
        "covers": "no dominant domain signal — world-first still applies",
        "compositions": ("real_object", "mechanism_reveal", "macro_zoom",
                         "panel"),
        "overlays": ("object_label", "cause_arrow", "measurement",
                     "state_label"),
        "accent": {"name": "brand_default", "rgb": None,
                   "secondary_rgb": None,
                   "note": "no domain opinion — the visual bible accent "
                           "applies (general may keep brand RUST)"},
        "keywords": {},
    },
}

# Legacy story.subject values map onto domains with a strong, deterministic
# bonus (the authored subject is the clearest single signal).
_SUBJECT_DOMAIN_ALIASES = {
    "biology": "biology", "medicine": "biology", "biology_medicine": "biology",
    "physics": "physics_mechanism", "mechanism": "physics_mechanism",
    "materials": "physics_mechanism", "space": "physics_mechanism",
    "astronomy": "physics_mechanism",
    "geography": "geography_environment", "geology": "geography_environment",
    "climate": "geography_environment", "ocean": "geography_environment",
    "history": "history",
    "engineering": "engineering", "engineering_failure": "engineering",
    "aviation": "engineering", "technology": "engineering",
    "everyday": "everyday_science", "everyday_science": "everyday_science",
}

# story_meta fields scanned with their weights; title/subject are the
# double-weight fields per the M2 task spec.
_DOMAIN_FIELD_WEIGHTS = (
    ("title", 2.0), ("subject", 2.0),
    ("topic", 2.0), ("subject_domain", 2.0),
    ("story_type", 1.0),
)

# Subject-alias bonus (strong but not absolute — narration can outvote it
# only by a wide margin, which is the desired behavior).
_SUBJECT_ALIAS_BONUS = 6.0


def _domain_scan(text: str, weight: float, source: str,
                 scores: dict, evidence: list) -> None:
    """Accumulate deterministic keyword scores for one text blob."""
    t = str(text or "").lower()
    if not t:
        return
    for domain, spec in STORY_DOMAINS.items():
        for kw, w in (spec.get("keywords") or {}).items():
            if re.search(rf"\b{re.escape(kw)}", t):
                scores[domain] += float(w) * weight
                evidence.append({"source": source, "domain": domain,
                                 "keyword": kw, "weight": float(w) * weight})


def detect_domain(story_meta: dict, narration_lines=None) -> dict:
    """V13B M2 — classify the story into a STORY_DOMAIN deterministically.

    Weighted keyword scoring: story_meta fields (title/subject double
    weight) plus one pass over the narration lines (single weight).  An
    explicit legacy subject alias adds a strong fixed bonus.  Returns
    {"domain", "confidence", "evidence"} — no randomness; ties resolve by
    STORY_DOMAINS declaration order; zero signal falls back to "general".
    """
    meta = story_meta or {}
    scores = {d: 0.0 for d in STORY_DOMAINS}
    evidence: list = []
    for field, weight in _DOMAIN_FIELD_WEIGHTS:
        _domain_scan(meta.get(field), weight, field, scores, evidence)
    subj = str(meta.get("subject") or "").strip().lower()
    alias = _SUBJECT_DOMAIN_ALIASES.get(subj)
    if alias:
        scores[alias] += _SUBJECT_ALIAS_BONUS
        evidence.append({"source": "subject-alias", "domain": alias,
                         "keyword": subj,
                         "weight": _SUBJECT_ALIAS_BONUS})
    for line in narration_lines or []:
        _domain_scan(line, 1.0, "narration", scores, evidence)
    ranked = sorted(STORY_DOMAINS,
                    key=lambda d: (-scores[d], list(STORY_DOMAINS).index(d)))
    top, second = ranked[0], ranked[1]
    domain = top if scores[top] > 0 else "general"
    denom = scores[top] + scores[second]
    confidence = round(scores[top] / denom, 3) if denom > 0 else 0.0
    evidence.sort(key=lambda e: (-e["weight"], list(STORY_DOMAINS).index(
        e["domain"]), e["source"], e["keyword"]))
    return {"domain": domain, "confidence": confidence,
            "evidence": evidence[:8],
            "scores": {d: round(scores[d], 2) for d in ranked
                       if scores[d] > 0}}


def domain_spec(domain: str) -> dict:
    """The STORY_DOMAINS record for a domain (general-safe)."""
    return STORY_DOMAINS.get(str(domain or "").strip().lower(),
                             STORY_DOMAINS["general"])


def compositions_for(domain: str) -> tuple:
    """Ordered composition preference list for a domain (panel last)."""
    return domain_spec(domain)["compositions"]


def overlays_for(domain: str) -> tuple:
    """Semantic overlay vocabulary for a domain."""
    return domain_spec(domain)["overlays"]


def accent_for(domain: str) -> dict:
    """Per-domain accent guidance dict (rgb None = brand default applies)."""
    return dict(domain_spec(domain)["accent"])


def is_general(domain: str) -> bool:
    return str(domain or "").strip().lower() == "general"


def detect_subject(story: dict, visual_plan: dict = None) -> str:
    """Best-effort subject classification from story text + tags."""
    # 1) explicit tag wins
    for k in ("subject", "topic", "domain"):
        v = story.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip().lower()
    # 2) aggregate text from beats + visual_plan
    text_parts = []
    for b in story.get("beats", []):
        text_parts.append(b.get("narration", ""))
        text_parts.append(b.get("text", ""))
    if visual_plan:
        for b in visual_plan.get("beats", []):
            for s in b.get("shots", []):
                text_parts.append(s.get("purpose", ""))
                text_parts.append(s.get("evidence", ""))
    blob = " ".join(text_parts).lower()
    for subj, words in SUBJECT_HINTS:
        if any(re.search(rf"\b{re.escape(w)}\b", blob) for w in words):
            return subj
    return "general"


# Visual modes the diagram layer can produce (see diagrams_v4 + director)
EXPLANATORY_MODES = (
    "BLUEPRINT", "STRUCTURAL_DIAGRAM", "CUTAWAY", "CROSS_SECTION",
    "MACRO_DETAIL", "CELLULAR_DIAGRAM", "MOLECULAR_PROCESS",
    "MAP", "GEOGRAPHIC_TRANSFORMATION", "CLIMATE_RECON",
    "ASTRONOMICAL_SCALE", "ORBITAL_DIAGRAM", "DARK_CINEMATIC",
    "TIMELINE", "ARCHIVAL_ILLUSTRATION", "MAP_TRANSFORMATION",
    "FORCE_DIAGRAM", "ANIMATION",
    # generic fallbacks
    "COMPARISON", "TRANSFORMATION", "SCALE", "DIAGRAM",
    # V13 M4 — mode→representation mapping (JADE_V13_RICH_VISUAL_DIRECTIVE
    # P0 "STORY-SPECIFIC VISUAL REPRESENTATION"): every major beat classifies
    # into the most informative visual mode; the rich visual plate + overlays
    # is the NORMAL visual, diagrams are evidence.
    "RICH_PLATE", "MATERIAL_DEFORMATION", "VECTOR_DIAGRAM",
    "DATA_GRAPHIC", "PROCESS_LOOP", "CAUSAL_CHAIN",
)

# V13 M4 — every mode maps to exactly ONE representation class:
#   PLATE          rich visual plate (the normal visual)
#   PLATE+OVERLAY  plate + annotation overlay (callouts, measures, arrows)
#   DIAGRAM        standalone diagram painter — evidence, never the default
#   HYBRID         diagram elements composed over the staged plate
# Unknown modes default to PLATE: a rich plate is always renderable and the
# directive forbids defaulting to diagram painters.
MODE_REPRESENTATION = {
    # PLATE
    "RICH_PLATE": "PLATE", "DARK_CINEMATIC": "PLATE",
    "ARCHIVAL_ILLUSTRATION": "PLATE", "MACRO_DETAIL": "PLATE",
    "TYPOGRAPHY": "PLATE",
    # PLATE+OVERLAY
    "CUTAWAY": "PLATE+OVERLAY", "CROSS_SECTION": "PLATE+OVERLAY",
    "MAP": "PLATE+OVERLAY", "MAP_TRANSFORMATION": "PLATE+OVERLAY",
    "GEOGRAPHIC_TRANSFORMATION": "PLATE+OVERLAY",
    "CLIMATE_RECON": "PLATE+OVERLAY", "ASTRONOMICAL_SCALE": "PLATE+OVERLAY",
    "MATERIAL_DEFORMATION": "PLATE+OVERLAY",
    # DIAGRAM (evidence)
    "DIAGRAM": "DIAGRAM", "STRUCTURAL_DIAGRAM": "DIAGRAM",
    "CELLULAR_DIAGRAM": "DIAGRAM", "ORBITAL_DIAGRAM": "DIAGRAM",
    "FORCE_DIAGRAM": "DIAGRAM", "BLUEPRINT": "DIAGRAM",
    "TIMELINE": "DIAGRAM", "COMPARISON": "DIAGRAM",
    "TRANSFORMATION": "DIAGRAM", "SCALE": "DIAGRAM",
    "VECTOR_DIAGRAM": "DIAGRAM", "DATA_GRAPHIC": "DIAGRAM",
    "MOLECULAR_PROCESS": "DIAGRAM", "ANIMATION": "DIAGRAM",
    # HYBRID (diagram composed over the plate)
    "PROCESS_LOOP": "HYBRID", "CAUSAL_CHAIN": "HYBRID",
    # V13 M5 — signature move: continuous zoom through nested scales
    # rendered as layered plates.  Compositor-side zoom primitive is
    # DEFERRED to the integration milestone (GAP_ANALYSIS #13 — needs M3
    # depth layers); the planner stamps the mode now, motion renders later.
    "SCALE_DIVE": "PLATE",
}

REPRESENTATION_CLASSES = ("PLATE", "PLATE+OVERLAY", "DIAGRAM", "HYBRID")


def representation_for(mode: str) -> str:
    """One representation class per mode (V13 M4); unknown -> PLATE."""
    return MODE_REPRESENTATION.get(str(mode or "").upper().strip(), "PLATE")


def representation_of(record: dict) -> tuple[str, str]:
    """Legacy tolerance (V13 M4): plans/beats stamped before M4 carry no
    representation field -> ("DIAGRAM", "legacy").  Old plans stay valid."""
    rep = str((record or {}).get("representation") or "").strip()
    if not rep:
        return "DIAGRAM", "legacy"
    return rep, str((record or {}).get("mode_justification") or "legacy")


# V13 M5 — SCALE_DIVE routing: nested-scale domains where a continuous
# zoom across scales IS the explanation (directive P0 signature move;
# mountain-to-microscope is the canonical class pair).
SCALE_DIVE_TERMS = (
    "cell", "cellular", "atom", "atomic", "molecule", "molecular",
    "galaxy", "galaxies", "universe", "cosmos",
    "ocean depth", "deep ocean", "abyss", "hadal", "trench",
    "mountain-to-microscope", "microscope",
)


def scale_dive_candidate(subject: str = "", claim: str = "") -> bool:
    """True when subject/claim text mentions a nested-scale domain."""
    text = f"{subject or ''} {claim or ''}".lower()
    return any(t in text for t in SCALE_DIVE_TERMS)


def grammar_for(subject: str, beat_function: str = "", topic_grammar=None) -> tuple:
    """Return the (preferred, fallback) grammar tuple for a subject.

    V11 P1 §3: an explicit bible `topic_grammar` declaration (brand ≠
    visual vocabulary — the author's chosen vocabulary for THIS topic)
    overrides the inferred SUBJECT_GRAMMAR. It still flows through the
    HOOK/PAYOFF cinematic/typography preference.
    """
    s = (subject or "general").lower()
    if topic_grammar:
        pref = tuple(str(m).upper() for m in topic_grammar if str(m).strip())
    elif s in SUBJECT_GRAMMAR:
        pref = SUBJECT_GRAMMAR[s]
    else:
        pref = ("COMPARISON", "TRANSFORMATION", "SCALE", "TIMELINE")
    # HOOK/PAYOFF prefer cinematic-or-strong-payoff grammar
    if beat_function in ("HOOK",):
        return ("DARK_CINEMATIC",) + tuple(p for p in pref if p != "DARK_CINEMATIC")
    if beat_function in ("PAYOFF",):
        return ("TYPOGRAPHY",) + tuple(p for p in pref if p != "TYPOGRAPHY")
    return pref


def recommend_mode_detailed(subject: str, beat_function: str, claim: str = "",
                            visual_mode: str = "",
                            scale_dive_allowed: bool = False) -> dict:
    """V13 M4: pick a mode AND justify it.  Returns
    {"mode", "representation", "mode_justification"}.  Richer representations
    (PLATE / PLATE+OVERLAY / HYBRID) are preferred whenever the subject
    grammar supports them; a DIAGRAM-class default carries an explicit
    justification (directive P0: diagrams are evidence, not the default)."""
    if visual_mode:
        rep = representation_for(visual_mode)
        just = ("author-declared mode" if rep != "DIAGRAM" else
                "author-declared diagram-class mode (evidence)")
        return {"mode": visual_mode, "representation": rep,
                "mode_justification": just}
    # V13 M5 — SCALE_DIVE signature routing.  The caller gates eligibility
    # (at most ONE mid-story beat; never the hook, never the payoff).
    if (scale_dive_allowed
            and str(beat_function or "").upper() not in ("HOOK", "PAYOFF")
            and scale_dive_candidate(subject, claim)):
        return {"mode": "SCALE_DIVE",
                "representation": representation_for("SCALE_DIVE"),
                "mode_justification":
                    "SCALE_DIVE: continuous zoom through nested scales "
                    "rendered as layered plates — single mid-story "
                    "signature move (not hook, not payoff)"}
    pref = grammar_for(subject, beat_function)
    valid = [m for m in pref if m in EXPLANATORY_MODES]
    rich = [m for m in valid if representation_for(m) != "DIAGRAM"]
    if rich:
        mode = rich[0]
        just = (f"subject grammar '{subject or 'general'}' supports "
                f"{representation_for(mode)}; {mode} preferred over "
                f"diagram painters")
    elif valid:
        mode = valid[0]
        just = (f"subject grammar '{subject or 'general'}' offers only "
                f"diagram-class modes; {mode} used as evidence")
    else:
        mode = "COMPARISON"
        just = "no subject grammar match; generic diagram fallback"
    return {"mode": mode, "representation": representation_for(mode),
            "mode_justification": just}


def recommend_mode(subject: str, beat_function: str, claim: str = "",
                   visual_mode: str = "") -> str:
    """Pick one recommended mode for a shot. Respects an explicit visual_mode
    if the visual_plan set one (V5 §5: don't override intentional choices);
    otherwise resolves the subject+function grammar and chooses the first
    mode that maps to an implemented diagram type.  V13 M4: now prefers
    richer representations when the subject grammar supports them; see
    recommend_mode_detailed for the justification companion."""
    return recommend_mode_detailed(subject, beat_function, claim,
                                   visual_mode)["mode"]


def is_explanatory_mode(mode: str) -> bool:
    """True if the mode is one of the brief's 'transformation-priority' modes
    (more informative than a decorative cinematic plate)."""
    return mode.upper() in {
        "COMPARISON", "TRANSFORMATION", "SCALE", "TIMELINE", "MAP", "CUTAWAY",
        "BLUEPRINT", "STRUCTURAL_DIAGRAM", "CROSS_SECTION", "MACRO_DETAIL",
        "CELLULAR_DIAGRAM", "MOLECULAR_PROCESS", "GEOGRAPHIC_TRANSFORMATION",
        "CLIMATE_RECON", "ASTRONOMICAL_SCALE", "ORBITAL_DIAGRAM",
        "ARCHIVAL_ILLUSTRATION", "MAP_TRANSFORMATION", "FORCE_DIAGRAM",
        "ANIMATION", "RICH_PLATE", "MATERIAL_DEFORMATION",
        "VECTOR_DIAGRAM", "DATA_GRAPHIC", "PROCESS_LOOP", "CAUSAL_CHAIN",
    }


def suggest_transformation(claim: str) -> str:
    """Brief P1: 'Before generating a decorative cinematic plate, ask: can
    this fact be communicated more powerfully through comparison /
    transformation / scale / timeline / map / cutaway / before-after /
    process diagram / cause-effect / animation of a physical relationship?'

    Lightweight keyword-based suggestion over the claim text.
    """
    c = (claim or "").lower()
    if any(w in c for w in ("before", "after", "now", "used to", "was", "became", "transformed")):
        return "COMPARISON"
    if any(w in c for w in ("scale", "times", "larger", "smaller", "bigger", "tiny", "vast", "thousand", "million")):
        return "SCALE"
    if any(w in c for w in ("over time", "years", "centuries", "ago", "history", "evolution", "age")):
        return "TIMELINE"
    if any(w in c for w in ("map", "region", "continent", "where", "location")):
        return "MAP"
    if any(w in c for w in ("inside", "cutaway", "cross-section", "layers", "internal")):
        return "CUTAWAY"
    if any(w in c for w in ("because", "causes", "results in", "leads to", "process", "mechanism")):
        return "ANIMATION"
    if any(w in c for w in ("compared", "versus", "vs", "than", "instead")):
        return "COMPARISON"
    return ""


# ------------------------------------------------------------------ #
# V6.2 §4 — Kinetic Vector Primitives                                #
#                                                                    #
# Animated, deterministic PIL plate renderers used in place of the   #
# static plate for specific diagram shots:                           #
#   clocks      -> scale/physics grammar: two clocks, near hand at   #
#                  omega_near = omega_ratio * omega_far              #
#   streamlines -> aerodynamics/blueprint: dashed streamline flow    #
#                  with dash-offset advancing procedurally           #
# Frames are rendered at the 2x STAGE canvas (letterboxed content,   #
# matching the zoompan stage geometry) so the standard single        #
# lanczos downsample to PANEL applies unchanged.                     #
# ------------------------------------------------------------------ #

_OMEGA_FAR = 2.0 * math.pi / 4.0   # far clock: one revolution per 4 s


def kinetic_spec(shot: dict, subject: str = "") -> dict | None:
    """Pick the kinetic primitive for a shot, or None (static plate).

    Deterministic content match on the asset id — no per-story patches.
    """
    asset = str(shot.get("asset", "")).lower().replace("_", "")
    if "twoclocks" in asset:
        return {"type": "clocks", "omega_ratio": 0.2}
    if "streamline" in asset or "bernoulli" in asset:
        return {"type": "streamlines"}
    return None


def _kin_palette(bible: dict) -> dict:
    from engine import bible as B
    bg = B.rgb255(bible, "background")
    ink = B.rgb255(bible, "text")
    acc = B.rgb255(bible, "accent")
    mut = B.rgb255(bible, "muted")
    face = tuple(min(255, int(c * 0.35 + 255 * 0.65)) for c in bg)
    return {"bg": bg, "ink": ink, "accent": acc, "muted": mut, "face": face}


def _kin_canvas(w: int, h: int, pal: dict) -> tuple[Image.Image, ImageDraw.ImageDraw, int]:
    """Stage-size canvas with the letterboxed content rect (pad bands in bg)."""
    pad = (h - round(w * 1024 / 1536)) // 2
    pad = max(0, pad)
    img = Image.new("RGB", (w, h), pal["bg"])
    d = ImageDraw.Draw(img, "RGBA")
    return img, d, pad


def _clock(d: ImageDraw.ImageDraw, cx: float, cy: float, r: float, t: float,
           omega: float, pal: dict, label: str, f_big, f_small):
    col = pal["ink"] + (255,)
    face = pal["face"] + (255,)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=face, outline=col, width=8)
    rr = r * 0.86
    for k in range(12):
        a = k * math.pi / 6.0
        x1, y1 = cx + rr * math.sin(a), cy - rr * math.cos(a)
        x2, y2 = cx + r * 0.96 * math.sin(a), cy - r * 0.96 * math.cos(a)
        d.line((x1, y1, x2, y2), fill=col, width=6 if k % 3 else 10)
    ang = (t * omega) % (2.0 * math.pi)
    am = (t * omega / 12.0) % (2.0 * math.pi)
    d.line((cx, cy, cx + r * 0.80 * math.sin(ang), cy - r * 0.80 * math.cos(ang)),
           fill=pal["accent"] + (255,), width=14)
    d.line((cx, cy, cx + r * 0.55 * math.sin(am), cy - r * 0.55 * math.cos(am)),
           fill=col, width=20)
    d.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=col)
    rev = (t * omega) / (2.0 * math.pi)
    tw = d.textlength(label, font=f_big)
    d.text((cx - tw / 2, cy + r + 18), label, font=f_big, fill=col)
    read = f"{rev:.1f} REV"
    rw = d.textlength(read, font=f_small)
    d.text((cx - rw / 2, cy + r + 18 + 96), read, font=f_small,
           fill=pal["muted"] + (255,))


def render_clock_frames(out_dir: Path, n_frames: int, w: int, h: int,
                        bible: dict, omega_ratio: float = 0.2,
                        fps: int = 15) -> list[str]:
    """Two clocks; NEAR hand rotates at omega_ratio x FAR. Deterministic."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pal = _kin_palette(bible)
    f_big = ImageFont.truetype(
        str((Path(__file__).resolve().parent.parent / "assets" / "fonts"
             / "BebasNeue-Regular.ttf")), 84)
    f_small = ImageFont.truetype(
        str((Path(__file__).resolve().parent.parent / "assets" / "fonts"
             / "Inter-Variable.ttf")), 52)
    paths = []
    for i in range(max(1, n_frames)):
        t = i / float(fps)
        img, d, pad = _kin_canvas(w, h, pal)
        cy0 = pad
        ch = h - 2 * pad
        r = int(ch * 0.24)
        # content-band vertical gradient wash for depth
        for yy in range(cy0, cy0 + ch, 8):
            u = (yy - cy0) / max(1, ch)
            g = tuple(int(c * (1.0 - 0.10 * u)) for c in pal["bg"])
            d.line((0, yy, w, yy), fill=g + (255,), width=8)
        _clock(d, w * 0.27, cy0 + ch * 0.38, r, t, _OMEGA_FAR, pal,
               "FAR CLOCK", f_big, f_small)
        _clock(d, w * 0.73, cy0 + ch * 0.62, r, t, _OMEGA_FAR * omega_ratio,
               pal, "NEAR CLOCK", f_big, f_small)
        cap = f"NEAR TICKS AT {omega_ratio:g} x FAR"
        cw = d.textlength(cap, font=f_small)
        d.text(((w - cw) / 2, cy0 + ch - 130), cap, font=f_small,
               fill=pal["ink"] + (230,))
        p = out_dir / f"f{i:05d}.png"
        img.save(p, "PNG")
        paths.append(str(p))
    return paths


def _dashed_polyline(d: ImageDraw.ImageDraw, pts: list, phase: float,
                     dash: float, gap: float, col, width: int):
    """Draw a polyline as moving dashes (phase = arclength offset in px)."""
    segs = []
    total = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        L = math.hypot(x2 - x1, y2 - y1)
        segs.append((x1, y1, x2, y2, total, L))
        total += L
    period = dash + gap
    start = -(phase % period)
    s = start
    while s < total:
        a, b = max(0.0, s), min(total, s + dash)
        if b > a:
            for (x1, y1, x2, y2, base, L) in segs:
                if b <= base or a >= base + L:
                    continue
                ta = (a - base) / L if a > base else 0.0
                tb = (b - base) / L if b < base + L else 1.0
                pa = (x1 + (x2 - x1) * ta, y1 + (y2 - y1) * ta)
                pb = (x1 + (x2 - x1) * tb, y1 + (y2 - y1) * tb)
                d.line((pa[0], pa[1], pb[0], pb[1]), fill=col, width=width)
        s += period


def render_streamline_frames(out_dir: Path, n_frames: int, w: int, h: int,
                             bible: dict, fps: int = 15) -> list[str]:
    """Airfoil + streamlines with animated dash-offset (procedural flow).
    Flow speed rises over the suction (upper) surface, drops below."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pal = _kin_palette(bible)
    f_lab = ImageFont.truetype(
        str((Path(__file__).resolve().parent.parent / "assets" / "fonts"
             / "Inter-Variable.ttf")), 56)
    paths = []
    x0, x1 = w * 0.10, w * 0.90
    cy = (h) * 0.52
    chord = x1 - x0
    # airfoil outline (upper cambered, lower flatter)
    upper, lower = [], []
    for i in range(61):
        u = i / 60.0
        x = x0 + u * chord
        bump = math.sin(math.pi * u)
        upper.append((x, cy - (bump * 0.085 * h + 8)))
        lower.append((x, cy + (bump * 0.028 * h + 6)))
    rows = []
    for k in range(9):
        rows.append(h * 0.14 + k * (h * 0.72) / 8.0)
    ink = pal["ink"] + (255,)
    for i in range(max(1, n_frames)):
        t = i / float(fps)
        img, d, pad = _kin_canvas(w, h, pal)
        d.polygon(upper + lower[::-1], fill=pal["face"] + (255,),
                  outline=ink, width=8)
        for k, y0 in enumerate(rows):
            dy = y0 - cy
            defl = 150.0 * math.exp(-((dy / (h * 0.16)) ** 2))
            pts = []
            for j in range(73):
                u = j / 72.0
                x = w * -0.03 + u * (w * 1.06)
                bend = defl * math.exp(-(((x - (x0 + chord * 0.45))
                                          / (chord * 0.42)) ** 2))
                y = y0 + (-bend if dy < 0 else bend * 0.6)
                pts.append((x, y))
            above = dy < 0
            speed = (1.0 + 0.9 * math.exp(-((abs(dy) / (h * 0.14)) ** 2))) \
                if above else 0.55
            col = pal["accent"] + (235,) if above else pal["ink"] + (200,)
            _dashed_polyline(d, pts, phase=t * speed * 300.0, dash=88.0,
                             gap=64.0, col=col, width=7 if above else 5)
        d.text((w * 0.06, rows[0] - 90), "FASTER", font=f_lab,
               fill=pal["accent"] + (255,))
        d.text((w * 0.06, rows[-1] + 24), "SLOWER", font=f_lab,
               fill=pal["muted"] + (255,))
        p = out_dir / f"f{i:05d}.png"
        img.save(p, "PNG")
        paths.append(str(p))
    return paths
