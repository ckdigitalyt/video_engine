"""
sun_scale.py — Manim scene: Earth vs the Sun (scale comparison).

The classic scale gut-punch: ~1.3 million Earths could fit inside the Sun,
and sunlight takes 8 minutes to reach Earth.  Rendered 1920x1080@30.
"""

from manim import *


class SunScale(Scene):
    def construct(self):
        GREY = "#E5E7EB"
        DIM = "#9CA3AF"
        EARTH = "#3B82F6"
        SUN = "#FBBF24"
        CYAN = "#67E8F9"

        title = Text("HOW BIG IS THE SUN?", font_size=34, color=GREY)
        title.to_edge(UP, buff=0.5)
        self.play(FadeIn(title, shift=DOWN * 0.2), run_time=0.8)

        # Sun: big gold circle, left-ish
        sun = Circle(radius=2.6, color=SUN, fill_color=SUN, fill_opacity=0.85)
        sun.move_to(LEFT * 2.6)
        self.play(FadeIn(sun, scale=0.6), run_time=1.0)

        # Earth: tiny blue dot, right
        earth = Dot(LEFT * 2.6 + UP * 3.4, radius=0.07, color=EARTH)
        earth_lab = Text("EARTH", font_size=14, color=EARTH)
        earth_lab.next_to(earth, UP, buff=0.2)
        self.play(FadeIn(earth), FadeIn(earth_lab), run_time=0.6)

        # The reveal: Earths dropping in, counter climbing
        counter = Integer(0, font_size=40, color=CYAN)
        counter.next_to(sun, DOWN, buff=0.9)
        counter_label = Text("EARTHS WOULD FIT INSIDE", font_size=18, color=DIM)
        counter_label.next_to(counter, DOWN, buff=0.2)
        self.play(FadeIn(counter), FadeIn(counter_label), run_time=0.5)

        # Rain of tiny earths into the sun
        for _ in range(60):
            x = -2.6 + (self._rng_random() - 0.5) * 4.2
            y0 = 3.2 + (self._rng_random() - 0.5) * 1.4
            e = Dot([x, y0, 0], radius=0.03, color=EARTH)
            self.add(e)
            self.play(
                e.animate.move_to([x + (self._rng_random() - 0.5) * 0.6,
                                   y0 - 5.0, 0]),
                run_time=0.12,
            )
            self.remove(e)
            counter.increment_value(21900)
            if counter.get_value() >= 1300000:
                counter.set_value(1300000)
                break

        counter.set_value(1300000)
        fit_line = Text("1.3 MILLION EARTHS", font_size=36, color=CYAN)
        fit_line.to_edge(DOWN, buff=1.4)
        self.play(FadeIn(fit_line, shift=UP * 0.15), run_time=0.9)
        self.wait(0.5)

        # Light-travel beat
        self.play(FadeOut(fit_line), run_time=0.4)
        light_line = Text("ITS LIGHT TAKES 8 MINUTES TO REACH US",
                          font_size=28, color=GREY)
        light_line.to_edge(DOWN, buff=1.4)
        pulse = Dot(earth.get_center(), radius=0.05, color=CYAN)
        self.play(FadeIn(light_line, shift=UP * 0.15), run_time=0.7)
        self.play(FadeIn(pulse), run_time=0.3)
        self.play(pulse.animate.move_to(LEFT * 2.6).set_opacity(0.3), run_time=1.6)
        self.remove(pulse)
        self.wait(1.0)

    def _rng_random(self):
        import random
        return random.random()
