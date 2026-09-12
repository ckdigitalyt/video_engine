"""V11 P1 §4 — Real 2.5D depth (informational, not decorative).

Directive: depth must be REAL informational depth. A blurred/stretched
background extension does NOT count (occupancy_qa already measures and
excludes blurred-extension area at render QA; this module never credits
it either — a decorative/A-class shot earns no depth-transition credit).

Support real 2.5D layer stacks:
    foreground / midground / background
with transitions between shots that REVEAL INFORMATION (layer change on
a shot carrying a living explanatory event), e.g. the directive ladder
    skate blade -> ice surface -> quasi-liquid interface -> molecular
    scale -> return to macroscopic skate.

Planner tagging (planv5): every shot gets `depth_layers` derived from its
visual mode (deterministic grammar — P2: no randomization). The
visual_plan may override with an authored stack:

  "depth": {"layers": ["foreground", "midground", "background"]}

`run(plan)` stamps `s["v8"]["depth"]` per shot and reports consecutive
shot-pair transitions: `revealing` (layer set changed + incoming shot has
a living explanatory event and is not decorative camera-only) vs
`decorative` (layer change with no information event — camera movement
alone is not information, P0 motion classes).
"""

from __future__ import annotations

LAYERS = ("foreground", "midground", "background")

# visual_mode → layer stack. Deterministic mapping from the mode grammar
# (diagrams_v4/director produce these modes); no randomness.
MODE_LAYERS = {
    # microscopic / structural stacks: subject plane + context plane
    "MACRO_DETAIL": ("foreground", "midground"),
    "CELLULAR_DIAGRAM": ("foreground", "midground"),
    "MOLECULAR_PROCESS": ("foreground", "midground"),
    "STRUCTURAL_DIAGRAM": ("foreground", "midground"),
    "BLUEPRINT": ("foreground", "midground"),
    "FORCE_DIAGRAM": ("foreground", "midground"),
    "COMPARISON": ("foreground", "midground"),
    "TRANSFORMATION": ("foreground", "midground"),
    "ANIMATION": ("foreground", "midground"),
    "PAYOFF": ("foreground", "midground"),
    # hidden-layer grammars: the reveal lives across all three planes
    "CUTAWAY": LAYERS,
    "CROSS_SECTION": LAYERS,
    "SPLIT": LAYERS,
    "SCALE": LAYERS,
    # plan-view / distant grammars: information laid on world planes
    "MAP": ("midground", "background"),
    "GEOGRAPHIC_TRANSFORMATION": ("midground", "background"),
    "CLIMATE_RECON": ("midground", "background"),
    "TIMELINE": ("midground", "background"),
    "ARCHIVAL_ILLUSTRATION": ("midground", "background"),
    "ASTRONOMICAL_SCALE": ("midground", "background"),
    "ORBITAL_DIAGRAM": ("midground", "background"),
    # cinematic establishing: full world stack
    "CINEMATIC": LAYERS,
    "DARK_CINEMATIC": LAYERS,
    # flat information planes
    "DIAGRAM": ("midground",),
    "TYPOGRAPHY": ("foreground",),
}

# Living explanatory event kinds (planv8-stamped) that make a layer change
# an INFORMATION reveal rather than a camera move.
_INFO_EVENTS = {"reveal", "isolate", "flow", "fill_state", "consequence"}


def layer_for(shot: dict, mode: str = "") -> tuple:
    """Layer stack for a shot: authored `depth.layers` wins, else derived
    from the (recommended/actual) visual mode."""
    a = shot.get("depth")
    if isinstance(a, dict):
        layers = tuple(str(x).lower() for x in (a.get("layers") or [])
                       if str(x).strip())
        layers = tuple(x for x in layers if x in LAYERS)
        if layers:
            return layers
    m = (mode or shot.get("visual_mode")
         or (shot.get("visual_grammar") or {}).get("recommended_mode") or "")
    return MODE_LAYERS.get(str(m).upper(), ("midground",))


def run(plan: dict) -> dict:
    """Stamp per-shot `v8["depth"]`, classify consecutive transitions."""
    shots = plan.get("shots") or []
    rows, prev, prev_id = [], None, None
    for s in shots:
        layers = layer_for(s)
        s.setdefault("v8", {})["depth"] = {
            "layers": list(layers),
            "authored": isinstance(s.get("depth"), dict)
                        and bool(s["depth"].get("layers")),
        }
        if prev is not None and set(layers) != set(prev):
            kinds = {str((e or {}).get("kind") or "").lower()
                     for e in (s.get("events") or [])}
            info = bool(kinds & _INFO_EVENTS)
            decorative_cam = str(s.get("motion_class") or "").upper() == "A"
            rows.append({"from": prev_id, "to": str(s.get("shot_id")),
                         "from_layers": list(prev), "to_layers": list(layers),
                         "kind": ("revealing" if info and not decorative_cam
                                  else "decorative"),
                         "events": sorted(kinds & _INFO_EVENTS)})
        prev, prev_id = layers, str(s.get("shot_id"))
    n_rev = sum(1 for r in rows if r["kind"] == "revealing")
    layered = sum(1 for s in shots
                  if len((s.get("v8") or {}).get("depth", {}).get("layers")
                         or []) >= 2)
    verdict = ("no_shots" if not shots else
               "layered" if n_rev >= 1 and layered >= max(1, len(shots) // 2)
               else "flat")
    return {"verdict": verdict, "n_transitions": len(rows),
            "n_revealing": n_rev, "n_decorative": len(rows) - n_rev,
            "layered_shots": layered, "rows": rows}
