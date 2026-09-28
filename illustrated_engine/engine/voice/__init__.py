"""Voice layer (WP3, DESIGN.md §5): one voice per video, per-sentence synthesis
joined with designed gaps, word timing aligned to the script, round-trip QA.

    synthesize(sentences, cfg, out_wav)  -> VoiceResult     (one clip)
    synthesize_video(story_dir, beats)   -> dict            (V15: one wav per
        beat, one voice for the whole video, whole-video fallback on failure)

The chosen provider is fixed before the first synthesis. If it fails part-way
every partial wav is discarded and the WHOLE script is re-synthesised with the
next voice in `fallback`; voices are never mixed. The switch is recorded.
"""
from __future__ import annotations

import hashlib
import json
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from engine.voice.lexicon import Lexicon
from engine.voice.text import split_sentences

REPO = Path(__file__).resolve().parents[3]
CONFIG = REPO / "configs" / "voice.yaml"
ROLES = ("hook", "normal", "payoff")


class VoiceUnavailable(RuntimeError):
    """A provider cannot (or must not) synthesise; the caller falls back."""


@dataclass
class Sentence:
    text: str
    role: str = "normal"


@dataclass
class Clip:
    audio: np.ndarray            # float32 mono
    sr: int
    words: list | None = None    # provider-native [{w,t0,t1}] (clip-relative)


@dataclass
class VoiceResult:
    wav: Path
    words: list                  # [{w,t0,t1}] one per script token
    timing: dict                 # v15_timing-compatible (words, pauses, ...)
    provider: str
    voice_id: str
    model: str
    commercial_ok: bool
    license_ref: str
    rtf: float
    qa: dict
    duration: float = 0.0
    sentence_spans: list = field(default_factory=list)  # [(t0, t1)] truth


def load_config(path=None) -> dict:
    cfg = yaml.safe_load(Path(path or CONFIG).read_text())
    for role, f in cfg["speed_by_role"].items():
        if not 0.95 <= f <= 1.08:
            raise ValueError(f"speed_by_role.{role}={f} outside 0.95-1.08")
    if cfg["channel_voice"] not in cfg["voices"]:
        raise ValueError("channel_voice is not a defined voice")
    return cfg


def load_lexicon(cfg: dict) -> Lexicon:
    p = Path(cfg.get("lexicon") or "")
    return Lexicon.load(p if p.is_absolute() else REPO / p)


def make_provider(voice_id: str, cfg: dict, lexicon: Lexicon | None = None):
    v = cfg["voices"][voice_id]
    if v["provider"] == "kokoro":
        from engine.voice.kokoro import KokoroProvider
        return KokoroProvider(v, lexicon or load_lexicon(cfg))
    if v["provider"] == "fish":
        from engine.voice.fish import FishProvider
        return FishProvider(v)
    raise ValueError(f"unknown provider {v['provider']!r}")


def _trim(audio: np.ndarray, sr: int, keep_s: float = 0.02) -> tuple:
    """Trim leading/trailing silence -> (audio, seconds cut from the start)."""
    thr = max(0.002, float(np.abs(audio).max()) * 0.02) if len(audio) else 0
    idx = np.nonzero(np.abs(audio) > thr)[0]
    if not len(idx):
        return audio, 0.0
    a = max(0, int(idx[0]) - int(keep_s * sr))
    b = min(len(audio), int(idx[-1]) + int(keep_s * sr) + 1)
    return audio[a:b], a / sr


def _gap_ms(cfg: dict, roles: list, i: int) -> int:
    g = cfg["gaps_ms"]
    if roles[i] == "hook":
        return g["hook"]
    if i + 1 < len(roles) and roles[i + 1] == "payoff":
        return g["payoff"]
    return g["normal"]


def _write_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    peak = float(np.abs(audio).max()) if len(audio) else 0.0
    if peak > 0.98:  # Kokoro can exceed 1.0; scale, never clip (loudnorm later)
        audio = audio * (0.98 / peak)
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


def _join(clips: list, roles: list, cfg: dict) -> tuple:
    """-> (audio, sr, [(t0, t1) per sentence], native words | None)."""
    sr = clips[0].sr
    parts, spans, words, t = [], [], [], 0.0
    for i, c in enumerate(clips):
        if c.sr != sr:
            raise VoiceUnavailable("provider returned mixed sample rates")
        a, lead = _trim(c.audio, sr)
        parts.append(a)
        spans.append((round(t, 3), round(t + len(a) / sr, 3)))
        if c.words:
            words += [{"w": w["w"], "t0": w["t0"] - lead + t,
                       "t1": w["t1"] - lead + t} for w in c.words]
        t += len(a) / sr
        if i + 1 < len(clips):
            gap = int(_gap_ms(cfg, roles, i) / 1000 * sr)
            parts.append(np.zeros(gap, dtype=np.float32))
            t += gap / sr
    native = words if all(c.words for c in clips) else None
    return np.concatenate(parts), sr, spans, native


