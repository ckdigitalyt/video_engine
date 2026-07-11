#!/usr/bin/env python3
"""Fix scene_purpose limit and then re-run the pipeline."""

import os
import sys

# Step 1: Fix the planner.py truncation
planner_path = os.path.join(os.path.dirname(__file__), 'src', 'planner', 'planner.py')

with open(planner_path, 'r') as f:
    content = f.read()

# Fix: ensure scene_purpose is always truncated to 50 chars
old = 'scene_purpose=(visual_intent.visual_objective or "general")[:50]'
new = 'scene_purpose=(visual_intent.visual_objective or "general")[:50]'

# More robust fix: find and wrap in explicit truncation
import re
pattern = r"scene_purpose=visual_intent\.visual_objective\[:50\] if visual_intent\.visual_objective else \"general\""
replacement = 'scene_purpose=(visual_intent.visual_objective or "general")[:50]'
content = re.sub(pattern, replacement, content)

# Also catch the old non-truncated version
content = content.replace(
    'scene_purpose=visual_intent.visual_objective or "general"',
    'scene_purpose=(visual_intent.visual_objective or "general")[:50]'
)

with open(planner_path, 'w') as f:
    f.write(content)

print("[FIX] planner.py patched")

# Step 2: Fix schemas.py to increase max_length from 50 to 200
schemas_path = os.path.join(os.path.dirname(__file__), 'src', 'models', 'schemas.py')
with open(schemas_path, 'r') as f:
    schemas_content = f.read()

# Increase scene_purpose max_length from 50 to 200
schemas_content = schemas_content.replace(
    'scene_purpose: str = Field(default="", max_length=50',
    'scene_purpose: str = Field(default="", max_length=200'
)

with open(schemas_path, 'w') as f:
    f.write(schemas_content)

print("[FIX] schemas.py scene_purpose max_length extended to 200")

# Step 3: Verify the fixes compile
sys.path.insert(0, os.path.dirname(__file__))
from src.models.schemas import VisualIntent, SearchPlan

# Test with a long objective
vi = VisualIntent(visual_objective="Show a side-by-side comparison of dark sky preserve vs heavily light-polluted city to illustrate light scattering and atmospheric effects on starlight visibility")
print(f"[VERIFY] Long visual_objective: {len(vi.visual_objective)} chars")

sp = SearchPlan(
    asset_search_queries=['test'],
    primary_topic='Space',
    scene_purpose=vi.visual_objective
)
print(f"[VERIFY] SearchPlan accepts long scene_purpose: {len(sp.scene_purpose)} chars")

# Verify round-trip
data = sp.model_dump(mode='json')
restored = SearchPlan(**data)
print(f"[VERIFY] Round-trip OK, purpose={len(restored.scene_purpose)} chars")

print("\n[READY] All fixes verified. Pipeline ready.")
