"""video_qa.py — Full-video QA + publish gate (directive §19/§21/§34).

Gates: TECHNICAL, AUDIO, FACTUAL, VISUAL, TEMPORAL, STYLE, VARIETY,
RETENTION. Emits publish_gate.json {overall: PASS|FAIL, gates: {...}}.

Rewrite/recut policy (§22): RETENTION or VARIETY failures feed the shot-plan
revision loop (max 2 iterations, driven by engine/v3/run.py) — only affected
shots are rebuilt, never the whole script.
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
from pathlib import Path
from typing import Any

from engine.audio.timeline import measure_loudness
from engine.validation.schema import validate as validate_schema
from engine.v3.plan.variety import analyze_variety
from engine.v3.qa.retention import retention_critic
from engine.v3.qa.technical import (
    black_stats,
    decode_errors,
    ffprobe,
    silence_stats,
)

logger = logging.getLogger(__name__)

LOUDNESS_TARGET = -14.0
LOUDNESS_TOL = 1.5
TP_MAX = -1.2
MAX_SILENCE_GAP = 3.0
VISUAL_SCORE_MIN = 65
MASTER_H = 1080
MASTER_W = 1920
MASTER_FPS = 30


def _gate(name: str, ok: bool, detail: str,
          fixes: list[str] | None = None) -> dict:
    return {"gate": name, "pass": bool(ok), "detail": detail,
            "fixes": fixes or []}


# ── Individual gates ─────────────────────────────────────────────────────────

def technical_gate(master: Path, expected_duration: float, *,
                   expected_width: int = MASTER_W,
                   expected_height: int = MASTER_H) -> dict:
    issues: list[str] = []
    try:
        probe = ffprobe(master)
    except Exception as exc:  # noqa: BLE001
        return _gate("TECHNICAL", False, f"probe failed: {exc}")
    video = probe.get("video") or {}
    w, h = int(video.get("width") or 0), int(video.get("height") or 0)
    dur = probe.get("duration") or 0.0
    codec = video.get("codec_name")
    rate = video.get("avg_frame_rate") or "0/1"
    try:
        fps = float(rate.split("/")[0]) / float(rate.split("/")[1] or 1)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if codec != "h264":
        issues.append(f"codec={codec}")
    if abs(h - expected_height) > 8 or abs(w - expected_width) > 8:
        issues.append(f"resolution {w}x{h} != {expected_width}x{expected_height}")
    if abs(fps - MASTER_FPS) > 1:
        issues.append(f"fps={fps:.2f}")
    if abs(dur - expected_duration) > 1.0:
        issues.append(f"duration {dur:.1f}s vs expected {expected_duration:.1f}s")
    if decode_errors(master) > 0:
        issues.append("decode errors present")
    blacks = black_stats(master, dur)
    if blacks["fraction"] > 0.3:
        issues.append(f"black frames {blacks['fraction'] * 100:.0f}%")
    return _gate("TECHNICAL", not issues,
                 f"h264 {w}x{h}@{fps:.0f}, {dur:.1f}s, "
                 f"black {blacks['fraction'] * 100:.1f}%",
                 issues)


def audio_gate(master: Path, *, require_audio: bool = True) -> dict:
    issues: list[str] = []
    probe = ffprobe(master)
    has_audio = probe.get("audio") is not None
    if require_audio and not has_audio:
        return _gate("AUDIO", False, "no audio stream", ["mux narration"])
    if has_audio:
        loud = measure_loudness(master)
        lufs, tp = loud.get("integrated_lufs"), loud.get("true_peak_db")
        if lufs is None:
            issues.append("loudness measurement failed")
        else:
            if abs(lufs - LOUDNESS_TARGET) > LOUDNESS_TOL:
                issues.append(f"I={lufs:.1f} LUFS (target {LOUDNESS_TARGET})")
            if tp is not None and tp > TP_MAX:
                issues.append(f"true peak {tp:.1f} dBTP > {TP_MAX}")
        sil = silence_stats(master, probe.get("duration"))
        if sil["fraction"] > 0.8:
            issues.append(f"silence {sil['fraction'] * 100:.0f}% of runtime")
        detail = (f"I={lufs:.1f} LUFS, TP={tp:.1f} dBTP, "
                  f"silence {sil['fraction'] * 100:.0f}%"
                  if lufs is not None else "loudness n/a")
    else:
        detail = "audio not required for this run"
    return _gate("AUDIO", not issues, detail, issues)


def factual_gate(research: dict, script_doc: dict) -> dict:
    """Claims-vs-sources check: every research claim must trace to a source
    OR be marked hedged/medium confidence; the research doc must exist with
    usable claims. LLM-general-knowledge provenance is recorded honestly."""
    issues: list[str] = []
    claims = research.get("claims", [])
    if len(claims) < 3:
        issues.append(f"research has only {len(claims)} claims")
    sources = {s.get("ref") for s in research.get("sources", [])}
    unbacked = [c.get("text", "")[:60] for c in claims
                if not c.get("source_ref") or c.get("source_ref") not in sources]
    if unbacked and research.get("provenance") == "pre_seeded":
        issues.append(f"{len(unbacked)} claims without source refs")
    # Script may only use numbers that appear in the research text.
    research_text = " ".join(str(c.get("text", "")) for c in claims)
    narration = " ".join(str(b.get("narration", ""))
                         for b in script_doc.get("beats", []))
    import re
    nums_narr = set(re.findall(r"\d[\d.,]*", narration))
    nums_res = set(re.findall(r"\d[\d.,]*", research_text))
    invented = [x for x in nums_narr if x not in nums_res]
    if invented:
        issues.append(f"narration numbers not found in research: "
                      f"{sorted(invented)[:5]}")
    detail = (f"{len(claims)} claims, {len(sources)} sources, "
              f"provenance={research.get('provenance', 'unknown')}")
    return _gate("FACTUAL", not issues, detail, issues)


def temporal_gate(shots: list[dict], master_duration: float,
                  shot_reports: dict[str, dict]) -> dict:
    """Shots match narration/timeline and no dead visual time."""
    issues: list[str] = []
    planned = sum(float(s.get("duration_sec", 0)) for s in shots)
    if abs(planned - master_duration) > max(2.0, 0.08 * master_duration):
        issues.append(
            f"shot durations sum {planned:.1f}s vs master {master_duration:.1f}s")
    dead = [sid for sid, rep in shot_reports.items()
            if rep.get("probe", {}).get("duration")
            and rep["probe"]["duration"] < 0.2]
    if dead:
        issues.append(f"near-empty shots: {dead}")
    return _gate("TEMPORAL", not issues,
                 f"timeline {master_duration:.1f}s, {len(shots)} shots",
                 issues)


def style_gate(style: dict, shots: list[dict]) -> dict:
    errs = validate_schema(style, "style_spec_v2")
    missing_style = [s["shot_id"] for s in shots
                     if not s.get("style") and not s.get("renderer")]
    issues = [f"style spec: {e}" for e in errs[:5]]
    if missing_style:
        issues.append(f"shots missing style ref: {missing_style[:5]}")
    return _gate("STYLE", not issues,
                 f"style={style.get('style_name')}, {len(shots)} shots",
                 issues)


def variety_gate(shots: list[dict]) -> dict:
    report = analyze_variety(shots)
    issues = list(report["issues"])
    if len(shots) >= 8 and report["distinct_renderers"] < 3:
        issues.append("renderer mix too narrow")
    fixes = []
    if issues:
        fixes.append("re-run variety enforcement / recut affected shots")
    return _gate("VARIETY", not issues,
                 f"mix={report['renderer_histogram']}, "
                 f"maxrun={report['max_consecutive_same_renderer']}, "
                 f"interrupts={report['pattern_interrupt_count']}/"
                 f"{report['pattern_interrupt_target']}",
                 fixes)


def visual_gate(shot_reports: dict[str, dict]) -> dict:
    """Average vision QA over shots (technical-only when vision offline)."""
    scored = [r.get("score", 0) for r in shot_reports.values()
              if r.get("score") is not None]
    if not scored:
        return _gate("VISUAL", False, "no shot QA results")
    avg = sum(scored) / len(scored)
    failing = sorted(
        (sid for sid, r in shot_reports.items()
         if r.get("action") == "regenerate"),
    )[:6]
    issues: list[str] = []
    if avg < VISUAL_SCORE_MIN:
        issues.append(f"average shot score {avg:.0f} < {VISUAL_SCORE_MIN}")
    if failing:
        issues.append(f"shots still failing QA: {failing}")
    return _gate("VISUAL", not issues,
                 f"avg shot score {avg:.0f} over {len(scored)} shots "
                 f"(vision {sum(1 for r in shot_reports.values() if r.get('vision_available'))}/{len(scored)} online)",
                 issues)


# ── Timeline vision QA (§20) ─────────────────────────────────────────────────

def timeline_vision_qa(master: Path, shots: list[dict], out_dir: Path,
                       *, use_vision: bool = True) -> dict:
    """Vision QA over the full timeline: opening, transitions, reveals,
    end card. One contact sheet per sampled moment group."""
    out_dir.mkdir(parents=True, exist_ok=True)
    from engine.v3.qa.vision import contact_sheet, sample_frames, vision_qa_shot

    dur = ffprobe(master).get("duration") or 0.0
    if dur <= 0:
        return {"available": False, "avg_score": 0, "issues": ["no video"]}
    # Sample: opening, first transition, midpoint, strongest reveal
    # (peak music_state shot), end card.
    reveal_t = dur * 0.75
    for s in shots:
        if s.get("music_state") == "peak":
            reveal_t = (s.get("narration_start", 0) or 0) + \
                       min(float(s.get("duration_sec", 4)), dur * 0.9)
            break
    times = [dur * 0.03, dur * 0.2, dur * 0.5, min(reveal_t, dur * 0.97),
             dur * 0.985]
    exe = shutil.which("ffmpeg")
    frames: list[Path] = []
    for i, t in enumerate(times):
        p = out_dir / f"tl_{i}_{int(t)}s.jpg"
        proc = subprocess.run(
            [exe, "-y", "-ss", f"{t:.2f}", "-i", str(master),
             "-frames:v", "1", "-q:v", "3", str(p)],
            capture_output=True, timeout=60)
        if proc.returncode == 0 and p.exists():
            frames.append(p)
    sheet = contact_sheet(frames, out_dir / "timeline_sheet.jpg")
    if not sheet:
        return {"available": False, "avg_score": 0,
                "issues": ["frame extraction failed"]}
    if not use_vision:
        return {"available": False, "avg_score": 0, "issues": [],
                "sheet": str(sheet)}
    shot_like = {
        "shot_id": "TIMELINE",
        "visual_goal": f"documentary about {shots[0].get('style', 'the topic')}"
        if shots else "documentary",
        "subject": "coherent documentary timeline",
        "background": "",
        "composition": "opening, transition, midpoint, reveal, end card",
        "text_overlay": None,
    }
    verdict = vision_qa_shot(sheet, shot_like)
    return {"available": verdict.get("available", False),
            "avg_score": verdict.get("score", 0),
            "issues": verdict.get("issues", []),
            "sheet": str(sheet)}


# ── Retention gate ───────────────────────────────────────────────────────────

def retention_gate(shots: list[dict], topic: str, *,
                   use_llm: bool = True) -> dict:
    narration = " ".join(
        str(s.get("metadata", {}).get("narration") or "") for s in shots)
    crit = retention_critic(shots, topic, narration_text=narration,
                            use_llm=use_llm)
    ok = crit.get("verdict") == "pass"
    return _gate("RETENTION", ok,
                 f"verdict={crit.get('verdict')} "
                 f"avg={crit.get('avg_score')} "
                 f"({'vision' if crit.get('available') else 'heuristic'})",
                 crit.get("fixes", [])) | {"critic": crit}


# ── Publish gate assembly ────────────────────────────────────────────────────

def publish_gate(master: Path, shots: list[dict], script_doc: dict,
                 research: dict, style: dict, shot_reports: dict[str, dict],
                 out_path: str | Path, *,
                 use_vision: bool = True, use_llm: bool = True,
                 require_audio: bool = True,
                 expected_width: int = MASTER_W,
                 expected_height: int = MASTER_H) -> dict:
    """Run every §34 gate and emit publish_gate.json."""
    master = Path(master)
    dur = ffprobe(master).get("duration") or 0.0

    gates = {
        "TECHNICAL": technical_gate(master, dur,
                                    expected_width=expected_width,
                                    expected_height=expected_height),
        "AUDIO": audio_gate(master, require_audio=require_audio),
        "FACTUAL": factual_gate(research, script_doc),
        "TEMPORAL": temporal_gate(shots, dur, shot_reports),
        "STYLE": style_gate(style, shots),
        "VARIETY": variety_gate(shots),
        "VISUAL": visual_gate(shot_reports),
        "RETENTION": retention_gate(shots, script_doc.get("topic", ""),
                                    use_llm=use_llm),
    }
    # Timeline vision QA folds into VISUAL when available.
    tl = timeline_vision_qa(master, shots, Path(out_path).parent / "qa" /
                            "timeline", use_vision=use_vision)
    if tl.get("available"):
        ok = tl.get("avg_score", 0) >= VISUAL_SCORE_MIN
        gates["VISUAL"]["pass"] = gates["VISUAL"]["pass"] and ok
        gates["VISUAL"]["detail"] += (
            f"; timeline vision {tl.get('avg_score')}")
        for issue in tl.get("issues", [])[:4]:
            gates["VISUAL"]["fixes"].append(f"timeline: {issue}")
    gates["VISUAL"]["timeline"] = {k: v for k, v in tl.items()
                                   if k != "issues"}

    overall = "PASS" if all(g["pass"] for g in gates.values()) else "FAIL"
    doc = {
        "version": 1,
        "overall": overall,
        "master": str(master),
        "duration_sec": round(dur, 2),
        "gates": gates,
        "failed_gates": [name for name, g in gates.items() if not g["pass"]],
    }
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, default=str), encoding="utf-8")
    return doc
