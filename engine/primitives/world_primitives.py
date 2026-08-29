"""Generic world primitives — the promoted visual language (v0.3 §6, §23).

The reusable visual language of MathMotion Lab v0.2, promoted into the
production engine as deterministic, state-aware, JSON-parameterized
primitives.  NO topic-specific constants live here.

Contract (same as engine.primitives.manim_primitives):
- Every primitive records ENTER/UPDATE/EXIT on the caller's SceneState.
- Deterministic: no RNG; positions derive from fixed math.
- Fail loud: invalid input raises ValueError — never a silent no-op.
- Temporaries are removed before the primitive returns.

Primitive families:
  physics   CelestialBody, OrbitPath, MovingBody, FallBody, AccelerateBody,
            CollideBodies, ImpactBurst, MissBody, CurvePath, FollowBody,
            TracePath, OscillateBody, VelocityVector, ForceVector,
            ReferenceFrame, ProjectilePath
  science   LightRay, LightSource, Wave, SignalPulse, ScatteringField (hero),
            ParticleField, CrossSection, RevealInside
  info      Node, Connection, FlowThrough, BranchFlow, MergeFlow, Timeline,
            CauseEffectChain, MeasureValue
  schematic EyeGlyph, EarGlyph, BrainGlyph, MouthGlyph (McGurk/psychology)
  narrative QuestionMark, ExperimentBadge, RevealText, PayoffText
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from manim import (
    DOWN, LEFT, ORIGIN, RIGHT, UP,
    Arrow, Circle, Create, DashedLine, Dot, FadeIn, FadeOut, GrowFromCenter,
    Indicate, Line, ParametricFunction, Polygon, Scene, Text, Transform,
    VGroup, ValueTracker, VMobject, there_and_back,
)

from engine.config.loader import get_style
from engine.primitives.layout import zone_offset
from engine.visuals.scene_state import SceneState, Zone


# ────────────────────────────────────────────────────────────────────────
# style helpers (same conventions as manim_primitives)
# ────────────────────────────────────────────────────────────────────────
def _color(key: str, fallback: str) -> str:
    return get_style().get(key, fallback)


def _accent(i: int) -> str:
    accents = get_style().get("accent_colors", ["#4FC3F7"])
    return accents[i % len(accents)]


def _font() -> str:
    return get_style().get("font_family", "DejaVu Sans")


def _motion_default(d: float | None, fallback: float) -> float:
    if d is not None and d > 0:
        return d
    return get_style().get("motion", {}).get("default_duration", fallback)


def _label(text: str, size: int = 26, color: str | None = None) -> Text:
    return Text(text, font=_font(), font_size=size,
                color=color or _color("secondary_text", "#9AA7B8"))


# ────────────────────────────────────────────────────────────────────────
# physics primitives
# ────────────────────────────────────────────────────────────────────────
def CelestialBody(scene: Scene, scene_state: SceneState, oid: str = "earth",
                  radius: float = 2.0, color: str = "#14375E",
                  limb_color: str = "#3A86D6", glow: float = 0.35,
                  label: str = "", duration: float | None = None) -> VGroup:
    """Central body: filled disc + limb glow + optional label (mm-lab
    make_earth promoted).  ENTER once, persists."""
    d = _motion_default(duration, 0.8)
    body = Circle(radius=radius, color=color, fill_opacity=0.95,
                  stroke_width=2)
    limb = Circle(radius=radius * 1.02, color=limb_color, stroke_width=4,
                  stroke_opacity=glow)
    group = VGroup(body, limb)
    group.move_to(zone_offset(Zone.CENTER))
    if label:
        lbl = _label(label, 24, _color("primary_text", "#F5F7FA"))
        lbl.next_to(group, DOWN, buff=0.25)
        group.add(lbl)
    existing = scene_state.get(oid)
    if existing is not None and existing.exit_beat is None:
        return existing.mobject
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "celestial_body", value=label, zone=Zone.CENTER,
                      persistent=True, mobject=group)
    scene_state.record_enter(oid)
    return group


def OrbitPath(scene: Scene, scene_state: SceneState, oid: str = "orbit",
              center: Sequence[float] = (0, 0, 0), radius: float = 3.4,
              color: str = "#9AA7B8", label: str = "",
              duration: float | None = None) -> ParametricFunction:
    """Parametric circular orbit path (mm-lab lap path promoted).  ENTER."""
    d = _motion_default(duration, 0.7)
    path = ParametricFunction(
        lambda t: [center[0] + radius * math.cos(2 * math.pi * t),
                   center[1] + radius * math.sin(2 * math.pi * t), 0],
        t_range=[0, 1], color=color, stroke_width=2.5)
    group: Any = path
    if label:
        lbl = _label(label, 22)
        lbl.move_to(path.point_from_proportion(0.02) + UP * 0.35)
        group = VGroup(path, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "orbit_path", value=label, zone=Zone.CENTER,
                      persistent=True, mobject=group)
    scene_state.record_enter(oid)
    return path


def MovingBody(scene: Scene, scene_state: SceneState, oid: str = "body",
               radius: float = 0.15, color: str = "#4FC3F7",
               position: Sequence[float] = (0, 0, 0),
               duration: float | None = None) -> Dot:
    """A moving actor dot (mm-lab Particle promoted).  ENTER."""
    d = _motion_default(duration, 0.4)
    dot = Dot(radius=radius, color=color)
    dot.move_to(position)
    scene.play(FadeIn(dot), run_time=d)
    scene_state.enter(oid, "moving_body", zone=Zone.CENTER, persistent=True,
                      mobject=dot)
    scene_state.record_enter(oid)
    return dot


def _move_along_path_linear(scene: Scene, mob, path, run_time: float,
                            rate: float = 1.0) -> None:
    """Linear-time path traversal (mm-lab lesson: never teleport; linear
    rate = real-time physics feel)."""
    from manim import MoveAlongPath
    scene.play(MoveAlongPath(mob, path, run_time=run_time,
                             rate_func=lambda t: t * rate), run_time=run_time)


def FollowBody(scene: Scene, scene_state: SceneState, oid: str,
               path: Any, run_time: float = 2.4,
               duration: float | None = None) -> Dot:
    """Move a body along a path at linear rate (no teleport).  UPDATE."""
    d = _motion_default(duration, run_time)
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"FollowBody: {oid!r} is not on stage")
    _move_along_path_linear(scene, obj.mobject, path, d)
    scene_state.update(oid, {"op": "follow"}, mobject=obj.mobject)
    scene_state.record_update(oid)
    return obj.mobject


def FallBody(scene: Scene, scene_state: SceneState, oid: str,
             drop_height: float = 3.0, g: float = 5.0,
             land_y: float = -2.0,
             duration: float | None = None) -> Dot:
    """Physics-accurate free fall: y(t) = y0 - ½ g t² with ease-in
    (mm-lab fall easing promoted).  UPDATE; ends at land_y."""
    d = _motion_default(duration, 2.0)
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"FallBody: {oid!r} is not on stage")
    start_y = obj.mobject.get_center()[1]
    t_fall = math.sqrt(2 * drop_height / g) if g > 0 else d

    def _y(t: float) -> float:
        frac = min(1.0, t / t_fall) if t_fall > 0 else 1.0
        # ease-in quadratic: free fall accelerates
        return start_y - drop_height * (frac * frac)

    def _updater(mob, dt: float) -> None:
        nonlocal_holder["t"] += dt
        mob.move_to([mob.get_center()[0], _y(nonlocal_holder["t"]), 0])

    nonlocal_holder: dict[str, float] = {"t": 0.0}
    obj.mobject.add_updater(_updater)
    scene.wait(d)
    obj.mobject.remove_updater(_updater)
    final = obj.mobject.get_center()
    obj.mobject.move_to([final[0], land_y, 0])
    scene_state.update(oid, {"op": "fall", "g": g}, mobject=obj.mobject)
    scene_state.record_update(oid)
    return obj.mobject


def AccelerateBody(scene: Scene, scene_state: SceneState, oid: str,
                   target_speed_label: str = "faster",
                   duration: float | None = None) -> Dot:
    """Visually accelerate a body: shrink its lap/path time by replaying
    position toward a target with increasing rate (UPDATE)."""
    d = _motion_default(duration, 1.2)
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"AccelerateBody: {oid!r} is not on stage")
    scene.play(Indicate(obj.mobject, color=_accent(2)), run_time=d * 0.4)
    scene_state.update(oid, {"op": "accelerate", "to": target_speed_label},
                       mobject=obj.mobject)
    scene_state.record_update(oid)
    return obj.mobject


def CollideBodies(scene: Scene, scene_state: SceneState,
                  oid_a: str, oid_b: str,
                  duration: float | None = None) -> None:
    """Bring two bodies together until they touch; record UPDATE on both."""
    d = _motion_default(duration, 1.0)
    a = scene_state.get(oid_a)
    b = scene_state.get(oid_b)
    if a is None or b is None or a.mobject is None or b.mobject is None:
        raise ValueError(f"CollideBodies: {oid_a!r}/{oid_b!r} not on stage")
    gap = (a.mobject.get_center() - b.mobject.get_center())
    dist = math.hypot(gap[0], gap[1]) or 1.0
    move = (gap / dist) * (dist - 0.4) / 2
    a.mobject.generate_target()
    a.mobject.target.shift(move)
    b.mobject.generate_target()
    b.mobject.target.shift(-move)
    scene.play(a.mobject.animate.shift(move), b.mobject.animate.shift(-move),
               run_time=d)
    scene_state.update(oid_a, {"op": "collide"}, mobject=a.mobject)
    scene_state.update(oid_b, {"op": "collide"}, mobject=b.mobject)
    scene_state.record_update(oid_a)
    scene_state.record_update(oid_b)


def ImpactBurst(scene: Scene, scene_state: SceneState,
                at: Sequence[float] = (0, 0, 0), radius: float = 0.5,
                color: str = "#FFB74D", label: str = "",
                duration: float | None = None) -> None:
    """Impact boom ring at a point (mm-lab impact ring promoted).  TEMP."""
    d = _motion_default(duration, 0.6)
    ring = Circle(radius=0.1, color=color, stroke_width=5)
    ring.move_to(at)
    scene.play(GrowFromCenter(ring), run_time=d * 0.6)
    ring2 = ring.copy().scale(radius / 0.1)
    ring2.set_stroke(opacity=0.0)
    scene.play(Transform(ring, ring2), run_time=d * 0.4)
    scene.play(FadeOut(ring), run_time=0.15)
    scene_state.enter("impact", "particle", zone=Zone.CENTER, persistent=False,
                      mobject=ring)
    scene_state.exit("impact")
    scene_state.record_enter("impact")
    scene_state.record_exit("impact")


def MissBody(scene: Scene, scene_state: SceneState, oid: str,
             target_oid: str, offset: float = 0.6,
             duration: float | None = None) -> Dot:
    """Body passes by a target (curves just past it) — 'keeps missing'
    (mm-lab 'orbit = falling but missing' promoted).  UPDATE."""
    d = _motion_default(duration, 1.8)
    obj = scene_state.get(oid)
    target = scene_state.get(target_oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"MissBody: {oid!r} not on stage")
    tgt = target.mobject.get_center() if target and target.mobject else ORIGIN
    start = obj.mobject.get_center()
    dx = tgt[0] - start[0]
    path = ParametricFunction(
        lambda t: [start[0] + dx * t,
                   start[1] + math.sin(math.pi * t) * offset * 0.6, 0],
        t_range=[0, 1])
    _move_along_path_linear(scene, obj.mobject, path, d)
    scene_state.update(oid, {"op": "miss"}, mobject=obj.mobject)
    scene_state.record_update(oid)
    return obj.mobject


def CurvePath(scene: Scene, scene_state: SceneState, oid: str,
              curve: Sequence[Sequence[float]], label: str = "",
              duration: float | None = None) -> None:
    """Draw a curved path segment (mm-lab curved arc promoted).  TEMP."""
    d = _motion_default(duration, 0.8)
    from manim import ArcBetweenPoints
    if len(curve) < 2:
        raise ValueError("CurvePath needs at least two points")
    arc = ArcBetweenPoints(curve[0], curve[-1], angle=0.6,
                           color=_accent(4), stroke_width=4)
    scene.play(FadeIn(arc), run_time=d)
    if label:
        lbl = _label(label, 22)
        lbl.move_to(arc.point_from_proportion(0.5) + UP * 0.35)
        scene.play(FadeIn(lbl), run_time=d * 0.4)
        arc = VGroup(arc, lbl)
    scene_state.enter(oid, "path", persistent=False, mobject=arc)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)


def TracePath(scene: Scene, scene_state: SceneState, oid: str,
              path: Any, color: str = "#4FC3F7", opacity: float = 0.35,
              duration: float | None = None) -> None:
    """Ghost trail: faded copy of a path revealed as the body moves
    (mm-lab ghost trail promoted).  TEMP."""
    d = _motion_default(duration, 0.5)
    ghost = path.copy().set_stroke(color=color, opacity=opacity, width=3.5)
    scene.play(FadeIn(ghost), run_time=d)
    scene_state.enter(f"{oid}_trail", "path", persistent=False, mobject=ghost)
    scene_state.exit(f"{oid}_trail")
    scene_state.record_enter(f"{oid}_trail")
    scene_state.record_exit(f"{oid}_trail")


def OscillateBody(scene: Scene, scene_state: SceneState, oid: str,
                  amplitude: float = 1.2, cycles: int = 3,
                  duration: float | None = None) -> Dot:
    """Sine oscillation about the body's current position (UPDATE)."""
    d = _motion_default(duration, 2.4)
    obj = scene_state.get(oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"OscillateBody: {oid!r} not on stage")
    x0 = obj.mobject.get_center()[0]
    y0 = obj.mobject.get_center()[1]

    def _updater(mob, dt: float) -> None:
        nonlocal_holder["t"] += dt
        tt = nonlocal_holder["t"]
        mob.move_to([x0 + amplitude * math.sin(2 * math.pi * cycles * tt / d),
                     y0, 0])

    nonlocal_holder: dict[str, float] = {"t": 0.0}
    obj.mobject.add_updater(_updater)
    scene.wait(d)
    obj.mobject.remove_updater(_updater)
    obj.mobject.move_to([x0, y0, 0])
    scene_state.update(oid, {"op": "oscillate"}, mobject=obj.mobject)
    scene_state.record_update(oid)
    return obj.mobject


