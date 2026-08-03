"""
black_hole_lensing.py — Manim scene: gravitational lensing at the event horizon.

A black hole bends the light of background stars around it (gravitational
lensing), and the event horizon marks the boundary where nothing escapes.
Factually safe labels; rendered 1920x1080@30.
"""

from manim import *


class BlackHoleLensing(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        HOLE = "#0B0B12"
        RING = "#FBBF24"     # photon ring (warm amber)
        DISK = "#F59E0B"     # accretion glow
        LENS = "#67E8F9"     # lensed light (cyan)
        STAR = "#FFFFFF"

        title = Text("GRAVITATIONAL LENSING", font_size=34, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        # Black hole: pure black sphere + thin photon ring
        hole = Circle(radius=1.0, color=HOLE, fill_color=HOLE, fill_opacity=1.0)
        hole.set_stroke(width=0)
        ring = Circle(radius=1.06, color=RING, stroke_width=3, fill_opacity=0)
        self.play(FadeIn(ring), FadeIn(hole), run_time=0.8)

        # Accretion disk glow (ellipse, warm)
        disk = Ellipse(width=4.6, height=1.5, color=DISK,
                       fill_color=DISK, fill_opacity=0.16, stroke_width=2)
        disk.rotate(-0.35)
        self.play(FadeIn(disk), run_time=0.7)

        # Background star field
        stars = VGroup()
        for i in range(26):
            s = Dot(radius=0.035, color=STAR)
            s.move_to(np.array([np.random.uniform(-7, 7),
                                np.random.uniform(-3.6, 3.6), 0]))
            stars.add(s)
        self.play(FadeIn(stars, run_time=0.6))

        # Lensed light: arcs bending around the hole
        arc_top = Arc(radius=2.6, start_angle=PI * 0.15, angle=PI * 0.7,
                      color=LENS, stroke_width=5)
        arc_bot = Arc(radius=2.6, start_angle=PI * 1.15, angle=PI * 0.7,
                      color=LENS, stroke_width=5)
        self.play(Create(arc_top), Create(arc_bot), run_time=1.4)

        # Slow rotation of disk + ring (cinematic)
        group = VGroup(hole, ring, disk)
        self.play(Rotate(group, angle=0.6, run_time=2.4),
                  Rotate(arc_top, angle=0.6, about_point=ORIGIN, run_time=2.4),
                  Rotate(arc_bot, angle=0.6, about_point=ORIGIN, run_time=2.4))

        label = Text("LIGHT BENDS AROUND THE HOLE", font_size=24, color=LENS)
        label.to_edge(DOWN, buff=1.4)
        self.play(FadeIn(label, shift=UP * 0.15), run_time=0.7)

        horizon = Text("EVENT HORIZON: NOTHING ESCAPES", font_size=22, color=GREY)
        horizon.to_edge(DOWN, buff=0.8)
        self.play(FadeIn(horizon, shift=UP * 0.15), run_time=0.7)

        self.wait(0.8)
        self.play(FadeOut(VGroup(title, group, arc_top, arc_bot, stars,
                                 label, horizon)), run_time=0.5)
