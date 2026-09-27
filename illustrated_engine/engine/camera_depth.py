"""V14 Stage 8 — camera/depth/motion integration (directive §15–§17).

Depth: every layer lands in one of the §15 bands — background, midground,
subject, foreground, atmosphere. Annotation layers are screen-space and
camera-immune by type. Band depth drives the shared parallax formula
``pf = 0.3 + 0.7 * depth`` — identical in SceneComposition.tsx and
FallbackRenderer — so a far band drifts against the camera while the near
band rides it: per-band parallax, not uniform scaling.

Motion: the §15 move set maps onto Scene IR camera types plus layer
animations. push-in / pull-out / lateral travel / focus shift / subject
reveal are camera types. Occlusion, depth transition and scale transition
are deterministic motion PLANS composed from supported camera types and
layer animations with continuous per-keyframe easing — no new camera
types, no random motion, and every plan carries an explicit purpose the
validator enforces (§15).

Plate bridge: plate_depth_layers() runs the V13 M3 real-mask derivation
(depth_layers.derive_masks — rembg when importable and fast, deterministic
saliency otherwise) and splits one raster plate into BACKGROUND /
MIDGROUND / SUBJECT masked raster layers at band depths, so an AI image
becomes a camera subject with parallax depth instead of a flat card.
Masks ride payload.mask; stage_assets hash-stages them like any other
asset file (§24 groundwork). Derive on a working copy — mask PNGs land
beside the plate.

Continuity (§16): verify_camera_continuity() walks the compiled camera
path frame-by-frame through the FallbackRenderer interpolator (the same
keyframes the Remotion target receives) and flags tremble: per-frame
steps above a segment-relative bound, or integer-snapped camera values.
Continuity is a property of keyframes + easings, so proving it on the
Python side proves it for both backends.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from engine.grammars.base import animation, camera_track, layer
from engine.scene_ir import normalize_scene_spec

# §15 depth bands -> canonical depth. Parallax: pf = 0.3 + 0.7 * depth.
DEPTH_BANDS = {
    "background": 0.0,
    "midground": 0.35,
    "subject": 0.6,
    "foreground": 0.85,
    "atmosphere": 0.95,
}
ANNOTATION_BAND = "annotation"  # screen-space; camera-immune by type (§15)

_BAND_BY_TYPE = {
    "background": "background",
    "environment": "background",
    "subject": "subject",
    "primary_subject": "subject",
    "secondary_subject": "midground",
    "foreground": "foreground",
    "atmosphere": "atmosphere",
    "semantic_annotation": ANNOTATION_BAND,
    "text": ANNOTATION_BAND,
    "mask": ANNOTATION_BAND,  # aperture definition, not a camera layer
}
_ROLE_HINTS = (
    ("background", "background"),
    ("atmosphere", "atmosphere"), ("weather", "atmosphere"),
    ("dust", "atmosphere"), ("particles", "atmosphere"),
    ("world_ground", "background"), ("environment", "background"),
    ("sky", "background"), ("sea_floor", "background"),
    ("foreground", "foreground"), ("accent", "foreground"),
    ("frame", "foreground"), ("occluder", "foreground"),
    ("midground", "midground"),
    ("hero", "subject"), ("subject", "subject"), ("primary", "subject"),
    ("callout", ANNOTATION_BAND), ("label", ANNOTATION_BAND),
    ("leader", ANNOTATION_BAND), ("title", ANNOTATION_BAND),
    ("readout", ANNOTATION_BAND), ("annotation", ANNOTATION_BAND),
)


def parallax(depth) -> float:
    """Shared per-band parallax factor (SceneComposition.tsx parity)."""
    d = max(0.0, min(1.0, float(depth)))
    return 0.3 + 0.7 * d


def band_for(lay: dict) -> str:
    t = lay.get("type")
    if t in _BAND_BY_TYPE:
        return _BAND_BY_TYPE[t]
    role = str(lay.get("semantic_role", "")).lower()
    for needle, band in _ROLE_HINTS:
        if needle in role:
            return band
    return "midground"  # explicit default, reported in the plan


def plan_depths(spec: dict, apply: bool = False) -> dict:
    """Assign every layer a §15 depth band from type, then semantic_role
    (default midground). Deterministic. Returns
    ``{layer_id: {band, depth, source[, prior]}}``. Layers coupled to the
    camera by mechanism (payload.local_scale / grows_with_camera) are
    reported as camera_coupled and never rewritten. apply=True writes band
    depths back onto the layers (annotation layers keep depth 0.0 — they
    are camera-immune by type, not by depth)."""
    plan: dict = {}
    for lay in spec.get("layers", []):
        if not isinstance(lay, dict):
            continue
        lid = lay.get("id", "?")
        p = lay.get("payload") or {}
        if isinstance(p, dict) and (p.get("local_scale") is not None
                                    or p.get("grows_with_camera")):
            plan[lid] = {"band": band_for(lay),
                         "depth": float(lay.get("depth", 0.0)),
                         "source": "camera_coupled"}
            continue
        band = band_for(lay)
        depth = 0.0 if band == ANNOTATION_BAND else DEPTH_BANDS[band]
        plan[lid] = {"band": band, "depth": depth, "source": "inferred",
                     "prior": lay.get("depth")}
        if apply:
            lay["depth"] = depth
    return plan


# ---------------------------------------------------------------- plate bridge

def plate_depth_layers(plate_path, asset_id: str, *, z_base: int = 10,
                       fit: str = "cover", min_coverage: float = 0.005) -> list:
    """Split one raster plate into §15 depth-band layers via the V13 M3
    real-mask derivation. Returns raster layer dicts (background /
    midground / subject) sharing the plate, each with a payload.mask
    cutout at its band depth; bands with negligible mask coverage are
    skipped. Deterministic; raises loudly when derivation yields nothing
    usable (honest failure — no silent flat-card fallback)."""
    from engine.depth_layers import derive_masks
    plate_path = Path(plate_path)
    if not plate_path.is_file():
        raise FileNotFoundError(f"plate missing: {plate_path}")
    res = derive_masks(plate_path)
    masks = res.get("masks") or {}
    if not masks:
        raise RuntimeError(
            f"depth derivation produced no masks for {plate_path.name} "
            f"(method={res.get('method')!r}) — plate unusable for depth bands")
    bands = (("BACKGROUND", "background", "background", z_base),
             ("MIDGROUND", "midground", "secondary_subject", z_base + 1),
             ("SUBJECT", "subject", "subject", z_base + 2))
    layers = []
    for mask_name, band, ltype, z in bands:
        cov = float(res.get("coverage", {}).get(mask_name, 0.0))
        if cov < min_coverage:
            continue
        layers.append(layer(
            f"{asset_id}_{mask_name.lower()}", ltype, band, "raster",
            z=z, depth=DEPTH_BANDS[band],
            payload={"path": str(plate_path), "fit": fit,
                     "mask": masks[mask_name],
                     "depth_method": res.get("method"),
                     "mask_coverage": cov}))
    if not layers:
        raise RuntimeError(
            f"all derived masks for {plate_path.name} fall under "
            f"min_coverage={min_coverage} — no depth layers to build")
    return layers


# ------------------------------------------------------------- motion plans

def occlusion_plan(subject_id: str, occluder_id: str, duration_s: float, *,
                   enter=(0.0, 0.0), exit=(0.0, 0.0), frame_w: float = 1080.0,
                   depth_in: float = 1.0, depth_out: float = 1.08) -> dict:
    """§15 occlusion: a foreground-band element crosses IN FRONT of the
    subject while the camera pushes in — reveal through occlusion, not a
    cut. Place the occluder z-above the subject at foreground depth.
    Returns {"camera": ..., "animations": [...]}."""
    margin = float(frame_w)
    camera = camera_track("push_in", [
        {"t": 0.0, "scale": depth_in, "easing": "ease_in_out_cubic"},
        {"t": duration_s, "scale": depth_out, "easing": "ease_in_out_cubic"},
    ], f"push-in while {occluder_id} crosses in front of {subject_id} — "
       "reveal through occlusion (§15)")
    anims = [animation(occluder_id, "position", [
        {"t": 0.0, "value": [float(enter[0]) - margin, float(enter[1])],
         "easing": "ease_in_out_cubic"},
        {"t": duration_s, "value": [float(exit[0]) + margin, float(exit[1])],
         "easing": "ease_in_out_cubic"},
    ], f"{occluder_id} sweeps across the frame occluding {subject_id} (§15)")]
    return {"camera": camera, "animations": anims}


def depth_transition_plan(bg_ids: list, subject_id: str, duration_s: float, *,
                          depth_in: float = 1.0, depth_peak: float = 1.35,
                          depth_settle: float = 1.12,
                          bg_floor: float = 0.15) -> dict:
    """§15 depth transition (§17 transformation family): the camera dollies
    THROUGH the depth bands — background layers recede toward bg_floor as
    the subject band fills the frame. Story-driven: 'machine exterior →
    cutaway', 'map → landscape'. Returns {"camera":..., "animations":[...]}. """
    camera = camera_track("push_in", [
        {"t": 0.0, "scale": depth_in, "easing": "ease_in_out_cubic"},
        {"t": duration_s * 0.55, "scale": depth_peak,
         "easing": "ease_in_out_cubic"},
        {"t": duration_s, "scale": depth_settle, "easing": "ease_in_out_cubic"},
    ], f"dolly through depth bands onto {subject_id} — exterior resolves "
       "into interior (§15 depth transition, §17 transformation)")
    anims = []
    for bid in bg_ids:
        anims.append(animation(bid, "opacity", [
            {"t": 0.0, "value": 1.0, "easing": "ease_in_out_cubic"},
            {"t": duration_s * 0.55, "value": bg_floor,
             "easing": "ease_in_out_cubic"},
            {"t": duration_s, "value": bg_floor, "easing": "linear"},
        ], f"{bid} recedes as the camera passes into the subject band (§15)"))
    return {"camera": camera, "animations": anims}


