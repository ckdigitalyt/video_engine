#!/usr/bin/env python3
"""Fix scene_purpose max_length in schemas.py."""

path = '/home/ubuntu/video_engine/src/models/schemas.py'
with open(path) as f:
    c = f.read()

old = 'scene_purpose: str = Field(\n        default="general",\n        description="Scene purpose (introduction, explanation, conclusion, etc.).",\n        max_length=50,\n    )'
new = 'scene_purpose: str = Field(\n        default="general",\n        description="Scene purpose (introduction, explanation, conclusion, etc.).",\n        max_length=200,\n    )'

assert old in c, "Block not in file!"
c = c.replace(old, new)
with open(path, 'w') as f:
    f.write(c)
print('OK')
