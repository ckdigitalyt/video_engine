"""
pulsar_lighthouse.py — Manim scene: the pulsar lighthouse beam.

A neutron star spinning ~30 times a second, sweeping twin beams of
radiation across space like a cosmic lighthouse.  Rendered 1920x1080@30.
"""

from manim import *


class PulsarLighthouse(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        STAR = "#FBBF24"
        BEAM = "#67E8F9"
        BEAM2 = "#A78BFA"

        title = Text("A COSMIC LIGHTHOUSE", font_size=34, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        # The neutron star: small, dense, blazing
        star = Circle(radius=0.55, color=STAR, fill_color=STAR, fill_opacity=0.9)
        star.move_to(LEFT * 3.2)
        glow = Circle(radius=0.8, color=STAR, fill_opacity=0.15)
        glow.move_to(star.get_center())
        self.play(FadeIn(glow), FadeIn(star), run_time=0.8)

        # Twin beams sweeping (rotation)
        beams = VGroup()
        for color, angle in ((BEAM, 0), (BEAM2, PI)):
            beam = Polygon(
                star.get_center() + 0.6 * np.array([np.cos(angle), np.sin(angle), 0]),
                star.get_center() + 6.0 * np.array([np.cos(angle + 0.18), np.sin(angle + 0.18), 0]),
                star.get_center() + 6.0 * np.array([np.cos(angle - 0.18), np.sin(angle - 0.18), 0]),
                color=color, fill_color=color, fill_opacity=0.25, stroke_width=0,
            )
            beams.add(beam)
        self.play(FadeIn(beams), run_time=0.6)

        # Rotate the whole star+beams rapidly (spinning neutron star)
        group = VGroup(star, glow, beams)
        self.play(
            Rotate(group, angle=2 * PI, about_point=star.get_center(), run_time=1.6),
            Rotate(group, angle=2 * PI, about_point=star.get_center(), run_time=1.6),
            Rotate(group, angle=2 * PI, about_point=star.get_center(), run_time=1.6),
        )

        # Label
        spin = Text("30 ROTATIONS EVERY SECOND", font_size=24, color=BEAM)
        spin.to_edge(DOWN, buff=1.4)
        self.play(FadeIn(spin, shift=UP * 0.15), run_time=0.7)

        self.play(FadeOut(group, shift=LEFT * 0.4), FadeOut(spin), run_time=0.5)

        # The beam reaching Earth
        earth = Dot(RIGHT * 4.5, radius=0.14, color="#3B82F6")
        earth_lab = Text("EARTH", font_size=16, color=DIM)
        earth_lab.next_to(earth, DOWN, buff=0.25)
        self.play(FadeIn(earth), FadeIn(earth_lab), run_time=0.5)

        star2 = Circle(radius=0.5, color=STAR, fill_color=STAR, fill_opacity=0.9)
        star2.move_to(LEFT * 3.2)
        sweep = Line(star2.get_center(), earth.get_center(), color=BEAM, stroke_width=6)
        sweep.set_opacity(0.0)
        self.add(star2, sweep)
        for _ in range(2):
            self.play(sweep.animate.set_opacity(0.9), run_time=0.5)
            self.play(sweep.animate.set_opacity(0.0), run_time=0.5)

        closing = Text("LIKE A BEACON IN THE DARK", font_size=26, color=GREY)
        closing.to_edge(DOWN, buff=1.0)
        self.play(FadeIn(closing, shift=UP * 0.15), run_time=0.7)
        self.wait(0.6)
