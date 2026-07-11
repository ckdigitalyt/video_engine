#!/usr/bin/env python3
"""Robustly fix the scene_purpose limit in schemas.py."""

path = '/home/ubuntu/video_engine/src/models/schemas.py'

with open(path, 'r') as f:
    content = f.read()

# Target block
old_block = '''    scene_purpose: str = Field(
        default="general",
        description="Scene purpose (introduction, explanation, conclusion, etc.).",
        max_length=50,
    )'''

new_block = '''    scene_purpose: str = Field(
        default="general",
        description="Scene purpose (introduction, explanation, conclusion, etc.).",
        max_length=200,
    )'''

assert old_block in content, "Old block not found!"

content = content.replace(old_block, new_block)

with open(path, 'w') as f:
    f.write(content)

print("PATCHED: scene_purpose max_length 50 -> 200")
