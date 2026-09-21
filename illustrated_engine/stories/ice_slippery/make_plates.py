#!/usr/bin/env python3
"""V13 plates for ice_slippery — deterministic ink-wash cards.

All six subjects are association-prone (ice surfaces, blade+pressure,
multi-element film/lattice compositions). The live Pollinations attempt on
the one rings-class candidate (B3 lattice, seed 4303) came back with a
generated pollinations.ai watermark, gibberish scrawl text and subject drift
(faceted radial oval, not hexagonal lattice rings) — the same subject-\nadherence ceiling the V13 pilot hit, so every plate ships as a
contract-faithful deterministic ink-wash card (cardlib_deterministic),
matching the pilot's final state (5 of 6 plates deterministic).

Every plate gets a v13-plate-sidecar@1 sidecar, derived SUBJECT/MIDGROUND/
BACKGROUND masks (engine.depth_layers.derive_masks), schema validation
(engine.plate_pipeline.validate_sidecar) and a continuity pre-score
(engine.harmonize.continuity_score) against stories/ice_slippery/
visual_bible.json. Final plates are mirrored to assets/.
"""
import json
import math
import random
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

STORY = "ice_slippery"
HERE = Path(__file__).resolve().parent
ENGINE = HERE.parent.parent          # illustrated_engine/
REPO = ENGINE.parent                # video_engine/
OUT_ROOT = ENGINE / "build" / "plates" / STORY
ASSETS = ENGINE / "assets"
BIBLE = json.loads((HERE / "visual_bible.json").read_text())

PLATE_W, PLATE_H = 2160, 3840
BG = (214, 199, 172)        # D6C7AC parchment
BG_DARK = (188, 171, 141)   # mottle
BG_LIGHT = (233, 223, 200)  # E9DFC8 cream
INK = (43, 38, 34)          # 2B2622
RUST = (156, 82, 44)        # 9C522C
SEPIA = (122, 106, 82)      # 7A6A52

TEXTURE_TAGS = ["ink_wash", "sepia_wash", "aged_parchment",
                "engraving_linework", "matte_grain"]
LIGHTING = "soft directional low-key with warm highlights"


def _rel(p: Path) -> str:
    import os
    return os.path.relpath(Path(p).resolve(), REPO)


def mottle_bg(rng: random.Random) -> Image.Image:
    """Parchment mottle background + vignette (continuity-safe: warm only)."""
    img = Image.new("RGB", (PLATE_W, PLATE_H), BG)
    blot = Image.new("RGB", (PLATE_W, PLATE_H), BG)
    d = ImageDraw.Draw(blot)
    for _ in range(70):
        x, y = rng.randrange(0, PLATE_W), rng.randrange(0, PLATE_H)
        r = rng.randrange(90, 420)
        col = BG_DARK if rng.random() < 0.55 else BG_LIGHT
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    blot = blot.filter(ImageFilter.GaussianBlur(140))
    img = Image.blend(img, blot, 0.5)
    # matte grain
    grain = Image.effect_noise((PLATE_W, PLATE_H), 18).convert("L")
    img = Image.composite(
        Image.new("RGB", (PLATE_W, PLATE_H), SEPIA), img,
        grain.point(lambda v: 255 if v > 232 else 0))
    # vignette
    vg = Image.new("L", (PLATE_W, PLATE_H), 0)
    dv = ImageDraw.Draw(vg)
    dv.ellipse([-int(PLATE_W * 0.35), -int(PLATE_H * 0.22),
                int(PLATE_W * 1.35), int(PLATE_H * 1.22)], fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(260))
    dark = Image.new("RGB", (PLATE_W, PLATE_H), (168, 150, 120))
    img = Image.composite(img, dark, vg)
    return img


