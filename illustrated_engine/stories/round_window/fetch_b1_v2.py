"""Re-fetch B1 hero plate (round 4): single dominant window.

Round-2 accepted plate shows TWO windows dominating the hook -> vision
subject FAIL on the rendered frame (qa4 proto6). This fetch uses a
close-up prompt where only one window can appear, requires a PASS
verdict before installing, and keeps continuity + finish acceptance.
"""
import sys, os, time, json, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image
from engine import bible as B, director, finish
from engine.style_continuity import style_continuity_score

ROOT = Path(__file__).resolve().parents[2]
bible = B.load_bible(str(ROOT / 'stories/round_window'))
vp = json.loads((ROOT / 'stories/round_window/visual_plan.json').read_text())
contract = {}
for b in vp['beats']:
    for s in b['shots']:
        if s.get('asset') == 'B1_round_window' and s.get('subject_contract'):
            contract = s['subject_contract']

STYLE = ('vintage 1950s aviation illustration, gouache and ink linework, '
         'muted deep-navy and rust palette, soft directional light, '
         'matte finish')
CORE = ('inside a dark airplane cabin at dusk, extreme close-up of a single '
        'large round passenger window filling the frame, glowing orange dusk '
        'sky and a dark wing seen only through that window, plain dark cabin '
        'wall surrounding it, no other windows visible')
suffix = bible.get('prompt_fragments', {}).get('suffix', '')
cand = Path('/home/ubuntu/.openclaw/workspace/media/plates/rw4_candidates')
cand.mkdir(parents=True, exist_ok=True)
SEEDS = (3, 17, 57, 71, 91)


def fetch(seed, url):
    tmp = cand / f'B1_round_window_{seed}.jpg'
    for attempt in range(3):
        os.system(f'curl -s -o {tmp} -w "%{{http_code}}" "{url}" '
                  f'--max-time 150 > /tmp/rw4_rc.txt')
        code = open('/tmp/rw4_rc.txt').read().strip()
        try:
            if code == '200' and tmp.exists() and tmp.stat().st_size > 10000:
                return Image.open(tmp).convert('RGB')
        except Exception:
            pass
        print('B1', seed, 'retry', attempt, 'http', code, flush=True)
        time.sleep(6)
    return None


prompt = f'{STYLE}, {CORE}, vertical 9:16 composition, {suffix}'
q = urllib.parse.quote(prompt)
results = []
for seed in SEEDS:
    url = (f'https://image.pollinations.ai/prompt/{q}'
           f'?width=1024&height=1280&seed={seed}&model=flux&nologo=true')
    img = fetch(seed, url)
    if img is None:
        continue
    p = cand / f'B1_round_window_s{seed}.png'
    img.save(p)
    sc = round(float(style_continuity_score(img, bible)), 3)
    chk = director.subject_check(p, contract)
    print('B1', seed, 'subject:', chk.get('verdict'), '| cont:', sc,
          '|', str(chk.get('depicted'))[:90], flush=True)
    results.append((seed, sc, chk))
    if chk.get('verdict') == 'PASS':
        break

passing = [r for r in results if r[2].get('verdict') == 'PASS']
if not passing:
    print('ALL_FAIL', json.dumps(
        [{'seed': s, 'cont': c, 'depicted': str(k.get('depicted'))[:100]}
         for s, c, k in results]), flush=True)
    raise SystemExit(1)

seed, sc, chk = max(passing, key=lambda r: r[1])
src = cand / f'B1_round_window_s{seed}.png'
fin = finish.finish_if_better(
    src, src.with_name('B1_round_window_fin.png'),
    lambda p: style_continuity_score(Image.open(p), bible))
keep = Path(fin['out'])
(ROOT / 'assets' / 'B1_round_window.png').write_bytes(keep.read_bytes())
(ROOT / 'assets' / 'B1_round_window.orig.png').write_bytes(src.read_bytes())
report = {'seed': seed, 'continuity': sc, 'subject': chk.get('verdict'),
          'finish': fin['kept'], 'depicted': str(chk.get('depicted'))[:140]}
(ROOT / 'build' / 'plate_report_rw4_b1.json').write_text(
    json.dumps(report, indent=2))
print(json.dumps(report, indent=2), flush=True)
