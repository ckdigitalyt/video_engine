"""V11 P1 §9 — audio hierarchy QA (Jade_todo_v11); V12 P1 additions.

Default hierarchy: NARRATION > intentional SFX > subtle ambience/music,
with deliberate silence — a continuous tonal/ambient bed is NOT the
default (planv5 now emits a silence bed plan unless a bed is explicitly
declared; the mix ducks any declared bed under narration and the master
is normalized at -14 LUFS / -1.5 dBTP as before).

QA over the rendered master + bed plan + narration timing:
  speech_to_bed_ratio      narration stem vs bed loudness delta (null
                           when the plan is bed-free — the silence default)
  low_frequency_tonal_noise  spectral-peak scan of the quietest windows
                           (tonal hum/rumble filling the silence); V12 P1
                           DISCRIMINATES the source stem-level (narration
                           harmonics / intentional tonal bed / electrical
                           50/60 Hz hum / repetitive synthetic tone) —
                           the 0.02 rule itself is unchanged
  silence_usage            V12 P1 — share + longest span of sub-floor
                           level (reported, informational)
  continuous_bed_duration  share of the timeline a bed covers; >70%
                           fails unless the bed is explicitly authored
  unnecessary_ambience     bed-only stretches (no narration, no SFX)
  sfx_narration_masking    SFX onsets landing inside narration speech
                           windows (transients are tolerated)
  dynamic_range            loudness range of the master (crushed or wild)

Plan/engine/mix behavior only — TTS providers and voices.yaml untouched.
"""
from __future__ import annotations

import io
import json
import subprocess
import wave
from pathlib import Path

import numpy as np

BED_SHARE_MAX = 0.70       # continuous-bed coverage ceiling (undeclared)
SFX_MASK_TRANSIENT_S = 0.8  # SFX shorter than this may sit under narration
LRA_MIN, LRA_MAX = 2.0, 18.0
HUM_ABS = 0.02             # tonal peak energy share in quiet windows


def _decode_mono(path: Path, sr: int = 16000) -> np.ndarray:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1",
         "-ar", str(sr), "-f", "f32le", "-"], capture_output=True)
    if p.returncode != 0 or not p.stdout:
        return np.zeros(0, dtype=np.float32)
    return np.frombuffer(p.stdout, dtype=np.float32)


def _lufs(path: Path) -> float | None:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-i", str(path), "-af",
         "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True)
    m = None
    for line in (p.stderr or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                m = json.loads(line)
            except Exception:
                m = None
    if not m or "input_i" not in m:
        return None
    try:
        return float(m["input_i"])
    except Exception:
        return None


def _quiet_windows(x: np.ndarray, sr: int, n: int = 6, win_s: float = 1.0) -> list:
    w = int(win_s * sr)
    if len(x) < w * 2:
        return []
    rms = np.array([float(np.sqrt(np.mean(x[i:i + w] ** 2)))
                    for i in range(0, len(x) - w, w)])
    idx = np.argsort(rms)[:n]
    return [int(i) * w for i in sorted(idx)]


def _tonal_peaks(x: np.ndarray, sr: int, offs: list) -> list:
    """Tonal peaks in 30-80 Hz across the quietest windows -> strongest
    single-bin energy share per window. The band is sub-bass (hum, rumble,
    synth pads): speech fundamentals sit ~85-180 Hz, so energy down here
    in the quietest windows is the tonal-fill signature the directive
    targets, not narration leakage."""
    w = int(1.0 * sr)
    out = []
    for o in offs:
        seg = x[o:o + w]
        if len(seg) < w // 2:
            continue
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
        band = (freqs >= 30) & (freqs <= 80)
        if not band.any() or spec.sum() <= 0:
            continue
        out.append(round(float(spec[band].max() / spec.sum()), 4))
    return out


# --- V12 P1 — LOW_FREQ_TONALITY discrimination (Jade_todo_v12 §P1) ---------
# The 0.02 narration-silence rule above stays UNCHANGED. What is new: when
# tonal energy shows up in the quiet windows, the QA now names WHAT it is —
# narration harmonics, an intentional (declared) tonal bed, electrical
# 50/60 Hz hum, or a repetitive synthetic tone — stem-level FFT root
# cause, building on the V11 P1b-fix approach in audio_mix/procedural.

_CLASS_BAND = (30.0, 300.0)   # hum + bed fundamentals + voice fundamentals
_HUM_SERIES = (50.0, 60.0, 100.0, 120.0, 150.0, 180.0, 200.0, 240.0, 300.0)


def _window_peaks(x: np.ndarray, sr: int, o: int, lo: float = _CLASS_BAND[0],
                  hi: float = _CLASS_BAND[1], top: int = 3) -> list:
    """Top spectral peaks (freq_hz, share) of one 1 s window."""
    w = int(1.0 * sr)
    seg = x[o:o + w]
    if len(seg) < w // 2:
        return []
    spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
    freqs = np.fft.rfftfreq(len(seg), 1.0 / sr)
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any() or spec.sum() <= 0:
        return []
    sb, fb = spec[band], freqs[band]
    order = np.argsort(sb)[::-1]
    peaks, taken = [], []
    for i in order:
        f = float(fb[i])
        if any(abs(f - t) < 6.0 for t in taken):
            continue  # skip sidebands of an already-taken peak
        peaks.append((round(f, 1), round(float(sb[i] / spec.sum()), 4)))
        taken.append(f)
        if len(peaks) >= top:
            break
    return peaks


def _stem_peaks(path: Path, lo: float = _CLASS_BAND[0],
                hi: float = _CLASS_BAND[1], top: int = 3) -> list:
    """Dominant tonal frequencies of a stem/file (average spectrum over
    its 1 s windows) — the stem-level FFT root-cause reference."""
    try:
        x = _decode_mono(Path(path))
    except Exception:
        return []
    if x.size < 16000:
        return []
    acc = None
    n = 0
    for o in range(0, len(x) - 8000, 16000):
        seg = x[o:o + 16000]
        if len(seg) < 16000:
            break
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) ** 2
        acc = spec if acc is None else acc + spec
        n += 1
    if not n or acc.sum() <= 0:
        return []
    freqs = np.fft.rfftfreq(16000, 1.0 / 16000)
    band = (freqs >= lo) & (freqs <= hi)
    if not band.any():
        return []
    sb, fb = acc[band] / n, freqs[band]
    order = np.argsort(sb)[::-1]
    peaks, taken = [], []
    for i in order:
        f = float(fb[i])
        if any(abs(f - t) < 6.0 for t in taken):
            continue
        peaks.append(round(f, 1))
        taken.append(f)
        if len(peaks) >= top:
            break
    return peaks


