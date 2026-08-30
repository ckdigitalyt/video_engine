"""prepare_hero_keyframes.py — Pre-flight HERO-shot artifact preparation.

For every HERO shot in a run's shotlist this tool:

1. Builds the §11 cinematic prompt deterministically from the shot's
   structured fields (engine.v4.prompts.build_cinematic_prompt — LTX variant
   by default, generic variant available).
2. Generates a keyframe still with NVIDIA NIM FLUX via the AI Media Broker
   and copies it into <out>/hero_keyframes/<SHOT>_keyframe.png.
3. Saves <SHOT>_prompt.txt (prompt + negative + build metadata) and a
   manifest.json describing exactly what a post-quota-reset agent needs to
   i2v the shot directly (prompt, negative, seed, duration, keyframe path).
4. Wires the keyframe into the shot (asset_requirements.image_path +
   asset_requirements.still_path so the AI_IMAGE_MOTION fallback reuses the
   same plate) and marks metadata.pending_ai_video = True in shotlist.json.
5. Ensures HERO shots carry the §15 layered-motion config (parallax +
   atmosphere + declared micro_events) so the fallback render is an animated
   scene, not a Ken Burns slide.

Usage:
    venv/bin/python tools/prepare_hero_keyframes.py --out results/dino_v2 \
        [--variant ltx] [--shot-ids S02,S07] [--skip-imagegen]

Idempotent: existing keyframes are reused unless --regen is passed.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

for _line in (ROOT / ".env").read_text().splitlines():
    _line = _line.strip()
    if _line and not _line.startswith("#") and "=" in _line:
        _k, _v = _line.split("=", 1)
        os.environ.setdefault(_k.strip(), _v.strip())

from engine.broker.broker import MediaBroker  # noqa: E402
from engine.v4.prompts import (  # noqa: E402
    ShotSpec,
    build_cinematic_prompt,
    build_negative_prompt,
)

_CAMERA_MOVES = {"static", "push_in", "pull_out", "pan", "tilt", "orbit",
                 "tracking", "whip", "dolly", "handheld"}
_SCALES = {"wide", "medium", "close", "macro"}


def shot_to_spec(shot: dict) -> ShotSpec:
    """Structured ShotSpec from the shot's v4 fields (deterministic)."""
    subject = str(shot.get("subject") or shot.get("visual_goal") or "").strip()
    if not subject:
        raise ValueError(f"{shot.get('shot_id')}: no subject/visual_goal")
    camera_move = str(shot.get("camera_move") or "static")
    if camera_move not in _CAMERA_MOVES:
        camera_move = "static"
    scale = str(shot.get("shot_scale") or "medium")
    if scale not in _SCALES:
        scale = "medium"
    return ShotSpec(
        subject=subject,
        action=str(shot.get("visual_event") or shot.get("subject_motion")
                   or "").strip(),
        environment=str(shot.get("environment") or "").strip(),
        camera_move=camera_move,
        shot_scale=scale,
        lighting_change=str(shot.get("lighting_change") or "").strip(),
        motion=str(shot.get("environment_motion") or "").strip(),
        duration_sec=float(shot.get("duration_sec") or 4.0),
        seed=int(shot.get("seed") or 0),
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, help="results/<id> dir")
    ap.add_argument("--variant", default="ltx", choices=["ltx", "generic"])
    ap.add_argument("--shot-ids", default=None,
                    help="comma list; default = every shot_class==HERO")
    ap.add_argument("--skip-imagegen", action="store_true",
                    help="prompts/manifest only (no broker calls)")
    ap.add_argument("--regen", action="store_true",
                    help="re-generate keyframes even if present")
    args = ap.parse_args()

    out_dir = Path(args.out)
    shotlist_path = out_dir / "shotlist.json"
    plan = json.loads(shotlist_path.read_text(encoding="utf-8"))
    shots = plan.get("shots", [])

    kf_dir = out_dir / "hero_keyframes"
    kf_dir.mkdir(parents=True, exist_ok=True)

    if args.shot_ids:
        wanted = [s.strip() for s in args.shot_ids.split(",") if s.strip()]
        targets = [s for s in shots if s.get("shot_id") in wanted]
    else:
        targets = [s for s in shots
                   if (s.get("shot_class") or "").upper() == "HERO"
                   or (s.get("renderer") or "").upper() == "AI_VIDEO"]
    if not targets:
        print("no HERO shots found — nothing to do")
        return 1

    broker = None if args.skip_imagegen else MediaBroker()
    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run": str(out_dir),
        "note": ("Post-quota-reset agent: run image_to_video(keyframe, "
                 "prompt, duration, seed) per entry, then re-run the "
                 "pipeline render for the shot (or render_shot with "
                 "renderer=AI_VIDEO) and replace the fallback clip."),
        "provider_hint": ["hf_router_i2v (fal-ai Wan2.2, monthly credits)",
                          "wan22_i2v / zerogpu_i2v (ZeroGPU daily quota)"],
        "shots": [],
    }

    for shot in targets:
        sid = shot.get("shot_id", "?")
        spec = shot_to_spec(shot)
        prompt = build_cinematic_prompt(spec, variant=args.variant)
        negative = build_negative_prompt(spec)
        seed = int(shot.get("seed") or spec.seed or 0)

        kf_path = kf_dir / f"{sid}_keyframe.png"
        provider = None
        if kf_path.exists() and not args.regen:
            provider = "cached"
        elif not args.skip_imagegen:
            result = broker.generate_image(
                prompt, aspect="16:9", seed=seed,
                renderer_version="v4_hero_keyframe")
            src = Path(result.path)
            if src.resolve() != kf_path.resolve():
                shutil.copyfile(src, kf_path)
            provider = result.provider

        # Per-shot prompt file (human- and agent-readable).
        meta_block = {
            "shot_id": sid,
            "variant": args.variant,
            "seed": seed,
            "duration_sec": float(shot.get("duration_sec") or 4.0),
            "camera_move": spec.camera_move,
            "shot_scale": spec.shot_scale,
            "keyframe": str(kf_path),
            "negative_prompt": negative,
            "provider_order": ["AI_VIDEO", "AI_VIDEO_retry_intelligent",
                               "AI_VIDEO_alt_provider",
                               "AI_IMAGE_MOTION (downgrade)"],
        }
        (kf_dir / f"{sid}_prompt.txt").write_text(
            prompt + "\n\n--- metadata ---\n"
            + json.dumps(meta_block, indent=2) + "\n", encoding="utf-8")

        # Wire the shot: keyframe into both AI renderers' requirement keys,
        # pending_ai_video flag, and the §15 layered-motion config.
        req = shot.get("asset_requirements")
        req = dict(req) if isinstance(req, dict) else {}
        if kf_path.exists():
            req["image_path"] = str(kf_path.resolve())
            req["still_path"] = str(kf_path.resolve())
        shot["asset_requirements"] = req
        md = shot.setdefault("metadata", {})
        md["pending_ai_video"] = True
        md["ai_video_prompt"] = prompt
        md["ai_video_negative"] = negative
        md["ai_video_variant"] = args.variant
        md["hero_keyframe"] = str(kf_path)
        motion = shot.get("motion")
        motion = dict(motion) if isinstance(motion, dict) else {}
        motion.setdefault("parallax", True)
        motion.setdefault("atmosphere", True)
        shot["motion"] = motion
        if not shot.get("micro_events"):
            from engine.v4.microevents import derive_micro_events
            shot["micro_events"] = derive_micro_events(shot)

        manifest["shots"].append({
            "shot_id": sid,
            "prompt": prompt,
            "negative_prompt": negative,
            "keyframe": str(kf_path) if kf_path.exists() else None,
            "keyframe_provider": provider,
            "seed": seed,
            "duration_sec": float(shot.get("duration_sec") or 4.0),
            "narration": shot.get("narration") or shot.get("narration_text")
            or "",
            "micro_events": shot.get("micro_events", []),
        })
        print(f"{sid}: prompt built, keyframe={'ok' if kf_path.exists() else 'MISSING'} "
              f"({provider})")

    (kf_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    shotlist_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    print(f"manifest: {kf_dir / 'manifest.json'}")
    print(f"shotlist updated: {shotlist_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
