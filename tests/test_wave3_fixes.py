"""Wave-3 fixes (glm_review_v4 remaining issues, 2026-08-29).

1. Entity ids must NEVER render as on-screen text (payoff card garbled
   label blocker) — reveal falls back to explicit value only.
2. Motion tweens must produce real per-frame pixel change — trackers are
   scene members now, the generated scene is a MovingCameraScene, and
   the Gabriel plan tweens only params with a visible hook.
3. Packaging (thumbnail.jpg) emits on every render run, not only full
   QA PASS.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from manim import Scene, Text, tempconfig

from engine.visuals.world_director import build_visualspec
from engine.world.world_model import WorldState


# ── helpers ───────────────────────────────────────────────────────────
def _gabriel_world() -> WorldState:
    return WorldState.from_dict({
        "topic": "gabriel's horn",
        "entities": [
            {"id": "horn", "type": "horn", "properties": {}},
        ],
        "hero_mechanism": {"concept": "painter's paradox",
                           "visualization": "painter_paradox_fill",
                           "objects": ["horn"]},
    })


def _render_scene(construct_fn) -> Scene:
    """Render a tiny scene headless (dry_run) and return the Scene."""
    holder = {}

    class _T(Scene):
        def construct(self):
            holder["scene"] = self
            construct_fn(self)

    with tempconfig({"dry_run": True, "quality": "low_quality",
                     "disable_caching": True}):
        _T().render()
    return holder["scene"]


def _text_strings(scene: Scene) -> list[str]:
    out = []
    for mob in scene.mobjects:
        for m in mob.get_family():
            if isinstance(m, Text):
                out.append(str(getattr(m, "text", "")))
    return out


def _frame_width() -> float:
    from manim import config
    return float(config.frame_width)


def _norm(texts: list[str]) -> list[str]:
    """manim strips spaces inside Text.text — compare space-free."""
    return ["".join(t.split()) for t in texts]


def _one_beat_spec(params: list[dict], actions: list[dict],
                   objects: list[dict], duration: float = 3.0) -> dict:
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    vs["beats"] = [{
        "beat_id": "b001", "intent": "demonstrate_transformation",
        "role": "change_variable", "narration": "fill", "duration":
        duration, "importance": "medium", "objects": objects,
        "transformations": [], "semantic_actions": actions,
        "visual_type": "simulation", "camera": {}, "kinetic_words": [],
        "explanation_score": 5, "text_primary": False,
        "scene_params": params,
    }]
    return vs


# ── FIX 1: entity ids never render as on-screen text ──────────────────
def test_materialize_payoff_renders_text_not_entity_id():
    from engine.primitives.world_primitives import materialize_entity
    from engine.visuals.scene_state import SceneState

    def body(scene):
        st = SceneState()
        st.begin_beat("b001")
        materialize_entity(scene, st, {
            "id": "some_debug_id", "type": "payoff",
            "properties": {"text": "V = π, A = ∞"}}, duration=0.8)

    texts = _norm(_text_strings(_render_scene(body)))
    assert any("V=π" in t for t in texts)
    assert not any("some_debug_id" in t for t in texts)


def test_materialize_text_entity_without_text_renders_nothing():
    from engine.primitives.world_primitives import materialize_entity
    from engine.visuals.scene_state import SceneState

    def body(scene):
        st = SceneState()
        st.begin_beat("b001")
        materialize_entity(scene, st, {
            "id": "some_debug_id", "type": "payoff",
            "properties": {}}, duration=0.5)

    scene = _render_scene(body)
    assert _text_strings(scene) == []          # nothing on screen
    assert scene is not None
    # state record exists so later actions resolve, but no mobject
    assert "some_debug_id" not in " ".join(_text_strings(scene))


def test_reveal_uses_value_not_id_or_internal_label():
    from engine.primitives.world_primitives import apply_action, \
        materialize_entity
    from engine.visuals.scene_state import SceneState

    def body(scene):
        st = SceneState()
        st.begin_beat("b001")
        materialize_entity(scene, st, {
            "id": "payoff_card", "type": "payoff",
            "properties": {"text": "V = π, A = ∞"}}, duration=0.5)
        apply_action(scene, st, {
            "action": "reveal", "target": "payoff_card",
            "params": {"value": "But how can π paint cover ∞ area?",
                       "label": "you decide"}},
            {"entities": []}, duration=0.7)

    texts = _norm(_text_strings(_render_scene(body)))
    assert any("Buthowcanπ" in t for t in texts)
    assert not any("payoff_card" in t for t in texts)
    assert not any("youdecide" in t for t in texts)
    # in-place swap on the existing card — exactly ONE text layer left
    assert len(texts) == 1


def test_reveal_without_explicit_text_renders_nothing():
    from engine.primitives.world_primitives import apply_action
    from engine.visuals.scene_state import SceneState

    def body(scene):
        st = SceneState()
        st.begin_beat("b001")
        st.enter("some_target", "text", value="", mobject=None)
        apply_action(scene, st, {
            "action": "reveal", "target": "some_target", "params": {}},
            {"entities": []}, duration=0.5)

    texts = _norm(_text_strings(_render_scene(body)))
    assert not any("some_target" in t for t in texts)


def test_measure_on_text_card_without_value_renders_nothing():
    from engine.primitives.world_primitives import apply_action, \
        materialize_entity
    from engine.visuals.scene_state import SceneState

    def body(scene):
        st = SceneState()
        st.begin_beat("b001")
        materialize_entity(scene, st, {
            "id": "payoff_card", "type": "payoff",
            "properties": {"text": "V = π, A = ∞"}}, duration=0.5)
        # measure with NO display value and only an internal label:
        # must not draw "payoff: " or the id
        apply_action(scene, st, {
            "action": "measure", "target": "payoff_card",
            "params": {"label": "payoff"}}, {"entities": []},
            duration=0.5)

    texts = _norm(_text_strings(_render_scene(body)))
    assert texts == ["V=π,A=∞"]           # original text untouched


# ── FIX 2: tweens are visible ─────────────────────────────────────────
def test_compiler_emits_moving_camera_and_scene_tracker():
    from engine.renderers.manim.world_compiler import emit_world_scene
    vs = _one_beat_spec(
        params=[{"param": "fill_level", "to": 0.75, "ease": "smooth"}],
        actions=[{"action": "fill", "target": "horn",
                  "params": {"label": "V = π"}}],
        objects=[{"id": "horn", "type": "horn", "properties": {}}])
    src = emit_world_scene(vs, "TScene")
    assert "class TScene(MovingCameraScene)" in src
    assert "self.add(tracker)" in src           # updaters only fire for
    assert "clear_updaters" in src              # scene members


def test_fill_level_tween_changes_fill_opacity():
    """Functional: after the tween the live fill polygon carries the
    hook opacity 0.15 + 0.5*level — proves the tracker updater FIRED
    (previously an orphan tracker made this a silent no-op)."""
    from engine.renderers.manim.world_compiler import emit_world_scene
    vs = _one_beat_spec(
        params=[{"param": "fill_level", "to": 0.75, "ease": "smooth"}],
        actions=[{"action": "fill", "target": "horn",
                  "params": {"label": "V = π"}}],
        objects=[{"id": "horn", "type": "horn", "properties": {}}])
    src = emit_world_scene(vs, "TScene")
    import engine.renderers.manim.world_compiler as _wc
    ns: dict = {"__file__": _wc.__file__}
    exec(compile(src, "<generated>", "exec"), ns)  # noqa: S102
    # render via the generated class directly
    holder = {}

    class _T(Scene):
        pass

    _T.__name__ = "TScene"
    generated = ns["TScene"]
    with tempconfig({"dry_run": True, "quality": "low_quality",
                     "disable_caching": True}):
        inst = generated()
        holder["scene"] = inst
        inst.render()
    scene = holder["scene"]
    fill = scene._state.objects.get("horn_fill")
    assert fill is not None and fill.mobject is not None
    ops = [m.fill_opacity for m in fill.mobject.get_family()
           if getattr(m, "fill_opacity", 0) and
           isinstance(getattr(m, "fill_opacity", None), (int, float))]
    assert ops, "no filled sub-mobject found on the fill layer"
    target = 0.15 + 0.5 * 0.75
    assert any(abs(o - target) < 0.02 for o in ops), (ops, target)


def test_camera_zoom_tween_moves_the_frame():
    """Functional: the generated scene is a MovingCameraScene, so a
    camera_zoom tween actually scales the frame (was a silent no-op on
    a plain Scene)."""
    from engine.renderers.manim.world_compiler import emit_world_scene
    vs = _one_beat_spec(
        params=[{"param": "camera_zoom", "to": 0.85, "ease": "smooth"}],
        actions=[], objects=[], duration=2.0)
    src = emit_world_scene(vs, "TScene")
    import engine.renderers.manim.world_compiler as _wc
    ns: dict = {"__file__": _wc.__file__}
    exec(compile(src, "<generated>", "exec"), ns)  # noqa: S102
    holder = {}
    with tempconfig({"dry_run": True, "quality": "low_quality",
                     "disable_caching": True}):
        inst = ns["TScene"]()
        holder["scene"] = inst
        inst.render()
    scene = holder["scene"]
    width = scene.camera.frame.width
    # frame actually scaled by the tween (was a silent no-op on a plain
    # Scene where camera.frame is None)
    assert width < _frame_width() - 1.0, width


def test_gabriel_plan_tweens_only_visible_params():
    """The close/payoff beats crawl the camera; counter_value (no
    visible hook) no longer produces static-hold beats."""
    from engine.visuals.world_director import build_visualspec
    vs = build_visualspec("gabriel's horn", _gabriel_world())
    params = [p for b in vs["beats"] for p in b.get("scene_params", [])]
    assert params, "plan lost its motion"
    assert all(p["param"] in ("fill_level", "camera_x", "camera_zoom")
               for p in params)
    # motion continues across the payoff → close beats (camera crawl)
    by_role = {b["role"]: [p["param"] for p in b.get("scene_params", [])]
               for b in vs["beats"] if b.get("scene_params")}
    assert "camera_zoom" in by_role.get("payoff", [])
    assert "camera_zoom" in by_role.get("close", [])


# ── FIX 3: packaging (thumbnail) on every render run ──────────────────
def test_packaging_emits_thumbnail_without_qa_pass(tmp_path):
    from engine.cli.autonomous import emit_packaging
    vs = _one_beat_spec(params=[], actions=[], objects=[
        {"id": "horn", "type": "horn", "properties": {}}])
    res = emit_packaging(tmp_path, "gabriel's horn", vs["beats"], vs,
                         video_path=None, qa_report={"passed": False})
    thumb = Path(res["thumbnail"])
    assert thumb.exists() and thumb.stat().st_size > 0
    assert (tmp_path / "youtube_metadata.json").exists()


def test_run_autonomous_packages_even_when_qa_fails():
    """Source-level guard: the emit_packaging call is not gated on full
    QA PASS (that gate silently dropped thumbnail.jpg on wave-2)."""
    from engine.cli.autonomous import run_autonomous
    src = inspect.getsource(run_autonomous)
    i = src.find("emit_packaging")
    assert i > 0, "run_autonomous lost its packaging call"
    segment = src[max(0, i - 400):i]
    assert 'if report.get("passed")' not in segment
