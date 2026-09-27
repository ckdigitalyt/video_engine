"""V14 Stage 5 — SceneRenderer adapter contract + backends + backend router.

Contract (directive §22, deliverable D) — every backend implements:
    render(spec, out_path)                  full scene render (mp4)
    render_frame(spec, frame, out_path)     single frame still (png)
    render_preview(spec, out_path, frames)  first-N-frames preview (mp4)
    validate(spec)                          -> (ok, errors)
    capabilities()                          -> capability dict (§23)

Backends:
    RemotionRenderer  — primary (Stage 3 decision, commit 9111d8d). Compiles
                        Scene IR -> props and drives the generic
                        SceneComposition in engine/remotion_project.
    FallbackRenderer  — existing composev5/FFmpeg pipeline. Capability-declared
                        now, wired at Stage 7 (asset/layer mapping). The router
                        never selects unavailable backends.

Cache note (§24): compile_spec() carries specHash — the canonical
spec_hash(normalize(spec)) — so cache keys can bind to the exact scene spec.

CLI:
    python3 -m engine.scene_renderer compile    <spec.json> [out.props.json]
    python3 -m engine.scene_renderer backend    <spec.json>
    python3 -m engine.scene_renderer render     <spec.json> <out.mp4> [--concurrency N]
    python3 -m engine.scene_renderer preview    <spec.json> <out.mp4> [--frames N]
    python3 -m engine.scene_renderer frame      <spec.json> <out.png> [--frame N]
    python3 -m engine.scene_renderer capabilities
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

try:
    from engine.scene_ir import (
        normalize_scene_spec,
        spec_hash,
        validate_scene_spec,
    )
except ImportError:  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.scene_ir import (
        normalize_scene_spec,
        spec_hash,
        validate_scene_spec,
    )

RENDER_PROJECT = Path(__file__).resolve().parent / "remotion_project"
COMPOSITION_ID = "SceneIR"
DEFAULT_CONCURRENCY = 2  # bounded workers (directive §26)
RENDER_TIMEOUT_S = 900


class BackendUnavailable(RuntimeError):
    """Raised when a requested backend is not installed/wired."""


# --------------------------------------------------------------------------
# IR -> props compilation (seconds domain -> frames domain)
# --------------------------------------------------------------------------

def compile_spec(spec: dict) -> dict:
    """Compile a Scene IR spec into Remotion props.

    Pure and deterministic: same spec -> byte-identical props JSON. Camera and
    animation keyframe times become frame indices; per-keyframe easing falls
    back to the camera-level easing; top-level animations are attached to
    their target layers; visibility windows are clamped to [0, duration].
    """
    norm = normalize_scene_spec(spec)
    fps = float(norm["fps"])
    dur = max(1, int(round(float(norm["duration_s"]) * fps)))
    w, h = int(norm["size"][0]), int(norm["size"][1])

    cam = norm["camera"]
    cam_default_easing = cam.get("easing", "linear")
    cam_kfs: list[dict] = []
    for kf in cam.get("keyframes", []):
        v = kf["value"]
        if isinstance(v, dict):
            scale, x, y = float(v.get("scale", 1.0)), float(v.get("x", 0.0)), float(v.get("y", 0.0))
        else:
            scale, x, y = float(v), 0.0, 0.0
        cam_kfs.append({
            "frame": int(round(float(kf["t"]) * fps)),
            "scale": scale, "x": x, "y": y,
            "easing": kf.get("easing", cam_default_easing),
        })
    if len(cam_kfs) < 2:  # static camera: synth a flat two-keyframe track
        end = cam_kfs[-1] if cam_kfs else {"scale": 1.0, "x": 0.0, "y": 0.0}
        cam_kfs = [
            {"frame": 0, "scale": end["scale"], "x": end["x"], "y": end["y"],
             "easing": cam_default_easing},
            {"frame": dur, "scale": end["scale"], "x": end["x"], "y": end["y"],
             "easing": cam_default_easing},
        ]

    anims_by_layer: dict[str, list[dict]] = {}
    for a in norm.get("animations", []):
        kfs = [{
            "frame": int(round(float(kf["t"]) * fps)),
            "value": kf["value"],
            "easing": kf.get("easing", "linear"),
        } for kf in a.get("keyframes", [])]
        anims_by_layer.setdefault(a["target_layer"], []).append(
            {"property": a.get("property", "opacity"), "keyframes": kfs}
        )

    layers: list[dict] = []
    for layer in sorted(norm["layers"], key=lambda l: l.get("z", 0)):
        vis = layer.get("visibility")
        if vis:
            v0 = max(0, min(dur, int(round(float(vis[0]) * fps))))
            v1 = max(v0 + 1, min(dur, int(round(float(vis[1]) * fps))))
        else:
            v0, v1 = 0, dur
        layers.append({
            "id": layer["id"],
            "type": layer["type"],
            "semantic_role": layer.get("semantic_role", ""),
            "source": layer["source"],
            "position": layer["position"],
            "scale": layer["scale"],
            "rotation": layer["rotation"],
            "opacity": layer["opacity"],
            "z": layer.get("z", 0),
            "depth": layer["depth"],
            "anchor": layer.get("anchor", "center"),
            "visibility": [v0, v1],
            "payload": layer.get("payload", {}),
            "animations": anims_by_layer.get(layer["id"], []),
        })

    return {
        "specHash": spec_hash(norm),
        "width": w,
        "height": h,
        "fps": int(fps) if float(fps).is_integer() else fps,
        "durationInFrames": dur,
        "seed": norm.get("seed", 0),
        "camera": {
            "type": cam["type"],
            "keyframes": cam_kfs,
            "apertures": cam.get("aperture_layers", []),
            "value_space": cam.get("value_space", "linear_scale"),
        },
        "layers": layers,
        "palette": None,
    }


# --------------------------------------------------------------------------
# Backend contract + implementations
# --------------------------------------------------------------------------

class SceneRenderer:
    name = "abstract"

    def capabilities(self) -> dict:
        raise NotImplementedError

    def available(self) -> bool:
        return True

    def validate(self, spec: dict) -> tuple[bool, list[str]]:
        return validate_scene_spec(spec)

    def render(self, spec: dict, out_path: str | Path,
               concurrency: int = DEFAULT_CONCURRENCY) -> dict:
        raise NotImplementedError

    def render_frame(self, spec: dict, frame: int, out_path: str | Path) -> dict:
        raise NotImplementedError

    def render_preview(self, spec: dict, out_path: str | Path,
                       frames: int = 30) -> dict:
        raise NotImplementedError


class RemotionRenderer(SceneRenderer):
    """Primary backend: generic SceneComposition, headless `remotion render`."""

    name = "remotion"

    def capabilities(self) -> dict:
        return {
            "available": True,
            "animated_vector": True,
            "layered_composition": True,
            "continuous_camera": True,
            "masks_apertures": True,
            "text_annotations": True,
            "audio_layers": True,
            "raster_cinematic": False,
            "deterministic": True,
            "max_tested_scale_dive": 30,
            "notes": "generic SceneComposition; grammar-specific payload "
                     "coverage expands at Stage 6",
        }

    def available(self) -> bool:
        return (RENDER_PROJECT / "node_modules" / ".bin" / "remotion").exists() \
            and (RENDER_PROJECT / "src" / "index.ts").exists()

    def _require(self) -> None:
        if not self.available():
            raise BackendUnavailable(
                f"remotion project not installed — run `npm install` in {RENDER_PROJECT}"
            )

    def _run(self, args: list[str], timeout: int = RENDER_TIMEOUT_S):
        cmd = ["npx", "remotion", *args, "--log", "error"]
        t0 = time.time()
        proc = subprocess.run(
            cmd, cwd=str(RENDER_PROJECT), capture_output=True, text=True,
            timeout=timeout,
        )
        return proc, time.time() - t0

    def _props_file(self, spec: dict, out_path: str | Path) -> tuple[dict, Path]:
        props = compile_spec(spec)
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        pf = out.parent / f"{out.stem}.props.json"
        pf.write_text(json.dumps(props, sort_keys=True, indent=1))
        return props, pf

    @staticmethod
    def _result(proc, secs: float, props: dict, pf: Path,
                out: Path) -> dict:
        res: dict[str, Any] = {
            "backend": "remotion",
            "spec_hash": props["specHash"],
            "ok": proc.returncode == 0,
            "seconds": round(secs, 1),
            "out": str(out),
            "props": str(pf),
        }
        if proc.stderr.strip():
            res["stderr_tail"] = proc.stderr.strip()[-800:]
        if res["ok"] and out.exists():
            res["md5"] = hashlib.md5(out.read_bytes()).hexdigest()
            res["bytes"] = out.stat().st_size
        return res

    def render(self, spec: dict, out_path: str | Path,
               concurrency: int = DEFAULT_CONCURRENCY) -> dict:
        self._require()
        ok, errors = self.validate(spec)
        if not ok:
            raise ValueError("invalid scene spec: " + "; ".join(errors[:5]))
        props, pf = self._props_file(spec, out_path)
        out = Path(out_path).resolve()
        proc, secs = self._run([
            "render", COMPOSITION_ID, str(out),
            "--props", str(pf), "--codec", "h264",
            "--concurrency", str(concurrency),
        ])
        return self._result(proc, secs, props, pf, out)

    def render_frame(self, spec: dict, frame: int, out_path: str | Path) -> dict:
        self._require()
        ok, errors = self.validate(spec)
        if not ok:
            raise ValueError("invalid scene spec: " + "; ".join(errors[:5]))
        props, pf = self._props_file(spec, out_path)
        out = Path(out_path).resolve()
        proc, secs = self._run([
            "render", COMPOSITION_ID, str(out),
            "--props", str(pf), "--frame", str(int(frame)),
        ])
        return self._result(proc, secs, props, pf, out)

    def render_preview(self, spec: dict, out_path: str | Path,
                       frames: int = 30) -> dict:
        self._require()
        ok, errors = self.validate(spec)
        if not ok:
            raise ValueError("invalid scene spec: " + "; ".join(errors[:5]))
        props, pf = self._props_file(spec, out_path)
        out = Path(out_path).resolve()
        proc, secs = self._run([
            "render", COMPOSITION_ID, str(out),
            "--props", str(pf), "--frames", f"0-{max(0, frames - 1)}",
            "--codec", "h264", "--concurrency", str(DEFAULT_CONCURRENCY),
        ])
        return self._result(proc, secs, props, pf, out)


class FallbackRenderer(SceneRenderer):
    """Existing composev5/FFmpeg pipeline — capability-declared, wired Stage 7."""

    name = "fallback"

    def capabilities(self) -> dict:
        return {
            "available": False,
            "animated_vector": False,
            "raster_cinematic": True,
            "simple_diagram": True,
            "wiring_stage": "Stage 7 (scene layers -> composev5/FFmpeg mapping)",
        }

    def available(self) -> bool:
        return False

    def _unavailable(self) -> None:
        raise BackendUnavailable(
            "FallbackRenderer not wired yet — scheduled Stage 7 (directive §23); "
            "router never selects unavailable backends"
        )

    def render(self, spec: dict, out_path: str | Path,
               concurrency: int = DEFAULT_CONCURRENCY) -> dict:
        self._unavailable()

    def render_frame(self, spec: dict, frame: int, out_path: str | Path) -> dict:
        self._unavailable()

    def render_preview(self, spec: dict, out_path: str | Path,
                       frames: int = 30) -> dict:
        self._unavailable()


# --------------------------------------------------------------------------
# §23 capability-driven backend router
# --------------------------------------------------------------------------

def all_backends() -> dict[str, SceneRenderer]:
    return {b.name: b for b in (RemotionRenderer(), FallbackRenderer())}


def select_backend(spec: dict, visual_backend: str = "auto") -> tuple[SceneRenderer, str]:
    """Pick a backend. auto honors spec.meta.backend_hint, then primary,
    then fallback. Explicit selections must be available."""
    backends = all_backends()
    hint = (spec.get("meta") or {}).get("backend_hint")
    if visual_backend != "auto":
        b = backends.get(visual_backend)
        if b is None:
            raise BackendUnavailable(f"unknown visual_backend {visual_backend!r}")
        if not b.available():
            raise BackendUnavailable(
                f"visual_backend={visual_backend!r} requested but unavailable"
            )
        return b, f"explicit visual_backend={visual_backend!r}"
    tried: list[str] = []
    for name in [hint, "remotion", "fallback"]:
        if not name or name in tried:
            continue
        tried.append(name)
        b = backends.get(name)
        if b is not None and b.available():
            if name == hint:
                return b, f"auto: meta.backend_hint={name!r} available"
            return b, (f"auto: hint {hint!r} not available/absent — "
                       f"selected primary {name!r}")
    raise BackendUnavailable(f"no available backend (tried order: {tried})")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _load(path: str) -> dict:
    return json.loads(Path(path).read_text())


def _main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="scene_renderer")
    ap.add_argument("command", choices=[
        "compile", "backend", "render", "preview", "frame", "capabilities",
    ])
    ap.add_argument("spec", nargs="?")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--frames", type=int, default=30)
    ap.add_argument("--frame", type=int, default=0)
    ap.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY)
    args = ap.parse_args(argv)

    if args.command == "capabilities":
        print(json.dumps({n: b.capabilities() for n, b in all_backends().items()},
                         indent=1))
        return 0

    if not args.spec:
        ap.error(f"{args.command} requires a spec path")

    spec = _load(args.spec)
    if args.command == "compile":
        props = compile_spec(spec)
        if args.out:
            Path(args.out).write_text(json.dumps(props, sort_keys=True, indent=1))
            print(f"wrote {args.out}")
        else:
            print(json.dumps(props, sort_keys=True, indent=1))
        return 0

    try:
        backend, reason = select_backend(spec, args.backend)
    except BackendUnavailable as exc:
        print(f"BACKEND_FAIL: {exc}", file=sys.stderr)
        return 3
    if args.command == "backend":
        print(f"backend={backend.name} reason={reason}")
        print(json.dumps(backend.capabilities(), indent=1))
        return 0

    if not args.out:
        ap.error(f"{args.command} requires an output path")
    if args.command == "render":
        result = backend.render(spec, args.out, concurrency=args.concurrency)
    elif args.command == "preview":
        result = backend.render_preview(spec, args.out, frames=args.frames)
    else:
        result = backend.render_frame(spec, args.frame, args.out)
    print(json.dumps(result, indent=1))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
