"""
voyager_trajectory.py — Manim scene: gravity-assist trajectory.

A stylized depiction of Voyager's path: Earth → Jupiter → Saturn →
out of the solar system, with the spacecraft as a glowing dot that
accelerates at each planetary slingshot.

Rendered at 1920x1080 30fps. Used by the stills-first mission pipeline.
"""

from manim import *


class VoyagerTrajectory(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        EARTH = "#3B82F6"
        JUPITER = "#FBBF24"
        SATURN = "#F59E0B"
        TRAIL = "#67E8F9"

        title = Text("A GRAVITY-ASSISTED JOURNEY", font_size=32, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        # Path: a curved trajectory from left to right
        path = CubicBezier(
            LEFT * 5.2 + DOWN * 1.0,
            LEFT * 1.5 + UP * 2.6,
            RIGHT * 1.5 + UP * 0.4,
            RIGHT * 5.2 + DOWN * 1.2,
        )
        self.play(Create(path), run_time=1.0)

        # Planets
        planets = [
            ("EARTH", LEFT * 5.2 + DOWN * 1.0, EARTH, 0.16),
            ("JUPITER", LEFT * 1.1 + UP * 1.9, JUPITER, 0.30),
            ("SATURN", RIGHT * 2.4 + UP * 0.2, SATURN, 0.26),
        ]
        planet_dots = []
        for label, pos, color, r in planets:
            d = Dot(pos, radius=r, color=color)
            t = Text(label, font_size=16, color=DIM)
            t.next_to(d, UP, buff=0.25)
            self.play(FadeIn(d), FadeIn(t), run_time=0.5)
            planet_dots.append((d, pos))

        # Spacecraft travels the path, accelerating at each slingshot
        craft = Dot(LEFT * 5.2 + DOWN * 1.0, radius=0.1, color=TRAIL)
        trail = TracedPath(craft.get_center, stroke_color=TRAIL,
                           stroke_width=4, stroke_opacity=[1, 0.25])
        self.add(craft, trail)

        def _segment_path(p, start, end, rate):
            return MoveAlongPath(p, path, run_time=end - start,
                                 rate_func=rate, lag_ratio=0)

        # Earth -> Jupiter (slow), Jupiter -> Saturn (faster), exit (fastest)
        self.play(MoveAlongPath(craft, path, run_time=2.6,
                                rate_func=lambda t: t * 0.32), run_time=2.6)
        # slingshot flash at Jupiter
        jup = planet_dots[1][1]
        ring = Circle(radius=0.4, stroke_color=JUPITER, stroke_width=3)
        ring.move_to(jup)
        ring.scale(0.1)
        self.play(FadeIn(ring), run_time=0.3)
        self.play(ring.animate.scale(3.0).set_opacity(0.2), run_time=0.5)
        self.remove(ring)

        self.play(MoveAlongPath(craft, path, run_time=2.8,
                                rate_func=lambda t: 0.32 + t * 0.42), run_time=2.8)
        sat = planet_dots[2][1]
        ring2 = Circle(radius=0.35, stroke_color=SATURN, stroke_width=3)
        ring2.move_to(sat)
        ring2.scale(0.1)
        self.play(FadeIn(ring2), run_time=0.3)
        self.play(ring2.animate.scale(3.0).set_opacity(0.2), run_time=0.5)
        self.remove(ring2)

        self.play(MoveAlongPath(craft, path, run_time=2.4,
                                rate_func=lambda t: 0.74 + t * 0.26), run_time=2.4)
        self.remove(trail)

        closing = Text("THREE PLANETS. ONE BOOST AFTER ANOTHER.", font_size=26, color=GREY)
        closing.to_edge(DOWN, buff=1.0)
        self.play(FadeIn(closing, shift=UP * 0.15), run_time=0.9)
        self.wait(1.2)
