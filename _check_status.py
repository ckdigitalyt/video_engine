#!/usr/bin/env python3
"""Check pipeline status and write results to a text file."""
import os, json, subprocess

out = []

# Process check
proc = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
out.append(f'orchestrator running: {"orchestrator.py" in proc.stdout}')

# Output file check
for f in ['final_output.mp4', 'timeline.json']:
    if os.path.exists(f):
        sz = os.path.getsize(f)
        out.append(f'{f}: {sz:,} bytes')
    else:
        out.append(f'{f}: NOT FOUND')

# Timeline contents
if os.path.exists('timeline.json'):
    with open('timeline.json') as f:
        data = json.load(f)
    scenes = len(data['audio_timeline'])
    dur = max(e['end_time'] for e in data['audio_timeline'])
    out.append(f'timeline: {scenes} scenes, {dur:.1f}s total')

print('\n'.join(out))
