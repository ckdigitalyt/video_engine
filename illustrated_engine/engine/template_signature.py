"""V13B M5a — deterministic presentation-template signature detector.

Directive: docs/directives/JADE_V13B_STORY_SPECIFIC_VISUAL_GRAMMAR.md P0
"PRESENTATION-TEMPLATE DETECTION" + P1 "VISUAL AUTHORSHIP TEST"
(anchors: docs/v13/V13B_AUDIT_MAP.md).

Per shot, count six signature features of the universal presentation-panel
grammar (parchment bg, central panel, translucent info boxes, dark rail,
generic vector diagram, edge caption band). Flag the shot when >= 4 of 6
co-occur. Fully deterministic thresholds — no ML, no paid calls. This is a
diagnostic for planner recomposition, not a pass-able score.

Also hosts the P1 visual-authorship mute-test helper (`mute_test`): segments
shots into 2-4 s windows and, ONLY when dry_run=False is explicitly passed,
asks the vision judge chain the directive question. Default dry_run=True
returns segment metadata with zero API calls.

Palette anchors: stories/_v6_cardlib.py PARCH family, engine/diagrams.py
paper (233,223,200), chrome BANDC (58,54,46); caption zone default:
engine/caption_place.py DEFAULT_ZONE; frame extraction mirrors
engine/occupancy_qa._frame_at.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

SCHEMA = "v13b.template_signature/1.0"
FLAG_MIN = 4                      # shots flagged when >= 4 of 6 features
ANALYSIS_W = 360                  # analysis downsample width (px)
BLOCK = 4                         # flatness block size (px, at analysis res)

# PARCH family: cardlib PARCH/PARCH_D/PARCH_L/CREAM + diagrams paper.
PARCH_FAMILY = [(233, 223, 200), (216, 208, 190), (206, 197, 178),
                (236, 230, 217), (239, 230, 212)]
BANDC = (58, 54, 46)              # chrome band dark (cardlib)

# Calibrated thresholds (2026-09-24) on ice_slippery old-grammar frames +
# ice/cell plates: old-grammar beige diagram frames flag 4-6 features,
# rich dark plates (SD_B5/B6) flag <= 2.
TH = {
    "beige_border": 0.40,         # f1: border-region beige share
    "beige_full": 0.30,           # f1: full-frame beige share
    "panel_frac": 0.30,           # f2: flat non-bg share of central region
    "empty_boxes": 2,             # f3: payload-less translucent boxes
    "rail_run": 0.52,             # f4: dark run fraction of width
    "rail_thick": 0.035,          # f4: band thickness fraction of height
    "vector_share": 0.10,         # f5: flat non-bg share
    "vector_ratio": 2.0,          # f5: flat non-bg vs textured share
    "light_bg_v": 0.35,           # bg luminance gate for rail/box/vector
}

MUTE_QUESTION = ("If the narration audio were removed, would the visual "
                 "itself communicate what changed, what matters, or what "
                 "the viewer should look at?")


# ---------------------------------------------------------------------------
# image plumbing
# ---------------------------------------------------------------------------

def _frame_at_rgb(video: Path, t: float):
    """RGB frame at time t via ffmpeg image2pipe (mirrors occupancy_qa)."""
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec",
         "png", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    return Image.open(io.BytesIO(p.stdout)).convert("RGB")


def _plate_for_shot(shot: dict, story_id: str, build: Path):
    """Plate PNG for a shot: exact asset match, else first clean png in the
    beat dir (masks / _comp_src excluded)."""
    beat = str(shot.get("beat_id") or "")
    d = build / "plates" / story_id / beat
    if not d.is_dir():
        return None
    asset = str(shot.get("asset") or "")
    if asset:
        exact = d / f"{asset}.png"
        if exact.exists():
            return exact
    for p in sorted(d.glob("*.png")):
        if ".mask." in p.name or "_comp_src" in p.name:
            continue
        return p
    return None


def _shot_image(shot: dict, story_id: str, video, t_abs: float, build: Path,
                prefer: str | None = None):
    """(PIL RGB image | None, source str, path str | None) for one shot.
    prefer="video" forces the rendered frame when a video exists."""
    if prefer != "video":
        plate = _plate_for_shot(shot, story_id, build)
        if plate is not None:
            try:
                return Image.open(plate).convert("RGB"), "plate", str(plate)
            except Exception:
                pass
    if video is not None:
        mid = t_abs + float(shot.get("duration_s") or 0.0) / 2.0
        im = _frame_at_rgb(Path(video), mid)
        if im is not None:
            return im, "video", str(video)
    return None, "none", None


# ---------------------------------------------------------------------------
# feature measures (all deterministic)
# ---------------------------------------------------------------------------

def _prep(im: Image.Image):
    w, h = im.size
    a = np.asarray(im.resize((ANALYSIS_W, max(1, int(h * ANALYSIS_W / w))),
                             Image.BILINEAR), dtype=np.float32)
    H, W, _ = a.shape
    mx, mn = a.max(-1), a.min(-1)
    V = mx / 255.0
    S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1.0), 0.0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    warm = (r >= g - 6) & (g >= b - 6) & (r > b)
    beige = (S < 0.24) & (V > 0.42) & (V < 0.98) & (warm | (S < 0.10))
    gray = a.mean(-1)
    Hb, Wb = H // BLOCK, W // BLOCK
    blk = gray[:Hb * BLOCK, :Wb * BLOCK].reshape(Hb, BLOCK, Wb, BLOCK)
    bstd = blk.std(axis=(1, 3))
    bmean = a[:Hb * BLOCK, :Wb * BLOCK, :].reshape(
        Hb, BLOCK, Wb, BLOCK, 3).mean(axis=(1, 3))
    q = (a // 14).astype(np.int64)
    key = q[..., 0] * 1000 + q[..., 1] * 40 + q[..., 2]
    vals, counts = np.unique(key, return_counts=True)
    bk = int(vals[counts.argmax()])
    bg = np.array([(bk // 1000) * 14 + 7, ((bk // 40) % 25) * 14 + 7,
                   (bk % 40) * 14 + 7], dtype=np.float32)
    bdist = np.sqrt(((bmean - bg) ** 2).sum(-1))
    flat = bstd < 6.0
    flat_nonbg = flat & (bdist > 25.0)
    return dict(a=a, H=H, W=W, Hb=Hb, Wb=Wb, gray=gray, beige=beige, V=V,
                bg=bg, bg_v=float(bg.max() / 255.0), flat=flat,
                flat_nonbg=flat_nonbg, bstd=bstd, S=S)


def _f1_parchment(P) -> dict:
    Hb, Wb, B = P["Hb"], P["Wb"], BLOCK
    border = np.ones((Hb, Wb), bool)
    border[int(.18 * Hb):int(.85 * Hb), int(.20 * Wb):int(.80 * Wb)] = False
    H, W = P["H"], P["W"]
    full = float(P["beige"].mean())
    # border share measured at pixel level via block expansion
    be = np.repeat(np.repeat(P["beige"], B, 0), B, 1)[:H, :W]
    bo = np.repeat(np.repeat(border, B, 0), B, 1)[:H, :W]
    frac = float(be[bo].mean()) if bo.any() else 0.0
    # nearest palette-distance share (diagnostic only, exact PARCH is
    # family-tight; beige metric above carries the grey-tan video variants)
    d = np.min(np.stack([np.sqrt(((P["a"] - np.array(p, dtype=np.float32)) ** 2)
                                 .sum(-1)) for p in PARCH_FAMILY]), 0)
    return {"flag": bool(frac >= TH["beige_border"] and full >= TH["beige_full"]),
            "measure": round(frac, 4),
            "beige_full": round(full, 4),
            "parch_palette_share": round(float((d < 38.0).mean()), 4)}


def _f2_panel(P) -> dict:
    Hb, Wb = P["Hb"], P["Wb"]
    cx0, cx1 = int(.24 * Wb), int(.76 * Wb)
    cy0, cy1 = int(.28 * Hb), int(.86 * Hb)
    frac = float(P["flat_nonbg"][cy0:cy1, cx0:cx1].mean())
    return {"flag": bool(frac >= TH["panel_frac"]
                         and P["beige"].mean() >= TH["beige_full"]),
            "measure": round(frac, 4)}


def _payload_rects(shot: dict, story: dict) -> list:
    """Frame-normalized payload rects: plan events + beat key-text.
    Boxes overlapping these carry payload and do NOT count as empty."""
    rects = []
    for ev in shot.get("events") or []:
        spec = ev.get("spec") or {}
        for k in ("rect", "from_rect", "to_rect"):
            r = spec.get(k)
            if isinstance(r, (list, tuple)) and len(r) == 4:
                rects.append([float(v) for v in r])
    beat_id = str(shot.get("beat_id") or "")
    for b in (story or {}).get("beats") or []:
        if str(b.get("beat_id")) == beat_id:
            kr = b.get("key_number_rect")
            if isinstance(kr, (list, tuple)) and len(kr) == 4:
                rects.append([float(v) for v in kr])
    sc = shot.get("plate_sidecar") or {}
    for r in sc.get("annotation_rects_px") or []:
        bb = r.get("bbox") if isinstance(r, dict) else None
        if isinstance(bb, (list, tuple)) and len(bb) == 4:
            w, h = float(sc.get("width") or 0), float(sc.get("height") or 0)
            if w and h:
                rects.append([bb[0] / w, bb[1] / h,
                              (bb[0] + bb[2]) / w, (bb[1] + bb[3]) / h])
    return rects


def _runs(mask_row):
    d = np.diff(np.concatenate([[0], mask_row.view(np.int8), [0]]))
    st, en = np.where(d == 1)[0], np.where(d == -1)[0]
    return list(zip(st.tolist(), en.tolist()))


def _f3_boxes(P, payload_norm) -> dict:
    """Translucent info boxes: lighter-than-bg flat runs grouped into
    rectangular bands; payload-less boxes count (occupancy_qa:178-188
    demotion logic — payload-bearing boxes never count as empty)."""
    if P["bg_v"] < TH["light_bg_v"]:
        return {"flag": False, "measure": 0, "detail": "bg too dark"}
    H, W = P["H"], P["W"]
    diff = P["gray"] - float(P["bg"].mean())
    box = (diff > 5) & (diff < 60)
    flatpx = np.repeat(np.repeat(P["flat"], BLOCK, 0), BLOCK, 1)[:H, :W]
    box &= flatpx
    min_run = int(0.18 * W)
    bands = []  # [y0, y1, x0, x1]
    for y in range(H):
        for x0, x1 in _runs(box[y]):
            if x1 - x0 < min_run:
                continue
            for bnd in bands:
                if bnd[1] >= y - 2 and not (x1 < bnd[2] - 6 or x0 > bnd[3] + 6):
                    bnd[1] = y + 1
                    bnd[2] = min(bnd[2], x0)
                    bnd[3] = max(bnd[3], x1)
                    break
            else:
                bands.append([y, y + 1, x0, x1])
    boxes = []
    for y0, y1, x0, x1 in bands:
        h_, w_ = y1 - y0, x1 - x0
        if h_ < max(4, int(0.012 * H)) or h_ > int(0.30 * H):
            continue
        area = (y1 - y0) * (x1 - x0)
        if area < 0.006 * H * W or area > 0.35 * H * W:
            continue
        fill = box[y0:y1, x0:x1].mean()
        if fill < 0.70:
            continue
        boxes.append((y0, y1, x0, x1))
    # drop nested duplicates (same band seen through slightly different runs)
    kept = []
    for b in sorted(boxes, key=lambda b: -(b[1] - b[0]) * (b[3] - b[2])):
        if not any(b[0] >= k[0] and b[1] <= k[1] and b[2] >= k[2]
                   and b[3] <= k[3] for k in kept):
            kept.append(b)
    empty = 0
    for y0, y1, x0, x1 in kept:
        nx0, nx1 = x0 / W, x1 / W
        ny0, ny1 = y0 / H, y1 / H
        cx, cy = (nx0 + nx1) / 2, (ny0 + ny1) / 2
        if any(r[0] - .02 <= cx <= r[0] + r[2] + .02
               and r[1] - .02 <= cy <= r[1] + r[3] + .02
               for r in payload_norm):
            continue  # payload-bearing box
        m = 0.25
        ix0, ix1 = int(x0 + m * (x1 - x0)), int(x1 - m * (x1 - x0))
        iy0, iy1 = int(y0 + m * (y1 - y0)), int(y1 - m * (y1 - y0))
        if ix1 - ix0 < 4 or iy1 - iy0 < 4:
            empty += 1
            continue
        inner = P["a"][iy0:iy1, ix0:ix1].mean(-1)
        gx = np.abs(np.diff(inner, axis=1)).mean()
        gy = np.abs(np.diff(inner, axis=0)).mean()
        if (gx + gy) / 2 < 3.0:  # near-uniform interior -> no payload
            empty += 1
    return {"flag": bool(empty >= TH["empty_boxes"]), "measure": empty,
            "detected_boxes": len(kept)}


def _f4_rail(P) -> dict:
    """Thin dark horizontal run spanning > 50% width. Gated on light bg so
    dark rich plates don't self-report."""
    if P["bg_v"] < TH["light_bg_v"]:
        return {"flag": False, "measure": 0.0, "detail": "bg too dark"}
    H, W = P["H"], P["W"]
    dark = (P["gray"] < 88) | (np.sqrt(((P["a"] - np.array(BANDC,
             dtype=np.float32)) ** 2).sum(-1)) < 40)
    run = np.zeros(H)
    for y in range(H):
        rs = _runs(dark[y])
        run[y] = max((x1 - x0 for x0, x1 in rs), default=0)
    rows = run >= TH["rail_run"] * W
    thick = best = 0
    for y in range(H):
        if rows[y]:
            thick += 1
        else:
            best = max(best, thick)
            thick = 0
    best = max(best, thick)
    return {"flag": bool(best >= 2 and best <= TH["rail_thick"] * H),
            "measure": round(best / H, 4)}


