"""Manim primitive library — the trusted rendering layer (directive §8).

GLM decides WHAT/WHY/WHEN; these primitives decide HOW.  They are
deterministic, reusable, and independently testable.

Object-continuity contract (the correctness fix):

    A semantic object (e.g. ``number_main``) is ENTERED once, then UPDATED
    in place (same physical Mobjects move / morph), then EXITED when its
    role ends.  Nothing is ever re-created every beat, so state never piles
    up.  Every primitive that touches the stage records its ENTER / UPDATE /
    EXIT decisions into the caller's ``SceneState`` so the emitted
    ``scene_state_log`` is a faithful per-beat lifecycle record.

Digit identity: digits carry SEMANTIC ids (``digit_A`` .. ``digit_D``) —
not positional ids — so identity survives sorting: a reorder physically
moves the same Text Mobjects to new positions instead of swapping values.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from manim import (
    DOWN, LEFT, RIGHT, UP,
    FadeIn, FadeOut, Indicate, Line, MoveToTarget, Scene, Tex, Text,
    Transform, VGroup,
)

from engine.config.loader import get_style
from engine.primitives.layout import zone_offset
from engine.validation import math_verify as M
from engine.visuals.scene_state import Lifecycle, SceneState, Zone

# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------


def _color(key: str, fallback: str) -> str:
    return get_style().get(key, fallback)


def _accent(i: int) -> str:
    accents = get_style().get("accent_colors", ["#4FC3F7"])
    return accents[i % len(accents)]


def _font() -> str:
    return get_style().get("font_family", "DejaVu Sans")


def _digit_size() -> int:
    return get_style().get("font_sizes", {}).get("digit", 64)


def _eq_size() -> int:
    return get_style().get("font_sizes", {}).get("equation", 44)


def _motion_default(d: float | None, fallback: float) -> float:
    if d is not None and d > 0:
        return d
    return get_style().get("motion", {}).get("default_duration", fallback)


def _reading(group: VGroup) -> str:
    """Current left-to-right reading of a digit group ('' if not digits)."""
    try:
        return "".join(d.text for d in group)
    except Exception:  # noqa: BLE001 — non-Text submobjects
        return ""


# ---------------------------------------------------------------------------
# Digit construction & identity
# ---------------------------------------------------------------------------


def make_digit_array(scene: Scene, value: str, id_prefix: str = "digit") -> VGroup:
    """Create a VGroup of digit Mobjects with SEMANTIC ids.

    ids are ``{id_prefix}_A`` .. ``{id_prefix}_D`` (semantic slots), never
    positional ``digit_0..digit_3``, so the same physical Mobject keeps its
    identity across reorders/morphs.
    """
    group = VGroup()
    for i, ch in enumerate(value):
        digit = Text(ch, font=_font(), font_size=_digit_size(),
                     color=_color("primary_text", "#F5F7FA"))
        digit.vid = f"{id_prefix}_{chr(ord('A') + i)}"
        group.add(digit)
    group.arrange(RIGHT, buff=0.2)
    return group


def _reorder_permutation(current: str, target: str) -> list[int]:
    """Map each target slot i -> index of the source digit that fills it.

    Stable matching (first unused digit with matching text) so duplicate
    digits (e.g. 1111) reorder deterministically.  Raises ValueError when
    ``target`` is not a permutation of ``current``.
    """
    if sorted(current) != sorted(target):
        raise ValueError(
            f"cannot reorder {current!r} -> {target!r}: not a permutation")
    used = [False] * len(current)
    perm: list[int] = []
    for ch in target:
        for idx, dch in enumerate(current):
            if dch == ch and not used[idx]:
                perm.append(idx)
                used[idx] = True
                break
    return perm


def animate_digit_reorder(scene: Scene, digit_objects: VGroup | Sequence,
                          from_value: str, to_value: str,
                          duration: float | None = None,
                          stagger: float = 0.15) -> VGroup:
    """Physically move the SAME digit Mobjects into ``to_value`` order.

    - No duplicates, no ghosts: the exact same Mobjects are moved (targets
      are generated on them, never new copies added to the scene).
    - Optional stagger (lag_ratio) makes the swap read as a sequence.
    - Final state equals target: after the animation, reading the group
      left-to-right yields ``to_value``.
    - ``from_value`` must match the current reading; ``to_value`` must be a
      permutation of it (a reorder, never a morph).
    """
    d = _motion_default(duration, 0.8)
    digits = list(digit_objects)
    current = _reading(digits) or from_value
    if current != from_value:
        raise ValueError(
            f"reorder from_value {from_value!r} does not match digits {current!r}")
    perm = _reorder_permutation(current, to_value)

    # Build the target layout from the same-width slots, centered on the
    # current group so the whole block does not drift.
    layout = VGroup(*[Text(ch, font=_font(), font_size=_digit_size(),
                           color=_color("primary_text", "#F5F7FA"))
                      for ch in to_value])
    layout.arrange(RIGHT, buff=0.2)
    centers = [dg.get_center() for dg in digits]
    cx = sum(c[0] for c in centers) / len(centers)
    cy = sum(c[1] for c in centers) / len(centers)
    layout.move_to([cx, cy, 0])

    anims: list = []
    for slot, src_idx in enumerate(perm):
        dg = digits[src_idx]
        dg.generate_target()
        dg.target.move_to(layout[slot].get_center())
        anims.append(MoveToTarget(dg))
    scene.play(*anims, run_time=d, lag_ratio=stagger)

    # Reorder the group's submobject list to the VISUAL target order so that
    # a later `_reading(group)` (which walks ``group.submobjects`` in order)
    # reflects the on-screen arrangement.  The same physical Mobjects are
    # kept (object continuity); only their ``submobjects`` ordering and
    # positions update.  Bound to a VGroup: reorder in place.
    if isinstance(digit_objects, VGroup):
        rebuilt = VGroup(*[digits[src_idx] for src_idx in perm])
        # VGroup.submobjects is writable; reassign to target order.
        digit_objects.submobjects = list(rebuilt)
    return digit_objects  # same physical objects, now in target order


def reorder_digits(scene: Scene, scene_state: SceneState, oid: str,
                   from_value: str, to_value: str, ndigits: int = 4,
                   duration: float | None = None,
                   stagger: float = 0.15) -> VGroup:
    """State-aware digit reorder: fetch the object's SAME digits from the
    SceneState and physically reorder them to spell ``to_value``; records
    the UPDATE on the SceneState.  Raises ValueError when the object is not
    on stage or the values are inconsistent (compiler plans guarantee this
    never happens)."""
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"reorder_digits: {oid!r} is not on stage")
    group = obj.mobject
    current = _reading(group)
    if current != str(from_value).zfill(ndigits):
        raise ValueError(
            f"reorder_digits from {from_value!r} != current reading {current!r}")
    animate_digit_reorder(scene, group, current, str(to_value).zfill(ndigits),
                          duration=duration, stagger=stagger)
    scene_state.update(oid, {"op": "sort", "to": str(to_value).zfill(ndigits)},
                       value=str(to_value).zfill(ndigits), mobject=group)
    scene_state.record_update(oid)
    return group


def _morph_digit(scene: Scene, dg, new_char: str, run_time: float) -> None:
    """Morph ONE digit Mobject to a new character in place (same object)."""
    target = Text(new_char, font=_font(), font_size=_digit_size(),
                  color=dg.color)
    target.move_to(dg.get_center())
    scene.play(Transform(dg, target), run_time=run_time)
    dg.text = new_char


def morph_digits_to(scene: Scene, group: VGroup, to_value: str,
                    duration: float | None = None) -> VGroup:
    """Morph the SAME digit Mobjects to spell ``to_value`` (no recreation)."""
    d = _motion_default(duration, 0.7)
    per = d / max(1, len(to_value))
    for i, ch in enumerate(to_value):
        if i < len(group) and group[i].text != ch:
            _morph_digit(scene, group[i], ch, per)
    return group


# ---------------------------------------------------------------------------
# SceneState-aware entry / exit / highlight primitives
# ---------------------------------------------------------------------------


def enter_number_main(scene: Scene, scene_state: SceneState, value: str,
                      ndigits: int = 4, duration: float | None = None) -> VGroup:
    """ENTER (or UPDATE) the persistent main-number digit block.

    If ``number_main`` is already on stage its SAME digits are reordered /
    morphed to ``value`` (continuity); otherwise the block is created.
    """
    d = _motion_default(duration, 0.6)
    value = str(value).zfill(ndigits)
    existing = scene_state.get("number_main")
    if existing is not None and existing.exit_beat is None and existing.mobject is not None:
        group = existing.mobject
        cur = _reading(group)
        if cur != value:
            try:
                animate_digit_reorder(scene, group, cur, value, duration=d)
            except ValueError:
                morph_digits_to(scene, group, value, duration=d)
            scene_state.update("number_main", {"op": "set_value", "value": value},
                               value=value, mobject=group)
            scene_state.record_update("number_main")
        return group

    group = make_digit_array(scene, value, id_prefix="digit")
    group.move_to(zone_offset(Zone.FOCUS))
    scene.play(FadeIn(group), run_time=d)
    scene_state.enter("number_main", "number", value=value, zone=Zone.FOCUS,
                      persistent=True, mobject=group)
    scene_state.record_enter("number_main")
    return group


def enter_attractor(scene: Scene, scene_state: SceneState, value: str = "6174",
                    duration: float | None = None) -> VGroup:
    """ENTER the attractor object if it is not already on stage."""
    d = _motion_default(duration, 0.6)
    value = str(value).zfill(4)
    existing = scene_state.get("attractor")
    if existing is not None and existing.exit_beat is None and existing.mobject is not None:
        return existing.mobject
    text = Text(value, font=_font(), font_size=_digit_size() * 1.15,
                color=_accent(0))
    text.move_to(zone_offset(Zone.CENTER))
    scene.play(FadeIn(text, scale=1.5), run_time=d)
    scene_state.enter("attractor", "number", value=value, zone=Zone.CENTER,
                      persistent=True, mobject=text)
    scene_state.record_enter("attractor")
    return text


def _on_stage(scene: Scene, mob) -> bool:
    """True when the mobject (or any of its family members) is currently
    in the scene's mobjects list.

    Identity-based (Mobject equality is identity in manim 0.20).  Family
    -wide because primitives may add a group's CHILDREN individually
    (e.g. Comparison fades in left/right separately, never the wrapper
    VGroup) — an identity-only check then missed live pixels and the
    compiler's exit faded nothing.
    """
    fam = {id(m) for m in mob.get_family()}
    return any(id(m) in fam for m in scene.mobjects)


def _stage_members(scene: Scene, mob) -> list:
    """The mobjects of ``mob``'s family that are actually on stage."""
    fam = {id(m) for m in mob.get_family()}
    return [m for m in scene.mobjects if id(m) in fam]


