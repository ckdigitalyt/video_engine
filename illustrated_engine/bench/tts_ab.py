#!/usr/bin/env python3
"""TTS A/B harness — synthesize the same narration lines with two voices.

FREE-tier only (voices.allow_paid: false). Default pair:
  A = fish       (production narrator, voices.yaml fish.voice_id)
  B = chatterbox (kurzgesagt_like fallback, voices.yaml chatterbox.voice_id)

Writes one wav per line per voice plus a manifest.json recording provider,
voice/model, text, duration and any errors, so a human can listen side by
side and pick. Synthesis failures degrade gracefully: the error is recorded
in the manifest and the other voice continues.

Usage:
  python3 bench/tts_ab.py --story sahara_greening
  python3 bench/tts_ab.py --story sahara_greening --beats B1 B4 B6
  python3 bench/tts_ab.py --list-providers
"""
import argparse
import json
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))          # engine package lives here
sys.path.append(str(ROOT.parent))      # repo root: src.providers lives there

from engine import tts as eng_tts  # noqa: E402  (loads repo .env for FISH)

LINE_PICKER = ("hook_first", "escalation_first", "payoff_last")


def pick_lines(story: dict, beats: list[str] | None) -> list[dict]:
    beats_all = story.get("beats") or []
    if beats:
        want = [b.strip().upper() for b in beats]
        return [b for b in beats_all
                if str(b.get("beat_id", "")).upper() in want]
    # default: hook / first escalation / payoff
    esc = next((b for b in beats_all
                if "ESCALAT" in str(b.get("function", "")).upper()
                or "CONSEQUENCE" in str(b.get("function", "")).upper()), None)
    pay = beats_all[-1] if beats_all else None
    out = []
    if beats_all:
        out.append(beats_all[0])
    if esc and esc not in out:
        out.append(esc)
    if pay and pay not in out:
        out.append(pay)
    return out[:3]


def build_providers(pairs: list[str]) -> dict:
    from src.providers.tts_provider import (  # noqa: E402
        ChatterboxProvider, FishAudioProvider, KokoroProvider)
    out = {}
    for name in pairs:
        try:
            if name == "fish":
                out[name] = FishAudioProvider()  # config voice: Narrator
            elif name == "chatterbox":
                out[name] = ChatterboxProvider()  # config: kurzgesagt_like
            elif name == "kokoro":
                out[name] = KokoroProvider()
            else:
                out[name] = f"unknown provider '{name}'"
        except Exception as e:  # record, keep the other voice alive
            out[name] = f"construct failed: {e}"
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--story", default="sahara_greening")
    ap.add_argument("--beats", nargs="*", default=None,
                    help="beat ids to sample (default: hook/escalation/payoff)")
    ap.add_argument("--a", default="fish")
    ap.add_argument("--b", default="chatterbox")
    ap.add_argument("--list-providers", action="store_true")
    a = ap.parse_args()

    if a.list_providers:
        print("available: fish, chatterbox, kokoro "
              "(ElevenLabs is rollback-only, disabled by config)")
        return

    eng_tts._ensure_env_key()
    story = json.loads(
        (ROOT / "stories" / a.story / "story.json").read_text())
    lines = pick_lines(story, a.beats)
    if not lines:
        sys.exit("no lines picked — check --story/--beats")

    providers = build_providers([a.a, a.b])
    stamp = time.strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "bench" / "tts_ab" / f"{a.story}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = {"story": a.story, "generated": stamp,
                "voices": {}, "lines": []}
    for name in (a.a, a.b):
        p = providers[name]
        manifest["voices"][name] = (
            f"construct failed: {p}" if isinstance(p, str)
            else type(p).__name__)
    print(f"A/B run -> {out_dir}")
    dead = set()  # voices that timed out once are skipped for later lines

    class _Timeout(Exception):
        pass

    def _alarm(sig, frm):
        raise _Timeout()

    signal.signal(signal.SIGALRM, _alarm)

    def write_manifest():
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2))

    for i, b in enumerate(lines, 1):
        text = str(b.get("narration") or "")
        entry = {"beat": b.get("beat_id"), "text": text}
        for name in (a.a, a.b):
            p = providers[name]
            dest = out_dir / name / f"line{i}_{b.get('beat_id')}.wav"
            dest.parent.mkdir(parents=True, exist_ok=True)
            rec = {"provider": name, "file": str(dest.relative_to(ROOT))}
            if name in dead:
                rec["error"] = "skipped: voice already timed out this run"
            elif isinstance(p, str):
                rec["error"] = p
            else:
                signal.alarm(240)  # per-line watchdog: never hang the run
                try:
                    t0 = time.time()
                    p.generate_voice(text, str(dest))
                    signal.alarm(0)
                    rec["duration"] = round(
                        eng_tts.ffprobe_duration(dest), 3)
                    rec["synth_s"] = round(time.time() - t0, 1)
                except _Timeout:
                    signal.alarm(0)
                    dead.add(name)
                    rec["error"] = ("timeout after 240s — voice skipped for "
                                    "the rest of this run")
                except Exception as e:
                    signal.alarm(0)
                    rec["error"] = f"{type(e).__name__}: {e}"
            entry[name] = rec
            print(f"  {name} {b.get('beat_id')}: "
                  f"{rec.get('duration', rec.get('error'))}")
        manifest["lines"].append(entry)
        write_manifest()  # incremental: partial runs stay valid

    write_manifest()
    print(f"manifest -> {out_dir / 'manifest.json'}")
    print("listen side by side and pick; winners feed configs/voices.yaml")


if __name__ == "__main__":
    main()
