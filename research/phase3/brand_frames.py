"""Phase 3 deliverable B: sample frames for 3 brand-bible options.

  venv/bin/python research/phase3/brand_frames.py

REAL: brand LUT generated in code (.cube) and applied to cached V15 plates with ffmpeg lut3d (the
proposed plate-ingest step); fonts are the actual OFL files; palette hexes are exact; safe-zone geometry.
MOCKED: this is a PIL still compositor, not the Remotion renderer. Caption motion (pop/spring), sting,
parallax and grain animation are not shown. The plates are all vintage-ink NIM plates, so options B/C
show a LUT re-grade of ink plates, not plates generated with their own style prompt. The option-C mascot
is a placeholder vector sketch, not a finished character design. No image API is called."""
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

PLATES = Path("/home/ubuntu/video_engine/illustrated_engine/build/cache/v15_plates")
OUT = Path.home() / "phase3_out" / "brand"
FONTS = Path.home() / "phase3_out" / "fonts"
W, H = 1080, 1920
# Shorts UI geometry (design values; exact YouTube insets vary by device and are unverified)
TOP_UI, BOTTOM_UI, RAIL_X, RAIL_Y0 = 220, 1440, 930, 760
CAP_Y, CAP_MAXW = 1180, 780
PLATE = {"hook": "421e0b8c", "mid": "c948c35e", "cover": "8187167d"}

OPTIONS = {
    "A_ink_ember": dict(
        name="Ink & Ember (refined vintage ink)",
        pal=dict(paper="#EDE0C4", ink="#15202B", navy="#1F3A56", accent="#C4502A", gold="#E3A83B", white="#FFF7E8"),
        lut=dict(s=0.12, sat=0.92, sh=(-0.02, 0.0, 0.035), hi=(0.03, 0.012, -0.03), lift=0.0, gamma=1.0),
        head=("BebasNeue-Regular.ttf", None), cap=("ArchivoBlack-Regular.ttf", None),
        eyebrow=("Fraunces-Italic[SOFT,WONK,opsz,wght].ttf", "Bold Italic")),
    "B_deep_signal": dict(
        name="Deep Signal (night-sky modern)",
        pal=dict(paper="#070B16", ink="#070B16", navy="#122440", accent="#3FE0FF", gold="#FFB23F", white="#F2F5FA"),
        lut=dict(s=0.25, sat=1.1, sh=(-0.10, -0.02, 0.16), hi=(0.06, 0.03, -0.05), lift=0.0, gamma=1.9),
        head=("Anton-Regular.ttf", None), cap=("Montserrat[wght].ttf", "Black"),
        eyebrow=("Montserrat[wght].ttf", "Bold")),
    "C_wonder_almanac": dict(
        name="Wonder Almanac (bold pop + mascot)",
        pal=dict(paper="#FFF1D0", ink="#1C1C1E", navy="#17A398", accent="#FF6A4D", gold="#FFC83D", white="#FFFFFF"),
        lut=dict(s=0.10, sat=1.9, sh=(-0.02, 0.05, 0.06), hi=(0.08, 0.04, -0.06), lift=0.04, gamma=0.9),
        head=("LilitaOne-Regular.ttf", None), cap=("Nunito[wght].ttf", "Black"),
        eyebrow=("Nunito[wght].ttf", "ExtraBold")),
}


def font(spec, size):
    f = ImageFont.truetype(str(FONTS / spec[0]), size)
    if spec[1]:
        f.set_variation_by_name(spec[1])
    return f


def rgb(h):
    return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))


def make_cube(path, s, sat, sh, hi, lift, gamma, n=33):
    """Generalisation of research/phase2/make_lut.py: S-curve, saturation, split-tone, lift, gamma."""
    g = np.linspace(0, 1, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")          # .cube order: R fastest
    c = np.stack([r, gg, b], -1).reshape(-1, 3)
    c = c ** gamma
    c = c + s * (c - 0.5) * (1 - np.abs(2 * c - 1))
    l = (c @ [0.2126, 0.7152, 0.0722])[:, None]
    c = l + sat * (c - l)
    c = c + (1 - l) * np.array(sh) + l * np.array(hi)
    c = lift + (1 - lift) * c
    with open(path, "w") as f:
        f.write(f'TITLE "{path.stem}"\nLUT_3D_SIZE {n}\n')
        np.savetxt(f, np.clip(c, 0, 1), fmt="%.6f")


def ingest(key, cube, dst):
    """Plate ingest: brand LUT via ffmpeg lut3d, then a 1.12x punch-in (also hides corner pseudo-signatures)."""
    src = next(PLATES.glob(key + "*.png"))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vf",
                    f"lut3d=file={cube}:interp=tetrahedral", str(dst)], check=True)
    im = Image.open(dst).convert("RGB").resize((W, H), Image.LANCZOS)
    z = 1.12; im = im.resize((int(W * z), int(H * z)), Image.LANCZOS)
    x0, y0 = (im.width - W) // 2, (im.height - H) // 2
    return im.crop((x0, y0, x0 + W, y0 + H))


