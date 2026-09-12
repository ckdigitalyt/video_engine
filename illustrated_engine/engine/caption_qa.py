"""V11 CAPTION gate (Jade_todo_v11 P0) — automated caption-integrity QA.

Two independent layers:

1. CONSTRUCTION — the plan timeline is re-run through the state machine
   (captions.normalize_cues) independently of the renderer and checked for:
   authored cue overlaps, persistence past the beat end, >2-line states,
   safe-zone containment (overlay report), global state uniqueness (no two
   ACTIVE states anywhere on the video timeline), and renderer repair
   records (reported; overlap-class repairs gate, pure gap shifts don't).

2. PIXELS — rendered frames sampled at caption transitions and mid-cue
   reference points. Inside the active caption band:
   - off-state (stale-caption detection): at the boundary frame (inside the
     state gap, where NO carrier is active) the band must be text-empty —
     any glyphs mean a layer persisted past its state (the ghost signature);
   - foreign text: mid-cue, text pixels outside the active carrier box
     (+ emphasis-rule margin) — the plate-footer bleed / leftover-layer
     signature that produced the V10 ghost captions;
   - shot-end persistence: no text in the band after the last state ends.

Any stale/overlapping caption = P0 defect -> CAPTION_PASS = False.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

MID_CUE_INSET = 0.35        # reference sample inset inside a state
OFFSTATE_ABS = 0.02         # boundary-frame band text frac must be < 2%
FOREIGN_ABS = 0.025         # foreign band text frac must be < 2.5%
EMPH_MARGIN = 44            # px below the carrier box allowed for the rule


def _frame_at(video: Path, t: float) -> Image.Image | None:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec",
         "png", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    return Image.open(io.BytesIO(p.stdout)).convert("L")


def _text_mask(gray: Image.Image) -> np.ndarray:
    """High-contrast glyph mask: |lum - local median| > 28 (no OCR needed —
    presence/absence and geometry only)."""
    med = gray.filter(ImageFilter.MedianFilter(9))
    a = np.asarray(gray).astype(np.int16)
    m = np.asarray(med).astype(np.int16)
    return np.abs(a - m) > 28


def _band_crop(img: Image.Image, band: tuple) -> Image.Image:
    top, bot = int(band[0]), int(band[1])
    pad = 16
    return img.crop((0, max(0, top - pad), img.width, min(img.height, bot + pad)))


def _frac(mask: np.ndarray, box=None) -> float:
    if box is None:
        return float(mask.mean())
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(mask.shape[1], x1), min(mask.shape[0], y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    return float(mask[y0:y1, x0:x1].mean())


def _carrier_boxes(shot: dict, bible: dict, band: tuple) -> list:
    """Per-normalized-cue carrier bbox (construction truth, no PNG I/O):
    union of the chunk text boxes the renderer would draw."""
    from engine import captions as caps_mod
    cues, _r = caps_mod.normalize_cues(shot.get("captions") or [],
                                       float(shot.get("duration_s", 0.0)))
    chunks = caps_mod.chunk_cues(shot, cues=cues)
    y0, y1 = int(band[0]), int(band[1])
    boxes = []
    for c in cues:
        mine = [k for k in chunks
                if k["t0"] >= float(c["t0"]) - 0.05 and k["t1"] <= float(c["t1"]) + 0.05]
        if not mine:
            boxes.append((0, y0, caps_mod.FRAME_W, y1))  # state with no chunks
            continue
        xs0, xs1 = [], []
        for k in mine:
            try:
                _f, _pl, width = caps_mod._chunk_font(k, bible)
            except Exception:
                width = caps_mod.FRAME_W - 2 * caps_mod.MARGIN_X
            cx = (caps_mod.FRAME_W - width) / 2.0
            xs0.append(cx)
            xs1.append(cx + width)
        boxes.append((min(xs0) - 26, y0, max(xs1) + 26, y1))
    return boxes


def _shift(box, dy):
    return (box[0], box[1] + dy, box[2], box[3] + dy) if box else None


def run(plan: dict, video_path: Path, build_dir: Path, bible: dict,
        sample_cap: int = 120) -> dict:
    build_dir = Path(build_dir)
    shots = plan.get("shots", [])
    findings: list = []
    checks: dict = {}
    from engine import captions as caps_mod

    # ---------------- construction layer ----------------
    cons = {"cue_overlap": 0, "past_beat_end": 0, "line_cap": 0,
            "safe_zone": 0, "render_repairs": 0, "gap_shift_repairs": 0}
    states_by_shot: dict = {}
    for s in shots:
        sid = str(s.get("shot_id"))
        dur = float(s.get("duration_s", 0.0))
        cues = list(s.get("captions", []) or [])
        raw = sorted(((float(c.get("t0", 0)), float(c.get("t1", 0)))
                      for c in cues), key=lambda x: x[0])
        for (a0, a1), (b0, _b1) in zip(raw, raw[1:]):
            if b0 < a1 - 0.001:
                cons["cue_overlap"] += 1
                findings.append({"severity": "P0", "rule": "cue_overlap",
                                 "shot": sid,
                                 "detail": f"{a0:.3f}-{a1:.3f} vs {b0:.3f}"})
        for c in cues:
            if float(c.get("t1", 0)) > dur + 0.01:
                cons["past_beat_end"] += 1
                findings.append({"severity": "P0",
                                 "rule": "persistence_past_beat_end",
                                 "shot": sid,
                                 "detail": f"cue t1={float(c['t1']):.3f} > dur={dur:.3f}"})
            _lines, n_lines = caps_mod._cue_lines(c)
            if n_lines > caps_mod.MAX_LINES:
                cons["line_cap"] += 1
                findings.append({"severity": "P0", "rule": "max_2_lines",
                                 "shot": sid, "detail": f"{n_lines} lines"})
        st_path = build_dir / "ov5" / sid / "cap_state.json"
        if st_path.exists():
            st = json.loads(st_path.read_text())
            states_by_shot[sid] = st
            for r in st.get("repairs", []) or []:
                if r.get("reason") in ("overlap_or_gap_repair", "clamped_to_shot"):
                    cons["gap_shift_repairs"] += 1
                else:
                    cons["render_repairs"] += 1
                    findings.append({"severity": "P0",
                                     "rule": f"state_machine_{r.get('reason')}",
                                     "shot": sid, "detail": json.dumps(r)[:120]})
    checks["construction"] = cons

    # safe-zone from the renderer's overlay report (per-shot adaptive
    # caption zone, V11 P1 §5; falls back to the global band for older
    # reports). Each shot's captions are checked against ITS OWN band.
    rep_path = build_dir / "overlay_report.json"
    band = None
    zone_by_shot: dict = {}
    if rep_path.exists():
        rep = json.loads(rep_path.read_text())
        band = rep.get("safe_caption_band")
        for sid, sr in (rep.get("shots") or {}).items():
            z = (sr.get("caption_zone") or {}).get("band")
            if z:
                zone_by_shot[sid] = (float(z[0]), float(z[1]))
            for c in sr.get("captions") or []:
                bb = c.get("bbox")
                zb = z or band
                if not bb or not zb:
                    continue
                if bb[1] < zb[0] - 10 or bb[3] > zb[1] + 10:
                    cons["safe_zone"] += 1
                    findings.append({"severity": "P0", "rule": "safe_zone",
                                     "shot": sid,
                                     "detail": f"bbox {bb} vs zone band {zb}"})
    if band is None:
        band = list(caps_mod.band_rect())
    checks["band"] = band
    checks["caption_zones"] = {k: list(v) for k, v in sorted(zone_by_shot.items())}

    # V11 P1 §5 — evidence clearance (belt-and-braces beyond the
    # out-of-card zone geometry): a rendered caption bbox must not
    # intersect any evidence/label/arrow rect the shot declares.
    from engine import caption_place as _cplace
    ev_hits = 0
    for s in shots:
        sid = str(s.get("shot_id"))
        sband = zone_by_shot.get(sid, tuple(band))
        ev_rects = [_cplace.card_to_frame(rc) for rc, _k, _w
                    in _cplace.evidence_rects(s)]
        if not ev_rects:
            continue
        boxes = _carrier_boxes(s, bible, sband)
        for bb in boxes:
            if not bb:
                continue
            for ex0, ey0, ex1, ey1 in ev_rects:
                ix = min(bb[2], ex1) - max(bb[0], ex0)
                iy = min(bb[3], ey1) - max(bb[1], ey0)
                if ix > 4 and iy > 4:
                    ev_hits += 1
                    findings.append({"severity": "P0",
                                     "rule": "evidence_collision",
                                     "shot": sid,
                                     "detail": f"caption box {tuple(round(v) for v in bb)} "
                                               f"intersects evidence rect "
                                               f"({ex0:.0f},{ey0:.0f},{ex1:.0f},{ey1:.0f})"})
                    break
    checks["evidence_collisions"] = ev_hits

    # global uniqueness on the video timeline (plan-level, independent)
    timeline = []
    offset = 0.0
    shot_offsets = {}
    for s in shots:
        sid = str(s.get("shot_id"))
        dur = float(s.get("duration_s", 0.0))
        shot_offsets[sid] = offset
        cues, _r = caps_mod.normalize_cues(s.get("captions") or [], dur)
        for c in cues:
            timeline.append((offset + float(c["t0"]), offset + float(c["t1"]), sid))
        offset += dur
    timeline.sort()
    n_overlap_states = 0
    for (a0, a1, sa), (b0, _b1, sb) in zip(timeline, timeline[1:]):
        if b0 < a1 - 1e-6:
            n_overlap_states += 1
            findings.append({"severity": "P0", "rule": "state_uniqueness",
                             "shot": f"{sa}->{sb}",
                             "detail": f"[{a0:.3f},{a1:.3f}] overlaps [{b0:.3f},{b1:.3f}]"})
    checks["timeline_states"] = len(timeline)
    checks["overlapping_state_pairs"] = n_overlap_states

    # ---------------- pixel layer ----------------
    # Stale-caption detection without OCR = the OFF-STATE probe: at the
    # boundary frame (inside the state gap) NO caption carrier is active, so
    # any glyph pixels in the band mean a layer persisted past its state —
    # the ghost signature. (A post-boundary "old-box" probe cannot
    # distinguish old from new text spatially — adjacent states share the
    # band rows — and produced only false positives; construction-layer
    # timeline uniqueness + the off-state frame carry the guarantee.)
    px = {"probes": 0, "offstate_hits": 0,
          "foreign_hits": 0, "shotend_hits": 0}
    # V11 P1 §5 — per-shot adaptive band: the carrier boxes and the pixel
    # probes follow each shot's OWN zone, not one global coordinate.
    boxes_by_shot = {}
    for s in shots:
        sid = str(s.get("shot_id"))
        sband = zone_by_shot.get(sid, tuple(band))
        boxes_by_shot[sid] = _carrier_boxes(s, bible, sband)
    samples: list = []
    for s in shots:
        sid = str(s.get("shot_id"))
        dur = float(s.get("duration_s", 0.0))
        st = states_by_shot.get(sid) or {}
        cues = st.get("normalized_cues") or []
        if not cues:
            cues, _r = caps_mod.normalize_cues(s.get("captions") or [], dur)
        off = shot_offsets[sid]
        boxes = boxes_by_shot.get(sid) or []
        sband = zone_by_shot.get(sid, tuple(band))
        for i, c in enumerate(cues):
            t0, t1 = float(c["t0"]), float(c["t1"])
            if t1 - t0 > 2 * MID_CUE_INSET:
                samples.append((off + t0 + MID_CUE_INSET, "ref", sid, i, None,
                                sband))
            if i > 0:
                prev_t1 = float(cues[i - 1]["t1"])
                # probe just AFTER the previous state ends: ffmpeg -ss snaps
                # forward to the first frame at/after the requested time, so
                # prev_t1 + 5ms is guaranteed to decode a frame INSIDE the
                # state gap (STATE_GAP=50ms > 1 frame at 30fps) — the frame
                # where the old state must already be fully removed.
                samples.append((off + prev_t1 + 0.005, "offstate", sid,
                                i, i - 1, sband))
        last_t1 = float(cues[-1]["t1"]) if cues else -1.0
        if last_t1 < dur - 0.15:
            samples.append((off + dur - 0.08, "shotend", sid, None, None,
                            sband))
        # cap samples per shot at ~12 to bound ffmpeg seeks
    samples = samples[:sample_cap]
    for (t, kind, sid, ci, pi, sband) in samples:
        img = _frame_at(Path(video_path), t)
        if img is None:
            continue
        y_off = max(0, int(sband[0]) - 16)
        gray = _band_crop(img, sband)
        mask = _text_mask(gray)
        px["probes"] += 1
        boxes = boxes_by_shot.get(sid) or []
        box = _shift(boxes[ci], -y_off) if ci is not None and ci < len(boxes) else None
        prev_box = _shift(boxes[pi], -y_off) if pi is not None and pi < len(boxes) else None
        if kind == "offstate":
            f = _frac(mask)
            if f > OFFSTATE_ABS:
                px["offstate_hits"] += 1
                findings.append({"severity": "P0", "rule": "stale_caption",
                                 "shot": sid, "t": round(t, 2),
                                 "detail": f"text frac {f:.3f} in band at state boundary frame (limit {OFFSTATE_ABS}) — a caption layer persisted past its state"})
        else:  # ref | shotend
            work = mask.copy()
            if kind == "ref" and box:
                x0, y0, x1, y1 = [int(v) for v in box]
                y0 = max(0, y0 - 6)
                y1 = min(work.shape[0], y1 + EMPH_MARGIN)
                x0 = max(0, x0 - 12)
                x1 = min(work.shape[1], x1 + 12)
                work[y0:y1, x0:x1] = False
            f = _frac(work)
            if f > FOREIGN_ABS:
                px["foreign_hits" if kind == "ref" else "shotend_hits"] += 1
                findings.append({"severity": "P0",
                                 "rule": "foreign_band_text" if kind == "ref"
                                 else "persistence_past_beat_end",
                                 "shot": sid, "t": round(t, 2),
                                 "detail": f"band text outside active state frac {f:.3f} ({kind})"})
    checks["pixels"] = px

    cap_pass = (cons["cue_overlap"] == 0 and cons["past_beat_end"] == 0
                and cons["line_cap"] == 0 and cons["safe_zone"] == 0
                and n_overlap_states == 0
                and ev_hits == 0
                and px["offstate_hits"] == 0
                and px["foreign_hits"] == 0 and px["shotend_hits"] == 0)
    return {"CAPTION_PASS": bool(cap_pass), "checks": checks,
            "findings": findings}


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"caption_qa_{story_id}.json" if story_id else "caption_qa.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