def exit_object(scene: Scene, scene_state: SceneState, oid: str,
                duration: float | None = None) -> None:
    """Idempotent EXIT: fade the object out and record its exit.

    Safe to call twice (compiler may sweep an object the primitive already
    removed) — a second call is a no-op.  The mobject handle is cleared
    after removal so 'exit declared + handle still set' always means
    'pixels still on stage'.
    """
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        return
    present = _stage_members(scene, obj.mobject)
    if present:
        from engine.qa.fade import clamp_fade
        # wave-2 fade rule (a): exits fade in <=0.4s (no sampled ghosts)
        d = clamp_fade(_motion_default(duration, 0.4))
        if len(present) == 1 and present[0] is obj.mobject:
            scene.play(FadeOut(obj.mobject), run_time=d)
        else:
            # children were added individually — fade exactly what is on
            # stage (manim renders the wrapped family, then removes the
            # wrapper; the zero-opacity originals left in scene.mobjects
            # are invisible and inert)
            scene.play(FadeOut(VGroup(*present)), run_time=d)
    obj.mobject = None
    scene_state.exit(oid)
    scene_state.record_exit(oid)


def HighlightTarget(scene: Scene, scene_state: SceneState, oid: str,
                    duration: float | None = None) -> None:
    """Indicate a live object (target must exist on stage)."""
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"HighlightTarget: {oid!r} is not on stage")
    d = _motion_default(duration, 0.5)
    scene.play(Indicate(obj.mobject, color=_accent(0)), run_time=d)
    scene_state.update(oid, {"op": "highlight"}, mobject=obj.mobject)
    scene_state.record_update(oid)


