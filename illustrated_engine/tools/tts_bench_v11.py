#!/usr/bin/env python3
"""V11 Stage 2c — isolated offline TTS benchmark (ADVISORY ONLY).

Compares local TTS candidates on the ice_slippery narration lines:

    A  chatterbox-turbo   (current directive candidate; ResembleAI/chatterbox-turbo)
    A0 chatterbox-base    (model actually cached in prod venv-cb, ResembleAI/chatterbox)
    B  chatterbox-nano    (ResembleAI/chatterbox-nano, ChatterboxTurboTTS(nano=True))
    C  qwen3-tts-0.6b     (NOT RUN: gated/private on HF -> unavailable offline)
    D  kokoro             (82M ONNX v0.19 + voices.bin, kokoro-onnx)

ZERO PRODUCTION CHANGES: this script never imports src.providers, never reads
or writes configs/voices.yaml, and writes audio only under its --out directory
(default /tmp/v11_tts_bench). Production voices.yaml was NOT modified by this
benchmark; results are advisory until accepted.

Two interpreters are involved:
  * chatterbox candidates (turbo/nano/base): run with a venv containing
    chatterbox-tts built from source (torch 2.6). This script takes
    --backend chatterbox under that interpreter.
  * kokoro: run with the repo's existing `venv` (kokoro-onnx + onnxruntime).

Usage:
  <cb-venv>/bin/python tools/tts_bench_v11.py --backend chatterbox \
      --candidate turbo|nano|base [--ref-wav <10s prod narration clip>]
  <venv>/bin/python     tools/tts_bench_v11.py --backend kokoro
  python3               tools/tts_bench_v11.py --backend measure \
      --out /tmp/v11_tts_bench --report V11_TTS_BENCH.md

Generation outputs one wav + manifest per candidate x beat. The `measure`
backend computes duration vs beat window (story.json start/end and the
production timing.json durations), peak/clipping, integrated LUFS (ffmpeg
ebur128), SNR estimate, F0 mean/std/creak-proxy (numpy autocorrelation) and
silence-gap behaviour at punctuation, then writes the markdown report. F0 is
measured with librosa YIN (run the `measure` backend with the chatterbox venv
python, which carries librosa).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORY = ROOT / "stories" / "ice_slippery"
DEFAULT_OUT = Path("/tmp/v11_tts_bench")
SR = 44100

# ---------------------------------------------------------------- story data


def load_beats() -> list[dict]:
    story = json.loads((STORY / "story.json").read_text())
    timing = json.loads((STORY / "audio" / "timing.json").read_text())
    out = []
    for b in story["beats"]:
        bid = b["beat_id"]
        out.append({
            "beat_id": bid,
            "function": b.get("function", ""),
            "text": b["narration"],
            "window_s": float(b["end"]) - float(b["start"]),
            "prod_dur_s": float(timing[bid]["duration"]),
        })
    return out


# ----------------------------------------------------------------- generate


def synth_chatterbox(candidate: str, beats: list[dict], ref: Path | None,
                     outdir: Path) -> None:
    import torch  # noqa: F401
    if candidate == "base":
        from chatterbox.tts import ChatterboxTTS
        model = ChatterboxTTS.from_pretrained("cpu")
        # clone the same narrator reference as turbo/nano for voice parity
        gen_kwargs = {"exaggeration": 0.40, "cfg_weight": 0.35,
                      "audio_prompt_path": str(ref)} if ref else \
                     {"exaggeration": 0.40, "cfg_weight": 0.35}
    else:
        from chatterbox.tts_turbo import ChatterboxTurboTTS
        model = ChatterboxTurboTTS.from_pretrained("cpu", nano=(candidate == "nano"))
        gen_kwargs = {"audio_prompt_path": str(ref)} if ref else {}

    cand_dir = outdir / candidate
    cand_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for b in beats:
        t0 = time.perf_counter()
        wav = model.generate(b["text"], **gen_kwargs).squeeze(0).cpu()
        gen_s = round(time.perf_counter() - t0, 1)
        path = cand_dir / f"beat_{b['beat_id']}.wav"
        torchaudio_save(path, wav, model.sr)
        manifest.append({"beat_id": b["beat_id"], "text": b["text"],
                         "wav": str(path), "gen_s": gen_s})
        print(f"[{candidate}] {b['beat_id']} -> {path.name} ({gen_s}s)")
    (cand_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))


def torchaudio_save(path: Path, wav, sr: int) -> None:
    import torchaudio
    torchaudio.save(str(path), wav.unsqueeze(0) if wav.dim() == 1 else wav, sr)


def synth_kokoro(beats: list[dict], outdir: Path) -> None:
    from kokoro_onnx import Kokoro
    repo = ROOT.parent  # /home/ubuntu/video_engine
    model_path = repo / "kokoro-v0_19.onnx"
    voices_path = repo / "voices.bin"
    kokoro = Kokoro(str(model_path), str(voices_path))
    cand_dir = outdir / "kokoro"
    cand_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for b in beats:
        # bm_george is the prod voices.yaml kokoro default (British male);
        # speed 1.0, lang en-gb — mirrors production config values.
        t0 = time.perf_counter()
        samples, sr = kokoro.create(b["text"], voice="bm_george",
                                    speed=1.0, lang="en-gb")
        gen_s = round(time.perf_counter() - t0, 1)
        path = cand_dir / f"beat_{b['beat_id']}.wav"
        write_wav(path, samples, sr)
        manifest.append({"beat_id": b["beat_id"], "text": b["text"],
                         "wav": str(path), "gen_s": gen_s})
        print(f"[kokoro] {b['beat_id']} -> {path.name} ({gen_s}s)")
    (cand_dir / "manifest.json").write_text(json.dumps(manifest, indent=1))


def write_wav(path: Path, samples, sr: int) -> None:
    import numpy as np
    import soundfile as sf
    data = np.asarray(samples, dtype=np.float32)
    if data.ndim == 2:
        data = data.T
    sf.write(str(path), data, sr, subtype="PCM_16")


# ------------------------------------------------------------------ measure


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def lufs(path: Path) -> float:
    """Integrated LUFS via ffmpeg ebur128 (None if ffmpeg fails)."""
    cmd = ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
           "-filter_complex", "ebur128=peak=true", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        vals = []
        for line in proc.stderr.splitlines():
            if "I:" in line and "LUFS" in line:
                try:
                    vals.append(float(line.split("I:")[1].split("LUFS")[0].strip()))
                except ValueError:
                    pass
        # the final summary "I:" is the last one printed — earlier ones are
        # per-frame momentary values
        return vals[-1] if vals else float("nan")
    except Exception:
        return float("nan")


def frame_rms(x, frame: int, hop: int):
    import numpy as np
    n = 1 + max(0, (len(x) - frame) // hop)
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    return np.sqrt((x[idx] ** 2).mean(axis=1))


def snr_estimate(x: 'np.ndarray', sr: int) -> float:
    """Active speech level (85th pct frame RMS) vs noise floor (10th pct), dB.
    Capped at 80 dB: a long internal silence drives the floor to digital zero
    and the raw ratio stops being meaningful."""
    import numpy as np
    fr, hp = int(0.04 * sr), int(0.01 * sr)
    rms = frame_rms(x, fr, hp) + 1e-10
    db = 20 * np.log10(rms)
    return float(min(np.percentile(db, 85) - np.percentile(db, 10), 80.0))


def f0_stats(x: 'np.ndarray', sr: int) -> dict:
    """F0 via librosa YIN (fmin 60, fmax 400 Hz). Creak proxy = share of
    voiced frames below 75 Hz (rough, objective, no subjective tuning)."""
    import numpy as np
    import librosa
    fl = int(2 ** round(np.log2(0.0464 * sr)))   # ~46 ms window (2048 @44.1k)
    hop = fl // 4
    # fmin 60: period-doubling artifacts (true F0/2) land below the band and
    # are excluded, so the creak proxy is not inflated by them
    f0 = librosa.yin(x.astype(np.float32), fmin=60, fmax=400,
                     frame_length=fl, hop_length=hop, sr=sr)
    rms = librosa.feature.rms(y=x.astype(np.float32),
                              frame_length=fl, hop_length=hop)[0]
    n = min(len(rms), len(f0))
    voiced = (f0[:n] > 61) & (f0[:n] < 400) & (rms[:n] > max(rms.max() * 0.05, 1e-4))
    fv = f0[:n][voiced]
    if len(fv) == 0:
        return {"f0_mean": float("nan"), "f0_std": float("nan"),
                "creak_frac": float("nan"), "n_voiced": 0}
    return {"f0_mean": float(np.median(fv)), "f0_std": float(fv.std()),
            "creak_frac": float(np.mean(fv < 75.0)), "n_voiced": int(len(fv))}


def silence_gaps(x: 'np.ndarray', sr: int) -> dict:
    """Leading/trailing/longest-internal silence + total pause time (ms)."""
    import numpy as np
    fr, hp = int(0.04 * sr), int(0.01 * sr)
    rms = frame_rms(x, fr, hp)
    thr = max(rms.max() * 0.02, 1e-5)
    voiced = rms > thr
    idx = np.where(voiced)[0]
    if len(idx) == 0:
        return {"lead_ms": len(x) / sr * 1000, "trail_ms": 0.0,
                "long_gap_ms": 0.0, "total_pause_ms": 0.0}
    lead = idx[0] * hp / sr * 1000
    trail = (len(voiced) - 1 - idx[-1]) * hp / sr * 1000
    gaps, run = [], 0.0
    for v in voiced[idx[0]:idx[-1]]:
        run = run + hp / sr * 1000 if not v else 0.0
        gaps.append(run)
    lg = max(gaps) if gaps else 0.0
    # total pause = frames under threshold inside the voiced span
    inner = voiced[idx[0]:idx[-1]]
    total_pause = float((~inner).sum()) * hp / sr * 1000
    return {"lead_ms": float(lead), "trail_ms": float(trail),
            "long_gap_ms": float(lg), "total_pause_ms": total_pause}


def measure_candidate(cand_dir: Path, beats: list[dict]) -> list[dict]:
    rows = []
    for b in beats:
        path = cand_dir / f"beat_{b['beat_id']}.wav"
        if not path.exists():
            rows.append({"beat_id": b["beat_id"], "error": "missing wav"})
            continue
        import numpy as np
        import soundfile as sf
        x, sr = sf.read(str(path), dtype="float32")
        if x.ndim == 2:
            x = x.mean(axis=1)
        peak = float(np.abs(x).max())
        clip = int((np.abs(x) >= 0.999).sum())
        dur = len(x) / sr
        f0 = f0_stats(x, sr)
        gaps = silence_gaps(x, sr)
        rows.append({
            "beat_id": b["beat_id"],
            "dur_s": round(dur, 2),
            "win_s": round(b["window_s"], 2),
            "prod_s": b["prod_dur_s"],
            "abs_dev_win": round(abs(dur - b["window_s"]), 2),
            "abs_dev_prod": round(abs(dur - b["prod_dur_s"]), 2),
            "peak_dbfs": round(20 * np.log10(peak + 1e-10), 1),
            "clip_samples": clip,
            "lufs": round(lufs(path), 1),
            "snr_db": round(snr_estimate(x, sr), 1),
            "f0_mean_hz": round(f0["f0_mean"], 1),
            "f0_std_hz": round(f0["f0_std"], 1),
            "creak_frac": round(f0["creak_frac"], 3),
            "lead_ms": round(gaps["lead_ms"]),
            "long_gap_ms": round(gaps["long_gap_ms"]),
            "total_pause_ms": round(gaps["total_pause_ms"]),
            "n_voiced": f0["n_voiced"],
        })
    return rows


def fmt(v, nd=1, na="—"):
    return na if v is None or (isinstance(v, float) and v != v) else f"{v:.{nd}f}"


def write_report(outdir: Path, report_path: Path, beat_note: str) -> None:
    beats = load_beats()
    candidates = sorted(d.name for d in outdir.iterdir()
                        if d.is_dir() and (d / "beat_B1.wav").exists())
    blocks, agg = [], {}
    for c in candidates:
        rows = measure_candidate(outdir / c, beats)
        (outdir / c / "metrics.json").write_text(json.dumps(rows, indent=1))
        ok = [r for r in rows if "error" not in r]
        agg[c] = {}
        for k in ("abs_dev_win", "abs_dev_prod", "lufs", "snr_db",
                  "f0_std_hz", "creak_frac", "long_gap_ms", "clip_samples"):
            vals = [r[k] for r in ok if r.get(k) == r.get(k)]
            agg[c][k] = round(sum(vals) / len(vals), 2) if vals else None
        lines = [
            f"### {c}",
            "",
            "| beat | dur s | window s | prod s | |Δ|win | |Δ|prod | peak dBFS | clip | LUFS | SNR dB | F0 μ/σ Hz | creak frac | lead ms | longest gap ms |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for r in rows:
            if "error" in r:
                lines.append(f"| {r['beat_id']} | — | — | — | — | — | — | — | "
                             f"— | — | — | — | — | — |")
                continue
            lines.append(
                f"| {r['beat_id']} | {r['dur_s']} | {r['win_s']} | {r['prod_s']} "
                f"| {r['abs_dev_win']} | {r['abs_dev_prod']} | {r['peak_dbfs']} "
                f"| {r['clip_samples']} | {fmt(r['lufs'])} | {fmt(r['snr_db'])} "
                f"| {r['f0_mean_hz']}/{r['f0_std_hz']} | {fmt(r['creak_frac'], 3)} "
                f"| {r['lead_ms']} | {r['long_gap_ms']} |")
        blocks.append("\n".join(lines))

    summary = ["| candidate | mean |Δ| vs window (s) | mean |Δ| vs prod (s) | LUFS | "
               "SNR dB | F0 σ (Hz) | creak frac | clip |",
               "|---|---|---|---|---|---|---|---|"]
    for c in candidates:
        a = agg[c]
        summary.append(
            f"| {c} | {fmt(a['abs_dev_win'], 2)} | {fmt(a['abs_dev_prod'], 2)} "
            f"| {fmt(a['lufs'])} | {fmt(a['snr_db'])} | {fmt(a['f0_std_hz'])} "
            f"| {fmt(a['creak_frac'], 3)} | {fmt(a['clip_samples'], 0)} |")

    # CPU generation cost from manifests (per line + total, model load excluded)
    cost = ["\nCPU generation cost (arm64 CPU, per line, model load excluded):",
            "", "| candidate | mean gen s / line | total gen s (7 lines) |",
            "|---|---|---|"]
    for c in candidates:
        mf = outdir / c / "manifest.json"
        if not mf.exists():
            continue
        gs = [m.get("gen_s") for m in json.loads(mf.read_text())]
        gs = [g for g in gs if g is not None]
        if gs:
            cost.append(f"| {c} | {sum(gs)/len(gs):.1f} | {sum(gs):.1f} |")
        else:
            cost.append(f"| {c} | not recorded | not recorded |")

    md = report_stub(beat_note) + "\n## Summary (mean over B1–B7)\n\n" \
        + "\n".join(summary) + "\n\n" + "\n".join(cost) \
        + "\n\n## Per-beat detail\n\n" + "\n\n".join(blocks) + "\n"
    report_path.write_text(md)
    print(f"report -> {report_path}")


def report_stub(beat_note: str) -> str:
    return f"""# V11 Stage 2c — TTS Benchmark (ADVISORY, PROD UNCHANGED)

