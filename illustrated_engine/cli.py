#!/usr/bin/env python3
"""CLI for the illustrated-documentary engine (see README.md).

Commands:
  validate [--make-edit-plan]   validate story JSONs (+ build edit_plan)
  render-shot <shot_id>         render one shot from build/edit_plan.json
  render-video                  render missing/outdated shots + concat final
  qa [path]                     ffprobe/black/freeze/loudness QA + qa.json
  contact-sheet <path>          3x4 contact sheet jpg
  smoke                         deterministic 2s test render, twice, sha256
  tts                           wired at TTS stage (stub)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine import Paths, compose, motion, plan  # noqa: E402
from engine import qa as qa_mod  # noqa: E402
from engine.text_ass import build_ass, load_style, normalize_cues  # noqa: E402

STORY = "space_closer"


def _paths():
    return Paths(ROOT).ensure_dirs()


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------

def cmd_validate(args):
    paths = _paths()
    rep = plan.validate(paths, STORY)
    code = plan.print_report(rep)
    if args.make_edit_plan or not (paths.build / "edit_plan.json").exists():
        eplan, erep = plan.make_edit_plan(paths, STORY)
        for m in erep["warnings"]:
            print(f"- [WARN] edit_plan: {m}")
        for m in erep["errors"]:
            print(f"- [FAIL] edit_plan: {m}")
        total = sum(s["duration_s"] for s in eplan["shots"])
        print(f"edit_plan -> {paths.build / 'edit_plan.json'}: "
              f"{len(eplan['shots'])} shots, {total:.1f}s estimated")
        for s in eplan["shots"]:
            print(f"  {s['shot_id']}: {s['duration_s']:5.1f}s "
                  f"{s['camera']['primitive']:<13} caps={len(s['captions'])} "
                  f"ovl={len(s['overlays'])} typ={len(s['typography'])} "
                  f"in={s['transition_in']}")
        if erep["errors"]:
            code = 1
    sys.exit(code)


def cmd_render_shot(args):
    paths = _paths()
    eplan = json.loads((paths.build / "edit_plan.json").read_text())
    shot = next((s for s in eplan["shots"] if s["shot_id"] == args.shot_id), None)
    if shot is None:
        known = [s["shot_id"] for s in eplan["shots"]]
        print(f"shot {args.shot_id!r} not in edit_plan; have: {known}")
        sys.exit(2)
    out = compose.render_shot(shot, paths)
    print(f"rendered {out}")


def cmd_render_video(args):
    paths = _paths()
    out = compose.render_video(paths)
    print(f"final -> {out}")


def cmd_qa(args):
    paths = _paths()
    target = Path(args.path) if args.path else paths.output / "final.mp4"
    rep = qa_mod.qa_video(target, paths, STORY)
    qa_mod.print_qa(rep)
    print(f"qa.json -> {paths.qa / 'qa.json'}")


def cmd_contact_sheet(args):
    paths = _paths()
    out = qa_mod.contact_sheet(Path(args.path), paths)
    print(f"contact sheet -> {out}")


def cmd_tts(args):
    print("wired at TTS stage")


def cmd_diagrams2(args):
    from engine import bible as B, composev2
    paths = _paths()
    bible = B.load_bible(Path(paths.stories) / args.story)
    scores = composev2.prep_diagrams(paths, bible, args.story)
    print(json.dumps(scores, indent=1))


def cmd_plan2(args):
    from engine import planv2
    paths = _paths()
    plan, rep = planv2.make_edit_plan_v2(paths, args.story)
    for w in rep["warnings"]:
        print("warn:", w)
    total = sum(s["duration_s"] for s in plan["shots"])
    print(f"edit_plan v2 -> build/edit_plan.json ({len(plan['shots'])} shots, {total:.1f}s)")


def cmd_render2(args):
    from engine import composev2
    paths = _paths()
    out = composev2.render_video_v2(paths, args.story, force=args.force)
    print(f"proto2 -> {out}")


def cmd_qa2(args):
    from engine import qa2
    paths = _paths()
    target = Path(args.path) if args.path else paths.output / "proto2.mp4"
    rep = qa2.qa_video_v2(target, paths, args.story)
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ": " + c["detail"])
    print("QA2 " + ("PASS" if rep["pass"] else "FAIL") + f" -> {paths.qa / 'qa2.json'}")


def cmd_facts(args):
    import json as _json
    from engine import facts
    rep = facts.verify_story(Path(args.story_dir))
    print(_json.dumps(rep, indent=1))
    raise SystemExit(0 if rep["ok"] else 1)


def cmd_diag4(args):
    from engine import bible as B, diagrams_v4
    paths = _paths()
    bible = B.load_bible(Path(paths.stories) / args.story)
    manifest = diagrams_v4.write_stages(paths, bible, args.story)
    import json as _json
    print(_json.dumps({k: len(v) for k, v in manifest.items()}, indent=1))


def cmd_plan4(args):
    from engine import planv4, editorial
    paths = _paths()
    plan, rep = planv4.make_edit_plan_v4(paths, args.story)
    for w in rep["warnings"]:
        print("warn:", w)
    for e in rep["errors"]:
        print("error:", e)
    total = sum(s["duration_s"] for s in plan["shots"])
    print(f"edit_plan v4 -> build/edit_plan.json ({len(plan['shots'])} shots, {total:.1f}s)")
    # dump shot-purpose map (pre-render deliverable §17)
    story = json.loads((Path(paths.stories) / args.story / "story.json").read_text())
    vp = json.loads((Path(paths.stories) / args.story / "visual_plan.json").read_text())
    pm = editorial.shot_purpose_map(story, vp)
    (Path(paths.build) / "purpose_map.json").write_text(json.dumps(pm, indent=2))


def cmd_render4(args):
    from engine import composev2
    paths = _paths()
    out = composev2.render_video_v2(paths, args.story, force=args.force,
                                    out_name=f"{args.story}.mp4")
    print(f"render4 -> {out}")


def cmd_qa4(args):
    import json as _json
    from engine import bible as B, phone_qa, qa2, qa3, qa4, style_continuity
    paths = _paths()
    video = Path(args.path) if args.path else paths.output / "proto4.mp4"
    bible = B.load_bible(Path(paths.stories) / args.story)
    rep = qa2.qa_video_v2(video, paths, args.story)
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ": " + c["detail"])
    sty = style_continuity.video_style_score(video, bible, samples=8)
    (Path(paths.build) / "style_continuity.json").write_text(_json.dumps(sty, indent=2))
    print(f"style continuity: mean={sty['mean']} min={sty['min']} max={sty['max']}")
    phone_qa.phone_render(video, Path(paths.build) / "phone_preview.mp4")
    plan4 = _json.loads((Path(paths.build) / "edit_plan.json").read_text())
    man4 = Path(paths.build) / "diag_stages" / "manifest_v4.json"
    stage_pngs = []
    if man4.exists():
        man = _json.loads(man4.read_text())
        assets_dir = Path(paths.assets)
        for stages in man.values():
            stage_pngs += [str(Path(paths.build) / "diag_stages" / f"{st['asset']}_full.png")
                           for st in stages]
    leg = phone_qa.phone_legibility(video, plan_shots=plan4.get("shots"),
                                    stage_pngs=stage_pngs)
    (Path(paths.build) / "phone_qa.json").write_text(_json.dumps(leg, indent=2))
    print(f"phone QA: readable={leg['readable']} pop_px={leg['key_number_px']} "
          f"diag_px={leg['diagram_key_number_px']} probes={leg['probes']}")
    ras = qa3.raster_text_qa(video, Path(paths.stories) / args.story, plan4)
    (Path(paths.build) / "raster_text_qa.json").write_text(_json.dumps(ras, indent=2))
    print(f"raster text QA: regenerated against current video "
          f"({sum(len(v) for v in ras.values()) if isinstance(ras, dict) else 'ok'})")
    res = qa4.run_qa4(video, Path(paths.stories) / args.story, build_dir=paths.build)
    print("groups:", _json.dumps({g: res["groups"][g]["score"] for g in res["groups"]}))
    print("metrics:", _json.dumps({k: round(v["score"], 1) for k, v in res["metrics"].items()}))
    print("p0:", _json.dumps(res["p0_defects"]))
    print("CAN_PUBLISH:", res["CAN_PUBLISH"])
    print("TOP 3 HUMAN-EDITOR CONCERNS:")
    for c in res["top_3_human_editor_concerns"]:
        print("  -", c)
    print("QA4 ->", Path(paths.build) / "qa" / "qa4.json")


def cmd_diag3(args):
    from engine import bible as B, diagrams_v3
    paths = _paths()
    bible = B.load_bible(Path(paths.stories) / args.story)
    manifest = diagrams_v3.write_stages(paths, bible, args.story)
    print(json.dumps({k: len(v) for k, v in manifest.items()}, indent=1))


def cmd_plan3(args):
    from engine import planv3
    paths = _paths()
    plan, rep = planv3.make_edit_plan_v3(paths, args.story)
    for w in rep["warnings"]:
        print("warn:", w)
    for e in rep["errors"]:
        print("error:", e)
    total = sum(s["duration_s"] for s in plan["shots"])
    print(f"edit_plan v3 -> build/edit_plan.json ({len(plan['shots'])} shots, {total:.1f}s)")


def cmd_render3(args):
    from engine import composev2
    paths = _paths()
    out = composev2.render_video_v2(paths, args.story, force=args.force,
                                    out_name="proto3.mp4")
    print(f"proto3 -> {out}")


def cmd_qa3(args):
    from engine import bible as B, phone_qa, qa2, qa3, style_continuity
    paths = _paths()
    video = Path(args.path) if args.path else paths.output / "proto3.mp4"
    bible = B.load_bible(Path(paths.stories) / args.story)
    rep = qa2.qa_video_v2(video, paths, args.story)
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ": " + c["detail"])
    sty = style_continuity.video_style_score(video, bible, samples=8)
    (Path(paths.build) / "style_continuity.json").write_text(json.dumps(sty, indent=2))
    print(f"style continuity: mean={sty['mean']} min={sty['min']} max={sty['max']}")
    phone_qa.phone_render(video, Path(paths.build) / "phone_preview.mp4")
    leg = phone_qa.phone_legibility(video)
    (Path(paths.build) / "phone_qa.json").write_text(json.dumps(leg, indent=2))
    print(f"phone QA: readable={leg['readable']} key_number_px={leg['key_number_px']}")
    res = qa3.run_qa3(video, Path(paths.stories) / args.story, build_dir=paths.build)
    print("scores:", json.dumps({g: res["groups"][g]["score"] for g in res["groups"]}))
    print("p0_defects:", json.dumps(res["p0_defects"]))
    print("can_publish:", res["can_publish"])
    for w in res["weaknesses"]:
        print(f"weakness: [{w['group']}] {w['check']} = {w['score']}")
    print("QA3 ->", Path(paths.build) / "qa" / "qa3.json")


def cmd_plan5(args):
    from engine import planv5
    import shutil as _shutil
    paths = _paths()
    plan, rep = planv5.make_edit_plan_v5(paths, args.story)
    for w in rep["warnings"]:
        print("warn:", w)
    for e in rep["errors"]:
        print("error:", e)
    total = sum(s["duration_s"] for s in plan["shots"])
    gp = plan.get("visual_grammar_plan", {})
    print(f"edit_plan v5 -> build/edit_plan.json ({len(plan['shots'])} shots, {total:.1f}s)")
    print(f"  subject: {gp.get('subject')}  default_grammar: {gp.get('default_grammar')}")
    _print_flags()


def _print_flags():
    """Surface the active flag set (engine.flags.describe) on plan/render —
    the v10v/v10k/v10d/v10p token is also baked into every CAS shot hash."""
    from engine import flags as _flags
    d = _flags.describe()
    print("flags:", _flags.token() or "baseline",
          " ".join(f"{k}={int(v) if isinstance(v, bool) else v}"
                   for k, v in d.items()))


def cmd_render5(args):
    from engine import composev5
    import shutil
    paths = _paths()
    snap = paths.build / f"edit_plan_{args.story}.json"
    if snap.exists():
        shutil.copyfile(snap, paths.build / "edit_plan.json")
        print(f"plan: restored {snap.name} -> edit_plan.json (per-story guard)")
    # Stage-2 V10 fix: the audio bed plan is per-story state too. build/ holds
    # the LAST story's plan (sfx timeline + bed files); without a guard, a
    # render mixes another story's SFX into this one. Restore from the
    # per-story snapshot if present, else the authored story-dir plan.
    bed_snap = paths.build / f"audio_bed_plan_{args.story}.json"
    bed_src = bed_snap if bed_snap.exists() else (
        Path(paths.stories) / args.story / "audio_bed_plan.json")
    if bed_src.exists() and bed_src != paths.build / "audio_bed_plan.json":
        shutil.copyfile(bed_src, paths.build / "audio_bed_plan.json")
        print(f"audio: restored {bed_src.name} -> audio_bed_plan.json (per-story guard)")
    _print_flags()
    out = composev5.render_video_v5(paths, args.story, force=args.force,
                                    out_name=f"{args.story}.mp4")
    print(f"v5 -> {out}")


def cmd_qa5(args):
    import json as _json
    from engine import qa5
    paths = _paths()
    video = Path(args.path) if args.path else paths.output / f"{args.story}.mp4"
    res = qa5.run_qa5(video, Path(paths.stories) / args.story, build_dir=paths.build)
    print("groups:", _json.dumps({g: res["groups"][g]["score"] for g in res["groups"]}))
    print("motion:",
          _json.dumps({k: res["motion"][k] for k in ("mean_jitter", "mean_reversal", "ok", "bad_shots")}))
    print("audio_continuity:", _json.dumps({
        k: res["audio_continuity"][k]
        for k in ("continuous", "gaps", "restarts", "score", "ok")
    }))
    print("CAN_PUBLISH:", res["CAN_PUBLISH"])
    print("TOP 3 HUMAN-EDITOR CONCERNS:")
    for c in res["top_3_human_editor_concerns"]:
        print("  -", c)
    print("QA5 ->", Path(paths.build) / "qa" / "qa5.json")


def cmd_qa5full(args):
    """V6 test-harness command: everything qa5 needs that the earlier V4-era
    steps used to produce inline (qa2 baseline, style/phone/raster QA,
    continuity.json for the generated plates, shots2 sync for the qa2
    engine-gate, sfx injection into the bed plan) — then qa5 itself.
    Adds no new gates; it only assembles the inputs qa5/qa4 read."""
    import json as _json
    import shutil

    import numpy as np
    from PIL import Image

    from engine import bible as B, harmonize, phone_qa, qa2, qa3, qa5, style_continuity
    paths = _paths()
    _snap = paths.build / f"edit_plan_{args.story}.json"
    if _snap.exists():
        shutil.copyfile(_snap, paths.build / "edit_plan.json")
        print(f"plan: restored {_snap.name} -> edit_plan.json (per-story guard)")
    video = Path(args.path) if args.path else paths.output / f"{args.story}.mp4"
    story_dir = Path(paths.stories) / args.story
    bible = B.load_bible(story_dir)

    # 0) shots2 sync: qa2's shot-count gate reads shots2 for engine v5 plans,
    #    while composev5 renders into shots3. Mirror shots3 -> shots2.
    s3 = Path(paths.build) / "shots3"
    s2 = Path(paths.build) / "shots2"
    if s3.exists():
        if s2.exists():
            shutil.rmtree(s2)
        shutil.copytree(s3, s2)

    # 0b) continuity.json for the story's generated plates (harmonize score
    #     vs the bible, same measure composev2.prep_diagrams uses).
    eplan = _json.loads((Path(paths.build) / "edit_plan.json").read_text())
    seen = []
    for s in eplan.get("shots", []):
        a = str(s.get("asset", ""))
        if a and a not in seen:
            seen.append(a)
    rows = []
    for a in seen:
        p = Path(paths.assets) / f"{a}.png"
        if not p.exists():
            continue
        sc = float(harmonize.continuity_score(np.asarray(Image.open(p).convert("RGB")), bible))
        rows.append({"file": f"{a}.png", "score_before": round(sc, 4),
                     "score_after": round(sc, 4), "ok": bool(sc >= 0.55)})
        print(f"continuity {a}: {sc:.3f} {'ok' if sc >= 0.55 else 'LOW'}")
    vals = [r["score_after"] for r in rows]
    (Path(paths.build) / "continuity.json").write_text(_json.dumps(
        {"assets": rows,
         "video_score": round(sum(vals) / len(vals), 4) if vals else None}, indent=2))

    # 0c) sfx injection into the bed plan (times computed from timing.json;
    #     planv5 already wrote bed_files; we only add the sfx layer).
    sfx_spec = story_dir / "sfx_plan.json"
    bp_path = Path(paths.build) / "audio_bed_plan.json"
    if sfx_spec.exists() and bp_path.exists():
        bp = _json.loads(bp_path.read_text())
        timing = _json.loads((story_dir / "audio" / "timing.json").read_text())
        story = _json.loads((story_dir / "story.json").read_text())
        pad = float(story.get("pad_s", 0.7))
        starts, acc = {}, 0.0
        for b in story.get("beats", []):
            bid = b["beat_id"]
            starts[bid] = acc
            acc += float((timing.get(bid) or {}).get("duration", 0)) + pad
        sfx = []
        for e in _json.loads(sfx_spec.read_text()).get("sfx", []):
            t0 = starts.get(e.get("beat_id"), 0.0) + float(e.get("offset", 0.4))
            sfx.append({"file": str(story_dir / e["file"]), "at": round(t0, 3),
                        "dur": float(e.get("dur", 1.5)),
                        "shot_id": e.get("shot_id", ""),
                        "reason": e.get("reason", "")})
            print(f"sfx {e['file']} at {t0:.2f}s")
        bp["sfx"] = sfx
        bp_path.write_text(_json.dumps(bp, indent=2))
        # keep a per-story snapshot so render5's bed-plan guard restores the
        # right sfx timeline (build/ copy is clobbered by the next story)
        _shutil.copyfile(bp_path,
                         paths.build / f"audio_bed_plan_{args.story}.json")

    # 1) the standard V4-era pre-QA chain (same order as cmd_qa4)
    rep = qa2.qa_video_v2(video, paths, args.story)
    for c in rep["checks"]:
        print(("PASS " if c["ok"] else "FAIL ") + c["check"] + ": " + c["detail"])
    sty = style_continuity.video_style_score(video, bible, samples=8)
    (Path(paths.build) / "style_continuity.json").write_text(_json.dumps(sty, indent=2))
    print(f"style continuity: mean={sty['mean']} min={sty['min']} max={sty['max']}")
    phone_qa.phone_render(video, Path(paths.build) / "phone_preview.mp4")
    plan4 = _json.loads((Path(paths.build) / "edit_plan.json").read_text())
    # V6.2: event rects are card-space ([0,1] of the 1080x780 panel at y=176);
    # the legacy phone QA probes in visual-zone space (y 176..1504). Hand it
    # a transformed copy so pop probes land on the rendered numbers.
    if str(plan4.get("engine", "")) == "v6.2":
        import copy as _cp
        from engine import flags as _fl
        _k = 780.0 / 1328.0
        plan4 = _cp.deepcopy(plan4)
        for _s in plan4.get("shots", []):
            for _e in _s.get("events", []) or []:
                _r = (_e.get("spec") or {}).get("rect")
                if _r and not _fl.vertical10():
                    # legacy card (780-tall at y=176) -> visual-zone fractions.
                    # V10_VERTICAL: the plan card is already the active portrait
                    # panel (1080x1152 at y=288) — phone_qa._zone_rect maps it
                    # with the live geometry, so no legacy rescale here.
                    _e["spec"]["rect"] = [_r[0], _r[1] * _k, _r[2], _r[3] * _k]
    man4 = Path(paths.build) / "diag_stages" / "manifest_v4.json"
    stage_pngs = []
    if man4.exists():
        man = _json.loads(man4.read_text())
        for stages in man.values():
            stage_pngs += [str(Path(paths.build) / "diag_stages" / f"{st['asset']}_full.png")
                           for st in stages]
    leg = phone_qa.phone_legibility(video, plan_shots=plan4.get("shots"),
                                    stage_pngs=stage_pngs)
    (Path(paths.build) / "phone_qa.json").write_text(_json.dumps(leg, indent=2))
    print(f"phone QA: readable={leg['readable']} pop_px={leg['key_number_px']} "
          f"diag_px={leg['diagram_key_number_px']} probes={leg['probes']}")
    ras = qa3.raster_text_qa(video, story_dir, plan4)
    (Path(paths.build) / "raster_text_qa.json").write_text(_json.dumps(ras, indent=2))
    print(f"raster text QA: clipped={len(ras['clipped'])} contrast_failures={len(ras['contrast_failures'])}")

    # 2) qa5 proper
    res = qa5.run_qa5(video, story_dir, build_dir=paths.build)
    print("groups:", _json.dumps({g: res["groups"][g]["score"] for g in res["groups"]}))
    print("motion:",
          _json.dumps({k: res["motion"][k] for k in ("mean_jitter", "mean_reversal", "ok", "bad_shots")}))
    print("audio_continuity:", _json.dumps({
        k: res["audio_continuity"][k]
        for k in ("continuous", "gaps", "restarts", "score", "ok")}))
    print("CAN_PUBLISH:", res["CAN_PUBLISH"])
    print("TOP 3 HUMAN-EDITOR CONCERNS:")
    for c in res["top_3_human_editor_concerns"]:
        print("  -", c)
    print("QA5 ->", Path(paths.build) / "qa" / "qa5.json")
    # snapshot per story (build/qa/qa5.json is a shared path)
    snap = Path(paths.build) / "qa" / f"qa5_{args.story}.json"
    shutil.copyfile(Path(paths.build) / "qa" / "qa5.json", snap)
    print("snapshot ->", snap)


def cmd_smoke(args):
    raise SystemExit(_smoke())


# --------------------------------------------------------------------------
# smoke: deterministic 2s test render, run twice, sha256 pair
# --------------------------------------------------------------------------

def _make_smoke_plate(path):
    """1536x1024 parchment gradient + ink lines + rust circle (deterministic
    Pillow art so camera motion is visible)."""
    import numpy as np
    from PIL import Image, ImageDraw

    W, H = 1536, 1024
    top = (233.0, 223.0, 200.0)
    bot = (201.0, 186.0, 152.0)
    g = np.linspace(0.0, 1.0, H, dtype=np.float32)[:, None, None]
    row = np.array(top, np.float32) * (1 - g) + np.array(bot, np.float32) * g
    arr = np.repeat(row, W, axis=1).astype(np.uint8)
    img = Image.fromarray(arr, "RGB")
    d = ImageDraw.Draw(img, "RGBA")
    ink, rust = (42, 33, 24), (180, 85, 45)
    for y in range(128, H, 128):
        d.line([(0, y), (W, y)], fill=ink + (90,), width=2)
    for x in range(192, W, 384):
        d.line([(x, 0), (x, H)], fill=ink + (60,), width=2)
    d.ellipse([1150 - 180, 460 - 180, 1150 + 180, 460 + 180],
              fill=rust + (210,), outline=ink + (255,), width=6)
    d.line([(180, 220), (560, 760)], fill=ink + (150,), width=8)
    d.line([(560, 220), (180, 760)], fill=ink + (120,), width=8)
    d.rectangle([90, 90, 240, 150], outline=ink + (200,), width=4)
    img.save(path)
    print(f"smoke plate -> {path}")


def _smoke():
    """Parchment plate -> 2s ZOOM_IN shot with title band + HIGHLIGHT +
    LIGHT_SWEEP + NumberPop + caption. Rendered twice; sha256 pair decides."""
    root = _paths()
    smoke_dir = root.build / "smoke"
    smoke_dir.mkdir(parents=True, exist_ok=True)
    style = load_style(root)

    plate = smoke_dir / "plate.png"
    _make_smoke_plate(plate)

    shot = {
        "shot_id": "smoke", "asset": "plate", "duration_s": 2.0,
        "camera": {"primitive": "ZOOM_IN",
                   "from": {"w": 0.92, "cx": 0.5, "cy": 0.5},
                   "to": {"w": 0.62, "cx": 0.5, "cy": 0.5}},
        "overlays": [
            {"kind": "HIGHLIGHT", "style": "circle", "color": "rust",
             "target": {"x": 0.60, "y": 0.34, "w": 0.24, "h": 0.30},
             "at": 0.4, "dur": 1.2},
            {"kind": "LIGHT_SWEEP", "at": 1.0, "dur": 0.9},
        ],
        "typography": [{"kind": "number_pop", "text": "100", "at": 0.3,
                        "pos": [760, 760], "color": "rust", "dur": 1.5}],
        "captions": [{"text": "Space is closer than you think.",
                      "t0": 0.2, "t1": 1.8}],
    }
    spaths = Paths(ROOT, assets_dir=smoke_dir, build_dir=smoke_dir,
                   overlays_dir=root.overlays)
    spaths.ensure_dirs()
    ass = smoke_dir / "smoke.ass"
    build_ass(normalize_cues(shot), ass, style)
    print(f"smoke ass   -> {ass} (fontsdir={spaths.fonts})")

    outs = []
    for i in (1, 2):
        out = smoke_dir / ("smoke.mp4" if i == 1 else "smoke_run2.mp4")
        compose.render_shot(shot, spaths, out_path=out, ass_path=ass)
        h = _sha256(out)
        outs.append((out, h))
        print(f"smoke run {i} -> {out}")
        print(f"  sha256 {h}")

    if outs[0][1] == outs[1][1]:
        print("DETERMINISM: IDENTICAL - deterministic pipeline confirmed")
        (smoke_dir / "smoke.sha256").write_text(outs[0][1] + "\n")
        return 0
    print("DETERMINISM: DIFFERENT - investigating")
    p = subprocess.run(["cmp", "-l", str(outs[0][0]), str(outs[1][0])],
                       capture_output=True, text=True)
    head = "\n".join(p.stdout.splitlines()[:5])
    print(f"  first differing bytes:\n{head}")
    return 1


# --------------------------------------------------------------------------

def cmd_qa7(args):
    from engine import editorial7
    story_id = args.story
    plan_path = Path(args.plan) if args.plan else Path("build/edit_plan.json")
    plan = json.loads(plan_path.read_text())
    story = json.loads((Path("stories") / story_id / "story.json").read_text())
    result = editorial7.evaluate(plan, story, save_sig=not args.no_sign)
    out = editorial7.write_report(result, Path("build/qa"))
    cov = result["coverage"]
    print(f"qa7 {story_id} -> {out}")
    print(f"  coverage: EVIDENCE {cov['evidence_pct']}% + CINEMATIC {cov['cinematic_pct']}% | BREATHING {cov['breathing_pct']}% | blur-card {cov['generic_blur_pct']}%")
    print(f"  hook {result['hook']['score']}/100 | ITS transformed-share {result['information_transformation']['transformed_share']} | redundancy {result['redundancy']['redundant_pct']}%")
    print(f"  continuity {result['continuity']['linked_share']} | payoff {result['payoff']['score']}/100 | anti-template {result['anti_template'].get('verdict')}")
    print(f"  editor gates: {'PASS' if result['human_editor_test']['editor_gates_pass'] else 'FAIL'}")
    for k, v in result["gates"].items():
        print(f"    {'PASS' if v else 'FAIL'}  {k}")
    print(f"  V7_EDITORIAL_PASS: {result['V7_EDITORIAL_PASS']}")





def cmd_plan7(args):
    from engine import planv7
    paths = _paths()
    out_name = args.out or "edit_plan.json"
    plan, v7 = planv7.make_edit_plan_v7(paths, args.story, out_name=out_name)
    # per-story snapshot: render5/qa5full restore this so a later plan7 for a
    # different story can never clobber this story's plan (V7 build bug 2026-09-06)
    snap = paths.build / f"edit_plan_{args.story}.json"
    snap.write_text(json.dumps(plan, indent=1) + "\n")
    print(f"  plan snapshot -> build/{snap.name}")
    total = sum(s["duration_s"] for s in plan["shots"])
    at = v7["anti_template"]
    print(f"edit_plan v7 -> build/{out_name} ({len(plan['shots'])} shots, {total:.1f}s)")
    print(f"  story_type: {plan.get('story_type')} | hook {v7['hook_check']['score']}/100 | "
          f"payoff {v7['payoff_check']['score']}/100 | anti-template "
          f"{at.get('verdict_after', at.get('verdict'))} | choreography +{v7.get('choreography_events_added', 0)}")
    for a in v7["actions"]:
        print("  v7:", a)
    for w in v7["warnings"]:
        print("  warn:", w)





def cmd_plan8(args):
    from engine import planv8
    paths = _paths()
    out_name = args.out or "edit_plan.json"
    plan, v8 = planv8.make_edit_plan_v8(paths, args.story, out_name=out_name)
    snap = paths.build / f"edit_plan_{args.story}.json"
    snap.write_text(json.dumps(plan, indent=1) + "\n")
    print(f"  plan snapshot -> build/{snap.name}")
    total = sum(float(s.get("duration_s") or 0) for s in plan.get("shots") or [])
    esc, cur, hero = v8["escalation"], v8["curiosity"], v8["hero_recognizability"]
    sm = v8["state_machine"]
    n = len(plan.get("shots") or [])
    print(f"edit_plan v8 -> build/{out_name} ({n} shots, {total:.1f}s)")
    print(f"  story_type: {plan.get('story_type')} | grammar: {v8['grammar_key']}")
    print(f"  states: {sm['shots_with_states']}/{n} shots | "
          f"needs_state_plate: {', '.join(sm['needs_state_plate']) or 'none'}")
    print(f"  escalation: {esc['verdict']} (range {esc['range']}, std {esc['std']}) | "
          f"curiosity: {cur['verdict']} | hero: "
          f"{'PASS' if hero['ok'] else 'FAIL: ' + '; '.join(hero['findings'])}")
    for a in v8["actions"]:
        print("  v8:", a)
    for w in v8["warnings"]:
        print("  warn:", w)


def cmd_semqa(args):
    from engine import semantic_qa
    paths = _paths()
    res = semantic_qa.verify(paths.stories / args.story)
    out = semantic_qa.write_report(res, Path("build/qa"))
    print(f"semqa {args.story} -> {out}")
    d = res["deterministic"]
    print(f"  deterministic: {'PASS' if d['deterministic_pass'] else 'FAIL'} (FAILs {d['counts']['FAIL']}, WARNs {d['counts']['WARN']})")
    ds = res["deepseek"]
    if ds.get("status") == "ok":
        print(f"  exact-wording (DeepSeek): {'PASS' if ds.get('exact_wording_pass') else 'FAIL'} - overstated {ds.get('n_overstated')}/{ds.get('n_claims')}")
    else:
        print(f"  exact-wording (DeepSeek): {ds.get('status')} ({ds.get('reason', '')})")
    for f in d["findings"][:8]:
        print(f"  [{f['severity']}] {f['rule']} {f['beat_id']}: {f['match']} | {f['sentence'][:70]}")
    print(f"  SEMANTIC_PASS: {res['SEMANTIC_PASS']}")


def cmd_qa8full(args):
    import json as _json
    from engine import editorial7, editorial8, semantic_qa
    paths = _paths()
    story_id = args.story
    _snap = Path("build") / f"edit_plan_{story_id}.json"
    if _snap.exists():
        import shutil
        shutil.copyfile(_snap, Path("build") / "edit_plan.json")
        print(f"plan: restored {_snap.name} -> edit_plan.json (per-story guard)")
    plan = _json.loads((Path("build") / "edit_plan.json").read_text())
    story = _json.loads((paths.stories / story_id / "story.json").read_text())
    qa7_res = editorial7.evaluate(plan, story, save_sig=False)
    v6_ok = None
    if getattr(args, "v6", False):
        cmd_qa5full(args)
        q5p = Path("build/qa") / f"qa5_{story_id}.json"
        v6_ok = bool(_json.loads(q5p.read_text()).get("CAN_PUBLISH")) \
            if q5p.exists() else None
    res8 = editorial8.evaluate8(plan, story, qa7_res)
    sem = semantic_qa.verify(paths.stories / story_id)
    res8["semantic_factual"] = {
        "deterministic_pass": sem["deterministic"]["deterministic_pass"],
        "SEMANTIC_PASS": sem["SEMANTIC_PASS"]}
    res8["story_id"] = story_id
    res8["V6_CAN_PUBLISH"] = v6_ok
    editorial8.write_report(res8, Path("build/qa"))
    print(f"qa8full {story_id} -> build/qa/qa8_{story_id}.json")
    for k, v in res8["gates"].items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    print(f"  V8 editorial: {'PASS' if res8['V8_EDITORIAL_PASS'] else 'FAIL'} | "
          f"documentary_vs_slideshow: {res8['documentary_vs_slideshow']} | "
          f"semantic: {res8['semantic_factual']['SEMANTIC_PASS']}")


def cmd_qa7full(args):
    import json as _json
    from engine import editorial7, semantic_qa
    paths = _paths()
    story_id = args.story
    cmd_qa5full(args)
    qa5_path = Path("build/qa") / f"qa5_{story_id}.json"
    qa5 = _json.loads(qa5_path.read_text()) if qa5_path.exists() else {}
    plan = _json.loads(Path("build/edit_plan.json").read_text())
    story = _json.loads((paths.stories / story_id / "story.json").read_text())
    qa7_res = editorial7.evaluate(plan, story, save_sig=True)
    editorial7.write_report(qa7_res, Path("build/qa"))
    sem = semantic_qa.verify(paths.stories / story_id)
    semantic_qa.write_report(sem, Path("build/qa"))
    combined = {
        "story_id": story_id,
        "v6_technical": {k: qa5.get(k) for k in ("groups", "motion", "audio_continuity")},
        "V6_CAN_PUBLISH": bool(qa5.get("CAN_PUBLISH")),
        "v7_editorial_gates": qa7_res["gates"],
        "V7_EDITORIAL_PASS": qa7_res["V7_EDITORIAL_PASS"],
        "semantic_factual": {"deterministic_pass": sem["deterministic"]["deterministic_pass"],
                             "counts": sem["deterministic"]["counts"],
                             "deepseek_status": sem["deepseek"].get("status"),
                             "exact_wording_pass": sem["deepseek"].get("exact_wording_pass")},
        "SEMANTIC_PASS": sem["SEMANTIC_PASS"],
        "CAN_PUBLISH_V7": bool(qa5.get("CAN_PUBLISH")) and qa7_res["V7_EDITORIAL_PASS"] and sem["SEMANTIC_PASS"],
    }
    out = Path("build/qa") / f"qa7full_{story_id}.json"
    out.write_text(_json.dumps(combined, indent=1))
    print(f"qa7full {story_id} -> {out}")
    print(f"  V6 technical: {'PASS' if combined['V6_CAN_PUBLISH'] else 'FAIL'} | V7 editorial: {'PASS' if combined['V7_EDITORIAL_PASS'] else 'FAIL'} | semantic: {'PASS' if combined['SEMANTIC_PASS'] else 'FAIL'}")
    print(f"  CAN_PUBLISH_V7: {combined['CAN_PUBLISH_V7']}")

def main():
    ap = argparse.ArgumentParser(prog="cli.py",
                                 description="illustrated-documentary engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate", help="validate story JSONs; --make-edit-plan builds edit_plan")
    v.add_argument("--make-edit-plan", action="store_true")
    v.set_defaults(fn=cmd_validate)
    rs = sub.add_parser("render-shot", help="render one shot by id")
    rs.add_argument("shot_id")
    rs.set_defaults(fn=cmd_render_shot)
    rv = sub.add_parser("render-video", help="render shots + concat final")
    rv.set_defaults(fn=cmd_render_video)
    q = sub.add_parser("qa", help="QA a video (default output/final.mp4)")
    q.add_argument("path", nargs="?", default=None)
    q.set_defaults(fn=cmd_qa)
    cs = sub.add_parser("contact-sheet", help="3x4 contact sheet")
    cs.add_argument("path")
    cs.set_defaults(fn=cmd_contact_sheet)
    sm = sub.add_parser("smoke", help="determinism smoke test")
    sm.set_defaults(fn=cmd_smoke)
    tt = sub.add_parser("tts", help="wired at TTS stage")
    tt.set_defaults(fn=cmd_tts)
    d2 = sub.add_parser("diagrams2", help="render programmatic v2 diagram assets")
    d2.add_argument("--story", default="tallest_mountain")
    d2.set_defaults(fn=cmd_diagrams2)
    p2 = sub.add_parser("plan2", help="build v2 edit plan (narration-first)")
    p2.add_argument("--story", default="tallest_mountain")
    p2.set_defaults(fn=cmd_plan2)
    r2 = sub.add_parser("render2", help="render v2 shots + concat -> output/proto2.mp4")
    r2.add_argument("--story", default="tallest_mountain")
    r2.add_argument("--force", action="store_true")
    r2.set_defaults(fn=cmd_render2)
    q2 = sub.add_parser("qa2", help="QA v2 video (default output/proto2.mp4)")
    q2.add_argument("path", nargs="?", default=None)
    q2.add_argument("--story", default="tallest_mountain")
    q2.set_defaults(fn=cmd_qa2)
    g3 = sub.add_parser("diag3", help="render v3 progressive diagram stages")
    g3.add_argument("--story", default="oldest_tree")
    g3.set_defaults(fn=cmd_diag3)
    p3 = sub.add_parser("plan3", help="build v3 edit plan (progressive reveals)")
    p3.add_argument("--story", default="oldest_tree")
    p3.set_defaults(fn=cmd_plan3)
    r3 = sub.add_parser("render3", help="render v3 shots + concat -> output/proto3.mp4")
    r3.add_argument("--story", default="oldest_tree")
    r3.add_argument("--force", action="store_true")
    r3.set_defaults(fn=cmd_render3)
    q3 = sub.add_parser("qa3", help="v3 three-axis QA (default output/proto3.mp4)")
    q3.add_argument("path", nargs="?", default=None)
    q3.add_argument("--story", default="oldest_tree")
    q3.set_defaults(fn=cmd_qa3)
    f4 = sub.add_parser("facts", help="factual-integrity verification (V4 P0)")
    f4.add_argument("story_dir")
    f4.set_defaults(fn=cmd_facts)
    g4 = sub.add_parser("diag4", help="render v4 progressive diagram stages")
    g4.add_argument("--story", default="sugar_star")
    g4.set_defaults(fn=cmd_diag4)
    p4 = sub.add_parser("plan4", help="build v4 edit plan (chrome/roles/levels)")
    p4.add_argument("--story", default="sugar_star")
    p4.set_defaults(fn=cmd_plan4)
    r4 = sub.add_parser("render4", help="render v4 shots + concat -> output/proto4.mp4")
    r4.add_argument("--story", default="sugar_star")
    r4.add_argument("--force", action="store_true")
    r4.set_defaults(fn=cmd_render4)
    q4p = sub.add_parser("qa4", help="V4 three-axis + editorial QA (default output/proto4.mp4)")
    q4p.add_argument("path", nargs="?", default=None)
    q4p.add_argument("--story", default="sugar_star")
    q4p.set_defaults(fn=cmd_qa4)
    p5 = sub.add_parser("plan5", help="build v5 edit plan (subject-specific grammar)")
    p5.add_argument("--story", default="sugar_star")
    p5.set_defaults(fn=cmd_plan5)
    r5 = sub.add_parser("render5", help="render v5 -> output/<story>.mp4 (Bezier motion + 3-layer audio)")
    r5.add_argument("--story", default="sugar_star")
    r5.add_argument("--force", action="store_true")
    r5.set_defaults(fn=cmd_render5)
    q5p = sub.add_parser("qa5", help="V6 QA: motion smoothness + audio continuity + editor test")
    q5p.add_argument("path", nargs="?", default=None)
    q5p.add_argument("--story", default="sugar_star")
    q5p.set_defaults(fn=cmd_qa5)
    q5f = sub.add_parser("qa5full", help="V6 QA + assemble qa2/style/phone/raster/continuity inputs")
    q5f.add_argument("path", nargs="?", default=None)
    q5f.add_argument("--story", default="sugar_star")
    q5f.set_defaults(fn=cmd_qa5full)
    q7 = sub.add_parser("qa7", help="V7 editorial metric suite (spec-level: coverage/hook/ITS/redundancy/continuity/payoff/anti-template)")
    q7.add_argument("--story", default="sugar_star")
    q7.add_argument("--plan", default=None)
    q7.add_argument("--no-sign", action="store_true")
    q7.set_defaults(fn=cmd_qa7)
    p7 = sub.add_parser("plan7", help="build V7 edit plan (editorial intelligence over planv5)")
    p7.add_argument("--story", default="sugar_star")
    p7.add_argument("--out", default=None)
    p7.set_defaults(fn=cmd_plan7)
    p8 = sub.add_parser("plan8", help="build V8 edit plan (visual state machine over planv7)")
    p8.add_argument("--story", default="sugar_star")
    p8.add_argument("--out", default=None)
    p8.set_defaults(fn=cmd_plan8)
    sq = sub.add_parser("semqa", help="V7 semantic factual QA (P0-8: exact wording, qualifiers, perspective)")
    sq.add_argument("--story", default="sugar_star")
    sq.set_defaults(fn=cmd_semqa)
    q7f = sub.add_parser("qa7full", help="V7 full gate: qa5full + qa7 + semqa -> CAN_PUBLISH_V7")
    q7f.add_argument("path", nargs="?", default=None)
    q7f.add_argument("--story", default="sugar_star")
    q7f.set_defaults(fn=cmd_qa7full)
    q8f = sub.add_parser("qa8full", help="V8 editorial gate: info gain + semantic payoff + narration cards + viewer sim (+ --v6 technical)")
    q8f.add_argument("path", nargs="?", default=None)
    q8f.add_argument("--story", default="sugar_star")
    q8f.add_argument("--v6", action="store_true")
    q8f.set_defaults(fn=cmd_qa8full)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