# ---------------------------------------------------------------------------
# The full Kaprekar step (state-aware)
# ---------------------------------------------------------------------------


def apply_kaprekar_step(scene: Scene, scene_state: SceneState,
                        from_value: str, to_value: str,
                        ndigits: int = 4,
                        duration: float | None = None) -> VGroup:
    """Visualize one complete Kaprekar step as a STATE A -> TRANSFORM -> STATE B.

    Phases:
      A  show the input number              (number_main ENTER / UPDATE)
      B  physically move the SAME digits into descending order (5432)
      C  ascending order appears (2345)     (temporary copy)
      D  subtraction constructs itself      (temporary equation)
      E  result is revealed                 (temporary result)
      F  the temporary equation is removed  (EXIT ascending/equation/result)
      G  the main number becomes the next state (SAME digits morph to
         ``to_value``)

    Every temporary object created here is removed before the function
    returns, so the NEXT beat never starts with earlier objects present.
    Math is verified deterministically (M.verify_kaprekar_step) — a wrong
    value raises instead of rendering.
    """
    total = _motion_default(duration, 3.0)
    from_value = str(from_value).zfill(ndigits)
    to_value = str(to_value).zfill(ndigits)
    desc = "".join(sorted(from_value, reverse=True))
    asc = "".join(sorted(from_value))
    v = M.verify_kaprekar_step(to_value, ndigits, from_value)
    if not v.ok:
        raise ValueError(
            "kaprekar math mismatch: " + "; ".join(f["detail"] for f in v.failures()))

    # phase weights (fractions of the total duration; they sum to exactly
    # 1.0 so the primitive consumes no more time than the compiler budgeted)
    w_show, w_sort, w_asc, w_eq, w_res_fade, w_res_ind, w_rem, w_morph = (
        0.14, 0.18, 0.10, 0.12, 0.10, 0.08, 0.10, 0.18)
    d_show = total * w_show
    d_sort = total * w_sort
    d_asc = total * w_asc
    d_eq = total * w_eq
    d_res = total * w_res_fade
    d_ind = total * w_res_ind
    d_rem = total * w_rem
    d_morph = total * w_morph

    # A — show input number (enter, or bring the SAME digits to from_value)
    digits = enter_number_main(scene, scene_state, from_value, ndigits,
                               duration=d_show)

    # B — physically reorder the SAME digits into descending order
    if _reading(digits) != desc:
        animate_digit_reorder(scene, digits, _reading(digits), desc,
                              duration=d_sort, stagger=0.12)
        scene_state.update("number_main", {"op": "sort_desc", "value": desc},
                           value=desc, mobject=digits)
        scene_state.record_update("number_main")

    # C — ascending order appears (temporary copy below the desc row)
    asc_row = make_digit_array(scene, asc, id_prefix="ascending")
    asc_row.next_to(digits, DOWN, buff=0.6)
    scene.play(FadeIn(asc_row), run_time=d_asc)
    scene_state.enter("ascending", "digit_array", value=asc, zone=Zone.SUPPORT,
                      persistent=False, mobject=asc_row)
    scene_state.record_enter("ascending")

    # D — subtraction constructs itself:  − 2345  ─────
    minus = Tex("-", font_size=_eq_size(), color=_color("secondary_text", "#9AA7B8"))
    minus.next_to(asc_row, LEFT, buff=0.3)
    line = Line(asc_row.get_left() + LEFT * 0.1,
                asc_row.get_right() + RIGHT * 0.1,
                color=_color("secondary_text", "#9AA7B8"), stroke_width=3)
    line.next_to(asc_row, DOWN, buff=0.2)
    equals = Tex("=", font_size=_eq_size(), color=_color("secondary_text", "#9AA7B8"))
    equals.next_to(line, RIGHT, buff=0.35)
    eq_group = VGroup(minus, line, equals)
    scene.play(FadeIn(eq_group), run_time=d_eq)
    scene_state.enter("equation", "equation", value=f"{desc} - {asc}",
                      zone=Zone.SUPPORT, persistent=False, mobject=eq_group)
    scene_state.record_enter("equation")

    # E — reveal the result in accent color
    result = Text(to_value, font=_font(), font_size=_digit_size(),
                  color=_accent(0))
    result.next_to(equals, RIGHT, buff=0.3)
    scene.play(FadeIn(result, scale=1.6), run_time=d_res)
    scene.play(Indicate(result, color=_accent(0)), run_time=d_ind)
    scene_state.enter("result", "result", value=to_value, zone=Zone.SUPPORT,
                      persistent=False, mobject=result)
    scene_state.record_enter("result")

    # F — remove the temporary equation (asc row, signs, result)
    scene.play(FadeOut(VGroup(asc_row, eq_group, result)), run_time=d_rem)
    for oid in ("ascending", "equation", "result"):
        scene_state.exit(oid)
        scene_state.record_exit(oid)

    # G — the main number becomes the next state (SAME digits morph)
    morph_digits_to(scene, digits, to_value, duration=d_morph)
    scene_state.update("number_main", {"op": "kaprekar_step", "to": to_value},
                       value=to_value, mobject=digits)
    scene_state.record_update("number_main")
    return digits


