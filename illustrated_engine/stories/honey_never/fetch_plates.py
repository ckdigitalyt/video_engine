"""Fetch + validate plates for honey_never (proto7).

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
bible = B.load_bible(str(ROOT / 'stories/honey_never'))
vp = json.loads((ROOT / 'stories/honey_never/visual_plan.json').read_text())
contracts = {s['asset']: s['subject_contract']
             for b in vp['beats'] for s in b['shots']
             if s.get('subject_contract')}

STYLE = ('vintage 1950s natural-history illustration, gouache and ink '
         'linework, warm amber and rust palette, soft directional light, '
         'matte finish')
PLATES = [
 ('B1_honey_hero',
  'extreme close-up of thick golden honey pouring in slow heavy ribbons, glossy amber liquid catching warm light, deep dark background',
  (5, 11, 21, 31)),
 ('B2_honey_rot',
  'split composition, left half a rotting peach with grey mould on a wooden table, right half a glass jar of glowing golden honey untouched, dramatic side light',
  (7, 17, 29)),
 ('B3_honey_osmosis',
  'vintage scientific diagram on parchment, one small round bacterium cell at the centre of a dense golden amber field, thin ink arrows pointing outward from the cell, engraving linework',
  (3, 9, 13)),
 ('B4_honey_hive',
  'worker honeybees crawling on a honeycomb frame, some fanning their wings, hexagonal wax cells filled with honey, warm golden light',
  (11, 19, 37)),
 ('B5_honey_cells',
  'extreme macro of hexagonal honeycomb cells, some capped with pale white beeswax, glistening liquid honey inside, shallow depth of field',
  (7, 23, 41)),
 ('B7_honey_tomb',
  'an ancient clay amphora glowing amber in a dark stone egyptian tomb, warm torchlight, dust motes in the air, hieroglyph shadows on the walls',
  (11, 29, 43)),
]
suffix = bible.get('prompt_fragments', {}).get('suffix', '')
cand = Path('/home/ubuntu/.openclaw/workspace/media/plates/honey_candidates')
cand.mkdir(parents=True, exist_ok=True)


def fetch(name, seed, url):
    tmp = cand / f'{name}_{seed}.jpg'
    for attempt in range(3):
        os.system(f'curl -s -o {tmp} -w "%{{http_code}}" "{url}" '
                  f'--max-time 150 > /tmp/honey_rc.txt')
        code = open('/tmp/honey_rc.txt').read().strip()
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

(ROOT / 'build' / 'plate_report_honey.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
