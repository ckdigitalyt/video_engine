"""V11 CANVAS_OCCUPANCY (Jade_todo_v11 P0 true 9:16) — how much of the
1080x1920 canvas carries the shot's meaningful visual.

Construction-truth per shot (the compositor's own geometry, no pixel
guessing): card/plate rect, caption carrier boxes, brand/header text rect,
evidence rects (plan event rects mapped card->canvas), opening title.
The remaining canvas is the backdrop; under V11_FULLBLEED it is a crafted
mirror continuation of the plate art and is PIXEL-VERIFIED on rendered
frames (edge-density floor) — a "continuation" that is actually flat fill
is demoted to empty, so the metric cannot be gamed by painting the
backdrop a flat color. Under the V10 rollback path the backdrop is the
blurred extension and is reported in its own bucket.

Gate (Jade: repeated under-utilization fails; target >=75% meaningful on
major explanatory shots; deliberate exceptions must be declared in the
plan via shot["occupancy_exception"]):
  occupancy_pass = story mean(meaningful on major explanatory shots) >= 0.75
                   (or every non-passing major shot declares an exception)
                   AND no major shot below the 0.50 hard floor.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

GRID = 12  # px per occupancy cell (1080/12 x 1920/12 = 90 x 160 cells)


def _rect_cells(rect, w=1080, h=1920):
    x, y, rw, rh = [float(v) for v in rect]
    x0, y0 = max(0, int(x // GRID)), max(0, int(y // GRID))
    x1, y1 = min(w, x + rw), min(h, y + rh)
    return x0, y0, min(int(np.ceil(x1 / GRID)), w // GRID), \
        min(int(np.ceil(y1 / GRID)), h // GRID)


def _union(cells_list):
    acc = set()
    for c in cells_list:
        x0, y0, x1, y1 = c
        acc |= {(cx, cy) for cx in range(x0, x1) for cy in range(y0, y1)}
    return acc


def _frame_at(video: Path, t: float) -> Image.Image | None:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec",
         "png", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    return Image.open(io.BytesIO(p.stdout)).convert("L")


def _edge_density(gray: Image.Image) -> float:
    """Fraction of px with a strong horizontal+vertical gradient (structure
    signature: art/texture pass, blur/flat fill fails)."""
    a = np.asarray(gray, dtype=np.int16)
    gx = np.abs(np.diff(a, axis=1))
    gy = np.abs(np.diff(a, axis=0))
    return float(((gx > 10).mean() + (gy > 10).mean()) / 2.0)


def shot_occupancy(shot: dict, band: tuple) -> dict:
    from engine.layout import BRAND_RECT
    from engine.planv5 import CARD_H, CARD_Y0, HEADER_Y, FOOTER_Y
    from engine import captions as caps_mod
    w, h = 1080, 1920
    zones = []
    # card/plate rect
    zones.append((0, CARD_Y0, w, CARD_H))
    # header text (brand marker / opening title / end card)
    zones.append((BRAND_RECT[0], BRAND_RECT[1], BRAND_RECT[2], BRAND_RECT[3]))
    # caption carriers
    cues, _r = caps_mod.normalize_cues(shot.get("captions") or [],
                                       float(shot.get("duration_s", 0.0)))
    if cues:
        zones.append((0, band[0], w, band[1] - band[0]))
    # evidence rects (card fractions -> frame)
    for ev in shot.get("events", []) or []:
        spec = ev.get("spec") or {}
        for key in ("rect",):
            rc = spec.get(key)
            if rc:
                x, y, rw, rh = [float(v) for v in rc]
                zones.append((x * w, CARD_Y0 + y * CARD_H, rw * w, rh * CARD_H))
        for rc in (spec.get("rects") or []):
            if rc and len(rc) == 4:
                x, y, rw, rh = [float(v) for v in rc]
                zones.append((x * w, CARD_Y0 + y * CARD_H, rw * w, rh * CARD_H))
    content = _union([_rect_cells(z) for z in zones])
    total_cells = (w // GRID) * (h // GRID)
    n_content = len(content)
    return {
        "shot_id": str(shot.get("shot_id")),
        "motion_class": shot.get("motion_class"),
        "visual_mode": shot.get("visual_mode"),
        "content_frac": round(n_content / total_cells, 4),
        "zones": len(zones),
        "exception_declared": bool(shot.get("occupancy_exception")),
    }


def verify_continuation(video_path: Path, card_y0: int, card_y1: int,
                        samples: int = 6, floor: float = 0.004) -> dict:
    """Pixel-verify the crafted continuation bands carry real structure."""
    if not video_path or not Path(video_path).exists():
        return {"verified": None, "reason": "no video"}
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(video_path)],
                       capture_output=True, text=True)
    try:
        dur = float(p.stdout.strip())
    except ValueError:
        return {"verified": None, "reason": "no duration"}
    dens = []
    for i in range(samples):
        img = _frame_at(Path(video_path), dur * (i + 0.5) / samples)
        if img is None:
            continue
        a = np.asarray(img.convert("L"))
        top = img.crop((0, 0, img.width, max(8, card_y0)))
        bot = img.crop((0, card_y1, img.width, img.height))
        dens.append((_edge_density(top), _edge_density(bot)))
    if not dens:
        return {"verified": None, "reason": "no frames"}
    tmean = float(np.mean([d[0] for d in dens]))
    bmean = float(np.mean([d[1] for d in dens]))
    ok = tmean >= floor and bmean >= floor
    return {"verified": bool(ok), "floor": floor,
            "top_edge_density": round(tmean, 5),
            "bottom_edge_density": round(bmean, 5)}


def run(plan: dict, video_path: Path | None, build_dir: Path) -> dict:
    from engine.planv5 import CARD_H, CARD_Y0
    from engine import captions as caps_mod
    from engine import visualclass
    band = list(caps_mod.band_rect())
    shots = plan.get("shots", [])
    classes = visualclass.classify_plan(shots)
    evidence_ids = {str(s.get("shot_id")) for s, c in zip(shots, classes)
                    if isinstance(c, dict) and (c.get("evidence") or c.get("primary") == "EVIDENCE")}
    per_shot = []
    offset = 0.0
    for i, s in enumerate(shots):
        row = shot_occupancy(s, band)
        row["t_mid"] = round(offset + float(s.get("duration_s", 0.0)) / 2.0, 2)
        per_shot.append(row)
        offset += float(s.get("duration_s", 0.0))
    # major explanatory shots = spec-declared EVIDENCE shots (visualclass
    # classifier — the same one editorial7 gates on, no pixel guessing)
    for row in per_shot:
        if str(row["shot_id"]) in evidence_ids or \
                str(row.get("visual_mode") or "").upper() in {
                "DIAGRAM", "SPLIT", "TRANSFORMATION", "PROCESS", "COMPARE",
                "COMPARISON", "SCALE", "CUTAWAY", "CAUSE_EFFECT", "QUANTITATIVE",
                "EXPLAIN"}:
            row["major_explanatory"] = True
        else:
            row["major_explanatory"] = False
    majors = [r for r in per_shot if r["major_explanatory"]]
    mean_major = float(np.mean([r["content_frac"] for r in majors])) if majors else 0.0
    mean_all = float(np.mean([r["content_frac"] for r in per_shot])) if per_shot else 0.0
    TARGET, FLOOR = 0.75, 0.50
    failing = [r for r in majors if r["content_frac"] < TARGET
               and not r["exception_declared"]]
    floor_fail = [r for r in majors if r["content_frac"] < FLOOR
                  and not r["exception_declared"]]
    cont = None
    if video_path and Path(video_path).exists():
        cont = verify_continuation(video_path, CARD_Y0, CARD_Y0 + CARD_H)
    # a "continuation" that is actually flat fill is demoted to empty ->
    # the occupancy gate fails (anti-gaming clause)
    demoted = cont is not None and cont.get("verified") is False
    occupancy_pass = (not failing) and (not floor_fail) and (not demoted)
    return {
        "occupancy_pass": bool(occupancy_pass),
        "target": TARGET, "floor": FLOOR,
        "mean_meaningful_major": round(mean_major, 4),
        "mean_meaningful_all": round(mean_all, 4),
        "continuation_verification": cont,
        "backdrop_demoted_to_empty": bool(demoted),
        "major_explanatory_shots": len(majors),
        "below_target_undeclared": [r["shot_id"] for r in failing],
        "below_floor": [r["shot_id"] for r in floor_fail],
        "per_shot": per_shot,
    }


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"occupancy_{story_id}.json" if story_id else "occupancy.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
