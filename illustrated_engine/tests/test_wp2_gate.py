"""WP2 — fail-closed QA: plate QA required, OCR watermark filter, one critical
judge frame fails, right-rail / caption safe-zone checks.

Run: python3 tests/test_wp2_gate.py   (exit 0 = all passed; no network, no render)
The fixtures are the edge strips of two real Phase 2 blackhole plates
(fixtures/plate_watermark_pollinations.jpg carries the shipped "pollinations.ai"
stamp; plate_clean.jpg is a clean control).
"""
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures"

from engine import v15_gate as g  # noqa: E402

QA_OK = {"checked": True, "ocr_checked": True, "fail": {}}


def _specs(tmp: Path, fixture: str) -> dict:
    """One scene whose world plate is a private copy of `fixture` (the OCR
    result is cached beside the plate, so never point at the repo copy)."""
    dst = tmp / fixture
    shutil.copy(FIX / fixture, dst)
    return {"B1_S1": {"layers": [{"id": "plate_world", "source": "ai_image",
                                  "payload": {"path": str(dst),
                                              "fit": "cover"}}]}}


def _gate_checks(specs, qa):
    return {"plates": g.check_plates(specs, qa)}


def test_plate_qa_not_run_is_hold():
    with tempfile.TemporaryDirectory() as d:
        specs = _specs(Path(d), "plate_clean.jpg")
        for qa in (None, {}, {"checked": False, "reason": "judge unavailable"}):
            r = g.check_plates(specs, qa)
            assert not r["ok"] and r["unverified"] and not r["critical"], r
            assert "plate QA did not run" in r["fails"][0], r
            assert g.verdict_of({"plates": r}) == "HOLD"
        assert g.check_plates(specs, QA_OK)["ok"]
        assert g.verdict_of(_gate_checks(specs, QA_OK)) == "PASS"


def test_watermark_plate_fails_even_when_qa_passed_or_skipped():
    with tempfile.TemporaryDirectory() as d:
        specs = _specs(Path(d), "plate_watermark_pollinations.jpg")
        for qa in (QA_OK, None):  # QA said fine / --no-plate-qa
            r = g.check_plates(specs, qa)
            assert r["critical"] and any("pollinations" in f for f in r["fails"]), r
            assert g.verdict_of({"plates": r}) == "FAIL"


def test_ocr_filter_hits_watermark_not_clean_plate():
    from engine.v15_plates import ocr_watermark
    with tempfile.TemporaryDirectory() as d:
        wm = Path(d) / "wm.jpg"
        ok = Path(d) / "ok.jpg"
        shutil.copy(FIX / "plate_watermark_pollinations.jpg", wm)
        shutil.copy(FIX / "plate_clean.jpg", ok)
        r = ocr_watermark(wm)
        assert r["checked"] and "pollinations" in r["hits"], r
        assert ocr_watermark(ok) == {"checked": True, "hits": [],
                                     "version": "ocr/1"}
        assert (Path(d) / "wm.ocr.json").exists()  # cached beside the plate


def test_ocr_unreadable_plate_is_unverified():
    with tempfile.TemporaryDirectory() as d:
        bad = Path(d) / "broken.png"
        bad.write_bytes(b"not an image")
        from engine.v15_plates import ocr_watermark
        r = ocr_watermark(bad)
        assert r["checked"] is False and not r["hits"], r


def test_plate_qa_merges_ocr_and_reports_whether_vision_ran():
    import engine.director as director
    from engine.v15_plates import plate_qa
    real = director.vision_ask
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        paths = []
        for f in ("plate_clean.jpg", "plate_watermark_pollinations.jpg"):
            shutil.copy(FIX / f, tmp / f)
            paths.append(str(tmp / f))
        items = [{"path": p, "subject": "a clock"} for p in paths]
        try:
            director.vision_ask = lambda *a, **k: None  # judge unavailable
            r = plate_qa(items, "ink", tmp / "sheet.jpg")
            assert r["checked"] is False and r["ocr_checked"], r
            assert r["fail"] == {1: "text"} and r["ocr_hits"][1], r
            director.vision_ask = lambda *a, **k: {"plates": [
                {"n": 1, "fail": None}, {"n": 2, "fail": None}]}
            r = plate_qa(items, "ink", tmp / "sheet.jpg")
            # vision missed the stamp; the OCR pre-filter still fails it
            assert r["checked"] and r["fail"] == {1: "text"}, r
        finally:
            director.vision_ask = real


