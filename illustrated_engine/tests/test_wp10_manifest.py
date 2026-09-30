"""WP10 — DESIGN.md §10 scorecard + §11 manifest/disclosure + distinctness
gate (engine.v16_gate + engine.v16_manifest).

Run: python3 -m pytest -q tests/test_wp10_manifest.py   (no network)
"""
import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_gate as g  # noqa: E402
from engine import v16_manifest as m  # noqa: E402
from engine.brand import load_brand  # noqa: E402

FIX = Path(__file__).resolve().parent / "fixtures"


# --------------------------------------------------------------- dhash --

def test_dhash_identical_images_zero_distance():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.png"
        Image.new("RGB", (64, 64), (10, 120, 200)).save(p)
        assert g.hamming(g.dhash(p), g.dhash(p)) == 0


def test_dhash_different_images_nonzero_distance():
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.png", Path(d) / "b.png"
        Image.new("RGB", (64, 64), (10, 120, 200)).save(a)
        im = Image.new("RGB", (64, 64), (10, 120, 200))
        for x in range(32):
            for y in range(64):
                im.putpixel((x, y), (250, 5, 5))
        im.save(b)
        assert g.hamming(g.dhash(a), g.dhash(b)) > 6


# ------------------------------------------------------- template signature --

def test_signature_distance_identical_is_zero():
    assert g.signature_distance("plate,zoom_through,plate", "plate,zoom_through,plate") == 0.0


def test_signature_distance_disjoint_sequences_is_high():
    d = g.signature_distance("plate,plate,plate", "map_pin,timeline,scale_compare")
    assert d >= 0.9


def test_template_signature_is_ordered_kind_sequence():
    meta = {"B1_S1": {"kind": "plate"}, "B1_S2": {"kind": "zoom_through"},
            "B2_S1": {"kind": "plate"}}
    assert g.template_signature(meta) == "plate,zoom_through,plate"


# ------------------------------------------------------------- distinctness --

def test_check_distinctness_ok_with_empty_history():
    meta = {"B1_S1": {"kind": "plate"}}
    r = g.check_distinctness("vid_a", meta, [], [])
    assert r["ok"] and r["history_size"] == 0


def test_check_distinctness_flags_near_identical_signature():
    meta = {"B1_S1": {"kind": "plate"}, "B1_S2": {"kind": "plate"},
            "B1_S3": {"kind": "zoom_through"}}
    history = [{"video_id": "vid_old",
               "signature": g.template_signature(meta), "plate_hashes": []}]
    r = g.check_distinctness("vid_new", meta, [], history)
    assert not r["ok"]
    assert any("template sequence" in f for f in r["fails"])


def test_check_distinctness_ignores_its_own_prior_entry():
    """A re-render of the SAME story must not flag itself as a near-
    duplicate of its own earlier history entry."""
    meta = {"B1_S1": {"kind": "plate"}}
    sig = g.template_signature(meta)
    history = [{"video_id": "vid_a", "signature": sig, "plate_hashes": []}]
    r = g.check_distinctness("vid_a", meta, [], history)
    assert r["ok"]


def test_check_distinctness_flags_reused_plate_hash():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "plate.png"
        Image.new("RGB", (64, 64), (30, 60, 90)).save(p)
        h = g.dhash(p)
        meta = {"B1_S1": {"kind": "map_pin"}}  # distinct signature from history
        history = [{"video_id": "vid_old", "signature": "plate,plate,plate",
                   "plate_hashes": [h]}]
        r = g.check_distinctness("vid_new", meta, [str(p)], history)
        assert not r["ok"]
        assert any("near-duplicate" in f for f in r["fails"])


# -------------------------------------------------------------------- hook --

def _timing(first_word_t0: float):
    return {"B1": {"words": [{"t0": first_word_t0, "t1": first_word_t0 + 0.3}]}}


def _specs_with_text_box(has_box: bool):
    return {"B1_S1": {"meta": {"text_boxes": (
        [{"id": "headline", "text": "X", "box": [0, 0, 10, 10]}] if has_box else [])}}}


