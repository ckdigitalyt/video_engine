#!/usr/bin/env python3
"""
ai_image_worker.py — Worker script for parallel AI image generation.

Spawns one AI still generation (NVIDIA NIM primary, Pollinations
fallback) and writes the image to a path.  v33: fixed the broken
``generate_image()`` call (no such method) — the provider interface is
``generate(prompt, output_path, width, height, seed)``.

Usage:
    python ai_image_worker.py --prompt "Photorealistic documentary image of the Voyager 1 spacecraft..." --output /path/to/output.png

Environment:
    - Uses NVIDIA NIM provider as primary, Pollinations as fallback.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from dotenv import load_dotenv
load_dotenv()

from src.providers.image_gen import NvidiaNimProvider, PollinationsProvider


def main():
    parser = argparse.ArgumentParser(description="AI Image Generation Worker")
    parser.add_argument("--prompt", type=str, required=True, help="Prompt for image generation")
    parser.add_argument("--output", type=str, required=True, help="Output file path (.png)")
    args = parser.parse_args()

    # Initialize providers
    primary = NvidiaNimProvider()
    fallback = PollinationsProvider()

    img_path = args.output
    os.makedirs(os.path.dirname(img_path), exist_ok=True)

    # Try primary provider first (v33: ``generate`` writes the file itself
    # and returns the path — the old code called a nonexistent
    # ``generate_image()`` and would AttributeError on first spawn).
    if primary.is_available():
        try:
            got = primary.generate(args.prompt, img_path, width=2560, height=1440)
            if got and os.path.exists(got):
                print("Image generated successfully via NVIDIA NIM")
                return 0
            raise RuntimeError("primary returned no file")
        except Exception as e:
            print(f"Primary provider failed: {e}")

    # Fallback to Pollinations
    if fallback.is_available():
        try:
            got = fallback.generate(args.prompt, img_path, width=2560, height=1440)
            if got and os.path.exists(got):
                print("Image generated successfully via Pollinations")
                return 0
            raise RuntimeError("fallback returned no file")
        except Exception as e:
            print(f"Fallback provider failed: {e}")

    print("Image generation failed on all providers")
    return 1


if __name__ == "__main__":
    sys.exit(main())
