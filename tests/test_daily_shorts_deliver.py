"""Decision #13 item 5: daily-mode Discord delivery (tools/daily_shorts_deliver.py).
PASS -> video + format-A message; HOLD/FAIL/ERROR -> reason only, no video.
No real Discord call: subprocess.run is mocked.
"""
import json
from unittest.mock import patch

from tools import daily_shorts_deliver as D


def _write_report(work, story, metadata):
    d = work / story
    d.mkdir(parents=True)
    (d / "pipeline_report.json").write_text(json.dumps({"metadata": metadata}))


def test_pass_posts_video_with_format_a_message(tmp_path):
    _write_report(tmp_path, "t_demo", {"title": "Demo Title",
                                       "description": "A short description.",
                                       "tags": ["a", "b"]})
    final = tmp_path / "t_demo" / "final.mp4"
    final.write_bytes(b"x" * 100)
    row = {"story": "t_demo", "verdict": "PASS", "scorecard": 84.0,
          "package": {"ok": True, "final": str(final)}}
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        D.deliver_one(tmp_path, row, "discord", "channel:1")
    assert m.call_count == 1
    cmd = m.call_args[0][0]
    assert "--media" in cmd and str(final) in cmd
    msg = cmd[cmd.index("--message") + 1]
    assert "Demo Title" in msg and "A short description." in msg
    assert "a, b" in msg and "PASS" in msg


def test_pass_too_large_posts_reason_not_video(tmp_path):
    _write_report(tmp_path, "t_big", {"title": "Big Video"})
    final = tmp_path / "t_big" / "final.mp4"
    final.write_bytes(b"x" * (D.MAX_MB * 1024 * 1024 + 1))
    row = {"story": "t_big", "verdict": "PASS",
          "package": {"ok": True, "final": str(final)}}
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        D.deliver_one(tmp_path, row, "discord", "channel:1")
    cmd = m.call_args[0][0]
    assert "--media" not in cmd
    assert "could not deliver" in cmd[cmd.index("--message") + 1]


def test_hold_posts_reason_only_no_video(tmp_path):
    _write_report(tmp_path, "t_hold", {"title": "Held Video"})
    row = {"story": "t_hold", "verdict": "HOLD",
          "failures": {"voice": ["round-trip QA failed"]}}
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        D.deliver_one(tmp_path, row, "discord", "channel:1")
    cmd = m.call_args[0][0]
    assert "--media" not in cmd
    msg = cmd[cmd.index("--message") + 1]
    assert "Held Video" in msg and "HOLD" in msg and "round-trip" in msg


def test_error_row_posts_error_reason(tmp_path):
    row = {"story": "t_err", "verdict": "ERROR", "error": "boom: something broke"}
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        D.deliver_one(tmp_path, row, "discord", "channel:1")
    msg = m.call_args[0][0]
    assert "boom" in msg[msg.index("--message") + 1]


def test_main_is_idempotent_via_delivered_state(tmp_path):
    _write_report(tmp_path, "t_demo", {"title": "Demo Title"})
    (tmp_path / "batch_report.json").write_text(json.dumps(
        {"rows": [{"story": "t_demo", "verdict": "HOLD", "failures": {}}]}))
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        with patch("sys.argv", ["prog", "--work", str(tmp_path), "--target", "channel:1"]):
            assert D.main() == 0
            assert D.main() == 0          # second run: already delivered
    assert m.call_count == 1


def test_materialize_hold_is_posted_even_with_no_batch_report(tmp_path):
    """decision #13 item 6 dry-run finding: a topic that HOLDs during
    research/script generation never reaches a run_batch row (no
    batch_report.json at all) — it must still be posted, reason only."""
    (tmp_path / "materialize_report.json").write_text(json.dumps(
        {"materialized": [], "holds": [
            {"id": "t_x", "title": "Earth's Missing Billion Years",
             "reason": "script: critic below bar after the rewrite"}]}))
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        with patch("sys.argv", ["prog", "--work", str(tmp_path), "--target", "channel:1"]):
            assert D.main() == 0
    assert m.call_count == 1
    msg = m.call_args[0][0]
    text = msg[msg.index("--message") + 1]
    assert "Earth's Missing Billion Years" in text and "HOLD" in text
    assert "critic below bar" in text
    assert "--media" not in msg


def test_materialize_hold_not_reposted_on_second_run(tmp_path):
    (tmp_path / "materialize_report.json").write_text(json.dumps(
        {"materialized": [], "holds": [{"id": "t_x", "title": "X", "reason": "r"}]}))
    with patch.object(D.subprocess, "run") as m:
        m.return_value.returncode = 0
        with patch("sys.argv", ["prog", "--work", str(tmp_path), "--target", "channel:1"]):
            assert D.main() == 0
            assert D.main() == 0
    assert m.call_count == 1