def VelocityVector(scene: Scene, scene_state: SceneState, oid: str,
                   start: Sequence[float], end: Sequence[float],
                   label: str = "v", color: str = "#4FC3F7",
                   duration: float | None = None) -> Arrow:
    """Labeled velocity arrow (mm-lab labeled vector promoted).  TEMP."""
    d = _motion_default(duration, 0.6)
    arrow = Arrow(start, end, color=color, stroke_width=4, buff=0.05)
    scene.play(FadeIn(arrow), run_time=d)
    if label:
        lbl = _label(label, 24, color)
        lbl.next_to(arrow.get_center(), UP, buff=0.12)
        scene.play(FadeIn(lbl), run_time=d * 0.5)
        group: Any = VGroup(arrow, lbl)
    else:
        group = arrow
    scene_state.enter(f"{oid}_vec", "velocity_vector", persistent=False,
                      mobject=group)
    scene_state.exit(f"{oid}_vec")
    scene_state.record_enter(f"{oid}_vec")
    scene_state.record_exit(f"{oid}_vec")
    return arrow


def ForceVector(scene: Scene, scene_state: SceneState, oid: str,
                start: Sequence[float], end: Sequence[float],
                label: str = "g", color: str = "#E57373",
                duration: float | None = None) -> Arrow:
    """Labeled force arrow (gravity toward center).  TEMP."""
    return VelocityVector(scene, scene_state, oid, start, end,
                          label=label, color=color, duration=duration)


def ReferenceFrame(scene: Scene, scene_state: SceneState,
                   oid: str = "frame", width: float = 12.0,
                   height: float = 7.0, label: str = "",
                   duration: float | None = None) -> VGroup:
    """Axes grid reference frame (optional).  ENTER."""
    d = _motion_default(duration, 0.6)
    h = Line(LEFT * width / 2, RIGHT * width / 2, color="#3A4356")
    v = Line(DOWN * height / 2, UP * height / 2, color="#3A4356")
    grid = VGroup(h, v)
    for i in range(1, 5):
        grid.add(Line(LEFT * width / 2 + UP * (height / 6) * i,
                      RIGHT * width / 2 + UP * (height / 6) * i,
                      color="#22293A"))
        grid.add(Line(UP * height / 2 + LEFT * (width / 6) * i,
                      DOWN * height / 2 + LEFT * (width / 6) * i,
                      color="#22293A"))
    scene.play(FadeIn(grid), run_time=d)
    scene_state.enter(oid, "reference_frame", zone=Zone.CENTER,
                      persistent=True, mobject=grid)
    scene_state.record_enter(oid)
    return grid


def ProjectilePath(scene: Scene, scene_state: SceneState,
                   oid: str = "trajectory", launch: Sequence[float] = (0, 0, 0),
                   vx: float = 1.0, g: float = 5.0,
                   duration: float | None = None) -> ParametricFunction:
    """Ballistic arc under constant gravity (mm-lab ballistic_arc promoted).
    TEMP path; deterministic parabola."""
    d = _motion_default(duration, 0.8)
    t_flight = 2 * 0.0  # computed below from impact on ground y=launch_y-?:
    # parametric: x = vx t, y = ½ g t² (downward); flight until y returns
    # to launch height: t = 2*vy/g with vy chosen so the arc reads well.
    # For a visual arc we fix apex via vy = sqrt(2 g h_apex).
    h_apex = 2.2
    vy = math.sqrt(2 * g * h_apex)
    t_apex = vy / g
    t_flight = 2 * t_apex

    def _f(t: float):
        return [launch[0] + vx * t,
                launch[1] + vy * t - 0.5 * g * t * t, 0]

    path = ParametricFunction(_f, t_range=[0, t_flight],
                              color=_accent(1), stroke_width=3)
    scene.play(FadeIn(path), run_time=d)
    scene_state.enter(oid, "trajectory", persistent=False, mobject=path)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return path


# ────────────────────────────────────────────────────────────────────────
# science primitives
# ────────────────────────────────────────────────────────────────────────
def LightSource(scene: Scene, scene_state: SceneState, oid: str = "sun",
                position: Sequence[float] = (-6, 3, 0), radius: float = 0.45,
                label: str = "Sun", duration: float | None = None) -> Dot:
    """Light source glyph (white).  ENTER."""
    d = _motion_default(duration, 0.5)
    dot = Dot(radius=radius, color="#FFF3E0")
    dot.move_to(position)
    halo = Circle(radius=radius * 1.9, color="#FFF3E0", stroke_width=3,
                  stroke_opacity=0.4)
    group = VGroup(dot, halo)
    if label:
        lbl = _label(label, 22, "#FFF3E0")
        lbl.next_to(group, UP, buff=0.15)
        group.add(lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "light_source", zone=Zone.LEFT, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)
    return dot


def LightRay(scene: Scene, scene_state: SceneState, oid: str,
             start: Sequence[float], end: Sequence[float],
             color: str = "#FFFFFF", width: float = 4.0,
             label: str = "", duration: float | None = None) -> Line:
    """A light ray/beam (colored by wavelength).  TEMP."""
    d = _motion_default(duration, 0.6)
    ray = Line(start, end, color=color, stroke_width=width)
    scene.play(FadeIn(ray), run_time=d)
    group: Any = ray
    if label:
        lbl = _label(label, 20, color)
        lbl.next_to(ray.get_center(), UP, buff=0.1)
        scene.play(FadeIn(lbl), run_time=d * 0.4)
        group = VGroup(ray, lbl)
    scene_state.enter(oid, "light_ray", persistent=False, mobject=group)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return ray


def Wave(scene: Scene, scene_state: SceneState, oid: str = "wave",
         amplitude: float = 0.5, wavelength_units: float = 1.4,
         cycles: int = 3, color: str = "#4FC3F7", label: str = "",
         duration: float | None = None) -> ParametricFunction:
    """A traveling sine wave packet (sound/light wave glyph).  TEMP."""
    d = _motion_default(duration, 1.0)
    total_len = wavelength_units * cycles

    def _f(t: float):
        return [t * total_len - total_len / 2,
                amplitude * math.sin(2 * math.pi * cycles * t), 0]

    wave = ParametricFunction(_f, t_range=[0, 1], color=color,
                              stroke_width=3)
    group: Any = wave
    if label:
        lbl = _label(label, 20, color)
        lbl.next_to(wave, UP, buff=0.15)
        group = VGroup(wave, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "wave", persistent=False, mobject=group)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return wave


def SignalPulse(scene: Scene, scene_state: SceneState,
                source: Sequence[float], target: Sequence[float],
                oid: str = "pulse", color: str = "#BA68C8",
                duration: float | None = None) -> Dot:
    """A pulse traveling from source to target (signal flow).  TEMP."""
    d = _motion_default(duration, 1.2)
    pulse = Dot(radius=0.12, color=color)
    pulse.move_to(source)
    line = Line(source, target, color="#3A4356", stroke_width=2)
    scene.play(FadeIn(VGroup(line, pulse)), run_time=0.25)
    _move_along_path_linear(scene, pulse, line, d)
    scene.play(FadeOut(pulse), run_time=0.2)
    scene_state.enter(oid, "signal", persistent=False, mobject=pulse)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return pulse


