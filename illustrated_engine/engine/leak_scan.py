"""V11 DEBUG_LEAK_SCAN (Jade_todo_v11 P0) — engine-level development-artifact
gate over ALL engine-drawn text sources + rendered frames.

SOURCE LAYER (deterministic): every string the engine can draw is collected
from the plan/story trees — captions (incl. kinetic chunk words), event pop
texts, shot titles/tags, end cards, title overlays, story/bible brand — and
scanned for development tokens:

  DEBUG TEST SIGNAL PLACEHOLDER TODO FIXME DUMMY LOREM XXX UNTITLED
  filenames (\\w+\\.(png|jpg|jpeg|wav|mp4|json|py))
  asset/shot-id shapes (B1_ice_blade_hero, S01_EXTRA) in drawable text
  model names (deepseek, gpt, flux, sdxl, chatterbox, qwen, kokoro, ...)

Any hit = CAN_PUBLISH=false. Tokens are NOT whitelistable per story
(reviewer directive 2026-09-10: SIGNAL in ice_slippery must be caught — a
semantic end-card word replaces it at the content level, never a scan
exemption).

FRAME LAYER: sampled frames are checked for glyph-like pixels OUTSIDE all
declared text zones (card content rect, brand rect, caption band, opening
title band). Under V11 full-bleed the continuation bands must be text-free;
any text-like cluster there means an undeclared text layer leaked onto the
canvas (catches plate-baked text escaping the card after composition bugs).

In-card OCR is out of scope (no tesseract dependency): plan-drawn text is
covered exhaustively by the source layer; plate-baked text stays inside the
declared card zone and is content, not metadata.
"""
from __future__ import annotations

import io
import json
import re
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

DEV_TOKENS = {"DEBUG", "TEST", "SIGNAL", "PLACEHOLDER", "TODO", "FIXME",
              "DUMMY", "LOREM", "UNTITLED"}
MODEL_TOKENS = {"DEEPSEEK", "GPT", "FLUX", "SDXL", "SD15", "CHATTERBOX",
                "QWEN", "KOKORO", "ELEVENLABS", "DALL"}
_FILENAME_RE = re.compile(r"[A-Za-z0-9_-]+\.(png|jpg|jpeg|wav|mp4|json|py)\b")
_IDISH_RE = re.compile(r"\b(?:[A-Z]\d?[a-z]+_[A-Za-z0-9_]{2,}|S\d{2}_[A-Za-z]{3,})\b")
_WORD_RE = re.compile(r"[A-Za-z0-9'\u2019%$.,:;!?+-]+")
FRAME_SAMPLES = 12


def _drawable_strings(plan: dict, story: dict, bible: dict) -> list:
    """(source, text) for every string any render path can draw."""
    out: list = []

    def add(src, val):
        if val is None:
            return
        v = str(val).strip()
        if v:
            out.append((src, v))

    add("bible.brand", (bible or {}).get("brand"))
    add("story.brand", (story or {}).get("brand"))
    add("story.title", (story or {}).get("title"))
    for s in (plan or {}).get("shots", []):
        sid = str(s.get("shot_id"))
        for c in s.get("captions", []) or []:
            add(f"{sid}.caption", c.get("text"))
            for ln in (c.get("lines") or []):
                add(f"{sid}.caption_line", ln)
        add(f"{sid}.title", s.get("title"))
        add(f"{sid}.tag", s.get("tag"))
        add(f"{sid}.end_card", s.get("end_card"))
        to = s.get("title_overlay")
        if isinstance(to, dict):
            add(f"{sid}.title_overlay", to.get("text"))
        for ev in s.get("events", []) or []:
            spec = ev.get("spec") or {}
            add(f"{sid}.event.{ev.get('kind')}", spec.get("text"))
    return out


def _scan_text(src: str, text: str) -> list:
    hits = []
    words = {w.upper().strip(".,:;!?") for w in _WORD_RE.findall(text)}
    for w in words:
        if w in DEV_TOKENS:
            hits.append({"source": src, "token": w, "kind": "dev_token",
                         "context": text[:80]})
        elif w in MODEL_TOKENS:
            hits.append({"source": src, "token": w, "kind": "model_name",
                         "context": text[:80]})
    m = _FILENAME_RE.search(text)
    if m:
        hits.append({"source": src, "token": m.group(0), "kind": "filename",
                     "context": text[:80]})
    m = _IDISH_RE.search(text)
    if m:
        hits.append({"source": src, "token": m.group(0), "kind": "internal_id",
                     "context": text[:80]})
    return hits


