#!/usr/bin/env python3
"""
comprehensive_code_review.py — Root-cause review of the video_engine programs.

Sends the core pipeline source + evidence of 5 recurring defects to
Gemini Pro and ZAI GLM (parallel), asks each for a root-cause
analysis + prioritized code-level recommendations, and saves the
reports to logs/code_review_{gemini,zai}.md

Evidence bundled:
  - The 5 recurring blockers (repeated_assets, motion_continuity,
    mirrored_edges, claim_contradictions, entity_disambiguation)
  - v6 Andromeda rerun QA output (gates firing on a cached-reuse run)
  - STATUS.json / run_report.json summaries
  - Timeline camera-move sequence
  - Recent fix history (git log) so reviewers know what was already tried
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")
from dotenv import load_dotenv
load_dotenv(override=True)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(ROOT, "logs")
RESULTS = os.path.join(ROOT, "results", "the_andromeda_milky_way_collision__our_g")

# ── Files under review ───────────────────────────────────────────────────────
CORE_FILES = [
    "mission_stills.py",
    "src/director/motion_grammar.py",
    "src/qa/deterministic_qa.py",
    "src/qa/claim_verifier.py",
    "src/orchestration/v2_pipeline.py",
]

# ── Evidence extraction ──────────────────────────────────────────────────────
def read(path):
    try:
        with open(path, "r", errors="replace") as f:
            return f.read()
    except Exception as e:
        return f"(unreadable: {e})"


def git_history():
    try:
        import subprocess
        out = subprocess.run(
            ["git", "-C", ROOT, "log", "--oneline", "-25"],
            capture_output=True, text=True, timeout=10)
        return out.stdout.strip()
    except Exception:
        return "(git log unavailable)"


def evidence_bundle():
    parts = []
    # STATUS + run report summary
    st = json.loads(read(os.path.join(RESULTS, "STATUS.json")))
    parts.append("=== STATUS.json ===")
    parts.append(json.dumps(st, indent=1))
    rr = json.loads(read(os.path.join(RESULTS, "run_report.json")))
    parts.append("\n=== run_report.json (key sections) ===")
    for k in ("started_at", "strategy", "stages"):
        if k in rr:
            parts.append(f"{k}: {json.dumps(rr[k], indent=1)[:2000]}")
    # v6 log QA lines
    v6log = os.path.join(LOGS, "andromeda_v6_run.log")
    if os.path.exists(v6log):
        lines = read(v6log).splitlines()
        keep = [l for l in lines if any(t in l for t in (
            "[qa]", "QA BLOCKED", "CLAIM GATE", "claim_gate", "[CACHE]",
            "coverage]", "PUBLISH GATE", "[status]", "sources", "cached:",
            "perceptual", "flips", "mirrored", "repeated_assets",
            "motion_continuity", "entity_disambiguation",
            "claim_contradictions", "manifest", "reuse]"))]
        parts.append("\n=== v6 run log (QA-relevant lines) ===")
        parts.append("\n".join(keep[:150]))
    # Timeline camera sequence
    tl_path = os.path.join(RESULTS, "timeline.json")
    if os.path.exists(tl_path):
        try:
            tl = json.loads(read(tl_path))
            vtl = tl.get("video_timeline", []) if isinstance(tl, dict) else tl
            seq = []
            for s in vtl:
                if isinstance(s, dict):
                    seq.append({
                        "t": round(s.get("start", s.get("t", 0)), 2),
                        "asset": os.path.basename(str(s.get("asset", ""))),
                        "camera": s.get("camera", s.get("move", s.get("motion", "?"))),
                    })
            parts.append("\n=== timeline video_timeline (camera moves) ===")
            parts.append(json.dumps(seq[:40], indent=1))
        except Exception as e:
            parts.append(f"(timeline parse failed: {e})")
    return "\n".join(parts)


REVIEW_PROMPT = """You are a principal software engineer doing a root-cause review of a documentary video production pipeline. The pipeline keeps producing the SAME 5 defects across many runs despite repeated point-fixes. Your job: find the SYSTEMIC root causes and give prioritized, code-level recommendations.

RECURRING DEFECTS (blockers):
1. repeated_assets — the same/similar image appears multiple times in one video ("perceptual repeats: 8 (same visual, different file)").
2. motion_continuity — jarring camera-move flips at cuts (e.g. pull_out -> push_in at 77.355s).
3. mirrored_edges — images show mirrored/black edges (Ken Burns pan exposes image borders).
4. claim_contradictions — script claims contradict each other.
5. entity_disambiguation — entities/names used ambiguously or wrongly.

