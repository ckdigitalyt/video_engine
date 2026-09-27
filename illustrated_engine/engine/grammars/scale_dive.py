"""V14 Stage 6 — SCALE_DIVE grammar (directive §9).

Nested-world magnification dive: aperture mask + inner world riding the full
camera; stage labels switch with magnification bands; continuous scale_dive
camera with a live ×{S} readout. Mechanism proven in Stage 5 (example C).
"""
from __future__ import annotations

from engine.grammars.base import (
    DEFAULT_STOPS,
    Grammar,
    GrammarError,
    animation,
    base_spec,
    camera_track,
    layer,
    leader_annotation,
    mag_readout,
    require,
    stage_label,
    title_text,
)
from engine.grammars.rich_illustrated import subject_layer

_OUTER_KINDS = ("eye", "cells", "helix", "circle")
_INNER_KINDS = ("cells", "helix", "circle")


class ScaleDive(Grammar):
    name = "SCALE_DIVE"
    summary = ("Nested-world magnification dive: aperture + inner world riding "
               "full camera; magnification-band stage labels; live ×{S} readout; "
               "continuous scale_dive camera.")

    def build(self, content: dict) -> dict:
        require(content, ["scene_id", "dive", "stages"], self.name)
        dur = float(content.get("duration_s", 7.0))
        to_scale = float(content["dive"].get("to_scale", 30.0))
        outer = content.get("outer_subject", {"kind": "eye"})
        inner = dict(content.get("inner_subject", {"kind": "cells", "count": 12}))
        for label, s, allowed in (("outer_subject", outer, _OUTER_KINDS),
                                  ("inner_subject", inner, _INNER_KINDS)):
            if s.get("kind") not in allowed:
                raise GrammarError(
                    f"{self.name}: {label} kind {s.get('kind')!r} not supported "
                    f"(one of {allowed})")

        layers, anims = [], []
        layers.append(layer("bg", "background", "world_ground",
                            "generated_gradient", depth=0.0, z=0,
                            payload={"kind": "radial",
                                     "stops": content.get("bg_stops", DEFAULT_STOPS),
                                     "focus": [0.5, 0.42]}))
        n_blobs = int(content.get("atmosphere_blobs", 4))
        if n_blobs > 0:
            layers.append(layer("atmosphere", "atmosphere", "ambient_motion",
                                "generated_shape", depth=0.2, z=10,
                                payload={"blobs": n_blobs,
                                         "opacity": [0.05, 0.12], "blur": 44.0}))
            anims.append(animation(
                "atmosphere", "position",
                [{"t": 0.0, "value": [0.0, 0.0]}, {"t": dur, "value": [24.0, -14.0]}],
                "ambient drift keeps the observable world alive during the dive"))
        layers.append(subject_layer("outer_world", outer, depth=0.5, z=20))
        # Aperture between outer (z20) and inner (z40): everything world-space
        # above the mask is clipped to the growing reveal circle (§15 scale dive).
        layers.append(layer("aperture", "mask", "reveal_aperture", "vector",
                            z=30,
                            payload={"world_r": float(content.get("aperture_r", 430.0)),
                                     "grows_with_camera": True}))
        inner_layer = subject_layer("inner_world", inner, depth=0.95, z=40)
        inner_layer.setdefault("payload", {})["local_scale"] = float(
            inner.get("local_scale", 1.0))
        layers.append(inner_layer)
        layers.append(stage_label("stage_label", content["stages"]))
        layers.append(mag_readout("mag_readout",
                                  prefix=content.get("readout_prefix", "MAGNIFICATION")))
        for i, a in enumerate(content.get("annotations", [])):
            layers.append(leader_annotation(
                f"callout_{i}", a["at"], a["title"], a.get("sub"),
                side=a.get("side", "left"), z=45 + i))
        if content.get("title"):
            layers.append(title_text("scene_title", content["title"],
                                     y=float(content.get("title_y", 120.0)),
                                     size=float(content.get("title_size", 44.0))))

        camera = camera_track(
            "scale_dive", [
                {"t": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
                {"t": dur * 0.18, "scale": 1.05, "easing": "ease_in_out_cubic"},
                {"t": dur, "scale": to_scale, "easing": "ease_in_out_cubic"},
            ],
            content.get("camera_purpose",
                        "carry the viewer from observable scale into the micro world"),
            aperture_layers=["aperture"])
        return base_spec(self.name, content, layers=layers, camera=camera,
                         animations=anims)
