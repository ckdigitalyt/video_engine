"""Correctness tests for the state-aware Kaprekar primitives + compiler.

Covers the correctness-sprint requirements:
  (a) digit reorder keeps the SAME physical Mobjects (no duplicates/ghosts)
  (b) the compiler raises CompileError on untargeted / no-op transforms and
      on unmapped types (no silent no-ops, no dead `pass` branches)
  (c) SceneState records ENTER / UPDATE / EXIT correctly per beat

Rendering-free: a StubScene records play() calls so pure-Python assertions
work headlessly (manim never has to draw a frame).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from manim import MoveToTarget, Text, VGroup, RIGHT

from engine.primitives.manim_primitives import (
    animate_digit_reorder,
    apply_kaprekar_step,
    make_digit_array,
    morph_digits_to,
    _reorder_permutation,
)
from engine.renderers.manim.compiler import (
    CompileError,
    compile_to_file,
    emit_scene,
)
from engine.visuals.scene_state import SceneState, Zone


# ---------------------------------------------------------------------------
# Stub scene — records plays instead of rendering
# ---------------------------------------------------------------------------

class StubScene:
    """Minimal Scene stand-in: records play() calls, applies nothing."""

    def __init__(self) -> None:
        self.played: list = []
        self.added: list = []

    def play(self, *anims, **kwargs) -> None:
        self.played.append((list(anims), kwargs))

    def wait(self, t: float) -> None:
        self.played.append(("wait", t))

    def add(self, *mobs) -> None:
        self.added.extend(mobs)


def _apply_targets(digits: VGroup) -> None:
    """Manually apply each digit's generated target (stub scene won't)."""
    for dg in digits:
        if getattr(dg, "target", None) is not None:
            dg.move_to(dg.target.get_center())


def _reading(digits: VGroup) -> str:
    return "".join(d.text for d in sorted(digits,
                                          key=lambda d: d.get_center()[0]))


# ---------------------------------------------------------------------------
# (a) digit reorder keeps the SAME physical Mobjects
# ---------------------------------------------------------------------------

def test_reorder_keeps_same_mobjects():
    scene = StubScene()
    digits = make_digit_array(scene, "3524")
    ids_before = [id(d) for d in digits]
    vids_before = [d.vid for d in digits]

    animate_digit_reorder(scene, digits, "3524", "5432", duration=0.5)

    # same physical objects — no duplicates, no ghosts.
    # NB: submobjects are intentionally reordered to the VISUAL target
    # order (so `_reading(group)` reflects the on-screen arrangement for
    # subsequent beats), so identity is compared as a multiset, not by
    # position.
    assert sorted(id(d) for d in digits) == sorted(ids_before)
    assert sorted(d.vid for d in digits) == sorted(vids_before)
    assert len(digits) == 4
    assert len(scene.added) == 0          # nothing new was added to stage
    # only MoveToTarget animations were played (no FadeIn of new copies)
    anims = [a for played, _ in scene.played for a in played]
    assert anims and all(isinstance(a, MoveToTarget) for a in anims)

    # final state == target (apply targets manually since stub doesn't move)
    _apply_targets(digits)
    assert _reading(digits) == "5432"


def test_reorder_permutation_mapping():
    assert _reorder_permutation("3524", "5432") == [1, 3, 0, 2]
    assert _reorder_permutation("1111", "1111") == [0, 1, 2, 3]
    assert _reorder_permutation("1222", "2221") == [1, 2, 3, 0]
    with pytest.raises(ValueError):
        _reorder_permutation("3524", "5433")  # not a permutation


def test_morph_keeps_same_mobjects():
    scene = StubScene()
    digits = make_digit_array(scene, "3087")
    ids_before = [id(d) for d in digits]
    morph_digits_to(scene, digits, "8352", duration=0.5)
    assert [id(d) for d in digits] == ids_before
    assert _reading(digits) == "8352"


# ---------------------------------------------------------------------------
# (b) compiler: no untargeted / no-op transforms; unmapped types raise
# ---------------------------------------------------------------------------

def _vs(beats):
    return {"version": "v1", "beats": beats}


def _beat(transformations, objects=None, visual_type="digit_sort",
          duration=2.0, narration=""):
    return {
        "beat_id": "b001",
        "intent": "demonstrate_transformation",
        "narration": narration,
        "duration": duration,
        "objects": objects or [],
        "transformations": transformations,
        "visual_type": visual_type,
    }


def test_compiler_untargeted_transform_raises():
    # a real transform (from/to present) with NO target object anywhere
    vs = _vs([_beat([{"type": "sort", "from": "3524", "to": "5432"}], objects=[])])
    with pytest.raises(CompileError):
        emit_scene(vs)


def test_compiler_unmapped_type_raises():
    vs = _vs([_beat([{"type": "banana", "from": "1", "to": "2"}],
                    objects=[{"id": "number_main", "type": "number",
                              "value": "3524"}])])
    with pytest.raises(CompileError):
        emit_scene(vs)


def test_compiler_duration_overflow_raises():
    # beat too short for even the minimum animation duration
    vs = _vs([_beat([{"type": "sort", "from": "3524", "to": "5432"}],
                    objects=[{"id": "number_main", "type": "number",
                              "value": "3524"}],
                    duration=0.2)])
    with pytest.raises(CompileError):
        emit_scene(vs)


def test_compiler_math_guard_raises():
    # subtract with a wrong result must be rejected by the math guard
    vs = _vs([_beat([{"type": "subtract", "from": "3524", "to": "9999"}],
                    objects=[{"id": "number_main", "type": "number",
                              "value": "3524"}],
                    visual_type="subtract")])
    with pytest.raises(CompileError):
        emit_scene(vs)


def test_compiler_emits_state_aware_scene():
    vs = _vs([
        _beat([{"type": "highlight", "from": "3524", "to": "3524"}],
              objects=[{"id": "number_main", "type": "number", "value": "3524"}],
              visual_type="highlight"),
        _beat([{"type": "subtract", "from": "3524", "to": "3087"}],
              objects=[{"id": "number_main", "type": "number", "value": "3524"}],
              visual_type="subtract", duration=3.0),
    ])
    src = emit_scene(vs, "KaprekarTestScene")
    # scene-state lifecycle is wired into the emitted source
    assert "self._state = SceneState()" in src
    assert "self._state.begin_beat" in src
    assert "self._state.record_persist()" in src
    assert "apply_kaprekar_step(self, self._state" in src
    assert "enter_number_main(self, self._state" in src
    # no silent no-op comments / dead code survived
    assert "no-op" not in src


def test_compile_to_file_writes_source(tmp_path):
    vs = _vs([_beat([{"type": "highlight", "from": "3524", "to": "3524"}],
                    objects=[{"id": "number_main", "type": "number",
                              "value": "3524"}],
                    visual_type="highlight")])
    out = compile_to_file(vs, tmp_path / "scene.py", "KaprekarTestScene")
    assert out.exists()
    assert "class KaprekarTestScene" in out.read_text()


# ---------------------------------------------------------------------------
# (c) SceneState records ENTER / UPDATE / EXIT correctly
# ---------------------------------------------------------------------------

def test_scene_state_records_enter_update_exit():
    st = SceneState()
    st.begin_beat("b001")
    st.enter("number_main", "number", value="3524", zone=Zone.FOCUS,
             persistent=True)
    st.record_enter("number_main")
    st.update("number_main", {"op": "sort", "to": "5432"}, value="5432")
    st.record_update("number_main")
    st.enter("equation", "equation", persistent=False)
    st.record_enter("equation")
    st.exit("equation")
    st.record_exit("equation")
    st.record_persist()

    log = st.to_log()
    assert log[0]["entering"][0]["id"] == "number_main"
    assert log[0]["updating"][0]["id"] == "number_main"
    assert log[0]["exiting"][0]["id"] == "equation"
    assert st.object_counts() == {"enters": 2, "updates": 1, "exits": 1}
    # persistent object is still active after its beat
    assert st.get("number_main").exit_beat is None
    assert st.get("equation").exit_beat is not None


def test_apply_kaprekar_step_records_clean_lifecycle():
    """A full step must ENTER the number, UPDATE it to the result, and EXIT
    every temporary (ascending/equation/result) before the beat ends — the
    next beat cannot inherit leftovers."""
    scene = StubScene()
    st = SceneState()
    st.begin_beat("b001")
    digits = apply_kaprekar_step(scene, st, "3524", "3087", ndigits=4,
                                 duration=1.0)

    # the main number persists and holds the result value
    main = st.get("number_main")
    assert main is not None
    assert main.exit_beat is None
    assert main.value == "3087"
    # temporaries entered AND exited within the beat
    for oid in ("ascending", "equation", "result"):
        obj = st.get(oid)
        assert obj is not None, f"{oid} should have been recorded"
        assert obj.exit_beat is not None, f"{oid} should have exited"
    # same physical digits survive the whole step
    assert len(digits) == 4
    assert all(d.vid.startswith("digit_") for d in digits)

    counts = st.object_counts()
    assert counts["enters"] >= 1
    assert counts["updates"] >= 1
    assert counts["exits"] >= 3  # ascending + equation + result

    # next beat begins with ONLY the persistent number on stage
    st.begin_beat("b002")
    assert st.ids() == ["number_main"]


def test_apply_kaprekar_step_math_guard():
    scene = StubScene()
    st = SceneState()
    st.begin_beat("b001")
    with pytest.raises(ValueError):
        apply_kaprekar_step(scene, st, "3524", "9999", ndigits=4,
                            duration=1.0)