def glow(img, cx, cy, r, color=RUST, strength=110):
    """Warm rust radial glow on an RGBA overlay."""
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    d.ellipse([cx - r, cy - r, cx + r, cy + r],
              fill=color + (strength,))
    ov = ov.filter(ImageFilter.GaussianBlur(r * 0.55))
    img.paste(Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB"),
              (0, 0))
    return img


def hexagon(cx, cy, side, rot=0.0):
    import math
    pts = []
    for i in range(6):
        a = math.pi / 3 * i + rot
        pts.append((cx + side * math.cos(a), cy + side * math.sin(a)))
    return pts


# ── B1: ice macro — angular frozen planes with glinting sheen ───────────
def card_b1() -> Image.Image:
    rng = random.Random(4101)
    img = mottle_bg(rng)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # large angular facets (closed curves, parchment fills)
    facets = [
        [(0, 0), (1250, 0), (980, 1180), (0, 1420)],
        [(1250, 0), (2160, 0), (2160, 1320), (980, 1180)],
        [(0, 1420), (980, 1180), (1400, 2300), (0, 2600)],
        [(980, 1180), (2160, 1320), (2160, 2700), (1400, 2300)],
        [(0, 2600), (1400, 2300), (1800, 3840), (0, 3840)],
        [(1400, 2300), (2160, 2700), (2160, 3840), (1800, 3840)],
    ]
    for i, poly in enumerate(facets):
        t = rng.uniform(0.3, 0.62)   # warm tan facet fill: stays in palette bins
        fill = tuple(int(SEPIA[j] * t + BG_LIGHT[j] * (1 - t)) for j in range(3))
        d.polygon(poly, fill=fill + (235,))
    # ink facet edges
    for poly in facets:
        d.line(poly + [poly[0]], fill=INK + (255,), width=9)
    # glinting sheen streaks (pale, low alpha)
    for _ in range(9):
        x, y = rng.randrange(150, 1800), rng.randrange(300, 3400)
        ln = rng.randrange(260, 720)
        dy = rng.randrange(-90, 90)
        d.line([x, y, x + ln, y + dy], fill=(248, 242, 228, 110), width=10)
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    # faint inner cracks
    d2 = ImageDraw.Draw(img)
    for _ in range(12):
        x, y = rng.randrange(200, 1900), rng.randrange(300, 3500)
        seg = [(x, y)]
        for _s in range(3):
            x += rng.randrange(-160, 160)
            y += rng.randrange(60, 220)
            seg.append((x, y))
        d2.line(seg, fill=INK, width=4)
    img = glow(img, 1350, 1750, 660, RUST, 150)
    img = glow(img, 700, 2900, 500, RUST, 95)
    return img


# ── B2: pressure micro — blade pressing slab, rust wedge, droplets ──────
def card_b2() -> Image.Image:
    rng = random.Random(4202)
    img = mottle_bg(rng)
    d = ImageDraw.Draw(img)
    # ice slab edge-on (lower third)
    slab = [260, 2480, 1900, 3220]
    d.rounded_rectangle(slab, radius=60, fill=(221, 206, 176))
    d.rounded_rectangle(slab, radius=60, outline=INK, width=10)
    for _ in range(8):  # internal facet cracks
        x = rng.randrange(340, 1780)
        d.line([x, 2530, x + rng.randrange(-220, 220), 3170],
               fill=SEPIA, width=5)
    img = glow(img, 1080, 2440, 600, RUST, 150)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # blade (near-neutral ink fill: drops out of hue mask) — tip INTO the slab
    d.polygon([(1010, 1180), (1150, 1180), (1130, 2530), (1030, 2530)],
              fill=(52, 48, 44, 255))
    d.line([1030, 2530, 1130, 2530], fill=(238, 232, 218, 255), width=16)
    # heavy rust pressure wedge into the contact (narrow, arrow-like)
    d.polygon([(1080, 1560), (950, 2320), (1210, 2320)],
              fill=RUST + (215,))
    ov = ov.filter(ImageFilter.GaussianBlur(3))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    d = ImageDraw.Draw(img)
    # melt droplets beaded at + along the contact line
    for x in (990, 1030, 1080, 1130, 1170):
        r = rng.randrange(20, 42)
        y = 2495 + rng.randrange(-25, 25)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(208, 194, 164),
                  outline=INK, width=5)
    for x in (830, 900, 1290, 1370):
        r = rng.randrange(12, 26)
        y = 2470 + rng.randrange(0, 40)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(208, 194, 164),
                  outline=INK, width=4)
    return img


