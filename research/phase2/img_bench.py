"""Phase 2 image-source bench: same 4 house-style prompts per provider, timed.
Usage: python3 img_bench.py <provider> [seed]   (uses repo providers, no cache writes)"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/home/ubuntu/video_engine"); sys.path.insert(0, "/home/ubuntu/video_engine/illustrated_engine")
from engine.v15_plates import REQ_W, REQ_H, _factory
P = json.loads(Path("/home/ubuntu/video_engine/research/phase2/qa_prompts.json").read_text())
PROMPTS = sorted(P)[:4]
name = sys.argv[1]; seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1234
out = Path(f"/home/ubuntu/phase2_out/img/{name}"); out.mkdir(parents=True, exist_ok=True)
prov = _factory().get(name); rows = []
for i, p in enumerate(PROMPTS):
    t = time.time()
    try:
        prov.generate(p, str(out / f"{i+1}.png"), width=REQ_W, height=REQ_H, seed=seed + i)
        rows.append({"i": i + 1, "ok": True, "s": round(time.time() - t, 1)})
    except Exception as e:
        rows.append({"i": i + 1, "ok": False, "s": round(time.time() - t, 1), "err": str(e)[:160]})
    if name == "pollinations": time.sleep(16)
res = {"provider": name, "model": getattr(prov, "_model", None), "rows": rows}
(out / "result.json").write_text(json.dumps(res, indent=1)); print(json.dumps(res))
