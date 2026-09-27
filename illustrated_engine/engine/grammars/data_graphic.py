"""V14 Stage 6 — DATA_GRAPHIC grammar (directive §9).

Data-first scene: bars or line chart computed from story values (geometry is
generated, not a fixed template), staggered per-mark reveal timed for
narration, callout on the key data point, subtle push-in camera.
"""
from __future__ import annotations

from engine.grammars.base import (
    COOL,
    INK,
    INK_DIM,
    LINE,
    WARM,
    Grammar,
    GrammarError,
    base_spec,
    camera_track,
    layer,
    leader_annotation,
    require,
    title_text,
)

X0, X1, Y_BASE, Y_TOP = 150.0, 930.0, 1450.0, 550.0


def _fmt(v) -> str:
    return f"{float(v):g}"


class DataGraphic(Grammar):
    name = "DATA_GRAPHIC"
    summary = ("Data-first scene: bars or line chart computed from story "
               "values with staggered narration-timed reveal, callout on the "
               "key data point; subtle push-in.")

    def build(self, content: dict) -> dict:
        require(content, ["scene_id", "chart"], self.name)
        dur = float(content.get("duration_s", 7.0))
        chart = content["chart"]
        ctype = chart.get("type")
        if ctype not in ("bars", "line"):
            raise GrammarError(f"{self.name}: chart.type must be 'bars' or 'line'")
        values = chart.get("values")
        if not isinstance(values, list) or len(values) < 2:
            raise GrammarError(f"{self.name}: chart.values needs >= 2 entries")
        for v in values:
            if not isinstance(v, dict) or "value" not in v:
                raise GrammarError(f"{self.name}: each chart.values entry needs 'value'")

        layers = []
        layers.append(layer("bg", "background", "world_ground",
                            "generated_gradient", depth=0.0, z=0,
                            payload={"kind": "radial",
                                     "stops": chart.get("bg_stops", ["#12405C", "#0A1D33"]),
                                     "focus": [0.5, 0.42]}))
        vmax = float(chart.get("max") or max(float(v["value"]) for v in values) * 1.15)
        plot_h = Y_BASE - Y_TOP

        grid = [{"x1": X0, "y1": Y_BASE - plot_h * f, "x2": X1,
                 "y2": Y_BASE - plot_h * f, "stroke": LINE, "width": 2,
                 "opacity": 0.5, "dash": "4 10"} for f in (0.25, 0.5, 0.75)]
        grid += [{"x1": X0, "y1": Y_BASE, "x2": X1, "y2": Y_BASE,
                  "stroke": INK_DIM, "width": 3, "opacity": 0.8},
                 {"x1": X0, "y1": Y_TOP - 30, "x2": X0, "y2": Y_BASE,
                  "stroke": INK_DIM, "width": 3, "opacity": 0.8}]
        layers.append(layer("axis", "scientific_layer", "chart_axes", "vector",
                            depth=0.0, z=10,
                            payload={"primitives": {"lines": grid}}))

        mark_at = {}
        if ctype == "bars":
            n = len(values)
            colw = (X1 - X0) / n
            bw = colw * 0.6
            stagger = float(chart.get("stagger_s", 0.55))
            t0 = float(chart.get("reveal_start_s", 0.8))
            for i, v in enumerate(values):
                h = max(6.0, float(v["value"]) / vmax * plot_h)
                bx = X0 + (i + 0.5) * colw - bw / 2.0
                vis = [min(t0 + i * stagger, dur - 0.5), dur]
                prims = {
                    "rects": [{"x": bx, "y": Y_BASE - h, "w": bw, "h": h,
                               "fill": chart.get("fill", WARM),
                               "fill_opacity": 0.92, "rx": 6}],
                    "texts": [
                        {"x": bx + bw / 2, "y": Y_BASE - h - 24,
                         "text": _fmt(v["value"]), "size": 30, "fill": INK},
                        {"x": bx + bw / 2, "y": Y_BASE + 46,
                         "text": str(v.get("label", f"{i + 1}")), "size": 26,
                         "fill": INK_DIM, "weight": 400},
                    ],
                }
                layers.append(layer(f"bar_{i}", "scientific_layer", "data_mark",
                                    "vector", depth=0.2, z=20 + i,
                                    visibility=vis,
                                    payload={"primitives": prims}))
                mark_at[i] = (bx + bw / 2, Y_BASE - h)
        else:  # line
            n = len(values)
            pts = [(X0 + (X1 - X0) * (0.06 + 0.88 * i / (n - 1)),
                    Y_BASE - max(0.0, float(v["value"])) / vmax * plot_h)
                   for i, v in enumerate(values)]
            prims = {
                "polylines": [{"points": " ".join(f"{x:.1f},{y:.1f}" for x, y in pts),
                               "stroke": COOL, "width": 6}],
                "circles": [{"x": x, "y": y, "r": 10, "fill": WARM,
                             "stroke": INK, "stroke_w": 2}
                            for (x, y) in pts],
                "texts": [{"x": x, "y": Y_BASE + 46,
                           "text": str(values[i].get("label", f"{i + 1}")),
                           "size": 26, "fill": INK_DIM, "weight": 400}
                          for i, (x, _y) in enumerate(pts)],
            }
            layers.append(layer("line_series", "scientific_layer", "data_mark",
                                "vector", depth=0.2, z=20,
                                payload={"primitives": prims}))
            mark_at = {i: (x, y) for i, (x, y) in enumerate(pts)}

        for i, a in enumerate(content.get("annotations", [])):
            idx = int(a.get("index", 0))
            if idx not in mark_at:
                raise GrammarError(f"{self.name}: annotation index {idx} out of range")
            layers.append(leader_annotation(f"callout_{i}", mark_at[idx],
                                            a["title"], a.get("sub"),
                                            side=a.get("side", "left"), z=40 + i))
        layers.append(title_text("chart_title", content.get("title", ""),
                                 y=300.0, size=52.0))
        if content.get("sub"):
            layers.append(title_text("chart_sub", content["sub"], y=372.0,
                                     size=30.0, fill=INK_DIM, weight=400, z=44))
        if chart.get("unit"):
            layers.append(title_text("chart_unit", chart["unit"], y=Y_BASE + 110.0,
                                     size=26.0, fill=INK_DIM, weight=400, z=44))

        camera = camera_track("push_in", [
            {"t": 0.0, "scale": 1.0, "easing": "ease_in_out_cubic"},
            {"t": dur, "scale": float(content.get("camera", {})
                                      .get("to_scale", 1.06)),
             "easing": "ease_in_out_cubic"},
        ], content.get("camera_purpose",
                       "hold attention on the data without drifting"))
        return base_spec(self.name, content, layers=layers, camera=camera)