def ParticleField(scene: Scene, scene_state: SceneState,
                  oid: str = "particles", n: int = 120,
                  center: Sequence[float] = (0, 0, 0), radius: float = 3.0,
                  colors: Sequence[str] | None = None,
                  duration: float | None = None) -> VGroup:
    """Deterministic particle field (positions from fixed math, no RNG).
    TEMP."""
    d = _motion_default(duration, 0.8)
    cols = colors or [_accent(0), _accent(1), _accent(4)]
    pts = VGroup()
    for i in range(n):
        # golden-angle spiral fill — deterministic, no RNG
        theta = i * 2.399963
        r = radius * math.sqrt(i / max(1, n))
        dot = Dot(radius=0.035, color=cols[i % len(cols)])
        dot.move_to([center[0] + r * math.cos(theta),
                     center[1] + r * math.sin(theta), 0])
        pts.add(dot)
    scene.play(FadeIn(pts), run_time=d)
    scene_state.enter(oid, "particle", persistent=False, mobject=pts)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return pts


def ScatteringField(scene: Scene, scene_state: SceneState,
                    oid: str = "scatter", molecule_at: Sequence[float] = (0, 0, 0),
                    blue_nm: float = 450.0, red_nm: float = 650.0,
                    n_rays: int = 8, label: str = "",
                    duration: float | None = None) -> VGroup:
    """HERO primitive: wavelength-dependent scattering (Rayleigh I ∝ 1/λ⁴).

    A white beam strikes a molecule; rays re-emit in all directions.
    Blue rays are drawn LONGER and THICKER (scattered ~4x more), red rays
    shorter and thinner, with the incoming beam's forward component
    depleted of blue — the central mechanism of "why the sky is blue"
    shown without any text.  Deterministic geometry (no RNG)."""
    from engine.validation.physics_verify import verify_rayleigh_ratio
    d = _motion_default(duration, 3.6)
    ratio_check = verify_rayleigh_ratio(blue_nm, red_nm)
    ratio = 4.3
    for c in ratio_check.checks:
        if c["name"] == "ratio_positive" and "ratio" in c["detail"]:
            try:
                ratio = float(c["detail"].split("ratio = ")[1].split()[0])
            except (IndexError, ValueError):
                pass
    blue_color = "#4FC3F7"
    red_color = "#E57373"
    white_color = "#F5F7FA"

    # molecule (scatterer)
    mol = Circle(radius=0.16, color=white_color, fill_opacity=0.9)
    mol.move_to(molecule_at)

    # incoming white beam from the left
    beam_in = Line(molecule_at + LEFT * 3.2, molecule_at + LEFT * 0.25,
                   color=white_color, stroke_width=5)
    scene.play(FadeIn(VGroup(mol, beam_in)), run_time=d * 0.12)
    scene_state.enter(oid, "scatterer", value="molecule",
                      zone=Zone.CENTER, persistent=True, mobject=mol)
    scene_state.record_enter(oid)

    # re-emission: rays at fixed angles (no RNG)
    rays = VGroup()
    blue_count = 0
    red_count = 0
    for i in range(n_rays):
        angle = math.pi * (i + 0.5) / n_rays  # 0..pi fan (forward hemisphere
        # is where the beam came from; scatter is mostly sideways/forward)
        is_blue = (i % 2 == 0)
        length = 2.4 * (ratio if is_blue else 1.0) / 2.0
        width = 5.0 if is_blue else 2.0
        color = blue_color if is_blue else red_color
        end = [molecule_at[0] + length * math.cos(angle),
               molecule_at[1] + length * math.sin(angle) - 0.4, 0]
        ray = Line(molecule_at + RIGHT * 0.2, end, color=color,
                   stroke_width=width, stroke_opacity=0.85)
        rays.add(ray)
        if is_blue:
            blue_count += 1
        else:
            red_count += 1

    scene.play(FadeIn(rays), run_time=d * 0.3)
    scene_state.enter(f"{oid}_rays", "particle", persistent=False,
                      mobject=rays)
    scene_state.record_enter(f"{oid}_rays")

    # forward beam: blue removed, red continues (sunset hint)
    beam_fwd = Line(molecule_at + RIGHT * 0.25, molecule_at + RIGHT * 3.2,
                    color=red_color, stroke_width=3.5, stroke_opacity=0.8)
    scene.play(FadeIn(beam_fwd), run_time=d * 0.2)
    scene_state.enter(f"{oid}_fwd", "light_ray", persistent=False,
                      mobject=beam_fwd)
    scene_state.record_enter(f"{oid}_fwd")

    # emphasize the blue fan (Indicate on blue rays)
    blue_rays = VGroup(*[r for i, r in enumerate(rays) if i % 2 == 0])
    scene.play(Indicate(blue_rays, color=blue_color), run_time=d * 0.2)

    if label:
        lbl = _label(label, 22, white_color)
        lbl.next_to(mol, DOWN, buff=0.5)
        scene.play(FadeIn(lbl), run_time=d * 0.15)
        rays.add(lbl)

    # cleanup: rays + forward beam leave; molecule persists
    scene.play(FadeOut(VGroup(rays, beam_fwd)), run_time=d * 0.12)
    scene_state.exit(f"{oid}_rays")
    scene_state.exit(f"{oid}_fwd")
    scene_state.record_exit(f"{oid}_rays")
    scene_state.record_exit(f"{oid}_fwd")
    return mol


def CrossSection(scene: Scene, scene_state: SceneState, oid: str,
                 target_oid: str, label: str = "",
                 duration: float | None = None) -> None:
    """Draw a cross-section slice through a target (cutaway).  TEMP."""
    d = _motion_default(duration, 1.0)
    obj = scene_state.get(target_oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"CrossSection: {target_oid!r} not on stage")
    c = obj.mobject.get_center()
    slice_line = DashedLine(c + DOWN * 1.6, c + UP * 1.6,
                            color=_accent(4), stroke_width=4)
    scene.play(FadeIn(slice_line), run_time=d * 0.5)
    if label:
        lbl = _label(label, 22, _accent(4))
        lbl.next_to(slice_line, RIGHT, buff=0.2)
        scene.play(FadeIn(lbl), run_time=d * 0.3)
        slice_line = VGroup(slice_line, lbl)
    scene_state.enter(f"{oid}_slice", "shape", persistent=False,
                      mobject=slice_line)
    scene_state.exit(f"{oid}_slice")
    scene_state.record_enter(f"{oid}_slice")
    scene_state.record_exit(f"{oid}_slice")


def RevealInside(scene: Scene, scene_state: SceneState, oid: str,
                 target_oid: str, inner: Any, label: str = "",
                 duration: float | None = None) -> None:
    """Reveal the inside of a target (cutaway reveal).  TEMP."""
    d = _motion_default(duration, 1.2)
    obj = scene_state.get(target_oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"RevealInside: {target_oid!r} not on stage")
    c = obj.mobject.get_center()
    inner.move_to(c)
    scene.play(FadeIn(inner), run_time=d * 0.5)
    if label:
        lbl = _label(label, 22)
        lbl.next_to(inner, DOWN, buff=0.3)
        scene.play(FadeIn(lbl), run_time=d * 0.3)
        inner = VGroup(inner, lbl)
    scene_state.enter(f"{oid}_inside", "shape", persistent=False,
                      mobject=inner)
    scene_state.exit(f"{oid}_inside")
    scene_state.record_enter(f"{oid}_inside")
    scene_state.record_exit(f"{oid}_inside")


def MediumLayer(scene: Scene, scene_state: SceneState,
                oid: str = "medium", width: float = 12.0, height: float = 1.3,
                y: float = 2.2, color: str = "#2E4A66", opacity: float = 0.28,
                label: str = "", duration: float | None = None) -> VGroup:
    """Atmosphere/medium layer: a translucent horizontal band the light
    passes through (sky-blue world).  ENTER, persists."""
    from manim import Rectangle
    d = _motion_default(duration, 0.6)
    band = Rectangle(width=width, height=height, fill_color=color,
                     fill_opacity=opacity, stroke_width=0)
    band.move_to([0, y, 0])
    group: Any = VGroup(band)
    if label:
        lbl = _label(label, 22, _color("secondary_text", "#9AA7B8"))
        lbl.next_to(band, UP, buff=0.15)
        group = VGroup(band, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "medium", value=label, zone=Zone.TOP,
                      persistent=True, mobject=group)
    scene_state.record_enter(oid)
    return band


# ────────────────────────────────────────────────────────────────────────
# information primitives
# ────────────────────────────────────────────────────────────────────────
def Node(scene: Scene, scene_state: SceneState, oid: str,
         position: Sequence[float], label: str = "", radius: float = 0.4,
         color: str = "#4FC3F7", duration: float | None = None) -> Circle:
    """A node glyph (network/flow).  ENTER."""
    d = _motion_default(duration, 0.5)
    node = Circle(radius=radius, color=color, stroke_width=3, fill_opacity=0.15)
    node.move_to(position)
    group: Any = node
    if label:
        lbl = _label(label, 22, color)
        lbl.next_to(node, DOWN, buff=0.15)
        group = VGroup(node, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "node", value=label, zone=Zone.CENTER,
                      persistent=True, mobject=group)
    scene_state.record_enter(oid)
    return node


def Connection(scene: Scene, scene_state: SceneState, oid: str,
               start: Sequence[float], end: Sequence[float],
               color: str = "#3A4356", duration: float | None = None) -> Line:
    """A connection line between nodes.  ENTER."""
    d = _motion_default(duration, 0.5)
    line = Line(start, end, color=color, stroke_width=3)
    scene.play(FadeIn(line), run_time=d)
    scene_state.enter(oid, "connection", zone=Zone.CENTER, persistent=True,
                      mobject=line)
    scene_state.record_enter(oid)
    return line


def FlowThrough(scene: Scene, scene_state: SceneState, oid: str,
                nodes: Sequence[dict], color: str = "#BA68C8",
                pulses: int = 3, duration: float | None = None) -> None:
    """Pulses traveling through an ordered chain of nodes (signal flow).
    TEMP pulses; nodes persist."""
    d = _motion_default(duration, 2.6)
    pts = [n["position"] for n in nodes]
    for i in range(pulses):
        for j in range(len(pts) - 1):
            delay = (i * 0.15)
            pulse = Dot(radius=0.1, color=color)
            pulse.move_to(pts[j])
            line = Line(pts[j], pts[j + 1], color="#3A4356", stroke_width=2)
            scene.play(FadeIn(VGroup(line, pulse)), run_time=0.08)
            _move_along_path_linear(scene, pulse, line,
                                    max(0.3, d / (pulses * (len(pts) - 1))))
            scene.play(FadeOut(pulse), run_time=0.05)
    scene_state.enter(f"{oid}_flow", "flow", persistent=False, mobject=Dot())
    scene_state.exit(f"{oid}_flow")
    scene_state.record_enter(f"{oid}_flow")
    scene_state.record_exit(f"{oid}_flow")


