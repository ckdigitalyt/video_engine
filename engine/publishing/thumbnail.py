"""Deterministic thumbnail generation for the OpenClaw Video Engine.

Renders a 1280x720 thumbnail (dark ``#0B0E14`` background, cyan ``#4FC3F7``
accent per StyleSpec v1) using Pillow when available. If Pillow is missing the
module degrades gracefully to an equivalent standalone SVG (``thumbnail.svg``)
— never a hard Manim dependency. Fully deterministic: no randomness, fixed
layout, supersampled text for crisp edges.

CLI::

    python -m engine.publishing.thumbnail results/space_black_engine
    python -m engine.publishing.thumbnail results/space_black_engine "Why does space look black?"
"""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:  # graceful degradation — Pillow may be absent
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except Exception:  # pragma: no cover - exercised only without Pillow
    Image = ImageDraw = ImageFont = None  # type: ignore
    HAS_PIL = False

try:
    from engine.assets.fonts import find_font
except ImportError:  # allow standalone use when repo root is on sys.path
    from assets.fonts import find_font  # type: ignore

from engine.publishing.metadata import generate_metadata, save

# StyleSpec v1 palette.
BG = (11, 14, 20)        # #0B0E14
ACCENT = (79, 195, 247)  # #4FC3F7 cyan
MUTED = (154, 167, 184)  # #9AA7B8 secondary text

WIDTH, HEIGHT = 1280, 720
SUPERSAMPLE = 2  # render at 2x, downscale with LANCZOS for clean text

# Designed-thumbnail palette (matches the render background #0B0F1A).
NAVY = (11, 15, 26)
HEADLINE_CLAIM_COLOR = (245, 247, 250)   # #F5F7FA near-white
HEADLINE_TWIST_COLOR = (255, 213, 79)    # #FFD54F amber (payoff color)


def split_hook(hook: str) -> Tuple[str, str]:
    """Split a hook sentence into ``(claim, twist)`` on its paradox hinge.

    "This shape holds exactly π paint — but can never be painted" →
    ("This shape holds exactly π paint", "can never be painted").
    Deterministic; returns ``(hook, "")`` when there is no hinge.
    """
    text = (hook or "").strip().rstrip(".!?\"'")
    if not text:
        return "", ""
    for sep in (" — ", " — ", " – ", " - "):
        if sep in text:
            claim, twist = text.split(sep, 1)
            twist = twist.strip()
            if twist.lower().startswith("but "):
                twist = twist[4:].strip()
            if claim.strip() and twist:
                return claim.strip(), twist
    m = re.search(r",\s+but\s+|\s+but\s+", text)
    if m:
        claim = text[: m.start()].strip().rstrip(",")
        twist = text[m.end():].strip()
        if claim and twist:
            return claim, twist
    return text, ""


