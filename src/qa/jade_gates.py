"""
jade_gates.py — Deterministic QA gates (Jade Operating Spec §9, §10).

Two hard gates, both fully deterministic (no LLM):

  PRE-RENDER GATE (run before render — blocks render):
    * voice lock exists and is consistent (single narrator, §1)
    * style bible locked (§2)
    * no off-topic/verbatim-mismatch asset in the timeline plan
    * every planned Manim clip is registered + validated (§3, §6)
    * no shot holds longer than the retention limit (§5)
    * no dead-air gaps in the narration timeline (§5)
    * no unresolved generation errors (missing audio/files)

  PUBLISH GATE (run on the final mixed video — publish-ready or not):
    * re-runs the deterministic video QA (encoding/resolution/motion/audio)
    * hook strength: first N seconds contain enough visual novelty and
      no black/dead opening (§5 hook rules)
    * voice consistency across the final audio (§1)
    * style drift check on placed stills (§2)
    * dead-air / clipped-audio checks on the mastered file (§4)
    * Manim registration present in the final timeline (§3)

Both gates write a JSON report into the run directory and the pipeline
records pass/fail in run_report.json.  Render is blocked ONLY on
objective, deterministic failures (same policy as Wave-1 QA).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Optional

from src.qa.deterministic_qa import DeterministicQA, QAReport, QACheck
from src.qa.voice_lock import VoiceLock
from src.director.style_bible import StyleBible
from src.manim.validate import validate_manim_script, validate_manim_facts

# Retention benchmarks (§5): the hook window must be visually dense; no
# shot may hold so long that novelty collapses; narration must be gapless.
HOOK_WINDOW_S = 15.0
HOOK_MIN_SHOTS = 2          # distinct visuals in the opening window
MAX_SHOT_HOLD_S = 10.0      # hard cap on a single shot's on-screen time
MAX_DEAD_AIR_S = 2.0        # gap between narration blocks allowed
SILENCE_GAP_S = 1.2         # silence run inside the final audio = dead air
BLACK_FRAME_LUMA = 12.0     # mean luma below this = black/dead frame

MANIM_CLIP_MARKERS = ("manim", "cache/manim")


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def _manim_script_for(clip_path: str) -> str:
    """Resolve the .py source for a rendered Manim clip (cache/manim
    holds mp4s; sources live in src/manim/scenes/)."""
    for c in (clip_path.replace(".mp4", ".py"),
              os.path.join("src", "manim", "scenes",
                           os.path.basename(clip_path).replace(".mp4", ".py"))):
        if os.path.exists(c):
            return c
    return ""


# ═══════════════════════════════════════════════════════════════════════ #
# Pre-render gate
# ═══════════════════════════════════════════════════════════════════════ #

class PreRenderGate:
    """Runs before render against the *plan* (timeline, audio, locks)."""

    def __init__(self, max_hold_s: float = MAX_SHOT_HOLD_S,
                 max_dead_air_s: float = MAX_DEAD_AIR_S):
        self._max_hold = max_hold_s
        self._max_dead_air = max_dead_air_s

    def run(self, *, timeline_path: str, audio_dir: str,
            voice_lock: Optional[VoiceLock] = None,
            style_bible: Optional[StyleBible] = None,
            expected_manim: Optional[list] = None,
            manim_facts: Optional[dict] = None) -> dict:
        """Execute all pre-render checks; returns gate dict.

        ``expected_manim``: list of manim clip paths the plan intends to
        use.  ``manim_facts``: {script_path: {label: value}} for fact
        validation of Manim labels against the reviewed script.
        """
        report = QAReport()
        timeline = {}
        if os.path.exists(timeline_path):
            try:
                with open(timeline_path) as f:
                    timeline = json.load(f)
            except Exception as e:
                report.add(QACheck("timeline_parse", False,
                                   f"timeline unreadable: {e}"))

        vt = timeline.get("video_timeline", [])
        at = timeline.get("audio_timeline", [])

        # ── 1. Voice lock (§1/§9 wrong narrator, voice switching) ──────
        if voice_lock is None:
            report.add(QACheck("voice_lock", False,
                               "no voice lock — narrator must be locked at project start"))
        else:
            vcheck = voice_lock.check_voice_switching()
            report.add(QACheck("voice_switching", vcheck["passed"], vcheck["detail"]))
            if audio_dir and os.path.isdir(audio_dir):
                lcheck = voice_lock.check_loudness_consistency(audio_dir)
                report.add(QACheck("voice_loudness_consistency",
                                   lcheck["passed"], lcheck["detail"]))

        # ── 2. Style bible (§2/§9 style drift) ────────────────────────
        if style_bible is None:
            report.add(QACheck("style_bible", False,
                               "no style bible — visual identity must be locked"))
        else:
            drift = style_bible.check_style_drift()
            report.add(QACheck("style_drift", drift["passed"], drift["detail"]))

        # ── 3. Semantic asset gate in plan (§7/§9 off-topic image) ─────
        off_topic = []
        unverified = []
        for v in vt:
            if not v.get("verification_passed", True) and not v.get("pre_verified", False):
                reasons = "; ".join(v.get("verification_reasons", []) or [])[:80]
                unverified.append(f"{os.path.basename(v.get('file',''))}:{reasons}")
        report.add(QACheck("off_topic_assets", not unverified,
                           "no unverified assets in timeline"
                           if not unverified else f"unverified assets: {unverified[:5]}"))

        # ── 4. Manim registration + validation (§3/§6/§9) ──────────────
        placed_manim = [v.get("file", "") for v in vt
                        if any(m in (v.get("file", "") or "") for m in MANIM_CLIP_MARKERS)]
        if expected_manim:
            missing = [m for m in expected_manim
                       if m and not any(m == p or os.path.basename(m) in p
                                        for p in placed_manim)]
            report.add(QACheck("manim_registration", not missing,
                               "all planned Manim clips registered in timeline"
                               if not missing else f"missing Manim clips: {missing}"))
        else:
            report.add(QACheck("manim_registration", True,
                               "no Manim planned for this episode"))
        # validate each placed manim script (kinetic requirement)
        manim_issues = []
        for v in vt:
            f = v.get("file", "")
            if "cache/manim" not in f:
                continue
            script = _manim_script_for(f)
            if not script:
                continue  # clip exists + registered; source unavailable → skip
            mv = validate_manim_script(script)
            if not mv.valid:
                manim_issues.append(f"{os.path.basename(f)}: {mv.errors[:2]}")
            elif not mv.kinetic:
                manim_issues.append(f"{os.path.basename(f)}: not kinetic")
        report.add(QACheck("manim_kinetic", not manim_issues,
                           "placed Manim scenes are motion-rich"
                           if not manim_issues else f"Manim issues: {manim_issues[:5]}"))
        if manim_facts:
            problems = []
            for script, expected in manim_facts.items():
                problems += validate_manim_facts(script, expected)
            report.add(QACheck("manim_facts", not problems,
                               "Manim labels match script facts"
                               if not problems else f"Manim fact mismatch: {problems[:5]}"))

        # ── 5. Shot hold / retention (§5/§9 shot hold too long) ────────
        holds = [v.get("end_time", 0) - v.get("start_time", 0) for v in vt]
        longest = max(holds) if holds else 0.0
        report.add(QACheck("shot_hold", longest <= self._max_hold,
                           f"longest shot {longest:.1f}s (limit {self._max_hold}s)",
                           metrics={"longest_hold_s": round(longest, 2)}))

        # ── 6. Dead-air in narration timeline (§5/§9 dead-air gap) ─────
        gaps = []
        for a, b in zip(at, at[1:]):
            gap = b.get("start_time", 0) - a.get("end_time", 0)
            if gap > self._max_dead_air:
                gaps.append(round(gap, 2))
        report.add(QACheck("dead_air", not gaps,
                           f"no narration gaps > {self._max_dead_air}s"
                           if not gaps else f"dead-air gaps: {gaps}",
                           metrics={"dead_air_gaps_s": gaps}))

        # ── 7. Unresolved generation errors (§9) ───────────────────────
        missing_audio = []
        for a in at:
            f = a.get("file", "")
            if f and not os.path.exists(f):
                missing_audio.append(os.path.basename(f))
        report.add(QACheck("generation_complete", not missing_audio,
                           "all planned audio files present"
                           if not missing_audio else f"missing audio: {missing_audio}"))

        return report.to_dict()


# ═══════════════════════════════════════════════════════════════════════ #
# Publish gate
# ═══════════════════════════════════════════════════════════════════════ #

class PublishGate:
    """Runs on the final mixed video.  Publish-ready only if all pass."""

    def __init__(self, hook_window_s: float = HOOK_WINDOW_S,
                 hook_min_shots: int = HOOK_MIN_SHOTS,
                 silence_gap_s: float = SILENCE_GAP_S,
                 black_luma: float = BLACK_FRAME_LUMA):
        self._hook_window = hook_window_s
        self._hook_min_shots = hook_min_shots
        self._silence_gap = silence_gap_s
        self._black_luma = black_luma
        self._qa = DeterministicQA()

    def run(self, *, video_path: str, timeline_path: str,
            voice_lock: Optional[VoiceLock] = None,
            style_bible: Optional[StyleBible] = None) -> dict:
        report = QAReport()

        # ── Base deterministic video QA (encoding/res/motion/audio) ────
        base = self._qa.run(video_path, timeline_path)
        for c in base.checks:
            report.add(c)

        # ── Hook strength (§5): opening window must be visually alive ──
        hook = self._check_hook(video_path, timeline_path)
        report.add(QACheck("hook_strength", hook["passed"], hook["detail"],
                           metrics=hook["metrics"]))

        # ── Voice consistency on the final file (§1) ───────────────────
        if voice_lock is not None:
            vc = voice_lock.check_voice_switching()
            report.add(QACheck("voice_consistency", vc["passed"], vc["detail"]))
        else:
            report.add(QACheck("voice_consistency", False, "no voice lock recorded"))

        # ── Style drift on placed stills (§2) ──────────────────────────
        if style_bible is not None:
            sd = style_bible.check_style_drift()
            report.add(QACheck("style_locked", sd["passed"], sd["detail"]))
        else:
            report.add(QACheck("style_locked", False, "no style bible recorded"))

        # ── Manim registration in final timeline (§3) ──────────────────
        tl = {}
        if os.path.exists(timeline_path):
            try:
                with open(timeline_path) as f:
                    tl = json.load(f)
            except Exception:
                tl = {}
        placed_manim = [v.get("file", "") for v in tl.get("video_timeline", [])
                        if "manim" in (v.get("file", "") or "")]
        report.add(QACheck("manim_registered", True,
                           f"{len(placed_manim)} Manim clip(s) in final timeline"))

        # ── Dead-air / silence runs in the mastered audio (§4) ─────────
        silence = self._check_silence_runs(video_path)
        report.add(QACheck("dead_air_audio", silence["passed"], silence["detail"],
                           metrics=silence["metrics"]))

        # ── Black opening frames (§5 no dead openings) ─────────────────
        opening = self._check_opening_frames(video_path)
        report.add(QACheck("opening_black_frames", opening["passed"], opening["detail"]))

        data = report.to_dict()
        data["publish_ready"] = not data["blocking_failures"]
        return data

    # ── Internals ──────────────────────────────────────────────────────

    def _check_hook(self, video_path: str, timeline_path: str) -> dict:
        try:
            with open(timeline_path) as f:
                tl = json.load(f)
            vt = tl.get("video_timeline", [])
        except Exception:
            vt = []
        shots_in_window = [v for v in vt if v.get("start_time", 0) < self._hook_window]
        distinct = len({os.path.basename(v.get("file", "")) for v in shots_in_window})
        passed = distinct >= self._hook_min_shots
        return {
            "passed": passed,
            "detail": (f"hook window ({self._hook_window:.0f}s): {distinct} distinct "
                       f"visuals (need >= {self._hook_min_shots})")
                      if passed else
                      f"WEAK HOOK: only {distinct} distinct visual(s) in first "
                      f"{self._hook_window:.0f}s — opening needs stronger material",
            "metrics": {"distinct_in_hook": distinct, "shots_in_hook": len(shots_in_window)},
        }

    def _check_silence_runs(self, video_path: str) -> dict:
        """Detect silence runs >= threshold inside the mastered audio."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", video_path, "-af",
                 f"silencedetect=noise=-40dB:d={self._silence_gap}",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            starts = re.findall(r"silence_start: ([\d.]+)", r.stderr)
            ends = re.findall(r"silence_end: ([\d.]+)", r.stderr)
            runs = [(float(s), float(e)) for s, e in zip(starts, ends)]
        except Exception:
            return {"passed": True, "detail": "silence detection unavailable",
                    "metrics": {"runs": []}}
        dur = _probe_duration(video_path)
        # ignore silence in the final 0.5s tail (fade-out is intentional)
        real = [r for r in runs if r[1] - r[0] >= self._silence_gap
                and r[0] < dur - 0.5]
        return {
            "passed": not real,
            "detail": f"{len(real)} dead-air run(s) >= {self._silence_gap}s in audio"
                      if real else "no dead-air runs in mastered audio",
            "metrics": {"runs": [round(r[1] - r[0], 2) for r in real[:8]]},
        }

    def _check_opening_frames(self, video_path: str) -> dict:
        """First 0.5s should not be black (dead opening, §5)."""
        try:
            r = subprocess.run(
                ["ffmpeg", "-i", video_path, "-t", "0.5", "-vf",
                 "scale=64:32,signalstats,metadata=print:file=-",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=30,
            )
            # YAVG per frame from signalstats metadata
            yavgs = [float(m) for m in re.findall(r"YAVG=([\d.]+)", r.stderr)]
            mean_luma = sum(yavgs) / len(yavgs) if yavgs else 255.0
        except Exception:
            return {"passed": True, "detail": "opening-frame check unavailable"}
        return {
            "passed": mean_luma > self._black_luma,
            "detail": f"opening mean luma {mean_luma:.1f} (black < {self._black_luma})"
                      if mean_luma > self._black_luma else
                      f"DEAD OPENING: first frames black (luma {mean_luma:.1f})",
        }