def _voice_meta(cfg: dict, voice_id: str) -> dict:
    v = cfg["voices"][voice_id]
    return {"provider": v["provider"], "voice_id": v.get("voice")
            or v.get("reference_id") or voice_id, "model": v["model"],
            "commercial_ok": bool(v.get("commercial_ok")),
            "license_ref": v.get("license_ref", "")}


def _timing_fallback(wav: Path, script: str) -> dict:
    from engine.v15_timing import align
    return align(wav, script)


def _asr_timing(wav: Path, script: str, cfg: dict, lex: Lexicon,
                native, asr_fn, counts: list, spans: list) -> tuple:
    """-> (timing, qa). ASR unavailable -> qa HOLD ("not run"), silence_v1
    timing: a QA that could not run is never a pass."""
    from engine.voice import align, qa as qa_mod
    try:
        asr = asr_fn(wav)
    except Exception as e:
        return _timing_fallback(wav, script), {
            "verdict": "HOLD", "checked": False,
            "reason": f"asr unavailable: {type(e).__name__}"}
    q = qa_mod.round_trip(script, asr, lex, cfg["qa"]["max_wer"])
    q["checked"] = True
    src = native if native else asr
    timing = align.timing_from_asr(script, src, None if native else wav)
    timing = align.clamp_to_spans(timing, counts, spans)
    if native:
        timing["method"] = "provider_native"
    return timing, q


def synthesize(sentences: list, cfg: dict, out_wav, *, provider=None,
               voice_id: str | None = None, lexicon: Lexicon | None = None,
               asr_fn=None, base_speed: float | None = None) -> VoiceResult:
    """Synthesise `sentences` with ONE provider into out_wav. Round-trip QA
    retries the failing sentences once (lexicon respelling, 0.95x speed)."""
    from engine.voice import align
    out_wav = Path(out_wav)
    voice_id = voice_id or cfg["channel_voice"]
    lex = lexicon or load_lexicon(cfg)
    provider = provider or make_provider(voice_id, cfg, lex)
    asr_fn = asr_fn or (lambda w: align.transcribe(w, cfg["qa"]["asr_model"]))
    speed = base_speed or cfg["voices"][voice_id].get("speed", 1.0)
    roles = [s.role for s in sentences]
    texts = [s.text for s in sentences]
    script = " ".join(texts)
    counts = [len(t.split()) for t in texts]
    spd = [speed * cfg["speed_by_role"][r] for r in roles]

    t0 = time.time()
    clips = [provider.synth(t, s) for t, s in zip(texts, spd)]
    synth_s = time.time() - t0
    audio, sr, spans, native = _join(clips, roles, cfg)
    _write_wav(out_wav, audio, sr)
    timing, qa = _asr_timing(out_wav, script, cfg, lex, native, asr_fn,
                               counts, spans)

    if qa["verdict"] == "FAIL":  # one retry of the offending sentences
        first, bad = qa, _bad_sentences(script, texts, qa)
        t1 = time.time()
        for i in bad:
            clips[i] = provider.synth(lex.respell(texts[i]),
                                      max(spd[i] * 0.95, 0.5))
        synth_s += time.time() - t1
        audio, sr, spans, native = _join(clips, roles, cfg)
        _write_wav(out_wav, audio, sr)
        timing, qa = _asr_timing(out_wav, script, cfg, lex, native, asr_fn,
                               counts, spans)
        qa["retried_sentences"] = bad
        qa["first_pass"] = {k: first[k] for k in ("wer", "hard_missed")}
        if qa["verdict"] == "FAIL":
            qa["verdict"] = "HOLD"
    elif qa["verdict"] == "PASS":
        qa["retried_sentences"] = []
    dur = len(audio) / sr
    return VoiceResult(wav=out_wav, words=timing["words"], timing=timing,
                       rtf=round(synth_s / max(dur, 1e-6), 3), qa=qa,
                       duration=round(dur, 3), sentence_spans=spans,
                       **_voice_meta(cfg, voice_id))


def _bad_sentences(script: str, texts: list, qa: dict) -> list:
    """Sentence indices containing a wrongly-heard word."""
    bounds, n = [], 0
    for t in texts:
        n += len(t.split())
        bounds.append(n)
    return sorted({next(k for k, b in enumerate(bounds) if i < b)
                   for i in qa["bad_word_idx"]})


def sentences_for_beat(text: str, function: str | None,
                       cfg: dict) -> list:
    role = cfg["role_by_function"].get(function or "", "normal")
    return [Sentence(s, role) for s in split_sentences(text)]


def _sidecar_key(voice_id: str, cfg: dict, text: str, role: str,
                 speed: float) -> str:
    v = json.dumps(cfg["voices"][voice_id], sort_keys=True)
    return hashlib.sha256(f"{v}|{cfg['gaps_ms']}|{cfg['speed_by_role']}|{role}"
                          f"|{speed}|{text}".encode()).hexdigest()[:16]