def test_regeneration_states():
    with tempfile.TemporaryDirectory() as d:
        specs = _specs(Path(d), "plate_clean.jpg")
        still = dict(QA_OK, regenerated=2, second_check=True,
                     still_failing=["a plate prompt"])
        r = g.check_plates(specs, still)
        assert r["critical"] and g.verdict_of({"plates": r}) == "FAIL"
        unchecked = dict(QA_OK, regenerated=2, second_check=False,
                         still_failing=[])
        r = g.check_plates(specs, unchecked)
        assert r["unverified"] and g.verdict_of({"plates": r}) == "HOLD", r
        fixed = dict(QA_OK, regenerated=2, second_check=True, still_failing=[])
        assert g.check_plates(specs, fixed)["ok"]


def test_fail_beats_hold_beats_pass():
    ok = {"ok": True, "fails": []}
    hold = {"ok": False, "fails": ["x"], "unverified": True}
    fail = {"ok": False, "fails": ["y"], "critical": True}
    assert g.verdict_of({"a": ok}) == "PASS"
    assert g.verdict_of({"a": ok, "b": hold}) == "HOLD"
    assert g.verdict_of({"a": ok, "b": hold, "c": fail}) == "FAIL"


def _judge(monkey_frames, hook=True):
    import engine.director as director
    real_sheet, real_ask = g._judge_sheet, director.vision_ask
    g._judge_sheet = lambda *a, **k: (Path("sheet.jpg"), len(monkey_frames))
    director.vision_ask = lambda *a, **k: {
        "frames": monkey_frames, "hook_stops_scroll": hook,
        "ending_resolves": True, "template_feel": False, "notes": "t"}
    try:
        return g.run_judge(Path("v.mp4"), {"story_id": "s", "beats": []}, {},
                           Path("."))
    finally:
        g._judge_sheet, director.vision_ask = real_sheet, real_ask


def _frames(n, bad=None):
    bad = bad or {}
    return [{"n": i + 1, "ok": bad.get(i + 1) is None,
             "issue": bad.get(i + 1, "none")} for i in range(n)]


def test_one_critical_frame_fails():
    for issue in ("text_garbled", "watermark", "overlap"):
        r = _judge(_frames(14, {5: issue}))
        assert not r["ok"] and r["critical"], (issue, r)
        assert g.verdict_of({"judge": r}) == "FAIL"


def test_soft_frame_issues_stay_hold_or_pass():
    one = _judge(_frames(14, {3: "subject_unrecognizable"}))
    assert one["ok"], one  # a single soft-critical frame is not enough
    two = _judge(_frames(14, {3: "subject_unrecognizable",
                          9: "empty_or_flat"}))
    assert not two["ok"] and not two["critical"]
    assert g.verdict_of({"judge": two}) == "HOLD"
    assert _judge(_frames(14))["ok"]


def test_right_rail_text_box():
    inside = {"s": {"meta": {"text_boxes": [{"id": "label", "text": "A",
                                              "box": [605, 794, 1010, 878]}]}}}
    r = g.check_text_bounds(inside)  # the Phase 2 blackhole label position
    assert not r["ok"] and "rail" in r["fails"][0], r
    above = {"s": {"meta": {"text_boxes": [{"id": "h", "text": "A",
                                             "box": [605, 300, 1010, 400]}]}}}
    assert g.check_text_bounds(above)["ok"]  # right rail starts at y=760


def _caption_png(tmp: Path, name: str, x0: int, x1: int) -> str:
    a = np.zeros((192, 1080, 4), np.uint8)
    a[40:130, x0:x1] = (255, 255, 255, 255)
    p = tmp / name
    Image.fromarray(a).save(p)
    return str(p)


def test_caption_safe_zone_and_rail():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        good = [{"png": _caption_png(tmp, "g.png", 160, 900), "text": "ok"}]
        assert g.check_caption_safe(good, 1500.0)["ok"]
        rail = [{"png": _caption_png(tmp, "r.png", 300, 1000), "text": "long"}]
        r = g.check_caption_safe(rail, 1500.0)
        assert not r["ok"] and "rail" in r["fails"][0], r
        assert g.check_caption_safe(rail, 300.0)["ok"]  # above the rail
        edge = [{"png": _caption_png(tmp, "e.png", 10, 700), "text": "edge"}]
        assert not g.check_caption_safe(edge, 300.0)["ok"]
        assert not g.check_caption_safe([], 1500.0)["ok"]


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL {name}: {e!r}"[:400])
    print(f"{'ALL PASS' if not fails else f'{fails} FAILED'}")
    sys.exit(1 if fails else 0)