def vignette(im, strength=0.45):
    y, x = np.mgrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
    m = np.clip(1 - strength * np.clip(d - 0.55, 0, None) ** 1.6, 0, 1)
    return Image.fromarray((np.asarray(im, np.float32) * m[..., None]).astype(np.uint8))


def grain(im, amt=10, seed=1):
    n = np.random.default_rng(seed).normal(0, amt, (H, W, 1))
    return Image.fromarray(np.clip(np.asarray(im, np.float32) + n, 0, 255).astype(np.uint8))


def grad(im, color, y0, y1, a0, a1):
    """Vertical scrim for text legibility."""
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov); c = rgb(color)
    for y in range(y0, y1):
        t = (y - y0) / max(1, y1 - y0); d.line([(0, y), (W, y)], fill=c + (int(a0 + (a1 - a0) * t),))
    return Image.alpha_composite(im.convert("RGBA"), ov)


def text_c(d, y, s, f, fill, stroke=0, sfill=None, x=W // 2, anchor="mt", spacing=0):
    if spacing:
        tot = sum(f.getlength(ch) for ch in s) + spacing * (len(s) - 1); cx = x - tot / 2
        for ch in s:
            d.text((cx, y), ch, font=f, fill=fill, anchor="lm" if anchor[1] == "m" else "lt", stroke_width=stroke, stroke_fill=sfill); cx += f.getlength(ch) + spacing
        return
    d.text((x, y), s, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sfill)


def fit(spec, s, maxw, start):
    size = start
    while size > 20 and font(spec, size).getlength(s) > maxw:
        size -= 4
    return font(spec, size)


def caption(im, o, words, active, key, y=CAP_Y):
    """Word-level caption: one phrase (<=4 words), active word highlighted, keyword (number/key noun) emphasised.
    Style differs per option; geometry (centre y, max width) is shared and safe-zone checked."""
    p = o["pal"]; d = ImageDraw.Draw(im); base = 104 if o is OPTIONS["C_wonder_almanac"] else 100
    fs = [font(o["cap"], int(base * (1.18 if i == key else 1.0))) for i in range(len(words))]
    sp = 22; widths = [f.getlength(w) for f, w in zip(fs, words)]
    tot = sum(widths) + sp * (len(words) - 1)
    if tot > CAP_MAXW:  # shrink uniformly to stay inside the safe width
        k = CAP_MAXW / tot; fs = [font(o["cap"], int(f.size * k)) for f in fs]; widths = [f.getlength(w) for f, w in zip(fs, words)]
        tot = sum(widths) + sp * (len(words) - 1)
    x = W / 2 - tot / 2
    for i, (w, f, wd) in enumerate(zip(words, fs, widths)):
        style = list(OPTIONS).index(next(k for k, v in OPTIONS.items() if v is o))
        fill = p["white"]
        if i == key:
            fill = p["accent"] if style != 1 else p["gold"]
        if style == 0:      # A: bone ink-stroked type, active word brass underline, key word ember
            if i == active: fill = p["gold"] if i != key else fill
            d.text((x, y), w, font=f, fill=fill, anchor="ls", stroke_width=9, stroke_fill=p["ink"])
            if i == active: d.rectangle([x, y + 14, x + wd, y + 22], fill=p["gold"])
        elif style == 1:    # B: white on soft shadow, active word in a cyan pill, numbers amber
            if i == active:
                d.rounded_rectangle([x - 12, y - f.size * 0.82, x + wd + 12, y + 18], radius=14, fill=p["accent"])
                fill = p["ink"]
            sh = Image.new("RGBA", im.size, (0, 0, 0, 0)); ImageDraw.Draw(sh).text((x + 4, y + 6), w, font=f, fill=(0, 0, 0, 170), anchor="ls")
            im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(6))); d = ImageDraw.Draw(im)
            d.text((x, y), w, font=f, fill=fill, anchor="ls")
        else:               # C: fat charcoal stroke + drop, active word sunflower, key word coral sticker
            if i == key:
                d.rounded_rectangle([x - 14, y - f.size * 0.86, x + wd + 14, y + 22], radius=20, fill=p["accent"], outline=p["ink"], width=6)
                fill = p["white"]
            elif i == active: fill = p["gold"]
            d.text((x + 5, y + 7), w, font=f, fill=p["ink"], anchor="ls", stroke_width=12, stroke_fill=p["ink"])
            d.text((x, y), w, font=f, fill=fill, anchor="ls", stroke_width=12, stroke_fill=p["ink"])
        x += wd + sp
    return im