def morph_number(scene: Scene, scene_state: SceneState, oid: str,
                 from_value: str, to_value: str, ndigits: int = 4,
                 duration: float | None = None) -> VGroup:
    """Morph an existing number object's SAME digits to a new value."""
    obj = scene_state.get(oid)
    if obj is None or obj.exit_beat is not None or obj.mobject is None:
        raise ValueError(f"morph_number: {oid!r} is not on stage")
    to_value = str(to_value).zfill(ndigits)
    group = obj.mobject
    cur = _reading(group)
    if cur and cur != str(from_value).zfill(ndigits):
        raise ValueError(f"morph_number from {from_value!r} != current {cur!r}")
    morph_digits_to(scene, group, to_value, duration=duration)
    scene_state.update(oid, {"op": "morph", "to": to_value}, value=to_value,
                       mobject=group)
    scene_state.record_update(oid)
    return group


# ---------------------------------------------------------------------------
# Attractor diagram (verified trajectories)
# ---------------------------------------------------------------------------


def _verify_trajectory(traj: Sequence[str], ndigits: int) -> None:
    """Deterministic guard: every step must verify; must end at 6174."""
    if not traj:
        raise ValueError("empty trajectory")
    for a, b in zip(traj, traj[1:]):
        v = M.verify_kaprekar_step(str(b).zfill(ndigits), ndigits,
                                   str(a).zfill(ndigits))
        if not v.ok:
            raise ValueError(
                f"unverified trajectory step {a} -> {b}: "
                + "; ".join(f["detail"] for f in v.failures()))
    if str(traj[-1]).zfill(ndigits) != str(6174).zfill(ndigits):
        raise ValueError(
            f"trajectory {list(traj)} does not converge to 6174")