def test_check_hook_passes_within_threshold_with_headline():
    meta = {"B1_S1": {"beat": "B1"}}
    r = g.check_hook(meta, _specs_with_text_box(True), _timing(0.0), 0.10,
                     {"hook_stops_scroll": True})
    assert r["ok"], r
    assert r["first_word_s"] == 0.10


def test_check_hook_fails_slow_first_word_and_missing_headline():
    meta = {"B1_S1": {"beat": "B1"}}
    r = g.check_hook(meta, _specs_with_text_box(False), _timing(0.5), 0.30,
                     {"hook_stops_scroll": False})
    assert not r["ok"]
    assert len(r["fails"]) == 3   # slow first word, no headline, judge no


# --------------------------------------------------------------- scorecard --

def _passing_checks():
    return {
        "judge": {"ok": True, "hook_stops_scroll": True, "frames_flagged": []},
        "hook": {"ok": True, "hook_stops_scroll": True, "first_word_s": 0.1,
                 "headline_at_frame0": True},
        "caption_identity": {"ok": True}, "text_bounds": {"ok": True},
        "caption_safe": {"ok": True},
        "audio": {"ok": True, "lufs": -14.0},
    }


def test_score_hook_perfect():
    assert g._score_hook(_passing_checks()["hook"]) == 100.0


def test_score_captions_all_ok_is_100():
    assert g._score_captions(_passing_checks()) == 100.0


def test_score_audio_on_target_is_100():
    assert g._score_audio(_passing_checks()) == 100.0


def test_score_story_uses_critic_scores_when_present():
    story = {"critic": {"scores": {"hook": 5, "pacing": 5, "clarity": 5}}}
    assert g._score_story(story) == 100.0


def test_score_story_structural_proxy_without_critic():
    story = {"beats": [{"contradiction": {"viewer_thinks": "x"}, "claim": "x",
                        "fact_ids": ["a"]}],
             "hook_plan": {"x": 1}, "payoff_image": "x"}
    assert g._score_story(story) == 100.0


def test_compute_scorecard_weighted_total_and_verdict():
    meta = {"B1_S1": {"kind": "plate"}, "B1_S2": {"kind": "plate"}}
    specs = {"B1_S1": {"duration_s": 1.0, "layers": []},
             "B1_S2": {"duration_s": 1.5, "layers": []}}
    checks = _passing_checks()
    brand = load_brand()
    sc = g.compute_scorecard(checks=checks, meta=meta, specs=specs,
                             story={"beats": []}, plates={}, brand=brand,
                             sting_present=True)
    assert set(sc["dimensions"]) == set(g.SCORE_WEIGHTS)
    assert sc["weights"] == g.SCORE_WEIGHTS
    expected = round(sum(sc["dimensions"][k] * g.SCORE_WEIGHTS[k] / 100
                         for k in g.SCORE_WEIGHTS), 1)
    assert sc["total"] == expected
    assert sc["verdict"] in ("PASS", "HOLD", "REJECT")


def test_scorecard_verdict_thresholds():
    dims_pass = {k: 100 for k in g.SCORE_WEIGHTS}
    total = sum(dims_pass[k] * g.SCORE_WEIGHTS[k] / 100 for k in g.SCORE_WEIGHTS)
    assert total == 100
    assert 80 <= total


# ---------------------------------------------------------- v16_manifest --

def _fake_plates():
    return {
        "prompt one": {"ok": True, "path": "/tmp/plate1.png", "provider": "nvidia_nim",
                       "model": "flux2-klein", "seed": 1, "lut_sha256": "abc"},
        "prompt two": {"ok": True, "path": "/tmp/plate2.png", "provider": "unknown_provider",
                       "model": "x", "seed": 2, "lut_sha256": "abc"},
        "prompt fail": {"ok": False},
    }


def test_plate_asset_rows_dedup_and_license_lookup():
    rows = m.plate_asset_rows(_fake_plates(), {"/tmp/plate1.png": False})
    assert len(rows) == 2
    r1 = next(r for r in rows if r["file"] == "/tmp/plate1.png")
    assert r1["commercial_ok"] is False   # NIM not owner-approved
    assert r1["realistic"] is False
    r2 = next(r for r in rows if r["file"] == "/tmp/plate2.png")
    assert r2["realistic"] is True        # unanswered -> conservative True
    assert r2["model_license"] == "unknown [U]"


