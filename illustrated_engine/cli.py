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
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
