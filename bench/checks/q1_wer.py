"""Q1 exit check: round-trip voice WER <= 0.03 on 3 real scripts incl. Tunguska.

Uses the already-cached beat wavs under stories/<id>/audio/ (no new TTS
synthesis, no render) -- pure component check of the voice QA metric against
real narration audio. Run via bench/checks/Q1.sh.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "illustrated_engine"))

from engine import voice as V  # noqa: E402
from engine.voice import align, qa  # noqa: E402
from engine.voice.lexicon import Lexicon  # noqa: E402

SCRIPTS = ["tunguska_1908", "venus_day", "fever_thermostat"]
MAX_WER = 0.03


def score(story_id: str, model: str, lex: Lexicon) -> dict:
    story = json.loads((REPO / "illustrated_engine/stories" / story_id /
                         "story.json").read_text())
    audio = REPO / "illustrated_engine/stories" / story_id / "audio"
    errors = ref_tokens = 0
    beats = {}
    for b in story["beats"]:
        wav = audio / f"beat_{b['beat_id']}.wav"
        asr = align.transcribe(wav, model)
        r = qa.round_trip(b["narration"], asr, lex, max_wer=MAX_WER)
        errors += r["errors"]
        ref_tokens += r["ref_tokens"]
        beats[b["beat_id"]] = r["wer"]
    return {"story_id": story_id, "wer": round(errors / max(ref_tokens, 1), 4),
            "beats": beats}


def main() -> int:
    cfg = V.load_config()
    model = cfg["qa"]["asr_model"]
    lex = Lexicon.load(REPO / cfg["lexicon"])
    rows = [score(s, model, lex) for s in SCRIPTS]
    ok = all(r["wer"] <= MAX_WER for r in rows)
    print(json.dumps({"asr_model": model, "max_wer": MAX_WER, "scripts": rows,
                       "verdict": "PASS" if ok else "FAIL"}, indent=1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