def _classify_tonal(x: np.ndarray, sr: int, offs: list,
                    narration_windows: list, bed_files: list,
                    narration_stem: Path | None) -> dict:
    """Classify tonal energy in the quiet windows into the directive's
    four classes (narration harmonics / intentional tonal bed / electrical
    50/60 Hz hum / repetitive synthetic tone)."""
    bed_peaks = []
    for bf in bed_files or []:
        if bf and Path(bf).exists():
            bed_peaks.extend(_stem_peaks(Path(bf)))
    nar_peaks = _stem_peaks(narration_stem) if (
        narration_stem and Path(narration_stem).exists()) else []
    rows = []
    for o in offs:
        t = o / sr
        in_narration = any(a - 0.25 <= t < b + 0.25
                           for a, b in narration_windows)
        for freq, share in _window_peaks(x, sr, o):
            cls, ev = None, ""
            if in_narration:
                cls, ev = "narration_harmonics", "quiet window overlaps a " \
                    "narration-active span"
            elif nar_peaks and any(abs(freq - p) <= 2.0 for p in nar_peaks):
                cls, ev = "narration_harmonics", \
                    f"{freq} Hz matches a narration-stem peak"
            elif any(abs(freq - h) <= 1.5 for h in _HUM_SERIES):
                cls, ev = "electrical_hum", \
                    f"{freq} Hz sits on the 50/60 Hz harmonic series"
            elif bed_peaks and any(abs(freq - p) <= 2.0 for p in bed_peaks):
                cls, ev = "intentional_tonal_bed", \
                    f"{freq} Hz matches a declared bed stem peak"
            else:
                cls, ev = "repetitive_synthetic_tone", \
                    f"stable {freq} Hz tone matching no bed/hum/voice peak"
            rows.append({"t": round(t, 2), "freq_hz": freq, "share": share,
                         "class": cls, "evidence": ev})
    # stability: same class+fuzzy freq across >= 2 windows -> repetitive
    by_class = {}
    for r in rows:
        by_class.setdefault(r["class"], []).append(r)
    counts = {k: len(v) for k, v in by_class.items()}
    dominant = (max(by_class.items(), key=lambda kv: max(
        r["share"] for r in kv[1]))[0] if rows else None)
    return {"rows": rows, "class_counts": counts,
            "dominant_class": dominant,
            "bed_reference_hz": sorted(set(bed_peaks))[:6],
            "narration_reference_hz": sorted(set(nar_peaks))[:6]}


