"""Phase A tests: explanation scoring for new §46 actions."""

from engine.world.scoring import score_beat


def _beat(actions, vtype=""):
    return {
        "beat_id": "b001",
        "visual_type": vtype,
        "objects": [{"id": "c", "type": "wave", "properties": {}}],
        "semantic_actions": actions,
        "transformations": [],
        "camera": {"type": "zoom_to"},
        "duration": 2.5,
    }


def test_interfere_scores_5():
    s = score_beat(_beat([{"action": "interfere", "target": "c",
                           "params": {"phase_deg": 180.0}}]))
    assert s.level == 5
    assert not s.text_primary


def test_cancel_scores_5():
    s = score_beat(_beat([{"action": "cancel", "target": "c"}]))
    assert s.level == 5


def test_burst_scores_5():
    s = score_beat(_beat([{"action": "burst", "target": "k"}]))
    assert s.level == 5


def test_narration_only_scores_0():
    s = score_beat({"beat_id": "b001", "visual_type": "narrative",
                    "objects": [], "semantic_actions": [],
                    "transformations": [], "camera": {}, "duration": 2.5})
    assert s.level == 0
    assert s.text_primary