def _f5_vector(P) -> dict:
    """Flat-stroke vector share vs textured/organic share."""
    if P["bg_v"] < TH["light_bg_v"]:
        return {"flag": False, "measure": 0.0, "detail": "bg too dark"}
    H, W, B = P["H"], P["W"], BLOCK
    fnb = np.repeat(np.repeat(P["flat_nonbg"], B, 0), B, 1)[:H, :W]
    tex = np.repeat(np.repeat(P["bstd"] >= 9.0, B, 0), B, 1)[:H, :W]
    v, t = float(fnb.mean()), float(tex.mean())
    return {"flag": bool(v >= TH["vector_share"] and v >= TH["vector_ratio"] * t),
            "measure": round(v, 4), "textured_share": round(t, 4)}


def _f6_caption_band(shot: dict) -> dict:
    from engine.caption_place import DEFAULT_ZONE
    zone = shot.get("caption_zone") or DEFAULT_ZONE
    return {"flag": zone == DEFAULT_ZONE, "measure": zone}


# ---------------------------------------------------------------------------
# per-shot / per-story detection
# ---------------------------------------------------------------------------

def detect_shot(shot: dict, story: dict, story_id: str, video, t_abs: float,
                build: Path = Path("build"), prefer: str | None = None) -> dict:
    im, source, src_path = _shot_image(shot, story_id, video, t_abs, build,
                                       prefer)
    flags = {"parchment_bg": {"flag": False, "measure": 0.0, "detail": "no image"},
             "central_panel": {"flag": False, "measure": 0.0, "detail": "no image"},
             "translucent_boxes": {"flag": False, "measure": 0, "detail": "no image"},
             "dark_rail": {"flag": False, "measure": 0.0, "detail": "no image"},
             "vector_diagram": {"flag": False, "measure": 0.0, "detail": "no image"},
             "edge_caption_band": _f6_caption_band(shot)}
    if im is not None:
        P = _prep(im)
        payload = _payload_rects(shot, story)
        flags["parchment_bg"] = _f1_parchment(P)
        flags["central_panel"] = _f2_panel(P)
        flags["translucent_boxes"] = _f3_boxes(P, payload)
        flags["dark_rail"] = _f4_rail(P)
        flags["vector_diagram"] = _f5_vector(P)
    n = sum(1 for f in flags.values() if f["flag"])
    vg = shot.get("visual_grammar") or {}
    return {"shot_id": shot.get("shot_id"),
            "source": source, "image": src_path,
            "composition": (vg.get("composition") if isinstance(vg, dict)
                            else None) or shot.get("visual_mode"),
            "flags": flags, "flagged": n >= FLAG_MIN, "feature_count": n}


