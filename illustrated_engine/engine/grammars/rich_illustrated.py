"""V14 Stage 6 — RICH_ILLUSTRATED_SCENE grammar (directive §9).

Hero-subject editorial scene: atmospheric world, one dominant procedural
subject (eye | cells | helix | circle | rings), optional secondary element,
leader-line callouts. Depth plan: bg 0.0 → atmosphere 0.25 → subject 0.8.
Camera: slow purposeful push-in (§16 continuous, no jump-cuts).
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
    title_text,
)

_SUBJECT_KINDS = ("eye", "cells", "helix", "circle", "rings")


def subject_layer(lid: str, subj: dict, *, depth: float, z: int) -> dict:
    kind = subj.get("kind", "circle")
    if kind not in _SUBJECT_KINDS:
        raise GrammarError(f"subject kind {kind!r} not supported (one of {_SUBJECT_KINDS})")
    if kind == "eye":
        p = {"shape": "eye", "iris_r": float(subj.get("iris_r", 210.0)),
             "pupil_r": float(subj.get("pupil_r", 64.0))}
        if "striations" in subj:
            p["striations"] = int(subj["striations"])
        src, ltype = "procedural_svg", "subject"
    elif kind == "cells":
        p = {"cells": int(subj.get("count", 12)),
             "junctions": bool(subj.get("junctions", True))}
        src, ltype = "procedural_svg", "subject"
    elif kind == "helix":
        p = {"helix": {"amplitude": float(subj.get("amplitude", 150.0)),
                       "period": float(subj.get("period", 110.0)),
                       "length": float(subj.get("length", 1400.0)),
                       "rungs_every": float(subj.get("rungs_every", 100.0))}}
        src, ltype = "procedural_svg", "subject"
    elif kind == "rings":
        cx, cy = subj.get("center", [540.0, 880.0])
        r0, n = float(subj.get("r", 130.0)), int(subj.get("count", 4))
        gap = float(subj.get("gap", 78.0))
        circles = [{"x": cx, "y": cy, "r": r0 + i * gap, "fill": "none",
                    "stroke": subj.get("stroke", "#E8EEF4"),
                    "stroke_w": float(subj.get("stroke_w", 5.0)),
                    "opacity": max(0.15, 0.85 - i * 0.18)} for i in range(n)]
        p, src, ltype = {"primitives": {"circles": circles}}, "vector", "subject"
    else:  # circle
        p = {"shape": "circle", "r": float(subj.get("r", 200.0))}
        for k in ("fill", "fill_opacity", "stroke", "stroke_w"):
            if k in subj:
                p[k] = subj[k]
        src, ltype = "generated_shape", "subject"
    return layer(lid, ltype, subj.get("role", "hero_subject"), src,
                 depth=depth, z=z, payload=p)


class RichIllustratedScene(Grammar):
    name = "RICH_ILLUSTRATED_SCENE"
    summary = ("Hero-subject editorial scene: atmospheric world, one dominant "
               "procedural subject (eye|cells|helix|circle|rings), optional "
               "secondary + leader callouts; slow purposeful push-in.")

    def build(self, content: dict) -> dict:
        from engine.grammars.base import require
        require(content, ["scene_id", "subject"], self.name)
        dur = float(content.get("duration_s", 7.0))
        layers, anims = [], []

        layers.append(layer("bg", "background", "world_ground",
                            "generated_gradient", depth=0.0, z=0,
                            payload={"kind": "radial",
                                     "stops": content.get("bg_stops", DEFAULT_STOPS),
                                     "focus": [0.5, 0.42]}))
        n_blobs = int(content.get("atmosphere_blobs", 4))
        if n_blobs > 0:
            layers.append(layer("atmosphere", "atmosphere", "ambient_motion",
                                "generated_shape", depth=0.25, z=10,
                                payload={"blobs": n_blobs,
                                         "opacity": [0.06, 0.14], "blur": 40.0}))
            anims.append(animation(
                "atmosphere", "position",
                [{"t": 0.0, "value": [0.0, 0.0]}, {"t": dur, "value": [30.0, -18.0]}],
                "slow ambient drift keeps the world alive without stealing focus"))
        if content.get("texture_squiggles"):
            layers.append(layer("texture", "texture", "hand_drawn_energy",
                                "procedural_svg", depth=0.45, z=15,
                                payload={"squiggles": int(content["texture_squiggles"])}))
        layers.append(subject_layer("subject", content["subject"], depth=0.8, z=20))
        if content.get("secondary"):
            layers.append(subject_layer("secondary", content["secondary"],
                                        depth=0.55, z=25))
        for i, a in enumerate(content.get("annotations", [])):
            layers.append(leader_annotation(
                f"callout_{i}", a["at"], a["title"], a.get("sub"),
                side=a.get("side", "left"), z=40 + i))
        title = content.get("title") or content["subject"].get("label")
        if title:
            layers.append(title_text("scene_title", title,
                                     y=float(content.get("title_y", 1780.0)),
                                     size=float(content.get("title_size", 46.0))))

        push = content.get("camera", {})
        camera = camera_track("push_in", [
            {"t": 0.0, "scale": float(push.get("from_scale", 1.0)),
             "easing": "ease_in_out_cubic"},
            {"t": dur, "scale": float(push.get("to_scale", 1.12)),
             "easing": "ease_in_out_cubic"},
        ], push.get("purpose", "settle the viewer onto the hero subject"))
        return base_spec(self.name, content, layers=layers, camera=camera,
                         animations=anims)