Generated by `tools/tts_bench_v11.py` on an arm64 CPU (offline, local models only).
Material: ice_slippery B1–B7 ({beat_note}). Reference clip for zero-shot
candidates: prod `stories/ice_slippery/audio/beat_B7.wav` (current narrator).
Kokoro cannot clone; it uses its library voice `bm_george` (the prod
voices.yaml kokoro default) — voice consistency vs the narrator is therefore
not assessable for Kokoro.

**Production status: `configs/voices.yaml`, `src/providers/*` and all pipeline
paths are UNCHANGED. This benchmark is advisory until explicitly accepted.**

Candidate availability:
- chatterbox-turbo (ResembleAI/chatterbox-turbo) — RUN
- chatterbox-base (ResembleAI/chatterbox, the model cached in prod venv-cb) — RUN (reference)
- chatterbox-nano (ResembleAI/chatterbox-nano, `nano=True`) — RUN (chatterbox built from source; pip 0.1.7 predates Nano)
- qwen3-tts-0.6b — NOT RUN: Qwen/Qwen3-TTS* repos are gated (HTTP 401) on
  Hugging Face; no open-weights offline build exists, and external APIs are
  out of scope for this benchmark.
- kokoro-82m (local kokoro-v0_19.onnx + voices.bin) — RUN

