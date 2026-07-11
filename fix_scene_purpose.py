import sys

with open('/home/ubuntu/video_engine/src/planner/planner.py', 'r') as f:
    content = f.read()

old = 'scene_purpose=visual_intent.visual_objective or "general"'
new = 'scene_purpose=(visual_intent.visual_objective or "general")[:50]'

if old in content:
    content = content.replace(old, new)
    with open('/home/ubuntu/video_engine/src/planner/planner.py', 'w') as f:
        f.write(content)
    print('PATCHED OK')
    sys.exit(0)
else:
    print('OLD STRING NOT FOUND')
    # Debug: find what's there
    idx = content.find('scene_purpose')
    if idx >= 0:
        print(f'Found scene_purpose at {idx}')
        print(repr(content[idx:idx+100]))
    sys.exit(1)