def AttractorDiagram(scene: Scene, scene_state: SceneState,
                     trajectories: Sequence[Sequence[str]],
                     ndigits: int = 4,
                     duration: float | None = None) -> VGroup:
    """Animate VERIFIED Python trajectories converging on 6174.

    ``trajectories`` is a list of sequences (each a list of digit strings
    ending at 6174).  Every step is re-verified deterministically here —
    unverified input raises ValueError (never rendered).

    Each trajectory gets its own color-coded lane; the lanes step through
    their orbits and then converge onto the attractor.  Lanes are temporary
    (ENTER/EXIT recorded); the attractor persists.
    """
    total = _motion_default(duration, 3.2)
    for traj in trajectories:
        _verify_trajectory(traj, ndigits)

    # attractor (persistent focal)
    attractor = enter_attractor(scene, scene_state, str(6174).zfill(ndigits),
                                duration=total * 0.08)
    n = len(trajectories)
    lane_groups: list[VGroup] = []
    step_rt = max(0.05, total * 0.06)
    for i, traj in enumerate(trajectories):
        lane = make_digit_array(scene, traj[0], id_prefix=f"lane_{i}")
        lane.move_to(zone_offset(Zone.LEFT) + UP * ((n - 1) / 2 - i) * 1.1)
        for dg in lane:
            dg.set_color(_accent(i + 1))
        scene.play(FadeIn(lane), run_time=total * 0.06)
        scene_state.enter(f"lane_{i}", "digit_array", value=traj[0],
                          zone=Zone.LEFT, persistent=False, mobject=lane)
        scene_state.record_enter(f"lane_{i}")
        lane_groups.append(lane)
        for a, b in zip(traj, traj[1:]):
            morph_digits_to(scene, lane, str(b).zfill(ndigits), duration=step_rt)
            scene_state.update(f"lane_{i}", {"op": "converge_step", "to": b},
                               value=str(b).zfill(ndigits), mobject=lane)
            scene_state.record_update(f"lane_{i}")

    # converge: lanes move onto the attractor, then exit
    anims = []
    for i, lane in enumerate(lane_groups):
        lane.generate_target()
        lane.target.move_to(attractor.get_center() +
                            UP * ((n - 1) / 2 - i) * 0.5 + LEFT * 1.2)
        anims.append(MoveToTarget(lane))
    scene.play(*anims, run_time=total * 0.2)
    scene.play(Indicate(attractor, color=_accent(0)), run_time=total * 0.08)
    scene.play(FadeOut(VGroup(*lane_groups)), run_time=total * 0.1)
    for i in range(n):
        scene_state.exit(f"lane_{i}")
        scene_state.record_exit(f"lane_{i}")
    return attractor


