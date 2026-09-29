"""V16 — brand bible: the single source of visual/audio truth for the channel
(DESIGN.md §7, WP6). Replaces the per-story `visual_bible.json` "look" for
everything this module governs: `brand/<brand_id>/brand.yaml` is loaded once,
validated, and exposed as typed ROLE NAMES (`caption_fill`, `headline`,
`label`, `scrim`, ...). Callers that build render specs (`engine.v15_shots`,
`engine.captions`) put ROLE NAMES in text/shape "fill"/"stroke"/"accent"
payload fields, never a literal `#RRGGBB` — `lint_props` enforces that on any
compiled spec, and `resolve` is the one place a role name becomes a hex, at
render-prop compile time (`engine.scene_renderer.compile_spec`) or PNG
compositing time (captions, sting/outro/cover), never inside the compiler.

Also owns the two other WP6 mechanisms: the brand LUT (`generate_cube`,
`apply_lut`, applied once per plate at ingest in `engine.v15_plates`) and the
sting/outro/cover asset generators (procedural, no external service).
"""
from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent       # illustrated_engine
REPO = ROOT.parent                                   # video_engine
BRAND_DIR = REPO / "brand"
FONT_DIR = ROOT / "assets" / "fonts"
DEFAULT_BRAND_ID = "ink_ember"

REQUIRED_TOP = ("brand_id", "version", "channel_name", "palette", "roles",
                "fonts", "grade", "plate_style", "captions", "safe_zones",
                "sting", "outro", "cover")
REQUIRED_ROLES = ("caption_fill", "caption_stroke", "caption_active",
                  "caption_key", "headline", "headline_2", "label", "scrim")


class BrandError(ValueError):
    pass


# ------------------------------------------------------------- load/validate

@lru_cache(maxsize=8)
def load_brand(brand_id: str = DEFAULT_BRAND_ID) -> dict:
    """Load + validate brand/<brand_id>/brand.yaml. Raises BrandError on any
    schema hole so a broken brand file fails the run, not the gate."""
    path = BRAND_DIR / brand_id / "brand.yaml"
    if not path.exists():
        raise BrandError(f"no brand.yaml for {brand_id!r} ({path})")
    brand = yaml.safe_load(path.read_text())
    errors = validate_brand(brand)
    if errors:
        raise BrandError(f"{path}: " + "; ".join(errors))
    brand["_dir"] = str(path.parent)
    return brand


def validate_brand(brand: dict) -> list:
    """-> list of schema/asset errors (empty = valid). Pure; does not raise,
    so the gate can report every hole at once instead of the first."""
    errors = []
    for key in REQUIRED_TOP:
        if key not in brand:
            errors.append(f"missing key: {key}")
    if errors:
        return errors
    for role in REQUIRED_ROLES:
        if role not in brand["roles"]:
            errors.append(f"roles missing: {role}")
    palette = brand["palette"]
    for role, pal_key in brand["roles"].items():
        if pal_key not in palette:
            errors.append(f"roles.{role} -> palette.{pal_key!r} not in palette")
    for _, spec in brand["fonts"].items():
        if not (FONT_DIR / spec["file"]).is_file():
            errors.append(f"font file missing: {spec['file']}")
        lic = spec.get("license_file")
        if lic and not (FONT_DIR / lic).is_file():
            errors.append(f"font licence file missing: {lic}")
    rail = (brand.get("safe_zones") or {}).get("right_rail") or {}
    if "x" not in rail or "y0" not in rail:
        errors.append("safe_zones.right_rail needs x and y0")
    return errors


def font_path(brand: dict, role: str) -> Path:
    spec = brand["fonts"].get(role) or brand["fonts"]["headline"]
    return FONT_DIR / spec["file"]


# ------------------------------------------------------------- roles -> hex

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def role_hex(brand: dict, role: str) -> str:
    """Role name -> '#RRGGBB'. Raises on an unknown role (never silently
    passes a literal colour through as if it were a role)."""
    if role not in brand["roles"]:
        raise BrandError(f"unknown brand role {role!r}")
    return brand["palette"][brand["roles"][role]]


def role_rgb(brand: dict, role: str) -> tuple:
    """Role name -> (r, g, b) 0-255 ints, for PIL fill= (engine.captions'
    ingest point for brand caption colour, mirroring engine.bible.rgb255)."""
    h = role_hex(brand, role).lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def renderer_roles(brand: dict) -> dict:
    """Every role name -> hex, for staging into render props (the ONE place
    role names get resolved to colour, e.g. compile_spec's `brand` prop)."""
    return {role: brand["palette"][pal_key]
            for role, pal_key in brand["roles"].items()}


def resolve(brand: dict, value):
    """A role-name string -> hex; anything else (already a colour, None,
    a number) passes through unchanged."""
    if isinstance(value, str) and value in brand["roles"]:
        return role_hex(brand, value)
    return value


# ------------------------------------------------------------- props lint

_COLOR_KEYS = {"fill", "stroke", "accent", "halo", "background", "bg",
              "color", "colour"}


