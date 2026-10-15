"""2026-10-15 review, priority 3: caption size/position, lone "one" not
numeralized, captions never under on-screen copy.

Run: python3 -m pytest -q tests/test_caption_review_20261015.py   (no network)
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import captions as C  # noqa: E402
from engine import v15_gate as g  # noqa: E402
from engine import v15_shots as S  # noqa: E402
from engine.voice.text import numeralize_cue_words  # noqa: E402


def _nums(text):
    return [w["w"] for w in numeralize_cue_words(
        [{"w": x, "t0": 0, "t1": 0} for x in text.split()])]


def test_lone_one_is_not_numeralized():
    assert _nums("Then one experimenter even levitated a coin.")[1] == "one"
    assert _nums("all thanks to one quiet truth")[3] == "one"
    assert _nums("It caused one of the largest")[2] == "one"


def test_quantity_one_still_numeralized():
    assert _nums("about one kilometer wide") == ["about", "1", "kilometer", "wide"]
    assert _nums("one hundred people") == ["100", "people"]
    assert _nums("one and a half seconds") == ["1.5", "seconds"]
    assert _nums("one to five meters") == ["1-5", "meters"]
    assert _nums("one two three") == ["1", "2", "3"]


def test_numerals_gate_accepts_word_one():
    assert g.check_caption_numerals([{"text": "one quiet truth"}])["ok"]
    assert not g.check_caption_numerals([{"text": "two quiet truths"}])["ok"]


def test_caption_band_is_out_from_under_the_shorts_ui():
    centre = C.V15_CAPTION_TOP + C.KIN_CAP_H / 2
    assert 0.60 * C.FRAME_H <= centre <= 0.70 * C.FRAME_H, centre
    assert g.CAPTION_BAND[0] <= C.V15_CAPTION_TOP
    assert g.CAPTION_BAND[1] >= C.V15_CAPTION_TOP + C.KIN_CAP_H


def test_caption_font_is_shorts_sized():
    for t in ("the dinosaurs also", "It caused one", "200 kilometers across."):
        f, _, _ = C._chunk_font({"lines": [t.split()]})
        assert f.size >= 80, (t, f.size)


def test_caption_ink_stays_in_band_and_clear_of_rail():
    with tempfile.TemporaryDirectory() as d:
        outs = []
        for i, t in enumerate(("megatsunamis we know of.", "it for up to 20 seconds.")):
            o = Path(d) / f"c{i}.png"
            C.chunk_png({"lines": [t.split()]}, {}, o, active=0,
                        zone_top=C.V15_CAPTION_TOP)
            outs.append({"png": str(o), "text": t})
        r = g.check_caption_safe(outs, C.V15_CAPTION_TOP, band=g.CAPTION_BAND)
        assert r["ok"], r
        # the same caption burned at the OLD (under-the-UI) top fails the band
        assert not g.check_caption_safe(outs, 1464.0, band=g.CAPTION_BAND)["ok"]


def test_bottom_zone_copy_and_labels_stay_above_captions():
    ink = {"fill": "#fff", "halo": "#000", "accent": "#f80"}
    boxes = []
    S._text_layer("headline", "A VERY LONG HEADLINE ABOUT THE OCEAN",
                  y=S.LOW_ZONE_BOTTOM, size=150, ink=ink, boxes=boxes,
                  max_lines=3, anchor_bottom=True)
    S._label("label", "LARGEST WAVE", {"bbox": [300, 1500, 700, 1800]},
             0.0, 3.0, ink, boxes, "top")
    assert len(boxes) == 2
    r = g.check_text_bounds({"s": {"meta": {"text_boxes": boxes}}})
    assert r["ok"], r


def test_fast_speech_cues_never_overlap_or_leave_the_beat():
    from engine import v15_pipeline as P
    from engine.captions import normalize_cues
    text = "It left a crater an estimated two hundred kilometers across."
    ws = text.split()
    # ~190 wpm: 0.31 s per word
    timing = {"words": [{"w": w, "t0": 0.31 * i, "t1": 0.31 * i + 0.27}
                        for i, w in enumerate(ws)]}
    end = P.LEAD_S + 0.31 * len(ws)
    cues = P.caption_cues(timing, P.LEAD_S, end=end)
    norm, repairs = normalize_cues(cues)
    assert not [r for r in repairs if r["reason"].startswith("dropped")], repairs
    assert " ".join(c["text"] for c in norm).split() == \
        " ".join(c["text"] for c in cues).split()
    assert all(c["t1"] <= end for c in cues)
    assert all(a["t1"] <= b["t0"] for a, b in zip(cues, cues[1:]))
