"""V5 plan wrapper — V4 + subject-specific visual grammar (V6 P1) + bed plan
+ V6.2 Dynamic Overlay Anti-Collision Compiler + kinetic stamping.

Additive on top of planv4:
  - subject hint (from story.json) -> grammar_for(...) -> recommended mode
  - audio_bed_plan.json: list of bed files per shot (None for continuity)
  - sfx plan: list of {file, at, dur, shot_id, reason}
  - visual_grammar section in edit_plan.json for downstream resolvers

V6.2 (Jade_todo §2/§4/§5):
  - Overlay coordinates standardized to CARD space [0,1] (the rendered
    PANEL: 1080x780 at y=176 on the 1080x1920 canvas). Legacy VISUAL-space
    rects (normalized to the 1328-tall visual zone) are rescaled, then
    clamped out of the header (y<0.18) / footer (y>0.85) exclusion zones.
  - Text dedup against the plate card manifest (parsed from the story's
    deterministic make_cards.py): a NUMBER_POP whose text already exists
    on the plate is suppressed and converted into a kinetic PULSE on the
    existing element (kind preserved so alignment gates still see it).
  - Temporally-overlapping event rects are pushed apart (no stacking).
  - Kinetic shots (animated clocks / streamlines) stamped per asset.
  - build/overlay_plan.json written as the compiler's ground truth.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine import flags as _flags
from engine import motion_v6 as _motion_v6

# Card geometry (must match motion_v6 PANEL_* and the composev5 overlay y)
# V10 §1 — native 9:16: the card fills the Shorts focal band (Y 0.15-0.75
# of the 1080x1920 canvas). Rollback: V10_VERTICAL=0 restores the legacy
# 1080x780 horizontal-monitor card at y=176.
if _flags.vertical10():
    CARD_W, CARD_H, CARD_Y0 = 1080, 1152, 288
else:
    CARD_W, CARD_H, CARD_Y0 = 1080, 780, 176
# V11_FULLBLEED (Jade_todo_v11 P0 true 9:16): the card grows to own 65% of
# the canvas (y 192..1440) and the freed top band keeps the brand block off
# the art. Card bottom stays at 1440 so the caption band below the card is
# identical in both geometries. Requires V10_VERTICAL (checked in fullbleed11).
if _flags.fullbleed11():
    CARD_W, CARD_H, CARD_Y0 = 1080, 1248, 192
HEADER_Y = 0.18    # card-relative exclusion zone: card header / title bar
FOOTER_Y = 0.85    # card-relative exclusion zone: card footer band
LEGACY_VIS_H = 1328.0   # pre-V6.2 rects were normalized to VISUAL_RECT height

_PLATE_W, _PLATE_H = 1536.0, 1024.0
# V10 — stage geometry follows the active panel (motion_v6 derives
# CONTENT/CANVAS from PANEL_W/H); the baseline values are identical.
_STAGE_W = float(_motion_v6.STAGE_W)
_STAGE_H = float(_motion_v6.CONTENT_H)
_STAGE_PAD = float(_motion_v6.CANVAS_PAD_Y)


def _norm_text(s: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def _plate_manifest(story_dir: Path) -> dict:
    """Parse the story's make_cards.py into {asset: [text elements]}.

    Elements: {text, cx, cy, w, h} in plate pixels (1536x1024). Position
    expressions are evaluated against W/H and the function's own simple
    scalar assignments; failures degrade to text-only entries (dedup still
    works; pulses fall back to the event's own rect).
    """
    mc = Path(story_dir) / "make_cards.py"
    if not mc.exists():
        return {}
    src = mc.read_text()
    amap = dict(re.findall(r'"([A-Za-z0-9_]+)":\s*(\w+)\(\)', src))
    parts = re.split(r"\ndef (\w+)\(", src)
    funcs = {}
    it = iter(parts[1:])
    for fname, body in zip(it, it):
        funcs[fname] = body
    manifest = {}
    base_ns = {"W": _PLATE_W, "H": _PLATE_H}
    for fname, body in funcs.items():
        local = dict(base_ns)
        for m in re.finditer(r"^[ \t]*(\w+)\s*=\s*([-\d\s\.\+\*/\(\)]+)$",
                             body, re.M):
            try:
                local[m.group(1)] = float(eval(  # noqa: S307 (guarded, numeric)
                    m.group(2), {"__builtins__": {}}, dict(local)))
            except Exception:
                pass

        def _xy(expr):
            try:
                return float(eval(expr, {"__builtins__": {}}, dict(local)))  # noqa: S307
            except Exception:
                return None

        els = []
        for m in re.finditer(
                r'big_number\(d,\s*"([^"]+)"\s*,\s*\(([^)]+)\)\s*,\s*(\d+)',
                body):
            t, pos, size = m.group(1), m.group(2).split(","), float(m.group(3))
            cx, cy = _xy(pos[0]), _xy(pos[-1])
            if cx is None or cy is None:
                els.append({"text": t})
                continue
            els.append({"text": t, "cx": cx, "cy": cy,
                        "w": max(120.0, len(t) * size * 0.48), "h": size * 1.25})
        for m in re.finditer(r'label\(d,\s*"([^"]+)"\s*,\s*\(([^)]+)\)', body):
            t, pos = m.group(1), m.group(2).split(",")
            cx, cy = _xy(pos[0]), _xy(pos[-1])
            if cx is None or cy is None:
                els.append({"text": t})
                continue
            els.append({"text": t, "cx": cx, "cy": cy,
                        "w": max(90.0, len(t) * 24.0), "h": 64.0})
        for m in re.finditer(r'title_bar\(d,\s*"([^"]+)"', body):
            t = m.group(1)
            els.append({"text": t, "cx": _PLATE_W / 2, "cy": 105.0,
                        "w": max(200.0, len(t) * 34.0), "h": 95.0})
        for m in re.finditer(r'footer_band\(d,\s*"([^"]+)"', body):
            t = m.group(1)
            els.append({"text": t, "cx": _PLATE_W / 2, "cy": 965.0,
                        "w": max(200.0, len(t) * 22.0), "h": 80.0})
        for m in re.finditer(r'd\.text\(\s*\(([^)]+)\)\s*,\s*"([^"]+)"', body):
            pos, t = m.group(1).split(","), m.group(2)
            cx, cy = _xy(pos[0]), _xy(pos[-1])
            if cx is None or cy is None or not t.strip():
                continue
            els.append({"text": t, "cx": cx, "cy": cy,
                        "w": max(80.0, len(t) * 17.0), "h": 42.0})
        if els:
            manifest[fname] = els
    out = {}
    for asset, fn in amap.items():
        out[asset] = manifest.get(fn, [])
    for asset in out:
        if not out[asset]:
            fn = asset.lower()
            if fn in funcs:
                out[asset] = manifest.get(fn, [])
    return out


def _plate_el_to_card(el: dict, cam: dict) -> list:
    """Map a plate-pixel element bbox into card space via the camera's
    from-window (the framing visible when the pulse starts)."""
    fs = float((cam or {}).get("from_scale") or 1.0)
    w_f = min(1.0, 1.0 / max(0.01, fs))
    if _flags.vertical10():
        # V10 §1 — the camera window carries the portrait re-scale (see
        # motion_v6.clamp_window); overlay anchoring must use the same
        # window or pulses/pop anchors drift off their plate elements.
        w_f = min(w_f * _motion_v6.CONTENT_H / _motion_v6.CANVAS_H, 1.0)
    cx = (cam or {}).get("from_cx")
    cy = (cam or {}).get("from_cy")
    if cx is None:
        cx = (cam or {}).get("cx") or 0.5
    if cy is None:
        cy = (cam or {}).get("cy") or 0.5
    cx_f, cy_f = float(cx), float(cy)
    ex = el["cx"] / _PLATE_W * _STAGE_W
    ey = _STAGE_PAD + el["cy"] / _PLATE_H * _STAGE_H
    ew = max(90.0, el.get("w", 200.0)) / _PLATE_W * _STAGE_W
    eh = max(70.0, el.get("h", 90.0)) / _PLATE_H * _STAGE_H
    win_w = w_f * _STAGE_W
    win_h = w_f * (_STAGE_H + 2 * _STAGE_PAD)
    wx = cx_f * _STAGE_W - win_w / 2.0
    if _flags.vertical10():
        # V10 — camera y convention: y_top = CONTENT_H*cy + PAD - CANVAS_H*w/2
        wy = cy_f * _STAGE_H + _STAGE_PAD - win_h / 2.0
    else:
        wy = cy_f * (_STAGE_H + 2 * _STAGE_PAD) - win_h / 2.0
    # pulse reads best slightly larger than the element itself
    m = 1.22
    return [(ex - ew / 2.0 * m - wx) / win_w,
            (ey - eh / 2.0 * m - wy) / win_h,
            ew * m / win_w, eh * m / win_h]


def _clamp_card_rect(rect: list) -> list:
    x, y, w, h = rect
    w = max(0.05, min(w, 0.96))
    h = max(0.04, min(h, FOOTER_Y - HEADER_Y))
    x = min(max(x, 0.02), 0.98 - w)
    if y < HEADER_Y:
        y = HEADER_Y
    if y + h > FOOTER_Y:
        y = FOOTER_Y - h
    y = max(HEADER_Y, min(y, FOOTER_Y - h))
    return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]


def _event_hold(ev: dict, dur: float) -> float:
    kind = str(ev.get("kind", ""))
    t0 = float(ev.get("t", 0.0))
    if kind == "number_pop":
        return min(2.6, max(0.4, dur - t0))
    if kind == "highlight":
        return min(2.8, max(0.4, dur - t0))
    if kind == "text_emphasis":
        return min(1.4, max(0.4, dur - t0))
    return max(0.4, dur - t0)


def _rects_overlap(a: list, b: list, pad: float = 0.01) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw + pad <= bx or bx + bw + pad <= ax or
                ay + ah + pad <= by or by + bh + pad <= ay)


def _overlay_compiler(eplan: dict, story_dir: Path) -> dict:
    """V6.2 §2 — dedup, zone enforcement, collision resolution, kinetic."""
    from engine import visual_grammar

    manifest = _plate_manifest(story_dir)
    subject = (eplan.get("visual_grammar_plan") or {}).get("subject", "")
    stats = {"pulses": 0, "clamped": 0, "collisions": 0, "dedup": 0}
    per_shot = {}

    for s in eplan.get("shots", []):
        dur = float(s.get("duration_s", 6.0))
        cam = s.get("camera") or {}
        asset = str(s.get("asset", ""))
        els = manifest.get(asset, [])
        events = []
        for ev in (s.get("events") or [])[:]:
            spec = dict(ev.get("spec") or {})
            kind = str(ev.get("kind", ""))
            rect = spec.get("rect")
            if not rect and kind not in ("number_pop", "highlight"):
                events.append(ev)
                continue
            if rect:
                x, y, w, h = [float(v) for v in rect]
                # legacy VISUAL-space rects (y+h fraction of the 1328-tall
                # zone) -> card space; anything already inside card range
                # with y+h<=1.005 keeps card interpretation.
                if y * (LEGACY_VIS_H / CARD_H) + h * (LEGACY_VIS_H / CARD_H) > 1.005 \
                        or y > 0.63:
                    y *= LEGACY_VIS_H / CARD_H
                    h *= LEGACY_VIS_H / CARD_H
                rect_c = [x, y, w, h]
                text = str(spec.get("text", ""))
                if kind == "number_pop" and text:
                    key = _norm_text(text)
                    hit = None
                    for el in els:
                        et = _norm_text(el.get("text", ""))
                        if not et:
                            continue
                        digs_e = re.sub(r"[^0-9]", "", key)
                        digs_p = re.sub(r"[^0-9]", "", et)
                        if et == key or (digs_e and digs_e == digs_p):
                            hit = el
                            break
                    if hit is not None:
                        if all(k in hit for k in ("cx", "cy")):
                            prect = _clamp_card_rect(_plate_el_to_card(hit, cam))
                        else:
                            prect = _clamp_card_rect(rect_c)
                        spec["rect"] = prect
                        spec["pulse"] = True
                        spec["suppressed_original"] = True
                        ev = {**ev, "spec": spec}
                        stats["pulses"] += 1
                        stats["dedup"] += 1
                        events.append(ev)
                        continue
                rect_c = _clamp_card_rect(rect_c)
                if rect_c != [round(v, 4) for v in (x, y, w, h)]:
                    stats["clamped"] += 1
                spec["rect"] = rect_c
                ev = {**ev, "spec": spec}
            events.append(ev)

        # temporal + spatial collision pass (later event yields)
        ordered = sorted(
            [e for e in events if (e.get("spec") or {}).get("rect")],
            key=lambda e: float(e.get("t", 0.0)))
        # same-shot duplicate text suppression (V6.2 §2 text-layer dedup):
        # a shot never stamps the same dynamic text twice — the earliest
        # occurrence wins, later duplicates are dropped.
        seen_texts = set()
        deduped = []
        for ev in ordered:
            if str(ev.get("kind")) == "number_pop":
                key = _norm_text((ev.get("spec") or {}).get("text", ""))
                if key:
                    if key in seen_texts:
                        stats["dedup"] += 1
                        continue
                    seen_texts.add(key)
            deduped.append(ev)
        kept_rects = [(e, (e.get("spec") or {}).get("rect")) for e in deduped]
        placed = []
        _stack = 0
        for ev, r0 in kept_rects:
            r = list(r0)
            t0 = float(ev.get("t", 0.0))
            t1 = t0 + _event_hold(ev, dur)
            for (pt0, pt1, pr) in placed:
                if t0 < pt1 and pt0 < t1 and _rects_overlap(r, pr):
                    r[1] = pr[1] + pr[3] + 0.02
                    if _flags.vertical10():
                        # V10 §1 — diagonal stage stacking: the portrait card
                        # cannot host wide horizontal chains, so colliding
                        # events stair-step down the card (alternating x
                        # offset) instead of piling straight down a column.
                        r[0] += 0.09 if _stack % 2 == 0 else -0.09
                        _stack += 1
                    r = _clamp_card_rect(r)
                    if _rects_overlap(r, pr):  # cannot fit below -> above
                        r[1] = max(HEADER_Y, pr[1] - r[3] - 0.02)
                        r = _clamp_card_rect(r)
                    ev["spec"]["rect"] = r
                    stats["collisions"] += 1
            placed.append((t0, t1, r))
        # rebuild the shot's event list: deduped rect-events (plan order)
        # + all events without rects, in original order
        dropped = set()
        kept = {}
        for e in deduped:
            kept[id(e)] = True
        new_events = []
        for ev in events:
            has_rect = bool((ev.get("spec") or {}).get("rect"))
            if has_rect and id(ev) not in kept:
                dropped.add(id(ev))
                continue
            new_events.append(ev)
        events = new_events

        kin = visual_grammar.kinetic_spec(s, subject)
        if kin:
            s["kinetic"] = kin
        s["events"] = events
        per_shot[str(s.get("shot_id"))] = {
            "events": [{"kind": e.get("kind"), "t": e.get("t"),
                        "spec": e.get("spec")} for e in events],
            "kinetic": kin,
        }

    eplan["engine"] = "v6.2"
    eplan["overlay_compiler"] = {
        "card": {"x": 0, "y": CARD_Y0, "w": CARD_W, "h": CARD_H},
        "zones": {"header_y": HEADER_Y, "footer_y": FOOTER_Y},
        "plate_manifest_assets": sorted(manifest.keys()),
        "totals": stats,
        "per_shot": per_shot,
    }
    return stats


def _motion_class(s: dict) -> str:
    """A/B/C motion-information tag for a plan shot (see make_edit_plan_v5).

    C beats B beats priority: any explanatory living event wins; then
    structural events; explanatory kinetic types count as C, other kinetic
    as B; a shot with only camera motion (or none) is A — camera movement
    does not count as information (Jade_todo_v11 P0).
    """
    kinds = {str((e or {}).get("kind", "")) for e in (s.get("events") or [])}
    if kinds & {"reveal", "isolate", "flow", "fill_state", "consequence"}:
        return "C"
    if kinds & {"number_pop", "highlight", "text_emphasis", "stage_overlay"}:
        return "B"
    k = s.get("kinetic")
    if k:
        kt = str(k.get("type", "") if isinstance(k, dict) else k).lower()
        # C: the animation shows a process/field/transformation (causal);
        # B: the animation restyles emphasis without causal content
        # (pulse/countup/drift/particles). Camera movement is never info.
        if kt in {"streamlines", "clock_sweep", "clocks", "orbit", "morph",
                  "heatmap", "flow"}:
            return "C"
        return "B"
    return "A"


def make_edit_plan_v5(paths, story_id: str):
    from engine import planv4, visual_grammar
    from engine import depth as _depth
    eplan, rep = planv4.make_edit_plan_v4(paths, story_id)
    story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
    vp = json.loads((Path(paths.stories) / story_id / "visual_plan.json").read_text())

    subject = visual_grammar.detect_subject(story, vp)
    # V11 P1 §3 — brand ≠ visual vocabulary: the bible may declare an
    # explicit topic grammar for THIS story (author's chosen vocabulary);
    # it overrides the inferred SUBJECT_GRAMMAR and is reported in the
    # visual_grammar_plan so plate authoring and QA see the same choice.
    from engine import bible as _bible
    bible = _bible.load_bible(Path(paths.stories) / story_id)
    topic_grammar = bible.get("topic_grammar") if isinstance(
        bible.get("topic_grammar"), (list, tuple)) else None
    grammar = visual_grammar.grammar_for(subject, "", topic_grammar=topic_grammar)
    # Per-shot recommended mode
    fns = {b.get("beat_id"): str(b.get("function", "")).upper()
           for b in story.get("beats", [])}
    beat_of = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            beat_of[str(s["shot_id"])] = b.get("beat_id")
    grammar_plan = []
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            beat_fn = fns.get(b.get("beat_id"), "")
            rec = visual_grammar.recommend_mode(
                subject, beat_fn, s.get("claim", ""),
                visual_mode=str(s.get("visual_mode", ""))
            )
            entry = {
                "shot_id": str(s["shot_id"]),
                "subject": subject,
                "beat_function": beat_fn,
                "recommended_mode": rec,
                "is_explanatory": visual_grammar.is_explanatory_mode(rec),
            }
            # V11 P1 §4 — real 2.5D depth: planner layer tagging per shot
            # (authored visual_plan `depth.layers` wins; deterministic
            # mode grammar otherwise — never randomization).
            entry["depth_layers"] = list(_depth.layer_for(s, rec))
            grammar_plan.append(entry)
            # Annotate the shot in eplan (read-only field for the renderer)
            svp_match = next(
                (x for x in eplan.get("shots", []) if str(x["shot_id"]) == str(s["shot_id"])),
                None)
            if svp_match is not None:
                svp_match.setdefault("visual_grammar", {})
                svp_match["visual_grammar"]["subject"] = subject
                svp_match["visual_grammar"]["recommended_mode"] = rec
                svp_match["depth_layers"] = entry["depth_layers"]
                # V11 P1 §2/§4 — authored surprise/depth declarations ride
                # through to the edit plan (planv4 rebuilds shots with a
                # field whitelist; planv8's checks read these).
                for _k in ("surprise", "depth"):
                    if isinstance(s.get(_k), dict):
                        svp_match[_k] = s[_k]
                svp_match["beat_id"] = b.get("beat_id")

    # V6.2 §2/§4: overlay compiler + kinetic stamping (mutates eplan shots)
    stats = _overlay_compiler(eplan, Path(paths.stories) / story_id)

    # V11 EXPLANATORY_MOTION_RATIO (Jade_todo_v11 P0): provisional A/B/C tag
    # per shot — plan5's event set predates planv8's living-event stamping,
    # so planv8 RE-TAGS inferred shots after stamping (authored overrides,
    # marked motion_class_authored, always win). QA consumes the plan8 tags.
    # C = explanatory, B = structural, A = decorative (camera-only/static;
    # camera movement is NOT information) — engine/motion_class.py consumes.
    mc = {}
    for s in eplan.get("shots", []):
        authored = str(s.get("motion_class") or "").upper()
        if authored in {"A", "B", "C"}:
            s["motion_class_authored"] = True
        else:
            s.pop("motion_class", None)
            authored = ""
        cls = authored or _motion_class(s)
        s["motion_class"] = cls
        mc[str(s.get("shot_id"))] = cls
    eplan["motion_classes"] = mc

    eplan["engine"] = "v6.2"
    eplan["visual_grammar_plan"] = {
        "subject": subject,
        "default_grammar": list(grammar),
        "topic_grammar_declared": list(topic_grammar) if topic_grammar else None,
        "per_shot": grammar_plan,
    }

    out = Path(paths.build) / "edit_plan.json"
    out.write_text(json.dumps(eplan, indent=2) + "\n")
    (Path(paths.build) / "overlay_plan.json").write_text(
        json.dumps(eplan["overlay_compiler"], indent=2) + "\n")

    # V11 P1 §9 — audio hierarchy default: DELIBERATE SILENCE. A continuous
    # tonal/ambient bed is NOT the default (NARRATION > intentional SFX >
    # subtle ambience/music). A bed is planned only when the story explicitly
    # declares one (story.json "audio": {"bed": "audio/bed_ambient.wav"});
    # an authored per-story audio_bed_plan.json always wins (copied by plan5).
    bed_plan_path = Path(paths.stories) / story_id / "audio_bed_plan.json"
    if not bed_plan_path.exists():
        n_shots = len(eplan.get("shots", []))
        story = json.loads((Path(paths.stories) / story_id / "story.json").read_text())
        declared = (story.get("audio") or {}).get("bed") if isinstance(
            story.get("audio"), dict) else None
        bed_file = None
        if declared and (Path(paths.stories) / story_id / str(declared)).exists():
            bed_file = str(Path(paths.stories) / story_id / str(declared))
        plan = {
            "bed_files": [bed_file] * n_shots,
            "sfx": [],
            "bed_crossfade_ms": 600,
            "authored": bool(declared),
        }
        (Path(paths.build) / "audio_bed_plan.json").write_text(
            json.dumps(plan, indent=2))

    return eplan, rep
