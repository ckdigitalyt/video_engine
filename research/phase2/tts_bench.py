"""Phase 2 TTS bench: RTF on this aarch64 CPU. Usage:
  venv/bin/python    tts_bench.py kokoro <model.onnx> <voices.bin> <voice>
  venv-cb/bin/python tts_bench.py chatterbox base|turbo [ref.wav]"""
import json, sys, time, wave
from pathlib import Path
import numpy as np
S = json.loads(Path("/home/ubuntu/phase2_out/stories/blackhole_clocks/story.json").read_text())
LINES = [b["narration"] for b in S["beats"][:4]] + [S["beats"][4]["narration"]]  # includes "38 microseconds"
OUT = Path("/home/ubuntu/phase2_out/tts"); OUT.mkdir(parents=True, exist_ok=True)
def save(p, x, sr):
    x = np.clip(np.asarray(x, dtype=np.float32).reshape(-1), -1, 1)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes((x * 32767).astype("<i2").tobytes())
    return len(x) / sr
kind = sys.argv[1]; t = time.time()
if kind == "kokoro":
    from kokoro_onnx import Kokoro
    m = Kokoro(sys.argv[2], sys.argv[3]); voice = sys.argv[4]
    tag = f"kokoro_{Path(sys.argv[2]).stem}_{voice}"
    synth = lambda s: m.create(s, voice=voice, speed=1.0, lang="en-us")
else:
    import torch; torch.set_num_threads(4)
    if sys.argv[2] == "turbo":
        from chatterbox.tts_turbo import ChatterboxTurboTTS as C
    else:
        from chatterbox.tts import ChatterboxTTS as C
    m = C.from_pretrained("cpu"); ref = sys.argv[3] if len(sys.argv) > 3 else None
    tag = f"chatterbox_{sys.argv[2]}" + ("_ref" if ref else "")
    def synth(s):
        kw = {"audio_prompt_path": ref} if ref else {}
        return m.generate(s, **kw).squeeze().numpy(), m.sr
load = time.time() - t
rows = []
for i, s in enumerate(LINES):
    t = time.time(); x, sr = synth(s); el = time.time() - t
    d = save(OUT / f"{tag}_{i+1}.wav", x, sr)
    rows.append({"i": i + 1, "wall": round(el, 2), "audio": round(d, 2), "rtf": round(el / d, 2)})
tw, ta = sum(r["wall"] for r in rows), sum(r["audio"] for r in rows)
res = {"tag": tag, "load_s": round(load, 1), "wall_s": round(tw, 1), "audio_s": round(ta, 1), "rtf": round(tw / ta, 2), "lines": rows}
(OUT / f"{tag}.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res))