def test_font_asset_rows_from_real_brand():
    brand = load_brand()
    rows = m.font_asset_rows(brand)
    assert rows and all(r["license"] for r in rows)
    assert all(r["commercial_ok"] for r in rows)


def test_llm_calls_since_scopes_by_timestamp():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "ledger.jsonl"
        rows = [{"ts": 100.0, "stage": "script_write"},
               {"ts": 105.0, "stage": "script_write"},
               {"ts": 200.0, "stage": "plate_qa"}]
        p.write_text("\n".join(json.dumps(r) for r in rows))
        out = m.llm_calls_since(100.0, 110.0, ledger_path=p)
        assert out == {"count": 2, "by_stage": {"script_write": 2}}


def test_build_manifest_disclosure_and_publishable():
    brand = load_brand()
    voice = {"provider": "kokoro", "model": "kokoro-v1.0 fp32",
             "voice_id": "am_michael", "license_ref": "Apache-2.0",
             "commercial_ok": True}
    manifest = m.build_manifest(
        video_id="v1", brand=brand, voice=voice, plates=_fake_plates(),
        plate_realistic={"/tmp/plate1.png": True, "/tmp/plate2.png": False},
        audio_rows=[{"kind": "music", "file": "/tmp/track.ogg",
                    "commercial_ok": True}],
        llm_calls={"count": 3, "by_stage": {"script_write": 1}},
        verdict="PASS")
    assert manifest["publishable"] is True
    assert manifest["disclosure"]["realistic_synthetic"] is True
    assert manifest["disclosure"]["youtube_altered_content"] is True
    assert manifest["disclosure"]["synthetic_voice"] is True
    kinds = {r["kind"] for r in manifest["assets"]}
    assert {"plate", "music", "font"} <= kinds
    assert manifest["voice"]["provider"] == "kokoro"


def test_build_manifest_not_publishable_on_hold():
    brand = load_brand()
    manifest = m.build_manifest(
        video_id="v2", brand=brand, voice={}, plates={},
        plate_realistic={}, audio_rows=[],
        llm_calls={"count": 0, "by_stage": {}}, verdict="HOLD")
    assert manifest["publishable"] is False
    assert manifest["disclosure"]["realistic_synthetic"] is False


def test_check_manifest_complete_detects_missing_and_extra():
    manifest = {"assets": [{"kind": "plate", "file": "/tmp/plate1.png"},
                           {"kind": "music", "file": "/tmp/track.ogg"}],
               "voice": {"provider": "kokoro"}}
    ok = m.check_manifest_complete(
        manifest, plate_paths=["/tmp/plate1.png"], voice_wav=None,
        audio_rows=[{"file": "/tmp/track.ogg"}])
    assert ok["ok"]
    bad = m.check_manifest_complete(
        manifest, plate_paths=["/tmp/plate1.png", "/tmp/plate_missing.png"],
        voice_wav=None, audio_rows=[])
    assert not bad["ok"]
    assert any("plate_missing" in f for f in bad["fails"])
    assert any("track.ogg" in f for f in bad["fails"])  # manifest lists an extra music file


def test_distinctness_history_round_trip_and_dedup():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "history.json"
        m.record_distinctness({"video_id": "a", "signature": "x",
                               "plate_hashes": []}, path=path)
        m.record_distinctness({"video_id": "a", "signature": "y",
                               "plate_hashes": []}, path=path)  # replaces, not appends
        hist = m.load_distinctness_history(path)
        assert len(hist) == 1 and hist[0]["signature"] == "y"


def test_distinctness_history_caps_at_30():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "history.json"
        for i in range(35):
            m.record_distinctness({"video_id": f"v{i}", "signature": "x",
                                   "plate_hashes": []}, path=path)
        hist = m.load_distinctness_history(path)
        assert len(hist) == 30
        assert hist[0]["video_id"] == "v5"
        assert hist[-1]["video_id"] == "v34"
