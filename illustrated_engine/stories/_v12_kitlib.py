"""V12 Stage 3 — kit-background painters for the story-driven canvas grammar.

Stage 1's documented residual: the V4-era cardlib still bakes cream
grid-paper parchment onto every plate while planv9 plans declare per-kit
background families (engine/canvas_grammar.py: edge_to_edge_dark,
depth_gradient, terrain_field, era_field, split_field, atmosphere_field).
composev5 already consumes the per-shot `canvas` dict (panel_usage /
chrome_density); THIS module makes the plate generator honor the declared
`canvas.background` too.

Rules:
- deterministic (seeded, no randomness, no image-model calls);
- NO grid paper, NO parchment border, NO baked header/footer chrome —
  the kits declare panel_usage "none" + chrome_density none/minimal, so
  plate art is the full canvas and text chrome lives in the plan, not
  the plate;
- the painters cover the background families the three Stage-3 stress
  stories declare; families not needed there remain in plan-space only.
"""
import math
import random

from PIL import Image, ImageDraw, ImageFilter

from _v6_cardlib import H, W, grain, vignette

# ---------------------------------------------------------------- painters --


def dark_field(seed, top=(24, 24, 24), bottom=(12, 12, 12), mott=(18, 18, 18)):
    """`edge_to_edge_dark` — near-black NEUTRAL charcoal gradient.

    Strictly channel-equal on purpose: the hue-histogram gate includes any
    pixel with S>0.15, and a ±2 channel imbalance at near-black values
    would push ~13% of the ground above that gate with a consistent
    pseudo-blue hue (evidence 2026-09-17, MW_B4: 209k stray-blue pixels
    from a 3-channel gap of 2). Equal channels keep the ground out of the
    palette match entirely; the kit's luminous accents own it. No border,
    no grid, no chrome.
    """
    base = Image.new("RGB", (1, H))
    base.putdata([tuple(int(top[i] + (bottom[i] - top[i]) * y / (H - 1))
                        for i in range(3)) for y in range(H)])
    img = base.resize((W, H))
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    for _ in range(7):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(220, 560)
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=mott + (rnd.randint(10, 26),))
    ov = ov.filter(ImageFilter.GaussianBlur(80))
    return Image.alpha_composite(img.convert("RGBA"), ov)


def era_field(seed, base_col=(176, 152, 116), dark=(150, 126, 92),
              edge=(120, 98, 70)):
    """`era_field` — darker archival paper of the event's period.

    timeline_band: an aged documentary record, distinctly darker and more
    sepia than the V4 cream parchment; stains instead of grids, time-ruled
    bands are drawn by the story code as content, not chrome.
    """
    img = Image.new("RGB", (W, H), base_col)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    for _ in range(10):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(200, 520)
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=dark + (rnd.randint(12, 30),))
    ov = ov.filter(ImageFilter.GaussianBlur(60))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    # gentle archival darkening toward all four edges (no visible frame)
    grad = Image.new("L", (W, H), 0)
    dg = ImageDraw.Draw(grad)
    for i in range(120):
        a = int(38 * (1 - i / 120))
        dg.rectangle((i, i, W - 1 - i, H - 1 - i), outline=a)
    grad = grad.filter(ImageFilter.GaussianBlur(40))
    shade = Image.new("RGBA", (W, H), edge + (255,))
    return Image.composite(shade, img.convert("RGBA"), grad.point(lambda v: v))


def terrain_field(seed, base_col=(198, 186, 156), wash=((184, 168, 126, 20),
                                                        (150, 158, 138, 16),
                                                        (206, 196, 164, 22))):
    """`terrain_field` — desaturated map-paper ground with organic washes.

    map_first: reads as cartographic terrain paper (sand/olive family),
    never as grid paper; the story code draws the ocean, landmasses and
    propagation field on top.
    """
    img = Image.new("RGB", (W, H), base_col)
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    for _ in range(16):
        cx, cy = rnd.randint(-80, W + 80), rnd.randint(-60, H + 60)
        rx, ry = rnd.randint(140, 460), rnd.randint(90, 260)
        c = wash[rnd.randrange(len(wash))]
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), fill=c)
    ov = ov.filter(ImageFilter.GaussianBlur(50))
    return Image.alpha_composite(img.convert("RGBA"), ov)


