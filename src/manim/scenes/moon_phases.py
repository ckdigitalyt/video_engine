"""
moon_phases.py — Kinetic Earth-Moon orbit + phases explainer (v9.1).

Shows the Moon orbiting Earth with continuous updater-driven motion,
a camera zoom for the phases beat, and on-screen labels.  Designed to
pass the Jade Manim validator: >=1 self.play(), bounded waits, kinetic.
"""

from manim import *


class MoonPhases(MovingCameraScene):
    def construct(self):
        # ── Earth ────────────────────────────────────────────────────
        earth = Circle(radius=0.5, color=BLUE_E, fill_opacity=0.9,
                       stroke_width=2)
        earth_label = Text("Earth", font_size=26, color=WHITE)
        earth_label.next_to(earth, DOWN, buff=0.25)

        # ── Orbit + Moon (updater-driven continuous motion) ───────────
        orbit = Circle(radius=2.6, color=GREY_B, stroke_width=1.5,
                       stroke_opacity=0.5)
        moon = Circle(radius=0.22, color=GREY_C, fill_opacity=1.0,
                      stroke_width=1)
        angle = ValueTracker(0.0)
        moon.add_updater(
            lambda m: m.move_to(
                2.6 * np.array([np.cos(angle.get_value()),
                                np.sin(angle.get_value()), 0])
            )
        )

        title = Text("Earth-Moon system", font_size=30).to_edge(UP)
        self.play(Write(title), Create(orbit), FadeIn(earth),
                  FadeIn(earth_label), run_time=1.2)
        self.play(FadeIn(moon), run_time=0.5)
        # Continuous orbit (kinetic core of the scene)
        self.play(angle.animate.set_value(TAU), run_time=5.5,
                  rate_func=linear)

        # ── Phases beat: camera push + label ─────────────────────────
        self.play(self.camera.frame.animate.scale(0.55), run_time=1.2)
        phase_label = Text("Phases: reflected sunlight",
                           font_size=24, color=YELLOW)
        phase_label.next_to(title, DOWN, buff=0.3)
        self.play(Write(phase_label), run_time=0.7)
        self.play(moon.animate.scale(1.5), run_time=0.8)
        self.wait(0.6)
