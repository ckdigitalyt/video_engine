"""
horn_revolution.py — TRUE 3D Gabriel's Horn (surface of revolution).

Addresses the #1 blocker from every v0.2/v0.3 review of the math-motion
video: reviewers rejected the flat 2D curve ("this is a 3D paradox — a
2D curve kills the illusion") and mandated a rendered 3D revolved horn.

What this scene does:
  1. Renders the curve y = 1/x for x in [1, 4] as a 3D surface of
     revolution about the x-axis (a true revolution, not a flat slice).
  2. Animated pull-back: the curve sweeps into a horn, then the horn
     grows by extending the rotation with a dashed "infinite" tail
     fading to the horizon — visually selling "tapers forever".
  3. Wireframe + translucent surface so the finite volume reads as a
     filled interior (via the rotated profile) while the infinite
     surface reads via the tapering mesh — the painter's paradox.

Flat, CPU-cheap by manim standards (Surface with 2D grid), runs at
1080p30.  Rendered by the manim planner and spliced by the stills
pipeline for any topic the topic-classifier routes to a paradox /
surface-of-revolution math topic.
"""

from manim import (
    ThreeDScene, Surface, ThreeDAxes, Text, VGroup, PI, TAU,
    OUT, WHITE, BLUE, GREY_B, FadeIn, FadeOut, Create, Indicate,
    Write, Rotate, ORANGE,
)
import numpy as np

NAVY = "#16213E"
CYAN_C = "#22D3EE"
ORANGE_C = ORANGE
DEG = 180.0 / PI


class GabrielHorn3D(ThreeDScene):
    """True 3D surface of revolution for Gabriel's Horn."""

    def construct(self):
        self.camera.background_color = NAVY
        self.set_camera_orientation(phi=65 * DEG, theta=-45 * DEG)

        axes = ThreeDAxes(
            x_range=[0, 4.5, 1],
            y_range=[-2.2, 2.2, 1],
            z_range=[-2.2, 2.2, 1],
            x_length=6.5, y_length=4.0, z_length=4.0,
        )
        axes.set_opacity(0.35)
        self.play(Create(axes), run_time=0.8)

        # y = 1/x profile swept about the x-axis = surface of revolution.
        def horn_uv(u: float, v: float):
            x = 1.0 + 3.0 * u            # u in [0,1] -> x in [1, 4]
            r = 1.0 / max(x, 1e-4)       # radius shrinks as 1/x
            y = r * np.cos(TAU * v)
            z = r * np.sin(TAU * v)
            return np.array([x, y, z])

        horn = Surface(
            horn_uv,
            u_range=[0, 1], v_range=[0, 1],
            resolution=(24, 48),
            fill_opacity=0.45,
            fill_color=BLUE,
            stroke_color=CYAN_C,
            stroke_width=1.0,
        )
        self.play(Create(horn, lag_ratio=0.02), run_time=2.2)
        self.wait(0.4)

        # Infinite tail: extend the profile's reach with a faint tapered
        # "ear" that vanishes — sells "tapers forever".
        tail = Surface(
            lambda u, v: horn_uv(1.0 + 0.6 * u, v),  # x in [4, 7.6]
            u_range=[0, 1], v_range=[0, 1],
            resolution=(10, 36),
            fill_opacity=0.12,
            stroke_color=GREY_B,
            stroke_width=0.6,
        )
        self.play(FadeIn(tail), run_time=1.2)
        self.wait(0.3)

        # Labels: finite volume (fills to the top) vs infinite surface.
        vol = Text("FINITE VOLUME", font_size=30, color=CYAN_C)
        vol.move_to([2.4, 1.7, 1.2])
        self.play(Write(vol), run_time=0.9)
        self.play(Indicate(vol), run_time=0.6)

        surf = Text("INFINITE SURFACE", font_size=30, color=ORANGE_C)
        surf.move_to([4.6, 1.4, 0.4])
        self.play(Write(surf), run_time=0.9)
        self.play(Indicate(surf), run_time=0.6)

        # Fix the labels to screen orientation so they stay readable
        # while the camera rotates, then give the horn a slow arc so
        # the true 3D revolution reads clearly.
        self.camera.add_fixed_orientation_mobjects(vol, surf)
        self.play(Rotate(horn, angle=0.9, axis=OUT), run_time=1.5)
        self.begin_ambient_camera_rotation(rate=0.35)
        self.wait(3.0)

        self.play(FadeOut(VGroup(vol, surf, horn, tail, axes)), run_time=0.8)
        self.wait(0.2)
