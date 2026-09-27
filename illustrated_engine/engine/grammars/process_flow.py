"""V14 Stage 6 — PROCESS_FLOW grammar (directive §9).

Stage-by-stage causal flow: nodes revealed in sequence down the frame with
arrow connectors, each node carrying one causal step of the beat; camera
drifts down with the flow. Reveal timing spreads the beat duration.
"""
from __future__ import annotations

from engine.grammars.base import (
    INK,
    INK_DIM,
    Grammar,
    GrammarError,
    base_spec,
    camera_track,
    layer,
    require,
    title_text,
)


def _fit(text: str, max_w: float, base: float) -> float:
    return max(18.0, min(base, max_w / (0.6 * max(1, len(str(text))))))


def _node_texts(cx: float, y: float, title: str) -> list:
    title = str(title)
    words = title.split()
    if len(title) <= 9 or len(words) < 2:
        return [{"x": cx, "y": y + 12, "text": title,
                 "size": _fit(title, 170.0, 34.0), "fill": INK}]
    mid = (len(words) + 1) // 2
    l1, l2 = " ".join(words[:mid]), " ".join(words[mid:])
    s = min(_fit(l1, 170.0, 32.0), _fit(l2, 170.0, 32.0))
    return [{"x": cx, "y": y - 8, "text": l1, "size": s, "fill": INK},
            {"x": cx, "y": y + 34, "text": l2, "size": s, "fill": INK}]


class ProcessFlow(Grammar):
    name = "PROCESS_FLOW"
    summary = ("Stage-by-stage causal flow: nodes revealed in sequence with "
               "arrow connectors, one causal step per node; camera drifts "
               "down with the flow.")

    def build(self, content: dict) -> dict:
        require(content, ["scene_id", "stages"], self.name)
        stages = content["stages"]
        if not isinstance(stages, list) or len(stages) < 2:
            raise GrammarError(f"{self.name}: content.stages needs >= 2 entries")
        dur = float(content.get("duration_s", 7.0))
        n = len(stages)
        cx = 540.0
        r = float(content.get("node_r", 96.0))
        y0, y1 = 470.0, 1470.0
        step = (y1 - y0) / (n - 1)

        layers = []
        layers.append(layer("bg", "background", "world_ground",
                            "generated_gradient", depth=0.0, z=0,
                            payload={"kind": "radial",
                                     "stops": content.get("bg_stops",
                                                          ["#12405C", "#0A1D33"]),
                                     "focus": [0.5, 0.45]}))
        for i, st in enumerate(stages):
            if not isinstance(st, dict) or "title" not in st:
                raise GrammarError(f"{self.name}: stage {i} needs 'title'")
            t_i = 0.0 if i == 0 else i * (dur - 1.2) / n
            vis = [min(t_i, dur - 0.5), dur]
            y = y0 + i * step
            if i > 0:
                y_prev = y0 + (i - 1) * step
                conn = {"paths": [
                    {"d": f"M {cx} {y_prev + r + 8:.1f} L {cx} {y - r - 26:.1f}",
                     "stroke": INK_DIM, "width": 4, "opacity": 0.7},
                    {"d": (f"M {cx - 16} {y - r - 44:.1f} L {cx} {y - r - 22:.1f} "
                           f"L {cx + 16} {y - r - 44:.1f}"),
                     "stroke": INK_DIM, "width": 4, "opacity": 0.7},
                ]}
                layers.append(layer(f"connector_{i}", "effect", "causal_link",
                                    "vector", depth=0.1, z=10 + i,
                                    visibility=vis,
                                    payload={"primitives": conn}))
            node = {"circles": [{"x": cx, "y": y, "r": r, "fill": "#12405C",
                                 "fill_opacity": 0.95, "stroke": INK,
                                 "stroke_w": 3}]}
            texts = _node_texts(cx, y, st["title"])
            if st.get("sub"):
                texts.append({"x": cx, "y": y + r + 44, "text": str(st["sub"]),
                              "size": 26, "fill": INK_DIM, "weight": 400})
            node["texts"] = texts
            layers.append(layer(f"stage_{i}", "subject", "process_stage",
                                "vector", depth=0.5, z=20 + i, visibility=vis,
                                payload={"primitives": node}))
        layers.append(title_text("flow_title", content.get("title", ""),
                                 y=240.0, size=50.0))

        camera = camera_track("travel", [
            {"t": 0.0, "scale": 1.04, "y": 0.0, "easing": "ease_in_out_cubic"},
            {"t": dur, "scale": 1.04, "y": min(140.0, (y1 - y0) * 0.12),
             "easing": "ease_in_out_cubic"},
        ], content.get("camera_purpose", "drift down with the causal flow"))
        return base_spec(self.name, content, layers=layers, camera=camera)