# ── B3: lattice — nested hexagonal node-and-bond rings to a glowing center
def card_b3() -> Image.Image:
    import math
    rng = random.Random(4303)
    img = mottle_bg(rng)
    img = glow(img, 1080, 1980, 640, RUST, 150)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    cx, cy = 1080, 1980
    # concentric hex rings of nodes + bond lines, shrinking inward
    for k, r_ in enumerate((900, 660, 440, 250, 110)):
        hexs = hexagon(cx, cy, r_)
        d.line(hexs + [hexs[0]], fill=INK + (255,), width=9 - k)
        for (vx, vy) in hexs:
            d.ellipse([vx - 16, vy - 16, vx + 16, vy + 16],
                      fill=INK + (255,))
    # radial bonds between consecutive rings at each vertex angle
    for i in range(6):
        a = math.pi / 3 * i
        for r_in, r_out in ((110, 250), (250, 440), (440, 660), (660, 900)):
            d.line([cx + r_in * math.cos(a), cy + r_in * math.sin(a),
                    cx + r_out * math.cos(a), cy + r_out * math.sin(a)],
                   fill=SEPIA + (235,), width=6)
    # sparse background lattice hexes at the frame edges (context, dimmer)
    for (bx, by) in ((250, 560), (1900, 780), (300, 3260), (1860, 3080),
                     (1080, 340)):
        hexs = hexagon(bx, by, 150)
        d.line(hexs + [hexs[0]], fill=SEPIA + (190,), width=5)
        for (vx, vy) in hexs:
            d.ellipse([vx - 10, vy - 10, vx + 10, vy + 10],
                      fill=SEPIA + (220,))
    # glowing center node
    d.ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=RUST + (255,))
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    return img


# ── B4: water film — lattice below, top ring row breaking into film ─────
def card_b4() -> Image.Image:
    rng = random.Random(4404)
    img = mottle_bg(rng)
    img = glow(img, 1080, 1520, 760, RUST, 150)
    img = glow(img, 1560, 2620, 440, RUST, 90)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    side = 230
    row_step = int(side * math.sqrt(3))          # 398: true honeycomb pitch
    rows = 4
    for row in range(rows):
        cy = 2380 + row * row_step
        broken = (row == 0)
        for i in range(6):
            cx = 260 + i * int(1.5 * side) + (int(0.75 * side) if row % 2 else 0)
            hexs = hexagon(cx, cy, side, rot=0.0)
            if broken:
                # topmost row breaking open: dashed edges + loose nodes
                for a, b in zip(hexs, hexs[1:] + hexs[:1]):
                    if rng.random() < 0.55:
                        d.line([a, b], fill=INK + (255,), width=8)
            else:
                d.polygon(hexs, fill=(224, 204, 167, 235))
                d.line(hexs + [hexs[0]], fill=INK + (255,), width=8)
            for (vx, vy) in hexs:
                d.ellipse([vx - 15, vy - 15, vx + 15, vy + 15],
                          fill=INK + (255,))
    # loose molecules escaping the broken top row toward the film
    for _ in range(22):
        x, y = rng.randrange(260, 1900), rng.randrange(1650, 2100)
        r = rng.randrange(14, 30)
        d.ellipse([x - r, y - r, x + r, y + r], fill=INK + (220,))
    # thin glowing liquid film band (warm cream, not white)
    d.rounded_rectangle([220, 1450, 1940, 1610], radius=70,
                        fill=(240, 229, 202, 235), outline=INK + (255,),
                        width=7)
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    return img


