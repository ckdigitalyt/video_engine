import os, json

checks = {}

# Check if orchestrator is running
try:
    pids = os.popen('pgrep -f "python.*orchestrator"').read().strip()
    checks['orch_running'] = len(pids) > 0
except:
    checks['orch_running'] = False

# Check output file
if os.path.exists('final_output.mp4'):
    checks['mp4_size'] = os.path.getsize('final_output.mp4')
else:
    checks['mp4_size'] = 0

# Check timeline
if os.path.exists('timeline.json'):
    with open('timeline.json') as f:
        tl = json.load(f)
    checks['timeline_scenes'] = len(tl['audio_timeline'])
    if tl['audio_timeline']:
        checks['timeline_dur'] = max(e['end_time'] for e in tl['audio_timeline'])
    else:
        checks['timeline_dur'] = 0
else:
    checks['timeline_scenes'] = 0
    checks['timeline_dur'] = 0

with open('/tmp/final_status.json', 'w') as f:
    json.dump(checks, f, indent=2)