def detect_story(plan: dict, story_id: str, video=None, story: dict | None = None,
                 build: Path = Path("build"), save: bool = True,
                 prefer: str | None = None) -> dict:
    """Run the detector over every shot; write build/qa/template_signature_<story>.json."""
    story = story or {}
    shots = plan.get("shots") or []
    t = 0.0
    out = []
    for s in shots:
        out.append(detect_shot(s, story, story_id, video, t, build, prefer))
        t += float(s.get("duration_s") or 0.0)
    flagged = [r["shot_id"] for r in out if r["flagged"]]
    res = {"schema": SCHEMA, "story": story_id, "flag_min": FLAG_MIN,
           "source_video": str(video) if video else None,
           "shots": out,
           "summary": {"shots": len(out), "flagged": len(flagged),
                       "flagged_shot_ids": flagged,
                       "flag_rate": round(len(flagged) / len(out), 3) if out else 0.0,
                       "note": ("diagnostic only — planner should recompose "
                                "flagged shots (>=4/6 template features); "
                                "recompose-on-flag wiring lands with M5 planner work")}}
    if save:
        qdir = build / "qa"
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / f"template_signature_{story_id}.json").write_text(
            json.dumps(res, indent=1))
    return res


# ---------------------------------------------------------------------------
# P1 — visual authorship mute test
# ---------------------------------------------------------------------------