def lint_props(obj, *, brand: dict | None = None, _path: str = "") -> list:
    """Walk a compiled spec/props tree; -> list of "<path>: <value>" for
    every literal `#RRGGBB` found under a colour-bearing key. Role-name
    strings (e.g. "headline") are fine; only resolved hex is a violation,
    because that means some caller resolved-then-baked instead of leaving
    the role for the render step to resolve (DESIGN §7.2: "the shot
    compiler rejects any literal colour ... in scene props")."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{_path}.{k}" if _path else str(k)
            if k in _COLOR_KEYS and isinstance(v, str) and _HEX_RE.match(v):
                hits.append(f"{p}: {v}")
            else:
                hits += lint_props(v, brand=brand, _path=p)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += lint_props(v, brand=brand, _path=f"{_path}[{i}]")
    return hits


def assert_no_literal_hex(obj, *, where: str = "spec") -> None:
    hits = lint_props(obj)
    if hits:
        raise BrandError(f"literal colour in {where} props (use a brand role "
                         f"name instead): {hits[:5]}")


# ------------------------------------------------------------- safe zones

def rail_safe_x1(y0: float, y1: float, default_x1: float, *,
                 brand: dict | None = None) -> float:
    """A text box spanning [y0, y1] must not cross the right UI rail: if any
    part of it sits at/below the rail's y0, its right edge is capped at the
    rail's x (DESIGN §7.1 safe_zones.right_rail), never `default_x1`."""
    brand = brand or load_brand()
    rail = brand["safe_zones"]["right_rail"]
    if y1 > float(rail["y0"]):
        return min(default_x1, float(rail["x"]))
    return default_x1


# ------------------------------------------------------------- caption style

def caption_style(brand: dict | None = None) -> dict:
    brand = brand or load_brand()
    cap = dict(brand["captions"])
    cap["fill"] = role_hex(brand, "caption_fill")
    cap["stroke"] = role_hex(brand, "caption_stroke")
    cap["active"] = role_hex(brand, "caption_active")
    cap["key"] = role_hex(brand, "caption_key")
    cap["font"] = str(font_path(brand, "caption"))
    return cap


# ------------------------------------------------------------------- LUT --

def generate_cube(path, s: float, sat: float, sh, hi, lift: float,
                  gamma: float, n: int = 33) -> Path:
    """Generalised S-curve + saturation + split-tone + lift/gamma 3D LUT,
    written as a .cube file (research/phase2/make_lut.py's original,
    generalised in research/phase3/brand_frames.py:make_cube). Pure/
    deterministic: same params -> byte-identical file -> stable sha256."""
    path = Path(path)
    g = np.linspace(0, 1, n)
    b, gg, r = np.meshgrid(g, g, g, indexing="ij")   # .cube order: R fastest
    c = np.stack([r, gg, b], -1).reshape(-1, 3)
    c = c ** gamma
    c = c + s * (c - 0.5) * (1 - np.abs(2 * c - 1))
    lum = (c @ [0.2126, 0.7152, 0.0722])[:, None]
    c = lum + sat * (c - lum)
    c = c + (1 - lum) * np.array(sh) + lum * np.array(hi)
    c = lift + (1 - lift) * c
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(f'TITLE "{path.stem}"\nLUT_3D_SIZE {n}\n')
        np.savetxt(f, np.clip(c, 0, 1), fmt="%.6f")
    return path


def cube_sha256(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cube_path(brand: dict) -> Path:
    return Path(brand["_dir"]) / brand["grade"]["cube"]


def verify_cube_hash(brand: dict) -> bool:
    return cube_sha256(cube_path(brand)) == brand["grade"]["sha256"]


def apply_lut(src, dst, brand: dict | None = None) -> str:
    """Plate ingest step: grade `src` through the brand cube with ffmpeg
    lut3d -> `dst`. Returns the cube's sha256, recorded per plate so the
    gate can prove every plate was actually graded with THIS brand's LUT
    (the "LUT-hash test")."""
    brand = brand or load_brand()
    cube = cube_path(brand)
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf",
         f"lut3d=file={cube}:interp=tetrahedral", str(dst)], check=True)
    return cube_sha256(cube)


# --------------------------------------------------------------- sting --

def sting_audio(out_path, brand: dict | None = None):
    """Procedural sting: a quick high scratch (quill) over a low sine thump
    (timpani), `sting.dur_s` long. Reuses engine.procedural_audio's FFT
    bandpass helper and SR/save_wav instead of reimplementing synthesis."""
    from engine.procedural_audio import SR, _fft_bandpass, save_wav
    brand = brand or load_brand()
    dur = float(brand["sting"]["dur_s"])
    n = int(dur * SR)
    tt = np.arange(n) / SR
    rng = np.random.default_rng(1907)
    scratch = _fft_bandpass(rng.standard_normal(n), 2200.0, 6500.0) \
        * np.exp(-tt * 26)
    thump = np.sin(2 * np.pi * 68.0 * tt * (1 + 0.5 * np.exp(-tt * 9))) \
        * np.exp(-tt * 7)
    y = 0.5 * scratch + 0.85 * thump
    y = y / (np.max(np.abs(y)) or 1.0) * 0.4
    return save_wav(out_path, np.stack([y, y], axis=1).astype(np.float32))


