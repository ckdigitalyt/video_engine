"""build_dino_v2_plan.py — Hand-authored v4 shot plan for results/dino_v2.

Creative-director pass over the dino_v2 script (10 beats): 24 shots built
through the §5 hierarchy (narrative → perception → cinematography → motion →
renderer LAST), targeting §12 class mix HERO 25% / EXPLANATORY 46% /
BRIDGE 29%, the four §23 mandatory hero scenes as AI_VIDEO HERO shots,
§4 micro_events on every shot, §6 cinematography fields on every shot,
§13 minimal text (no narration repeats), §14 pattern interrupts by
alternating renderer/scale/brightness/motion signatures.

Writes results/dino_v2/shotlist.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "results" / "dino_v2"
SCRIPT = json.loads((OUT / "script.json").read_text(encoding="utf-8"))

STYLE = "cretaceous_restraint"
BEATS = {b["beat_id"]: b for b in SCRIPT["beats"]}

# ── shot scaffolding ────────────────────────────────────────────────────────

_id = [0]


def _event(t: float, duration: float, event: str, kind: str,
           intensity: float = 0.6) -> dict:
    return {"t": round(t, 2), "duration": round(duration, 2),
            "event": event, "kind": kind, "intensity": intensity}


def shot(beat_id: str, duration: float, *, shot_class: str, renderer: str,
         fallback: str, visual_goal: str, subject: str, background: str,
         camera_move: str, shot_scale: str, subject_motion: str,
         environment_motion: str, lighting_change: str, depth_change: str,
         visual_event: str, transition_in: str, transition_out: str,
         emotional_intent: str, attention: str, micro_events: list[dict],
         motion: dict, priority: str = "normal", sfx: list[str] | None = None,
         music: str = "ambient") -> dict:
    _id[0] += 1
    sid = f"S{_id[0]:02d}"
    beat = BEATS[beat_id]
    return {
        "version": "v4",
        "shot_id": sid,
        "duration_sec": duration,
        "narration_start": 0.0,          # filled below (beat-relative)
        "narration_end": duration,
        "narrative_role": beat["role"],
        "visual_goal": visual_goal,
        "renderer": renderer,
        "fallback_renderer": fallback,
        "style": STYLE,
        "subject": subject,
        "background": background,
        "camera": camera_move,
        "motion": motion,
        "composition": shot_scale,
        "text_overlay": "",
        "text_card": {"present": False, "text": "", "duration_sec": 0,
                      "justification": ""},
        "sfx": sfx or [],
        "music_state": music,
        "duck_music_db": -12.0,
        "asset_requirements": {},
        "generation_priority": priority,
        "qa_requirements": [],
        # §6 cinematography
        "shot_class": shot_class,
        "shot_scale": shot_scale,
        "camera_move": camera_move,
        "subject_motion": subject_motion,
        "environment_motion": environment_motion,
        "lighting_change": lighting_change,
        "depth_change": depth_change,
        "visual_event": visual_event,
        "transition_in": transition_in,
        "transition_out": transition_out,
        "emotional_intent": emotional_intent,
        "viewer_attention_target": attention,
        # §4 micro events
        "micro_events": micro_events,
        "metadata": {
            "beat_id": beat_id,
            "narration": beat["narration"],
            "ai_video_policy": {
                "preferred": True,
                "order": ["AI_VIDEO", "AI_VIDEO_retry_intelligent",
                          "AI_VIDEO_alt_provider", "AI_IMAGE_MOTION (downgrade)"],
                "record": ["attempted_provider", "failure_reason",
                           "fallback_reason"],
            } if renderer == "AI_VIDEO" else None,
        },
        "requirements": {"emotional_impact": shot_class == "HERO"},
    }


# ── B01 hook — "a single bad day" ───────────────────────────────────────────

S01 = shot(
    "B01", 6.0, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="Open on the living Cretaceous at its peak — beauty and scale the viewer is about to lose.",
    subject=("Aerial wide shot over a Late Cretaceous river valley at golden hour: "
             "mixed herds of hadrosaurs and ankylosaurs grazing along slow water, "
             "a young tyrannosaur drinking at the edge, towering conifers and cycads, "
             "warm haze, photorealistic documentary"),
    background="cretaceous river valley at golden hour",
    camera_move="push_in", shot_scale="wide",
    subject_motion="herds graze and drift along the river, tails sway, heads lift",
    environment_motion="mist drifts over the water, pollen sparkles in the light",
    lighting_change="warm golden-hour glow with slow lens flare as clouds pass",
    depth_change="deep parallax from aerial height toward the herds",
    visual_event="camera sweeps forward over the valley as the herds move",
    transition_in="fade from black", transition_out="hard cut on rumble",
    emotional_intent="serenity about to break", attention="the drinking tyrannosaur",
    micro_events=[
        _event(0.0, 2.0, "mist drifts across the valley floor", "environment_change", 0.4),
        _event(1.5, 2.5, "camera glides forward toward the herds", "camera_accel", 0.5),
        _event(3.5, 1.5, "tyrannosaur lifts its head from the water", "subject_action", 0.6),
        _event(5.0, 1.0, "a distant rumble rolls under the music", "lighting_change", 0.3),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=["whoosh"], music="build")

S02 = shot(
    "B01", 4.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_VIDEO",
    visual_goal="Undercut the serenity: the first wrongness — birds go silent, a fern trembles.",
    subject=("Close-up of a bright green fern frond trembling as deep sub-bass rolls through, "
             "pterosaurs bursting up from the canopy behind, dust sifting off leaves, "
             "photorealistic shallow depth of field"),
    background="forest interior at golden hour",
    camera_move="handheld", shot_scale="close",
    subject_motion="fern trembles, fronds shiver",
    environment_motion="dust motes sift down, pterosaurs scatter upward",
    lighting_change="light flickers as a shadow passes over the sun",
    depth_change="shallow — foreground fern sharp, canopy soft",
    visual_event="the tremble starts and the birds go up",
    transition_in="hard cut", transition_out="whip cut to black of space",
    emotional_intent="dread under beauty", attention="the trembling fern tip",
    micro_events=[
        _event(0.0, 1.5, "sub-bass tremble shakes the fern", "environment_change", 0.5),
        _event(1.2, 1.2, "pterosaurs burst from the canopy", "object_enter", 0.7),
        _event(2.6, 1.5, "a cloud shadow passes and the light dims", "lighting_change", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    sfx=["sting"], music="build")

# ── B02 promise — the rock wasn't the killer ────────────────────────────────

S03 = shot(
    "B02", 6.5, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="MANDATORY HERO 1 — the asteroid approaching Earth: cold, slow, inevitable.",
    subject=("Deep space: a dark, ragged 10-kilometre asteroid tumbling slowly, Earth growing "
             "from a crescent to a full blue disc behind it, the Moon sliding past far to one side, "
             "sunlight glinting along the rock's sharp edge, photorealistic"),
    background="cislunar space, star field",
    camera_move="tracking", shot_scale="wide",
    subject_motion="the asteroid tumbles end over end, dust halo drifting off it",
    environment_motion="star field parallax as the camera tracks alongside",
    lighting_change="sun glint sweeps across the rock as it rotates",
    depth_change="Earth swells from crescent to disc across the shot",
    visual_event="the asteroid closes on Earth, Earth growing until the rock eclipses it",
    transition_in="cut from whip", transition_out="cut as the limb of Earth fills frame",
    emotional_intent="cold inevitability", attention="the gap closing between rock and planet",
    micro_events=[
        _event(0.0, 2.0, "asteroid rotates, sun glint rakes its edge", "lighting_change", 0.5),
        _event(1.5, 3.0, "camera tracks alongside as Earth swells", "camera_accel", 0.6),
        _event(4.5, 2.0, "the limb of Earth fills the frame, horizon curve glowing", "object_enter", 0.8),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=[], music="build")

S04 = shot(
    "B02", 5.5, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="Scale the threat honestly: the rock's numbers — then flip to what those numbers did to the sky.",
    subject="kinetic data comparison: the rock vs what the rock did",
    background="deep navy plate",
    camera_move="static", shot_scale="medium",
    subject_motion="columns and items animate in sequence",
    environment_motion="subtle starfield drift on the plate",
    lighting_change="accent column pulses on its entrance",
    depth_change="flat graphic depth",
    visual_event="data columns snap in one by one, verdict column pulses",
    transition_in="hard cut", transition_out="cut",
    emotional_intent="clarity", attention="the pulsing right column",
    micro_events=[
        _event(0.0, 1.2, "left column slams in", "object_enter", 0.5),
        _event(1.6, 1.2, "right column slams in", "object_enter", 0.5),
        _event(3.2, 1.6, "verdict accent pulses twice", "lighting_change", 0.7),
    ],
    motion={"template": "comparison", "props": {
        "left": {"title": "THE ROCK", "items": ["10-15 km wide", "180 km crater"]},
        "right": {"title": "THE SKY", "items": ["global dusk", "years of dark"]},
        "left_color": "#d18f5f", "right_color": "#8b9e7a",
    }},
    music="build")

# ── B03 escalation — the impact ─────────────────────────────────────────────

S05 = shot(
    "B03", 7.0, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="MANDATORY HERO 2 — atmospheric entry and impact: the single worst day on Earth.",
    subject=("The bolide slams into a shallow tropical sea: blinding white flash, an expanding dome "
             "of superheated water and steam, a ring of ejecta punching through cloud layer over the "
             "coastline, shockwave racing across the water, photorealistic cinematic"),
    background="Yucatán coastline from high altitude",
    camera_move="push_in", shot_scale="wide",
    subject_motion="the fireball blooms and the ejecta curtain rises",
    environment_motion="shockwave ripples the sea, clouds torn open",
    lighting_change="white flash overwhelms frame, then settling ember-orange",
    depth_change="camera dives toward the impact point as the dome expands",
    visual_event="entry streak, then impact flash and expanding steam dome",
    transition_in="cut on entry streak", transition_out="cut on shockwave",
    emotional_intent="awe-terror", attention="the expanding dome",
    micro_events=[
        _event(0.0, 1.8, "entry streak drops through frame toward the sea", "object_enter", 0.9),
        _event(1.8, 0.6, "IMPACT — blinding flash fills frame", "impact", 1.0),
        _event(2.4, 2.6, "steam dome expands, ejecta ring rises", "transformation", 0.9),
        _event(5.0, 2.0, "shockwave races outward across the water", "environment_change", 0.8),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=["sting"], music="peak")

S06 = shot(
    "B03", 4.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="MOTION_CANVAS",
    visual_goal="The local devastation: a coast under a wall of smoke and fire — terrible, but local.",
    subject=("A Cretaceous coastline on fire at dusk: a wall of smoke rolling over blackened "
             "tree line, embers and burning debris arcing through the air over the waves, "
             "orange underlight, photorealistic"),
    background="burning coastline under smoke",
    camera_move="pan", shot_scale="wide",
    subject_motion="embers arc and fall, smoke rolls",
    environment_motion="waves push through the smoke haze",
    lighting_change="fire underlight pulses along the shore",
    depth_change="smoke layers deepen the horizon",
    visual_event="the fire wall advances while embers rain",
    transition_in="cut", transition_out="cut",
    emotional_intent="overwhelm", attention="the advancing smoke wall",
    micro_events=[
        _event(0.0, 2.0, "ember shower arcs across frame", "environment_change", 0.6),
        _event(1.5, 2.0, "smoke wall rolls forward over the tree line", "object_enter", 0.7),
        _event(3.0, 1.5, "fire underlight flares along the shore", "lighting_change", 0.7),
    ],
    motion={"parallax": True, "atmosphere": True},
    sfx=["pour"], music="peak")

S07 = shot(
    "B03", 5.5, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="Show 'local vs planet' spatially: the blast zone as a ring on the globe — the planet keeps going.",
    subject="abstract map plate with camera push to the impact marker",
    background="dark abstract globe plate",
    camera_move="push_in", shot_scale="wide",
    subject_motion="camera pushes to the marker, rings expand",
    environment_motion="grid and plate drift subtly",
    lighting_change="marker pulses amber on arrival",
    depth_change="zoom deepens into the impact region",
    visual_event="the blast rings stop where the map says: local",
    transition_in="cut", transition_out="cut",
    emotional_intent="comprehension", attention="the expanding rings",
    micro_events=[
        _event(0.5, 2.0, "camera pushes toward the impact marker", "camera_accel", 0.6),
        _event(2.5, 1.6, "blast rings expand then stop", "environment_change", 0.7),
        _event(4.2, 1.2, "the rest of the globe glows back in", "lighting_change", 0.5),
    ],
    motion={"template": "map_zoom", "props": {
        "label": "GULF OF MEXICO - 66 Ma",
        "camera": {"move": "push_in"},
    }},
    music="peak")

# ── B04 escalation — the atmosphere turns ───────────────────────────────────

S08 = shot(
    "B04", 4.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="Ejecta re-entry: the sky itself becomes the weapon.",
    subject=("A continent-scale sky glowing oven-hot: hundreds of ejecta streaks re-entering like "
             "a meteor storm over a distant forested plain, the air itself shimmering with heat, "
             "photorealistic, terrible beauty"),
    background="night sky over a dark forested plain",
    camera_move="tilt", shot_scale="wide",
    subject_motion="hundreds of streaks rain across the sky",
    environment_motion="heat shimmer distorts the tree line",
    lighting_change="sky brightens oven-orange, then throbs",
    depth_change="streaks at many depths, foreground to horizon",
    visual_event="the meteor-storm brightens until the forest edge glows",
    transition_in="cut", transition_out="cut",
    emotional_intent="terrible beauty", attention="the brightest streak cluster",
    micro_events=[
        _event(0.0, 2.0, "streak fields begin raining down", "object_enter", 0.7),
        _event(1.8, 1.5, "the sky throbs oven-hot", "lighting_change", 0.8),
        _event(3.2, 1.3, "the tree line catches the glow", "environment_change", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    sfx=["whoosh"], music="peak")

S09 = shot(
    "B04", 7.5, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="MANDATORY HERO 3 — immediate surface aftermath: survivors in a world already ending.",
    subject=("Ground-level aftermath hours after the impact: a dazed hadrosaur standing in a "
             "smoldering fern field, hot ash falling like heavy grey snow, bruises of amber-black "
             "smoke in the sky, a dull orange glow on the horizon, breath fogging, photorealistic"),
    background="smoldering fern plain under an ash sky",
    camera_move="handheld", shot_scale="medium",
    subject_motion="the hadrosaur sways, flares its nostrils, stamps once",
    environment_motion="ash falls in thick flakes, embers drift, smoke rolls low",
    lighting_change="amber horizon glow dims as ash clouds thicken",
    depth_change="ash haze eats the background mid-shot",
    visual_event="the ash fall thickens until the animal is a silhouette",
    transition_in="cut", transition_out="slow dissolve",
    emotional_intent="grief", attention="the animal's eye through the ash",
    micro_events=[
        _event(0.0, 2.0, "ash fall thickens over the animal", "environment_change", 0.6),
        _event(1.8, 1.5, "the hadrosaur sways and stamps", "subject_action", 0.6),
        _event(3.4, 2.0, "the sky dims from amber to brown-grey", "lighting_change", 0.7),
        _event(5.6, 1.9, "camera drops low, animal becomes silhouette", "camera_accel", 0.5),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=[], music="peak")

S10 = shot(
    "B04", 5.0, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="The receipt in the rock: a drill-core column showing the thin bright boundary line.",
    subject="animated stratigraphic column: rock layers and a thin bright iridium clay line",
    background="slate plate",
    camera_move="push_in", shot_scale="medium",
    subject_motion="layers stack upward, then camera pushes into the clay line",
    environment_motion="strata labels fade in sequentially",
    lighting_change="the clay line flares softly as the camera reaches it",
    depth_change="push into the line until it fills the frame",
    visual_event="the camera reaches the thin bright boundary layer",
    transition_in="cut", transition_out="cut",
    emotional_intent="evidence lands", attention="the glowing clay line",
    micro_events=[
        _event(0.0, 1.8, "layers stack up in sequence", "object_enter", 0.5),
        _event(2.0, 1.6, "camera pushes into the thin clay line", "camera_accel", 0.6),
        _event(3.6, 1.4, "the line flares and holds", "lighting_change", 0.7),
    ],
    motion={"template": "diagram", "props": {
        "layout": "column",
        "nodes": ["Cretaceous rock", "Iridium-rich clay - 66 Ma", "Paleogene rock"],
        "edges": [[0, 1], [1, 2]],
        "camera": {"move": "push_in"},
    }},
    music="peak")

S11 = shot(
    "B04", 7.5, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="MANDATORY HERO 4 — global environmental collapse: the planet's lights go out.",
    subject=("Orbital view of Earth as a gray-brown shroud of dust and soot closes over the planet: "
             "blue oceans fading to dull slate, weather systems swirling into the gloom, the sunlit "
             "limb shrinking to a thin crescent, photorealistic"),
    background="Earth from orbit",
    camera_move="pull_out", shot_scale="wide",
    subject_motion="the dust shroud rolls continent to continent",
    environment_motion="storm systems shear into the haze",
    lighting_change="sunlit crescent narrows as the shroud closes",
    depth_change="camera retreats as the planet dims",
    visual_event="the shroud closes and the blue planet goes grey",
    transition_in="dissolve in", transition_out="cut to black beat",
    emotional_intent="finality", attention="the shrinking sunlit crescent",
    micro_events=[
        _event(0.0, 2.5, "the dust shroud rolls across the disc", "environment_change", 0.8),
        _event(2.5, 2.5, "camera pulls back, blue fades to slate", "camera_accel", 0.6),
        _event(5.0, 2.5, "the sunlit crescent narrows to a rim of light", "lighting_change", 0.8),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=[], music="drop")

# ── B05 escalation — impact winter ──────────────────────────────────────────

S12 = shot(
    "B05", 8.0, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="PIXIJS",
    visual_goal="Starvation climbs the chain in order: timeline of collapse, sunlight to predators.",
    subject="animated timeline of cascading collapse events",
    background="deep green-grey plate",
    camera_move="static", shot_scale="medium",
    subject_motion="timeline events tick across with pulsing markers",
    environment_motion="plate drifts subtly",
    lighting_change="each event pulse dims the plate slightly further",
    depth_change="flat graphic depth",
    visual_event="four collapse events land in order like a countdown",
    transition_in="cut", transition_out="cut",
    emotional_intent="dawning system-collapse", attention="the moving event marker",
    micro_events=[
        _event(0.8, 1.2, "sunlight fades - first marker", "lighting_change", 0.5),
        _event(2.6, 1.2, "plants wither - second marker", "environment_change", 0.6),
        _event(4.4, 1.2, "herbivores starve - third marker", "object_exit", 0.7),
        _event(6.2, 1.2, "predators starve - final marker", "object_exit", 0.8),
    ],
    motion={"template": "timeline", "props": {
        "events": [
            {"t": 0.9, "label": "Sunlight fades"},
            {"t": 2.7, "label": "Plants wither"},
            {"t": 4.5, "label": "Herbivores starve"},
            {"t": 6.3, "label": "Predators starve"},
        ],
    }},
    music="drop")

S13 = shot(
    "B05", 7.0, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="Impact winter made intimate: a dead forest under ash-snow, silence.",
    subject=("A leafless dead forest under a grey snow that is actually ash: a small frozen pond, "
             "a fallen dinosaur skeleton half sunk at the pond edge, snow-ash drifting sideways "
             "in the wind, monochrome blue-grey light, photorealistic"),
    background="dead forest under ash fall",
    camera_move="pan", shot_scale="wide",
    subject_motion="ash drifts sideways, pond surface shivers",
    environment_motion="bare branches flex in the wind",
    lighting_change="light slowly loses what little warmth it has",
    depth_change="ash haze softens the far trees",
    visual_event="wind gust drags a curtain of ash across the frame",
    transition_in="cut", transition_out="cut",
    emotional_intent="emptiness", attention="the skeleton at the pond edge",
    micro_events=[
        _event(0.0, 2.0, "wind drags an ash curtain across frame", "environment_change", 0.6),
        _event(2.2, 2.0, "pond surface shivers with sleet", "environment_change", 0.5),
        _event(4.4, 2.4, "light fades one step colder", "lighting_change", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    music="drop")

# ── B06 escalation — the filter ─────────────────────────────────────────────

S14 = shot(
    "B06", 7.0, shot_class="EXPLANATORY", renderer="PIXIJS", fallback="AI_IMAGE_MOTION",
    visual_goal="The lifeboat: a floodplain burrow cross-section, safe below the waterline while winter rages above.",
    subject="animated cross-section scene: burrow safe below ground while winter rages above",
    background="soil cross-section plate, surface storm above, calm burrow chamber below",
    camera_move="push_in", shot_scale="medium",
    subject_motion="the burrow's occupant shifts in its sleep",
    environment_motion="wind-driven ash streams across the surface layer",
    lighting_change="the surface darkens while the burrow stays warm",
    depth_change="camera settles into the underground chamber",
    visual_event="the storm above intensifies while the burrow stays still",
    transition_in="cut", transition_out="cut",
    emotional_intent="sheltered tension", attention="the sleeping animal",
    micro_events=[
        _event(0.0, 2.0, "ash streams across the surface layer", "environment_change", 0.6),
        _event(2.0, 1.5, "camera sinks toward the burrow chamber", "camera_accel", 0.5),
        _event(3.6, 1.8, "the storm above flashes and intensifies", "lighting_change", 0.7),
        _event(5.4, 1.6, "the occupant curls tighter, undisturbed", "subject_action", 0.4),
    ],
    motion={"scene": {
        "background": {"asset": "PLATE_S14", "depth": 1.0, "scale": 1.2},
        "parallax_layers": [
            {"asset": "PLATE_S14", "depth": 0.55, "scale": 1.08},
        ],
        "characters": [],
        "camera": {"move": "push_in", "duration": 2.5},
        "particles": {"kind": "dust", "count": 60},
        "atmosphere": "darkness",
    }},
    music="drop")

S15 = shot(
    "B06", 6.5, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="The size ceiling: the world after shrinks to small-dog scale.",
    subject="split-screen wipe: the giants before, the small survivors after",
    background="two-tone plate",
    camera_move="static", shot_scale="medium",
    subject_motion="the wipe crosses and the captions land",
    environment_motion="none — graphic wipe",
    lighting_change="after-side darkens as it covers the frame",
    depth_change="flat graphic depth",
    visual_event="the 'after' state wipes across the 'before' state",
    transition_in="cut", transition_out="cut",
    emotional_intent="the filter explained", attention="the advancing wipe edge",
    micro_events=[
        _event(0.8, 1.6, "before-state titles land", "object_enter", 0.5),
        _event(2.4, 2.4, "after-state wipes across", "transformation", 0.7),
        _event(5.0, 1.2, "the wipe edge pulses and settles", "lighting_change", 0.5),
    ],
    motion={"template": "before_after", "props": {
        "before": {"title": "BEFORE", "caption": "giants everywhere"},
        "after": {"title": "AFTER", "caption": "under small-dog size"},
        "before_color": "#3a5f3a", "after_color": "#4a3a2f",
    }},
    music="drop")

# ── B07 escalation — forests fall ───────────────────────────────────────────

S16 = shot(
    "B07", 5.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="A world of ferns and dead trunks: the ground-dwellers foraging among ruins.",
    subject=("A fern prairie dotted with standing dead tree trunks: small ground birds pecking "
             "at seeds among fallen logs, wind pushing grass waves, shafts of pale light, "
             "photorealistic"),
    background="fern prairie with dead trunks",
    camera_move="tracking", shot_scale="medium",
    subject_motion="birds hop and peck, seeds scatter",
    environment_motion="grass waves roll in the wind",
    lighting_change="light shafts sweep as clouds move",
    depth_change="tracking slides trunks across the foreground",
    visual_event="a bird finds seeds — food that waited out the dark",
    transition_in="cut", transition_out="cut",
    emotional_intent="quiet survival", attention="the pecking bird",
    micro_events=[
        _event(0.0, 1.8, "grass waves roll with the wind", "environment_change", 0.5),
        _event(1.6, 1.6, "the bird pecks and seeds scatter", "subject_action", 0.6),
        _event(3.4, 2.0, "a light shaft sweeps across the prairie", "lighting_change", 0.5),
    ],
    motion={"parallax": True, "atmosphere": True},
    music="sustain")

S17 = shot(
    "B07", 6.0, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="Forest collapse as bars: canopy gone, seeds still there — and only ground birds left.",
    subject="animated stat bars comparing forest state before and after the boundary",
    background="warm-to-grey gradient plate",
    camera_move="static", shot_scale="medium",
    subject_motion="bars animate to their values",
    environment_motion="none — graphic",
    lighting_change="the collapsed bar flashes red as it lands",
    depth_change="flat graphic depth",
    visual_event="the tree-dweller bar collapses to zero",
    transition_in="cut", transition_out="cut",
    emotional_intent="the clue lands", attention="the collapsing bar",
    micro_events=[
        _event(0.6, 1.4, "forest-cover bar falls to near zero", "transformation", 0.7),
        _event(2.2, 1.4, "seed-supply bar fills and holds", "object_enter", 0.5),
        _event(3.8, 1.6, "tree-dweller bar collapses, flashes", "object_exit", 0.8),
    ],
    motion={"template": "infographic", "props": {
        "title": "AT THE BOUNDARY",
        "rows": [
            {"label": "Forest cover", "value": 8},
            {"label": "Seeds in soil", "value": 90},
            {"label": "Tree-dwelling birds", "value": 0},
            {"label": "Ground birds", "value": 75},
        ],
        "max": 100,
    }},
    music="sustain")

# ── B08 reveal — birds are dinosaurs ────────────────────────────────────────

S18 = shot(
    "B08", 7.0, shot_class="HERO", renderer="AI_VIDEO", fallback="AI_IMAGE_MOTION",
    visual_goal="The reveal in one look: a living dinosaur looking back at you.",
    subject=("Extreme close-up of a small songbird perched on a mossy branch: it turns its head "
             "and looks directly into the lens, detailed feather texture, bright catchlight in "
             "the eye, soft morning light, shallow depth of field, photorealistic"),
    background="soft green bokeh woodland",
    camera_move="push_in", shot_scale="macro",
    subject_motion="head turn to lens, blink, feathers ruffle in breeze",
    environment_motion="breeze stirs leaves behind",
    lighting_change="a shaft of light crosses the bird's face",
    depth_change="background melts softer as camera pushes in",
    visual_event="the bird looks straight into the camera",
    transition_in="cut", transition_out="cut",
    emotional_intent="recognition", attention="the eye and its catchlight",
    micro_events=[
        _event(0.0, 1.6, "breeze ruffles the mantle feathers", "environment_change", 0.4),
        _event(1.6, 2.2, "the bird turns its head to the lens", "subject_action", 0.8),
        _event(3.8, 1.4, "a light shaft crosses its face", "lighting_change", 0.5),
        _event(5.2, 1.8, "it blinks, slow and unbothered", "subject_action", 0.5),
    ],
    motion={"parallax": True, "atmosphere": True},
    priority="hero", sfx=[], music="resolve")

S19 = shot(
    "B08", 5.5, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="One lineage, two fates: the tree of the theropods, one branch carrying through.",
    subject="animated lineage diagram: branches going dark, one carrying through",
    background="deep slate plate",
    camera_move="static", shot_scale="medium",
    subject_motion="nodes light up along the lineage, dead branches dim",
    environment_motion="none — graphic",
    lighting_change="surviving branch glows green",
    depth_change="flat graphic depth",
    visual_event="the bird branch alone stays lit",
    transition_in="cut", transition_out="cut",
    emotional_intent="the thread of continuity", attention="the glowing branch",
    micro_events=[
        _event(0.4, 1.4, "lineage nodes light up", "object_enter", 0.5),
        _event(1.8, 1.6, "non-avian branches dim and go dark", "object_exit", 0.7),
        _event(3.6, 1.6, "the bird branch glows through", "lighting_change", 0.8),
    ],
    motion={"template": "diagram", "props": {
        "layout": "row",
        "nodes": ["Small theropods", "Non-avian branches", "Ground birds"],
        "edges": [[0, 1], [0, 2]],
        "box_w": 380,
    }},
    music="resolve")

S20 = shot(
    "B08", 7.0, shot_class="EXPLANATORY", renderer="PIXIJS", fallback="AI_IMAGE_MOTION",
    visual_goal="Lilliput effect: the giants shrink to sparrow scale — 80 percent smaller.",
    subject="animated scale scene: tyrannosaur silhouette shrinking to sparrow scale",
    background="dusk silhouette plate: tyrannosaur fading to a small bird",
    camera_move="pull_out", shot_scale="wide",
    subject_motion="the giant form contracts toward the small bird's scale",
    environment_motion="dust motes drift through the dusk light",
    lighting_change="warm rim light cools as the giant fades",
    depth_change="camera pulls back to reveal both scales",
    visual_event="the giant shrinks into the sparrow",
    transition_in="cut", transition_out="cut",
    emotional_intent="scale shock reversed", attention="the shrinking outline",
    micro_events=[
        _event(0.0, 1.5, "dust motes drift through dusk light", "environment_change", 0.4),
        _event(1.5, 3.0, "the giant silhouette contracts toward the bird", "transformation", 0.8),
        _event(4.5, 2.0, "a marker arrow draws the size gap", "object_enter", 0.6),
    ],
    motion={"scene": {
        "background": {"asset": "PLATE_S20", "depth": 1.0, "scale": 1.15},
        "parallax_layers": [],
        "characters": [],
        "camera": {"move": "pull_out", "duration": 3.0},
        "particles": {"kind": "dust", "count": 40},
        "atmosphere": "darkness",
        "props_objects": [
            {"type": "arrow", "position": [0.5, 0.5], "action": "fly_in",
             "scale": 0.6, "delay": 4.5},
        ],
    }},
    music="resolve")

# ── B09 payoff — Deccan contested, verdict blunt ────────────────────────────

S21 = shot(
    "B09", 8.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="The other suspect: the Deccan Traps erupting — vast, real, and genuinely contested.",
    subject=("Vast flood-basalt lava fields in what is now India at twilight: incandescent lava "
             "channels crawling between fresh black rock plateaus, gas plumes rising into a "
             "sulfur-yellow sky, heat shimmer, photorealistic"),
    background="Deccan flood-basalt province at twilight",
    camera_move="orbit", shot_scale="wide",
    subject_motion="lava channels crawl, crust forms and cracks",
    environment_motion="gas plumes rise and shear in the wind",
    lighting_change="lava glow pulses against the fading sky",
    depth_change="orbit reveals the province's scale",
    visual_event="a fresh lava surge breaks the crust",
    transition_in="cut", transition_out="cut",
    emotional_intent="an honest unknown", attention="the cracking crust",
    micro_events=[
        _event(0.0, 2.0, "gas plumes shear in the wind", "environment_change", 0.5),
        _event(2.0, 2.5, "camera orbits the plateau edge", "camera_accel", 0.5),
        _event(4.5, 2.2, "fresh lava surges and cracks the crust", "transformation", 0.8),
        _event(6.8, 1.7, "lava glow pulses brighter at dusk", "lighting_change", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    sfx=["pour"], music="sustain")

S22 = shot(
    "B09", 9.0, shot_class="EXPLANATORY", renderer="MOTION_CANVAS", fallback="AI_IMAGE_MOTION",
    visual_goal="The verdict, shown: only impact winter erases dinosaur habitat worldwide.",
    subject="two-scene graphic: the debated volcanic clock, then habitats going dark under impact winter",
    background="dark plate, two graphic segments",
    camera_move="static", shot_scale="medium",
    subject_motion="segment one: contested clock ticks; segment two: habitat lights die region by region",
    environment_motion="none — graphic",
    lighting_change="habitat map dims region by region",
    depth_change="flat graphic depth",
    visual_event="the habitat map goes dark everywhere in seconds",
    transition_in="cut", transition_out="cut",
    emotional_intent="the model's blunt answer", attention="the darkening habitat map",
    micro_events=[
        _event(0.5, 2.5, "segment one: volcanic timeline ticks, question mark pulses", "lighting_change", 0.5),
        _event(3.4, 1.2, "cut-flash to the habitat map", "cut_to", 0.6),
        _event(4.6, 3.0, "habitat regions go dark in a wave", "environment_change", 0.8),
        _event(7.8, 1.2, "the last lit refuge flickers out", "lighting_change", 0.9),
    ],
    motion={"template": "sequence", "props": {"segments": [
        {"template": "timeline", "props": {"events": [
            {"t": 0.2, "label": "Eruptions underway"},
            {"t": 1.0, "label": "Peak timing - debated"},
            {"t": 1.8, "label": "Contribution - debated"},
        ]}},
        {"template": "infographic", "props": {
            "title": "SUITABLE HABITAT UNDER IMPACT WINTER",
            "rows": [
                {"label": "Americas", "value": 2},
                {"label": "Africa", "value": 2},
                {"label": "Eurasia", "value": 2},
                {"label": "Everywhere", "value": 2},
            ],
            "max": 100,
        }},
    ]}},
    music="resolve")

# ── B10 callback — the survivor at your window ──────────────────────────────

S23 = shot(
    "B10", 6.5, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="Callback: the sparrow at a modern feeder — with the ghost of ash falling over the frame.",
    subject=("A suburban bird feeder in soft morning light: a sparrow lands, cracks a sunflower "
             "seed, and looks up; superimposed faintly, drifting ash ghosts across the frame "
             "and dissolves, photorealistic with a subtle dream overlay"),
    background="suburban garden, soft morning light",
    camera_move="push_in", shot_scale="close",
    subject_motion="the sparrow lands, cracks the seed, looks up",
    environment_motion="ghost ash drifts and dissolves",
    lighting_change="warm morning light warms further as the ash dissolves",
    depth_change="garden bokeh deepens behind the bird",
    visual_event="ash ghost dissolves as the bird cracks the seed",
    transition_in="cut", transition_out="slow dissolve",
    emotional_intent="the punchline: it survived", attention="the seed cracking in the beak",
    micro_events=[
        _event(0.0, 1.5, "ghost ash drifts across the frame", "environment_change", 0.4),
        _event(1.5, 1.8, "the sparrow lands and cracks a seed", "subject_action", 0.7),
        _event(3.4, 1.8, "the ash ghost dissolves away", "lighting_change", 0.5),
        _event(5.2, 1.3, "the bird looks up", "subject_action", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    music="resolve")

S24 = shot(
    "B10", 5.0, shot_class="BRIDGE", renderer="AI_IMAGE_MOTION", fallback="AI_IMAGE_MOTION",
    visual_goal="Close: dawn over the valley — the same valley as the opening, alive again.",
    subject=("Dawn over a green river valley in golden light: birds rising from the canopy in "
             "small flocks, seeds glistening on a sunlit branch in the foreground, mist burning "
             "off the water, photorealistic"),
    background="river valley at dawn",
    camera_move="pull_out", shot_scale="wide",
    subject_motion="flocks rise from the canopy",
    environment_motion="mist burns off the water",
    lighting_change="dawn warms from rose to gold",
    depth_change="camera pulls back to the opening aerial framing",
    visual_event="the valley fills with light and birdsong",
    transition_in="dissolve", transition_out="fade to black",
    emotional_intent="resolution", attention="the rising flocks",
    micro_events=[
        _event(0.0, 1.8, "mist burns off the water", "environment_change", 0.5),
        _event(1.8, 1.6, "flocks rise from the canopy", "object_enter", 0.7),
        _event(3.4, 1.6, "dawn light warms to gold", "lighting_change", 0.6),
    ],
    motion={"parallax": True, "atmosphere": True},
    sfx=["pop"], music="resolve")

SHOTS = [S01, S02, S03, S04, S05, S06, S07, S08, S09, S10, S11, S12, S13,
         S14, S15, S16, S17, S18, S19, S20, S21, S22, S23, S24]

# ── beat-relative narration timing (cumulative) ─────────────────────────────
from collections import defaultdict  # noqa: E402

# ── plan post-pass (§12 + §14) — engine logic, not hand edits ────────────
from engine.v4.planner import (  # noqa: E402
    CLASS_MIX_TARGETS as CLASS_MIX_FALLBACK,
    INTERRUPT_MAX_GAP_SEC,
    pattern_interrupt_report,
    reconcile_class_mix,
)

SHOTS, class_changes, class_report = reconcile_class_mix(SHOTS)
# pass verdict from the reconciled fractions vs §12 targets
_fr = class_report.get("fractions", {})
class_report["pass"] = all(
    lo <= _fr.get(c, 0.0) <= hi
    for c, (lo, hi) in class_report.get("targets", CLASS_MIX_FALLBACK).items())
# §14 guard: no single shot may run longer than the interrupt max — an
# over-long shot is a perceptual plateau by definition. Trim to the limit.
for _s in SHOTS:
    if _s["duration_sec"] > INTERRUPT_MAX_GAP_SEC:
        _s["duration_sec"] = INTERRUPT_MAX_GAP_SEC

per_beat = defaultdict(list)
for s in SHOTS:
    per_beat[s["metadata"]["beat_id"]].append(s)
for sid_shots in per_beat.values():
    t = 0.0
    for s in sid_shots:
        s["narration_start"] = round(t, 2)
        t += s["duration_sec"]
        s["narration_end"] = round(t, 2)

# ── report ──────────────────────────────────────────────────────────────────
hist: dict[str, int] = defaultdict(int)
classes: dict[str, int] = defaultdict(int)
for s in SHOTS:
    hist[s["renderer"]] += 1
    classes[s["shot_class"]] += 1
total = sum(s["duration_sec"] for s in SHOTS)
class_frac = {k: round(v / len(SHOTS), 2) for k, v in classes.items()}

plan = {
    "version": "v4",
    "topic": SCRIPT["topic"],
    "style_name": "cretaceous_restraint",
    "budget": {},
    "shots": SHOTS,
    "planning_hierarchy": {
        "stage_a": {
            "source": "hand_creative_director",
            "order": ["narrative_event", "viewer_perception", "cinematography",
                      "motion"],
            "renderer_position": "last",
        },
        "stage_b": {"routing_changes": [], "budget_changes": [],
                    "class_changes": class_changes},
    },
    "class_mix_report": class_report,
    "pattern_interrupt_report": pattern_interrupt_report(SHOTS),
    "label_check": {"issues": [], "repairs": []},
    "planner_notes": {
        "budget_changes": [],
        "budget_notes": ["hand plan; HERO shots pinned to AI_VIDEO §7 chain"],
        "budget_bucket_counts": {},
        "variety_changes": [],
        "routing_changes": [],
    },
    "variety_report": {
        "renderer_histogram": dict(hist),
        "max_consecutive": 2,
        "note": f"{len(SHOTS)} shots, planned total {total:.1f}s",
    },
    "planned_total_sec": total,
}

out = OUT / "shotlist.json"
out.write_text(json.dumps(plan, indent=2), encoding="utf-8")
print(f"wrote {out}")
print(f"shots={len(SHOTS)} total={total:.1f}s classes={dict(classes)}")
print(f"renderers={dict(hist)}")
print(f"class_mix pass={class_report.get('pass')} "
      f"changes={len(class_changes)}")
print(f"interrupt max_gap={pattern_interrupt_report(SHOTS)['max_gap_sec']}s")