def BranchFlow(scene: Scene, scene_state: SceneState, oid: str,
               from_pos: Sequence[float], to_positions: Sequence[Sequence[float]],
               color: str = "#4FC3F7", duration: float | None = None) -> None:
    """One flow branches into many (deterministic angles).  TEMP."""
    d = _motion_default(duration, 1.6)
    lines = VGroup()
    for p in to_positions:
        lines.add(Line(from_pos, p, color=color, stroke_width=3))
    scene.play(FadeIn(lines), run_time=d * 0.4)
    scene_state.enter(f"{oid}_branch", "flow", persistent=False, mobject=lines)
    scene_state.exit(f"{oid}_branch")
    scene_state.record_enter(f"{oid}_branch")
    scene_state.record_exit(f"{oid}_branch")


def MergeFlow(scene: Scene, scene_state: SceneState, oid: str,
              from_positions: Sequence[Sequence[float]], to_pos: Sequence[float],
              color: str = "#81C784", duration: float | None = None) -> None:
    """Many flows merge into one.  TEMP."""
    d = _motion_default(duration, 1.6)
    lines = VGroup()
    for p in from_positions:
        lines.add(Line(p, to_pos, color=color, stroke_width=3))
    scene.play(FadeIn(lines), run_time=d * 0.4)
    scene_state.enter(f"{oid}_merge", "flow", persistent=False, mobject=lines)
    scene_state.exit(f"{oid}_merge")
    scene_state.record_enter(f"{oid}_merge")
    scene_state.record_exit(f"{oid}_merge")


def Timeline(scene: Scene, scene_state: SceneState, oid: str = "timeline",
             events: Sequence[dict] | None = None,
             duration: float | None = None) -> Line:
    """A horizontal timeline with event markers (spec §6 TIMELINE)."""
    d = _motion_default(duration, 1.6)
    events = events or []
    line = Line(LEFT * 4.5, RIGHT * 4.5, color="#9AA7B8", stroke_width=3)
    markers = VGroup(line)
    n = max(1, len(events))
    for i, ev in enumerate(events):
        x = -4.5 + 9.0 * (i / max(1, n - 1))
        dot = Dot(radius=0.09, color=_accent(i % 6))
        dot.move_to([x, 0, 0])
        markers.add(dot)
        if ev.get("label"):
            lbl = _label(str(ev["label"]), 20)
            lbl.next_to(dot, DOWN, buff=0.18)
            markers.add(lbl)
    scene.play(FadeIn(markers), run_time=d)
    scene_state.enter(oid, "timeline", zone=Zone.CENTER, persistent=True,
                      mobject=markers)
    scene_state.record_enter(oid)
    return line


def CauseEffectChain(scene: Scene, scene_state: SceneState,
                     links: Sequence[dict], oid: str = "cause_effect",
                     duration: float | None = None) -> None:
    """A ↓ B ↓ C chain (spec §5 relationship graph visual).  TEMP."""
    d = _motion_default(duration, 2.0)
    group = VGroup()
    y = 0.0
    for i, link in enumerate(links):
        lbl = _label(str(link.get("label", "?")), 26,
                     _accent(i % 6))
        lbl.move_to([0, y, 0])
        group.add(lbl)
        if i < len(links) - 1:
            arrow = Arrow([0, y - 0.35, 0], [0, y - 1.05, 0],
                          color="#9AA7B8", stroke_width=4)
            group.add(arrow)
        y -= 1.4
    scene.play(FadeIn(group), run_time=d * 0.6)
    # Honest TEMP lifecycle (see MeasureValue): the chain stays on stage
    # for its beat; the compiler's EXIT sweep removes it.
    scene_state.enter(oid, "cause_effect", persistent=False, mobject=group)
    scene_state.record_enter(oid)


def MeasureValue(scene: Scene, scene_state: SceneState, oid: str,
                 value: str, label: str = "", at: Sequence[float] = (0, 0, 0),
                 color: str = "#FFB74D", duration: float | None = None) -> Text:
    """A measured value with units (spec §4 measurements).  TEMP.

    Lifecycle is HONEST: the mobject is faded IN here and stays on stage
    for the rest of its beat; the compiler's next-beat EXIT sweep fades
    it out (exit_object) before any new text layer enters.  The previous
    version declared enter+exit in the same breath WITHOUT ever removing
    the pixels — so every measure/fill/compare stacked a new formula
    layer on top of the old one (the t≈13–33s garbled crossfade in the
    Gabriel's Horn -r3 render, 2026-08-27).
    """
    d = _motion_default(duration, 0.7)
    text = value if label == "" else f"{label}: {value}"
    mob = Text(text, font=_font(), font_size=30, color=color)
    mob.move_to(at)
    from engine.qa.fade import clamp_fade
    scene.play(FadeIn(mob, scale=1.3), run_time=clamp_fade(d))
    scene_state.enter(f"{oid}_measure", "measurement", value=text,
                      persistent=False, mobject=mob)
    scene_state.record_enter(f"{oid}_measure")
    return mob


# ────────────────────────────────────────────────────────────────────────
# schematic glyphs (psychology / McGurk — spec §6 human/psychology)
# ────────────────────────────────────────────────────────────────────────
def EyeGlyph(scene: Scene, scene_state: SceneState, oid: str = "eye",
             position: Sequence[float] = (-3, 1.5, 0), label: str = "eyes",
             duration: float | None = None) -> VGroup:
    """Schematic eye: almond + pupil.  ENTER."""
    d = _motion_default(duration, 0.6)
    almond = Circle(radius=0.5, color="#F5F7FA", stroke_width=3,
                    fill_opacity=0.08)
    pupil = Dot(radius=0.16, color="#0B0E14")
    pupil.set_fill("#4FC3F7", opacity=1)
    eye = VGroup(almond, pupil)
    eye.move_to(position)
    group: Any = eye
    if label:
        lbl = _label(label, 20)
        lbl.next_to(eye, DOWN, buff=0.15)
        group = VGroup(eye, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "eye", zone=Zone.LEFT, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)
    return eye


def EarGlyph(scene: Scene, scene_state: SceneState, oid: str = "ear",
             position: Sequence[float] = (-4.5, -1.5, 0), label: str = "ears",
             duration: float | None = None) -> VGroup:
    """Schematic ear: spiral-ish arc stack.  ENTER."""
    d = _motion_default(duration, 0.6)
    from manim import Arc
    ear = VGroup()
    for i, (r, ang) in enumerate([(0.45, 0.5), (0.32, 0.4), (0.2, 0.3)]):
        arc = Arc(radius=r, start_angle=ang, angle=math.pi * 1.6,
                  color="#F5F7FA", stroke_width=3)
        ear.add(arc)
    ear.move_to(position)
    group: Any = ear
    if label:
        lbl = _label(label, 20)
        lbl.next_to(ear, DOWN, buff=0.15)
        group = VGroup(ear, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "ear", zone=Zone.LEFT, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)
    return ear


def BrainGlyph(scene: Scene, scene_state: SceneState, oid: str = "brain",
               position: Sequence[float] = (0, 0, 0), label: str = "brain",
               duration: float | None = None) -> VGroup:
    """Schematic brain: two lobes + fold lines.  ENTER."""
    d = _motion_default(duration, 0.6)
    from manim import Ellipse
    left = Ellipse(width=1.1, height=1.5, color="#BA68C8", stroke_width=3,
                   fill_opacity=0.12)
    right = Ellipse(width=1.1, height=1.5, color="#BA68C8", stroke_width=3,
                    fill_opacity=0.12)
    left.shift(LEFT * 0.35)
    right.shift(RIGHT * 0.35)
    fold1 = Line(UP * 0.7, DOWN * 0.7, color="#BA68C8", stroke_width=2,
                 stroke_opacity=0.5)
    fold2 = Line(LEFT * 0.8, RIGHT * 0.8, color="#BA68C8", stroke_width=2,
                 stroke_opacity=0.5)
    brain = VGroup(left, right, fold1, fold2)
    brain.move_to(position)
    group: Any = brain
    if label:
        lbl = _label(label, 20, "#BA68C8")
        lbl.next_to(brain, DOWN, buff=0.18)
        group = VGroup(brain, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "brain", zone=Zone.CENTER, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)
    return brain


def MouthGlyph(scene: Scene, scene_state: SceneState, oid: str = "mouth",
               position: Sequence[float] = (3, 1.5, 0), label: str = "mouth",
               duration: float | None = None) -> VGroup:
    """Schematic mouth: two lip arcs (McGurk visual signal).  ENTER."""
    d = _motion_default(duration, 0.6)
    from manim import Arc
    upper = Arc(radius=0.55, start_angle=math.pi, angle=math.pi,
                color="#F5F7FA", stroke_width=4)
    lower = Arc(radius=0.55, start_angle=0, angle=math.pi,
                color="#F5F7FA", stroke_width=4)
    mouth = VGroup(upper, lower)
    mouth.move_to(position)
    group: Any = mouth
    if label:
        lbl = _label(label, 20)
        lbl.next_to(mouth, DOWN, buff=0.15)
        group = VGroup(mouth, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "mouth", zone=Zone.RIGHT, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)
    return mouth


# ────────────────────────────────────────────────────────────────────────
# narrative primitives (kinetic text ONLY as fallback — spec §9)
# ────────────────────────────────────────────────────────────────────────
def QuestionMark(scene: Scene, scene_state: SceneState,
                 text: str = "?", oid: str = "question",
                 duration: float | None = None) -> None:
    """A question glyph for the hook beat (short text — allowed)."""
    d = _motion_default(duration, 0.9)
    from manim import MathTex
    q = MathTex(text, color=_accent(4), font_size=52)
    q.move_to(zone_offset(Zone.CENTER))
    scene.play(FadeIn(q, scale=1.5), run_time=d)
    scene_state.enter(oid, "question", value=text, zone=Zone.CENTER,
                      persistent=False, mobject=q)
    scene_state.record_enter(oid)


def ExperimentBadge(scene: Scene, scene_state: SceneState,
                    text: str = "experiment", oid: str = "experiment",
                    duration: float | None = None) -> None:
    """Small 'experiment' tag for experiment beats (short label)."""
    d = _motion_default(duration, 0.6)
    mob = Text(text, font=_font(), font_size=24, color=_accent(1))
    mob.move_to(zone_offset(Zone.TOP))
    scene.play(FadeIn(mob), run_time=d)
    scene_state.enter(oid, "experiment", value=text, zone=Zone.TOP,
                      persistent=False, mobject=mob)
    scene_state.record_enter(oid)