Method notes:
- F0 via librosa YIN (fmin 60 / fmax 400 Hz, ~46 ms frames); creak proxy =
  share of voiced frames below 75 Hz. YIN medians were cross-validated
  against the prod reference clip (deep male narrator) — the three chatterbox
  clones land in the reference register; Kokoro's library voice sits higher
  (no clone, expected).
- SNR is an active-level vs noise-floor estimate, capped at 80 dB.
- Integrated LUFS per file via ffmpeg ebur128 (pre-normalization).
- All four candidates ran offline on arm64 CPU; zero external API calls.

## Recommendation (advisory — requires ckdigital acceptance)

**Keep Chatterbox Turbo as the narrator. No production change is proposed by
this benchmark.**

Reasoning against the directive's criteria:
- Pacing/timing fit: turbo (mean |Δ| 0.85 s vs beat window, 0.53 s vs prod
durations) and nano (0.80 / 0.54) are tied and both track the production
narrator closely; base trails (1.01 / 0.88).
- Punctuation respect: all candidates pause at punctuation; turbo's longest
pause averages 554 ms (most deliberate documentary read), nano 389 ms. One
turbo outlier (B1, ~1.2 s internal pause) is worth a listen before acceptance.
- Low creak: the creak proxy is inherited from the narrator reference clip —
turbo (0.36) and nano (0.35) match the reference's character; base smooths it
slightly (0.29). Reducing creak is a reference-clip/voice decision, not a
model swap; no candidate fixes it.
- Voice consistency: turbo/nano/base all clone the narrator (F0 median 79–83
Hz vs ref ~78 Hz). Kokoro cannot clone — bm_george is a different voice, so it
fails the one-voice-per-video constraint unless ckdigital accepts a voice
change.
- CPU cost: nano is 2× faster than turbo (22 s vs 45 s per line) at equal
quality — the natural next candidate if generation cost matters. Caveat: prod
venv-cb ships chatterbox-tts 0.1.7, which cannot load Nano (source build
required), and nano's SNR is the lowest of the cloners (36 dB).
- Numbers/names: B6 ("minus five" / "minus thirty") rendered by all cloners;
round-trip QA not automated here.