def _bed_coverage(bed_plan: dict, shot_durs: list) -> tuple:
    """-> (coverage_share, bed_only_spans, declared). A bed 'file' string
    means a bed is active for that shot; None = deliberate silence."""
    beds = bed_plan.get("bed_files") or []
    declared = bool(bed_plan.get("authored"))
    active = 0.0
    bed_only = []
    t = 0.0
    for b, d in zip(beds + [None] * max(0, len(shot_durs) - len(beds)),
                    list(shot_durs) + [0.0] * max(0, len(shot_durs) - len(beds))):
        if b:
            active += float(d)
        t += float(d)
    sfx_times = [(float(s.get("at") or 0)) for s in bed_plan.get("sfx") or []]
    # bed-only stretches: active bed with no sfx anywhere in the shot
    t = 0.0
    for b, d in zip(beds, shot_durs):
        if b and not any(t - 0.5 <= st < t + float(d) + 0.5 for st in sfx_times):
            bed_only.append([round(t, 2), round(t + float(d), 2)])
        t += float(d)
    total = float(sum(shot_durs)) or 1.0
    return active / total, bed_only, declared


def _narration_windows(plan: dict, timing: dict) -> list:
    """Per-shot narration-active spans [t0, t1] on the video timeline."""
    out = []
    t = 0.0
    for s in plan.get("shots") or []:
        d = float(s.get("duration_s") or 0)
        beat = timing.get(str(s.get("beat_id")) or "") or {}
        nd = float(beat.get("duration") or 0)
        if nd > 0 and d > 0:
            out.append([t, t + min(nd, d)])
        t += d
    return out


def _sfx_durations(sfx: list) -> list:
    durs = []
    for s in sfx or []:
        f = str(s.get("file") or "")
        d = None
        if f and Path(f).exists():
            try:
                with wave.open(f, "rb") as w:
                    d = w.getnframes() / float(w.getframerate())
            except Exception:
                d = None
        durs.append(d)
    return durs


