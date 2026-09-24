"""V13B M5b — human-editor gate (P1 "HUMAN-EDITOR TEST").

Directive: docs/directives/JADE_V13B_STORY_SPECIFIC_VISUAL_GRAMMAR.md P1
"Before CAN_PUBLISH, evaluate the six questions ... If #1, #2, #3, #4 or #6
fails → CAN_PUBLISH=false. Do not turn this into a huge scoring framework."

Per VIDEO, six questions over the existing vision judge chain
(engine.director.vision_ask — Gemini primary, GLM fallback; callers must
treat None as unjudged, never a pass):

  Q1 hook        frames at t=0.5 / 2 / 4 s  (one call each, majority vote)
  Q2 explain     3 mid-shot frames          (one call each, +Q3)
  Q3 subject     same 3 mid-shot frames     (same calls)
  Q4 transform   composite of the 3 mid     (one call)
                 frames, early -> late
  Q5 swap-nouns  DETERMINISTIC (no vision): >60% of shots sharing one
                 (composition, layout class) == template-driven
  Q6 resolve     first frame + last frame   (one call, composite)

Budget: 8 real vision calls per evaluation (3 + 3 + 1 + 1), far under the
<=24 verification budget. Any shot whose plate sidecar carries
asset_tier=="failed" (M3 unpublishable placeholder) forces the verdict to
fail regardless of the answers.

Gate semantics follow the engine's honesty rule (unverified never passes):
gate_pass = no required question (q1..q4, q6) failed OR went unjudged, and
no failed-tier plate. Q5 is recorded as evidence for the visual-grammar
revision loop (directive: "If #5 repeatedly fails across many shots/videos,
the generator is still too template-driven") but does not gate a single
video.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

SCHEMA = "v13b.human_editor/1.0"
REQUIRED = ("q1", "q2", "q3", "q4", "q6")
Q5_SHARE = 0.60          # >60% identical (composition, layout) = template
COMPOSITE_W = 480        # per-frame width inside composites (px)
HOOK_TIMES = (0.5, 2.0, 4.0)
MID_FRACTIONS = (0.35, 0.5, 0.65)   # mid-shot frame positions (video time)


# ---------------------------------------------------------------------------
# frame plumbing (reuses the M5a extractor; no new machinery)


def _frame(video: Path, t: float):
    from engine.template_signature import _frame_at_rgb
    return _frame_at_rgb(video, max(0.0, t))


def _save_frames(video: Path, times, tmpdir: Path) -> list:
    """[(label, path)] for each extractable frame; missing frames skipped
    (recorded as unjudged downstream)."""
    tmpdir.mkdir(parents=True, exist_ok=True)
    out = []
    for i, t in enumerate(times):
        im = _frame(video, t)
        if im is None:
            continue
        p = tmpdir / f"he_{i:02d}_{str(t).replace('.', '_')}.png"
        im.save(p)
        out.append((t, str(p)))
    return out


def _composite(paths: list, out_path: Path) -> str | None:
    """Vertical stack (equal width) so one vision call can compare frames."""
    ims = [Image.open(p).convert("RGB") for p in paths]
    if not ims:
        return None
    ims = [im.resize((COMPOSITE_W, max(1, int(im.height * COMPOSITE_W
                                               / im.width))),
                     Image.BILINEAR) for im in ims]
    canvas = Image.new("RGB", (COMPOSITE_W, sum(im.height for im in ims)
                               + 8 * (len(ims) - 1)), (16, 16, 16))
    y = 0
    for im in ims:
        canvas.paste(im, (0, y))
        y += im.height + 8
    canvas.save(out_path)
    return str(out_path)


def _ask(image_path, question: str) -> dict | None:
    from engine.director import vision_ask
    return vision_ask(image_path, question, max_tokens=300)


def _vote(question: dict, yes: int, judged: int) -> None:
    """Majority vote with a quorum of 2 judged frames; an unreachably low
    quorum is recorded as unjudged -> the required question fails."""
    if judged == 0:
        question.update({"pass": False, "status": "unjudged",
                         "evidence": "vision judge unreachable for all "
                                     "sampled frames"})
    elif judged < 2:
        question.update({"pass": False, "status": "unjudged",
                         "evidence": f"quorum not met ({judged}/3 frames "
                                     f"judged; yes={yes})"})
    else:
        ok = yes * 2 > judged
        question.update({"pass": bool(ok),
                         "status": "pass" if ok else "fail",
                         "evidence": f"{yes}/{judged} judged frames yes"})


# ---------------------------------------------------------------------------
# Q5 — deterministic swap-nouns test


def _q5_swap_test(plan: dict) -> dict:
    """>60% of shots sharing one identical (composition, layout class) pair
    means the same canvas is reused with only the nouns swapped ->
    template-driven (deterministic; no vision)."""
    groups: dict = {}
    for s in (plan.get("shots") or []):
        vg = s.get("visual_grammar") or {}
        canvas = s.get("canvas") or {}
        key = (str(vg.get("composition") or ""),
               str(canvas.get("panel_usage") or canvas.get("caption_zone")
                   or ""))
        groups[key] = groups.get(key, 0) + 1
    n = sum(groups.values())
    if not n:
        return {"pass": True, "status": "unjudged",
                "evidence": "no shots", "modal_share": 0.0, "groups": {}}
    modal, count = max(groups.items(), key=lambda kv: (kv[1], kv[0]))
    share = count / n
    ok = share <= Q5_SHARE
    if ok:
        ev = (f"{count}/{n} shots share one (composition, layout) pair "
              f"{modal} -> varied grammar")
    else:
        ev = (f"{count}/{n} shots share one (composition, layout) pair "
              f"{modal} -> same composition with only the nouns swapped: "
              f"template-driven")
    return {"pass": bool(ok), "status": "pass" if ok else "fail",
            "evidence": ev,
            "modal_share": round(share, 3), "groups": {str(k): v for k, v
                                                       in groups.items()}}


# ---------------------------------------------------------------------------
# main evaluation


def evaluate(plan: dict, story: dict, story_id: str, video,
             build: Path = Path("build"), max_calls: int = 24,
             ts_result: dict | None = None, save: bool = True) -> dict:
    """Full six-question human-editor evaluation for one rendered video.
    Returns the verdict dict; qa8full ANDs `gate_pass` into the publish
    gate as the HUMAN_EDITOR component."""
    out = {"schema": SCHEMA, "story": story_id,
           "video": str(video) if video else None,
           "questions": {}, "vision_calls": 0, "budget": max_calls}
    vid = Path(video) if video else None
    if vid is None or not vid.exists():
        out.update({"available": False, "gate_pass": False,
                    "status": "unavailable",
                    "note": "no rendered video — human-editor test cannot "
                            "run; gate stays open-fail (honest unverified)"})
        return out
    out["available"] = True
    total = _duration(vid)
    tmpdir = build / "qa" / f"human_editor_{story_id}"
    calls = 0
    budget_ok = lambda: calls < max_calls  # noqa: E731

    # -- Q1 hook: t=0.5 / 2 / 4 s -------------------------------------------
    q1 = {"pass": False, "status": "unjudged", "evidence": ""}
    frames = _save_frames(vid, [t for t in HOOK_TIMES if t < total], tmpdir)
    yes = judged = 0
    for t, fp in frames:
        if not budget_ok():
            break
        ans = _ask(fp, "You are a ruthless human video editor. Frame from "
                       "the very start of a short documentary video. "
                       "Question 1: is something visually interesting "
                       "happening immediately in this frame (a real scene/"
                       "subject/action), or is it a bare title card, empty "
                       "container, or generic presentation board?\n"
                       'Answer strict JSON: {"interesting": true|false, '
                       '"reason": "<one sentence>"}')
        calls += 1
        if isinstance(ans, dict) and isinstance(ans.get("interesting"), bool):
            judged += 1
            yes += int(ans["interesting"])
            q1["evidence"] = (q1["evidence"] + " | " if q1["evidence"]
                              else "") + f"t={t}s: {ans.get('reason', '')[:80]}"
    _vote(q1, yes, judged)
    out["questions"]["q1"] = q1

    # -- Q2/Q3: 3 mid-shot frames -------------------------------------------
    mid = _mid_frames(plan, vid, total, tmpdir)
    q2 = {"pass": False, "status": "unjudged", "evidence": ""}
    q3 = {"pass": False, "status": "unjudged", "evidence": ""}
    y2 = j2 = y3 = j3 = 0
    mid_paths = []
    for t, fp in mid:
        mid_paths.append(fp)
        if not budget_ok():
            continue
        ans = _ask(fp, "You are a ruthless human video editor reviewing a "
                       "frame from the middle of a documentary short "
                       "(narration describes the on-screen subject). Two "
                       "questions: (a) Does the visual EXPLAIN the "
                       "narration rather than merely accompany it? (b) Does "
                       "the scene feel specific to this subject — could it "
                       "not be reused for a different topic by swapping "
                       "only the nouns?\n"
                       'Answer strict JSON: {"explains": true|false, '
                       '"subject_specific": true|false, "reason": '
                       '"<one sentence>"}')
        calls += 1
        if isinstance(ans, dict):
            if isinstance(ans.get("explains"), bool):
                j2 += 1
                y2 += int(ans["explains"])
                q2["evidence"] = (q2["evidence"] + " | " if q2["evidence"]
                                  else "") + f"t={t}s: {ans.get('reason', '')[:80]}"
            if isinstance(ans.get("subject_specific"), bool):
                j3 += 1
                y3 += int(ans["subject_specific"])
    _vote(q2, y2, j2)
    _vote(q3, y3, j3)
    out["questions"]["q2"], out["questions"]["q3"] = q2, q3

    # -- Q4 transform: one composite call over the mid frames ----------------
    q4 = {"pass": False, "status": "unjudged", "evidence": ""}
    comp_path = _composite(mid_paths, tmpdir / "he_q4_composite.png")
    if comp_path and budget_ok():
        ans = _ask(comp_path, "You are a ruthless human video editor. These "
                              "three frames are from the middle of one "
                              "documentary short, in chronological order "
                              "(top = earliest). Question: does the visual "
                              "MATERIALLY transform as the explanation "
                              "progresses — new state, new information, a "
                              "changed scene — or do all three look like "
                              "the same static slide?\n"
                              'Answer strict JSON: {"transforms": '
                              'true|false, "reason": "<one sentence>"}')
        calls += 1
        if isinstance(ans, dict) and isinstance(ans.get("transforms"), bool):
            q4.update({"pass": bool(ans["transforms"]),
                       "status": "pass" if ans["transforms"] else "fail",
                       "evidence": str(ans.get("reason", ""))[:160]})
    else:
        q4["evidence"] = "composite frame unavailable or call budget spent"
    out["questions"]["q4"] = q4

    # -- Q6 resolve: first + last frame --------------------------------------
    q6 = {"pass": False, "status": "unjudged", "evidence": ""}
    ends = _save_frames(vid, [0.2, max(0.3, total - 0.3)], tmpdir)
    end_paths = [p for _, p in ends]
    comp_path = _composite(end_paths, tmpdir / "he_q6_composite.png")
    if comp_path and budget_ok():
        ans = _ask(comp_path, "You are a ruthless human video editor. Frame "
                              "1 (top) is the OPENING and frame 2 (bottom) "
                              "is the ENDING of one documentary short. "
                              "Question: does the ending visually RESOLVE "
                              "the opening's curiosity (payoff, closure, "
                              "the question the opening raised is answered "
                              "on screen)?\n"
                              'Answer strict JSON: {"resolves": true|false, '
                              '"reason": "<one sentence>"}')
        calls += 1
        if isinstance(ans, dict) and isinstance(ans.get("resolves"), bool):
            q6.update({"pass": bool(ans["resolves"]),
                       "status": "pass" if ans["resolves"] else "fail",
                       "evidence": str(ans.get("reason", ""))[:160]})
    else:
        q6["evidence"] = "composite frame unavailable or call budget spent"
    out["questions"]["q6"] = q6

    # -- Q5 (deterministic, no vision) ----------------------------------------
    out["questions"]["q5"] = _q5_swap_test(plan)

    # -- M3 failed-tier force-fail --------------------------------------------
    failed = [str(s.get("shot_id")) for s in (plan.get("shots") or [])
              if (s.get("plate_sidecar") or {}).get("asset_tier") == "failed"]
    out["tier_check"] = {"pass": not failed, "failed_shots": failed,
                         "evidence": ("unpublishable placeholder tier "
                                      "(asset_tier=failed) on: "
                                      + ", ".join(failed)) if failed
                         else "no failed-tier plates"}
    # template-signature flag rate carried for one-stop gate evidence
    if isinstance(ts_result, dict):
        out["template_flag_rate"] = (ts_result.get("summary") or {}).get(
            "flag_rate")

    out["vision_calls"] = calls
    failed_q = [q for q in REQUIRED
                if not out["questions"][q]["pass"]]
    out["failed_questions"] = failed_q
    out["gate_pass"] = not failed_q and out["tier_check"]["pass"]
    out["note"] = ("gate = six-question test (q1..q4,q6 must pass; unjudged "
                   "fails) AND no failed-tier plates; q5 recorded for the "
                   "grammar-revision loop, non-gating per video")
    if save:
        qdir = build / "qa"
        qdir.mkdir(parents=True, exist_ok=True)
        (qdir / f"human_editor_{story_id}.json").write_text(
            json.dumps(out, indent=1))
    return out


# ---------------------------------------------------------------------------
# helpers


def _duration(video: Path) -> float:
    import subprocess
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True)
    try:
        return float(p.stdout.strip())
    except ValueError:
        return 0.0


def _mid_frames(plan: dict, video: Path, total: float,
                tmpdir: Path) -> list:
    """3 mid-shot frames: midpoints of the shots containing the 35% / 50% /
    65% timeline marks (deterministic; falls back to plain timeline
    fractions when the plan carries no usable shot durations)."""
    shots = plan.get("shots") or []
    targets, t, spans = [], 0.0, []
    for s in shots:
        d = float(s.get("duration_s") or 0)
        if d > 0:
            spans.append((t, d))
        t += d
    if total <= 0:
        total = t
    for frac in MID_FRACTIONS:
        mark = frac * total
        span = next(((st, d) for st, d in spans if st <= mark < st + d),
                    None)
        targets.append(span[0] + span[1] / 2.0 if span else mark)
    return _save_frames(video, targets, tmpdir)