# ---------------------------------------------------------------------------
# Fixed-point reveal (genuine)
# ---------------------------------------------------------------------------


def FixedPointReveal(scene: Scene, scene_state: SceneState,
                     value: str = "6174", duration: float | None = None) -> VGroup:
    """A genuine fixed-point reveal:

      1. converge paths stream into 6174          (temporary)
      2. 6174 dominates: scales up + is indicated (UPDATE attractor)
      3. surrounding weight is reduced            (EXIT lingering temps)
      4. camera focuses on the constant
      5. then recedes to restore the frame
    """
    total = _motion_default(duration, 2.5)
    value = str(value).zfill(4)
    attractor = enter_attractor(scene, scene_state, value, duration=total * 0.1)

    # 1 — converge paths (controlled, purposeful dots)
    from manim import Dot
    paths = VGroup()
    for i in range(24):
        dot = Dot(radius=0.035, color=_accent(i % 6))
        dot.move_to(LEFT * 5 + UP * ((i % 9) - 4) * 0.6 + DOWN * ((i % 3) - 1) * 0.4)
        paths.add(dot)
    scene.play(FadeIn(paths), run_time=total * 0.15)
    scene_state.enter("converge_paths", "particles", value="paths",
                      zone=Zone.LEFT, persistent=False, mobject=paths)
    scene_state.record_enter("converge_paths")
    scene.play(*[p.animate.move_to(attractor.get_center() +
                                   UP * (0.15 * ((i % 5) - 2)))
                 for i, p in enumerate(paths)], run_time=total * 0.35)

    # 2 — dominate 6174
    attractor.generate_target()
    attractor.target.scale(1.6)
    scene.play(MoveToTarget(attractor), run_time=total * 0.18)
    scene.play(Indicate(attractor, color=_color("success", "#81C784")),
               run_time=total * 0.12)
    scene_state.update("attractor", {"op": "dominate"}, value=value,
                       mobject=attractor)
    scene_state.record_update("attractor")

    # 3 — reduce surrounding weight: any lingering temporary leaves
    for obj in list(scene_state.active()):
        if obj.id != "attractor" and obj.temporary and obj.mobject is not None:
            scene.play(FadeOut(obj.mobject), run_time=total * 0.1)
            scene_state.exit(obj.id)
            scene_state.record_exit(obj.id)

    # 4 — camera focus
    frame = getattr(scene.camera, "frame", None) if hasattr(scene, "camera") else None
    if frame is not None:
        scene.play(frame.animate.scale(0.72).move_to(attractor.get_center()),
                   run_time=total * 0.18)

    # 5 — recede
    if frame is not None:
        scene.play(frame.animate.scale(1 / 0.72), run_time=total * 0.15)
    return attractor


# ---------------------------------------------------------------------------
# Exception visual (repeated digits: 1111 -> 0000 -> 0000)
# ---------------------------------------------------------------------------