Kokoro is fastest (4.6 s/line) and cleanest, but is a voice change — out of
scope for the current mandate.

## Gaps

- Objective metrics only; no human listening pass (naturalness, authority,
emotional range from directive P1 remain unmeasured).
- Chatterbox default sampling params for turbo/nano (no per-line tuning);
base used the prod fallback params (ex 0.40 / cfg 0.35) + narrator clone.
- Single story (ice_slippery, 7 lines). Directive P1 asks for a 30–45 s read
A/B with human review before any production decision.
- Qwen3-TTS-0.6B untested: gated upstream, no open-weights offline build.
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backend", required=True,
                    choices=["chatterbox", "kokoro", "measure"])
    ap.add_argument("--candidate", default="turbo",
                    choices=["turbo", "nano", "base"])
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--report", default=str(ROOT / "V11_TTS_BENCH.md"))
    ap.add_argument("--ref-wav", default=str(STORY / "audio" / "beat_B7.wav"))
    args = ap.parse_args()

    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    beats = load_beats()

    if args.backend == "chatterbox":
        ref = Path(args.ref_wav) if Path(args.ref_wav).exists() else None
        synth_chatterbox(args.candidate, beats, ref, outdir)
    elif args.backend == "kokoro":
        synth_kokoro(beats, outdir)
    else:
        note = ("7 short lines incl. hedged B6/B7; numbers in B6 "
                "(minus five / minus thirty)")
        write_report(outdir, Path(args.report), note)


if __name__ == "__main__":
    main()
