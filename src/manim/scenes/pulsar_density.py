"""
pulsar_density.py — Manim scene: the impossible density of neutron stars.

A neutron star packs ~1.4 Suns into a 20 km sphere.  One teaspoon weighs
about a billion tons.  Compare against familiar objects.  1920x1080@30.
"""

from manim import *


class PulsarDensity(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        TEAL = "#2DD4BF"
        AMBER = "#FBBF24"

        title = Text("IMPOSSIBLY DENSE", font_size=34, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        # The city-sized star: 20 km across
        star_label = Text("A NEUTRON STAR: 20 KM ACROSS", font_size=22, color=AMBER)
        star_label.to_edge(DOWN, buff=2.2)
        self.play(FadeIn(star_label), run_time=0.6)

        star = Circle(radius=1.6, color=AMBER, fill_color=AMBER, fill_opacity=0.85)
        star.move_to(LEFT * 3.6)
        self.play(FadeIn(star, scale=0.5), run_time=0.8)

        # But it weighs 1.4 Suns
        sun_comp = Text("≈ 1.4× THE SUN'S MASS", font_size=20, color=DIM)
        sun_comp.next_to(star, DOWN, buff=0.3)
        self.play(FadeIn(sun_comp), run_time=0.6)

        # The teaspoon
        spoon = Rectangle(width=1.5, height=0.4, color=TEAL, fill_color=TEAL, fill_opacity=0.4)
        spoon.move_to(RIGHT * 3.6)
        spoon_lab = Text("ONE TEASPOON", font_size=18, color=TEAL)
        spoon_lab.next_to(spoon, UP, buff=0.3)
        self.play(FadeIn(spoon), FadeIn(spoon_lab), run_time=0.6)

        # Weight reveal
        weight = Text("WEIGHS ≈ 1 BILLION TONS", font_size=26, color=TEAL)
        weight.to_edge(DOWN, buff=1.2)
        self.play(FadeIn(weight, shift=UP * 0.15), run_time=0.8)

        # Comparison: mountains
        mt = Text("≈ THE WEIGHT OF ALL HUMANS COMBINED", font_size=20, color=DIM)
        mt.next_to(weight, UP, buff=0.15)
        self.play(FadeIn(mt), run_time=0.7)

        closing = Text("SPOONFULS OF A DYING STAR", font_size=24, color=GREY)
        closing.to_edge(DOWN, buff=0.5)
        self.play(FadeIn(closing, shift=UP * 0.1), run_time=0.6)
        self.wait(0.6)