# --------------------------------------------------------- visual overlays

def _hex_rgba(hexcolor: str, alpha: int) -> tuple:
    h = hexcolor.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)


def ink_bloom_overlay(out_path, size=(1080, 1920), brand: dict | None = None):
    """Sting visual: a soft radial ink wash from the centre, `scrim` role
    colour, fully transparent at the edge (the overlay engine.v14_assembly
    fades in/out over `sting.dur_s`)."""
    brand = brand or load_brand()
    w, h = size
    ink = _hex_rgba(role_hex(brand, "scrim"), 255)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    d = np.hypot((xx - cx) / (w * 0.75), (yy - cy) / (h * 0.75))
    a = np.clip(1.0 - d, 0.0, 1.0) ** 1.6
    img = np.zeros((h, w, 4), dtype=np.uint8)
    img[..., 0], img[..., 1], img[..., 2] = ink[0], ink[1], ink[2]
    img[..., 3] = (a * 235).astype(np.uint8)
    Image.fromarray(img, "RGBA").save(out_path)
    return Path(out_path)


def seal_badge(out_path, brand: dict | None = None, *, part_label: str = "",
              diameter: int = 260):
    """Outro visual: a simple procedural wax-seal disc (concentric rings +
    the channel's first letter) in the brand accent/ink roles, plus an
    optional 'Part N' ring caption. No external art asset."""
    brand = brand or load_brand()
    d = diameter
    pad = 24
    img = Image.new("RGBA", (d + pad * 2, d + pad * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = d // 2 + pad
    accent = _hex_rgba(role_hex(brand, "headline_2"), 255)
    ink = _hex_rgba(role_hex(brand, "scrim"), 255)
    paper = _hex_rgba(role_hex(brand, "headline"), 255)
    draw.ellipse([pad, pad, pad + d, pad + d], fill=accent)
    draw.ellipse([pad + 10, pad + 10, pad + d - 10, pad + d - 10], outline=ink,
                 width=5)
    draw.ellipse([pad + 22, pad + 22, pad + d - 22, pad + d - 22], outline=ink,
                 width=2)
    letter = (brand.get("channel_name") or brand["brand_id"])[0].upper()
    f = ImageFont.truetype(str(font_path(brand, "headline")), int(d * 0.42))
    bbox = draw.textbbox((0, 0), letter, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), letter, font=f,
              fill=paper)
    if part_label:
        fb = ImageFont.truetype(str(font_path(brand, "caption")), 26)
        bb = draw.textbbox((0, 0), part_label, font=fb)
        bw = bb[2] - bb[0]
        draw.rounded_rectangle(
            [cx - bw / 2 - 14, pad + d + 6, cx + bw / 2 + 14, pad + d + 40],
            radius=10, fill=ink)
        draw.text((cx - bw / 2 - bb[0], pad + d + 12), part_label, font=fb,
                  fill=paper)
    img = img.filter(ImageFilter.GaussianBlur(0.4))
    img.save(out_path)
    return Path(out_path)


def render_cover(out_path, *, bg_frame, title: str, part_label: str = "",
                 brand: dict | None = None, size=(1080, 1920)):
    """`cover.template == "title_lower_third"`: `bg_frame` (a still, e.g. a
    graded plate or a frame grabbed from the final render) cropped to the
    top 60%, brand seal + 2-line headline title lower-middle, series badge.
    """
    brand = brand or load_brand()
    w, h = size
    canvas = Image.new("RGB", (w, h), _hex_rgba(role_hex(brand, "scrim"), 255)[:3])
    bg = Image.open(bg_frame).convert("RGB")
    bw, bh = bg.size
    top_h = int(h * 0.62)
    sc = max(w / bw, top_h / bh)
    bg = bg.resize((round(bw * sc), round(bh * sc)), Image.LANCZOS)
    canvas.paste(bg.crop((0, 0, w, top_h)), (0, 0))
    draw = ImageDraw.Draw(canvas, "RGBA")
    wash = Image.new("RGBA", (w, h - top_h + 120),
                     _hex_rgba(role_hex(brand, "scrim"), 235))
    canvas.paste(wash, (0, top_h - 120), wash)
    f = ImageFont.truetype(str(font_path(brand, "headline")), 108)
    words = title.upper().split()
    lines, cur = [], ""
    for word in words:
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=f) > w - 140 and cur:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    lines.append(cur)
    lines = lines[:2]
    ty = top_h + 20
    for ln in lines:
        bb = draw.textbbox((0, 0), ln, font=f)
        draw.text(((w - (bb[2] - bb[0])) / 2 - bb[0], ty), ln, font=f,
                  fill=role_hex(brand, "headline"))
        ty += 118
    seal_tmp = Path(tempfile.mktemp(suffix=".png"))
    seal_badge(seal_tmp, brand, part_label=part_label, diameter=180)
    seal = Image.open(seal_tmp).convert("RGBA")
    canvas.paste(seal, (w - seal.width - 40, 40), seal)
    seal_tmp.unlink(missing_ok=True)
    canvas.save(out_path, "JPEG", quality=92)
    return Path(out_path)