def scale_transition_plan(small_id: str, large_id: str, duration_s: float, *,
                          small_to: float = 0.35, large_from: float = 0.4,
                          large_to: float = 1.2, cam_in: float = 1.06,
                          cam_out: float = 0.95) -> dict:
    """§15 scale transition (§17 'small quantity → huge comparison'): the
    small subject shrinks while the comparison element grows; the camera
    pulls out to hold both. Relative layer-scale multipliers, eased, never
    jump-cut. Returns {"camera":..., "animations":[...]}. """
    camera = camera_track("pull_out", [
        {"t": 0.0, "scale": cam_in, "easing": "ease_in_out_cubic"},
        {"t": duration_s, "scale": cam_out, "easing": "ease_in_out_cubic"},
    ], f"pull out to contain the {small_id} → {large_id} scale comparison "
       "(§15)")
    return {"camera": camera, "animations": [
        animation(small_id, "scale", [
            {"t": 0.0, "value": 1.0, "easing": "ease_in_out_cubic"},
            {"t": duration_s, "value": small_to, "easing": "ease_in_out_cubic"},
        ], f"{small_id} shrinks against the comparison (§15 scale transition)"),
        animation(large_id, "scale", [
            {"t": 0.0, "value": large_from, "easing": "ease_in_out_cubic"},
            {"t": duration_s, "value": large_to, "easing": "ease_in_out_cubic"},
        ], f"{large_id} grows to dominate the frame (§15 scale transition)"),
    ]}


