"""Phase 2: faster-whisper word timestamps vs V15 silence-anchored timing.
Usage: phase2_venv/bin/python align_bench.py <model> [threads]"""
import json, re, sys, time, resource
from pathlib import Path
from faster_whisper import WhisperModel
A = Path("/home/ubuntu/phase2_out/stories/blackhole_clocks/audio")
S = json.loads((A.parent / "story.json").read_text())
norm = lambda w: re.sub(r"[^a-z0-9]", "", w.lower())
name = sys.argv[1]; th = int(sys.argv[2]) if len(sys.argv) > 2 else 4
t = time.time(); m = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=th); load = time.time() - t
tot_wall = tot_audio = 0; diffs = []; errs = words = 0; rows = []
for b in S["beats"]:
    wav = A / f"beat_{b['beat_id']}.wav"
    ref = json.loads((A / f"beat_{b['beat_id']}.timing.json").read_text())
    t = time.time()
    segs, info = m.transcribe(str(wav), language="en", word_timestamps=True, beam_size=1,
                              initial_prompt=None, vad_filter=False)
    ws = [w for s in segs for w in s.words]
    el = time.time() - t; tot_wall += el; tot_audio += info.duration
    hyp = [norm(w.word) for w in ws]; tgt = [norm(x) for x in b["narration"].split()]
    # word error proxy: Levenshtein on normalized tokens
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(tgt, 1):
        p, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            p, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, p + (r != h))
    errs += d[-1]; words += len(tgt)
    # timing agreement where tokens match in order
    rw = ref.get("words") or []
    j = 0
    for w in ws:
        k = norm(w.word)
        while j < len(rw) and norm(rw[j].get("w", rw[j].get("word", ""))) != k: j += 1
        if j < len(rw):
            diffs.append(abs(w.start - rw[j]["t0"])); j += 1
    rows.append({"beat": b["beat_id"], "hyp": " ".join(w.word.strip() for w in ws)})
diffs.sort()
q = lambda p: round(diffs[int(p * (len(diffs) - 1))], 3) if diffs else None
res = {"model": name, "threads": th, "load_s": round(load, 1), "wall_s": round(tot_wall, 1), "audio_s": round(tot_audio, 1),
       "rtf": round(tot_wall / tot_audio, 3), "wer": round(errs / words, 3), "matched_words": len(diffs),
       "v15_vs_whisper_start_abs_diff_s": {"p50": q(.5), "p90": q(.9), "max": q(1.0)},
       "maxrss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024, "hyp": rows}
Path(f"/home/ubuntu/phase2_out/align_{name}.json").write_text(json.dumps(res, indent=1))
print(json.dumps({k: v for k, v in res.items() if k != "hyp"}))
