#!/usr/bin/env python3
"""generate_thumbnail.py — FLUX.1 thumbnail + Gemini packaging check (expert §6.2).

Generates a high-contrast, palette-consistent thumbnail for a finished video
and runs the Gemini review agent against title+thumbnail pairing to verify a
strong curiosity gap BEFORE publish.

Usage:
  python tools/generate_thumbnail.py results/<slug>/<slug>_mixed.mp4 \
      --title "Europa: The Ocean Under the Ice" [--out thumb.png]

Outputs:
  <run_dir>/thumbnail.png            generated FLUX.1 thumbnail (1280x720)
  <run_dir>/thumbnail_review.json    Gemini packaging verdict

Non-fatal by design: a failed thumbnail never blocks the video pipeline.
"""

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def _load_report(video_path: str) -> dict:
    """Pull topic/title defaults from the run's report when not given."""
    run_dir = Path(video_path).parent
    report = {}
    rp = run_dir / "run_report.json"
    if rp.exists():
        try:
            report = json.loads(rp.read_text())
        except Exception:
            pass
    return report, run_dir


def _gen_thumbnail(prompt: str, out_path: str) -> bool:
    """Generate a 1280x720 thumbnail via the provider fallback chain
    (NVIDIA NIM FLUX → SiliconFlow FLUX → Pollinations)."""
    from src.providers.image_gen import ImageGenFactory
    factory = ImageGenFactory.from_config()
    for name in ("nvidia_nim", "siliconflow", "pollinations"):
        try:
            provider = factory.get(name)
            if provider is None:
                continue
            print(f"  [thumb] trying provider {name} ...")
            url = provider.generate(prompt, width=1280, height=720)
            if not url:
                continue
            import subprocess
            r = subprocess.run(
                ["curl", "-sL", "-o", out_path, url], capture_output=True,
                text=True, timeout=120)
            if r.returncode == 0 and os.path.exists(out_path) and \
                    os.path.getsize(out_path) > 5000:
                print(f"  [thumb] OK via {name} -> {out_path}")
                return True
        except Exception as e:  # noqa: BLE001
            print(f"  [thumb] {name} failed: {str(e)[:120]}")
    return False


def _packaging_review(title: str, thumb_path: str, topic: str) -> dict:
    """Gemini packaging check: does the title+thumbnail create a curiosity
    gap?  Non-fatal — quota-flaky chain mirrors review_video.py."""
    try:
        import subprocess
        r = subprocess.run(
            [sys.executable, str(REPO / "review_video.py"), "--help"],
            capture_output=True, text=True, timeout=30)
        # review_video.py reviews VIDEO files; for a static thumb we call
        # Gemini directly with a small image prompt instead.
    except Exception:
        pass
    try:
        import google.generativeai as genai
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            return {"passed": None, "reason": "no GEMINI_API_KEY"}
        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.5-flash")
        img = genai.upload_file(thumb_path)
        resp = model.generate_content([
            "You are a YouTube packaging strategist. Score 0-100 how well "
            f"this thumbnail pairs with the title: '{title}' (topic: {topic}). "
            "Check: curiosity gap, text legibility, color pop, subject clarity. "
            "Return strict JSON {\"score\": int, \"verdict\": \"pass|revise\", "
            "\"notes\": \"...\"}.",
            img,
        ])
        import re
        m = re.search(r"\{.*\}", resp.text, re.S)
        if m:
            return json.loads(m.group(0))
        return {"passed": None, "raw": resp.text[:300]}
    except Exception as e:  # noqa: BLE001
        return {"passed": None, "reason": str(e)[:200]}


def main():
    ap = argparse.ArgumentParser(description="FLUX.1 thumbnail + packaging check")
    ap.add_argument("video", help="path to the final _mixed.mp4")
    ap.add_argument("--title", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    video = Path(args.video)
    if not video.exists():
        sys.exit(f"ERROR: video not found: {video}")
    report, run_dir = _load_report(str(video))
    topic = report.get("topic", video.stem.replace("_", " "))
    title = args.title or report.get("title", topic)

    out = Path(args.out) if args.out else run_dir / "thumbnail.png"
    os.makedirs(out.parent, exist_ok=True)

    prompt = (
        f"Ultra-detailed YouTube thumbnail for a space documentary, 16:9. "
        f"Topic: {topic}. High contrast, cinematic lighting, vivid colors, "
        f"single strong subject centered, dramatic composition, NO text, "
        f"consistent warm-amber color palette."
    )
    ok = _gen_thumbnail(prompt, str(out))
    review = {"passed": None}
    if ok:
        review = _packaging_review(title, str(out), topic)
        review_path = run_dir / "thumbnail_review.json"
        review_path.write_text(json.dumps(review, indent=2))
        print(f"  [thumb] review: {json.dumps(review)[:200]}")
    print(f"THUMBNAIL: {'OK ' + str(out) if ok else 'FAILED (non-fatal)'}")
    print(f"PACKAGING: {review.get('verdict', review.get('reason', 'n/a'))}")


if __name__ == "__main__":
    main()
