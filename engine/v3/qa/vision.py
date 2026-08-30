"""vision.py — Vision QA over representative frames (directive §20).

Samples frames per shot (first / mid / last + randoms), builds a contact
sheet, and asks the DeepSeek vision model for a structured verdict
{score, issues[], ok}. Offline fallback: the caller uses technical-only
scoring (vision_qa returns available=False).

Frame sampling mirrors tools/describe_frames.py conventions; the model call
reuses the broker's DeepSeekVisionProvider (same base64 chat-completions
pattern, Wave-2 verified).
"""

from __future__ import annotations

import json
import logging
import random
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

VISION_QA_SYSTEM = (
    "You are a shot QA inspector for a documentary video pipeline. You "
    "inspect representative frames from ONE rendered shot and score its "
    "visual quality. Output ONLY valid JSON — no commentary."
)

VISION_QA_PROMPT = """This contact sheet shows up to 3 frames (left=first,
middle=middle, right=last) from one rendered shot of a documentary video.

Expected content of the shot:
- visual goal: {visual_goal}
- subject: {subject}
- background: {background}
- composition: {composition}

Score the shot 0-100 and list concrete issues. STRICT JSON only:
{{"score": <0-100 int>, "issues": ["<specific, actionable issue>"],
"ok": <bool>}}

Penalise heavily:
- black, empty, or nearly-empty frames; letterboxing bars
- garbled or hallucinated text (text_overlay was: {text_overlay!r})
- distorted anatomy or physically impossible artifacts
- a subject unrelated to the expected content
- severe blur, smearing, or duplicated features
Do NOT penalise: film grain, cinematic colour grading, motion blur that
reads as camera movement, stylisation consistent with a documentary look."""


def sample_frames(path: str | Path, out_dir: str | Path, *,
                  n: int = 5, seed: int = 0) -> list[Path]:
    """Extract n representative frames: first, mid, last + (n-3) randoms."""
    from engine.v3.qa.technical import ffprobe

    p = Path(path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    probe = ffprobe(p)
    dur = probe.get("duration") or 0.0
    if dur <= 0:
        return []
    times = [0.04 * dur, 0.5 * dur, dur * 0.96]
    if n > 3 and dur > 1.0:
        rng = random.Random(seed)
        times += sorted(rng.uniform(0.1 * dur, 0.9 * dur)
                        for _ in range(n - 3))
    frames: list[Path] = []
    exe = shutil.which("ffmpeg")
    for i, t in enumerate(times):
        out_path = out / f"{p.stem}_f{i}_{t:05.1f}.jpg"
        proc = subprocess.run(
            [exe, "-y", "-ss", f"{t:.2f}", "-i", str(p), "-frames:v", "1",
             "-q:v", "3", str(out_path)],
            capture_output=True, timeout=60)
        if proc.returncode == 0 and out_path.exists() \
                and out_path.stat().st_size > 0:
            frames.append(out_path)
    return frames


def contact_sheet(frames: list[Path], out_path: Path) -> Path | None:
    """Horizontal contact sheet of up to 3 frames (one vision call/shot)."""
    if not frames:
        return None
    selected = frames[:1] + (frames[len(frames) // 2:len(frames) // 2 + 1]
                             if len(frames) > 1 else []) + frames[-1:]
    seen: list[Path] = []
    for f in selected:
        if f not in seen:
            seen.append(f)
    exe = shutil.which("ffmpeg")
    inputs: list[str] = []
    for f in seen:
        inputs += ["-i", str(f)]
    n = len(seen)
    proc = subprocess.run(
        [exe, "-y", *inputs, "-filter_complex",
         f"hstack=inputs={n}" if n > 1 else "null",
         "-frames:v", "1", "-q:v", "4", str(out_path)],
        capture_output=True, timeout=60)
    if proc.returncode == 0 and out_path.exists() \
            and out_path.stat().st_size > 0:
        return out_path
    logger.warning("contact sheet failed: %s", proc.stderr[-200:])
    return None


def vision_qa_shot(sheet: Path, shot: dict) -> dict:
    """One vision call per shot over the contact sheet.

    Returns {"available": bool, "score": int, "issues": [str], "raw": str}
    — available=False means the caller falls back to technical-only QA.
    """
    try:
        from engine.broker.providers.deepseek import DeepSeekVisionProvider

        provider = DeepSeekVisionProvider()
        if not provider.capabilities().enabled:
            return {"available": False, "score": 0, "issues": [],
                    "raw": "deepseek key not configured"}
        prompt = VISION_QA_PROMPT.format(
            visual_goal=str(shot.get("visual_goal", ""))[:200],
            subject=str(shot.get("subject", ""))[:200],
            background=str(shot.get("background", ""))[:120],
            composition=str(shot.get("composition", ""))[:120],
            text_overlay=shot.get("text_overlay"),
        )
        resp = provider.analyze_image(sheet, prompt)
        content = resp.get("content", "") if isinstance(resp, dict) else ""
        # Extract the JSON verdict from the reply.
        try:
            from engine.v3.story.llm import extract_json

            data = extract_json(content)
        except Exception:  # noqa: BLE001
            return {"available": False, "score": 0, "issues": [],
                    "raw": f"unparseable vision reply: {content[:200]}"}
        score = data.get("score")
        if not isinstance(score, (int, float)):
            return {"available": False, "score": 0, "issues": [],
                    "raw": f"vision reply missing score: {content[:200]}"}
        issues = [str(i) for i in (data.get("issues") or []) if str(i).strip()]
        return {"available": True,
                "score": int(max(0, min(100, round(score)))),
                "issues": issues,
                "ok": bool(data.get("ok", score >= 60)),
                "raw": content[:400]}
    except Exception as exc:  # noqa: BLE001 — vision must never kill the run
        logger.warning("vision QA failed for %s: %s",
                       shot.get("shot_id"), exc)
        return {"available": False, "score": 0, "issues": [],
                "raw": f"{type(exc).__name__}: {exc}"[:200]}
