"""
Generic topic-agnostic Manim scenes (v12) — rendered once to
cache/manim/ and registered so ANY topic gets motion, not just the
space registry.  All scenes are flat, geometric, CPU-cheap at 1080p30.
"""
from manim import (
    Scene, Circle, Line, Arrow, Dot, Text, Rectangle, VGroup, Annulus,
    Angle, NumberLine, BarChart, Axes, Polygon, PI, TAU, DOWN, UP, LEFT,
    RIGHT, ORIGIN, RED, BLUE, GREEN, YELLOW, WHITE, GREY_B, GREY_D,
    FadeIn, FadeOut, Create, GrowFromCenter, GrowFromEdge, Transform,
    TransformFromCopy, Indicate, Rotate, Write, MoveToTarget, LaggedStart,
    rate_functions,
)

NAVY = "#16213E"
CYAN = "#22D3EE"
ORANGE = "#F47F3F"
LIME = "#A3E635"
SKIN = "#F0C4A8"
RED_SOFT = "#F87171"


# ── 1. Analog clock sweeping to "7" (seven hours / sleep / time) ────────
class ClockSeven(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        face = Circle(radius=2.2, color=WHITE, stroke_width=6)
        self.play(Create(face), run_time=0.8)
        ticks = VGroup()
        for k in range(12):
            a = TAU * k / 12
            inner = (1.9 * np_cos(a), 1.9 * np_sin(a), 0)
            outer = (2.05 * np_cos(a), 2.05 * np_sin(a), 0)
            ticks.add(Line(inner, outer, color=WHITE, stroke_width=4))
        self.play(FadeIn(ticks), run_time=0.6)
        center = Dot(ORIGIN, color=ORANGE, radius=0.08)
        self.play(FadeIn(center), run_time=0.3)
        hour = Line(ORIGIN, (0, 1.25, 0), color=CYAN, stroke_width=9)
        minute = Line(ORIGIN, (1.55, 0, 0), color=ORANGE, stroke_width=6)
        self.play(Create(hour), Create(minute), run_time=0.5)
        # sweep minute hand a full circle to the 12, hour to 7
        for step in range(60):
            self.play(
                Rotate(minute, angle=TAU / 60, about_point=ORIGIN),
                Rotate(hour, angle=TAU / 720, about_point=ORIGIN),
                run_time=0.05,
            )
        seven = Text("7", font_size=64, color=YELLOW).next_to(face, DOWN, buff=0.5)
        self.play(Write(seven), run_time=0.6)
        self.wait(0.8)


# ── 2. Brain waves (EEG-style sine pulses) ──────────────────────────────
class BrainWaves(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        ax = Axes(x_range=[0, 8, 1], y_range=[-1.6, 1.6, 1],
                  x_length=11, y_length=4).to_edge(DOWN, buff=0.7)
        waves = VGroup()
        colors = [CYAN, LIME, ORANGE, RED_SOFT]
        for i, col in enumerate(colors):
            w = ax.plot(
                lambda x, i=i: 1.1 * np_sin(2.1 * x + i * 1.3)
                + 0.35 * np_sin(4.7 * x + i),
                color=col, stroke_width=5,
            )
            waves.add(w)
        self.play(LaggedStart(*[Create(w) for w in waves], lag_ratio=0.35),
                  run_time=2.2)
        label = Text("gamma · beta · alpha · theta", font_size=34, color=WHITE)
        label.to_edge(UP, buff=0.6)
        self.play(Write(label), run_time=0.8)
        self.wait(1.0)


# ── 3. Growing bar chart (data beats: hours, %s, comparisons) ───────────
class GrowingBars(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        chart = BarChart(
            values=[4, 6, 8], bar_names=["too little", "enough", "ideal"],
            y_range=[0, 10, 2], bar_colors=[RED_SOFT, LIME, CYAN],
            bar_width=1.1, x_length=10, y_length=4.5,
        ).to_edge(DOWN, buff=0.8)
        chart.scale(0.85)
        self.play(Create(chart), run_time=1.2)
        self.play(chart.animate.change_bar_values([8, 8, 8]), run_time=1.4)
        note = Text("target: the goldilocks zone", font_size=30, color=YELLOW)
        note.next_to(chart, UP, buff=0.5)
        self.play(Write(note), run_time=0.7)
        self.wait(0.8)


# ── 4. Pulsing circle motif (heartbeat / rhythm / pulse) ────────────────
class PulseMotif(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        rings = VGroup()
        for r, col in zip([0.6, 1.0, 1.4, 1.8, 2.2],
                          [CYAN, LIME, ORANGE, RED_SOFT, WHITE]):
            rings.add(Circle(radius=r, color=col, stroke_width=5))
        self.play(LaggedStart(*[Create(c) for c in rings], lag_ratio=0.25),
                  run_time=1.8)
        core = Dot(ORIGIN, color=YELLOW, radius=0.18)
        self.play(FadeIn(core), run_time=0.4)
        for _ in range(3):
            self.play(core.animate.scale(1.6), run_time=0.35)
            self.play(core.animate.scale(1 / 1.6), run_time=0.35)
        self.wait(0.6)


# ── 5. Simple human figure waking/walking beat (Kurzgesagt-style) ───────
class FigureBeat(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        head = Circle(radius=0.42, color=SKIN, fill_opacity=1, stroke_width=0)
        head.move_to(UP * 2.1)
        body = Rectangle(width=1.5, height=1.6, color=ORANGE, fill_opacity=1,
                         stroke_width=0).move_to(UP * 0.4)
        leg_l = Line(ORIGIN + UP * 0.1, DOWN * 1.4 + LEFT * 0.35,
                     color=WHITE, stroke_width=12)
        leg_r = Line(ORIGIN + UP * 0.1, DOWN * 1.4 + RIGHT * 0.35,
                     color=WHITE, stroke_width=12)
        arm_l = Line(UP * 1.2 + LEFT * 0.55, UP * 0.35 + LEFT * 1.15,
                     color=WHITE, stroke_width=10)
        arm_r = Line(UP * 1.2 + RIGHT * 0.55, UP * 0.35 + RIGHT * 1.15,
                     color=WHITE, stroke_width=10)
        guy = VGroup(head, body, leg_l, leg_r, arm_l, arm_r)
        self.play(LaggedStart(*[GrowFromCenter(g) for g in
                                [head, body, leg_l, leg_r, arm_l, arm_r]],
                              lag_ratio=0.15), run_time=1.6)
        # walk-in-place sway
        for _ in range(4):
            self.play(guy.animate.shift(UP * 0.06), run_time=0.25)
            self.play(guy.animate.shift(DOWN * 0.06), run_time=0.25)
        label = Text("it's you", font_size=40, color=CYAN).next_to(guy, RIGHT, buff=1.2)
        self.play(Write(label), run_time=0.6)
        self.wait(0.6)


# ── 6. Circular cycle / loop (circadian, REM cycles, feedback loops) ─────
class CycleLoop(Scene):
    def construct(self):
        self.camera.background_color = NAVY
        ring = Annulus(inner_radius=1.35, outer_radius=1.75, color=CYAN,
                       fill_opacity=0.15, stroke_width=5)
        self.play(Create(ring), run_time=0.8)
        pts = VGroup()
        for i in range(4):
            a = TAU * i / 4
            p = Dot((1.55 * np_cos(a), 1.55 * np_sin(a), 0), color=ORANGE, radius=0.12)
            pts.add(p)
        self.play(LaggedStart(*[GrowFromCenter(p) for p in pts], lag_ratio=0.3),
                  run_time=1.4)
        arrows = VGroup()
        for i in range(4):
            a1 = TAU * i / 4
            a2 = TAU * (i + 1) / 4
            mid = (1.55 * np_cos((a1 + a2) / 2), 1.55 * np_sin((a1 + a2) / 2), 0)
            arrows.add(Arrow(ORIGIN, mid, color=WHITE, stroke_width=5,
                             max_tip_length_to_length_ratio=0.12))
        self.play(LaggedStart(*[GrowFromCenter(a) for a in arrows],
                              lag_ratio=0.2), run_time=1.2)
        self.wait(0.6)


def np_cos(x):
    from math import cos
    return cos(x)


def np_sin(x):
    from math import sin
    return sin(x)
