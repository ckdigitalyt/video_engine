"""V6 effects — restrained multi-pass bloom for luminous procedural frames.

PIL-only (no new dependencies), deterministic, benchmark-gated behind
ENABLE_BLOOM. Applied ONLY to kinetic frames (clock sweeps, streamlines —
luminous strokes on dark fields). Never to card/text plates.

Pipeline (brief §5): bright-pass threshold -> multi-pass blur -> masked
screen composite back onto the original. The final mask composite confines
the glow to bright neighborhoods so dark ink / backgrounds cannot wash out
and text can never halo.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter


def bloom(img: Image.Image, threshold: int = 160, radius: int = 8,
          strength: float = 0.28, passes: int = 2, glow_scale: int = 4) -> Image.Image:
    """Return a bloomed copy. Restrained by construction:
      - only pixels >= threshold seed the glow (bright-pass)
      - glow chroma comes from the source's own bright pixels
      - glow intensity scaled by `strength` (<0.3 keeps contrast headroom)
      - applied as a screen DELTA on the full-resolution original, so the
        sharp base loses no detail; the glow field itself is soft by
        construction (computed at 1/glow_scale resolution for CPU cost)
      - final composite confines the delta to bright neighborhoods (no
        frame-wide wash, no halos on dark ink)
    """
    if img.mode != "RGB":
        img = img.convert("RGB")
    W, H = img.size
    sw, sh = max(1, W // glow_scale), max(1, H // glow_scale)
    small = img.resize((sw, sh), Image.BILINEAR)
    lum = small.convert("L")
    mask = lum.point(lambda v: 255 if v >= threshold else 0)
    r = max(2, radius // glow_scale)
    for _ in range(max(1, int(passes))):
        mask = mask.filter(ImageFilter.GaussianBlur(r))
        r = max(1, r // 2)
    black = Image.new("RGB", small.size, (0, 0, 0))
    glow = Image.composite(small, black, mask)
    glow = glow.point(lambda v: int(v * strength))
    glow = glow.filter(ImageFilter.GaussianBlur(2))
    lit_small = ImageChops.screen(small, glow)
    # glow-only delta (screen is monotone: lit >= base, so delta >= 0)
    delta = ImageChops.subtract(lit_small, small).resize((W, H), Image.BILINEAR)
    out = ImageChops.screen(img, delta)
    out_mask = mask.filter(ImageFilter.GaussianBlur(2)).resize((W, H), Image.BILINEAR)
    return Image.composite(out, img, out_mask)


def bloom_dir(src_dir: Path, dst_dir: Path, **kw) -> Path:
    """Bloom every f*.png in src_dir into dst_dir (deterministic, idempotent:
    source frames are never modified, so CAS reuse + flag toggles stay safe).
    Returns dst_dir."""
    src_dir, dst_dir = Path(src_dir), Path(dst_dir)
    frames = sorted(src_dir.glob("f*.png"))
    if not frames:
        raise FileNotFoundError(f"no kinetic frames in {src_dir}")
    if dst_dir.exists():
        shutil.rmtree(dst_dir)
    dst_dir.mkdir(parents=True)
    for f in frames:
        bloom(Image.open(f), **kw).save(dst_dir / f.name, "PNG")
    return dst_dir