# ── B5: glide — blade edge on a film line, spray arcs trailing ──────────
def card_b5() -> Image.Image:
    rng = random.Random(4505)
    img = mottle_bg(rng)
    img = glow(img, 1180, 2180, 680, RUST, 145)
    img = glow(img, 1620, 2740, 400, RUST, 85)
    d = ImageDraw.Draw(img)
    # thin bright film line across the frame
    d.rounded_rectangle([240, 2110, 1920, 2210], radius=45,
                        fill=(243, 235, 215), outline=INK, width=8)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # single blade edge gliding left-to-right (no person) — low, long profile
    d.polygon([(1120, 1880), (1330, 1910), (1560, 2120), (1530, 2155),
               (1200, 2110)], fill=(52, 48, 44, 255))
    d.line([1200, 2110, 1530, 2155], fill=(238, 232, 218, 255), width=14)
    # faint spray arcs trailing behind the contact
    for k in range(3):
        bx = 1430 + k * 60
        d.arc([bx - 260, 1980 - k * 40, bx + 60, 2300 + k * 40],
              start=200, end=320, fill=INK + (200 - k * 55,), width=7)
    # motion streaks behind
    for _ in range(6):
        x = rng.randrange(300, 1200)
        y = rng.randrange(1850, 2080)
        d.line([x, y, x + rng.randrange(180, 420), y + rng.randrange(-24, 24)],
               fill=(238, 231, 214, 130), width=10)
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    return img


# ── B6: payoff — lattice rings below, liquid skin band, quiet field ─────
def card_b6() -> Image.Image:
    rng = random.Random(4606)
    img = mottle_bg(rng)
    img = glow(img, 1080, 1900, 760, RUST, 140)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    # nested hexagonal lattice rings, lower half
    for r_, w_ in ((560, 10), (420, 8), (280, 6)):
        hexs = hexagon(1080, 2680, r_)
        d.line(hexs + [hexs[0]], fill=INK + (255,), width=w_)
        for (vx, vy) in hexs:
            d.ellipse([vx - 16, vy - 16, vx + 16, vy + 16],
                      fill=INK + (255,))
    # spokes to the glowing center
    for (vx, vy) in hexagon(1080, 2680, 280):
        d.line([1080, 2680, vx, vy], fill=SEPIA + (220,), width=5)
    d.ellipse([1050, 2650, 1110, 2710], fill=RUST + (255,))
    # thin glowing liquid skin band across the middle (warm cream)
    d.rounded_rectangle([280, 1800, 1880, 1950], radius=70,
                        fill=(238, 226, 198, 230), outline=INK + (255,),
                        width=7)
    # a few droplets drifting between film and lattice
    for _ in range(7):
        x, y = rng.randrange(420, 1740), rng.randrange(2050, 2450)
        r = rng.randrange(12, 24)
        d.ellipse([x - r, y - r, x + r, y + r], fill=INK + (200,))
    ov = ov.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    return img


