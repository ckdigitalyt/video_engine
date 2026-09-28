"""Phase 2: objective TTS quality proxies per candidate (whisper round-trip WER,
words/min, pause structure, F0 spread, clipping). Usage: phase2_venv python tts_measure.py"""
import json, re, subprocess, wave, glob
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
S = json.loads(Path("/home/ubuntu/phase2_out/stories/blackhole_clocks/story.json").read_text())
LINES = [b["narration"] for b in S["beats"][:5]]
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
m = WhisperModel("small.en", device="cpu", compute_type="int8", cpu_threads=4)
def load(p):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True)
    return np.frombuffer(r.stdout, np.float32)
def f0_spread(x, sr=16000):  # autocorrelation pitch on voiced 40 ms frames -> semitone IQR
    f, hop, out = 640, 320, []
    for i in range(0, len(x) - f, hop):
        fr = x[i:i + f] - x[i:i + f].mean()
        if np.sqrt((fr ** 2).mean()) < 0.02: continue
        ac = np.correlate(fr, fr, "full")[f - 1:]
        lo, hi = sr // 400, sr // 60
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.3 * ac[0]: out.append(sr / k)
    if len(out) < 10: return None, None
    st = 12 * np.log2(np.array(out) / np.median(out))
    return round(float(np.median(out)), 1), round(float(np.percentile(st, 75) - np.percentile(st, 25)), 2)
cands = {}
for p in sorted(glob.glob("/home/ubuntu/phase2_out/tts/*_[1-5].wav")) + sorted(glob.glob("/home/ubuntu/phase2_out/tts/fish_[1-5].wav")):
    tag, i = p.rsplit("_", 1); cands.setdefault(Path(tag).name, []).append((int(i[0]), p))
res = {}
for tag, files in cands.items():
    E = W = 0; dur = 0; pauses = []; f0s = []; spreads = []; peak = 0; hyps = []
    for i, p in sorted(files):
        x = load(p); dur += len(x) / 16000; peak = max(peak, float(np.abs(x).max()))
        segs, _ = m.transcribe(p, language="en", beam_size=1, word_timestamps=True)
        ws = [w for s in segs for w in s.words]; hyp = [norm(w.word) for w in ws]; tgt = [norm(t) for t in LINES[i - 1].split()]
        d = list(range(len(hyp) + 1))
        for a, r in enumerate(tgt, 1):
            pv, d[0] = d[0], a
            for b, h in enumerate(hyp, 1):
                pv, d[b] = d[b], min(d[b] + 1, d[b - 1] + 1, pv + (r != h))
        E += d[-1]; W += len(tgt); hyps.append(" ".join(w.word.strip() for w in ws))
        pauses += [ws[k + 1].start - ws[k].end for k in range(len(ws) - 1)]
        f0, sp = f0_spread(x); f0s.append(f0); spreads.append(sp)
    pz = [q for q in pauses if q > 0.25]
    res[tag] = {"wer": round(E / W, 3), "wpm": round(W / dur * 60), "pauses_gt250ms": len(pz),
                "max_pause_s": round(max(pauses), 2) if pauses else None, "peak": round(peak, 3),
                "f0_median_hz": np.median([f for f in f0s if f]).round(1) if any(f0s) else None,
                "pitch_iqr_semitones": round(float(np.median([s for s in spreads if s])), 2) if any(spreads) else None,
                "hyp": hyps}
    print(tag, json.dumps({k: (float(v) if isinstance(v, np.floating) else v) for k, v in res[tag].items() if k != "hyp"}))
Path("/home/ubuntu/phase2_out/tts/measure.json").write_text(json.dumps(res, indent=1, default=float))