def mascot(im, cx, cy, s, p):
    """PLACEHOLDER sketch of 'Tik' the trilobite field-explorer (option C). Not final character art."""
    d = ImageDraw.Draw(im); ink = p["ink"]; lw = max(4, int(s * 0.04))
    d.ellipse([cx - s * .42, cy - s * .30, cx + s * .42, cy + s * .62], fill=p["navy"], outline=ink, width=lw)
    for k in range(1, 5):
        yy = cy - s * .05 + k * s * .13; d.arc([cx - s * .40, yy - s * .12, cx + s * .40, yy + s * .12], 200, 340, fill=ink, width=lw)
    d.line([cx, cy - s * .1, cx, cy + s * .6], fill=ink, width=lw)
    d.pieslice([cx - s * .5, cy - s * .55, cx + s * .5, cy + s * .25], 180, 360, fill=p["navy"], outline=ink, width=lw)
    for ex in (-.18, .18):
        d.ellipse([cx + s * ex - s * .12, cy - s * .38, cx + s * ex + s * .12, cy - s * .12], fill="white", outline=ink, width=lw)
        d.ellipse([cx + s * ex - s * .04, cy - s * .30, cx + s * ex + s * .06, cy - s * .18], fill=ink)
    d.chord([cx - s * .34, cy - s * .78, cx + s * .34, cy - s * .30], 180, 360, fill=p["gold"], outline=ink, width=lw)
    d.rectangle([cx - s * .46, cy - s * .56, cx + s * .46, cy - s * .48], fill=p["gold"], outline=ink, width=lw)


def logo(im, o, x, y, scale=1.0):
    p = o["pal"]; d = ImageDraw.Draw(im); st = list(OPTIONS.values()).index(o)
    if st == 0:   # brass wax seal with MA monogram
        r = 70 * scale
        d.ellipse([x - r, y - r, x + r, y + r], fill=p["accent"], outline=p["gold"], width=int(6 * scale))
        d.ellipse([x - r * .78, y - r * .78, x + r * .78, y + r * .78], outline=p["paper"], width=int(3 * scale))
        text_c(d, y, "MA", font(o["head"], int(84 * scale)), p["paper"], anchor="mm", x=x)
    elif st == 1:  # signal ring + dot
        r = 46 * scale
        for k, a in ((1.0, 255), (1.5, 120), (2.0, 50)):
            d.ellipse([x - r * k, y - r * k, x + r * k, y + r * k], outline=rgb(p["accent"]) + (a,), width=int(5 * scale))
        d.ellipse([x - 14 * scale, y - 14 * scale, x + 14 * scale, y + 14 * scale], fill=p["accent"])
    else:
        mascot(im, x, y, 170 * scale, p)