def sidecar_for(plate_path: Path, subject_bbox, seed: int) -> dict:
    return {
        "schema": "v13-plate-sidecar@1",
        "plate": _rel(plate_path),
        "asset_class": "RICH_VISUAL_PLATE",
        "generation": {
            "composition": {
                "provider": "cardlib_deterministic",
                "status": "authored",
                "note": "contract-faithful deterministic card (live AI "
                        "attempt: provider watermark + scrawl text + "
                        "subject drift — same ceiling as the V13 pilot)"},
            "detail": {"provider": "pollinations", "model": "flux",
                       "seed": seed + 1, "edited": False, "degraded": True,
                       "note": "edit op unsupported; stage skipped"},
            "semantic_edit": {"provider": "pollinations", "model": "flux",
                              "seed": seed + 2, "edited": False,
                              "degraded": True,
                              "note": "edit op unsupported; stage skipped"},
            "depth": {"provider": "depth_layers", "model": None,
                      "status": "deferred_to_M3", "depth_map": None,
                      "note": "masks derived below via depth_layers"}},
        "layers": [
            {"name": "BACKGROUND", "mask": None,
             "bbox_px": [0, 0, PLATE_W, PLATE_H], "parallax_weight": 0.15},
            {"name": "MIDGROUND", "mask": None,
             "bbox_px": [216, 768, 1944, 3072], "parallax_weight": 0.45},
            {"name": "SUBJECT", "mask": None, "bbox_px": list(subject_bbox),
             "parallax_weight": 0.85}],
        "subject_bbox_px": list(subject_bbox),
        "annotation_rects_px": [],
        "depth_map": None,
        "zoom_safe": {"max_scale": 1.6},
        "safe_margin_px": 40,
        "texture_tags": TEXTURE_TAGS,
        "lighting": LIGHTING,
    }


CARDS = {
    "B1": ("IS_B1_ice_macro", card_b1,
           [180, 900, 1980, 2940], 4101),
    "B2": ("IS_B2_pressure_micro", card_b2,
           [760, 1180, 1500, 3260], 4202),
    "B3": ("IS_B3_lattice", card_b3,
           [180, 1080, 1980, 2880], 4303),
    "B4": ("IS_B4_water_film", card_b4,
           [220, 1450, 1940, 3660], 4404),
    "B5": ("IS_B5_glide", card_b5,
           [240, 1700, 1920, 2350], 4505),
    "B6": ("IS_B6_payoff", card_b6,
           [280, 1800, 1880, 3300], 4606),
}


def finish_card(beat: str):
    asset, drawer, bbox, seed = CARDS[beat]
    out_dir = OUT_ROOT / beat
    out_dir.mkdir(parents=True, exist_ok=True)
    plate = out_dir / f"{asset}.png"
    if plate.exists() and (plate.with_name(f"{asset}.sidecar.json")).exists():
        return plate, seed
    img = drawer()
    img.save(plate)
    sc = sidecar_for(plate, bbox, seed)
    from engine import depth_layers
    depth_layers.derive_masks(plate, sc, plate.with_name(f"{asset}.sidecar.json"))
    sc["plate"] = _rel(plate)
    for layer in sc["layers"]:
        if layer.get("mask"):
            layer["mask"] = _rel(ENGINE / layer["mask"].replace(
                "illustrated_engine/", ""))
    plate.with_name(f"{asset}.sidecar.json").write_text(
        json.dumps(sc, indent=2) + "\n")
    return plate, seed


def main() -> int:
    sys.path.insert(0, str(ENGINE))
    from engine.plate_pipeline import validate_sidecar
    from engine.harmonize import continuity_score
    from PIL import Image as PImage

    scores = {}
    plates = {}
    for beat in ("B1", "B2", "B3", "B4", "B5", "B6"):
        plate, _ = finish_card(beat)
        plates[beat] = plate

    ok = True
    for beat in ("B1", "B2", "B3", "B4", "B5", "B6"):
        plate = plates[beat]
        sc_path = plate.with_name(plate.stem + ".sidecar.json")
        sc = json.loads(sc_path.read_text())
        errs = validate_sidecar(sc)
        score = continuity_score(PImage.open(plate).convert("RGB"), BIBLE)
        scores[beat] = score
        status = "OK" if (not errs and score >= 0.55) else "FAIL"
        if status == "FAIL":
            ok = False
        print(f"{beat} {plate.name}: continuity={score:.3f} "
              f"sidecar_errors={errs or 'none'} [{status}]")
    if not ok:
        print("plates NOT ok")
        return 1
    ASSETS.mkdir(exist_ok=True)
    for beat, plate in plates.items():
        (ASSETS / plate.name).write_bytes(plate.read_bytes())
    print("plates ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
