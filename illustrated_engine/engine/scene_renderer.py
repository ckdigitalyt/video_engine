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
    FallbackRenderer  — PIL + FFmpeg compositor for the raster-cinematic
                        subset (raster plates, gradients, shape primitives,
                        opacity/position/scale animations, uniform-scale
                        cameras). Wired Stage 7; text/masks route to Remotion.

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
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw

try:
    from engine.asset_pipeline import stage_assets
    from engine.scene_ir import (
        normalize_scene_spec,
        spec_hash,
        validate_scene_spec,
    )
except ImportError:  # direct-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from engine.asset_pipeline import stage_assets
    from engine.scene_ir import (
        normalize_scene_spec,
        spec_hash,
        validate_scene_spec,
    )

RENDER_PROJECT = Path(__file__).resolve().parent / "remotion_project"
COMPOSITION_ID = "SceneIR"
DEFAULT_CONCURRENCY = 2  # bounded workers (directive §26)
RENDER_TIMEOUT_S = 900


def _source_version(paths: list) -> str:
    """sha16 over renderer source files — the §24 renderer-version component.
    Editing the compositor (SceneComposition.tsx, this module) must move
    every cache key; a constant version reused stale renders (V15 fix)."""
    h = hashlib.sha256()
    for p in paths:
        p = Path(p)
        h.update(p.name.encode())
        h.update(p.read_bytes() if p.is_file() else b"<missing>")
    return h.hexdigest()[:16]


_THIS = Path(__file__).resolve()
_FONT_DIR = _THIS.parent.parent / "assets" / "fonts"
_DEFAULT_FONTS = {"display": "BebasNeue-Regular.ttf", "body": "Inter-Variable.ttf"}