# ---------------------------------------------------------------- §16 continuity

def _numeric_camera_path(renderer, norm: dict, fps: int, frames: int) -> tuple:
    """§16 continuity for camera types the fallback cannot composite
    (scale_dive): the SAME keyframe math as _camera_track/_camera_at applied
    numerically via the renderer's own easing/lerp — the Remotion target
    receives these same keyframes. Returns (kfs, path)."""
    cam = norm["camera"]
    default_easing = cam.get("easing", "linear")
    kfs = []
    for kf in cam.get("keyframes", []):
        v = kf.get("value")
        if isinstance(v, dict):
            s, x, y = (float(v.get("scale", 1.0)), float(v.get("x", 0.0)),
                       float(v.get("y", 0.0)))
        elif isinstance(v, (int, float)):
            s, x, y = float(v), 0.0, 0.0
        else:
            s = float(kf.get("scale", 1.0))
            x = float(kf.get("x", 0.0))
            y = float(kf.get("y", 0.0))
        kfs.append({"frame": int(round(float(kf["t"]) * fps)),
                    "scale": s, "x": x, "y": y,
                    "easing": kf.get("easing", default_easing)})
    kfs.sort(key=lambda k: k["frame"])
    if len(kfs) < 2:
        end = kfs[-1] if kfs else {"scale": 1.0, "x": 0.0, "y": 0.0,
                                   "easing": default_easing}
        kfs = [dict(end, frame=0), dict(end, frame=frames)]

    def _at(frame: int) -> tuple:
        if frame <= kfs[0]["frame"]:
            k = kfs[0]
            return k["scale"], k["x"], k["y"]
        for a, b in zip(kfs, kfs[1:]):
            if a["frame"] <= frame <= b["frame"]:
                span = max(1, b["frame"] - a["frame"])
                u = renderer._ease((frame - a["frame"]) / span,
                                   b.get("easing", "linear"))
                return (renderer._lerp(a["scale"], b["scale"], u),
                        renderer._lerp(a["x"], b["x"], u),
                        renderer._lerp(a["y"], b["y"], u))
        k = kfs[-1]
        return k["scale"], k["x"], k["y"]

    return kfs, [_at(f) for f in range(frames + 1)]