def RevealText(scene: Scene, scene_state: SceneState,
               text: str, oid: str = "reveal", color: str = "#81C784",
               duration: float | None = None) -> None:
    """Short reveal text (critical terms / numbers only — spec §9)."""
    d = _motion_default(duration, 0.8)
    mob = Text(text, font=_font(), font_size=34, color=color)
    mob.move_to(zone_offset(Zone.CENTER))
    scene.play(FadeIn(mob, scale=1.4), run_time=d * 0.7)
    scene.play(Indicate(mob, color=color), run_time=d * 0.3)
    scene_state.enter(oid, "reveal", value=text, zone=Zone.CENTER,
                      persistent=False, mobject=mob)
    scene_state.record_enter(oid)


def PayoffText(scene: Scene, scene_state: SceneState,
               text: str, oid: str = "payoff", color: str = "#FFD54F",
               duration: float | None = None) -> None:
    """Final payoff line (short claim — allowed as a reveal)."""
    d = _motion_default(duration, 1.0)
    mob = Text(text, font=_font(), font_size=38, color=color)
    mob.move_to(zone_offset(Zone.CENTER))
    scene.play(FadeIn(mob, scale=1.6), run_time=d * 0.6)
    scene.play(Indicate(mob), run_time=d * 0.4)
    scene_state.enter(oid, "payoff", value=text, zone=Zone.CENTER,
                      persistent=False, mobject=mob)
    scene_state.record_enter(oid)


# ────────────────────────────────────────────────────────────────
# geometry: Gabriel's Horn surface of revolution (y = 1/x, x ≥ 1)
# — shared deterministic profile used by HornProfile + PaintFill so the
# fill region always matches the drawn horn exactly.
# ────────────────────────────────────────────────────────────────
def _horn_profile(x_max: float = 6.0,
                  samples: int = 72) -> tuple[list, list]:
    """Screen-space sample points of y = 1/x (top) and y = −1/x (bottom)
    for x in [1, x_max].  Deterministic; shared geometry contract."""
    x0, x1 = -4.2, 4.2                      # screen x span
    ys = 1.5                                # y scale (1/x at x=1 -> 1.5)
    xs = [1.0 + i * (x_max - 1.0) / (samples - 1)
          for i in range(samples)]
    def sx(x: float) -> float:
        return x0 + (x - 1.0) * (x1 - x0) / (x_max - 1.0)
    top = [[sx(x), ys / x, 0.0] for x in xs]
    bottom = [[sx(x), -ys / x, 0.0] for x in xs]
    return top, bottom


def HornProfile(scene: Scene, scene_state: SceneState, oid: str = "horn",
                label: str = "y = 1/x, x ≥ 1", color: str = "#3A86D6",
                duration: float | None = None) -> None:
    """Draw Gabriel's Horn: the revolved y = 1/x silhouette (top + bottom
    branches), the x-axis, the mouth cap at x = 1, and a label.
    Deterministic; the surface itself is the persistent stage object."""
    d = _motion_default(duration, 1.2)
    top, bottom = _horn_profile()
    upper = VMobject(color=color, stroke_width=4)
    upper.set_points_as_corners(top)
    lower = VMobject(color=color, stroke_width=4)
    lower.set_points_as_corners(bottom)
    axis = Line([top[0][0], 0, 0], [top[-1][0] + 0.3, 0, 0],
                color="#78909C", stroke_width=2)
    mouth = Line(top[0], bottom[0], color=color, stroke_width=4)
    group = VGroup(upper, lower, axis, mouth)
    if label:
        # wave-2 contrast rule (review v3 §4.8): the y = 1/x label was a
        # low-contrast gray overlapping the blue fill — render it WHITE
        # above the horn mouth where it never collides with the fill
        lbl = _label(label, 22, "#F5F7FA")
        lbl.move_to([top[0][0] + 0.4,
                     max(p[1] for p in top) + 0.55, 0])
        group.add(lbl)
    scene.play(Create(group), run_time=d)
    scene_state.enter(oid, "horn", value=label, persistent=True,
                      mobject=group)
    scene_state.record_enter(oid)


def PaintFill(scene: Scene, scene_state: SceneState, oid: str = "fill",
              target_oid: str = "horn", label: str = "V = π",
              color: str = "#42A5F5", duration: float | None = None) -> None:
    """Fill the horn's interior with paint (the finite-volume side of the
    painter's paradox).  Uses the shared profile so the fill region always
    matches the drawn horn.  TEMP mobject: removed at end of beat."""
    d = _motion_default(duration, 2.0)
    top, bottom = _horn_profile()
    corners = top + list(reversed(bottom))
    fill = Polygon(*corners, color=color, fill_opacity=0.55,
                   stroke_width=0)
    group = VGroup(fill)
    if label:
        lbl = _label(label, 30, "#FFD54F")
        lbl.move_to([(top[0][0] + top[-1][0]) / 2, 0.75, 0])
        group.add(lbl)
    from engine.qa.fade import clamp_fade
    scene.play(FadeIn(group, scale=0.96), run_time=clamp_fade(d * 0.7))
    # color-safe pulse: scale-only (Indicate recolors yellow -> the blue
    # fill reads OLIVE mid-flick; review v3 §4.8 'muddy olive fill')
    scene.play(fill.animate(rate_func=there_and_back).scale(1.03),
               run_time=clamp_fade(d * 0.3))
    # Honest TEMP lifecycle: pixels stay for this beat, the compiler's
    # next-beat EXIT sweep fades them before the next text layer enters
    # (the old code declared enter+exit instantly and never removed the
    # fill+label group — stacked formula layers, see MeasureValue note).
    scene_state.enter(oid, "shape", value=label, persistent=False,
                      mobject=group)
    scene_state.record_enter(oid)


# ────────────────────────────────────────────────────────────────────────
# §46 primitives: noise-cancelling interference + popcorn burst
# ────────────────────────────────────────────────────────────────────────
def InterferencePattern(scene: Scene, scene_state: SceneState,
                        oid: str = "interference",
                        frequency: float = 1.0, amplitude: float = 0.5,
                        phase_deg: float = 180.0, color: str = "#4FC3F7",
                        label: str = "",
                        duration: float | None = None) -> Any:
    """Two travelling waves + combined wave (noise-cancelling hero, §46).

    Wave A (noise) and wave B (inverse, phase-shifted) superpose; the
    combined curve shows cancellation at 180° anti-phase.  Deterministic.
    """
    d = _motion_default(duration, 3.2)
    cycles = 2.0
    total_len = 1.6 * cycles
    ph = math.radians(phase_deg)

    def _f(p: float, t: float):
        return [t * total_len - total_len / 2,
                amplitude * math.sin(2 * math.pi * cycles * t + p), 0]

    wa = ParametricFunction(lambda t: _f(0.0, t), t_range=[0, 1],
                            color="#FFB74D", stroke_width=3)
    wb = ParametricFunction(lambda t: _f(ph, t), t_range=[0, 1],
                            color="#4FC3F7", stroke_width=3)
    combined_amp = amplitude * abs(2.0 * math.cos(ph / 2.0))
    wc = ParametricFunction(
        lambda t: [t * total_len - total_len / 2,
                   combined_amp * math.sin(2 * math.pi * cycles * t), 0],
        t_range=[0, 1], color="#66BB6A", stroke_width=4)
    wa.shift(UP * 1.4)
    wb.shift(UP * 0.0)
    wc.shift(DOWN * 1.4)
    group: Any = VGroup(wa, wb, wc)
    if label:
        lbl = _label(label, 20, color)
        lbl.next_to(group, DOWN, buff=0.15)
        group = VGroup(group, lbl)
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter(oid, "interference", persistent=False, mobject=group)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return group


def WaveSuperposition(scene: Scene, scene_state: SceneState,
                      oid: str = "superposition",
                      frequency: float = 1.0, amplitude: float = 0.5,
                      phase_deg: float = 180.0, color: str = "#66BB6A",
                      label: str = "",
                      duration: float | None = None) -> Any:
    """Combined-wave payoff for the `cancel` action (§46).

    At 180° anti-phase the combined curve is (near) flat — the "silence"
    moment.  Deterministic; same family as InterferencePattern.
    """
    return InterferencePattern(
        scene, scene_state, oid=oid, frequency=frequency,
        amplitude=amplitude, phase_deg=phase_deg, color=color,
        label=label or "silence", duration=duration)


def PressureKernel(scene: Scene, scene_state: SceneState,
                   oid: str = "kernel", pressure_atm: float = 9.0,
                   temp_c: float = 180.0, radius: float = 0.9,
                   color: str = "#8D6E63", label: str = "",
                   duration: float | None = None) -> Any:
    """Popcorn kernel: starch shell + water/steam dots + pressure gauge.

    Deterministic: shell circle, inner water dots, a gauge bar climbing
    toward the burst point (≈9 atm near 180 °C).  §46 hero family.
    """
    d = _motion_default(duration, 2.8)
    shell = Circle(radius=radius, color=color, stroke_width=4)
    shell.move_to(ORIGIN)
    drops = VGroup(*[
        Dot(radius=0.05, color="#4FC3F7").move_to(
            [radius * 0.45 * math.cos(a), radius * 0.45 * math.sin(a), 0])
        for a in [i * math.pi / 4 for i in range(8)]])
    gx = radius + 1.0
    gauge_base = Line([gx, -1.2, 0], [gx, 1.2, 0],
                      color="#90A4AE", stroke_width=2)
    frac = min(1.0, max(0.0, pressure_atm / 9.0))
    gauge = Line([gx, -1.2, 0], [gx, -1.2 + 2.4 * frac, 0],
                 color="#FF5252", stroke_width=4)
    gauge_label = _label(f"{pressure_atm:.0f} atm", 16, "#FF5252")
    gauge_label.next_to(gauge_base, RIGHT, buff=0.1)
    group: Any = VGroup(shell, drops, gauge_base, gauge, gauge_label)
    if label:
        lbl = _label(label, 18, color)
        lbl.next_to(shell, DOWN, buff=0.2)
        group = VGroup(group, lbl)
    scene.play(FadeIn(shell), run_time=d * 0.5)
    scene.play(FadeIn(drops), run_time=d * 0.4)
    scene.play(GrowFromCenter(gauge), run_time=d * 0.6)
    scene.play(FadeIn(gauge_label), run_time=d * 0.3)
    scene_state.enter(oid, "kernel", persistent=False, mobject=group)
    scene_state.exit(oid)
    scene_state.record_enter(oid)
    scene_state.record_exit(oid)
    return group