def run(plan: dict, bed_plan: dict, timing: dict, master: Path,
        narration_stem: Path | None = None,
        mix_policy: dict | None = None) -> dict:
    shots = plan.get("shots") or []
    shot_durs = [float(s.get("duration_s") or 0) for s in shots]
    coverage, bed_only, declared = _bed_coverage(bed_plan, shot_durs)
    findings = []
    checks = {}

    # --- speech-to-bed ratio -------------------------------------------------
    bed_files = sorted({b for b in (bed_plan.get("bed_files") or []) if b})
    if not bed_files:
        checks["speech_to_bed_ratio"] = {
            "bed": None, "delta_lufs": None,
            "pass": True,
            "note": "bed-free plan — deliberate silence default (P1 §9)"}
    else:
        nar_l = _lufs(Path(narration_stem)) if narration_stem else None
        bed_l = _lufs(Path(bed_files[0])) if bed_files else None
        delta = (nar_l - bed_l) if (nar_l is not None and bed_l is not None) else None
        ok = delta is not None and delta >= 6.0
        checks["speech_to_bed_ratio"] = {
            "narration_lufs": nar_l, "bed_lufs": bed_l, "delta_lufs": delta,
            "pass": ok, "note": "narration must sit >=6 LU above the bed"}
        if not ok:
            findings.append({"severity": "P1", "rule": "speech_to_bed_ratio",
                             "detail": f"narration-bed delta {delta} LU (<6)"})

    # --- continuous bed duration / unnecessary ambience ----------------------
    checks["continuous_bed_duration"] = {
        "coverage": round(coverage, 3), "declared": declared,
        "pass": coverage <= BED_SHARE_MAX or declared,
        "note": "a continuous tonal bed is not the default (>70% coverage "
                "fails unless the bed is explicitly authored)"}
    if coverage > BED_SHARE_MAX and not declared:
        findings.append({"severity": "P0", "rule": "continuous_bed_default",
                         "detail": f"bed covers {coverage:.0%} of the runtime"})
    long_bed_only = [sp for sp in bed_only
                     if sp[1] - sp[0] > 5.0]
    checks["unnecessary_ambience"] = {
        "bed_only_spans": bed_only, "long_spans": long_bed_only,
        "pass": not long_bed_only,
        "note": "bed running with no narration and no SFX for >5s"}
    if long_bed_only:
        findings.append({"severity": "P1", "rule": "unnecessary_ambience",
                         "detail": f"bed-only spans {long_bed_only[:3]}"})

    # --- SFX / narration masking --------------------------------------------
    nar_windows = _narration_windows(plan, timing)
    sfx = bed_plan.get("sfx") or []
    sdurs = _sfx_durations(sfx)
    masked, transient_ok = 0, 0
    for s, d in zip(sfx, sdurs):
        at = float(s.get("at") or 0)
        if any(a <= at < b for a, b in nar_windows):
            if d is not None and d <= SFX_MASK_TRANSIENT_S:
                transient_ok += 1
            else:
                masked += 1
    checks["sfx_narration_masking"] = {
        "sfx_total": len(sfx), "overlapping_narration": masked + transient_ok,
        "sustained_overlaps": masked, "transient_overlaps": transient_ok,
        "sfx_ducked_in_mix": bool((mix_policy or {}).get("sfx_ducked")),
        "pass": masked == 0 or bool((mix_policy or {}).get("sfx_ducked")),
        "note": "transient SFX may punctuate narration; sustained SFX must "
                "either stay out of narration windows or be ducked under "
                "speech by the mix (NARRATION > intentional SFX)"}
    if masked and not (mix_policy or {}).get("sfx_ducked"):
        findings.append({"severity": "P1", "rule": "sfx_narration_masking",
                         "detail": f"{masked} sustained SFX inside narration windows "
                                  "and the mix does not duck SFX under speech"})

    # --- dynamic range + low-frequency tonal noise (rendered master) --------
    lra = None
    master_path = Path(master)
    tonal_class = {"rows": [], "class_counts": {}, "dominant_class": None}
    silence_usage = None
    if master_path.exists():
        p = subprocess.run(
            ["ffmpeg", "-nostdin", "-i", str(master_path), "-af",
             "loudnorm=print_format=json", "-f", "null", "-"],
            capture_output=True, text=True)
        for line in (p.stderr or "").splitlines():
            line = line.strip()
            if line.startswith("{"):
                try:
                    lra = float(json.loads(line).get("input_lra"))
                except Exception:
                    pass
        x = _decode_mono(master_path)
        quiet_offs = _quiet_windows(x, 16000) if x.size else []
        peaks = _tonal_peaks(x, 16000, quiet_offs) if x.size else []
        hum = max(peaks) if peaks else 0.0
        if x.size:
            # V12 P1 — discriminate WHAT the tonal energy is
            tonal_class = _classify_tonal(
                x, 16000, quiet_offs, nar_windows,
                [b for b in (bed_plan.get("bed_files") or []) if b],
                narration_stem)
            # V12 P1 — silence usage (reported, informational)
            w = 8000  # 0.5 s windows @16 kHz
            rms = np.array([float(np.sqrt(np.mean(x[i:i + w] ** 2)))
                            for i in range(0, len(x) - w, w)])
            active = rms[rms > 1e-4]
            floor = (float(np.median(active)) * 0.05) if active.size else 0.0
            silent = rms <= max(floor, 1e-4)
            share = float(silent.mean()) if silent.size else 0.0
            longest, run_len = 0.0, 0
            for sv in silent:
                run_len = run_len + 0.5 if sv else 0.0
                longest = max(longest, run_len)
            silence_usage = {"share": round(share, 3),
                             "longest_silence_s": round(longest, 2),
                             "window_s": 0.5,
                             "note": "deliberate silence is the default "
                                     "hierarchy floor (reported, not gated)"}
    else:
        peaks, hum = [], 0.0
    checks["dynamic_range"] = {
        "lra": lra, "pass": lra is None or (LRA_MIN <= lra <= LRA_MAX),
        "note": f"master loudness range must sit in {LRA_MIN}..{LRA_MAX} LU"}
    if lra is not None and not (LRA_MIN <= lra <= LRA_MAX):
        findings.append({"severity": "P1", "rule": "dynamic_range",
                         "detail": f"LRA {lra}"})
    dominant_cls = tonal_class.get("dominant_class")
    checks["low_frequency_tonal_noise"] = {
        "quiet_window_peaks": peaks, "max_share": hum, "threshold": HUM_ABS,
        "pass": hum <= HUM_ABS,
        "classification": tonal_class,
        "note": "tonal peaks in 30-80 Hz (sub-bass: hum/rumble/pads) during "
                "the quietest windows; V12 P1 discriminates the source: "
                f"dominant class = {dominant_cls}"}
    if hum > HUM_ABS:
        findings.append({"severity": "P1", "rule": "low_frequency_tonal_noise",
                         "detail": f"tonal share {hum} in quiet windows "
                                   f"(dominant class: {dominant_cls})"})
    checks["silence_usage"] = {
        **(silence_usage or {"share": None, "longest_silence_s": None}),
        "pass": True,
        "note": "reported for the directive's silence-usage addition; "
                "informational, never gated"}

    hard = (checks["continuous_bed_duration"]["pass"]
            and checks["speech_to_bed_ratio"]["pass"]
            and checks["dynamic_range"]["pass"]
            and checks["low_frequency_tonal_noise"]["pass"]
            and checks["sfx_narration_masking"]["pass"])
    return {"schema": "v11.audio_qa/1.0", "checks": checks,
            "findings": findings, "AUDIO_HIERARCHY_PASS": bool(hard)}


def write_report(res: dict, out_dir: Path, story_id: str = "") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / (f"audio_qa_{story_id}.json" if story_id
                   else "audio_qa.json")
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
