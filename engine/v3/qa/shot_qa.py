"""shot_qa.py — Combined per-shot QA (technical + vision, cached).

Score model (§20 structured findings {shot_id, score, issues[], action}):
- technical pass baseline 100; each failed gate −15;
- when vision is available: final = round(0.6·vision + 0.4·technical);
- action: keep (≥70 and technical pass) | regenerate | re-route.

Every QA result is cached (§25) keyed by the sha256 of the rendered file +
shot content + QA config; unchanged shots are never re-inspected.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from engine.v3.qa.technical import technical_qa
from engine.v3.qa.vision import contact_sheet, sample_frames, vision_qa_shot

logger = logging.getLogger(__name__)

REGEN_SCORE_THRESHOLD = 70
FAILED_GATE_PENALTY = 15
GATE_WEIGHT = 0.4
VISION_WEIGHT = 0.6


def _qa_key(path: Path, shot: dict, expect_audio: bool,
            use_vision: bool) -> str:
    basis = json.dumps({
        "file_sha": _file_sha(path), "shot": _shot_fingerprint(shot),
        "expect_audio": expect_audio, "use_vision": use_vision,
        "qa_version": 1,
    }, sort_keys=True)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _shot_fingerprint(shot: dict) -> dict:
    keys = ("shot_id", "duration_sec", "renderer", "visual_goal", "subject",
            "camera", "motion", "composition", "generation_priority")
    return {k: shot.get(k) for k in keys}


def qa_shot(shot: dict, path: str | Path, qa_dir: str | Path, *,
            expect_audio: bool = False, use_vision: bool = True,
            min_height: int = 0, sample_seed: int = 0,
            force_fail: bool = False, cache: bool = True) -> dict:
    """QA one rendered shot. Returns the §20 findings document.

    force_fail=True injects a synthetic failure (dev flag --force-fail SXX)
    to exercise the regeneration loop deterministically.
    """
    p = Path(path)
    qdir = Path(qa_dir)
    qdir.mkdir(parents=True, exist_ok=True)
    key = _qa_key(p, shot, expect_audio, use_vision)
    cache_file = qdir / f"{shot.get('shot_id', 'shot')}_{key}.json"
    if cache and cache_file.exists() and not force_fail:
        try:
            doc = json.loads(cache_file.read_text(encoding="utf-8"))
            doc["cached"] = True
            return doc
        except (json.JSONDecodeError, OSError):
            pass

    tech = technical_qa(p, float(shot.get("duration_sec", 4.0)),
                        expect_audio=expect_audio, min_height=min_height)

    tech_score = 100
    for g in tech.get("gates", {}).values():
        if not g.get("pass"):
            tech_score -= FAILED_GATE_PENALTY
    tech_score = max(0, tech_score)

    vision: dict[str, Any] = {"available": False, "score": 0, "issues": []}
    if use_vision and tech.get("probe", {}).get("duration"):
        try:
            frames = sample_frames(p, qdir / "frames" / shot.get(
                "shot_id", "shot"), seed=sample_seed)
            sheet_path = qdir / "sheets" / f"{shot.get('shot_id', 'shot')}.jpg"
            sheet = contact_sheet(frames, sheet_path)
            if sheet:
                vision = vision_qa_shot(sheet, shot)
        except Exception as exc:  # noqa: BLE001
            logger.warning("frame sampling failed for %s: %s",
                           shot.get("shot_id"), exc)

    if vision.get("available"):
        score = round(VISION_WEIGHT * vision["score"]
                      + GATE_WEIGHT * tech_score)
    else:
        # §20 offline fallback: technical-only gate-based score.
        score = tech_score

    issues = list(tech.get("issues", []))
    issues += [f"vision: {i}" for i in vision.get("issues", [])]
    if force_fail:
        issues.append("forced failure (--force-fail dev flag)")
        score = min(score, 30)

    if force_fail or not tech.get("pass") or score < REGEN_SCORE_THRESHOLD:
        action = "regenerate"
    else:
        action = "keep"

    doc = {
        "shot_id": shot.get("shot_id", "?"),
        "file": str(p),
        "score": int(score),
        "technical_pass": bool(tech.get("pass")),
        "technical_score": tech_score,
        "vision_available": bool(vision.get("available")),
        "vision_score": vision.get("score", 0),
        "issues": issues,
        "action": action,
        "gates": tech.get("gates", {}),
        "probe": tech.get("probe", {}),
    }
    if cache and not force_fail:
        try:
            cache_file.write_text(json.dumps(doc, indent=2),
                                  encoding="utf-8")
        except OSError:
            pass
    return doc


def qa_shotlist(shots: list[dict], records: dict[str, dict],
                qa_dir: str | Path, **kw) -> dict[str, dict]:
    """QA every rendered shot. records: shot_id → render record."""
    out: dict[str, dict] = {}
    for shot in shots:
        sid = shot["shot_id"]
        rec = records.get(sid) or {}
        if not rec.get("ok"):
            out[sid] = {
                "shot_id": sid, "score": 0, "action": "regenerate",
                "issues": [f"render failed: {rec.get('attempts', [])[:2]}"],
                "technical_pass": False, "vision_available": False,
            }
            continue
        out[sid] = qa_shot(shot, rec["path"], qa_dir, **kw)
    return out
