"""
sun_layers.py — Manim scene: the Sun's internal structure.

Core -> radiative zone -> convective zone -> photosphere, revealed as
concentric shells with labels.  Rendered 1920x1080@30.
"""

from manim import *


class SunLayers(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        CORE = "#FDE68A"
        RADIATIVE = "#FBBF24"
        CONVECTIVE = "#F59E0B"
        PHOTOSPHERE = "#F97316"

        title = Text("INSIDE THE SUN", font_size=34, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        layers = [
            ("CORE", 0.8, CORE, "15 million degrees"),
            ("RADIATIVE ZONE", 1.7, RADIATIVE, "energy crawls outward"),
            ("CONVECTIVE ZONE", 2.5, CONVECTIVE, "boiling plasma"),
            ("PHOTOSPHERE", 3.1, PHOTOSPHERE, "the surface we see"),
        ]

        circles = []
        for label, radius, color, note in layers:
            c = Circle(radius=radius, color=color,
                       fill_color=color, fill_opacity=0.55)
            self.play(FadeIn(c, scale=0.7), run_time=0.4)
            lab = Text(label, font_size=18, color=color)
            lab.shift(UP * (radius + 0.35))
            note_t = Text(note, font_size=13, color=DIM)
            note_t.next_to(lab, DOWN, buff=0.1)
            self.play(FadeIn(lab), FadeIn(note_t), run_time=0.3)
            circles.append(c)

        closing = Text("A FUSION REACTOR, 150 MILLION KM AWAY",
                       font_size=26, color=GREY)
        closing.to_edge(DOWN, buff=1.0)
        self.play(FadeIn(closing, shift=UP * 0.15), run_time=0.6)
        # keep the final hold SHORT (QA blocks frozen tails >= 2.5s)
        self.wait(0.6)
