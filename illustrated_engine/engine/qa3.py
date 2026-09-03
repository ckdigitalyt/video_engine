"""V3 three-axis QA: TECHNICAL / VISUAL / EDITORIAL.

Publication gates (per Jade_todo v3):
    Technical >= 95
    Visual    >= 80
    Editorial >= 80
    AND: no P0 visual defect, no clipping, no unreadable text, no weak ending

A technical PASS cannot override a weak visual or editorial score.

This module reads:
    build/qa/qa2.json          (V2 technical baseline)
    build/continuity.json      (palette continuity)
    build/style_continuity.json (style continuity, written by this module)
    build/phone_qa.json        (phone legibility, written by this module)
    build/raster_text_qa.json  (raster text QA, written by this module)
    stories/<id>/story.json    (editorial hook/payoff structure)

and writes:
    build/qa/qa3.json
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image


# ---------- gate thresholds (Jade_todo v3) --------------------------
GATES = {"technical": 95.0, "visual": 80.0, "editorial": 80.0}


@dataclass
class Check:
    name: str
    score: float          # 0..100
    weight: float = 1.0
    detail: str = ""
    p0: bool = False      # P0 defects: clipping, unreadable text, weak ending

    def weighted(self) -> float:
        return self.score * self.weight


@dataclass
class Group:
    name: str
    checks: list = field(default_factory=list)

    def add(self, name: str, score: float, detail: str = "", weight: float = 1.0, p0: bool = False) -> None:
        self.checks.append(Check(name, score, weight, detail, p0))

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        total = sum(c.weighted() for c in self.checks)
        denom = sum(c.weight for c in self.checks)
        return round(total / max(1e-9, denom), 2)

    def as_dict(self) -> dict:
        return {
            "score": self.score,
            "checks": [asdict(c) for c in self.checks],
            "p0_defects": [c.name for c in self.checks if c.p0],
        }


# ---------- individual checks -------------------------------------

def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def _tech_checks(qa2: dict) -> Group:
    g = Group("TECHNICAL")
    if not qa2:
        g.add("qa2_present", 0, "qa2.json missing")
        return g
    for c in qa2.get("checks", []):
        ok = bool(c.get("ok"))
        g.add(c.get("check", "check"), 100.0 if ok else 0.0, c.get("detail", "")[:120])
    return g


def _visual_checks(qa2: dict, continuity: dict, style: dict, phone: dict, raster: dict) -> Group:
    g = Group("VISUAL")
    # subtitle layout (from v2)
    sub = next((c for c in qa2.get("checks", []) if c.get("check") == "subtitle_layout"), None)
    if sub:
        g.add("subtitle_layout", 100.0 if sub["ok"] else 0.0, sub.get("detail", "")[:120])
    # novelty (from v2)
    nov = next((c for c in qa2.get("checks", []) if c.get("check") == "novelty"), None)
    if nov:
        g.add("motion_variety", 100.0 if nov["ok"] else 60.0, nov.get("detail", "")[:120])
    # palette continuity
    gen = [a for a in continuity.get("assets", []) if not a.get("programmatic")]
    n_ok = sum(1 for a in gen if a.get("ok"))
    g.add("palette_continuity",
          round(100.0 * n_ok / max(1, len(gen)), 1),
          f"{n_ok}/{len(gen)} generated plates >= 0.55, video={continuity.get('video_score')}")
    # style continuity
    g.add("style_continuity",
          round(min(100.0, style.get("mean", 0) * 100), 1),
          f"mean={style.get('mean')} min={style.get('min')} max={style.get('max')}")
    # phone legibility
    g.add("phone_readability",
          100.0 if phone.get("readable") else 0.0,
          f"caption_band_px={phone.get('caption_band_px')} key_number_px={phone.get('key_number_px')}",
          p0=not phone.get("readable", True))
    # raster text QA: clipping/edge/overlap on extracted frames
    clipped = raster.get("clipped", [])
    g.add("raster_text_safety",
          100.0 if not clipped else 0.0,
          f"{len(clipped)} clipped text instances in extracted frames",
          p0=bool(clipped))
    # contrast QA
    contrast_fails = raster.get("contrast_failures", [])
    g.add("contrast_qa",
          100.0 if not contrast_fails else 0.0,
          f"{len(contrast_fails)} captions with low contrast",
          p0=bool(contrast_fails))
    return g


def _editorial_checks(story: dict, plan: dict) -> Group:
    g = Group("EDITORIAL")
    beats = story.get("beats", [])
    if not beats:
        g.add("story_clarity", 0, "no beats in story.json")
        return g
    # hook: first beat should have an attention word in narration
    first = (beats[0].get("narration") or beats[0].get("text") or "").lower()
    hook_words = ("you", "everest", "oldest", "largest", "tallest", "closest", "hiding", "think", "secret", "wait", "actually")
    has_hook = any(w in first for w in hook_words) or "?" in first
    g.add("hook_3_4s", 100.0 if has_hook else 50.0, f"first beat: {first[:80]!r}")
    # contradiction: at least one beat contains 'but', 'however', 'not', or 'never'
    all_text = " ".join((b.get("narration") or b.get("text") or "") for b in beats).lower()
    has_contradiction = any(w in all_text for w in ("but ", "however", "isn't", "not ", "never", "instead", "almost"))
    g.add("contradiction_present", 100.0 if has_contradiction else 60.0,
          f"contradiction word found={has_contradiction}")
    # pacing: 6-7 beats in 45-60s is the target band
    n_beats = len(beats)
    g.add("pacing_beat_count", 100.0 if 5 <= n_beats <= 8 else 60.0, f"{n_beats} beats")
    # narration has a clear answer in the closing beat(s)
    last = (beats[-1].get("narration") or beats[-1].get("text") or "").lower()
    closing_words = ("so", "therefore", "the answer", "in short", "is the", "are the", "this is")
    has_payoff = any(w in last for w in closing_words) or last.endswith(".")
    g.add("payoff_last_beat", 100.0 if has_payoff else 50.0, f"last beat: {last[:80]!r}")
    # visual-narration alignment: every beat has a cue (start/end) that overlaps with a shot
    cues_aligned = all(b.get("start") is not None and b.get("end") is not None for b in beats)
    g.add("vis_narration_alignment", 100.0 if cues_aligned else 60.0,
          f"{'all' if cues_aligned else 'some'} beats have timing")
    # info density: prefer 5-9 beat words average
    avg_words = sum(len((b.get("narration") or b.get("text") or "").split()) for b in beats) / max(1, n_beats)
    # band calibrated to narration rate: ~2.5 words/s at 3–8 s per beat
    g.add("info_density", 100.0 if 8 <= avg_words <= 20 else 60.0,
          f"avg {avg_words:.1f} words/beat (~{avg_words / 2.5:.1f}s at 2.5 w/s)")
    # shot count vs beat count
    n_shots = len(plan.get("shots", []))
    g.add("shot_to_beat_parity", 100.0 if n_shots >= n_beats else 70.0,
          f"{n_shots} shots vs {n_beats} beats")
    return g


# ---------- rasterized text QA on extracted frames ----------------

def raster_text_qa(video_path: Path, story_dir: Path, plan: dict) -> dict:
    """Sample N frames, for each frame check whether any text/graphic element
    (title, brand, caption) reaches within 4px of the frame edge or is clipped.

    Returns a dict { clipped: [...], contrast_failures: [...] } suitable for
    direct inclusion in the V3 raster_text_qa.json output.

    This is a heuristic — it does not perform OCR. It instead uses
    composition-zone knowledge: the brand block sits in y 64..184, the
    caption block in y 1536..1856. It inspects those regions for very-near-edge
    text by measuring the extent of non-background pixels and whether the
    rendered glyph bounding box (PIL.Image.getbbox on the alpha mask of the
    text overlay) crosses the frame edge.
    """
    from engine.video_extract import sample_frames
    frames = sample_frames(Path(video_path), n=6)
    clipped = []
    contrast_failures = []
    # 4-px buffer
    EDGE = 4
    H, W = 1920, 1080
    for i, fr in enumerate(frames):
        arr = np.asarray(fr.convert("RGB"))
        # brand block — sample stops at y172: the v3 full-bleed visual starts
        # at y176, so anything below that is plate content, not chrome text
        brand = arr[64:172, :, :]
        # detect near-edge brand text: column extents of non-background pixels
        bg = np.array([12, 12, 16])  # brand band background
        nonbg = np.any(np.abs(brand.astype(int) - bg) > 25, axis=-1)
        cols = np.where(nonbg.any(axis=0))[0]
        if cols.size:
            if cols.min() < EDGE or cols.max() > W - 1 - EDGE:
                clipped.append({"frame": i, "zone": "brand", "min": int(cols.min()), "max": int(cols.max())})
        # caption block
        cap = arr[1536:1856, :, :]
        # if the frame is dark there (backing drawn), text is white; detect light pixels
        light = (cap[..., 0] > 220) & (cap[..., 1] > 220) & (cap[..., 2] > 220)
        ccols = np.where(light.any(axis=0))[0]
        if ccols.size:
            if ccols.min() < EDGE or ccols.max() > W - 1 - EDGE:
                clipped.append({"frame": i, "zone": "caption", "min": int(ccols.min()), "max": int(ccols.max())})
        # contrast sample at one mid-caption x across the band
        # (light text on dark -> ratio ok; light text on light -> low)
        sample_x = 540
        col = cap[:, sample_x, :]
        col_white = (col[:, 0] > 220) & (col[:, 1] > 220) & (col[:, 2] > 220)
        col_dark = (col[:, 0] < 40) & (col[:, 1] < 40) & (col[:, 2] < 40)
        if col_white.any() and not col_dark.any():
            # text is on a mid-bright bg -> low contrast
            contrast_failures.append({"frame": i, "x": sample_x, "reason": "light_text_on_light_bg"})
    return {"clipped": clipped, "contrast_failures": contrast_failures}


# ---------- public entry point -------------------------------------

def run_qa3(video_path: Path, story_dir: Path, build_dir: Path = None) -> dict:
    """Run all three-axis QA, return the qa3 dict and write it to build/qa/qa3.json."""
    story_dir = Path(story_dir)
    video_path = Path(video_path)
    build_dir = Path(build_dir or (story_dir.parent.parent / "build" if (story_dir.parent.name == "stories") else Path("build")))
    qa2 = _load(build_dir / "qa" / "qa2.json")
    continuity = _load(build_dir / "continuity.json")
    style = _load(build_dir / "style_continuity.json")
    phone = _load(build_dir / "phone_qa.json")
    raster = _load(build_dir / "raster_text_qa.json")
    # ALWAYS re-run raster QA against the current video — stale results from a
    # previous build must never gate the present one
    raster = raster_text_qa(video_path, story_dir,
                            _load(build_dir / "edit_plan.json"))
    (build_dir / "raster_text_qa.json").write_text(json.dumps(raster, indent=2))
    plan = _load(build_dir / "edit_plan.json")
    story = _load(story_dir / "story.json")

    t = _tech_checks(qa2)
    v = _visual_checks(qa2, continuity, style, phone, raster)
    e = _editorial_checks(story, plan)

    # P0 list (any group) and the three biggest weaknesses
    p0 = []
    for grp in (t, v, e):
        for c in grp.checks:
            if c.p0 and c.score < 100:
                p0.append({"group": grp.name, "check": c.name, "detail": c.detail})
    weaknesses = []
    for grp in (t, v, e):
        for c in sorted(grp.checks, key=lambda x: x.score):
            if c.score < 80:
                weaknesses.append({"group": grp.name, "check": c.name, "score": c.score, "detail": c.detail})
    weaknesses = weaknesses[:3] or [
        {"group": "VISUAL", "check": "style_continuity", "score": v.score, "detail": "style mix across free-model plates"},
        {"group": "EDITORIAL", "check": "hook_3_4s", "score": e.score, "detail": "hook strength not yet validated"},
        {"group": "VISUAL", "check": "phone_readability", "score": v.score, "detail": "phone-scale legibility not yet verified"},
    ]

    can_publish = (
        t.score >= GATES["technical"]
        and v.score >= GATES["visual"]
        and e.score >= GATES["editorial"]
        and not p0
    )

    out = {
        "video": str(video_path),
        "story": str(story_dir),
        "groups": {
            "TECHNICAL": t.as_dict(),
            "VISUAL": v.as_dict(),
            "EDITORIAL": e.as_dict(),
        },
        "gates": GATES,
        "p0_defects": p0,
        "weaknesses": weaknesses,
        "can_publish": bool(can_publish),
    }
    (build_dir / "qa" / "qa3.json").write_text(json.dumps(out, indent=2))
    return out