def synthesize_beat(story_dir, beat_id: str, text: str, function: str | None,
                    cfg: dict, *, get_provider, voice_id: str,
                    lexicon: Lexicon, asr_fn=None, force: bool = False,
                    base_speed: float | None = None) -> dict:
    """One beat -> audio/beat_<id>.wav (+ .timing.json in v15_timing format,
    + .voice.json sidecar keyed by voice/config/text so a cached beat is only
    reused for the same voice). `get_provider()` is called only on a cache
    miss (loading Kokoro costs ~6 s)."""
    story_dir = Path(story_dir)
    wav = story_dir / "audio" / f"beat_{beat_id}.wav"
    side = wav.with_suffix(".voice.json")
    role = cfg["role_by_function"].get(function or "", "normal")
    speed = base_speed or cfg["voices"][voice_id].get("speed", 1.0)
    key = _sidecar_key(voice_id, cfg, text, role, speed)
    if not force and wav.exists() and side.exists():
        try:
            info = json.loads(side.read_text())
            if info.get("key") == key:
                return info
        except (OSError, ValueError):
            pass
    res = synthesize(sentences_for_beat(text, function, cfg), cfg, wav,
                     provider=get_provider(), voice_id=voice_id, lexicon=lexicon,
                     asr_fn=asr_fn, base_speed=base_speed)
    timing = dict(res.timing)
    from engine.v15_timing import timing_key
    timing["key"] = timing_key(wav, text)
    wav.with_suffix(".timing.json").write_text(json.dumps(timing, indent=1))
    info = {"key": key, "file": f"audio/beat_{beat_id}.wav",
            "duration": round(res.duration, 3), "provider": res.provider,
            "voice_id": res.voice_id, "model": res.model,
            "commercial_ok": res.commercial_ok,
            "license_ref": res.license_ref, "rtf": res.rtf, "qa": res.qa,
            "timing_method": timing["method"]}
    side.write_text(json.dumps(info, indent=1))
    return info


def _discard(story_dir: Path, beat_ids: list) -> None:
    for b in beat_ids:
        for p in (story_dir / "audio").glob(f"beat_{b}.*"):
            p.unlink()


def synthesize_video(story_dir, beats: list, cfg: dict | None = None, *,
                     provider_factory=None, asr_fn=None, force: bool = False,
                     base_speed: float | None = None) -> dict:
    """All beats of one video with ONE voice; on any failure discard every
    beat wav and redo the whole script with the next voice in the chain."""
    cfg = cfg or load_config()
    lex = load_lexicon(cfg)
    factory = provider_factory or (lambda vid, c: make_provider(vid, c, lex))
    chain = [cfg["channel_voice"]] + [v for v in cfg["fallback"]
                                      if v != cfg["channel_voice"]]
    story_dir = Path(story_dir)
    ids = [b["beat_id"] for b in beats]
    switches = []
    for voice_id in chain:
        memo = {}

        def get_provider(voice_id=voice_id, memo=memo):
            if "p" not in memo:
                memo["p"] = factory(voice_id, cfg)
            return memo["p"]
        try:
            out = {b["beat_id"]: synthesize_beat(
                story_dir, b["beat_id"], b["narration"], b.get("function"),
                cfg, get_provider=get_provider, voice_id=voice_id, lexicon=lex,
                asr_fn=asr_fn, force=force, base_speed=base_speed)
                for b in beats}
            break
        except Exception as e:  # unreliable service: fall back, whole video
            _discard(story_dir, ids)
            force = True
            switches.append({"from": voice_id, "reason": f"{type(e).__name__}: "
                             f"{str(e)[:120]}"})
    else:
        raise VoiceUnavailable("every voice in the chain failed: "
                               + json.dumps(switches))
    if switches:
        switches[-1]["to"] = voice_id
        for a, b in zip(switches, switches[1:]):
            a["to"] = b["from"]
    infos = list(out.values())
    meta = _voice_meta(cfg, voice_id)
    ref = sum(i["qa"].get("ref_tokens", 0) for i in infos)
    err = sum(i["qa"].get("errors", 0) for i in infos)
    unchecked = [b for b, i in out.items() if not i["qa"].get("checked")]
    hold = [b for b, i in out.items() if i["qa"]["verdict"] != "PASS"]
    publishable = meta["commercial_ok"] or not cfg["publish_requires_commercial_ok"]
    return {"beats": out, "voice": dict(
        meta, switches=switches, publishable=publishable,
        qa={"verdict": "HOLD" if hold else "PASS",
            "wer": round(err / ref, 4) if ref else None,
            "held_beats": hold, "unchecked_beats": unchecked,
            "max_wer": cfg["qa"]["max_wer"]})}

