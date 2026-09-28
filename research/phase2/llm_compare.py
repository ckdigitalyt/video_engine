"""Phase 2: Claude CLI vs Gemini vs GLM on two real V15 calls, scored with V15's
own validators. (1) Beat Visual Plan for blackhole_clocks; (2) plate QA on the
e2e contact sheet (the call that came back 'unparseable' in the timed run)."""
import json, subprocess, sys, time
from pathlib import Path
IE = Path("/home/ubuntu/video_engine/illustrated_engine"); sys.path.insert(0, str(IE))
from engine import director as D
from engine.v15_plan import build_prompt, _parse_json, _repair, validate_plan
from engine.v15_style import load_style
from engine.v15_plates import QA_QUESTION, _main_subject
OUT = Path("/home/ubuntu/phase2_out/llm_compare"); OUT.mkdir(parents=True, exist_ok=True)
SD = Path("/home/ubuntu/phase2_out/stories/blackhole_clocks")
story = json.loads((SD / "story.json").read_text()); bible = load_style(SD, story)

def claude(prompt, image=None):
    cmd = ["claude", "-p", "--output-format", "json", "--strict-mcp-config",
           "--allowedTools", "Read", "--disallowedTools",
           "Bash Edit Write WebFetch WebSearch Task NotebookEdit Glob Grep"]
    if image:
        prompt = f"First use the Read tool to view the image at {image}. Then answer.\n\n" + prompt
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=600, cwd="/tmp")
    j = json.loads(r.stdout)
    return j.get("result"), {k: j.get(k) for k in ("total_cost_usd", "num_turns", "duration_ms", "usage", "modelUsage")}

res = {}
def run(name, fn):
    t = time.time()
    try:
        out = fn()
    except Exception as e:
        out = (None, {"error": str(e)[:300]})
    raw, meta = out if isinstance(out, tuple) else (out, {})
    res[name] = {"wall_s": round(time.time() - t, 1), "meta": meta, "raw": raw}
    (OUT / f"{name}.txt").write_text(str(raw))
    return raw

which = sys.argv[1:] or ["plan", "qa"]
if "plan" in which:
    P = build_prompt(story, bible)
    for name, fn in (("plan_gemini", lambda: D._text_gemini(P, 0.0, 6000)),
                     ("plan_glm", lambda: D._text_glm(P, 0.0, 6000)),
                     ("plan_claude", lambda: claude(P))):
        raw = run(name, fn); plan = _parse_json(raw) if raw else None
        if plan is None:
            res[name]["verdict"] = "unparseable/none"; continue
        errs = validate_plan(_repair(plan, story), story)
        res[name].update(n_errors=len(errs), errors=errs[:8],
                         n_shots=sum(len(b.get("shots", [])) for b in plan.get("beats", [])))
if "qa" in which:
    rep = json.loads((Path("/home/ubuntu/phase2_out/e2e_blackhole/visual_plan.json")).read_text())
    sheet = "/home/ubuntu/phase2_out/e2e_blackhole/plate_sheet.jpg"
    prompts = sorted(json.loads(Path(sys.argv[0]).with_name("qa_prompts.json").read_text()))
    listing = "\n".join(f"#{i+1}: {_main_subject(p.split('. ')[1] if '. ' in p else p)}" for i, p in enumerate(prompts))
    Q = QA_QUESTION.format(style=bible.get("illustration_style", "")[:200], n=len(prompts), items=listing)
    mt = 60 * len(prompts) + 200
    for name, fn in (("qa_gemini", lambda: D._vision_gemini(sheet, Q, mt)),
                     ("qa_glm", lambda: D._vision_glm(sheet, Q, mt)),
                     ("qa_claude", lambda: claude(Q, sheet))):
        raw = run(name, fn)
        parsed = D.vision_ask.__globals__.get("_parse_vision_json")
        try:
            j = json.loads(raw[raw.find("{"): raw.rfind("}") + 1]) if raw else None
        except Exception:
            j = None
        res[name]["parsed_ok"] = isinstance(j, dict) and "plates" in j
        res[name]["n_plates"] = len(j["plates"]) if res[name]["parsed_ok"] else None
        res[name]["fails"] = [p for p in (j or {}).get("plates", []) if p.get("fail")] if res[name]["parsed_ok"] else None
(OUT / ("result_" + "_".join(which) + ".json")).write_text(json.dumps(res, indent=1, default=str))
print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != "raw"} for k, v in res.items()}, indent=1, default=str)[:6000])
