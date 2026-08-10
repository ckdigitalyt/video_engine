"""Tests for the v13 expert-review gates (rec #1-#10).

Covers:
  * claim_verifier  — Bloop/52-Hz conflation detection + unsupported claims
  * publish_status  — PUBLISH_READY / REVISION_REQUIRED / BLOCKED resolution
  * resolution_gate — zoom-headroom math (1024x576 source cannot sustain 1.22x)
  * authentic_audio — registry keys + speed-integrity QA
  * visual_artifact_check — mirror/smear/seam detection on synthetic frames
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.qa.claim_verifier import ClaimVerifier
from src.qa.publish_status import resolve_status
from src.qa.resolution_gate import max_safe_zoom, check_shot_headroom
from src.qa.authentic_audio import resolve_key, audio_qa
from src.qa.visual_artifact_check import (
    check_frame_mirror, check_frame_smear, check_frame_seam,
)


# ═══════════════════════════════════════════════════════════════════════ #
# claim_verifier — the Bloop/52-Hz conflation (rec #1, #9)
# ═══════════════════════════════════════════════════════════════════════ #

def _bloop_scenes():
    return [
        {"narration": "In 1997, deep in the Pacific Ocean, an underwater "
                      "microphone picked up a sound. It was so loud, it was "
                      "detected by sensors five thousand kilometers away."},
        {"narration": "They called it the Bloop. At fifty-two hertz, it was "
                      "in the range of a whale — but it dwarfed every whale "
                      "that ever sang."},
        {"narration": "In 2012, the mystery was solved. The Bloop was an "
                      "icequake — the sound of a glacier cracking and "
                      "collapsing into the sea."},
    ]


def test_bloop_script_fails_claim_gate():
    """The exact expert finding: 52 Hz attributed to the Bloop must fail."""
    gate = ClaimVerifier(llm=None, research_pack={}).run(_bloop_scenes())
    assert gate["passed"] is False
    assert "entity_disambiguation" in gate["blocking_failures"]
    assert any("bloop" in r["a"] for r in gate["conflation_risks"])


def test_corrected_bloop_script_passes_disambiguation():
    fixed = [
        {"narration": "In 1997, an underwater microphone in the Pacific "
                      "picked up a sound so loud it was detected thousands "
                      "of kilometers away."},
        {"narration": "They called it the Bloop — an ultra-low-frequency "
                      "sound unlike anything ever recorded."},
        {"narration": "In 2012, NOAA concluded the Bloop was consistent "
                      "with icequakes — glaciers cracking and calving into "
                      "the sea."},
    ]
    gate = ClaimVerifier(llm=None, research_pack={}).run(fixed)
    # No quantitative claims remain → nothing unsupported; disambiguation
    # passes; the corrected script is factually clean.
    assert gate["passed"] is True
    assert "entity_disambiguation" not in gate["blocking_failures"]
    assert gate["conflation_risks"] == []


def test_52hz_whale_alone_passes():
    scenes = [{"narration": "A single whale calls at fifty-two hertz, "
                            "a frequency no other whale uses."}]
    gate = ClaimVerifier(llm=None, research_pack={}).run(scenes)
    # 52 Hz + whale WITHOUT the Bloop is not a conflation.
    assert gate["conflation_risks"] == []
    assert "entity_disambiguation" not in gate["blocking_failures"]


# ═══════════════════════════════════════════════════════════════════════ #
# publish_status — rec #10 state machine
# ═══════════════════════════════════════════════════════════════════════ #

def test_status_all_pass():
    s = resolve_status(
        publish_gate={"checks": [{"name": "loudness_master", "passed": True}]},
        artifacts=[__file__])
    assert s["status"] == "PUBLISH_READY"
    assert s["publish_ready"] is True


def test_status_revision_on_blocked_publish():
    s = resolve_status(
        publish_gate={"checks": [
            {"name": "hook_strength", "passed": False},
            {"name": "loudness_master", "passed": True}]},
        artifacts=[__file__])
    assert s["status"] == "REVISION_REQUIRED"
    assert "retention" in s["categories"]


def test_status_blocked_on_missing_artifact():
    s = resolve_status(artifacts=["/definitely/not/here.mp4"])
    assert s["status"] == "BLOCKED"


# ═══════════════════════════════════════════════════════════════════════ #
# resolution_gate — rec #3 zoom headroom
# ═══════════════════════════════════════════════════════════════════════ #

def test_max_safe_zoom_headroom():
    # 1024x576 source for 1920x1080 output: headroom < 1.0 → clamped to 1.0,
    # so the DEFAULT 1.22 zoom must be impossible on this source.
    z = max_safe_zoom(1024, 576)
    assert z < 1.22
    # 2560x1440 source: 1.33x headroom (enough for default 1.22 zoom)
    z2 = max_safe_zoom(2560, 1440)
    assert z2 >= 1.22


def test_shot_headroom_fails_low_res(tmp_path):
    import subprocess
    img = tmp_path / "low.png"
    # solid 1024x576 PNG via ffmpeg
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
         "-i", "color=c=navy:s=1024x576", "-frames:v", "1", str(img)],
        check=True, capture_output=True)
    shot = {"file": str(img), "motion_params": {"zoom_end": 1.22}}
    r = check_shot_headroom(shot)
    assert r["passed"] is False  # 1.22 zoom impossible on a 1024x576 source


# ═══════════════════════════════════════════════════════════════════════ #
# authentic_audio — rec #2 registry + speed integrity
# ═══════════════════════════════════════════════════════════════════════ #

def test_authentic_registry_keys():
    assert resolve_key("bloop") == "bloop"
    assert resolve_key("the bloop") == "bloop"
    assert resolve_key("52-Hz whale") == "52hz_whale"
    assert resolve_key("nothing") is None


def test_authentic_audio_qa_speed_mismatch():
    scenes = [{"narration": "sped up sixteen times",
               "sfx_events": [{"type": "authentic", "source": "bloop"}]}]
    qa = audio_qa(scenes, cache_dir="cache/audio")
    # 16x matches the Bloop file → pass (no false speed contradiction)
    assert qa["passed"] is True


# ═══════════════════════════════════════════════════════════════════════ #
# visual_artifact_check — rec #5 synthetic artifact frames
# ═══════════════════════════════════════════════════════════════════════ #

def _frame_with_mirror_top():
    """Noisy interior + top border that is an exact vertical mirror of it.

    Textured (random) interior so same-side row correlation is low and the
    mirrored copy is a strong flip signature — the mirror detector skips
    near-flat rows by design (Andromeda v4 false positive: black-sky
    borders have std ~ 0 and correlation there is numeric noise).
    """
    h, w = 270, 480
    rng = np.random.default_rng(11)
    base = rng.normal(100, 25, (h, w)).astype(np.float32)  # texture per row
    top_h = int(h * 0.04)
    frame = base.copy()
    frame[:top_h] = base[top_h:2 * top_h][::-1]        # mirrored top border
    return frame.astype(np.float32)


def test_mirror_detected():
    f = _frame_with_mirror_top()
    deltas = []
    from src.qa.visual_artifact_check import border_row_deltas
    deltas = border_row_deltas(f)
    assert max(deltas) > 0.3  # strong mirror signature


def test_clean_frame_no_mirror():
    h, w = 270, 480
    rng = np.random.default_rng(7)
    f = rng.normal(100, 25, (h, w)).astype(np.float32)
    from src.qa.visual_artifact_check import border_row_deltas
    deltas = border_row_deltas(f)
    assert max(deltas) < 0.3  # random noise: no sustained mirror


def test_black_frame_skipped_by_smear():
    f = np.zeros((270, 480), dtype=np.float32)
    s = check_frame_smear(f)
    # ratio on a flat frame is degenerate but must not crash
    assert "ratio" in s
