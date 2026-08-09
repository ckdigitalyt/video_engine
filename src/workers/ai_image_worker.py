#!/usr/bin/env python3
"""
ai_image_worker.py — Worker script for parallel AI image generation.

This script is spawned by mission_run.py via sessions_spawn to generate
an AI still image for a specific prompt and save it to a specified path.

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

    # Try primary provider first
    if primary.is_available():
        try:
            img_data = primary.generate_image(args.prompt)
            with open(img_path, "wb") as f:
                f.write(img_data)
            print("Image generated successfully via NVIDIA NIM")
            return 0
        except Exception as e:
            print(f"Primary provider failed: {e}")

    # Fallback to Pollinations
    if fallback.is_available():
        try:
            img_data = fallback.generate_image(args.prompt)
            with open(img_path, "wb") as f:
                f.write(img_data)
            print("Image generated successfully via Pollinations")
            return 0
        except Exception as e:
            print(f"Fallback provider failed: {e}")

    print("Image generation failed on all providers")
    return 1


if __name__ == "__main__":
    sys.exit(main())
