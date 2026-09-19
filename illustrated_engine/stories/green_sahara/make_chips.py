"""Generate stage-chip + typography overlay PNGs for green_sahara (proto8).

Chips are full-frame 1080x1920 RGBA cards with a single rounded plate at
y=1318; composev2 composites them via the `stage_overlay` events that
planv3 emits from visual_plan `stage_chips` entries. The TYPOGRAPHY shot
(S06) uses a full-frame type card — type IS the visual (V5 §6).

Series chrome identical to round_window: NAVY/CREAM/ORANGE plates.

Run:  python3 stories/green_sahara/make_chips.py   (from repo root)
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from engine.diagrams import FONT_DIR  # noqa: E402

W, H = 1080, 1920
PLATE_Y = 1318
NAVY = (28, 40, 62, 255)
CREAM = (240, 231, 212, 255)
ORANGE = (196, 90, 42, 255)

CHIPS = {
    "chip_g1": "6,000 YEARS AGO: HIPPOS IN THE SAHARA",
    "chip_g3": "UNDER 25 MM RAIN A YEAR — TODAY",
    "chip_g4": "26,000-YEAR WOBBLE",
    "chip_g5": "GREEN AGE ENDS ~5,500 YEARS AGO",
    "chip_g7": "DUST: 27 MILLION TONS A YEAR TO THE AMAZON",
}


def _disp(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(Path(FONT_DIR) / "BebasNeue-Regular.ttf"),
                              size)


def build_chips(out_dir: Path) -> None:
    for name, text in CHIPS.items():
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        disp = _disp(54)
        tw = d.textlength(text, font=disp)
        pad_x, pad_y = 30, 22
        w = int(tw + pad_x * 2 + 26)
        h = 54 + pad_y * 2
        x0 = (W - w) // 2
        d.rounded_rectangle([x0, PLATE_Y, x0 + w, PLATE_Y + h], radius=6,
                            fill=CREAM, outline=NAVY, width=3)
        d.rectangle([x0 + 14, PLATE_Y + pad_y, x0 + 22, PLATE_Y + h - pad_y],
                    fill=ORANGE)
        d.text((x0 + 14 + 22, PLATE_Y + pad_y - 4), text, font=disp,
               fill=NAVY)
        img.save(out_dir / f"{name}_full.png")
        print(f"{name}_full.png  ({w}x{h} plate at y={PLATE_Y})")


def build_typo_card(out_dir: Path) -> None:
    """V5 §6 TYPOGRAPHY mode: large type is the visual."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, H], fill=(28, 40, 62, 236))
    d.text((100, 600), "THE BIGGEST DESERT ON EARTH", font=_disp(44),
           fill=ORANGE)
    for text, size, y in (("IT WAS", 190, 680), ("GREEN.", 190, 900)):
        f = _disp(size)
        while d.textlength(text, font=f) > W - 200 and size > 60:
            size -= 6
            f = _disp(size)
        d.text((100, y), text, font=f, fill=CREAM)
    d.rectangle([100, 1140, 660, 1148], fill=ORANGE)
    d.text((100, 1180), "6,000 YEARS AGO — LAKES, GRASS, HIPPOS",
           font=ImageFont.truetype(str(Path(FONT_DIR) / "Inter-Variable.ttf"),
                                   30),
           fill=(240, 231, 212, 210))
    img.save(out_dir / "typo_sahara_full.png")
    print("typo_sahara_full.png  (full-frame 1080x1920)")


if __name__ == "__main__":
    out = Path(__file__).resolve().parents[2] / "build" / "diag_stages"
    out.mkdir(parents=True, exist_ok=True)
    build_chips(out)
    build_typo_card(out)