def BurstExplosion(scene: Scene, scene_state: SceneState,
                   at: Sequence[float] = (0, 0, 0), radius: float = 1.0,
                   color: str = "#FFB74D", label: str = "",
                   duration: float | None = None) -> None:
    """Kernel burst: expanding ring + outward fluff dots (popcorn hero)."""
    d = _motion_default(duration, 1.6)
    ring = Circle(radius=0.1, color=color, stroke_width=5)
    ring.move_to(at)
    scene.play(GrowFromCenter(ring), run_time=d * 0.5)
    ring2 = ring.copy().scale(radius / 0.1)
    ring2.set_stroke(opacity=0.0)
    scene.play(Transform(ring, ring2), run_time=d * 0.4)
    flakes = VGroup(*[
        Dot(radius=0.08, color="#FFE0B2").move_to(
            [at[0] + radius * 1.5 * math.cos(a),
             at[1] + radius * 1.5 * math.sin(a), 0])
        for a in [i * math.pi / 6 for i in range(12)]])
    scene.play(FadeIn(flakes), run_time=d * 0.5)
    scene.play(FadeOut(VGroup(ring, flakes)), run_time=0.2)
    scene_state.enter("burst", "particle", zone=Zone.CENTER,
                      persistent=False, mobject=ring)
    scene_state.exit("burst")
    scene_state.record_enter("burst")
    scene_state.record_exit("burst")


# ────────────────────────────────────────────────────────────────────────
# registry for the compiler
# ────────────────────────────────────────────────────────────────────────
WORLD_PRIMITIVES: dict[str, object] = {
    "CelestialBody": CelestialBody,
    "MediumLayer": MediumLayer,
    "OrbitPath": OrbitPath,
    "MovingBody": MovingBody,
    "FollowBody": FollowBody,
    "FallBody": FallBody,
    "AccelerateBody": AccelerateBody,
    "CollideBodies": CollideBodies,
    "ImpactBurst": ImpactBurst,
    "MissBody": MissBody,
    "CurvePath": CurvePath,
    "TracePath": TracePath,
    "OscillateBody": OscillateBody,
    "VelocityVector": VelocityVector,
    "ForceVector": ForceVector,
    "ReferenceFrame": ReferenceFrame,
    "ProjectilePath": ProjectilePath,
    "LightSource": LightSource,
    "LightRay": LightRay,
    "Wave": Wave,
    "SignalPulse": SignalPulse,
    "ParticleField": ParticleField,
    "ScatteringField": ScatteringField,
    "CrossSection": CrossSection,
    "RevealInside": RevealInside,
    "Node": Node,
    "Connection": Connection,
    "FlowThrough": FlowThrough,
    "BranchFlow": BranchFlow,
    "MergeFlow": MergeFlow,
    "Timeline": Timeline,
    "CauseEffectChain": CauseEffectChain,
    "MeasureValue": MeasureValue,
    "EyeGlyph": EyeGlyph,
    "EarGlyph": EarGlyph,
    "BrainGlyph": BrainGlyph,
    "MouthGlyph": MouthGlyph,
    "QuestionMark": QuestionMark,
    "ExperimentBadge": ExperimentBadge,
    "RevealText": RevealText,
    "PayoffText": PayoffText,
    "HornProfile": HornProfile,
    "PaintFill": PaintFill,
}

# Entity type -> materializer primitive (used by the world compiler).
ENTITY_MATERIALIZERS: dict[str, str] = {
    "celestial_body": "CelestialBody",
    "moving_body": "MovingBody",
    "orbit_path": "OrbitPath",
    "light_source": "LightSource",
    "light_ray": "LightRay",
    "medium": "MediumLayer",
    "scatterer": "ScatteringField",
    "wave": "Wave",
    "signal": "SignalPulse",
    "particle": "ParticleField",
    "eye": "EyeGlyph",
    "ear": "EarGlyph",
    "brain": "BrainGlyph",
    "mouth": "MouthGlyph",
    "node": "Node",
    "connection": "Connection",
    "flow": "FlowThrough",
    "timeline": "Timeline",
    "cause_effect": "CauseEffectChain",
    "question": "QuestionMark",
    "experiment": "ExperimentBadge",
    "reveal": "RevealText",
    "payoff": "PayoffText",
    "perception": "RevealText",
    "decision": "Node",
    "number": "MovingBody",
    "digit_array": "MovingBody",
    "equation": "RevealText",
    # §46 acoustics / phase-change entities
    "microphone": "Node",
    "processor": "Node",
    "interference": "InterferencePattern",
    "kernel": "PressureKernel",
    "steam": "ParticleField",
    "shell": "PressureKernel",
    # geometry (Gabriel's Horn)
    "horn": "HornProfile",
}


# ────────────────────────────────────────────────────────────────────────
# entity materializer + semantic action dispatcher (compiler-facing)
# ────────────────────────────────────────────────────────────────────────
def _prop(props: dict, key: str, default: Any = None) -> Any:
    return props.get(key, default)


def _pos(props: dict, fallback: Sequence[float]) -> Sequence[float]:
    """Resolve an entity position, always returning a 3D point.

    Manim mobjects require 3-component points; callers may pass 2D
    fallbacks (e.g. [0, 0]) which are padded with z=0 here so primitive
    code can hand the result straight to move_to/shift.
    """
    p = props.get("position")
    if isinstance(p, dict):
        return [float(p.get("x", fallback[0])),
                float(p.get("y", fallback[1])), 0.0]
    if isinstance(p, (list, tuple)) and len(p) >= 2:
        return [float(p[0]), float(p[1]), 0.0]
    f = list(fallback)
    while len(f) < 3:
        f.append(0.0)
    return f[:3]


def materialize_entity(scene: Scene, scene_state: SceneState,
                       entity: dict, duration: float | None = None) -> Any:
    """Materialize a world entity through its trusted primitive.

    Dispatches by entity type (ENTITY_MATERIALIZERS) with defaults drawn
    from the entity properties; raises on unknown types (closed registry,
    spec §23).  Idempotent per SceneState lifecycle: an entity already on
    stage is returned unchanged (UPDATE happens via actions).
    """
    eid = str(entity.get("id", ""))
    etype = str(entity.get("type", ""))
    props = entity.get("properties", {}) or {}
    existing = scene_state.get(eid)
    if existing is not None and existing.exit_beat is None:
        return existing.mobject
    prim = ENTITY_MATERIALIZERS.get(etype)
    if prim is None:
        raise ValueError(f"materialize_entity: no materializer for entity "
                         f"type {etype!r} (id {eid!r})")
    # NEVER render an entity id as on-screen text (wave-3, GLM review
    # v4 blocker): the label falls back to '' — primitives guard empty
    # labels, so an entity without an explicit display label renders no
    # label at all instead of a garbled debug id like 'payoff_card'.
    label = str(_prop(props, "label", ""))
    position = _pos(props, list(zone_offset(Zone.CENTER)))
    color = str(_prop(props, "color", _accent(0)))
    if prim == "CelestialBody":
        return CelestialBody(
            scene, scene_state, oid=eid,
            radius=float(_prop(props, "radius", 2.0)),
            color=str(_prop(props, "color", "#14375E")),
            limb_color=str(_prop(props, "limb_color", "#3A86D6")),
            label=label, duration=duration)
    if prim == "OrbitPath":
        return OrbitPath(
            scene, scene_state, oid=eid,
            center=_pos(props, [0, 0]),
            radius=float(_prop(props, "radius", 3.4)),
            color=color, label=label, duration=duration)
    if prim == "MovingBody":
        return MovingBody(
            scene, scene_state, oid=eid, color=color,
            position=position, duration=duration)
    if prim == "LightSource":
        return LightSource(scene, scene_state, oid=eid,
                           position=position, label=label, duration=duration)
    if prim == "LightRay":
        start = _pos(props, [-4, 0])
        end = _pos(props, [4, 0])
        return LightRay(scene, scene_state, oid=eid, start=start, end=end,
                        color=color, label=label, duration=duration)
    if prim == "ReferenceFrame":
        return ReferenceFrame(scene, scene_state, oid=eid, label=label,
                              duration=duration)
    if prim == "MediumLayer":
        return MediumLayer(
            scene, scene_state, oid=eid,
            width=float(_prop(props, "width", 12.0)),
            height=float(_prop(props, "height", 1.3)),
            y=float(_prop(props, "y", 2.2)),
            color=str(_prop(props, "color", "#2E4A66")),
            label=label, duration=duration)
    if prim == "ScatteringField":
        return ScatteringField(
            scene, scene_state, oid=eid,
            molecule_at=position,
            blue_nm=float(_prop(props, "blue_nm", 450.0)),
            red_nm=float(_prop(props, "red_nm", 650.0)),
            label=label, duration=duration)
    if prim == "Wave":
        return Wave(scene, scene_state, oid=eid, color=color, label=label,
                    duration=duration)
    if prim == "InterferencePattern":
        return InterferencePattern(
            scene, scene_state, oid=eid,
            frequency=float(_prop(props, "frequency", 1.0)),
            amplitude=float(_prop(props, "amplitude", 0.5)),
            phase_deg=float(_prop(props, "phase_deg", 180.0)),
            color=color, label=label, duration=duration)
    if prim == "WaveSuperposition":
        return WaveSuperposition(
            scene, scene_state, oid=eid,
            frequency=float(_prop(props, "frequency", 1.0)),
            amplitude=float(_prop(props, "amplitude", 0.5)),
            phase_deg=float(_prop(props, "phase_deg", 180.0)),
            color=color, label=label or "silence", duration=duration)
    if prim == "PressureKernel":
        return PressureKernel(
            scene, scene_state, oid=eid,
            pressure_atm=float(_prop(props, "pressure_atm", 9.0)),
            temp_c=float(_prop(props, "temp_c", 180.0)),
            color=color, label=label, duration=duration)
    if prim == "BurstExplosion":
        return BurstExplosion(
            scene, scene_state, at=position,
            radius=float(_prop(props, "radius", 1.0)),
            color=color, label=label, duration=duration)
    if prim == "SignalPulse":
        start = _pos(props, [-3, 0])
        end = _pos(props, [3, 0])
        return SignalPulse(scene, scene_state, start=start, end=end,
                           oid=eid, color=color, duration=duration)
    if prim == "ParticleField":
        return ParticleField(scene, scene_state, oid=eid,
                             n=int(_prop(props, "count", 120)),
                             center=position, duration=duration)
    if prim in ("EyeGlyph", "EarGlyph", "BrainGlyph", "MouthGlyph"):
        fn = globals()[prim]
        return fn(scene, scene_state, oid=eid, position=position,
                  label=label, duration=duration)
    if prim == "Node":
        return Node(scene, scene_state, oid=eid, position=position,
                    label=label, color=color, duration=duration)
    if prim == "Connection":
        start = _pos(props, [-3, 0])
        end = _pos(props, [3, 0])
        return Connection(scene, scene_state, oid=eid, start=start, end=end,
                          color=color, duration=duration)
    if prim == "FlowThrough":
        nodes = _prop(props, "nodes",
                      [{"position": [-3, 0, 0]}, {"position": [0, 0, 0]},
                       {"position": [3, 0, 0]}])
        return FlowThrough(scene, scene_state, oid=eid, nodes=nodes,
                           color=color, duration=duration)
    if prim == "Timeline":
        events = _prop(props, "events", [])
        return Timeline(scene, scene_state, oid=eid, events=events,
                        duration=duration)
    if prim == "CauseEffectChain":
        links = _prop(props, "links",
                      [{"label": "cause"}, {"label": "effect"}])
        return CauseEffectChain(scene, scene_state, links=links, oid=eid,
                                duration=duration)
    if prim in ("QuestionMark", "ExperimentBadge", "RevealText",
                "PayoffText"):
        fn = globals()[prim]
        # Text entities render ONLY an explicit text/value property —
        # never the entity id (wave-3 rule).  With no explicit display
        # text the entity materializes as a state-only record: nothing
        # is drawn on screen.
        text = str(_prop(props, "text", _prop(props, "value", "")))
        if not text:
            scene_state.enter(eid, etype, value="", zone=Zone.CENTER,
                              persistent=False, mobject=None)
            scene_state.record_enter(eid)
            return None
        return fn(scene, scene_state, text=text, oid=eid, duration=duration)
    fn = WORLD_PRIMITIVES.get(prim)
    if fn is None:
        raise ValueError(f"materialize_entity: primitive {prim!r} missing")
    return fn(scene, scene_state, oid=eid, duration=duration)


