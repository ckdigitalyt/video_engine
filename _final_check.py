# Final check script - writes plain text to a file
import os, json, time, subprocess, sys

def check():
    out = []
    # Process
    procs = subprocess.run(['pgrep', '-f', 'orchestrator'], capture_output=True, text=True)
    out.append('orch_running=' + ('yes' if procs.returncode == 0 else 'no'))
    
    # Output file
    for f in ['final_output.mp4', 'timeline.json']:
        if os.path.exists(f):
            sz = os.path.getsize(f)
            out.append(f'{f}_size={sz}')
        else:
            out.append(f'{f}_size=0')
    
    # Timeline
    if os.path.exists('timeline.json'):
        with open('timeline.json') as f:
            tl = json.load(f)
        out.append('timeline_scenes=' + str(len(tl['audio_timeline'])))
        dur = max(e['end_time'] for e in tl['audio_timeline']) if tl['audio_timeline'] else 0
        out.append('timeline_duration=' + f'{dur:.1f}')
    
    out.append('ts=' + str(int(time.time())))
    return '\n'.join(out)

result = check()
with open('/tmp/pipeline_final.txt', 'w') as f:
    f.write(result)
print(result)
