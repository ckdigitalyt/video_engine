"""Manim primitive library — the trusted rendering layer (directive §8).

DeepSeek decides WHAT/WHY/WHEN; these primitives decide HOW.  They are
deterministic, reusable, and independently testable.  They implement object
continuity: every digit has a persistent ID so it physically transforms
rather than being destroyed/recreated.
"""

from __future__ import annotations

import re
from typing import Iterable

from manim import (
    DOWN, LEFT, RIGHT, UP,
    Animation, FadeIn, FadeOut, Indicate, MoveToTarget, Scene, Tex, Text,
    Transform, VGroup,
)

from engine.config.loader import get_style


def _color(key: str, fallback: str) -> str:
    return get_style().get(key, fallback)


def _accent(i: int) -> str:
    accents = get_style().get("accent_colors", ["#4FC3F7"])
    return accents[i % len(accents)]


# ──────────────────────────────────────────────────────────────────────────
# Mathematical primitives
# ──────────────────────────────────────────────────────────────────────────
def make_digit_array(scene: Scene, value: str, id_prefix: str = "digit") -> VGroup:
    """Create a VGroup of digit Mobjects with persistent ids (digit_0..n).

    Returns a VGroup whose submobjects each carry `.vid` = f"{id_prefix}_{i}".
    """
    group = VGroup()
    for i, ch in enumerate(value):
        digit = Text(ch, font=get_style().get("font_family", "DejaVu Sans"),
                     font_size=get_style().get("font_sizes", {}).get("digit", 64),
                     color=_color("primary_text", "#F5F7FA"))
        digit.vid = f"{id_prefix}_{i}"
        group.add(digit)
    group.arrange(RIGHT, buff=0.2)
    return group


def DigitSort(scene: Scene, digits: VGroup, target_order: str,
              highlight_final: bool = True, duration: float | None = None) -> None:
    """Physically reorder digits into `target_order` by swapping into place.

    Keeps the same physical digit Mobjects (object continuity); they move,
    never get recreated.
    """
    style_motion = get_style().get("motion", {})
    d = duration or style_motion.get("default_duration", 0.8)
    # Convert target string to indices among current digit values
    current = "".join(dg.text for dg in digits)
    target = list(target_order)
    # Build a permutation of existing mobjects
    pool = list(digits)
    order: list = []
    used = [False] * len(pool)
    for ch in target:
        for idx, dg in enumerate(pool):
            if dg.text == ch and not used[idx]:
                order.append(dg)
                used[idx] = True
                break
    if len(order) != len(digits):
        raise ValueError(f"Cannot reorder {current} -> {target_order}")
    for dg in digits:
        dg.target = None
    for i, dg in enumerate(order):
        dg.generate_target()
        dg.target.move_to(digits[i].get_center())
    # Animate all to targets simultaneously (physical swap)
    anims = [MoveToTarget(dg) for dg in order]
    scene.play(*anims, run_time=d)
    if highlight_final:
        scene.play(Indicate(VGroup(*order), color=_accent(0)), run_time=d * 0.5)


def DigitMorph(scene: Scene, mob: object, new_text: str, color: str | None = None,
               duration: float | None = None) -> None:
    """Morph a single digit mobject to new_text (or recolor)."""
    style_motion = get_style().get("motion", {})
    d = duration or style_motion.get("default_duration", 0.8)
    scene.play(Transform(mob, Text(new_text, font=get_style().get("font_family", "DejaVu Sans"),
                                       font_size=mob.height * 2 if mob.height else 64,
                                       color=color or mob.color)), run_time=d)


def KaprekarStep(scene: Scene, from_value: str, to_value: str,
                 ndigits: int = 4) -> VGroup:
    """Visualize one full Kaprekar step: descend, ascend, subtract -> result.

    The digits physically reorder into descending order, the ascending order
    appears beneath, the subtraction constructs itself, and the result
    emerges in accent color.
    """
    desc = "".join(sorted(from_value, reverse=True))
    asc = "".join(sorted(from_value))
    assert str(int(desc) - int(asc)).zfill(ndigits) == to_value, (
        f"math mismatch: {desc}-{asc} != {to_value}")

    # 1) Show the input number
    digits = make_digit_array(scene, from_value)
    scene.play(FadeIn(digits), run_time=0.4)

    # 2) Physical reorder into descending order (object continuity)
    desc_order = make_digit_array(scene, desc)
    anims = []
    pool = list(digits)
    used = [False] * len(pool)
    for ch in desc:
        for idx, dg in enumerate(pool):
            if dg.text == ch and not used[idx]:
                dg.generate_target()
                dg.target.move_to(desc_order[idx].get_center())
                anims.append(MoveToTarget(dg))
                used[idx] = True
                break
    scene.play(*anims, run_time=0.7)

    # 3) Subtraction constructs itself
    sub = Tex(
        f"{desc} - {asc} = ",
        font_size=get_style().get("font_sizes", {}).get("equation", 44),
    )
    sub.next_to(digits, DOWN, buff=0.6)
    scene.play(FadeIn(sub), run_time=0.4)

    # 4) Result emerges in accent color
    result = Text(
        to_value,
        font=get_style().get("font_family", "DejaVu Sans"),
        font_size=get_style().get("font_sizes", {}).get("digit", 64),
        color=_accent(0),
    )
    result.align_to(sub, LEFT).shift(RIGHT * 2.2)
    scene.play(FadeIn(result), run_time=0.5)
    return digits


