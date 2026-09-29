"""WP6 — brand bible: brand/ink_ember/ assets, engine.brand roles/LUT/props
lint/sting/outro/cover, and the right-rail layout fix in engine.v15_shots.

Run: python3 tests/test_wp6_brand.py   (exit 0 = all passed; no network)
"""
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import brand as BR  # noqa: E402
from engine import v15_gate as g  # noqa: E402
from engine import v15_shots as S  # noqa: E402

INK = {"fill": "#FFF7E8", "halo": "#15202B", "accent": "#E3A83B"}


# --------------------------------------------------------------- schema --

def test_ink_ember_validates_clean():
    b = BR.load_brand("ink_ember")
    assert BR.validate_brand(b) == []


def test_font_licence_files_present():
    b = BR.load_brand("ink_ember")
    for role, spec in b["fonts"].items():
        assert (BR.FONT_DIR / spec["file"]).is_file(), spec["file"]
        lic = spec.get("license_file")
        assert lic, f"{role} has no license_file"
        assert (BR.FONT_DIR / lic).is_file(), lic


def test_missing_brand_raises():
    try:
        BR.load_brand("does_not_exist")
        assert False, "should have raised"
    except BR.BrandError:
        pass


def test_unknown_role_raises():
    b = BR.load_brand("ink_ember")
    try:
        BR.role_hex(b, "not_a_role")
        assert False, "should have raised"
    except BR.BrandError:
        pass


# ------------------------------------------------------------- LUT hash --

def test_lut_hash_matches_recorded_sha256():
    """The committed grade.cube is reproducible from brand.yaml's own
    params, and its hash matches the hash brand.yaml records (the
    "LUT-hash test")."""
    b = BR.load_brand("ink_ember")
    assert BR.verify_cube_hash(b)
    with tempfile.TemporaryDirectory() as d:
        # same stem as the committed file: generate_cube's TITLE line embeds
        # path.stem, so a differently-named regen legitimately hashes
        # differently even with byte-identical LUT data.
        regen = BR.generate_cube(Path(d) / "grade.cube", **b["grade"]["params"])
        assert BR.cube_sha256(regen) == b["grade"]["sha256"]


def test_apply_lut_grades_and_returns_matching_hash():
    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src.png"
        dst = Path(d) / "dst.png"
        Image.new("RGB", (32, 32), (120, 90, 60)).save(src)
        h = BR.apply_lut(src, dst, b)
        assert h == b["grade"]["sha256"]
        assert dst.exists()
        before = Image.open(src).convert("RGB").getpixel((16, 16))
        after = Image.open(dst).convert("RGB").getpixel((16, 16))
        assert before != after  # actually graded, not a passthrough copy


def test_plate_ingest_records_lut_hash():
    """engine.v15_plates.generate_plate grades every plate at ingest and
    records the brand's cube hash on the cached meta."""
    from engine import v15_plates as VP

    class FakeProv:
        model = "fake"

        def is_available(self):
            return True

        def generate(self, prompt, path, width, height, seed):
            Image.new("RGB", (width, height), (200, 140, 80)).save(path)

    class FakeFactory:
        def get(self, name):
            return FakeProv()

    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        old_cache, old_factory = VP.CACHE_DIR, VP._factory
        VP.CACHE_DIR = Path(d)
        VP._factory = lambda: FakeFactory()
        try:
            r = VP.generate_plate("a brand-ingest test prompt", 7)
        finally:
            VP.CACHE_DIR, VP._factory = old_cache, old_factory
    assert r["ok"] and r["lut_sha256"] == b["grade"]["sha256"]


# ------------------------------------------------------------- props lint --

def test_lint_props_catches_literal_hex():
    spec = {"layers": [{"payload": {"fill": "#FF00FF", "text": "x"}}]}
    hits = BR.lint_props(spec)
    assert hits and "fill" in hits[0]
    try:
        BR.assert_no_literal_hex(spec)
        assert False, "should have raised"
    except BR.BrandError:
        pass


def test_lint_props_allows_role_names():
    spec = {"layers": [{"payload": {"fill": "headline", "stroke": "scrim"}}]}
    assert BR.lint_props(spec) == []
    BR.assert_no_literal_hex(spec)  # does not raise