def compose_designed_thumbnail(frame_path: Optional[str] = None,
                               topic: str = "", hook: str = "",
                               out_path: str = "thumbnail.jpg") -> str:
    """Compose a DESIGNED 1280x720 ``thumbnail.jpg`` (deterministic, PIL).

    Never a raw video frame: the hero frame (when available) is used as a
    dimmed backdrop under a navy wash + bottom gradient consistent with
    the video's dark-navy look, with a large two-tone headline derived
    from the hook's claim/twist split ("THIS SHAPE HOLDS EXACTLY π PAINT"
    near-white / "CAN NEVER BE PAINTED" amber).  Raises when Pillow is
    missing — callers fall back to the SVG layout thumbnail.
    """
    if not HAS_PIL:
        raise RuntimeError("compose_designed_thumbnail needs Pillow")

    scale = SUPERSAMPLE
    W, H = WIDTH * scale, HEIGHT * scale

    base = None
    if frame_path and os.path.exists(frame_path):
        try:
            base = Image.open(frame_path).convert("RGB")
        except Exception:  # noqa: BLE001 — unreadable frame → navy base
            base = None
    if base is not None:
        # cover-crop the frame to 16:9 so it never distorts
        src_w, src_h = base.size
        target_ratio = W / H
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            x0 = (src_w - new_w) // 2
            base = base.crop((x0, 0, x0 + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            y0 = max(0, int((src_h - new_h) * 0.35))  # bias above center
            base = base.crop((0, y0, src_w, y0 + new_h))
        base = base.resize((W, H), Image.LANCZOS)
    else:
        base = Image.new("RGB", (W, H), NAVY)

    # navy wash + bottom gradient for headline legibility
    wash = Image.new("L", (1, H))
    for y in range(H):
        t = max(0.0, (y - 0.30 * H) / (0.70 * H))
        wash.putpixel((0, y), int(95 + 135 * t))
    wash = wash.resize((W, H))
    base.paste(Image.new("RGB", (W, H), NAVY), (0, 0), wash)
    img = base
    draw = ImageDraw.Draw(img)

    # headline: claim (near-white) + twist (amber), large, word-wrapped
    claim, twist = split_hook(hook)
    if not claim:
        claim = (topic or "").split(":")[0].strip() or "Untitled video"

    margin = 80 * scale
    max_width = W - 2 * margin

    def _lines_for(text: str, font) -> List[str]:
        return _wrap(text.upper(), font, max_width)

    font_size = 88
    while font_size >= 44:
        font = _pick_font("bold", font_size * scale)
        claim_lines = _lines_for(claim, font)
        twist_lines = _lines_for(twist, font) if twist else []
        if len(claim_lines) <= 2 and len(twist_lines) <= 1:
            break
        font_size -= 6
    if not claim_lines:
        claim_lines = [claim.upper()]

    line_h = int(font_size * 1.22 * scale)
    total_h = line_h * (len(claim_lines) + len(twist_lines))
    y = H - 96 * scale - total_h

    # accent bar left of the headline block
    draw.rectangle((36 * scale, y + 6 * scale, 50 * scale,
                    y + total_h - 6 * scale), fill=ACCENT)

    for line in claim_lines:
        draw.text((margin, y), line, font=font,
                  fill=HEADLINE_CLAIM_COLOR,
                  stroke_width=4 * scale, stroke_fill=NAVY)
        y += line_h
    for line in twist_lines:
        draw.text((margin, y), line, font=font,
                  fill=HEADLINE_TWIST_COLOR,
                  stroke_width=4 * scale, stroke_fill=NAVY)
        y += line_h

    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.save(out_path, "JPEG", quality=92)
    return out_path


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[Dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _topic_from_run(run_dir: str) -> Optional[str]:
    beatsheet = _read_json(os.path.join(run_dir, "beatsheet.json"))
    if beatsheet:
        topic = (beatsheet.get("metadata") or {}).get("topic")
        if topic:
            return str(topic)
    # v0.3 runs: topic lives in topic.json / visualspec.json metadata
    topic_file = _read_json(os.path.join(run_dir, "topic.json"))
    if topic_file and topic_file.get("topic"):
        return str(topic_file["topic"])
    vs = _read_json(os.path.join(run_dir, "visualspec.json"))
    if vs:
        topic = (vs.get("metadata") or {}).get("topic")
        if topic:
            return str(topic)
    return None


def _hook_phrase_from_run(run_dir: str) -> str:
    beatsheet = _read_json(os.path.join(run_dir, "beatsheet.json"))
    if not beatsheet:
        return ""
    beats = list(beatsheet.get("beats") or [])
    if not beats:
        return ""
    beat = next((b for b in beats if b.get("intent") == "hook"), beats[0])
    text = (beat.get("narration") or "").strip()
    if not text:
        return ""
    sentence = text.split(".")[0].split("!")[0].split("?")[0].strip()
    if len(sentence) > 40:
        words = sentence.split()
        sentence = " ".join(words[:7])
    return sentence


def _pick_font(weight: str = "bold", size: int = 48):
    """Return a PIL font; falls back to PIL default when no font file found."""
    path = find_font(weight)
    if path and ImageFont is not None:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _wrap(text: str, font, max_width: int) -> List[str]:
    """Word-wrap ``text`` to fit ``max_width`` px at the given font."""
    words = (text or "").split()
    if not words:
        return []
    lines: List[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if font.getlength(candidate) <= max_width or not cur:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _layout_lines(topic: str, hook: str, font, max_width: int) -> List[str]:
    """Two hook lines: the topic wrapped to <=2 lines; when it fits on one,
    the key narration phrase becomes the second line."""
    lines = _wrap(topic, font, max_width)
    if len(lines) > 2:
        # Shrink font until the topic fits on two lines.
        return _wrap(topic, font, max_width)[:2]  # caller re-runs with smaller font
    if len(lines) == 1 and hook:
        second = _wrap(hook, font, max_width)
        if second:
            lines.append(second[0])
    return lines[:2]


# ────────────────────────────────────────────────────────────────────────────
# Renderers
# ────────────────────────────────────────────────────────────────────────────

def _render_png(topic: str, hook: str, out_path: str) -> str:
    """Render 1280x720 PNG (supersampled 2x, LANCZOS downscale)."""
    scale = SUPERSAMPLE
    W, H = WIDTH * scale, HEIGHT * scale
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    font_size = 60
    font = _pick_font("bold", font_size * scale)
    max_width = (WIDTH - 160) * scale  # 80px margins each side

    lines = _layout_lines(topic, hook, font, max_width)
    while len(lines) > 2 and font_size > 36:
        font_size -= 4
        font = _pick_font("bold", font_size * scale)
        lines = _layout_lines(topic, hook, font, max_width)

    # Top-left accent bar.
    draw.rectangle(
        (80 * scale, 92 * scale, 176 * scale, 102 * scale), fill=ACCENT
    )
    # Bottom hairline accent.
    draw.rectangle((0, H - 4 * scale, W, H), fill=ACCENT)

    # Title lines (cyan, bold).
    y = 200 * scale
    line_height = int(font_size * 1.3 * scale)
    for line in lines:
        draw.text((80 * scale, y), line, font=font, fill=ACCENT)
        y += line_height

    # Footer attribution (muted, small).
    footer_font = _pick_font("regular", 28 * scale)
    draw.text(
        (80 * scale, HEIGHT * scale - 90 * scale),
        "OpenClaw Video Engine",
        font=footer_font,
        fill=MUTED,
    )

    img = img.resize((WIDTH, HEIGHT), Image.LANCZOS)
    img.save(out_path, "PNG")
    return out_path


def _render_svg(topic: str, hook: str, out_path: str) -> str:
    """Pillow-free fallback: equivalent layout as standalone SVG."""
    lines = _wrap_svg(topic, 60, max_chars=38)
    if len(lines) == 1 and hook:
        second = _wrap_svg(hook, 60, max_chars=38)
        if second:
            lines.append(second[0])
    lines = lines[:2]

    def esc(s: str) -> str:
        return (
            s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;")
        )

    texts = []
    y = 200
    for line in lines:
        texts.append(
            f'<text x="80" y="{y}" fill="#4FC3F7" font-size="60" '
            f'font-family="DejaVu Sans, Arial, sans-serif" font-weight="bold">{esc(line)}</text>'
        )
        y += 78

    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <rect width="1280" height="720" fill="#0B0E14"/>
  <rect x="80" y="92" width="96" height="10" fill="#4FC3F7"/>
  <rect x="0" y="716" width="1280" height="4" fill="#4FC3F7"/>
  {chr(10).join(texts)}
  <text x="80" y="630" fill="#9AA7B8" font-size="28" font-family="DejaVu Sans, Arial, sans-serif">OpenClaw Video Engine</text>
</svg>
"""
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(svg)
    return out_path


def _wrap_svg(text: str, font_size: int, max_chars: int) -> List[str]:
    """Rough char-based wrap for the SVG fallback (no font metrics)."""
    words = (text or "").split()
    if not words:
        return []
    avg = 0.55 * font_size  # approximate avg char width
    max_width = WIDTH - 160
    per_line = max(int(max_width / avg), 8)
    lines: List[str] = []
    cur = ""
    for word in words:
        candidate = f"{cur} {word}".strip()
        if len(candidate) <= per_line or not cur:
            cur = candidate
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines[:2]


# ────────────────────────────────────────────────────────────────────────────
# Public API
# ────────────────────────────────────────────────────────────────────────────

def generate_thumbnail(
    run_dir: Optional[str] = None,
    topic: Optional[str] = None,
    out_dir: Optional[str] = None,
) -> str:
    """Generate a thumbnail for a run and return the output path.

    ``run_dir`` supplies the topic/hook from ``beatsheet.json`` when ``topic``
    is not given. Output is ``<out_dir>/thumbnail.png`` (Pillow) or
    ``<out_dir>/thumbnail.svg`` (fallback); ``out_dir`` defaults to ``run_dir``.
    """
    if run_dir:
        topic = topic or _topic_from_run(run_dir) or os.path.basename(os.path.normpath(run_dir)).replace("_", " ")
        hook = _hook_phrase_from_run(run_dir)
    else:
        hook = ""
    topic = (topic or "").strip() or "Untitled video"

    out_dir = out_dir or run_dir
    if not out_dir:
        raise ValueError("generate_thumbnail needs out_dir when run_dir is not given")
    os.makedirs(out_dir, exist_ok=True)

    if HAS_PIL:
        out_path = os.path.join(out_dir, "thumbnail.png")
        return _render_png(topic, hook, out_path)
    out_path = os.path.join(out_dir, "thumbnail.svg")
    return _render_svg(topic, hook, out_path)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI: write thumbnail + metadata.json for a run dir.

    Usage: ``python -m engine.publishing.thumbnail <run_dir> [topic]``
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="engine.publishing.thumbnail",
        description="Generate thumbnail.png and metadata.json for a video run.",
    )
    parser.add_argument("run_dir", help="results/<run> directory with artifacts")
    parser.add_argument("topic", nargs="?", default=None, help="topic override (default: from beatsheet)")
    parser.add_argument("--out", default=None, help="output dir (default: run_dir)")
    args = parser.parse_args(argv)

    out = args.out or args.run_dir
    meta = generate_metadata(args.run_dir, topic=args.topic)
    meta_path = save(meta, out)
    thumb_path = generate_thumbnail(args.run_dir, topic=args.topic, out_dir=out)
    print(f"metadata: {meta_path}")
    print(f"thumbnail: {thumb_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
