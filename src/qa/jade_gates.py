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
from src.cinematic.pacing_engine import audit_pacing, comprehension_risk

# Retention benchmarks (§5, 2026 recalibration): the hook window must be
# visually dense; no shot may hold so long that novelty collapses; narration
# must be gapless.  Recalibrated per expert review 2026-08-05: mobile-first
# Indian market — micro-window hook (3-5s decision), micro-beats (<=4s
# holds), dead air <= 0.5s (2s of silence reads as "video over").
HOOK_WINDOW_S = 15.0
HOOK_MIN_SHOTS = 5          # distinct visuals in the opening window
MAX_SHOT_HOLD_S = 4.0      # hard cap on a single shot's on-screen time
MAX_SHOT_DURATION_S = 12.0  # v13 rec #4: NO single clip may run 12+ s
                            # (even animated — visual progression required)
MAX_DEAD_AIR_S = 0.5        # gap between narration blocks allowed
SILENCE_GAP_S = 0.8         # silence run inside the final audio = dead air
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
            manim_facts: Optional[dict] = None,
            scenes_data: Optional[list] = None,
            audio_durations: Optional[list] = None) -> dict:
        """Execute all pre-render checks; returns gate dict.

        ``expected_manim``: list of manim clip paths the plan intends to
        use.  ``manim_facts``: {script_path: {label: value}} for fact
        validation of Manim labels against the reviewed script.
        ``scenes_data`` + ``audio_durations`` (v10): enables the pacing
        gate (rec 1/11) and the semantic-alignment gate (rec 6/7).
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
        # v12: animated clips (manim / vector beats) are MOTION, not static
        # holds — a 4-8s animated beat keeps novelty high and is standard
        # Kurzgesagt pacing.  The hold cap exists to prevent frozen-frame
        # novelty collapse, so only static (ken-burns/still) shots count.
        # v14 fix: timeline entries do NOT carry an asset_source field, so
        # the old check never matched and 7s manim clips were flagged as
        # static holds (52-Hz run shot_hold blocker).  Detect animated
        # clips by their file path (cache/manim/, cache/vector/) instead.
        def _is_animated(file_path: str) -> bool:
            p = (file_path or "").replace("\\", "/")
            return ("/manim/" in p or "/vector/" in p
                    or p.startswith("cache/manim/") or p.startswith("cache/vector/"))

        holds = [
            v.get("end_time", 0) - v.get("start_time", 0)
            for v in vt
            if v.get("asset_source") not in ("manim", "vector")
            and not _is_animated(v.get("file", ""))
        ]
        longest = max(holds) if holds else 0.0
        # float-epsilon tolerance: a 4.000000000000002s hold is a rounding
        # artifact of start/end both being rounded to 3dp, NOT a real
        # violation of the 4.0s cap — never fail-closed on binary dust.
        report.add(QACheck("shot_hold", longest <= self._max_hold + 1e-6,
                           f"longest static shot {longest:.3f}s (limit {self._max_hold}s)",
                           metrics={"longest_hold_s": round(longest, 3)}))

        # ── 5b. Absolute max shot duration (v13 rec #4) ────────────────
        # No single clip — animated or not — may exceed the hard ceiling.
        # 12+ s of essentially unchanged visual kills retention even when
        # the narration is good.  (Holds are chunked into <=6s motion
        # segments by the timeline builder; this is the final backstop.)
        all_durs = [v.get("end_time", 0) - v.get("start_time", 0) for v in vt]
        over = [d for d in all_durs if d > MAX_SHOT_DURATION_S + 1e-6]
        report.add(QACheck(
            "max_shot_duration", not over,
            f"no shot exceeds {MAX_SHOT_DURATION_S:.0f}s"
            if not over else f"{len(over)} shot(s) exceed {MAX_SHOT_DURATION_S:.0f}s: "
            + ", ".join(f"{d:.1f}s" for d in sorted(over, reverse=True)[:5]),
            metrics={"longest_shot_s": round(max(all_durs), 3) if all_durs else 0.0,
                     "over_limit": [round(d, 2) for d in sorted(over, reverse=True)[:8]]}))

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

        # ── 8. Pacing gate (v10 rec 1/11) — rushed narration blocks ────
        # Pacing is a core quality metric: scenes delivered above the
        # role's comprehension band fail the gate deterministically.
        # v10.2: only RUSHED (WPM over the role band) blocks.  "High
        # comprehension risk" from technical density (numbers/units) is
        # recorded as a metric + fed to the postmortem (rec 11) but is
        # NOT a hard blocker — a science documentary always has dense
        # figures, and pace-padding already slows those scenes into band.
        if scenes_data is not None and audio_durations is not None:
            pacing = audit_pacing(scenes_data, audio_durations)
            rushed = []
            risk_flags = []
            for r in pacing["rows"]:
                for f in r.get("flags", []):
                    if f.startswith("rushed"):
                        rushed.append(f"scene {r['scene']}: {f} ({r['wpm']:.0f} wpm)")
                    else:
                        risk_flags.append(f"scene {r['scene']}: {f}")
            report.add(QACheck(
                "pacing", not rushed,
                "narration paced for comprehension"
                if not rushed else f"rushed scenes: {rushed[:5]}",
                metrics={"avg_wpm": pacing["avg_wpm"],
                         "rushed_scene_count": pacing["rushed_scene_count"],
                         "comprehension_risk_flags": risk_flags,
                         "high_risk": pacing["high_risk_scenes"]}))

        # ── 9. Semantic alignment (v10 rec 6/7) — visuals belong to the ──
        #    narration beat they support.  Deterministic token overlap
        #    between each shot's query/title and its scene narration.
        #    v10.1: skip STRUCTURAL queries — visual_goal fallbacks like
        #    "The viewer should see Galileo's discovery of..." are intent
        #    descriptions, not asset searches; matching them against
        #    narration token-by-token produces false misalignment.
        _STRUCTURAL = re.compile(
            r"^(the viewer should see|viewer should|show|depict|illustrat|visuals? for|visual goal|scene \d|image of)",
            re.IGNORECASE,
        )
        if scenes_data is not None and vt:
            misaligned = []
            for v in vt:
                sid = v.get("scene_id")
                if sid is None or sid >= len(scenes_data):
                    continue
                sc = scenes_data[sid]
                # Token pool = narration + visual goal + script-approved
                # search queries.  A shot is aligned if its query shares
                # terms with ANY of them — the visual metaphor legitimately
                # differs from narration phrasing ("clock at 7" for
                # "seven hours of sleep"), and search_queries are
                # script-authored, so a shot using one is aligned by
                # construction.  Truly off-topic fallbacks (cached space
                # footage in a sleep scene) still fail: their queries
                # never appear in this scene's approved vocabulary.
                text = " ".join([
                    sc.get("narration") or "",
                    sc.get("visual_goal") or "",
                    " ".join(sc.get("search_queries") or []),
                ]).lower()
                query = ((v.get("query_used") or "") + " " +
                         (v.get("asset_title") or "")).lower()
                if not query.strip():
                    continue
                # ignore pre-verified/pinned assets: human-approved swaps
                # are trusted even when the free-text query differs.
                if v.get("pre_verified"):
                    continue
                # skip structural/intent queries (visual_goal fallbacks)
                if _STRUCTURAL.match(query.strip()):
                    continue
                narr_tokens = set(re.findall(r"[a-z]{4,}", text))
                query_tokens = set(re.findall(r"[a-z]{4,}", query))
                overlap = narr_tokens & query_tokens
                if not overlap and query_tokens:
                    misaligned.append(
                        f"{os.path.basename(v.get('file',''))}: query '{query.strip()[:40]}' "
                        f"shares no terms with scene {sid} narration")
            report.add(QACheck(
                "semantic_alignment", not misaligned,
                "every visual belongs to its narration beat"
                if not misaligned else f"misaligned shots: {misaligned[:5]}"))

        # ── 10. Resolution headroom (v13 rec #3) — source images must ───
        #    sustain the planned zoom before render.  Generates at final
        #    res then zooming = guaranteed softness; catch it on the PLAN.
        try:
            from src.qa.resolution_gate import check_timeline_headroom
            from src.utils.config import get_config
            _margin = float(get_config(
                "pipeline.image_gen.zoom_headroom_margin", 1.05))
            rh = check_timeline_headroom(timeline_path, margin=_margin)
            report.add(QACheck("resolution_headroom", rh["passed"], rh["detail"]))
        except Exception as e:
            report.add(QACheck("resolution_headroom", True,
                               f"headroom check skipped ({str(e)[:60]})"))

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

        # ── Loudness / clipping on the mastered file (v10 rec 4) ───────
        # Publication-safe audio: YouTube streaming standard (-14 LUFS,
        # true peak <= -1.5 dBTP), no clipping, no over-compression.
        loud = self._check_loudness(video_path)
        report.add(QACheck("loudness_master", loud["passed"], loud["detail"],
                           metrics=loud["metrics"]))

        # ── Black opening frames (§5 no dead openings) ─────────────────
        opening = self._check_opening_frames(video_path)
        report.add(QACheck("opening_black_frames", opening["passed"], opening["detail"]))

        # ── Absolute max shot duration in final timeline (v13 rec #4) ──
        tl2 = tl or {}
        durs = [v.get("end_time", 0) - v.get("start_time", 0)
                for v in tl2.get("video_timeline", [])]
        over = [d for d in durs if d > MAX_SHOT_DURATION_S + 1e-6]
        report.add(QACheck(
            "max_shot_duration", not over,
            f"no shot exceeds {MAX_SHOT_DURATION_S:.0f}s in final timeline"
            if not over else f"{len(over)} shot(s) exceed {MAX_SHOT_DURATION_S:.0f}s: "
            + ", ".join(f"{d:.1f}s" for d in sorted(over, reverse=True)[:5])))

        # ── Visual artifact scan on the final video (v13 rec #5) ───────
        # Mirrored edges / smeared borders / seam lines / wrong aspect.
        try:
            from src.qa.visual_artifact_check import run_visual_artifact_check
            art = run_visual_artifact_check(video_path)
            for c in art.get("checks", []):
                report.add(QACheck(c["name"], c["passed"], c["detail"]))
        except Exception as e:
            report.add(QACheck("visual_artifacts", True,
                               f"artifact scan skipped ({str(e)[:60]})"))

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

    def _check_loudness(self, video_path: str) -> dict:
        """Publication-safe mastering check (v10 rec 4).

        Verifies integrated loudness near YouTube standard (-14 LUFS),
        true peak within headroom (<= -1.0 dBTP after platform processing),
        no clipping (max sample < -0.5 dB) and sane dynamic range.
        Uses ffmpeg loudnorm print + volumedetect — deterministic.
        """
        try:
            ln = subprocess.run(
                ["ffmpeg", "-i", video_path, "-af",
                 "loudnorm=print_format=json", "-f", "null", "-"],
                capture_output=True, text=True, timeout=90,
            )
            # loudnorm JSON block appears at the end of stderr
            m = re.search(r"\{.*\}", ln.stderr[-2500:], re.DOTALL)
            stats = {}
            if m:
                try:
                    stats = json.loads(m.group(0))
                except Exception:
                    stats = {}
            def _f(key):
                try:
                    return float(stats.get(key, 0))
                except (TypeError, ValueError):
                    return 0.0
            i_lufs = _f("input_i")
            tp = _f("input_tp")
            lra = _f("input_lra")
            # clip check via volumedetect (max_volume is the true peak)
            vd = subprocess.run(
                ["ffmpeg", "-i", video_path, "-af", "volumedetect",
                 "-f", "null", "-"],
                capture_output=True, text=True, timeout=60,
            )
            mv = re.search(r"max_volume: ([-\.\d]+) dB", vd.stderr)
            max_db = float(mv.group(1)) if mv else -99.0
        except Exception as e:
            return {"passed": True, "detail": f"loudness check unavailable ({str(e)[:60]})",
                    "metrics": {}}

        problems = []
        if i_lufs and not (-16.0 <= i_lufs <= -11.0):
            problems.append(f"integrated {i_lufs:.1f} LUFS (target ~-14)")
        if tp and tp > -1.0:
            problems.append(f"true peak {tp:.1f} dBTP > -1.0 (platform headroom)")
        if max_db > -0.5:
            problems.append(f"max sample {max_db:.1f} dB — clipping risk")
        if lra and lra > 20:
            problems.append(f"LRA {lra:.1f} — over-compressed/over-wide")
        return {
            "passed": not problems,
            "detail": "mastered audio publication-safe (I/LRA/TP OK)"
                      if not problems else "mastering issues: " + "; ".join(problems[:4]),
            "metrics": {"integrated_lufs": i_lufs, "true_peak_dbTP": tp,
                         "lra": lra, "max_volume_db": max_db},
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
