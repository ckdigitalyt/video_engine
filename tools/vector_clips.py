"""
Vector clip generator (v12) — Kurzgesagt-style flat-vector ANIMATED clips
rendered headless in Blender 4.0.2 (Workbench FLAT, transparent PNGs,
ffmpeg composite onto the channel navy).

Fixes the two biggest v11 failures: the sleep episode shipped with
`manim: 0` and ZERO vector/animation — 19 cached stills + 1 AI image.
Every scene can now pull an animated vector beat.

Templates (all flat mesh shapes, CPU-cheap):
  orbit       — planet + ring + orbiting moon, camera drift
  figure_walk — Kurzgesagt human figure walking in place (proven cycle)
  pulse       — concentric pulsing rings (hook / emotion beats)
  bars        — growing bar chart (data beats)
  clock       — analog clock sweeping to 7 (time/sleep beats)
  waves       — layered sine waves (brain/rhythm beats)

Usage:
  venv/bin/python tools/vector_clips.py --template orbit --out cache/vector/orbit.mp4
"""
import argparse
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

TEMPLATES = {
    # all beats share one parameterized Blender script; VC_TEMPLATE picks it
    "orbit": "vector_scene.py",
    "figure_walk": "vector_scene.py",
    "pulse": "vector_scene.py",
    "bars": "vector_scene.py",
    "clock": "vector_scene.py",
    "waves": "vector_scene.py",
}

DURATION = {"orbit": 8, "figure_walk": 8, "pulse": 6, "bars": 8, "clock": 8, "waves": 6}
FPS = 30
W, H = 1920, 1080
BG = (0.067, 0.071, 0.125)  # ~ #111420 channel navy (linear ≈ sRGB)


def _hex(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def render(template: str, out_path: str, palette: dict | None = None,
           duration: float | None = None, label: str = "") -> str:
    src = os.path.join(ROOT, "tools", "blender_templates", TEMPLATES[template])
    if not os.path.exists(src):
        raise FileNotFoundError(f"template script missing: {src}")
    dur = duration or DURATION[template]
    frames = max(1, int(dur * FPS))
    tmp = tempfile.mkdtemp(prefix="vecclip_")
    pal = palette or {}
    env = dict(os.environ)
    env.update({
        "VC_TEMPLATE": template,
        "VC_FRAMES": str(frames),
        "VC_FPS": str(FPS),
        "VC_W": str(W),
        "VC_H": str(H),
        "VC_OUT": tmp,
        "VC_BG": ",".join(f"{c:.4f}" for c in BG),
        "VC_LABEL": label or "",
    })
    for k, v in pal.items():
        env[f"VC_PAL_{k.upper()}"] = v if isinstance(v, str) else ",".join(f"{c:.4f}" for c in v)
    r = subprocess.run(
        ["blender", "-b", "-P", src, "--", "--vector"],
        capture_output=True, text=True, env=env, timeout=3600,
    )
    if r.returncode != 0:
        raise RuntimeError(f"blender failed: {r.stderr[-500:]}")
    pngs = sorted(f for f in os.listdir(tmp) if f.endswith(".png"))
    if not pngs:
        raise RuntimeError(f"no frames rendered: {r.stderr[-300:]}")
    # composite transparent frames onto navy bg → h264 mp4
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    if os.path.exists(out_path):
        os.remove(out_path)  # never leave a stale/partial clip behind
    concat = os.path.join(tmp, "frames.txt")
    with open(concat, "w") as f:
        for p in pngs:
            f.write(f"file '{os.path.join(tmp, p)}'\n")
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat,
        "-filter_complex",
        f"color=c=0x{int(BG[0]*255):02x}{int(BG[1]*255):02x}{int(BG[2]*255):02x}"
        f":s={W}x{H}:r={FPS},format=rgb24[bg];"
        f"[0:v]format=rgba[fg];[bg][fg]overlay=0:0:shortest=1:format=auto,format=yuv420p[vout]",
        "-map", "[vout]",
        "-r", str(FPS), "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        out_path,
    ]
    r2 = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
    if r2.returncode != 0 or not os.path.exists(out_path):
        raise RuntimeError(f"ffmpeg composite failed: {r2.stderr[-400:]}")
    return out_path


def render_all(out_dir: str, only: str | None = None) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    made = []
    for t in TEMPLATES:
        if only and t != only:
            continue
        out = os.path.join(out_dir, f"vector_{t}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 200_000:
            print(f"  [cache] {t} exists ({os.path.getsize(out)//1024} KB)")
            made.append(out)
            continue
        print(f"  [render] {t} ...", flush=True)
        try:
            render(t, out)
            made.append(out)
            print(f"  [ok] {t} -> {out}")
        except Exception as e:  # noqa: BLE001
            print(f"  [FAIL] {t}: {str(e)[:120]}")
    return made


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=None)
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "cache", "vector"))
    args = ap.parse_args()
    made = render_all(args.out_dir, only=args.template)
    print(f"DONE: {len(made)} vector clips ready")