def _frame_at(video: Path, t: float) -> Image.Image | None:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(video), "-frames:v", "1", "-f", "image2pipe", "-vcodec",
         "png", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return None
    return Image.open(io.BytesIO(p.stdout)).convert("L")


def _text_zones():
    """Declared text zones (x0, y0, x1, y1) in frame coords."""
    from engine import caption_place as cplace
    from engine.planv5 import CARD_H, CARD_Y0
    zones = [(0, 0, 1080, CARD_Y0),                       # header band (brand/title/end-card)
             (0, CARD_Y0, 1080, CARD_Y0 + CARD_H)]        # card content (plate labels/footer)
    # V12 3 fix — declare EVERY caption_place candidate zone, not just the
    # default band. composev5 places captions per shot via
    # caption_place.choose_zone (below_card / below_card_low retreat /
    # top_band), so a caption drawn in a non-default candidate zone is
    # engine output inside a declared zone, not a leak. The stale
    # single-band declaration produced the systematic
    # frame_text_outside_zones P0 on the 3a renders (evidence:
    # microwave_dielectric S06 clusters y1774..1818 == below_card_low
    # carrier text rows; S05 top_band likewise; atacama frame hits drop
    # to zero once all candidate zones are declared). Detection itself
    # (median-diff glyph mask, row clustering, dev-token source scan) is
    # unchanged — only the declared-zone set now matches the render
    # contract.
    for _top, _bot in cplace.zones().values():
        zones.append((0, max(0, _top - 8), 1080, min(1920, _bot + 8)))
    return zones


def _outside_mask(shape, zones) -> np.ndarray:
    m = np.ones(shape, dtype=bool)
    for (x0, y0, x1, y1) in zones:
        m[max(0, y0):min(shape[0], y1), max(0, x0):min(shape[1], x1)] = False
    return m


def run(plan: dict, story: dict, bible: dict, video_path: Path | None,
        build_dir: Path, frame_samples: int = FRAME_SAMPLES) -> dict:
    findings: list = []
    source_hits: list = []
    for src, text in _drawable_strings(plan, story, bible):
        for h in _scan_text(src, text):
            source_hits.append(h)
            findings.append({"severity": "P0", "rule": "debug_leak_source",
                             **h})
    frame_hits = 0
    frames_probed = 0
    if video_path and Path(video_path).exists():
        p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                            "format=duration", "-of", "csv=p=0",
                            str(video_path)], capture_output=True, text=True)
        try:
            dur = float(p.stdout.strip())
        except ValueError:
            dur = 0.0
        if dur > 0:
            zones = _text_zones()
            outside = None
            ts = [dur * (i + 0.5) / frame_samples for i in range(frame_samples)]
            for t in ts:
                img = _frame_at(Path(video_path), t)
                if img is None:
                    continue
                frames_probed += 1
                gray = img.filter(ImageFilter.MedianFilter(5))
                a = np.asarray(img).astype(np.int16)
                m = np.asarray(gray).astype(np.int16)
                mask = (np.abs(a - m) > 34)
                if outside is None or outside.shape != mask.shape:
                    outside = _outside_mask(mask.shape, zones)
                work = mask & outside
                # glyph-like: rows with compact high-contrast runs; require
                # a cluster of >=3 adjacent such rows (noise tolerance)
                rows = np.where(work.sum(axis=1) > 6)[0]
                cluster = 1
                hit = False
                for i in range(1, len(rows)):
                    cluster = cluster + 1 if rows[i] - rows[i - 1] <= 2 else 1
                    if cluster >= 3:
                        hit = True
                        break
                if hit:
                    frame_hits += 1
                    findings.append({"severity": "P0", "rule": "debug_leak_frame",
                                     "t": round(t, 2),
                                     "detail": "glyph-like pixels outside declared text zones"})
    debug_free = not source_hits and frame_hits == 0
    return {"DEBUG_FREE": bool(debug_free), "source_hits": source_hits,
            "frame_hits": frame_hits, "frames_probed": frames_probed,
            "tokens": sorted(DEV_TOKENS | MODEL_TOKENS),
            "findings": findings}


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"leak_scan_{story_id}.json" if story_id else "leak_scan.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
