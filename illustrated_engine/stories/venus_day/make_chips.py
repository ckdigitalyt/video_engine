"""Generate stage-chip overlay PNGs for venus_day (proto5).

Chips are full-frame 1080x1920 RGBA cards with a single rounded plate at
y=1318; composev2 composites them via the `stage_overlay` events that
planv3 emits from visual_plan `stage_chips` entries.

Run:  python3 stories/venus_day/make_chips.py   (from repo root)

Outputs build/diag_stages/chip_s01_full.png / chip_s06_full.png / chip_s09_full.png.
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
    "chip_s01": "SPIN 243 DAYS / LAP 225 DAYS",
    "chip_s06": "DAY 117 / YEAR 225",
    "chip_s09": "1.92 SUNRISES PER YEAR",
}


def build(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    disp = ImageFont.truetype(str(Path(FONT_DIR) / "BebasNeue-Regular.ttf"), 54)
    for name, text in CHIPS.items():
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        tw = d.textlength(text, font=disp)
        pad_x, pad_y = 30, 22
        w = int(tw + pad_x * 2 + 26)
        h = 54 + pad_y * 2
        x0 = (W - w) // 2
        d.rounded_rectangle([x0, PLATE_Y, x0 + w, PLATE_Y + h], radius=6,
                            fill=CREAM, outline=NAVY, width=3)
        d.rectangle([x0 + 14, PLATE_Y + pad_y, x0 + 22, PLATE_Y + h - pad_y],
                    fill=ORANGE)
        d.text((x0 + 14 + 22, PLATE_Y + pad_y - 4), text, font=disp, fill=NAVY)
        img.save(out_dir / f"{name}_full.png")
        print(f"{name}_full.png  ({w}x{h} plate at y={PLATE_Y})")


if __name__ == "__main__":
    build(Path(__file__).resolve().parents[2] / "build" / "diag_stages")