def split_field(seed, cool=(64, 82, 94), warm=(96, 68, 56),
                seam=(226, 222, 212)):
    """`split_field` — before_after: one canvas split by a soft hinge.

    Cool steel half (state A / intact) meets a warm rust half (state B /
    collapsed); a narrow desaturated seam keeps the split reading as ONE
    composed canvas with a hinge, not two separate slides. No grid, no
    chrome.
    """
    img = Image.new("RGB", (W, H))
    img.paste(Image.new("RGB", (W // 2 + 40, H), cool), (0, 0))
    img.paste(Image.new("RGB", (W // 2 + 40, H), warm), (W // 2 - 40, 0))
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    for _ in range(10):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(160, 420)
        col = cool if cx < W // 2 else warm
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=col + (rnd.randint(10, 26),))
    ov = ov.filter(ImageFilter.GaussianBlur(70))
    img = Image.alpha_composite(img.convert("RGBA"), ov)
    grad = Image.new("L", (W, H), 0)
    dg = ImageDraw.Draw(grad)
    for i in range(26):
        dg.line((W // 2 - 13 + i, 0, W // 2 - 13 + i, H),
                fill=int(190 * (1 - i / 26)))
    grad = grad.filter(ImageFilter.GaussianBlur(7))
    seam_img = Image.new("RGBA", (W, H), seam + (255,))
    return Image.composite(seam_img, img, grad.point(lambda v: v))


def depth_field(seed, top=(44, 98, 106), mid=(22, 58, 76), bottom=(8, 18, 36)):
    """`depth_gradient` — scale_descent: surface-to-abyss vertical gradient.

    Reads as descending water column depth, not as a backdrop wash: cool
    aqua light at the top sinking through slate blue to near-black navy —
    the story code draws the scale ladder on top. No grid, no chrome.
    """
    base = Image.new("RGB", (1, H))
    for y in range(H):
        t = y / (H - 1)
        if t < 0.5:
            c = tuple(int(top[i] + (mid[i] - top[i]) * t * 2) for i in range(3))
        else:
            c = tuple(int(mid[i] + (bottom[i] - mid[i]) * (t - 0.5) * 2)
                      for i in range(3))
        base.putpixel((0, y), c)
    img = base.resize((W, H)).convert("RGBA")
    ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    rnd = random.Random(seed)
    for _ in range(9):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        r = rnd.randint(180, 460)
        d.ellipse((cx - r, cy - r // 2, cx + r, cy + r // 2),
                  fill=(14, 38, 54, rnd.randint(10, 24)))
    ov = ov.filter(ImageFilter.GaussianBlur(70))
    return Image.alpha_composite(img, ov)


# ------------------------------------------------------- kit dispatch -------

KIT_BACKGROUND = {
    "edge_to_edge_dark": dark_field,
    "era_field": era_field,
    "terrain_field": terrain_field,
    "split_field": split_field,
    "depth_gradient": depth_field,
}


def kit_background(name, seed, **kw):
    """Paint the declared kit background family. Unknown names fall back to
    dark_field but the story build FAILS loudly instead, because a silent
    grid-paper/legacy fallback is exactly the Stage-1 residual this module
    exists to close."""
    fn = KIT_BACKGROUND.get(name)
    if fn is None:
        raise SystemExit(
            f"kit_background: undeclared background family '{name}' — add a "
            "painter to _v12_kitlib.KIT_BACKGROUND instead of falling back")
    return fn(seed, **kw)


def finish(img, seed, vig=0.26, amount=0.012):
    """Shared finish: fine grain + vignette (cardlib conventions)."""
    img = grain(img, seed, amount=amount)
    return vignette(img, vig)