def frame_hook(o, plate):
    p = o["pal"]; st = list(OPTIONS.values()).index(o)
    im = grad(plate, p["ink"], 0, 900, 215, 0)
    d = ImageDraw.Draw(im)
    eb = font(o["eyebrow"], 46)
    if st == 0:
        text_c(d, 300, "Siberia, 30 June 1908", eb, p["gold"], stroke=3, sfill=p["ink"])
        f = fit(o["head"], "80 MILLION TREES.", 900, 230)
        text_c(d, 370, "80 MILLION TREES.", f, p["white"], stroke=8, sfill=p["ink"])
        text_c(d, 370 + f.size * .92, "ZERO CRATER.", f, p["accent"], stroke=8, sfill=p["ink"])
        d.rectangle([W / 2 - 150, 370 + f.size * 1.95, W / 2 + 150, 370 + f.size * 1.95 + 10], fill=p["gold"])
    elif st == 1:
        text_c(d, 300, "SIBERIA  ·  1908", eb, p["accent"], spacing=8)
        f = fit(o["head"], "80 MILLION TREES", 880, 200)
        text_c(d, 380, "80 MILLION TREES", f, p["white"])
        text_c(d, 380 + f.size * 1.18, "ZERO CRATER", f, p["accent"])
    else:
        f = fit(o["head"], "80 MILLION TREES", 860, 170)
        text_c(d, 330, "80 MILLION TREES", f, p["white"], stroke=12, sfill=p["ink"])
        sf = font(o["head"], 130); tw = int(sf.getlength("ZERO CRATER")) + 110
        tag = Image.new("RGBA", (tw, 200), (0, 0, 0, 0)); td = ImageDraw.Draw(tag)
        td.rounded_rectangle([10, 10, tw - 10, 190], radius=36, fill=p["gold"], outline=p["ink"], width=10)
        text_c(td, 104, "ZERO CRATER", sf, p["ink"], anchor="mm", x=tw // 2)
        tag = tag.rotate(-4, expand=True, resample=Image.BICUBIC); im.alpha_composite(tag, (W // 2 - tag.width // 2, 520))
    return im


def frame_mid(o, plate):
    p = o["pal"]; st = list(OPTIONS.values()).index(o)
    im = grad(plate, p["ink"], 900, H, 0, 215)
    d = ImageDraw.Draw(im)
    # giant-number label with leader line (V15 PLATE_SHOT grammar, restyled)
    num = font(o["head"], 190 if st != 2 else 150); sub = font(o["eyebrow"], 44)
    col = p["gold"] if st != 2 else p["white"]
    if st == 2:
        d.rounded_rectangle([140, 300, 800, 560], radius=34, fill=p["navy"], outline=p["ink"], width=8)
    text_c(d, 320, "2,150 km²", num, col, stroke=6 if st != 1 else 0, sfill=p["ink"], x=470)
    text_c(d, 320 + num.size * 1.02, "of forest flattened" if st != 1 else "OF FOREST FLATTENED", sub, p["white"],
           stroke=3 if st != 1 else 0, sfill=p["ink"], x=470, spacing=0 if st != 1 else 4)
    d.line([(620, 600), (700, 760)], fill=p["accent"] if st != 2 else p["ink"], width=6)
    d.ellipse([688, 748, 712, 772], fill=p["accent"])
    return caption(im, o, ["it", "exploded", "in", "MID-AIR"], active=1, key=3)


def frame_cover(o, plate):
    """Cover frame (also the outro end-card): title in the safe zone, series badge, channel mark."""
    p = o["pal"]; st = list(OPTIONS.values()).index(o)
    im = grad(grad(plate, p["ink"], 0, 820, 150, 0), p["ink"], 820, H, 0, 235)
    d = ImageDraw.Draw(im)
    lines = ["THE EXPLOSION", "WITH NO CRATER"]
    f = fit(o["head"], max(lines, key=len), 860, 190 if st != 2 else 140)
    y = 1000
    for i, s in enumerate(lines):
        col = p["white"] if i == 0 else (p["accent"] if st != 1 else p["accent"])
        text_c(d, y, s, f, col, stroke=0 if st == 1 else (8 if st == 0 else 12), sfill=p["ink"]); y += f.size * (1.0 if st != 2 else 1.1)
    bf = font(o["eyebrow"], 48)
    badge = "Tunguska · Part 1 of 3" if st == 0 else ("TUNGUSKA  ·  PART 1/3" if st == 1 else "TUNGUSKA · PART 1 of 3")
    bw = bf.getlength(badge) + (60 if st != 1 else 60 + 4 * len(badge))
    bx0, by0 = W / 2 - bw / 2, y + 30
    if st == 0:
        d.rectangle([bx0, by0, bx0 + bw, by0 + 78], fill=p["ink"], outline=p["gold"], width=4)
    elif st == 1:
        d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + 78], radius=39, outline=p["accent"], width=4)
    else:
        d.rounded_rectangle([bx0, by0, bx0 + bw, by0 + 78], radius=39, fill=p["gold"], outline=p["ink"], width=6)
    text_c(d, by0 + 39, badge, bf, p["gold"] if st == 0 else (p["accent"] if st == 1 else p["ink"]),
           anchor="mm", spacing=4 if st == 1 else 0)
    logo(im, o, W // 2, 470 if st != 2 else 500, 1.3 if st != 2 else 1.5)
    mf = font(o["eyebrow"], 40)
    text_c(d, 640 if st != 2 else 700, "MOST AMAZING", mf, p["white"], stroke=3 if st != 1 else 0, sfill=p["ink"], spacing=10)
    return im


def safezones(im):
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(ov); red = (255, 40, 40, 90)
    d.rectangle([0, 0, W, TOP_UI], fill=red); d.rectangle([0, BOTTOM_UI, W, H], fill=red)
    d.rectangle([RAIL_X, RAIL_Y0, W, BOTTOM_UI], fill=red)
    d.rectangle([W / 2 - CAP_MAXW / 2, CAP_Y - 110, W / 2 + CAP_MAXW / 2, CAP_Y + 40], outline=(60, 255, 90, 255), width=4)
    d.text((20, BOTTOM_UI + 20), "Shorts UI (title/channel/sound)", fill="white", font=ImageFont.truetype(str(FONTS / "Inter-Variable.ttf"), 34))
    d.text((20, 150), "Shorts UI (search/header)", fill="white", font=ImageFont.truetype(str(FONTS / "Inter-Variable.ttf"), 34))
    return Image.alpha_composite(im.convert("RGBA"), ov)


def finish(im, o):
    st = list(OPTIONS.values()).index(o); im = im.convert("RGB")
    if st == 0: im = grain(vignette(im, .5), 9)
    elif st == 1: im = vignette(im, .6)
    else: im = grain(im, 5)
    return im


def sheet(paths, labels, dst, cw=360, title=None):
    ch = cw * 16 // 9; th = 60 if title else 0
    s = Image.new("RGB", (cw * len(paths) + 20 * (len(paths) + 1), ch + 70 + th), "#202020"); d = ImageDraw.Draw(s)
    f = ImageFont.truetype(str(FONTS / "Inter-Variable.ttf"), 24)
    if title: d.text((20, 18), title, fill="white", font=ImageFont.truetype(str(FONTS / "Inter-Variable.ttf"), 30))
    for i, (pp, lb) in enumerate(zip(paths, labels)):
        x = 20 + i * (cw + 20); s.paste(Image.open(pp).convert("RGB").resize((cw, ch), Image.LANCZOS), (x, th + 20))
        d.text((x, th + ch + 30), lb, fill="white", font=f)
    s.save(dst, quality=90)


if __name__ == "__main__":
    rows = []
    for key, o in OPTIONS.items():
        od = OUT / key; od.mkdir(parents=True, exist_ok=True)
        cube = od / f"{key}.cube"; make_cube(cube, **o["lut"])
        plates = {k: ingest(v, cube, od / f"_plate_{k}.png") for k, v in PLATE.items()}
        fr = {"hook": frame_hook(o, plates["hook"]), "mid": frame_mid(o, plates["mid"]), "cover": frame_cover(o, plates["cover"])}
        paths = []
        for k, im in fr.items():
            pth = od / f"{k}.png"; finish(im, o).save(pth); paths.append(pth)
        safezones(Image.open(od / "mid.png")).convert("RGB").save(od / "mid_safezones.png"); paths.append(od / "mid_safezones.png")
        for k in PLATE: (od / f"_plate_{k}.png").unlink()
        sheet(paths, ["hook (t≈0.3 s)", "mid-explainer + caption", "cover / outro card", "safe-zone check"],
              od / "contact_sheet.jpg", title=o["name"])
        rows.append((o["name"], paths[:3]))
    cw = 300; ch = cw * 16 // 9
    s = Image.new("RGB", (3 * cw + 80 + 360, len(rows) * (ch + 20) + 20), "#202020"); d = ImageDraw.Draw(s)
    f = ImageFont.truetype(str(FONTS / "Inter-Variable.ttf"), 28)
    for r, (nm, ps) in enumerate(rows):
        y = 20 + r * (ch + 20)
        d.multiline_text((20, y + ch // 2 - 40), nm.replace(" (", "\n("), fill="white", font=f)
        for i, pp in enumerate(ps):
            s.paste(Image.open(pp).convert("RGB").resize((cw, ch), Image.LANCZOS), (380 + i * (cw + 20), y))
    s.save(OUT / "comparison.jpg", quality=90)
    print("ok", OUT)