def verify_camera_continuity(spec: dict, renderer=None) -> dict:
    """§16 anti-jitter proof. Walks the compiled camera path frame-by-frame
    through the FallbackRenderer interpolator — the same keyframes the
    Remotion target receives — and flags:
    - cut: one frame consuming >4x the segment's per-frame average
    - jerk: frame-to-frame velocity changing faster than smooth eased motion
    - oscillation: signed steps flipping sign above the floor
    - integer snapping: a moving camera whose steps never go sub-pixel
    Cameras the fallback cannot composite (scale_dive) are verified on the
    same keyframe math applied numerically (track=numeric_keyframes).
    Returns {frames, max_step_scale, max_step_pan, jumps, float_continuous,
    track, ok}."""
    if renderer is None:
        from engine.scene_renderer import FallbackRenderer
        renderer = FallbackRenderer()
    norm = normalize_scene_spec(spec)
    fps = int(round(float(norm["fps"])))
    w = float(norm["size"][0])
    dur = float(norm.get("duration_s")
                or (norm.get("meta") or {}).get("duration_s")
                or spec.get("duration_s") or 0.0)
    if dur <= 0:
        raise ValueError("verify_camera_continuity: no meta.duration_s")
    frames = max(2, int(round(dur * fps)))
    try:
        kfs = renderer._camera_track(norm, fps, frames)
        path = [renderer._camera_at(kfs, f) for f in range(frames + 1)]
        track = "fallback_interpolator"
    except ValueError as exc:
        if "not supported" not in str(exc):
            raise
        kfs, path = _numeric_camera_path(renderer, norm, fps, frames)
        track = "numeric_keyframes"

    jumps = []
    max_ss = max_sp = 0.0
    for a, b in zip(kfs, kfs[1:]):
        f0, f1 = int(a["frame"]), int(b["frame"])
        span = max(1, f1 - f0)
        seg = path[f0:f1 + 1]
        for axis, kind, floor in ((0, "scale", 0.02),
                                  (1, "pan_x", 0.02 * w),
                                  (2, "pan_y", 0.02 * w)):
            vals = [p[axis] for p in seg]
            s_span = max(vals) - min(vals)
            if s_span <= 1e-9:
                continue
            ds = [vals[i + 1] - vals[i] for i in range(len(vals) - 1)]
            peak = max(abs(v) for v in ds)
            if axis == 0:
                max_ss = max(max_ss, peak)
            else:
                max_sp = max(max_sp, peak)
            avg = s_span / span
            # (1) cut: one frame consuming far more than an eased peak
            #     (cubic easings peak at 3x the per-frame average -> 4x headroom)
            for i, d in enumerate(ds):
                if abs(d) > max(4.0 * avg, floor):
                    jumps.append({"frame": f0 + i, "kind": kind,
                                  "step": round(abs(d), 5)})
            # (2) velocity discontinuity inside the segment (tremble/jerk);
            #     smooth eased paths vary velocity by ~4/n of peak per frame
            for i in range(len(ds) - 1):
                dvel = abs(ds[i + 1] - ds[i])
                if dvel > max(8.0 * peak / span, 1e-6):
                    jumps.append({"frame": f0 + i, "kind": f"{kind}_jerk",
                                  "step": round(dvel, 5)})
            # (3) oscillation: signed steps flipping sign above the floor
            for i in range(len(ds) - 1):
                if ds[i] * ds[i + 1] < 0 and min(abs(ds[i]), abs(ds[i + 1])) > floor:
                    jumps.append({"frame": f0 + i, "kind": f"{kind}_osc",
                                  "step": round(min(abs(ds[i]), abs(ds[i + 1])), 5)})
    moving = max_ss > 1e-9 or max_sp > 1e-9
    nonzero = [abs(b[i] - a[i]) for a, b in zip(path, path[1:])
               for i in range(3) if abs(b[i] - a[i]) > 1e-12]
    float_continuous = (all(isinstance(v, float) for p in path for v in p)
                        and (not moving or min(nonzero) < 1.0))
    return {"frames": frames + 1,
            "max_step_scale": round(max_ss, 6),
            "max_step_pan": round(max_sp, 6),
            "jumps": jumps,
            "float_continuous": float_continuous,
            "track": track,
            "ok": not jumps and float_continuous}


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.camera_depth")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("bands")
    p_plan = sub.add_parser("plan")
    p_plan.add_argument("spec")
    p_plan.add_argument("--apply", action="store_true")
    p_plan.add_argument("--out")
    p_ver = sub.add_parser("verify")
    p_ver.add_argument("spec")
    p_ver.add_argument("--out")
    args = ap.parse_args(argv)
    if args.cmd == "bands":
        print(json.dumps({"depth_bands": DEPTH_BANDS,
                          "annotation_band": ANNOTATION_BAND}, indent=1))
        return 0
    if args.cmd == "plan":
        spec = json.loads(Path(args.spec).read_text())
        plan = plan_depths(spec, apply=args.apply)
        payload = {"plan": plan}
        if args.apply:
            ok, errors = __import__(
                "engine.scene_ir", fromlist=["validate_scene_spec"]
            ).validate_scene_spec(spec)
            payload["validator"] = {"ok": ok, "errors": errors[:5]}
            if args.out:
                Path(args.out).write_text(json.dumps(spec, indent=1,
                                                     sort_keys=True))
        if args.out and not args.apply:
            Path(args.out).write_text(json.dumps(plan, indent=1))
        print(json.dumps(payload, indent=1))
        return 0
    spec = json.loads(Path(args.spec).read_text())
    report = verify_camera_continuity(spec)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
