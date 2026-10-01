"""V16 WP5 — one-composition render (DESIGN.md S8 / 15.2 WP5).

Builds the props for `Short.tsx` (`<Series>` of the same per-scene
`SceneComposition` props every scene already renders with, plus a
`Captions` overlay driven by `@remotion/captions`, and optional `Sting`/
`Outro` overlays) and drives a pre-bundled `@remotion/renderer` render via
`remotion_project/render_short.mjs`.

This module is additive: it does not change `v15_pipeline.run_pipeline`'s
live compose path (`engine.v14_assembly.assemble`, Python caption PNGs
burned by ffmpeg). Per DESIGN.md 15.2 WP5 and AGENTS.md's fallback rule,
the Python caption pass stays the default until a frame-exact parity test
(`bench/ab/wp5_parity.py`) proves SSIM >= 0.98 against it. See
`bench/ab/wp5.md` for the measured number and the resulting go/no-go.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

try:
    from engine.asset_pipeline import stage_assets
    from engine.brand import caption_style, load_brand
    from engine.captions import band_rect
    from engine.scene_renderer import RENDER_PROJECT, compile_spec
except ImportError:  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.asset_pipeline import stage_assets
    from engine.brand import caption_style, load_brand
    from engine.captions import band_rect
    from engine.scene_renderer import RENDER_PROJECT, compile_spec

RENDER_SCRIPT = RENDER_PROJECT / "render_short.mjs"
COMPOSITION_ID = "Short"
RENDER_TIMEOUT_S = 900

# @remotion/captions' createTikTokStyleCaptions regroups a flat per-word
# timeline back into cue "pages". The live pipeline's word windows never
# have an intra-cue gap (proportional/word_starts timing is continuous) and
# always have >=50ms between cues (engine.captions.STATE_GAP), so any
# threshold strictly between those two bounds reproduces the exact same
# cue groups the Python pass burned — verified against the ice_slippery
# fixture in bench/ab/wp5_parity.py (min gap seen: 60ms).
CAPTION_COMBINE_MS = 40


class ComposeError(ValueError):
    pass


def _stage_caption_font(brand: dict) -> None:
    """Copy the brand caption font to public/fonts/caption.ttf — the one
    font SceneComposition's sibling Captions.tsx needs that
    scene_renderer._stage_fonts (display/body only) does not stage."""
    import shutil
    src = Path(caption_style(brand)["font"])
    dest = RENDER_PROJECT / "public" / "fonts" / "caption.ttf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.read_bytes() != src.read_bytes():
        shutil.copyfile(src, dest)


def build_caption_track(caption_overlays: list) -> list:
    """assembly_report.json's flat per-word `caption_overlays` (png, t0, t1,
    cue, text, word) -> a flat per-word `@remotion/captions` `Caption[]`
    (text, startMs, endMs). No grouping here — Captions.tsx's
    `createTikTokStyleCaptions` call does that, from real per-word times."""
    track = []
    for item in caption_overlays or []:
        t0, t1 = float(item["t0"]), float(item["t1"])
        if t1 <= t0:
            continue
        track.append({
            "text": str(item["word"]),
            "startMs": round(t0 * 1000),
            "endMs": round(t1 * 1000),
        })
    track.sort(key=lambda c: c["startMs"])
    return track


def build_short_props(scene_entries: list, caption_overlays: list,
                      brand: dict | None = None, sting: dict | None = None,
                      outro: dict | None = None) -> dict:
    """scene_entries: [{"scene_id": str, "spec": <scene IR dict>}] in the
    exact order they were concatenated (production["reuse"]/["render"]
    order — the same list `engine.v14_assembly._concat_scenes` consumed).

    Returns the JSON-serializable `ShortProps` for `Short.tsx`. Pure aside
    from asset/font staging into remotion_project/public (the same staging
    every per-scene render already does via `stage_assets`/`_stage_fonts`).
    """
    if not scene_entries:
        raise ComposeError("build_short_props: no scenes")
    brand = brand or load_brand()
    _stage_caption_font(brand)

    scenes = []
    sizes = set()
    fps = None
    for entry in scene_entries:
        staged, _ = stage_assets(entry["spec"], RENDER_PROJECT / "public")
        props = compile_spec(staged)
        sizes.add((props["width"], props["height"]))
        fps = fps or props["fps"]
        if props["fps"] != fps:
            raise ComposeError(
                f"scene {entry['scene_id']!r}: fps {props['fps']} != {fps}")
        scenes.append({"id": entry["scene_id"],
                       "durationInFrames": props["durationInFrames"],
                       "props": props})
    if len(sizes) != 1:
        raise ComposeError(f"scene frame sizes differ: {sorted(sizes)}")
    width, height = sizes.pop()

    cap = caption_style(brand)
    return {
        "width": width,
        "height": height,
        "fps": fps,
        "scenes": scenes,
        "captions": {
            "track": build_caption_track(caption_overlays),
            "combineWithinMs": CAPTION_COMBINE_MS,
            "bandTop": band_rect()[0],
            "textColor": cap["fill"],
            "activeColor": cap["active"],
        },
        "sting": sting,
        "outro": outro,
    }


def total_duration_frames(props: dict) -> int:
    """Total Short duration = the scenes alone. Per DESIGN.md S4/7.1, the
    sting is an overlay at t=0 (not a pre-roll) and the outro is a brand
    stamp over the FINAL moving footage (not a static end screen) — neither
    extends the timeline."""
    return sum(s["durationInFrames"] for s in props["scenes"])


def _run_node(args: list, timeout: int = RENDER_TIMEOUT_S):
    if not RENDER_SCRIPT.is_file():
        raise ComposeError(f"missing {RENDER_SCRIPT}")
    cmd = ["node", str(RENDER_SCRIPT), *args]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(RENDER_PROJECT), capture_output=True,
                          text=True, timeout=timeout)
    return proc, time.time() - t0


def render_short_frames(props: dict, frames: list, out_dir: str | Path) -> dict:
    """One pre-bundled `@remotion/renderer` process renders every frame in
    `frames` (absolute frame indices into the whole Short composition) as a
    PNG `out_dir/f_<n>.png` — one webpack bundle for all N frames, not one
    `npx remotion still` cold start per frame (bench/ab/wp5.md measures the
    difference)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    props_file = out_dir / "short.props.json"
    props_file.write_text(json.dumps(props))
    proc, secs = _run_node([
        "stills", str(props_file), str(out_dir),
        ",".join(str(f) for f in frames),
    ])
    res = {"ok": proc.returncode == 0, "seconds": round(secs, 1),
          "frames": frames, "out_dir": str(out_dir)}
    if proc.stderr.strip():
        res["stderr_tail"] = proc.stderr.strip()[-1200:]
    if proc.stdout.strip():
        res["stdout_tail"] = proc.stdout.strip()[-400:]
    return res


def render_short(props: dict, out_path: str | Path) -> dict:
    """Full `Short` composition render (mp4) via the same pre-bundled
    renderer, for a real end-to-end proof (not used by the frame-sampled
    parity test, which only needs `render_short_frames`)."""
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    props_file = out.parent / f"{out.stem}.short.props.json"
    props_file.write_text(json.dumps(props))
    proc, secs = _run_node(["render", str(props_file), str(out)])
    res = {"ok": proc.returncode == 0, "seconds": round(secs, 1),
          "out": str(out)}
    if proc.stderr.strip():
        res["stderr_tail"] = proc.stderr.strip()[-1200:]
    return res