KNOWN SYSTEMIC PATTERNS (validate/refute with the code):
- Runs reuse a topic cache (\"[CACHE] sceneX_Y.jpg reused from topic cache\", sources: cached=20, fresh=0), which may BYPASS generation-time fixes (dedup, camera compatibility) while QA gates still fire on the rendered result.
- The claims \"fix\" loop reports passed:true after rewrites (Groq/OpenRouter chain), yet the final review still flags claim_contradictions + entity_disambiguation — the fix loop may be gate-gaming rather than genuinely resolving contradictions.
- Camera-move compatibility logic was added (v21) but motion_continuity still fails — the fix may not cover all code paths (cache-reuse, coverage variants, timeline assembly).

TASK — for EACH of the 5 defects:
A. Root cause: trace the exact code path (file + function + line numbers) that lets this defect through. Distinguish generation-time vs detection-time vs fix-loop.
B. Why previous fixes failed (check the fix history provided).
C. Concrete fix design: name the function(s) to change/add, the algorithm, parameters, and where the fix MUST live so it cannot be bypassed by cache reuse or variant paths.
D. How to verify the fix (which gate, what metric).

Then give a PRIORITIZED implementation plan (P0/P1/P2) with the exact files to touch.

You are reviewing the full source of these files (below): mission_stills.py (main pipeline), src/director/motion_grammar.py (camera grammar), src/qa/deterministic_qa.py (objective QA gates), src/qa/claim_verifier.py (claims gate + fix loop), src/orchestration/v2_pipeline.py (orchestration).

Respond in markdown with clear sections. Be specific and ruthless — no generic advice.
"""


def gemini_review(bundle):
    from google import genai
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    models = ["gemini-2.5-pro", "gemini-3.1-pro-preview", "gemini-3.5-flash"]
    last_err = None
    for model in models:
        for attempt in range(1, 4):
            try:
                print(f"[gemini] trying {model} (attempt {attempt}/3)...")
                resp = client.models.generate_content(
                    model=model,
                    contents=REVIEW_PROMPT + "\n\n===== SOURCE CODE + EVIDENCE =====\n" + bundle,
                    config={"response_mime_type": "text/plain"},
                )
                return model, resp.text
            except Exception as e:
                last_err = str(e)[:200]
                print(f"[gemini] {model} attempt {attempt} failed: {last_err}")
                time.sleep(8)
    raise RuntimeError(f"Gemini review failed: {last_err}")


def zai_review(bundle):
    import requests
    url = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {os.environ['ZAI_API_KEY']}",
        "Content-Type": "application/json",
    }
    payload = {
        # glm-5.3-flash always thinks: no "thinking" field; generous max_tokens.
        "model": os.environ.get("ZAI_MODEL", "glm-5.3-flash"),
        "messages": [
            {"role": "system", "content":
                "You are a principal software engineer performing a rigorous "
                "root-cause code review. Be specific, cite file/function/line, "
                "and give prioritized implementable fixes."},
            {"role": "user", "content":
                REVIEW_PROMPT + "\n\n===== SOURCE CODE + EVIDENCE =====\n" + bundle},
        ],
        "temperature": 0.2,
        "max_tokens": 8000,
        "stream": False,
    }
    for attempt in range(1, 4):
        try:
            print(f"[zai] attempt {attempt}/3...")
            r = requests.post(url, headers=headers, json=payload, timeout=600)
            r.raise_for_status()
            data = r.json()
            return os.environ.get("ZAI_MODEL", "glm-5.3-flash"), data["choices"][0]["message"]["content"]
        except Exception as e:
            last_err = str(e)[:200]
            print(f"[zai] attempt {attempt} failed: {last_err}")
            time.sleep(10)
    raise RuntimeError(f"ZAI GLM review failed: {last_err}")


def main():
    os.makedirs(LOGS, exist_ok=True)
    print("[review] assembling source + evidence bundle...")
    parts = []
    for f in CORE_FILES:
        p = os.path.join(ROOT, f)
        parts.append(f"\n\n{'='*80}\nFILE: {f} ({os.path.getsize(p)} bytes)\n{'='*80}")
        parts.append(read(p))
    bundle = "\n".join(parts) + "\n\n" + evidence_bundle()
    bundle += "\n\n=== FIX HISTORY (git log) ===\n" + git_history()
    print(f"[review] bundle size: {len(bundle)} chars")

    # Run both reviews sequentially in this process (parallel via background procs if desired)
    results = {}
    for name, fn in (("gemini", gemini_review), ("zai", zai_review)):
        try:
            model, text = fn(bundle)
            out = os.path.join(LOGS, f"code_review_{name}.md")
            with open(out, "w") as f:
                f.write(f"# Code review ({name}) — model: {model}\n\n")
                f.write(f"_Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}_\n\n")
                f.write(text)
            results[name] = out
            print(f"[review] {name} DONE -> {out} ({len(text)} chars)")
        except Exception as e:
            results[name] = f"FAILED: {e}"
            print(f"[review] {name} FAILED: {e}")

    print("\n=== REVIEW SUMMARY ===")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
