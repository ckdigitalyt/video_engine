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
)


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


def recommend_mode(subject: str, beat_function: str, claim: str = "",
                   visual_mode: str = "") -> str:
    """Pick one recommended mode for a shot. Respects an explicit visual_mode
    if the visual_plan set one (V5 §5: don't override intentional choices);
    otherwise resolves the subject+function grammar and chooses the first
    mode that maps to an implemented diagram type."""
    if visual_mode:
        return visual_mode
    pref = grammar_for(subject, beat_function)
    for mode in pref:
        if mode in EXPLANATORY_MODES:
            return mode
    return "COMPARISON"


def is_explanatory_mode(mode: str) -> bool:
    """True if the mode is one of the brief's 'transformation-priority' modes
    (more informative than a decorative cinematic plate)."""
    return mode.upper() in {
        "COMPARISON", "TRANSFORMATION", "SCALE", "TIMELINE", "MAP", "CUTAWAY",
        "BLUEPRINT", "STRUCTURAL_DIAGRAM", "CROSS_SECTION", "MACRO_DETAIL",
        "CELLULAR_DIAGRAM", "MOLECULAR_PROCESS", "GEOGRAPHIC_TRANSFORMATION",
        "CLIMATE_RECON", "ASTRONOMICAL_SCALE", "ORBITAL_DIAGRAM",
        "ARCHIVAL_ILLUSTRATION", "MAP_TRANSFORMATION", "FORCE_DIAGRAM",
        "ANIMATION",
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
