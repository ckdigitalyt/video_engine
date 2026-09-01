"""Load + validate story.json / visual_plan.json / build/edit_plan.json, and
build build/edit_plan.json from the story pair (pre-TTS estimates).

Symbolic visual_plan references (key_regions names like "atmosphere_band",
named points like "lower-left", number positions like "panel-lower-third")
are resolved here into concrete panel-normalized geometry for edit_plan.
Camera windows are clamped via motion.clamp_window; every clamp is reported
as a warning so off-plate plan coords stay visible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import motion
from .text_ass import load_style

STORY_REQUIRED = ("story_id", "title", "beats")
VP_REQUIRED = ("story_id", "render", "assets_planned", "beats")
SHOT_REQUIRED = ("shot_id", "asset", "camera")
TYPOGRAPHY_KINDS_VP = ("NUMBER_POP", "TEXT_REVEAL", "CALLOUT")
CAPTION_MODES_VP = ("phrase", "none", "none_final_card")

# key_regions-style name -> panel-normalized rect {x, y, w, h}.
# Deterministic estimates from visual_plan key_regions; refine as plates land.
REGION_TARGETS = {
    "atmosphere_band": {"x": 0.10, "y": 0.36, "w": 0.80, "h": 0.26},
    "atmosphere_line": {"x": 0.12, "y": 0.60, "w": 0.76, "h": 0.20},
    "marker_10km": {"x": 0.28, "y": 0.52, "w": 0.44, "h": 0.16},
    "marker_100km": {"x": 0.24, "y": 0.24, "w": 0.52, "h": 0.16},
    "apex_100km": {"x": 0.52, "y": 0.10, "w": 0.40, "h": 0.28},
    "meteor": {"x": 0.26, "y": 0.30, "w": 0.48, "h": 0.34},
    "aurora": {"x": 0.10, "y": 0.06, "w": 0.80, "h": 0.30},
    "board_sketch": {"x": 0.56, "y": 0.16, "w": 0.36, "h": 0.40},
    "figure": {"x": 0.06, "y": 0.20, "w": 0.52, "h": 0.62},
    "station": {"x": 0.26, "y": 0.10, "w": 0.48, "h": 0.40},
    "jet": {"x": 0.26, "y": 0.48, "w": 0.48, "h": 0.36},
    "full_ladder": {"x": 0.06, "y": 0.06, "w": 0.88, "h": 0.88},
    "arc": {"x": 0.06, "y": 0.10, "w": 0.88, "h": 0.78},
    "road_start": {"x": 0.04, "y": 0.62, "w": 0.34, "h": 0.32},
}

# Named panel points for arrows (panel-normalized x, y).
POINT_NAMES = {
    "lower-left": (0.14, 0.84), "lower-right": (0.86, 0.84),
    "upper-left": (0.14, 0.16), "upper-right": (0.86, 0.16),
    "center": (0.50, 0.50),
}

# Symbolic NUMBER_POP positions -> frame coords [x, y] (panel zone).
POS_PRESETS = {
    "panel-lower-third": [540.0, 1130.0],
    "panel-upper": [540.0, 640.0],
    "panel-center": [540.0, 850.0],
    "near-jet": [540.0, 1000.0],
    "near-station": [540.0, 760.0],
    "caption_zone": [540.0, 1410.0],
}


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _load(rep, path):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        rep["errors"].append(f"{Path(path).name}: file not found ({path})")
    except json.JSONDecodeError as e:
        rep["errors"].append(f"{Path(path).name}: invalid JSON ({e})")
    return None


def validate(paths, story_id="space_closer"):
    """-> report {ok: [], warnings: [], errors: []}. Missing assets are
    warnings (acceptable pre-render); schema/primitive/kind problems are
    errors."""
    rep = {"ok": [], "warnings": [], "errors": []}
    story_dir = Path(paths.stories) / story_id

    story = _load(rep, story_dir / "story.json")
    if story is not None:
        for k in STORY_REQUIRED:
            if k not in story:
                rep["errors"].append(f"story.json missing key: {k}")
        beats = story.get("beats") or []
        for i, b in enumerate(beats):
            for k in ("beat_id", "narration"):
                if k not in b:
                    rep["errors"].append(f"story.json beats[{i}] missing key: {k}")
        if not rep["errors"]:
            rep["ok"].append(f"story.json: {len(beats)} beats, title={story.get('title')!r}")

    vp = _load(rep, story_dir / "visual_plan.json")
    if vp is None:
        return rep
    for k in VP_REQUIRED:
        if k not in vp:
            rep["errors"].append(f"visual_plan.json missing key: {k}")
    render = vp.get("render") or {}
    if render and (render.get("width"), render.get("height"), render.get("fps")) != (1080, 1920, 30):
        rep["errors"].append("visual_plan render is not 1080x1920@30: "
                             f"{render.get('width')}x{render.get('height')}@{render.get('fps')}")
    panel = render.get("panel") or {}
    if panel and (panel.get("x"), panel.get("y"), panel.get("w"), panel.get("h")) != (0, 460, 1080, 780):
        rep["errors"].append(f"visual_plan panel != 0,460,1080x780: {panel}")

    asset_ids = {a.get("asset_id") for a in vp.get("assets_planned") or []}
    seen = set()
    nshots = 0
    for b in vp.get("beats") or []:
        for s in b.get("shots") or []:
            nshots += 1
            sid = str(s.get("shot_id", f"{b.get('beat_id')}#{nshots}"))
            if sid in seen:
                rep["errors"].append(f"duplicate shot_id: {sid}")
            seen.add(sid)
            for k in SHOT_REQUIRED:
                if k not in s:
                    rep["errors"].append(f"{sid}: missing key {k}")
            cam = s.get("camera") or {}
            if cam.get("primitive") not in motion.CAMERA_PRIMITIVES:
                rep["errors"].append(f"{sid}: unknown camera primitive {cam.get('primitive')!r}")
            else:
                _, _, _, notes = motion.resolve_camera(cam)
                if notes:
                    rep["warnings"].append(
                        f"{sid}: camera clamped to plate/canvas ({'; '.join(notes)})")
            for ov in s.get("overlays") or []:
                if ov.get("kind") not in motion.OVERLAY_KINDS:
                    rep["errors"].append(f"{sid}: unknown overlay kind {ov.get('kind')!r}")
            for tp in s.get("typography") or []:
                if tp.get("kind") not in TYPOGRAPHY_KINDS_VP:
                    rep["errors"].append(f"{sid}: unknown typography kind {tp.get('kind')!r}")
            caps = s.get("captions", "phrase")
            if caps not in CAPTION_MODES_VP:
                rep["warnings"].append(f"{sid}: unusual captions mode {caps!r}")
    rep["ok"].append(f"visual_plan.json: {len(vp.get('beats') or [])} beats, {nshots} shots")

    missing = sorted(a for a in asset_ids if a and not (Path(paths.assets) / f"{a}.png").exists())
    if missing:
        rep["warnings"].append(f"assets missing on disk (OK pre-render): {', '.join(missing)}")
    else:
        rep["ok"].append(f"all {len(asset_ids)} planned assets present")

    st = load_style(paths)
    for nm, pk, fk in (("caption", "_caption_font_path", "_caption_family"),
                       ("number", "_number_font_path", "_number_family"),
                       ("endcard", "_endcard_font_path", "_endcard_family")):
        if Path(st[pk]).exists():
            rep["ok"].append(f"{nm} font: {Path(st[pk]).name}")
        else:
            rep["warnings"].append(f"{nm} font file missing -> libass fallback {st[fk]!r}")

    ep = Path(paths.build) / "edit_plan.json"
    if ep.exists():
        e = _load(rep, ep)
        if e is not None:
            rep["errors"].extend(validate_edit_plan(e))
            rep["ok"].append(f"edit_plan.json: {len(e.get('shots') or [])} shots")
    else:
        rep["warnings"].append("build/edit_plan.json missing -> run validate --make-edit-plan")
    return rep


def validate_edit_plan(eplan):
    errs = []
    for k in ("story_id", "fps", "size", "shots"):
        if k not in eplan:
            errs.append(f"edit_plan missing key: {k}")
    if eplan.get("fps") not in (30, 30.0):
        errs.append("edit_plan fps != 30")
    if tuple(eplan.get("size") or ()) != (1080, 1920):
        errs.append("edit_plan size != [1080, 1920]")
    for s in eplan.get("shots") or []:
        sid = str(s.get("shot_id", "?"))
        for k in ("shot_id", "asset", "camera", "duration_s"):
            if k not in s:
                errs.append(f"{sid}: missing key {k}")
        cam = s.get("camera") or {}
        if cam.get("primitive") not in motion.CAMERA_PRIMITIVES:
            errs.append(f"{sid}: unknown camera primitive {cam.get('primitive')!r}")
        try:
            if float(s.get("duration_s", 0)) <= 0:
                errs.append(f"{sid}: duration_s must be > 0")
        except (TypeError, ValueError):
            errs.append(f"{sid}: duration_s not a number")
        if str(s.get("transition_in", "CUT")).upper() not in motion.TRANSITIONS:
            errs.append(f"{sid}: unknown transition_in {s.get('transition_in')!r}")
        for ov in s.get("overlays") or []:
            if ov.get("kind") not in motion.OVERLAY_KINDS:
                errs.append(f"{sid}: unknown overlay kind {ov.get('kind')!r}")
        for tp in s.get("typography") or []:
            if tp.get("kind") not in ("caption", "number_pop", "end_card"):
                errs.append(f"{sid}: unknown typography kind {tp.get('kind')!r}")
    return errs


def print_report(rep):
    for level, tag in (("errors", "FAIL"), ("warnings", "WARN"), ("ok", "OK")):
        for m in rep[level]:
            print(f"- [{tag:4}] {m}")
    print(f"validate: {len(rep['ok'])} ok, {len(rep['warnings'])} warn, "
          f"{len(rep['errors'])} fail")
    return 1 if rep["errors"] else 0


# --------------------------------------------------------------------------
# symbolic reference resolvers (visual_plan -> concrete edit_plan geometry)
# --------------------------------------------------------------------------

def resolve_region(name, rep=None):
    """key_regions-style name -> panel-normalized rect (deterministic)."""
    if isinstance(name, dict) and "x" in name:
        return {"x": float(name["x"]), "y": float(name["y"]),
                "w": float(name.get("w", 0.30)), "h": float(name.get("h", 0.20))}
    s = str(name or "").strip().lower()
    if s:
        for key, rect in REGION_TARGETS.items():
            if key in s or s in key:
                return dict(rect)
    if rep is not None:
        rep["warnings"].append(f"region {name!r} unresolved -> center fallback")
    return {"x": 0.28, "y": 0.30, "w": 0.44, "h": 0.40}


def resolve_point(name):
    """Named point / region / dict -> panel-normalized (x, y)."""
    if isinstance(name, dict) and "x" in name:
        return (float(name["x"]), float(name["y"]))
    s = str(name or "").strip().lower()
    if s in POINT_NAMES:
        return POINT_NAMES[s]
    r = REGION_TARGETS.get(s)
    if r is None:
        for key, rect in REGION_TARGETS.items():
            if key in s:
                r = rect
                break
    if r is not None:
        return (r["x"] + r["w"] / 2.0, r["y"] + r["h"] / 2.0)
    return POINT_NAMES["center"]


def resolve_pos(pos):
    """Symbolic or explicit NUMBER_POP position -> frame coords [x, y]."""
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        return [float(pos[0]), float(pos[1])]
    s = str(pos or "").strip().lower()
    for key, xy in POS_PRESETS.items():
        if key in s:
            return list(xy)
    return [540.0, 850.0]


def _region_center(name):
    p = resolve_point(name)
    return {"x": p[0], "y": p[1]}


def _label_near(anchor):
    p = resolve_point(anchor)
    return {"x": max(0.03, p[0] - 0.20), "y": max(0.03, p[1] - 0.18)}


# --------------------------------------------------------------------------
# edit_plan builder (pre-TTS estimates)
# --------------------------------------------------------------------------

def split_phrases(text, max_words=9):
    """Narration -> caption phrase groups: sentence split, then <= max_words
    chunks; tiny tails merge into the previous phrase."""
    text = re.sub(r"\s+", " ", str(text)).strip()
    if not text:
        return []
    phrases = []
    for sent in re.split(r"(?<=[.!?])\s+", text):
        words = sent.split()
        if len(words) <= max_words:
            phrases.append(_tidy(sent))
            continue
        cur = []
        for w in words:
            cur.append(w)
            if len(cur) >= max_words:
                phrases.append(_tidy(" ".join(cur)))
                cur = []
        if cur:
            if len(cur) <= 3 and phrases:
                phrases[-1] = phrases[-1] + " " + " ".join(cur)
            else:
                phrases.append(_tidy(" ".join(cur)))
    return [p for p in phrases if p]


def _tidy(s):
    s = s.strip()
    if s.endswith("."):
        s = s[:-1]
    return s.strip()


def make_edit_plan(paths, story_id="space_closer"):
    """story.json + visual_plan.json -> build/edit_plan.json.

    Durations: shot duration_est x beat split (shots scaled so each beat
    sums to its duration_est). Captions: beat narration split into phrase
    groups, laid across the beat timeline proportional to word count, then
    assigned to the shot containing each phrase's midpoint (shot-local
    t0/t1). Returns (plan, report)."""
    story_dir = Path(paths.stories) / story_id
    story = json.loads((story_dir / "story.json").read_text())
    vp = json.loads((story_dir / "visual_plan.json").read_text())
    rep = {"ok": [], "warnings": [], "errors": []}
    story_beats = {b.get("beat_id"): b for b in story.get("beats") or []}

    shots_out = []
    for vb in vp.get("beats") or []:
        bid = vb.get("beat_id")
        sb = story_beats.get(bid) or {}
        narration = sb.get("narration", "")
        vshots = vb.get("shots") or []
        if not vshots:
            continue
        est_sum = sum(float(s.get("duration_est", 0)) for s in vshots) or 1.0
        beat_target = float(vb.get("duration_est", est_sum))
        scale = beat_target / est_sum
        durs = [float(s.get("duration_est", 0)) * scale for s in vshots]
        starts = []
        acc = 0.0
        for d in durs:
            starts.append(acc)
            acc += d

        phrases = split_phrases(narration)
        total_words = sum(len(p.split()) for p in phrases) or 1
        cues = []
        cacc = 0.0
        for ph in phrases:
            d = beat_target * (len(ph.split()) / total_words)
            cues.append({"text": ph, "t0": cacc, "t1": cacc + d})
            cacc += d

        for i, s in enumerate(vshots):
            sid = str(s["shot_id"])
            dur = durs[i]
            off = starts[i]
            typ, ovs = [], []
            caps = []
            if str(s.get("captions", "phrase")) == "phrase":
                for c in cues:
                    mid = (c["t0"] + c["t1"]) / 2.0
                    if off <= mid < off + dur or (i == len(vshots) - 1 and mid >= off):
                        caps.append({"text": c["text"],
                                     "t0": round(max(0.0, c["t0"] - off), 3),
                                     "t1": round(min(dur, c["t1"] - off), 3)})
            for tp in s.get("typography") or []:
                k = tp.get("kind")
                at = float(tp.get("at", 0.5))
                if k == "NUMBER_POP":
                    typ.append({"kind": "number_pop", "text": tp["text"], "at": at,
                                "pos": resolve_pos(tp.get("pos")),
                                "color": tp.get("color", "rust"), "dur": 1.8})
                elif k == "TEXT_REVEAL":
                    typ.append({"kind": "caption", "text": tp["text"],
                                "mode": "word_reveal", "t0": at,
                                "t1": round(min(dur, at + 3.2), 3)})
                elif k == "CALLOUT":
                    ovs.append({"kind": "CALLOUT", "text": tp.get("text", ""),
                                "anchor": _region_center(tp.get("anchor")),
                                "label": _label_near(tp.get("anchor")),
                                "at": at, "color": "ink",
                                "dur": round(min(3.0, max(1.5, dur - at - 0.3)), 3)})
            for ov in s.get("overlays") or []:
                k = ov.get("kind")
                at = float(ov.get("at", 0.4))
                if k == "HIGHLIGHT":
                    style = "circle" if "circle" in str(ov.get("style", "circle")) else "rect"
                    ovs.append({"kind": "HIGHLIGHT", "style": style, "color": "rust",
                                "target": resolve_region(ov.get("target"), rep),
                                "at": at,
                                "dur": round(min(2.6, max(1.2, dur - at - 0.2)), 3)})
                elif k == "ARROW_DRAW":
                    ovs.append({"kind": "ARROW_DRAW",
                                "from": list(resolve_point(ov.get("from"))),
                                "to": list(resolve_point(ov.get("to"))),
                                "at": at, "dur": 0.9, "color": "ink",
                                "hold": round(min(1.6, max(0.6, dur - at - 1.0)), 3)})
                elif k == "CALLOUT":
                    ovs.append({"kind": "CALLOUT", "text": ov.get("text", ""),
                                "anchor": _region_center(ov.get("anchor")),
                                "label": _label_near(ov.get("anchor")),
                                "at": at, "color": "ink",
                                "dur": round(min(3.0, max(1.5, dur - at - 0.3)), 3)})
            shot = {"shot_id": sid, "asset": s["asset"],
                    "camera": {"primitive": s["camera"]["primitive"],
                               "from": dict(s["camera"].get("from") or {}),
                               "to": dict(s["camera"].get("to") or {})},
                    "duration_s": round(dur, 3),
                    "overlays": ovs, "typography": typ, "captions": caps,
                    "transition_in": str(s.get("transition_in", "CUT")).upper()}
            if s.get("end_card"):
                typ.append({"kind": "end_card", "text": s["end_card"],
                            "at": round(max(0.5, dur - 3.4), 3), "dur": 3.2})
            shots_out.append(shot)

    eplan = {"story_id": story.get("story_id", story_id), "fps": 30,
             "size": [1080, 1920], "panel": {"x": 0, "y": 460, "w": 1080, "h": 780},
             "generated": "pre-TTS estimates from visual_plan duration_est; "
                          "word-proportional phrase captions; symbolic targets resolved",
             "shots": shots_out}
    out = Path(paths.build) / "edit_plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(eplan, indent=2) + "\n")
    return eplan, rep
