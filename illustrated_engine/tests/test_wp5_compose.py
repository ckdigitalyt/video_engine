"""WP5 — one-composition render (engine.v16_compose).

Pure-function unit tests: caption-track flattening and Short props assembly
from synthetic minimal Scene IR specs. No Claude calls, no Remotion/Node
invocation (that's bench/ab/wp5_parity.py's job, a real render).

Run: python3 tests/test_wp5_compose.py   (exit 0 = all passed; no network)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
REPO = ROOT.parent                              # video_engine
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(ROOT))

from engine import v16_compose as compose  # noqa: E402
from engine.brand import load_brand  # noqa: E402


def _spec(scene_id: str, duration_s: float, seed: int = 1) -> dict:
    return {
        "schema_version": "v14.scene_ir/1.0",
        "scene_id": scene_id,
        "visual_grammar": "RICH_ILLUSTRATED_SCENE",
        "duration_s": duration_s,
        "fps": 30,
        "size": [1080, 1920],
        "seed": seed,
        "layers": [{
            "id": "bg", "type": "background", "semantic_role": "world_ground",
            "source": "generated_gradient", "position": [0.0, 0.0], "scale": 1,
            "rotation": 0, "opacity": 1, "z": 0, "depth": 0, "anchor": "center",
            "payload": {"kind": "radial", "stops": ["#12405C", "#0A1D33"]},
        }],
        "camera": {"type": "static", "purpose": "establish", "keyframes": [
            {"t": 0.0, "value": 1.0}, {"t": duration_s, "value": 1.0}]},
        "animations": [],
        "caption_safe_regions": [],
        "meta": {},
    }


# --------------------------------------------------------- caption track --

def test_build_caption_track_maps_word_windows():
    overlays = [
        {"t0": 0.5, "t1": 0.8, "word": "You", "text": "You can stand", "cue": 0},
        {"t0": 0.8, "t1": 1.0, "word": "can", "text": "You can stand", "cue": 0},
    ]
    track = compose.build_caption_track(overlays)
    assert track == [
        {"text": "You", "startMs": 500, "endMs": 800},
        {"text": "can", "startMs": 800, "endMs": 1000},
    ]


def test_build_caption_track_sorts_by_start_and_drops_degenerate():
    overlays = [
        {"t0": 1.0, "t1": 1.2, "word": "b", "text": "x"},
        {"t0": 0.0, "t1": 0.0, "word": "zero_len", "text": "x"},  # t1<=t0 dropped
        {"t0": 0.2, "t1": 0.5, "word": "a", "text": "x"},
    ]
    track = compose.build_caption_track(overlays)
    assert [t["text"] for t in track] == ["a", "b"]


def test_build_caption_track_empty():
    assert compose.build_caption_track([]) == []
    assert compose.build_caption_track(None) == []


# --------------------------------------------------------- short props ----

def test_build_short_props_scene_order_and_durations():
    entries = [{"scene_id": "S1", "spec": _spec("S1", 1.0)},
              {"scene_id": "S2", "spec": _spec("S2", 2.0)}]
    props = compose.build_short_props(entries, [], brand=load_brand())
    assert [s["id"] for s in props["scenes"]] == ["S1", "S2"]
    assert [s["durationInFrames"] for s in props["scenes"]] == [30, 60]
    assert props["width"] == 1080 and props["height"] == 1920 and props["fps"] == 30
    assert compose.total_duration_frames(props) == 90


def test_build_short_props_rejects_mismatched_sizes():
    s2 = _spec("S2", 1.0)
    s2["size"] = [720, 1280]
    entries = [{"scene_id": "S1", "spec": _spec("S1", 1.0)},
              {"scene_id": "S2", "spec": s2}]
    try:
        compose.build_short_props(entries, [], brand=load_brand())
        raise AssertionError("expected ComposeError")
    except compose.ComposeError:
        pass


def test_build_short_props_rejects_empty_scenes():
    try:
        compose.build_short_props([], [], brand=load_brand())
        raise AssertionError("expected ComposeError")
    except compose.ComposeError:
        pass


def test_build_short_props_caption_style_from_brand():
    entries = [{"scene_id": "S1", "spec": _spec("S1", 1.0)}]
    brand = load_brand()
    props = compose.build_short_props(entries, [], brand=brand)
    cap = props["captions"]
    assert cap["textColor"].startswith("#") and cap["activeColor"].startswith("#")
    assert cap["bandTop"] > 0
    assert cap["combineWithinMs"] == compose.CAPTION_COMBINE_MS


def test_total_duration_frames_ignores_sting_and_outro_overlays():
    entries = [{"scene_id": "S1", "spec": _spec("S1", 1.0)}]
    props = compose.build_short_props(
        entries, [], brand=load_brand(),
        sting={"durationInFrames": 12, "imageSrc": "x.png"},
        outro={"durationInFrames": 45, "imageSrc": "y.png"})
    # both are in-timeline overlays (DESIGN.md S4/7.1), never additive
    assert compose.total_duration_frames(props) == 30


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
