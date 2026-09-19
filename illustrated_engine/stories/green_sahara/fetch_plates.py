"""Fetch + validate plates for green_sahara (proto8).

Illustrated style matching the series bible (§10: one visual team).
Per plate: curl Pollinations flux -> vision subject check against the
shot's semantic contract (V5 §8/§9, degrades to UNVERIFIED when vision
providers are down) -> §10 finish acceptance (keep finished plate only
if continuity doesn't drop).
"""
import sys, os, time, json, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PIL import Image
from engine import bible as B, director, finish
from engine.style_continuity import style_continuity_score

ROOT = Path(__file__).resolve().parents[2]
bible = B.load_bible(str(ROOT / 'stories/green_sahara'))
vp = json.loads((ROOT / 'stories/green_sahara/visual_plan.json').read_text())
contracts = {s['asset']: s['subject_contract']
             for b in vp['beats'] for s in b['shots']
             if s.get('subject_contract')}

STYLE = ('vintage 1950s natural-history and geological survey '
         'illustration, gouache and ink linework, sage-green and ochre '
         'palette, soft directional light, matte finish')
PLATES = [
 ('B1_sahara_lake',
  'a vast green savannah with a wide calm lake at dawn, hippopotamuses at the waterline, acacia trees, golden mist over the water',
  (5, 11, 23, 41)),
 ('B2_sahara_rockart',
  'ancient prehistoric rock art painted on a sandstone cliff face, ochre-red giraffes and human figures in neolithic style, desert landscape below',
  (7, 17, 31)),
 ('B3_sahara_split',
  'split composition, left half a lush green wetland with water reeds and grass, right half the same land bone-dry with cracked clay and sand dunes',
  (5, 13, 29)),
 ('B4_sahara_orbit',
  'vintage scientific diagram on parchment, planet earth with a tilted axis line and small wobble arrows, a long curved wind arrow sweeping north across north africa, engraving linework',
  (3, 11, 19)),
 ('B5_sahara_dry',
  'a vast cracked dry lakebed, pale clay cracks stretching to distant sand dunes, empty hazy sky, no water',
  (11, 21, 37)),
 ('B7_sahara_dust',
  'satellite view high above the atlantic ocean, a vast orange dust plume drifting from the african coast toward south america, deep blue ocean, thin cloud streaks',
  (7, 19, 33)),
]
suffix = bible.get('prompt_fragments', {}).get('suffix', '')
cand = Path('/home/ubuntu/.openclaw/workspace/media/plates/sahara_candidates')
cand.mkdir(parents=True, exist_ok=True)


def fetch(name, seed, url):
    tmp = cand / f'{name}_{seed}.jpg'
    for attempt in range(3):
        os.system(f'curl -s -o {tmp} -w "%{{http_code}}" "{url}" '
                  f'--max-time 150 > /tmp/sahara_rc.txt')
        code = open('/tmp/sahara_rc.txt').read().strip()
        try:
            if code == '200' and tmp.exists() and tmp.stat().st_size > 10000:
                return Image.open(tmp).convert('RGB')
        except Exception:
            pass
        print(name, seed, 'retry', attempt, 'http', code, flush=True)
        time.sleep(6)
    return None


report = {}
for name, core, seeds in PLATES:
    prompt = f'{STYLE}, {core}, vertical 9:16 composition, {suffix}'
    q = urllib.parse.quote(prompt)
    best = None
    for seed in seeds:
        url = (f'https://image.pollinations.ai/prompt/{q}'
               f'?width=1024&height=1280&seed={seed}&model=flux&nologo=true')
        img = fetch(name, seed, url)
        if img is None:
            continue
        p = cand / f'{name}_s{seed}.png'
        img.save(p)
        sc = round(float(style_continuity_score(img, bible)), 3)
        chk = director.subject_check(p, contracts.get(name) or {})
        print(name, seed, 'subject:', chk.get('verdict'),
              '| cont:', sc, '|', str(chk.get('depicted'))[:90], flush=True)
        cand_pick = (seed, sc, chk)
        if best is None:
            best = cand_pick
        if chk.get('verdict') == 'PASS':
            best = cand_pick
            break
    if not best:
        report[name] = {'status': 'FETCH_FAIL'}
        continue
    seed, sc, chk = best
    src = cand / f'{name}_s{seed}.png'
    fin = finish.finish_if_better(
        src, src.with_name(f'{name}_fin.png'),
        lambda p: style_continuity_score(Image.open(p), bible))
    keep = Path(fin['out'])
    (ROOT / 'assets' / f'{name}.png').write_bytes(keep.read_bytes())
    (ROOT / 'assets' / f'{name}.orig.png').write_bytes(src.read_bytes())
    report[name] = {'seed': seed, 'continuity': sc,
                    'subject': chk.get('verdict'), 'finish': fin['kept'],
                    'depicted': str(chk.get('depicted'))[:140]}
    print(name, '->', report[name], flush=True)

(ROOT / 'build' / 'plate_report_sahara.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
