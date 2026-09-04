"""Fetch + validate plates for round_window (proto6), round 2.

Illustrated style matching the series bible (§10: one visual team).
Per plate: curl Pollinations flux -> vision subject check against the
shot's semantic contract (V5 §8/§9, Gemini fallback) -> §10 finish
acceptance (keep finished plate only if continuity doesn't drop).
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
contracts = {s['asset']: s['subject_contract']
             for b in vp['beats'] for s in b['shots']
             if s.get('subject_contract')}

STYLE = ('vintage 1950s aviation illustration, gouache and ink linework, '
         'muted deep-navy and rust palette, soft directional light, '
         'matte finish')
PLATES = [
 ('B1_round_window',
  'interior of a jet airplane cabin at dusk, one single large round passenger window dominating the frame, glowing orange sunset sky and a dark wing seen only through that window, soft warm cabin light',
  (11, 41, 23)),
 ('B2_comet_jet',
  'a gleaming early 1950s silver jet airliner in flight against a clear blue sky, four engines buried in the wing roots, polished aluminum fuselage, seen slightly from below',
  (41, 53, 67)),
 ('B3_crack_skin',
  'close-up of riveted aluminum aircraft fuselage skin, a thin fatigue crack radiating from the corner of a small rectangular cutout, dramatic raking light',
  (11, 37, 23)),
 ('B4_payoff_window',
  'view through one round airplane window at high altitude at dawn, an aircraft wing silhouette below, warm sunrise gradient sky, serene and calm',
  (11, 23, 37)),
]
suffix = bible.get('prompt_fragments', {}).get('suffix', '')
cand = Path('/home/ubuntu/.openclaw/workspace/media/plates/rw2_candidates')
cand.mkdir(parents=True, exist_ok=True)


def fetch(name, seed, url):
    tmp = cand / f'{name}_{seed}.jpg'
    for attempt in range(3):
        os.system(f'curl -s -o {tmp} -w "%{{http_code}}" "{url}" '
                  f'--max-time 150 > /tmp/rw_rc.txt')
        code = open('/tmp/rw_rc.txt').read().strip()
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

(ROOT / 'build' / 'plate_report_rw2.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