def test_lint_props_ignores_non_colour_keys():
    spec = {"layers": [{"payload": {"path": "#not-a-colour-key-value",
                                    "id": "#123456"}}]}
    # "id" IS a colour-bearing-looking string but not in _COLOR_KEYS
    assert BR.lint_props(spec) == []


# ---------------------------------------------------- right-rail layout --

def test_label_clears_right_rail_black_hole_case():
    """Reproduces the exact Phase 2 blackhole label the WP2 gate HOLDs on
    (bench/ab/wp2.md: "THE BLACK HOLE" x 605-1010, y 794-878) and asserts
    engine.v15_shots._label no longer produces a rail-breaching box."""
    boxes = []
    info = {"bbox": [300, 850, 700, 1066]}
    lab = S._label("label", "THE BLACK HOLE", info, 1.0, 3.0, INK, boxes, "top")
    assert lab is not None
    box = boxes[0]["box"]
    assert not g._box_problems(box), box
    checks = g.check_text_bounds({"s": {"meta": {"text_boxes": boxes}}})
    assert checks["ok"], checks


def test_headline_bottom_zone_clears_right_rail():
    boxes = []
    S._text_layer("headline",
                  "A VERY LONG HEADLINE ABOUT THE BLACK HOLE EVENT HORIZON",
                  y=S.LOW_ZONE_BOTTOM, size=150, ink=INK, boxes=boxes,
                  max_lines=3, anchor_bottom=True)
    assert not g._box_problems(boxes[0]["box"]), boxes[0]


def test_headline_top_zone_unaffected():
    """Above the rail (y1 < 760), the old full-width fit is untouched."""
    boxes = []
    S._text_layer("headline", "SHORT", y=S.TOP_ZONE_Y + 60, size=150,
                  ink=INK, boxes=boxes, max_lines=3)
    assert boxes[0]["box"][3] < g.RAIL_Y0


def test_process_step_chip_clears_right_rail():
    sc = {"duration": 8.0, "shot": {"steps": [
        {"text": f"step {i} of the process happens here", "word": 0}
        for i in range(5)]}, "plates": [], "t_of": lambda w: 0.5}
    boxes = []
    S.compile_process_shot(sc, {
        "palette": {"primary": "#15202B", "secondary": "#1F3A56",
                    "accent": "#C4502A", "text": "#FFF7E8"},
        "texture": {}}, boxes, [])
    rail_hits = [b for b in boxes if g._box_problems(b["box"])]
    assert not rail_hits, rail_hits


# --------------------------------------------------------- sting/outro/cover

def test_sting_audio_generates_wav():
    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        p = BR.sting_audio(Path(d) / "sting.wav", b)
        assert p.exists() and p.stat().st_size > 1000


def test_ink_bloom_overlay_generates_rgba_png():
    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        p = BR.ink_bloom_overlay(Path(d) / "bloom.png", (200, 300), b)
        im = Image.open(p)
        assert im.mode == "RGBA" and im.size == (200, 300)


def test_seal_badge_generates_png_with_part_label():
    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        p = BR.seal_badge(Path(d) / "seal.png", b, part_label="PART 2")
        assert Image.open(p).mode == "RGBA"


def test_render_cover_generates_jpeg():
    b = BR.load_brand("ink_ember")
    with tempfile.TemporaryDirectory() as d:
        bg = Path(d) / "bg.jpg"
        Image.new("RGB", (1080, 1920), (80, 60, 40)).save(bg)
        out = BR.render_cover(Path(d) / "cover.jpg", bg_frame=bg,
                              title="The Black Hole Next Door",
                              part_label="PART 1", brand=b)
        im = Image.open(out)
        assert im.size == (1080, 1920)


# ----------------------------------------------------------- captions --

def test_captions_use_brand_roles_not_bible():
    from engine.captions import chunk_png
    b = BR.load_brand("ink_ember")
    chunk = {"words": ["THE", "BLACK", "HOLE"],
            "lines": [["THE", "BLACK", "HOLE"]]}
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "c.png"
        # bible arg is intentionally garbage: colour must NOT come from it
        chunk_png(chunk, {"palette": {"text": "#000000", "accent": "#000000"}},
                  out, active=1)
        im = Image.open(out).convert("RGBA")
        px = [im.getpixel((x, y)) for x in range(im.width)
              for y in range(im.height) if im.getpixel((x, y))[3] > 200]
        accent = BR.role_rgb(b, "caption_active")
        assert any(p[:3] == accent for p in px), "active word not in brand accent"


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
