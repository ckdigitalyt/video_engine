"""
voyager_scale.py — Manim scene: the distance to Voyager 1.

A cinematic scale comparison:
  Earth → Moon (1.3 light-seconds) → Sun (8.3 light-minutes) →
  Voyager 1 (22.9 light-hours) with a light-speed pulse racing outward.

Rendered at 1920x1080 30fps. Used by the mission pipeline as a first-class
visualization for the "distance" beat (mission: Manim for scale comparisons).
"""

from manim import *


class VoyagerScale(Scene):
    def construct(self):
        # ── Palette ───────────────────────────────────────────────────
        EARTH_BLUE = "#3B82F6"
        SUN_GOLD = "#FBBF24"
        VOYAGER_AMBER = "#F59E0B"
        PULSE_CYAN = "#67E8F9"
        TEXT_GREY = "#E5E7EB"
        DIM = "#9CA3AF"

        # ── Title ─────────────────────────────────────────────────────
        title = Text("THE DISTANCE TO VOYAGER 1", font_size=34, color=TEXT_GREY)
        title.to_edge(UP, buff=0.5)
        subtitle = Text("at the speed of light", font_size=22, color=DIM)
        subtitle.next_to(title, DOWN, buff=0.25)
        self.play(FadeIn(title, shift=DOWN * 0.2), FadeIn(subtitle), run_time=1.0)
        self.wait(0.4)

        # ── The scale bar ─────────────────────────────────────────────
        bar = Line(LEFT * 5.2, RIGHT * 5.2, stroke_width=2.5, color="#374151")
        bar.to_edge(DOWN, buff=2.2)
        self.play(Create(bar), run_time=1.0)

        # Logarithmic-ish anchor positions along the bar
        anchors = {
            "earth": (-5.2, 0.0),
            "moon": (-4.2, 1.3),
            "sun": (-2.4, 8.3),
            "voyager": (5.2, 22.9),
        }

        # ── Earth ─────────────────────────────────────────────────────
        earth = Dot(bar.get_left(), radius=0.16, color=EARTH_BLUE)
        earth_lab = Text("EARTH", font_size=20, color=TEXT_GREY)
        earth_lab.next_to(earth, DOWN, buff=0.25)
        self.play(FadeIn(earth), FadeIn(earth_lab), run_time=0.6)

        # ── Moon ──────────────────────────────────────────────────────
        moon_pos = bar.point_from_proportion(0.08)
        moon = Dot(moon_pos, radius=0.07, color="#9CA3AF")
        moon_lab = Text("MOON  ·  1.3 light-seconds", font_size=18, color=DIM)
        moon_lab.next_to(moon, UP, buff=0.3)
        pulse1 = self._pulse(moon, PULSE_CYAN)
        self.play(FadeIn(moon), FadeIn(moon_lab), run_time=0.5)
        self.play(pulse1, run_time=0.8)
        self.wait(0.3)

        # ── Sun ───────────────────────────────────────────────────────
        sun_pos = bar.point_from_proportion(0.27)
        sun = Dot(sun_pos, radius=0.22, color=SUN_GOLD)
        sun_lab = Text("SUN  ·  8.3 light-minutes", font_size=18, color=DIM)
        sun_lab.next_to(sun, UP, buff=0.3)
        pulse2 = self._pulse(sun, PULSE_CYAN)
        self.play(FadeIn(sun), FadeIn(sun_lab), run_time=0.5)
        self.play(pulse2, run_time=0.8)
        self.wait(0.3)

        # ── Voyager ───────────────────────────────────────────────────
        voy_pos = bar.get_right()
        voyager = Dot(voy_pos, radius=0.13, color=VOYAGER_AMBER)
        voy_lab = Text("VOYAGER 1  ·  22.9 LIGHT-HOURS", font_size=20, color=VOYAGER_AMBER)
        voy_lab.next_to(voyager, UP, buff=0.35)
        pulse3 = self._pulse(voyager, VOYAGER_AMBER, big=True)
        self.play(FadeIn(voyager), FadeIn(voy_lab), run_time=0.6)
        self.play(pulse3, run_time=1.0)
        self.wait(0.4)

        # ── The light-speed pulse journey ─────────────────────────────
        trail = TracedPath(voyager.get_center, stroke_color=VOYAGER_AMBER,
                           stroke_width=4, stroke_opacity=[1, 0.2])
        self.add(trail)
        # Pulse from Earth to Voyager along the bar
        pulse = Dot(earth.get_center(), radius=0.09, color=PULSE_CYAN)
        self.add(pulse)
        self.play(
            pulse.animate.move_to(voy_pos),
            run_time=2.2,
            rate_func=linear,
        )
        self.remove(pulse)

        # ── Closing line ──────────────────────────────────────────────
        closing = Text("AND IT IS STILL CALLING HOME", font_size=30, color=TEXT_GREY)
        closing.to_edge(DOWN, buff=1.1)
        self.play(FadeIn(closing, shift=UP * 0.15), run_time=0.9)
        self.wait(1.2)

    def _pulse(self, target: Dot, color: str, big: bool = False):
        radius = 0.35 if big else 0.22
        ring = Circle(radius=radius, stroke_color=color, stroke_width=2.5)
        ring.move_to(target.get_center())
        ring.scale(0.1)
        return Succession(
            FadeIn(ring),
            ring.animate.scale(2.4).set_opacity(0.2),
            FadeOut(ring),
        )
