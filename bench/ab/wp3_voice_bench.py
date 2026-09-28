"""WP3 voice measurements (local Kokoro + faster-whisper, no network).

  venv/bin/python bench/ab/wp3_voice_bench.py shortlist   # WER/F0/RTF per candidate voice
  venv/bin/python bench/ab/wp3_voice_bench.py samples V1 V2 V3   # owner sample set, 1.0x and 1.1x, -14 LUFS
  venv/bin/python bench/ab/wp3_voice_bench.py accept      # topic-1 acceptance: WER + caption timing

Output goes to ~/phase4_out/wp3/. The script is the 73-word Phase 3 birds/dinosaurs
script (the topic-1 pack has claims only; WP4 writes real scripts)."""
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "illustrated_engine"))
from engine import voice as V  # noqa: E402
from engine.voice import align  # noqa: E402

OUT = Path.home() / "phase4_out" / "wp3"
SCRIPT = (Path.home() / "phase3_out/voice/script.txt").read_text().strip()
CANDIDATES = ["am_michael", "am_fenrir", "am_puck", "am_onyx", "am_adam",
              "bm_george", "bm_fable", "bm_daniel", "bm_lewis"]


def _cfg(voice: str, speed: float = 1.0) -> dict:
    cfg = V.load_config()
    cfg["voices"]["kokoro_michael"] = dict(cfg["voices"]["kokoro_michael"],
                                           voice=voice, speed=speed)
    return cfg


def _sentences() -> list:
    ss = V.split_sentences(SCRIPT)
    return [V.Sentence(s, "hook" if i == 0 else "payoff" if i == len(ss) - 1
                       else "normal") for i, s in enumerate(ss)]


def f0_median(wav: Path) -> float:
    import wave
    with wave.open(str(wav)) as w:
        sr = w.getframerate()
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2") / 32768.0
    n, hop, vals = int(sr * 0.04), int(sr * 0.02), []
    lo, hi = int(sr / 300), int(sr / 60)
    for i in range(0, len(x) - n, hop):
        f = x[i:i + n] - x[i:i + n].mean()
        if np.sqrt((f ** 2).mean()) < 0.02:
            continue
        ac = np.correlate(f, f, "full")[n - 1:]
        k = lo + int(np.argmax(ac[lo:hi]))
        if ac[k] > 0.5 * ac[0]:
            vals.append(sr / k)
    return float(np.median(vals)) if vals else 0.0


def synth(voice: str, speed: float, path: Path) -> "V.VoiceResult":
    return V.synthesize(_sentences(), _cfg(voice, speed), path)


def loudnorm(src: Path, dst: Path, target: float = -14.0) -> dict:
    """Static gain to -14 LUFS + sample limiter (same method as Phase 3)."""
    def measure(p):
        err = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(p), "-af",
                              "ebur128=peak=true", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
        s = err[err.rfind("Summary:"):]
        return (float(re.search(r"I:\s+(-?[\d.]+) LUFS", s).group(1)),
                float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", s).group(1)))
    gain = target - measure(src)[0]
    for _ in range(4):
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-af",
                        f"aresample=48000,volume={gain:.2f}dB,alimiter=limit=0.76:level=false:attack=2:release=60",
                        "-ac", "1", str(dst)], check=True)
        i, tp = measure(dst)
        if abs(i - target) <= 0.2:
            break
        gain += target - i
    return {"lufs": i, "true_peak_dbfs": tp}


def q90(a):
    return {k: round(float(np.quantile(a, q)), 3) for k, q in
            (("p50", .5), ("p90", .9), ("max", 1.0))}


def shortlist():
    rows = []
    for v in CANDIDATES:
        r = synth(v, 1.0, OUT / "tmp" / f"{v}.wav")
        rows.append({"voice": v, "dur_s": r.duration, "rtf": r.rtf, "wer": r.qa["wer"],
                     "hard_missed": r.qa["hard_missed"], "verdict": r.qa["verdict"],
                     "f0_median_hz": round(f0_median(r.wav), 1)})
        print(rows[-1], flush=True)
    (OUT / "shortlist.json").write_text(json.dumps(rows, indent=1))


def samples(voices: list):
    (OUT / "samples").mkdir(parents=True, exist_ok=True)
    rows = []
    for v in voices:
        for sp in (1.0, 1.1):
            raw = OUT / "tmp" / f"{v}_{sp}x_raw.wav"
            r = synth(v, sp, raw)
            n = loudnorm(raw, OUT / "samples" / f"{v}_{sp:.1f}x.wav")
            rows.append({"voice": v, "speed": sp, "dur_s": r.duration, "wer": r.qa["wer"],
                         "wpm": round(len(SCRIPT.split()) / r.duration * 60), **n,
                         "f0_median_hz": round(f0_median(raw), 1),
                         "verdict": r.qa["verdict"], "heard_diff": r.qa["hard_missed"]})
            print(rows[-1], flush=True)
    (OUT / "samples.json").write_text(json.dumps(rows, indent=1))


def accept():
    r = synth("am_michael", 1.0, OUT / "tmp" / "topic1.wav")
    words = r.words
    # (a) truth: each sentence starts where the synthesis put it (the clamp to sentence spans makes this partly circular; (b) is the independent check)
    sents = _sentences()
    errs, i = [], 0
    for (t0, t1), s in zip(r.sentence_spans, sents):
        n = len(s.text.split())
        errs.append(abs(words[i]["t0"] - (t0 + 0.02)))  # word ENDS excluded: the truth end includes the fade
        i += n
    # (b) base.en timings vs small.en word starts (independent estimator, Phase 2 method)
    small = align.timing_from_asr(SCRIPT, align.transcribe(r.wav, "small.en"), r.wav)["words"]
    diff = [abs(a["t0"] - b["t0"]) for a, b in zip(words, small)]
    old = _old_silence(r.wav)
    res = {"wer": r.qa["wer"], "verdict": r.qa["verdict"], "hard_missed": r.qa["hard_missed"],
           "duration_s": r.duration, "first_word_t0": words[0]["t0"],
           "sentence_onset_err_s": q90(errs), "n_anchors": len(errs),
           "base_vs_small_word_start_s": q90(diff),
           "silence_v1_vs_small_word_start_s": q90([abs(a["t0"] - b["t0"]) for a, b in zip(old, small)]),
           "method": r.timing["method"]}
    (OUT / "accept_topic1.json").write_text(json.dumps(res, indent=1))
    print(json.dumps(res, indent=1))


def _old_silence(wav: Path) -> list:
    from engine.v15_timing import align as silence_align
    return silence_align(wav, SCRIPT)["words"]


if __name__ == "__main__":
    (OUT / "tmp").mkdir(parents=True, exist_ok=True)
    mode = sys.argv[1]
    {"shortlist": shortlist, "accept": accept}.get(mode, lambda: samples(sys.argv[2:]))()