def _stage_fonts(fonts: dict) -> None:
    """Copy the bible's display/body TTFs to public/fonts/{display,body}.ttf
    (SceneComposition loads them via FontFace before frame 0). The font
    choice is in meta.fonts, so it is part of specHash -> cache-correct."""
    dest = RENDER_PROJECT / "public" / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    for role, default in _DEFAULT_FONTS.items():
        src = _FONT_DIR / (fonts.get(role) or default)
        if not src.is_file():
            src = _FONT_DIR / default
        out = dest / f"{role}.ttf"
        if not out.exists() or out.read_bytes() != src.read_bytes():
            shutil.copyfile(src, out)


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
        # V15: the story's bible palette (meta.palette, role -> hex) reaches
        # the renderer; None keeps the V14 default navy palette.
        "palette": (norm.get("meta") or {}).get("palette"),
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
            "version": _source_version(
                [_THIS] + sorted((RENDER_PROJECT / "src").glob("*.ts*"))),
            "animated_vector": True,
            "layered_composition": True,
            "continuous_camera": True,
            "masks_apertures": True,
            "text_annotations": True,
            "audio_layers": True,
            "raster_cinematic": True,
            "deterministic": True,
            "max_tested_scale_dive": 30,
            "notes": "generic SceneComposition; Stage 7 asset staging "
                     "(hash-verified copies under public/) wired",
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
        # Stage 7: manifest-referenced asset files hash-copy into public/
        # and payload.path rewrites to the served-relative path; the staged
        # spec is what compiles, so specHash binds asset content (§24).
        spec, _staged = stage_assets(spec, RENDER_PROJECT / "public")
        _stage_fonts((spec.get("meta") or {}).get("fonts") or {})
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
    """PIL + FFmpeg compositor for the raster-cinematic subset (§23 fallback).

    Serves scenes whose visual material is raster plates, generated gradients
    and shape primitives — the existing-asset-pipeline lane. Honest capability
    limits (§23): no text/annotation rendering, no mask apertures, no
    scale_dive camera — mask layers and unsupported cameras raise; auto
    routing sends those specs to Remotion. Supported: raster layers (fit
    cover/contain, payload.mask luminance cutouts — Stage 8 §15 depth bands),
    generated gradients, primitives payloads (rects,
    ellipses, circles, lines, straight-segment paths, polylines), per-layer
    opacity/position/scale animations, visibility windows, and the
    per-band-parallax cameras (§15: pf = 0.3 + 0.7*depth per layer,
    SceneComposition parity; static/push_in/pull_out/pan/travel plus the
    keyframe-driven reveal/focus_shift). Frames composite in PIL and pipe
    rawvideo to FFmpeg; asset staging reuses asset_pipeline.stage_assets so
    specHash binds asset content identically across backends.
    """

    name = "fallback"
    _SUPPORTED_CAMERAS = {"static", "push_in", "pull_out", "pan", "travel",
                          "reveal", "focus_shift"}

    def capabilities(self) -> dict:
        return {
            "available": True,
            "version": _source_version([_THIS]),
            "animated_vector": False,
            "raster_cinematic": True,
            "simple_diagram": True,
            "text_annotations": False,
            "masks_apertures": False,
            "raster_depth_masks": True,
            "per_band_parallax": True,
            "deterministic": True,
            "notes": "PIL+FFmpeg raster/gradient/primitive compositor with "
                     "raster luminance depth masks and per-band parallax; "
                     "scale_dive, aperture-mask and text render via remotion",
        }

    def available(self) -> bool:
        return shutil.which("ffmpeg") is not None

    def _require_ffmpeg(self) -> None:
        if not self.available():
            raise BackendUnavailable("FallbackRenderer requires ffmpeg on PATH")

    # ---- easing / interpolation --------------------------------------
    @staticmethod
    def _ease(u: float, name: str) -> float:
        u = max(0.0, min(1.0, u))
        if name == "ease_in_out_cubic":
            return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2
        if name == "ease_in_cubic":
            return u ** 3
        if name == "ease_out_cubic":
            return 1 - (1 - u) ** 3
        return u

    @staticmethod
    def _lerp(a, b, u):
        if isinstance(a, (list, tuple)):
            return [x + (y - x) * u for x, y in zip(a, b)]
        return a + (b - a) * u

    @staticmethod
    def _rgba(color, opacity: float = 1.0) -> tuple:
        c = str(color or "#E8EEF4").lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16),
                int(round(255 * max(0.0, min(1.0, opacity)))))

    # ---- camera -------------------------------------------------------
    def _camera_track(self, norm: dict, fps: int, dur: int) -> list[dict]:
        cam = norm["camera"]
        if cam["type"] not in self._SUPPORTED_CAMERAS:
            raise ValueError(
                f"FallbackRenderer: camera {cam['type']!r} not supported — "
                "scale_dive/aperture scenes render via the remotion backend")
        default_easing = cam.get("easing", "linear")
        kfs: list[dict] = []
        for kf in cam.get("keyframes", []):
            v = kf["value"]
            if isinstance(v, dict):
                s, x, y = (float(v.get("scale", 1.0)), float(v.get("x", 0.0)),
                           float(v.get("y", 0.0)))
            else:
                s, x, y = float(v), 0.0, 0.0
            kfs.append({"frame": int(round(float(kf["t"]) * fps)),
                        "scale": s, "x": x, "y": y,
                        "easing": kf.get("easing", default_easing)})
        if len(kfs) < 2:
            end = kfs[-1] if kfs else {"scale": 1.0, "x": 0.0, "y": 0.0}
            kfs = [dict(end, frame=0, easing=default_easing),
                   dict(end, frame=dur, easing=default_easing)]
        return kfs

    def _camera_at(self, kfs: list[dict], frame: int) -> tuple[float, float, float]:
        if frame <= kfs[0]["frame"]:
            k = kfs[0]
            return k["scale"], k["x"], k["y"]
        for a, b in zip(kfs, kfs[1:]):
            if a["frame"] <= frame <= b["frame"]:
                span = max(1, b["frame"] - a["frame"])
                # segment easing = START keyframe's easing (Remotion
                # evalCam parity: SceneComposition eases with a.easing)
                u = self._ease((frame - a["frame"]) / span,
                               a.get("easing", "linear"))
                return (self._lerp(a["scale"], b["scale"], u),
                        self._lerp(a["x"], b["x"], u),
                        self._lerp(a["y"], b["y"], u))
        k = kfs[-1]
        return k["scale"], k["x"], k["y"]

    # ---- per-layer animations ----------------------------------------
    @staticmethod
    def _anims_by_layer(norm: dict, fps: int) -> dict:
        out: dict[str, list[dict]] = {}
        for a in norm.get("animations", []):
            kfs = [{"frame": int(round(float(kf["t"]) * fps)),
                    "value": kf["value"],
                    "easing": kf.get("easing", "linear")}
                   for kf in a.get("keyframes", [])]
            out.setdefault(a["target_layer"], []).append(
                {"property": a.get("property", "opacity"), "keyframes": kfs})
        return out

    def _anim_at(self, anims: list[dict], prop: str, frame: int, default):
        for a in anims:
            if a["property"] != prop:
                continue
            kfs = a["keyframes"]
            if not kfs:
                return default
            if frame <= kfs[0]["frame"]:
                return kfs[0]["value"]
            for ka, kb in zip(kfs, kfs[1:]):
                if ka["frame"] <= frame <= kb["frame"]:
                    span = max(1, kb["frame"] - ka["frame"])
                    u = self._ease((frame - ka["frame"]) / span,
                                   ka.get("easing", "linear"))
                    return self._lerp(ka["value"], kb["value"], u)
            return kfs[-1]["value"]
        return default

    # ---- layer canvases (pre-rendered once) ---------------------------
    def _raster_canvas(self, lay: dict, p: dict, w: int, h: int) -> Image.Image:
        path = p.get("path")
        if not path:
            raise ValueError(
                f"layer {lay['id']!r}: raster payload has no path — resolve "
                "asset_id against the AssetManifest before rendering")
        cand = Path(path)
        if not cand.is_file():  # staged-relative path from stage_assets
            cand = RENDER_PROJECT / "public" / path
        if not cand.is_file():
            raise FileNotFoundError(f"layer {lay['id']!r} asset missing: {path}")
        img = Image.open(cand).convert("RGBA")
        sw, sh = img.size
        fit = p.get("fit", "cover")
        sc = max(w / sw, h / sh) if fit == "cover" else min(w / sw, h / sh)
        nw, nh = max(1, int(round(sw * sc))), max(1, int(round(sh * sc)))
        img = img.resize((nw, nh), Image.LANCZOS)
        left, top = (nw - w) // 2, (nh - h) // 2
        base = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if fit == "cover":
            base.alpha_composite(img.crop((left, top, left + w, top + h)))
        else:
            base.alpha_composite(img, (left, top))
        # Stage 8 (§15): depth-band layers carry a luminance mask cutout —
        # white = visible, mapped to the identical fit rect as the image.
        mask_p = p.get("mask")
        if mask_p:
            mcand = Path(mask_p)
            if not mcand.is_file():
                mcand = RENDER_PROJECT / "public" / mask_p
            if not mcand.is_file():
                raise FileNotFoundError(
                    f"layer {lay['id']!r} mask missing: {mask_p}")
            m = Image.open(mcand).convert("L").resize((nw, nh), Image.LANCZOS)
            mfull = Image.new("L", (w, h), 0)
            if fit == "cover":
                mfull.paste(m.crop((left, top, left + w, top + h)), (0, 0))
            else:
                mfull.paste(m, (left, top))
            base.putalpha(ImageChops.multiply(base.getchannel("A"), mfull))
        return base

    def _gradient_canvas(self, p: dict, w: int, h: int) -> Image.Image:
        stops = p.get("stops") or ["#0A1D33", "#12405C"]
        cols = [self._rgba(c) for c in stops]
        if len(cols) == 1:
            cols = [cols[0], cols[0]]
        if p.get("kind", "linear") == "radial":
            g = Image.radial_gradient("L")  # 0 at center -> 255 at edge
            gw, gh = int(w * 1.6), int(h * 1.6)
            g = g.resize((gw, gh), Image.BILINEAR)
            fx, fy = (p.get("focus") or [0.5, 0.42])
            mask = Image.new("L", (w, h), 255)
            mask.paste(g, (int(fx * w - gw / 2), int(fy * h - gh / 2)))
            flat0 = Image.new("RGBA", (w, h), cols[0])
            flat1 = Image.new("RGBA", (w, h), cols[-1])
            return Image.composite(flat1, flat0, mask)
        strip = Image.new("RGBA", (1, h))
        n = len(cols) - 1
        for y in range(h):
            seg = min(n - 1, int(y / h * n))
            u = (y / h * n) - seg
            strip.putpixel((0, y), tuple(int(a + (b - a) * u)
                                         for a, b in zip(cols[seg], cols[seg + 1])))
        return strip.resize((w, h), Image.BILINEAR)

    @staticmethod
    def _path_points(d_attr: str) -> tuple[list[tuple], bool]:
        """Parse 'M x y L x y ... Z' straight segments. Curves (C/Q/A) are
        out of fallback capability and abort the path silently-safe (empty)."""
        toks = d_attr.replace(",", " ").split()
        pts: list[tuple] = []
        closed = "Z" in d_attr.upper()
        i = 0
        while i < len(toks):
            t = toks[i]
            if t.upper() in ("M", "L", "Z"):
                if t.upper() == "Z":
                    break
                i += 1
                continue
            try:
                pts.append((float(t), float(toks[i + 1])))
            except (ValueError, IndexError):
                return [], closed  # unsupported curve segment
            i += 2
        return pts, closed

    @staticmethod
    def _fill_of(shape: dict, default=None):
        f = shape.get("fill", default)
        return None if f is None or str(f).strip().lower() == "none" else f

    @staticmethod
    def _stroke_of(shape: dict, default=None):
        s = shape.get("stroke", default)
        return None if s is None or str(s).strip().lower() == "none" else s

    def _shape_kwargs(self, shape: dict, fill_default=None) -> dict:
        """PIL draw kwargs mirroring SceneComposition paint semantics:
        fill/stroke "none" -> absent; outline width follows stroke_w."""
        kwargs: dict = {}
        f = self._fill_of(shape, fill_default)
        if f is not None:
            kwargs["fill"] = self._rgba(f, shape.get("fill_opacity", 0.85))
        s = self._stroke_of(shape)
        if s is not None:
            kwargs["outline"] = self._rgba(s, shape.get("opacity", 1.0))
            kwargs["width"] = int(shape.get("stroke_w", 2))
        return kwargs

    def _primitives_canvas(self, pr: dict, w: int, h: int) -> tuple[Image.Image, int]:
        """Mirror of SceneComposition renderPrimitives field names; SVG-style
        fill/stroke "none" resolves to no paint. Text nodes are
        capability-skipped and counted."""
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        for r in pr.get("rects", []):
            kw = self._shape_kwargs(r)
            if kw:
                d.rectangle([r["x"], r["y"], r["x"] + r.get("w", 0),
                             r["y"] + r.get("h", 0)], **kw)
        for e in pr.get("ellipses", []):
            kw = self._shape_kwargs(e)
            if kw:
                cx, cy = float(e["x"]), float(e["y"])
                rx, ry = float(e["rx"]), float(e["ry"])
                d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], **kw)
        for c in pr.get("circles", []):
            kw = self._shape_kwargs(c)
            if kw:
                cx, cy, r = float(c["x"]), float(c["y"]), float(c["r"])
                d.ellipse([cx - r, cy - r, cx + r, cy + r], **kw)
        for l in pr.get("lines", []):
            s = self._stroke_of(l, "#E8EEF4")
            if s is None:
                continue
            d.line([l["x1"], l["y1"], l["x2"], l["y2"]],
                   fill=self._rgba(s, l.get("opacity", 1.0)),
                   width=int(l.get("width", 3)))
        for pl in pr.get("polylines", []):
            s = self._stroke_of(pl, "#E8EEF4")
            pts = [tuple(float(v) for v in pair.split(","))
                   for pair in str(pl.get("points", "")).split()]
            if s is not None and len(pts) >= 2:
                d.line(pts, fill=self._rgba(s, pl.get("opacity", 1.0)),
                       width=int(pl.get("width", 4)), joint="curve")
        for q in pr.get("paths", []):
            pts, closed = self._path_points(str(q.get("d", "")))
            if not pts:
                continue
            f = self._fill_of(q, "none")
            if f is not None:
                d.polygon(pts, fill=self._rgba(f, q.get("fill_opacity", 1.0)))
            s = self._stroke_of(q)
            if s is not None:
                seq = pts + [pts[0]] if closed else pts
                d.line(seq, fill=self._rgba(s, q.get("opacity", 1.0)),
                       width=int(q.get("width", 3)), joint="curve")
        skipped = len(pr.get("texts", []))
        return img, skipped

    # ---- scene prep + frame composite ---------------------------------
    def _prepare_layers(self, norm: dict, fps: int,
                        w: int, h: int) -> tuple[list[dict], list[str]]:
        if any(l.get("type") == "mask" for l in norm["layers"]):
            raise ValueError(
                "FallbackRenderer: mask/aperture layers are out of capability "
                "— render scale_dive scenes via the remotion backend")
        anims_by_layer = self._anims_by_layer(norm, fps)
        prep: list[dict] = []
        skipped: list[str] = []
        for lay in sorted(norm["layers"], key=lambda l: l.get("z", 0)):
            src, p = lay.get("source"), lay.get("payload") or {}
            if src == "raster":
                canvas = self._raster_canvas(lay, p, w, h)
            elif src == "generated_gradient":
                canvas = self._gradient_canvas(p, w, h)
            elif src in ("vector", "generated_shape") and "primitives" in p:
                canvas, n_txt = self._primitives_canvas(p["primitives"], w, h)
                if n_txt:
                    skipped.append(f"{lay['id']} ({n_txt} text nodes)")
            else:
                skipped.append(lay["id"])
                continue
            vis = lay.get("visibility")
            v0, v1 = 0, 10 ** 9
            if vis:
                v0 = max(0, int(round(float(vis[0]) * fps)))
                v1 = max(v0 + 1, int(round(float(vis[1]) * fps)))
            prep.append({"id": lay["id"], "canvas": canvas,
                         "opacity": float(lay.get("opacity", 1.0)),
                         "position": [float(c) for c in lay.get("position", [0.0, 0.0])],
                         "scale": float(lay.get("scale", 1.0)),
                         "depth": float(lay.get("depth", 0.0)),
                         "screen_space": lay.get("type") in
                         ("semantic_annotation", "text"),
                         "v0": v0, "v1": v1,
                         "anims": anims_by_layer.get(lay["id"], [])})
        return prep, skipped

    def _composite_frame(self, prep: list[dict], cam_kfs: list[dict],
                         frame: int, w: int, h: int) -> Image.Image:
        """§15 per-band parallax: the camera distributes per layer by depth
        (pf = 0.3 + 0.7*depth, SceneComposition parity). Composing the band
        camera after the layer transform gives total = sc*sc_cam and offset
        sc_cam*pos + pan*pf, which reduces to the previous uniform behavior
        at pf = 1. Screen-space layers (pf = 0) ignore the camera."""
        s, px, py = self._camera_at(cam_kfs, frame)
        cx, cy = w / 2.0, h / 2.0
        world = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        for st in prep:
            if not (st["v0"] <= frame < st["v1"]):
                continue
            op = st["opacity"] * float(
                self._anim_at(st["anims"], "opacity", frame, 1.0))
            if op <= 0.005:
                continue
            pf = 0.0 if st["screen_space"] else 0.3 + 0.7 * max(
                0.0, min(1.0, st["depth"]))
            pos = list(st["position"])
            ap = self._anim_at(st["anims"], "position", frame, None)
            if ap is not None:
                pos = [pos[0] + float(ap[0]), pos[1] + float(ap[1])]
            sc = st["scale"] * float(
                self._anim_at(st["anims"], "scale", frame, 1.0))
            sc_cam = 1.0 + (s - 1.0) * pf
            total = sc * sc_cam
            tx = sc_cam * pos[0] + px * pf
            ty = sc_cam * pos[1] + py * pf
            img = st["canvas"]
            if total != 1.0 or tx != 0.0 or ty != 0.0:
                img = img.transform(
                    (w, h), Image.AFFINE,
                    (1.0 / total, 0.0, cx - (cx + tx) / total,
                     0.0, 1.0 / total, cy - (cy + ty) / total),
                    resample=Image.BILINEAR)
            if op < 0.995:
                img = img.copy()
                img.putalpha(img.getchannel("A").point(
                    lambda v, _op=op: int(v * _op + 0.5)))
            world.alpha_composite(img)
        return world

    @staticmethod
    def _result(out: Path, secs: float, spec: dict, skipped: list[str],
                n_frames: int) -> dict:
        res: dict[str, Any] = {
            "backend": "fallback",
            "spec_hash": spec_hash(normalize_scene_spec(spec)),
            "ok": True,
            "seconds": round(secs, 1),
            "out": str(out),
            "frames": n_frames,
        }
        if skipped:
            res["skipped_layers"] = skipped
        if out.exists():
            res["md5"] = hashlib.md5(out.read_bytes()).hexdigest()
            res["bytes"] = out.stat().st_size
        return res

    def _ffmpeg_pipe(self, out: Path, w: int, h: int, fps: int):
        return subprocess.Popen(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo",
             "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-",
             "-c:v", "libx264", "-preset", "medium", "-crf", "18",
             "-pix_fmt", "yuv420p", str(out)],
            stdin=subprocess.PIPE)

    def _render_frames(self, spec: dict, out_path: str | Path,
                       max_frames: int | None) -> dict:
        self._require_ffmpeg()
        ok, errors = self.validate(spec)
        if not ok:
            raise ValueError("invalid scene spec: " + "; ".join(errors[:5]))
        spec, _staged = stage_assets(spec, RENDER_PROJECT / "public")
        norm = normalize_scene_spec(spec)
        fps = int(round(float(norm["fps"])))
        w, h = int(norm["size"][0]), int(norm["size"][1])
        dur = max(1, int(round(float(norm["duration_s"]) * fps)))
        n_frames = dur if max_frames is None else min(dur, int(max_frames))
        t0 = time.time()
        cam_kfs = self._camera_track(norm, fps, dur)
        prep, skipped = self._prepare_layers(norm, fps, w, h)
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        proc = self._ffmpeg_pipe(out, w, h, fps)
        for f in range(n_frames):
            rgb = self._composite_frame(prep, cam_kfs, f, w, h).convert("RGB")
            proc.stdin.write(rgb.tobytes())
        proc.stdin.close()
        rc = proc.wait()
        res = self._result(out, time.time() - t0, spec, skipped, n_frames)
        res["ok"] = rc == 0
        return res

    def render(self, spec: dict, out_path: str | Path,
               concurrency: int = DEFAULT_CONCURRENCY) -> dict:
        return self._render_frames(spec, out_path, None)

    def render_preview(self, spec: dict, out_path: str | Path,
                       frames: int = 30) -> dict:
        return self._render_frames(spec, out_path, frames)

    def render_frame(self, spec: dict, frame: int, out_path: str | Path) -> dict:
        self._require_ffmpeg()
        ok, errors = self.validate(spec)
        if not ok:
            raise ValueError("invalid scene spec: " + "; ".join(errors[:5]))
        spec, _staged = stage_assets(spec, RENDER_PROJECT / "public")
        norm = normalize_scene_spec(spec)
        fps = int(round(float(norm["fps"])))
        w, h = int(norm["size"][0]), int(norm["size"][1])
        dur = max(1, int(round(float(norm["duration_s"]) * fps)))
        t0 = time.time()
        cam_kfs = self._camera_track(norm, fps, dur)
        prep, skipped = self._prepare_layers(norm, fps, w, h)
        out = Path(out_path).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        img = self._composite_frame(prep, cam_kfs, int(frame), w, h).convert("RGB")
        img.save(out)
        return self._result(out, time.time() - t0, spec, skipped, 1)


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
