"""Decision #18 item 4: judge-aligned plate QA + reason-steered regeneration."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"
IDENT = {"name": "the icy dwarf planet",
         "description": "small grey-white cratered ice sphere",
         "not_like": "Earth with blue oceans and green continents"}


def _items(tmp, n=3):
    out = []
    for i in range(n):
        p = tmp / f"{i}.jpg"
        shutil.copy(FIX / "plate_clean.jpg", p)
        out.append({"path": str(p), "subject": "the icy dwarf planet in space"})
    return out


def _run(answer, identity, n=3):
    import engine.director as director
    from engine.v15_plates import plate_qa
    real, seen = director.vision_ask, {}

    def fake(path, q, **k):
        seen["q"] = q
        return answer
    with tempfile.TemporaryDirectory() as d:
        try:
            director.vision_ask = fake
            r = plate_qa(_items(Path(d), n), "gouache", Path(d) / "s.jpg",
                         identity=identity)
        finally:
            director.vision_ask = real
    return r, seen["q"]


def test_new_fail_codes_and_shows_are_recorded():
    r, q = _run({"plates": [
        {"n": 1, "shows": "Earth with oceans", "fail": "generic_subject"},
        {"n": 2, "shows": "black sky, tiny dot", "fail": "empty"},
        {"n": 3, "shows": "same planet again", "fail": "near_duplicate"}]},
        IDENT)
    assert r["fail"] == {0: "generic_subject", 1: "empty", 2: "near_duplicate"}
    assert r["shows"][0] == "Earth with oceans"
    assert "Earth with blue oceans" in q and "the icy dwarf planet:" in q


def test_generic_subject_ignored_without_identity_block():
    r, q = _run({"plates": [{"n": 1, "fail": "generic_subject"}]}, None, n=1)
    assert r["fail"] == {} and "generic_subject" not in q


def test_schema_enum_lists_every_code_plate_qa_accepts():
    from engine.v15_plates import FAIL_CODES
    schema = json.loads((ROOT.parent / "llm/schemas/plate_qa.json").read_text())
    enum = schema["properties"]["plates"]["items"]["properties"]["fail"]["enum"]
    assert set(FAIL_CODES) <= set(enum)


def _bible():
    from engine.v15_style import load_style
    story = json.loads((ROOT / "stories/ice_slippery/story.json").read_text())
    return load_style(ROOT / "stories/ice_slippery", story)


PARTS = {"subject": "A small icy world hangs alone in starlit space",
         "composition": "subject_low", "view": "wide"}


def test_steer_generic_subject_leads_with_identity():
    from engine.v15_pipeline import steer_prompt
    p = steer_prompt(_bible(), PARTS, "generic_subject", 1, IDENT)
    assert p.index("small grey-white cratered ice sphere") < p.index("hangs alone")
    assert "Earth" not in p and "oceans" not in p   # not_like never prompted


def test_steer_empty_and_near_duplicate_change_framing():
    from engine.v15_pipeline import steer_prompt
    from engine.v15_style import VIEW_PHRASES
    b = _bible()
    p = steer_prompt(b, PARTS, "empty", 1)
    assert "filling most of the frame" in p and VIEW_PHRASES["medium"] in p
    d1 = steer_prompt(b, PARTS, "near_duplicate", 1)
    d2 = steer_prompt(b, PARTS, "near_duplicate", 2)
    assert VIEW_PHRASES["wide"] not in d1 and d1 != d2


def test_steer_narration_mismatch_strips_numbers():
    from engine.v15_pipeline import steer_prompt
    p = steer_prompt(_bible(), PARTS, "narration_mismatch", 1,
                     narration="It faded over one and a half seconds.")
    assert "clearly depicts: It faded over and a seconds" in p
    assert "one" not in p.split("depicts:")[1]


LAND = {"subject": "A narrow strip of frozen land between two icy coastlines, "
                   "tiny beavers crossing it. A stocky round-bodied beaver",
        "composition": "subject_low", "view": "wide"}
BEAVER = {"name": "the beaver", "description": "stocky round-bodied beaver",
          "not_like": "a capybara"}


def test_steer_wrong_subject_and_empty_lead_with_the_plates_own_object():
    """Dry run 6 (final): identity-led steering turned a land-bridge plate
    into a beaver portrait three rounds running."""
    from engine.v15_pipeline import steer_prompt
    b = _bible()
    for reason in ("wrong_subject", "empty"):
        p = steer_prompt(b, LAND, reason, 2, BEAVER)
        assert p.index("narrow strip of frozen land") < p.index("stocky"), (reason, p)
    g = steer_prompt(b, LAND, "generic_subject", 1, BEAVER)
    assert g.index("the beaver, stocky") < g.index("narrow strip")
