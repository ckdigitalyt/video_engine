"""V14 Stage 6 — MAP_TRANSFORMATION grammar (directive §9).

Place transformation: one seeded procedural landmass rendered before → after
with a timed crossfade (no hard cut), bloom details on the after state,
change markers with callouts, slow push-in. The landmass geometry is shared
between states so only the transformation itself changes.
"""
from __future__ import annotations

import math
import random

from engine.grammars.base import (
    Grammar,
    GrammarError,
    animation,
    base_spec,
    camera_track,
    layer,
    leader_annotation,
    require,
    title_text,
)


def _blob_path(rng: random.Random, cx: float, cy: float, r: float,
               n: int = 18, wobble: float = 0.32) -> str:
    pts = []
    for i in range(n):
        a = 2 * math.pi * i / n
        rr = r * (1 + rng.uniform(-wobble, wobble))
        pts.append((cx + math.cos(a) * rr * 1.18, cy + math.sin(a) * rr * 0.78))
    d = f"M {pts[0][0]:.1f} {pts[0][1]:.1f}"
    for x, y in pts[1:]:
        d += f" L {x:.1f} {y:.1f}"
    return d + " Z"


class MapTransformation(Grammar):
    name = "MAP_TRANSFORMATION"
    summary = ("Place transformation: seeded procedural landmass before → after "
               "with a timed crossfade (no hard cut), bloom details + change "
               "markers with callouts; slow push-in.")

    def build(self, content: dict) -> dict:
        require(content, ["scene_id", "before", "after"], self.name)
        dur = float(content.get("duration_s", 7.0))
        seed = int(content.get("seed", 7))
        cf = float(content.get("crossfade_s", dur * 0.45))
        if not (0.5 <= cf <= dur - 0.5):
            raise GrammarError(f"{self.name}: crossfade_s must be within "
                               f"[0.5, {dur - 0.5:.1f}]")
        rng = random.Random(seed)
        cx, cy = content.get("center", [540.0, 980.0])
        r = float(content.get("radius", 360.0))
        before, after = content["before"], content["after"]
        d = _blob_path(rng, cx, cy, r)

        layers = []
        layers.append(layer("bg", "background", "world_ground",
                            "generated_gradient", depth=0.0, z=0,
                            payload={"kind": "radial",
                                     "stops": content.get("bg_stops",
                                                          ["#12405C", "#0A1D33"]),
                                     "focus": [0.5, 0.42]}))
        grat = {"lines": [{"x1": 90, "y1": 480 + i * 300, "x2": 990,
                           "y2": 480 + i * 300, "stroke": "#2A4E6E", "width": 2,
                           "opacity": 0.4, "dash": "3 14"} for i in range(4)]}
        layers.append(layer("graticule", "environment", "map_frame", "vector",
                            depth=0.0, z=8, payload={"primitives": grat}))
        layers.append(layer("map_before", "subject", "place_before", "vector",
                            depth=0.4, z=20,
                            payload={"primitives": {"paths": [
                                {"d": d, "fill": before.get("fill", "#4A5D6E"),
                                 "fill_opacity": 0.9, "stroke": "#E8EEF4",
                                 "width": 4}]}}))
        blooms = [{"x": cx + rng.uniform(-r, r) * 1.02,
                   "y": cy + rng.uniform(-r * 0.66, r * 0.66),
                   "r": rng.uniform(10.0, 30.0), "fill": "#F2A65A",
                   "fill_opacity": 0.85}
                  for _ in range(int(after.get("blooms", 12)))]
        after_prims = {"paths": [{"d": d, "fill": after.get("fill", "#3E7CB1"),
                                  "fill_opacity": 0.9, "stroke": "#E8EEF4",
                                  "width": 4}]}
        if blooms:
            after_prims["circles"] = blooms
        layers.append(layer("map_after", "subject", "place_after", "vector",
                            depth=0.4, z=22, payload={"primitives": after_prims}))
        for i, m in enumerate(content.get("markers", [])):
            mx, my = float(m["at"][0]), float(m["at"][1])
            layers.append(layer(f"marker_{i}", "secondary_subject",
                                "change_marker", "vector", depth=0.7, z=30,
                                visibility=[cf, dur],
                                payload={"primitives": {"circles": [
                                    {"x": mx, "y": my,
                                     "r": float(m.get("r", 46.0)),
                                     "fill": "none", "stroke": "#E8EEF4",
                                     "stroke_w": 3}]}}))
            layers.append(leader_annotation(f"callout_{i}", m["at"], m["title"],
                                            m.get("sub"),
                                            side=m.get("side", "left"),
                                            z=40 + i, visibility=[cf, dur]))
        layers.append(title_text("label_before", before.get("label", "BEFORE"),
                                 y=240.0, size=44.0, visibility=[0.0, cf]))
        layers.append(title_text("label_after", after.get("label", "AFTER"),
                                 y=240.0, size=44.0, visibility=[cf + 0.05, dur]))

        anims = [animation("map_after", "opacity",
                           [{"t": max(0.1, cf - 0.9), "value": 0.0},
                            {"t": cf, "value": 1.0}],
                           "crossfade shows the transformation without a hard cut")]
        camera = camera_track("push_in", [
            {"t": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
            {"t": dur,
             "scale": float(content.get("camera", {}).get("to_scale", 1.1)),
             "easing": "ease_in_out_cubic"},
        ], content.get("camera_purpose",
                       "draw the eye to the region that changes"))
        return base_spec(self.name, content, layers=layers, camera=camera,
                         animations=anims)