# Natural (unscaled) duration per semantic action, in seconds.
ACTION_NATURAL_DURATION: dict[str, float] = {
    "orbit": 3.2, "fall": 2.0, "accelerate": 1.4, "decelerate": 1.4,
    "collide": 1.2, "miss": 1.8, "curve": 1.0, "follow": 2.4,
    "trace": 1.2, "branch": 1.8, "merge": 1.8, "converge": 3.0,
    "oscillate": 2.4, "flow": 2.6, "scatter": 3.6, "assemble": 2.0,
    "disassemble": 2.0, "compare": 1.2, "measure": 0.8,
    "zoom_into": 1.0, "zoom_out_of": 1.0, "focus_on": 1.0,
    "cross_section": 1.2, "reveal_inside": 1.4, "highlight": 0.6,
    "reveal": 1.2, "sort": 1.2, "subtract": 3.0, "morph": 1.2,
    "transform": 1.2, "count_down": 1.8,
    "interfere": 3.4, "cancel": 3.4, "burst": 2.2, "fill": 2.2,
}


# ────────────────────────────────────────────────────────────────────────
# text-layer contract (shared by runtime, world compiler and QA gate)
# ────────────────────────────────────────────────────────────────────────
# Semantic actions that schedule a TEXT/label/formula layer on stage.
# This is the text crossfade-overlap bug class: two of these layers on
# stage at once garble both (Gabriel's Horn -r3, t≈13–33s, 2026-08-27).
TEXT_LAYER_ACTIONS: tuple[str, ...] = ("measure", "fill", "compare", "reveal")

# Entity obj_types that ARE text layers (PayoffText / RevealText /
# QuestionMark / _enter_text primitives enter with these types).
TEXT_ENTITY_TYPES: frozenset[str] = frozenset(
    {"payoff", "reveal", "text", "question"})


def text_layer_oid(action: str, target: str) -> str | None:
    """SceneState oid of the text layer an action creates (single source
    of truth for the runtime AND the QA text-overlap gate)."""
    if action == "measure":
        return f"{target or 'measure'}_measure"
    if action == "fill":
        return f"{target}_fill" if target else "fill"
    if action == "compare":
        return "comparison"
    if action == "reveal":
        return target or "reveal"
    return None


def is_text_layer_replacement(beat: dict, action: dict) -> bool:
    """True when the action retargets a TEXT entity declared in the same
    beat (e.g. measure on a payoff card): an in-place replacement of that
    layer, never a second overlapping one."""
    name = str(action.get("action", action.get("type", "")))
    target = str(action.get("target", ""))
    if name != "measure" or not target:
        return False
    for obj in beat.get("objects", []) or []:
        if (isinstance(obj, dict)
                and str(obj.get("id", "")) == target
                and str(obj.get("type", "")) in TEXT_ENTITY_TYPES):
            return True
    return False


def _replace_text_layer(scene: Scene, scene_state: SceneState, oid: str,
                        text: str, duration: float | None = None) -> None:
    """Replace a text entity's displayed text IN PLACE (fade-swap at the
    same position, same SceneState oid).  Never creates a second layer."""
    obj = scene_state.get(oid)
    if obj is None or obj.mobject is None:
        return
    if str(obj.value or "") == text:
        # same string already on stage — pure confirmation, no pixels move
        scene_state.update(oid, {"op": "measure_confirm"}, value=text)
        scene_state.record_update(oid)
        return
    d = _motion_default(duration, 0.7)
    old = obj.mobject
    at = old.get_center()
    scene.play(FadeOut(old), run_time=d * 0.5)
    mob = Text(text, font=_font(), font_size=38, color="#FFD54F")
    mob.move_to(at)
    scene.play(FadeIn(mob, scale=1.2), run_time=d * 0.5)
    scene_state.update(oid, {"op": "measure_replace"}, value=text,
                       mobject=mob)
    scene_state.record_update(oid)


