"""V15 — unit tests for the correctness fixes and the new deterministic layers.

Run: python3 tests/test_v15.py   (exit 0 = all passed; no network, no render)
"""
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]

from engine import v14_assembly as asm  # noqa: E402
from engine.v15_gate import check_caption_identity, check_text_bounds  # noqa: E402

BIBLE = {"typography": {"display": "BebasNeue-Regular.ttf"},
         "palette": {"text": "#F5F2EB", "accent": "#FFC857"}}
STORY = {"story_id": "t", "beats": [
    {"beat_id": "B1", "narration": "One two three four five six."},
    {"beat_id": "B2", "narration": "Seven eight nine ten."}]}
CUES = {"B1": [{"t0": 0.2, "t1": 1.2, "text": "One two three"},
               {"t0": 1.3, "t1": 2.4, "text": "four five six."}],
        "B2": [{"t0": 0.2, "t1": 1.5, "text": "Seven eight nine ten."}]}
WIN = {"B1": (0.0, 3.0), "B2": (3.0, 5.0)}


def _overlays(tmp: Path) -> list:
    out = []
    for bid, off in (("B1", 0.0), ("B2", 3.0)):
        ins, _ = asm.build_caption_inputs(CUES[bid], BIBLE, tmp, offset=off)
        out += ins
    return out


def test_caption_namespace_and_identity():
    with tempfile.TemporaryDirectory() as d:
        ov = _overlays(Path(d))
        assert len({o["png"] for o in ov}) == len(ov), "png collision"
        r = check_caption_identity(ov, STORY, WIN)
        assert r["ok"], r


def test_v14_naming_fails_identity():
    """Regression proof: the V14 name (cue{ci}_w{wi} restarting per scene in
    one dir) makes later scenes overwrite earlier PNGs -> gate must fail."""
    orig = asm._caption_key
    try:
        asm._caption_key = lambda words, wi, bible, z, _c=[0]: None
        with tempfile.TemporaryDirectory() as d:
            ov = []
            for bid, off in (("B1", 0.0), ("B2", 3.0)):
                ci = [0]

                def key(words, wi, bible, z, _ci=ci):
                    return f"cue{_ci[0]:03d}_w{wi:02d}"
                asm._caption_key = key
                ins, _ = asm.build_caption_inputs(CUES[bid], BIBLE, Path(d),
                                                  offset=off)
                # V14 rendered every PNG (no exists() skip) -> last writer
                # wins; emulate by re-labelling reused paths with B2 text
                ov += ins
            last = {}
            for o in ov:
                last[o["png"]] = (o["text"], o["word"])
            burned = [dict(o, text=last[o["png"]][0], word=last[o["png"]][1])
                      for o in ov]
            r = check_caption_identity(burned, STORY, WIN)
            assert not r["ok"], "V14-style overwrite must fail identity"
    finally:
        asm._caption_key = orig


def test_word_starts_drive_highlight():
    with tempfile.TemporaryDirectory() as d:
        cue = [{"t0": 0.0, "t1": 2.0, "text": "a bb ccc",
                "word_starts": [0.0, 0.3, 1.5]}]
        ins, _ = asm.build_caption_inputs(cue, BIBLE, Path(d), offset=10.0)
        assert [round(i["t0"], 2) for i in ins] == [10.0, 10.3, 11.5], ins


def test_textfit():
    from engine.textfit import TextFitError, fit_text
    r = fit_text("WHAT DOES THE ICE LOOK LIKE BELOW THE SURFACE", max_w=900,
                 size=150, max_lines=3)
    assert r["width"] <= 900 and len(r["lines"]) <= 3
    try:
        fit_text("x" * 400, max_w=300, size=60, min_size=40, max_lines=1)
        raise AssertionError("expected TextFitError")
    except TextFitError:
        pass


def test_text_bounds_gate():
    ok = {"s": {"meta": {"text_boxes": [{"id": "h", "text": "A",
                                          "box": [100, 200, 900, 400]}]}}}
    bad = {"s": {"meta": {"text_boxes": [{"id": "h", "text": "A",
                                           "box": [-20, 200, 1100, 400]},
                                          {"id": "n", "text": "B",
                                           "box": [100, 1400, 900, 1500]}]}}}
    assert check_text_bounds(ok)["ok"]
    r = check_text_bounds(bad)
    assert not r["ok"] and len(r["fails"]) == 2, r


def test_plan_validation_and_fallback():
    from engine.v15_plan import fallback_plan, validate_plan
    story = json.loads((ROOT / "stories/ice_slippery/story.json").read_text())
    plan = fallback_plan(story)
    assert validate_plan(plan, story) == []
    # an invented number must be rejected (factual integrity)
    plan["beats"][1]["shots"][0]["number"] = {"text": "42 DEGREES", "word": 3}
    errs = validate_plan(plan, story)
    assert any("not spoken" in e for e in errs), errs
    # asking the image model for numbers/labels is rejected
    plan = fallback_plan(story)
    plan["beats"][0]["shots"][0]["subject"] = "a ruler with labels reading 10 nm"
    assert any("must not ask" in e for e in validate_plan(plan, story))
    for sd in sorted((ROOT / "stories").glob("*/story.json")):
        s = json.loads(sd.read_text())
        assert validate_plan(fallback_plan(s), s) == [], sd


def test_timing_on_synthetic_speech():
    from engine.procedural_audio import SR, save_wav
    from engine.v15_timing import align
    rng = np.random.default_rng(0)
    seg = []
    for dur, loud in ((0.3, 0), (1.2, 1), (0.4, 0), (1.0, 1), (0.3, 0)):
        n = int(dur * SR)
        seg.append(rng.normal(0, 0.2 if loud else 0.002, n))
    y = np.concatenate(seg).astype(np.float32)
    with tempfile.TemporaryDirectory() as d:
        p = save_wav(Path(d) / "x.wav", np.stack([y, y], 1))
        r = align(p, "alpha beta gamma, delta epsilon.")
    assert r["anchored"] == 1, r
    gamma_end = r["words"][2]["t1"]
    delta = r["words"][3]["t0"]
    assert 1.4 <= gamma_end <= 1.6 and 1.85 <= delta <= 2.05, r["words"]


def test_scale_dive_inner_scale():
    from engine.grammars import build_scene
    spec = build_scene("SCALE_DIVE", {
        "scene_id": "x", "duration_s": 6.0, "dive": {"to_scale": 24.0},
        "outer_subject": {"kind": "circle"},
        "inner_subject": {"kind": "circle"},
        "stages": [{"until_scale": 1e9, "title": "A"}]})
    inner = next(l for l in spec["layers"] if l["id"] == "inner_world")
    assert abs(inner["payload"]["local_scale"] - 1 / 24.0) < 1e-9


def test_renderer_version_moves_with_source():
    from engine.scene_renderer import _source_version
    with tempfile.TemporaryDirectory() as d:
        f = Path(d) / "a.tsx"
        f.write_text("x")
        v1 = _source_version([f])
        f.write_text("y")
        assert _source_version([f]) != v1


def test_image_prompt_sanitized():
    from engine.v15_style import image_prompt, load_style
    b = load_style(ROOT / "stories/ice_slippery")
    p = image_prompt(b, "a scientific cross-section of a skate blade")
    low = p.lower()
    for bad in ("diagram", "grammar", "text", "parchment", "scientific"):
        assert bad not in low, (bad, p)


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