def SubtractAndResort(scene: Scene, from_value: str, to_value: str,
                      ndigits: int = 4) -> None:
    """KaprekarStep with explicit subtraction construction."""
    KaprekarStep(scene, from_value, to_value, ndigits)


def AttractorOrbit(scene: Scene, starts: Iterable[str], ndigits: int = 4) -> None:
    """Show multiple starting numbers converging to the attractor (6174)."""
    for s in starts:
        digits = make_digit_array(scene, s)
        scene.play(FadeIn(digits), run_time=0.4)
        cur = s
        for _ in range(6):
            desc = "".join(sorted(cur, reverse=True))
            asc = "".join(sorted(cur))
            nxt = str(int(desc) - int(asc)).zfill(ndigits)
            scene.play(Transform(digits.copy(), make_digit_array(scene, nxt)),
                       run_time=0.5)
            cur = nxt
            if cur == str(6174).zfill(ndigits):
                break
        scene.play(FadeOut(digits), run_time=0.4)


def FixedPointReveal(scene: Scene, value: str = "6174") -> None:
    """A satisfying reveal/impact for the fixed point."""
    text = Text(value, font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("digit", 72),
                color=_accent(0))
    scene.play(FadeIn(text, scale=2), run_time=0.8)
    scene.play(Indicate(text, color=_color("success", "#81C784")), run_time=0.5)
    scene.wait(0.4)


def ConvergenceParticles(scene: Scene, target: object, n: int = 40,
                         duration: float = 2.0) -> None:
    """Controlled convergence of small particles toward a target — must serve
    explanation (numbers/objects converging), never random decoration."""
    from manim import Dot, always_redraw
    pts = []
    for _ in range(n):
        d = Dot(radius=0.03, color=_accent(1))
        d.move_to(LEFT * 4 + UP * (3 * ((_ % 5) - 2) / 4) + DOWN * (0.5 * (_ % 3)))
        pts.append(d)
        scene.add(d)
    scene.play(*[d.animate.move_to(target.get_center() + UP * (0.2 * ((i % 4) - 1.5))) for i, d in enumerate(pts)],
               run_time=duration)
    scene.play(FadeOut(VGroup(*pts)), run_time=0.5)


# ──────────────────────────────────────────────────────────────────────────
# Narrative primitives
# ──────────────────────────────────────────────────────────────────────────
def QuestionReveal(scene: Scene, question: str) -> None:
    text = Text(question, font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("heading", 40),
                color=_accent(4))
    scene.play(FadeIn(text), run_time=0.6)
    scene.wait(0.3)


def ClaimReveal(scene: Scene, claim: str) -> None:
    text = Text(claim, font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("body", 32),
                color=_color("primary_text", "#F5F7FA"))
    scene.play(FadeIn(text), run_time=0.5)
    scene.wait(0.2)


def KineticTypography(scene: Scene, word: str, color: str | None = None,
                      from_left: bool = False) -> None:
    """Word reveal with scale — kinetic emphasis for important narration."""
    text = Text(word, font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("heading", 40),
                color=color or _accent(5))
    if from_left:
        text.shift(LEFT * 4)
    scene.play(FadeIn(text, scale=3), run_time=0.5)
    scene.play(Indicate(text), run_time=0.4)


def Comparison(scene: Scene, left_label: str, right_label: str, value_left: str,
               value_right: str) -> None:
    left = Text(f"{left_label}: {value_left}", font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("body", 28),
                color=_accent(0))
    right = Text(f"{right_label}: {value_right}", font=get_style().get("font_family", "DejaVu Sans"),
                 font_size=get_style().get("font_sizes", {}).get("body", 28),
                 color=_accent(2))
    left.shift(LEFT * 3)
    right.shift(RIGHT * 3)
    scene.play(FadeIn(left), FadeIn(right), run_time=0.6)
    scene.wait(0.3)


def CycleReveal(scene: Scene, cycle: str) -> None:
    text = Text(cycle, font=get_style().get("font_family", "DejaVu Sans"),
                font_size=get_style().get("font_sizes", {}).get("body", 30),
                color=_accent(1))
    scene.play(FadeIn(text), run_time=0.5)
    scene.wait(0.3)


# ──────────────────────────────────────────────────────────────────────────
# Registry for the compiler
# ──────────────────────────────────────────────────────────────────────────
PRIMITIVES: dict[str, object] = {
    "DigitSort": DigitSort,
    "DigitMorph": DigitMorph,
    "KaprekarStep": KaprekarStep,
    "SubtractAndResort": SubtractAndResort,
    "AttractorOrbit": AttractorOrbit,
    "FixedPointReveal": FixedPointReveal,
    "ConvergenceParticles": ConvergenceParticles,
    "QuestionReveal": QuestionReveal,
    "ClaimReveal": ClaimReveal,
    "KineticTypography": KineticTypography,
    "Comparison": Comparison,
    "CycleReveal": CycleReveal,
}
