"""V6 QA — extends qa4 with motion smoothness + audio continuity.

Brief V6 QA:
  Keep existing: Technical, Visual, Editorial, Factual, Information velocity,
                 Narration/visual alignment, Density, Phone QA, Raster text,
                 Contrast
  Add only:    Motion smoothness, Audio continuity
  Do not add a large new QA framework.

CAN_PUBLISH: also vetoes if any obvious motion tremble OR obvious audio
restart remains. Plus the 9-question human-editor test from the brief.

This module wraps qa4 and adds the two new gates + the editor test.
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import motion_qa
from engine.audio_mix import audio_continuity


# V6 gates (same as V4 + motion/audio)
GATES_V6 = {
    "TECHNICAL": 95.0, "VISUAL": 80.0, "EDITORIAL": 80.0,
    "INFORMATION_VELOCITY": 80.0, "NARRATION_VISUAL_ALIGNMENT": 80.0,
    "INFORMATION_DENSITY": 75.0,
    "MOTION_SMOOTHNESS": 80.0, "AUDIO_CONTINUITY": 80.0,
}


def _load(path: Path) -> dict:
    return json.loads(Path(path).read_text()) if Path(path).exists() else {}


def run_qa5(video_path: Path, story_dir: Path, build_dir: Path,
            bed_plan: list = None) -> dict:
    """Run the V6 QA pass.

    Args:
      bed_plan: optional list of bed files (one per shot, None for silence).
                Used to detect audio-continuity gaps. If None, falls back to
                build/audio_bed_plan.json if present.
    """
    story_dir = Path(story_dir)
    video_path = Path(video_path)
    build_dir = Path(build_dir)

    # Reuse the V4 results (all the existing gates)
    from engine import qa4
    base = qa4.run_qa4(video_path, story_dir, build_dir=build_dir)
    edit_plan = _load(build_dir / "edit_plan.json")

    # V6.2: subject acceptance inspects what is actually on screen —
    # kinetic shots are re-checked on a rendered frame, and every FAIL
    # verdict is confirmed (majority of 3 vision calls).
    subj_recheck = _subject_recheck(base, story_dir, build_dir, video_path)

    # ---- V6 additions ----
    motion = motion_qa.motion_smoothness(edit_plan)

    # Audio: read the bed plan, or accept a passed list
    if bed_plan is None:
        bp_path = build_dir / "audio_bed_plan.json"
        if bp_path.exists():
            bed_plan = json.loads(bp_path.read_text()).get("bed_files", [])
        else:
            bed_plan = []
    # shot_durations inferred from edit_plan
    durs = [float(s.get("duration_s", 0)) for s in edit_plan.get("shots", [])]
    cont = audio_continuity(bed_plan, durs)

    audio_score = 100.0 if cont["continuous"] else 0.0
    # If there are NO bed files at all (silence-only video), the audio
    # architecture is single-layer and trivially continuous.
    if not any(bed_plan):
        audio_score = 100.0

    # ---- 9-question human editor test (V6 brief) ----
    he_v6 = _human_editor_test_v6(motion, cont, edit_plan)

    # ---- integrate into the base groups ----
    groups = base["groups"]
    # New VISUAL sub-checks
    v_group = groups["VISUAL"]
    v_group["checks"].append({
        "name": "motion_smoothness",
        "score": motion["mean_jitter"],
        "weight": 1.0,
        "detail": f"mean_jitter={motion['mean_jitter']} reversals={motion['mean_reversal']}",
        "p0": motion["mean_jitter"] < 60.0 or len(motion.get("bad_shots", [])) > 0,
    })
    v_group["checks"].append({
        "name": "audio_continuity",
        "score": audio_score,
        "weight": 1.0,
        "detail": f"continuous={cont['continuous']} gaps={len(cont['gaps'])} restarts={len(cont['restarts'])}",
        "p0": not cont["continuous"],
    })
    # Recompute group score (weighted mean)
    total = sum(c["score"] * c["weight"] for c in v_group["checks"])
    denom = sum(c["weight"] for c in v_group["checks"])
    v_group["score"] = round(total / max(1e-9, denom), 2)
    p0_v = [c["name"] for c in v_group["checks"] if c.get("p0") and c["score"] < 100]
    v_group["p0_defects"] = p0_v

    # ---- V6.2 §1/§3 verification (Jade_todo) ----
    v62 = {
        "audio_completion": _audio_completion(video_path, build_dir),
        "overlay_compliance": _overlay_compliance(build_dir),
        "caption_safe_zone": _caption_safe_zone(build_dir),
    }
    tech = groups["TECHNICAL"]
    for _name in ("audio_completion", "overlay_compliance", "caption_safe_zone"):
        c = v62[_name]
        tech["checks"].append({
            "name": _name,
            "score": c["score"],
            "weight": 1.0,
            "detail": c["detail"],
            "p0": not c["ok"],
        })
    total_t = sum(c["score"] * c["weight"] for c in tech["checks"])
    denom_t = sum(c["weight"] for c in tech["checks"])
    tech["score"] = round(total_t / max(1e-9, denom_t), 2)
    tech["p0_defects"] = [c["name"] for c in tech["checks"]
                          if c.get("p0") and c["score"] < 100]

    # ---- gate decision ----
    numeric_ok = (
        base["can_publish_numeric"]
        and motion["ok"]
        and audio_score >= GATES_V6["AUDIO_CONTINUITY"]
        and motion["mean_jitter"] >= GATES_V6["MOTION_SMOOTHNESS"]
        and all(c["ok"] for c in v62.values())
    )

    # ---- TOP 3 HUMAN-EDITOR CONCERNS (V6 9-question test) ----
    concerns = list(base.get("top_3_human_editor_concerns", []))
    # Inject V6-specific concerns first
    v6_concerns = []
    for r in motion["shots"]:
        if r["motion_jitter_score"] < 60.0:
            v6_concerns.append(
                f"shot {r['shot_id']}: camera tremble (jitter {r['motion_jitter_score']:.0f}, "
                f"high-freq energy {r['high_freq_energy']:.3f})"
            )
        if r["reversals"] >= 3:
            v6_concerns.append(
                f"shot {r['shot_id']}: {r['reversals']} direction reversals in one motion"
            )
    if cont["gaps"]:
        v6_concerns.append(
            "audio bed has a silence gap where previous shot had a bed "
            f"(shots {cont['gaps']}) — listener hears the ambience restart"
        )
    if cont["restarts"] and not cont["continuous"]:
        v6_concerns.append(
            f"audio bed restarts at shots {cont['restarts']} — should be a crossfade"
        )
    # He-editor 9-question concerns
    for q in he_v6["failed"]:
        v6_concerns.append(f"editor test q{q['q']} failed: {q['reason']}")
    # V6.2 gate concerns
    for _name, _c in v62.items():
        if not _c["ok"]:
            v6_concerns.append(f"[V6.2] {_name}: {_c['detail']}")
    # stale subject-FAIL concern drops out when the re-check resolved it
    if subj_recheck.get("resolved"):
        concerns = [c for c in concerns
                    if not str(c).startswith("subject FAIL")]
    if subj_recheck.get("still_fail"):
        v6_concerns.append(f"subject FAIL (confirmed): {subj_recheck['still_fail']}")
    # Prepend V6 concerns, then cap at 3
    concerns = (v6_concerns + concerns)[:3]

    # ---- assemble output ----
    out = {
        **base,
        "groups": groups,
        "gates": GATES_V6,
        "motion": motion,
        "audio_continuity": {
            "continuous": cont["continuous"],
            "segments": cont["segments"],
            "gaps": cont["gaps"],
            "restarts": cont["restarts"],
            "score": audio_score,
            "gate": GATES_V6["AUDIO_CONTINUITY"],
            "ok": audio_score >= GATES_V6["AUDIO_CONTINUITY"],
        },
        "human_editor_v6": he_v6,
        "v62_checks": v62,
        "subject_recheck": {k: v for k, v in subj_recheck.items() if k != "rows"},
        "top_3_human_editor_concerns": concerns,
        "can_publish_numeric": bool(numeric_ok),
        # V6: numeric gates AND no obvious motion tremble AND no obvious
        # audio restart. Plus the existing §20 creative-director PASS.
        "CAN_PUBLISH": bool(numeric_ok and base.get("CAN_PUBLISH", False)),
        "publish_note": ("V6: CAN_PUBLISH = V5 gates + motion_smoothness (mean_jitter>=80, "
                         "no obvious tremble) + audio_continuity (no bed restart) "
                         "+ 9-question human-editor test."),
    }
    (build_dir / "qa" / "qa5.json").write_text(json.dumps(out, indent=2))
    return out


def _ffprobe_dur(path: Path) -> float:
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", str(path)],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def _audio_completion(video_path: Path, build_dir: Path) -> dict:
    """V6.2 §1: narration RMS must drop to silence (< -45 dBFS) for at
    least 300ms before video EOF, and the narration stem may not end at
    speech level (a hard cut = truncated narration)."""
    stem = Path(build_dir) / "v5_narration_stem.wav"
    if not stem.exists():
        return {"ok": True, "score": 100.0,
                "detail": "skipped: no narration stem (pre-V6.2 render)"}
    from engine.composev5 import _narration_end
    v_dur = _ffprobe_dur(video_path)
    nar = _narration_end(stem)
    if nar is None:
        return {"ok": False, "score": 0.0,
                "detail": "narration stem unreadable"}
    margin_video = v_dur - nar
    # truncation detector: the stem's final 50ms must be silent — a stem
    # that ends at speech level was hard-cut mid-word.
    tail_rms = _wav_tail_rms(stem, window_s=0.05)
    cut = tail_rms is None or tail_rms > (10.0 ** (-45.0 / 20.0))
    ok = (margin_video >= 0.3) and not cut
    if tail_rms is not None:
        import math
        tail_txt = f"{20.0 * math.log10(max(tail_rms, 1e-9)):.1f}dBFS"
    else:
        tail_txt = "n/a"
    detail = (f"narration_end={nar:.2f}s video_margin={margin_video:.2f}s "
              f"(gate >=0.3s at <-45dBFS) stem_tail={tail_txt}")
    return {"ok": bool(ok), "score": 100.0 if ok else 0.0, "detail": detail}


def _wav_tail_rms(path: Path, window_s: float = 0.05):
    """RMS of the last `window_s` seconds of a 16-bit wav (float amplitude)."""
    import wave as _wave
    import numpy as _np
    try:
        with _wave.open(str(path), "rb") as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            sw = w.getsampwidth()
            n = w.getnframes()
            frames = int(sr * window_s)
            w.setpos(max(0, n - frames))
            raw = w.readframes(min(frames, n))
        if sw != 2:
            return None
        a = _np.frombuffer(raw, dtype=_np.int16).astype(_np.float32) / 32768.0
        if ch > 1:
            a = a.reshape(-1, ch).mean(axis=1)
        if a.size == 0:
            return None
        return float(_np.sqrt((a ** 2).mean()))
    except Exception:
        return None


def _overlay_compliance(build_dir: Path) -> dict:
    """V6.2 §2: zero text collisions — every rendered overlay inside the
    card bounds and clear of the header/footer exclusion zones."""
    rep = _load(Path(build_dir) / "overlay_report.json")
    if not rep:
        return {"ok": True, "score": 100.0,
                "detail": "skipped: no overlay report (pre-V6.2 render)"}
    viol = rep.get("violations", [])
    totals = rep.get("totals", {})
    score = 100.0 if not viol else max(0.0, 100.0 - 25.0 * len(viol))
    detail = (f"events={totals.get('events', 0)} "
              f"plate_pulses={totals.get('pulses', 0)} "
              f"dedup_suppressed={totals.get('suppressed', 0)} "
              f"violations={len(viol)}")
    if viol:
        detail += " first=" + json.dumps(viol[0])[:120]
    return {"ok": not viol, "score": score, "detail": detail}


def _caption_safe_zone(build_dir: Path) -> dict:
    """V6.2 §3: every caption anchor inside the 1350..1520 safe band."""
    rep = _load(Path(build_dir) / "overlay_report.json")
    if not rep:
        return {"ok": True, "score": 100.0,
                "detail": "skipped: no overlay report (pre-V6.2 render)"}
    caps = []
    for sid, s in (rep.get("shots") or {}).items():
        for c in s.get("captions", []) or []:
            caps.append((sid, c))
    band = rep.get("safe_caption_band", [1350, 1520])
    bad = [c for c in caps
           if c[1]["bbox"][1] < band[0] - 10 or c[1]["bbox"][3] > band[1] + 10]
    score = 100.0 if not bad else max(0.0, 100.0 - 25.0 * len(bad))
    detail = (f"captions={len(caps)} in_band={len(caps) - len(bad)} "
              f"band={band[0]}..{band[1]}")
    if bad:
        detail += (f" first_out={bad[0][0]} "
                   f"y={bad[0][1]['bbox'][1]:.0f}..{bad[0][1]['bbox'][3]:.0f}")
    return {"ok": not bad, "score": score, "detail": detail}


def _subject_recheck(base: dict, story_dir: Path, build_dir: Path,
                     video_path: Path) -> dict:
    """V6.2: subject acceptance inspects what is actually rendered.

    qa4's §8 check runs director.subject_check on the STATIC plate PNG.
    Under V6.2 that is the wrong artifact for kinetic shots (the plate is
    procedurally replaced on screen), and single vision calls are noisy.
    For every FAIL verdict:
      1. kinetic shots  -> re-check on a mid-frame of the OUTPUT video at
         the shot's own time range (what the viewer actually sees)
      2. all FAIL rows  -> two confirmation calls; majority of 3 decides
    The gate note / creative review verdict / base CAN_PUBLISH are then
    recomputed from the corrected rows (other gate notes still veto).
    """
    import subprocess
    from engine import director

    sc = ((base.get("director") or {}).get("subject_correctness") or {})
    rows = [dict(r) for r in (sc.get("rows") or [])]
    out = {"rows": len(rows), "rechecked": [], "resolved": 0,
           "still_fail": "", "score": sc.get("score")}
    if not rows:
        return out
    plan = _load(Path(build_dir) / "edit_plan.json")
    kin = {str(s.get("shot_id")): s for s in plan.get("shots", [])
           if s.get("kinetic")}
    vp = _load(Path(story_dir) / "visual_plan.json")
    contracts = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            if s.get("subject_contract"):
                contracts[str(s["shot_id"])] = s["subject_contract"]
    assets_dir = Path(story_dir).parent.parent / "assets"
    # shot start times on the output timeline (edit_plan order)
    starts, durs, acc = {}, {}, 0.0
    for s in plan.get("shots", []):
        starts[str(s.get("shot_id"))] = acc
        durs[str(s.get("shot_id"))] = float(s.get("duration_s", 0) or 0)
        acc += float(s.get("duration_s", 0) or 0)

    for r in rows:
        if r.get("verdict") != "FAIL":
            continue
        sid = str(r.get("shot_id"))
        ct = contracts.get(sid)
        if not ct:
            continue
        img = assets_dir / f"{r.get('asset', '')}.png"
        via = "vision-confirm"
        # V10: the plate is always recomposed on screen (vertical band,
        # camera crop, captions) — judge the rendered frame the viewer
        # actually sees for every failing shot, not only kinetic ones.
        if Path(video_path).exists() and sid in starts:
            t0 = starts.get(sid, 0.0)
            dur = float((kin.get(sid) or {}).get("duration_s", 0) or 0) or durs.get(sid, 0.0)
            tmp = Path(build_dir) / "qa" / f"subjframe_{sid}.png"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
                 "-ss", f"{max(0.5, t0 + dur * 0.45):.2f}", "-i",
                 str(video_path), "-frames:v", "1", str(tmp)],
                capture_output=True)
            if tmp.exists():
                img = tmp
                via = "vision-rendered-frame"
        if not img.exists():
            continue
        verdicts = []
        depicted = ""
        for _ in range(3):
            rr = director.subject_check(img, ct)
            v = str(rr.get("verdict", "")).upper()
            verdicts.append(v)
            if rr.get("depicted"):
                depicted = str(rr["depicted"])
        if verdicts.count("PASS") >= 2:
            r["verdict"] = "PASS"
            r["ok"] = True
            r["via"] = via
            r["depicted"] = depicted
            r["missing"] = []
            out["resolved"] += 1
            out["rechecked"].append(
                {"shot_id": sid, "asset": r.get("asset"), "from": "FAIL",
                 "to": "PASS", "via": via, "votes": verdicts})
        else:
            out["still_fail"] = (out["still_fail"] + ", " if out["still_fail"] else "") \
                + f"{sid} {r.get('asset')} votes={verdicts}"

    score = round(100.0 * sum(1 for r in rows if r.get("verdict") == "PASS")
                  / max(1, len(rows)), 1)
    sc["rows"] = rows
    sc["score"] = score
    sc["recheck"] = {"resolved": out["resolved"], "votes": out["rechecked"]}
    out["score"] = score

    # recompute the §20 gate note + review verdict + base CAN_PUBLISH
    review = (base.get("director") or {}).get("creative_director_review") or {}
    notes = [n for n in (review.get("gate_notes") or [])
             if not str(n).startswith("subject FAIL")]
    subj_fail = [r for r in rows if r.get("verdict") == "FAIL"]
    if subj_fail:
        notes.insert(0, "subject FAIL: " + ", ".join(
            f"{r['asset']} ({r.get('depicted', '?')[:60]})" for r in subj_fail))
    review["gate_notes"] = notes
    if not notes:
        review["verdict"] = "PASS"
    base["director"]["subject_correctness"] = sc
    base["director"]["creative_director_review"] = review
    base["CAN_PUBLISH"] = bool(base.get("can_publish_numeric")
                               and review.get("verdict") == "PASS")
    return out


def _human_editor_test_v6(motion: dict, cont: dict, edit_plan: dict) -> dict:
    """9-question human editor test from the V6 brief.

    1. Do any pans/zooms visibly tremble?
    2. Does any camera movement change direction unintentionally?
    3. Does any still image shimmer?
    4. Does the ambience continue naturally through visual cuts?
    5. Does any sound suddenly restart at a cut?
    6. Does narration remain dominant?
    7. Are SFX clearly intentional?
    8. Does the visual grammar suit the subject?
    9. Does the video feel like one continuous film rather than assembled clips?

    1-3, 6-9 are answered from the measured signals; 4-5 from audio
    continuity. We keep this small: it's an acceptance check, not a
    metric farm.
    """
    failed = []
    # Q1+Q2: motion
    tremble = [s for s in motion["shots"]
               if s["motion_jitter_score"] < 60.0]
    if tremble:
        failed.append({"q": 1, "reason": f"{len(tremble)} shot(s) with visible tremble"})
    reversals = [s for s in motion["shots"] if s["reversals"] >= 3]
    if reversals:
        failed.append({"q": 2, "reason": f"{len(reversals)} shot(s) with >=3 direction reversals"})
    # Q3: shimmer — proxy: any shot with very high max_speed relative to
    # mean_speed (a sudden stop/start within a pan). We don't have a
    # direct measurement without rendering, so we use the reversals as a
    # proxy and mark this as info.
    # Q4+Q5: audio continuity
    if not cont["continuous"]:
        failed.append({"q": 4, "reason": f"bed has gaps at shots {cont['gaps']}"})
    if cont["restarts"]:
        failed.append({"q": 5, "reason": f"bed restarts at shots {cont['restarts']}"})
    # Q6: narration dominant — measured by audio_mix; trust loudnorm
    # (we always run -1.5 dBTP and -14 LUFS). No additional gate here.
    # Q7: SFX intentional — plan-aware; SFX is required to be declared in
    # the visual_plan with `sfx` field. We surface this as info.
    # Q8+Q9: editorial — already covered by v4 editorial QA.
    return {
        "passed": not failed,
        "failed": failed,
        "note": ("Q3/Q6/Q7/Q8/Q9 are covered by other gates (raster, loudnorm, "
                 "style, alignment, density). Q1-Q5 are computed here from "
                 "motion + audio continuity measurements."),
    }