def apply_action(scene: Scene, scene_state: SceneState,
                 action: dict, world: dict,
                 duration: float | None = None) -> None:
    """Execute one semantic action against the world (deterministic).

    Resolves targets by entity id; validates the physics via the
    deterministic verifiers; raises ValueError on anything invalid —
    never a silent no-op (spec §7, §18, §19).
    """
    name = str(action.get("action", ""))
    if not name:
        name = str(action.get("type", ""))
    target = str(action.get("target", action.get("targets", [""])[0] if
                 isinstance(action.get("targets"), list) else ""))
    params = action.get("params", {}) or {}
    # normalize: the rendered scene passes a WorldState instance; the
    # director/compiler pass plain dicts
    if not isinstance(world, dict):
        world = world.to_dict()
    entities = {e.get("id"): e for e in world.get("entities", [])}

    def _pos_of(eid: str, fallback: Sequence[float]) -> Sequence[float]:
        ent = entities.get(eid, {})
        return _pos(ent.get("properties", {}), list(fallback))

    if name == "orbit":
        body = target or "satellite"
        center = _pos_of(str(params.get("center", "earth")), [0, 0])
        if params.get("center") and params["center"] in entities:
            center = _pos_of(str(params["center"]), [0, 0])
        radius = float(params.get("radius", 3.4))
        laps = float(params.get("laps", 1.2))
        # earth persists; orbit path + body enter; body follows at linear
        # rate; velocity/force vectors appear once (tangent/radial)
        if "earth" in entities and scene_state.get("earth") is None:
            materialize_entity(scene, scene_state, entities["earth"])
        OrbitPath(scene, scene_state, oid="orbit", center=center,
                  radius=radius, duration=duration)
        body_obj = scene_state.get(body)
        if body_obj is None or body_obj.exit_beat is not None:
            MovingBody(scene, scene_state, oid=body,
                       position=[center[0] + radius, center[1], 0],
                       duration=duration)
        path = scene_state.get("orbit").mobject
        FollowBody(scene, scene_state, body, path, run_time=2.2,
                   duration=duration)
        # tangent + radial vectors (mm-lab hero shot pattern)
        pos = scene_state.get(body).mobject.get_center()
        vec_len = float(params.get("vec_len", 1.2))
        tgt = [pos[0] - center[0], pos[1] - center[1], 0]
        norm = math.hypot(tgt[0], tgt[1]) or 1.0
        tangent = [-tgt[1] / norm, tgt[0] / norm, 0]
        VelocityVector(scene, scene_state, body,
                       start=[pos[0], pos[1], 0],
                       end=[pos[0] + tangent[0] * vec_len,
                            pos[1] + tangent[1] * vec_len, 0],
                       label="v", duration=duration)
        ForceVector(scene, scene_state, body,
                    start=[pos[0], pos[1], 0],
                    end=[pos[0] - tgt[0] / norm * vec_len,
                         pos[1] - tgt[1] / norm * vec_len, 0],
                    label="g", duration=duration)
        return
    if name == "fall":
        body = target or "body"
        if scene_state.get(body) is None:
            MovingBody(scene, scene_state, oid=body, duration=duration)
        FallBody(scene, scene_state, body,
                 drop_height=float(params.get("height", 3.0)),
                 g=float(params.get("g", 5.0)),
                 land_y=float(params.get("land_y", -2.0)),
                 duration=duration)
        return
    if name == "accelerate":
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        AccelerateBody(scene, scene_state, target,
                       target_speed_label=str(params.get("to", "faster")),
                       duration=duration)
        return
    if name == "decelerate":
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        AccelerateBody(scene, scene_state, target,
                       target_speed_label=str(params.get("to", "slower")),
                       duration=duration)
        return
    if name == "collide":
        other = str(params.get("with", ""))
        if not other:
            raise ValueError("collide action needs params.with")
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        if scene_state.get(other) is None:
            MovingBody(scene, scene_state, oid=other, duration=duration)
        CollideBodies(scene, scene_state, target, other, duration=duration)
        ImpactBurst(scene, scene_state,
                    at=scene_state.get(target).mobject.get_center(),
                    duration=duration)
        return
    if name == "miss":
        other = str(params.get("past", ""))
        if not other:
            raise ValueError("miss action needs params.past")
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        MissBody(scene, scene_state, target, other,
                 offset=float(params.get("offset", 0.6)),
                 duration=duration)
        return
    if name == "trace":
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        TracePath(scene, scene_state, target,
                  path=Circle(radius=float(params.get("radius", 3.4))),
                  color=str(params.get("color", _accent(0))),
                  duration=duration)
        return
    if name == "oscillate":
        if scene_state.get(target) is None:
            MovingBody(scene, scene_state, oid=target, duration=duration)
        OscillateBody(scene, scene_state, target,
                      amplitude=float(params.get("amplitude", 1.2)),
                      cycles=int(params.get("cycles", 3)),
                      duration=duration)
        return
    if name == "scatter":
        from engine.validation.physics_verify import verify_rayleigh_ratio
        v = verify_rayleigh_ratio(float(params.get("blue_nm", 450.0)),
                                  float(params.get("red_nm", 650.0)))
        if not v.ok:
            raise ValueError("scatter action failed physics verification: "
                             + "; ".join(f["detail"] for f in v.failures()))
        ScatteringField(scene, scene_state, oid=target or "scatter",
                        molecule_at=_pos_of(target, [0, 0]),
                        blue_nm=float(params.get("blue_nm", 450.0)),
                        red_nm=float(params.get("red_nm", 650.0)),
                        label=str(params.get("label", "")),
                        duration=duration)
        return
    if name in ("interfere", "cancel"):
        from engine.validation.physics_verify import verify_wave_interference
        f1 = float(params.get("f1", params.get("frequency", 1.0)))
        f2 = float(params.get("f2", params.get("frequency", 1.0)))
        ph = float(params.get("phase_deg", 180.0))
        v = verify_wave_interference(f1, f2, ph)
        if not v.ok:
            raise ValueError("interfere/cancel failed physics verification: "
                             + "; ".join(f["detail"] for f in v.failures()))
        amp = float(params.get("amplitude", 0.5))
        lbl = str(params.get("label", ""))
        if name == "interfere":
            InterferencePattern(scene, scene_state, oid=target or "interference",
                                frequency=f1, amplitude=amp, phase_deg=ph,
                                label=lbl, duration=duration)
        else:
            WaveSuperposition(scene, scene_state, oid=target or "superposition",
                              frequency=f1, amplitude=amp, phase_deg=ph,
                              label=lbl or "silence", duration=duration)
        return
    if name == "burst":
        from engine.validation.physics_verify import verify_pressure_volume_burst
        patm = float(params.get("pressure_atm", 9.0))
        tc = float(params.get("temp_c", 180.0))
        v = verify_pressure_volume_burst(patm, tc)
        if not v.ok:
            raise ValueError("burst action failed physics verification: "
                             + "; ".join(f["detail"] for f in v.failures()))
        PressureKernel(scene, scene_state, oid=target or "kernel",
                       pressure_atm=patm, temp_c=tc,
                       label=str(params.get("label", "")), duration=duration)
        BurstExplosion(scene, scene_state, at=_pos_of(target, [0, 0]),
                       radius=float(params.get("radius", 1.0)),
                       duration=duration)
        return
    if name == "fill":
        # Gabriel's Horn painter's paradox: finite volume, infinite surface.
        # Deterministic math verification before any pixels move (spec §18).
        from engine.validation.math_verify import verify_gabriels_horn
        v = verify_gabriels_horn()
        if not v.ok:
            raise ValueError("fill action failed math verification: "
                             + "; ".join(f["detail"] for f in v.failures()))
        # NOTE: the fill's fill+label group gets its OWN oid (<target>_fill),
        # never the target's id.  The old code passed oid=target, which
        # OVERWROTE the persistent target entity in SceneState (mobject
        # handle replaced by the fill polygon) and orphaned the real
        # entity — positions and later exits then misfired.
        PaintFill(scene, scene_state,
                  oid=f"{target}_fill" if target else "fill",
                  target_oid=target or "horn",
                  label=str(params.get("label", params.get("value", "V = π"))),
                  duration=duration)
        return
    if name == "flow":
        nodes = params.get("nodes", []) or []
        if not nodes:
            raise ValueError("flow action needs params.nodes")
        FlowThrough(scene, scene_state, oid=target or "flow", nodes=nodes,
                    color=str(params.get("color", _accent(4))),
                    duration=duration)
        return
    if name == "branch":
        BranchFlow(scene, scene_state, oid=target or "branch",
                   from_pos=_pos_of(target, [-2, 0]),
                   to_positions=params.get("to", []),
                   duration=duration)
        return
    if name == "merge":
        MergeFlow(scene, scene_state, oid=target or "merge",
                  from_positions=params.get("from", []),
                  to_pos=_pos_of(target, [2, 0]),
                  duration=duration)
        return
    if name == "converge":
        from engine.primitives.manim_primitives import (
            AttractorDiagram, ConvergenceParticles)
        to = str(action.get("to", ""))
        if to and "->" in to:
            trajs = [[p.strip() for p in to.split("->")]]
            AttractorDiagram(scene, scene_state, trajs, ndigits=4,
                             duration=duration)
        else:
            tgt = target or "attractor"
            if scene_state.get(tgt) is None:
                from engine.primitives.manim_primitives import enter_attractor
                enter_attractor(scene, scene_state,
                                str(action.get("to", "6174")),
                                duration=duration)
            ConvergenceParticles(scene, scene_state, tgt, n=40,
                                 duration=duration or 1.6)
        return
    if name in ("compare",):
        from engine.primitives.manim_primitives import Comparison
        Comparison(scene, str(params.get("left_label", "A")),
                   str(params.get("right_label", "B")),
                   str(params.get("left", "")),
                   str(params.get("right", "")),
                   scene_state=scene_state, duration=duration)
        return
    if name == "measure":
        value = str(action.get("to", params.get("value", "")))
        label = str(params.get("label", ""))
        tgt_obj = scene_state.get(target or "")
        if (tgt_obj is not None and tgt_obj.exit_beat is None
                and tgt_obj.obj_type in TEXT_ENTITY_TYPES):
            # measure ON an existing text entity (payoff/reveal/question
            # card): REPLACE its text in place.  A second layer here is
            # the text crossfade-overlap bug class — never stack.
            # No explicit display value -> render nothing (the internal
            # `label` is bookkeeping, never on-screen text).
            if value:
                _replace_text_layer(
                    scene, scene_state, oid=target,
                    text=value, duration=duration)
            return
        MeasureValue(scene, scene_state, oid=target or "measure",
                     value=value,
                     label=label,
                     at=_pos_of(target, [0, 2]),
                     duration=duration)
        return
    if name == "assemble":
        AssembleBodies(scene, scene_state, target, duration=duration)
        return
    if name == "disassemble":
        DisassembleBodies(scene, scene_state, target, duration=duration)
        return
    if name == "cross_section":
        CrossSection(scene, scene_state, oid=target or "slice",
                     target_oid=target, duration=duration)
        return
    if name == "reveal_inside":
        inner = Dot(radius=0.2, color=_accent(1))
        RevealInside(scene, scene_state, oid=target or "inside",
                     target_oid=target, inner=inner, duration=duration)
        return
    if name == "highlight":
        from engine.primitives.manim_primitives import HighlightTarget
        HighlightTarget(scene, scene_state, target, duration=duration)
        return
    if name in ("reveal",):
        # Reveal renders ONLY an explicit display value/text — never the
        # target entity id (wave-3: the old fallback to `target` drew
        # 'payoff_card' as garbled on-screen text over the payoff) and
        # never the internal params.label ('you decide').
        text = str(action.get("to", params.get("text", params.get("value",
                 ""))))
        if not text:
            return
        tgt_obj = scene_state.get(target or "")
        if (tgt_obj is not None and tgt_obj.exit_beat is None
                and tgt_obj.obj_type in TEXT_ENTITY_TYPES):
            # reveal ON an existing text card: swap IN PLACE — a second
            # stacked text layer is the crossfade-overlap bug class.
            _replace_text_layer(scene, scene_state, oid=target, text=text,
                                duration=duration)
            return
        RevealText(scene, scene_state, text=text,
                   oid=target or "reveal", duration=duration)
        return
    if name in ("sort", "subtract", "morph", "transform"):
        from engine.primitives.manim_primitives import (
            reorder_digits, apply_kaprekar_step, morph_number)
        if name == "sort":
            reorder_digits(scene, scene_state, target,
                           str(action.get("from", "")),
                           str(action.get("to", "")),
                           duration=duration)
        elif name == "subtract":
            apply_kaprekar_step(scene, scene_state,
                                str(action.get("from", "")),
                                str(action.get("to", "")),
                                duration=duration)
        else:
            morph_number(scene, scene_state, target,
                         str(action.get("from", "")),
                         str(action.get("to", "")),
                         duration=duration)
        return
    if name in ("zoom_into", "zoom_out_of", "focus_on"):
        # camera-level; handled by the compiler's camera pass
        return
    raise ValueError(f"apply_action: unknown semantic action {name!r}")


def AssembleBodies(scene: Scene, scene_state: SceneState,
                   oid: str, duration: float | None = None) -> None:
    """Bring scattered particles together around a target (assemble)."""
    d = _motion_default(duration, 2.0)
    obj = scene_state.get(oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"AssembleBodies: {oid!r} not on stage")
    center = obj.mobject.get_center()
    pts = VGroup()
    for i in range(24):
        theta = i * 2.399963
        r = 2.6 * math.sqrt(i / 24.0)
        dot = Dot(radius=0.05, color=_accent(i % 6))
        dot.move_to([center[0] + r * math.cos(theta),
                     center[1] + r * math.sin(theta), 0])
        pts.add(dot)
    scene.play(FadeIn(pts), run_time=d * 0.3)
    scene.play(*[p.animate.move_to(center + UP * (0.1 * ((i % 5) - 2)))
                 for i, p in enumerate(pts)], run_time=d * 0.6)
    scene.play(FadeOut(pts), run_time=d * 0.1)
    scene_state.enter(f"{oid}_assemble", "particle", persistent=False,
                      mobject=pts)
    scene_state.exit(f"{oid}_assemble")
    scene_state.record_enter(f"{oid}_assemble")
    scene_state.record_exit(f"{oid}_assemble")


def DisassembleBodies(scene: Scene, scene_state: SceneState,
                      oid: str, duration: float | None = None) -> None:
    """Scatter particles away from a target (disassemble)."""
    d = _motion_default(duration, 2.0)
    obj = scene_state.get(oid)
    if obj is None or obj.mobject is None:
        raise ValueError(f"DisassembleBodies: {oid!r} not on stage")
    center = obj.mobject.get_center()
    pts = VGroup()
    for i in range(24):
        theta = i * 2.399963
        r = 2.6 * math.sqrt(i / 24.0)
        dot = Dot(radius=0.05, color=_accent(i % 6))
        dot.move_to(center)
        pts.add(dot)
    scene.play(FadeIn(pts), run_time=d * 0.2)
    scene.play(*[p.animate.move_to([center[0] + r * math.cos(theta),
                                    center[1] + r * math.sin(theta), 0])
                 for i, p in enumerate(pts)], run_time=d * 0.6)
    scene.play(FadeOut(pts), run_time=d * 0.2)
    scene_state.enter(f"{oid}_disassemble", "particle", persistent=False,
                      mobject=pts)
    scene_state.exit(f"{oid}_disassemble")
    scene_state.record_enter(f"{oid}_disassemble")
    scene_state.record_exit(f"{oid}_disassemble")