def ExceptionVisual(scene: Scene, scene_state: SceneState,
                    value: str = "1111", ndigits: int = 4,
                    duration: float | None = None) -> None:
    """Visualize the repeated-digit exception as a clean separate state.

    1111 -> 0000 -> 0000: the rule yields 0000 once, and repeating it still
    yields 0000 (nothing converges to 6174).  Everything entered here is
    removed before the function returns — the exception never bleeds into
    the next beat.
    """
    total = _motion_default(duration, 3.2)
    value = str(value).zfill(ndigits)
    if len(set(value)) != 1:
        raise ValueError(
            f"ExceptionVisual expects repeated digits, got {value!r}")
    desc = "".join(sorted(value, reverse=True))
    asc = "".join(sorted(value))
    diff = str(int(desc) - int(asc)).zfill(ndigits)  # 0000

    digits = make_digit_array(scene, value, id_prefix="exception")
    digits.move_to(zone_offset(Zone.CENTER))
    scene.play(FadeIn(digits), run_time=total * 0.15)
    scene_state.enter("exception", "digit_array", value=value, zone=Zone.CENTER,
                      persistent=False, mobject=digits)
    scene_state.record_enter("exception")

    eq = Tex(f"{value} - {value} = {diff}", font_size=_eq_size(),
             color=_color("secondary_text", "#9AA7B8"))
    eq.next_to(digits, DOWN, buff=0.8)
    scene.play(FadeIn(eq), run_time=total * 0.12)
    scene_state.enter("exception_equation", "equation", value=f"{value} - {value}",
                      zone=Zone.SUPPORT, persistent=False, mobject=eq)
    scene_state.record_enter("exception_equation")

    # step 1: morph the SAME digits to 0000
    morph_digits_to(scene, digits, diff, duration=total * 0.2)
    scene_state.update("exception", {"op": "kaprekar", "to": diff},
                       value=diff, mobject=digits)
    scene_state.record_update("exception")

    # step 2: repeating the rule still yields 0000 (stuck, not 6174)
    eq2 = Tex(f"{diff} - {diff} = {diff}", font_size=_eq_size(),
              color=_color("danger", "#E57373"))
    eq2.move_to(eq.get_center())
    scene.play(Transform(eq, eq2), run_time=total * 0.18)
    scene.play(Indicate(digits, color=_color("danger", "#E57373")),
               run_time=total * 0.12)
    scene_state.update("exception_equation", {"op": "stuck", "to": diff},
                       value=diff, mobject=eq)
    scene_state.record_update("exception_equation")

    # clean removal — nothing persists
    scene.play(FadeOut(VGroup(digits, eq)), run_time=total * 0.12)
    for oid in ("exception", "exception_equation"):
        scene_state.exit(oid)
        scene_state.record_exit(oid)


# ---------------------------------------------------------------------------
# Convergence particles (targeted, state-aware)
# ---------------------------------------------------------------------------


def ConvergenceParticles(scene: Scene, scene_state: SceneState,
                         target_oid: str, n: int = 40,
                         duration: float = 1.6) -> None:
    """Controlled convergence of particles toward a named target object.

    Must serve explanation (numbers/objects converging), never random
    decoration.  Particles are temporary (ENTER/EXIT recorded).
    """
    from manim import Dot
    target = scene_state.get(target_oid)
    if target is None or target.exit_beat is not None or target.mobject is None:
        raise ValueError(f"ConvergenceParticles: target {target_oid!r} not on stage")
    d = _motion_default(duration, 1.6)
    pts = VGroup()
    for i in range(n):
        dot = Dot(radius=0.03, color=_accent(i % 6))
        dot.move_to(LEFT * 4 + UP * (3 * ((i % 5) - 2) / 4) + DOWN * (0.5 * (i % 3)))
        pts.add(dot)
    scene.play(FadeIn(pts), run_time=d * 0.15)
    scene_state.enter("particles", "particles", value="converge",
                      zone=Zone.LEFT, persistent=False, mobject=pts)
    scene_state.record_enter("particles")
    scene.play(*[p.animate.move_to(target.mobject.get_center() +
                                   UP * (0.2 * ((i % 4) - 1.5)))
                 for i, p in enumerate(pts)], run_time=d * 0.65)
    scene_state.update("particles", {"op": "converge"}, mobject=pts)
    scene_state.record_update("particles")
    scene.play(FadeOut(pts), run_time=d * 0.2)
    scene_state.exit("particles")
    scene_state.record_exit("particles")


# ---------------------------------------------------------------------------
# Narrative primitives (state-aware, self-cleaning via compiler sweep)
# ---------------------------------------------------------------------------