def segment_shots(plan: dict, seg_min: float = 2.0, seg_max: float = 4.0,
                  target: float = 3.0) -> list:
    """Segment each shot into ~2-4 s windows (deterministic even split:
    n = ceil(dur / seg_max), so every window is within [2, 4] s whenever the
    shot is long enough). Absolute t0/t1 over the rendered timeline
    (cumulative shot durations)."""
    import math
    segs = []
    t_shot = 0.0
    for shot in plan.get("shots") or []:
        dur = float(shot.get("duration_s") or 0.0)
        if dur <= 0:
            continue
        caps = [c for c in (shot.get("captions") or [])
                if isinstance(c.get("t0"), (int, float))]
        n = max(1, math.ceil(dur / seg_max))
        if n > 1 and dur / n < seg_min:
            n -= 1
        win = dur / n
        for idx in range(n):
            t0, t1 = idx * win, (idx + 1) * win
            text = " / ".join(c.get("text", "") for c in caps
                              if c.get("t0", 0) < t1 - 1e-3
                              and c.get("t1", dur) > t0 + 1e-3)
            segs.append({"shot_id": shot.get("shot_id"),
                         "seg_index": idx, "t0": round(t_shot + t0, 3),
                         "t1": round(t_shot + t1, 3),
                         "dur": round(t1 - t0, 3),
                         "shot_local_t0": round(t0, 3),
                         "caption_text": text})
        t_shot += dur
    return segs