def _enter_text(scene: Scene, scene_state: SceneState | None, oid: str,
                text: str, color: str, font_size: int,
                run_time: float, zone: Zone = Zone.CENTER):
    from engine.qa.fade import clamp_fade
    mob = Text(text, font=_font(), font_size=font_size, color=color)
    mob.move_to(zone_offset(zone))
    # wave-2 fade rule (a): text fades complete in <=0.4s so no 1fps
    # review sample ever catches a <=50%-opacity ghost
    scene.play(FadeIn(mob), run_time=clamp_fade(run_time))
    if scene_state is not None:
        scene_state.enter(oid, "text", value=text, zone=zone,
                          persistent=False, mobject=mob)
        scene_state.record_enter(oid)
    return mob


def QuestionReveal(scene: Scene, question: str,
                   scene_state: SceneState | None = None,
                   duration: float | None = None) -> None:
    d = _motion_default(duration, 0.9)
    _enter_text(scene, scene_state, "question", question, _accent(4),
                get_style().get("font_sizes", {}).get("heading", 40),
                d, Zone.CENTER)


def ClaimReveal(scene: Scene, claim: str,
                scene_state: SceneState | None = None,
                duration: float | None = None) -> None:
    d = _motion_default(duration, 0.7)
    _enter_text(scene, scene_state, "claim", claim,
                _color("primary_text", "#F5F7FA"),
                get_style().get("font_sizes", {}).get("body", 32), d,
                Zone.BOTTOM)


def KineticTypography(scene: Scene, word: str, color: str | None = None,
                      from_left: bool = False,
                      scene_state: SceneState | None = None,
                      duration: float | None = None) -> None:
    d = _motion_default(duration, 0.9)
    text = _enter_text(scene, scene_state, "kinetic", word, color or _accent(5),
                       get_style().get("font_sizes", {}).get("heading", 40),
                       d * 0.6, Zone.CENTER)
    if from_left:
        text.shift(LEFT * 4)
    scene.play(Indicate(text), run_time=d * 0.4)


def Comparison(scene: Scene, left_label: str, right_label: str,
               value_left: str, value_right: str,
               scene_state: SceneState | None = None,
               duration: float | None = None) -> None:
    d = _motion_default(duration, 0.9)
    left = Text(f"{left_label}: {value_left}", font=_font(),
                font_size=get_style().get("font_sizes", {}).get("body", 28),
                color=_accent(0))
    right = Text(f"{right_label}: {value_right}", font=_font(),
                 font_size=get_style().get("font_sizes", {}).get("body", 28),
                 color=_accent(2))
    left.shift(LEFT * 3)
    right.shift(RIGHT * 3)
    scene.play(FadeIn(left), FadeIn(right), run_time=d)
    if scene_state is not None:
        group = VGroup(left, right)
        scene_state.enter("comparison", "text", value=f"{value_left} / {value_right}",
                          zone=Zone.CENTER, persistent=False, mobject=group)
        scene_state.record_enter("comparison")


def CycleReveal(scene: Scene, cycle: str,
                scene_state: SceneState | None = None,
                duration: float | None = None) -> None:
    d = _motion_default(duration, 0.8)
    _enter_text(scene, scene_state, "cycle", cycle, _accent(1),
                get_style().get("font_sizes", {}).get("body", 30), d,
                Zone.CENTER)


# ---------------------------------------------------------------------------
# Registry for the compiler
# ---------------------------------------------------------------------------

PRIMITIVES: dict[str, object] = {
    "apply_kaprekar_step": apply_kaprekar_step,
    "animate_digit_reorder": animate_digit_reorder,
    "morph_number": morph_number,
    "enter_number_main": enter_number_main,
    "enter_attractor": enter_attractor,
    "reorder_digits": reorder_digits,
    "exit_object": exit_object,
    "AttractorDiagram": AttractorDiagram,
    "FixedPointReveal": FixedPointReveal,
    "ExceptionVisual": ExceptionVisual,
    "ConvergenceParticles": ConvergenceParticles,
    "HighlightTarget": HighlightTarget,
    "QuestionReveal": QuestionReveal,
    "ClaimReveal": ClaimReveal,
    "KineticTypography": KineticTypography,
    "Comparison": Comparison,
    "CycleReveal": CycleReveal,
}