def mute_test(plan: dict, story_id: str | None = None, video=None,
              dry_run: bool = True, build: Path = Path("build"),
              max_calls: int | None = None) -> dict:
    """P1 visual-authorship mute test. dry_run=True (default) returns
    segment metadata + the directive question with ZERO API calls.
    dry_run=False extracts each segment's midpoint frame and asks the
    vision judge chain (engine.director.vision_ask); every None answer is
    recorded as unjudged, never as a pass."""
    segs = segment_shots(plan)
    out = {"schema": "v13b.mute_test/1.0", "story": story_id,
           "question": MUTE_QUESTION, "dry_run": bool(dry_run),
           "segments": []}
    judged = weak = calls = 0
    tmpdir = build / "qa" / f"mute_frames_{story_id or 'plan'}"
    for seg in segs:
        rec = dict(seg)
        rec.update({"visual_authorship": None, "reason": None,
                    "judged": False})
        if not dry_run:
            if video is None or not Path(video).exists():
                rec["error"] = "no video for frame extraction"
            elif max_calls is not None and calls >= max_calls:
                rec["error"] = "call budget exhausted"
            else:
                from engine.director import vision_ask
                tmpdir.mkdir(parents=True, exist_ok=True)
                fp = tmpdir / (f"{seg['shot_id']}_{seg['seg_index']:02d}.png")
                mid = (seg["t0"] + seg["t1"]) / 2.0
                im = _frame_at_rgb(Path(video), mid)
                if im is None:
                    rec["error"] = "frame extraction failed"
                else:
                    im.save(fp)
                    q = (MUTE_QUESTION + " Answer as JSON "
                         '{"visual_authorship": "strong"|"weak", "reason": '
                         '"<one sentence>"}. Segment covers '
                         f"{seg['dur']:.1f}s; on-screen caption text: "
                         f"\"{seg['caption_text'][:120]}\".")
                    calls += 1
                    ans = vision_ask(str(fp), q, max_tokens=300) or {}
                    va = ans.get("visual_authorship") or ans.get("answer")
                    if isinstance(va, str):
                        va = va.lower()
                        rec["visual_authorship"] = va
                        rec["judged"] = True
                        judged += 1
                        if va not in ("strong", "yes", "true"):
                            weak += 1
                    rec["reason"] = ans.get("reason")
        out["segments"].append(rec)
    out["calls_made"] = calls
    out["summary"] = {"segments": len(segs), "judged": judged,
                      "weak_visual_authorship": weak if not dry_run else None,
                      "note": ("weak = visual alone does not communicate "
                               "what changed / what matters / where to look")}
    if story_id and not dry_run:
        qdir = build / "qa"
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / f"mute_test_{story_id}.json").write_text(json.dumps(out, indent=1))
    return out
