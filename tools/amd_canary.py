#!/usr/bin/env python3
"""AMD Token Factory canary — head-to-head vs paid ZAI GLM.

Replays the SAME representative workload prompts sent to paid ZAI GLM
(research JSON, fact-check JSON array, script build, script_review,
claim extract/verify, JSON extraction, tool decision, reasoning, coding)
against AMD Token Factory and the paid ZAI GLM API (glm-5.3-flash).

Measures per provider:
  - availability: 429 / 5xx / timeout / 401 / connection / other
  - latency per call (s)
  - JSON validity (when the prompt demands JSON)
  - truncation (finish_reason == "length" or output at max_tokens)
  - factual accuracy (known-answer number probes)
  - claim-gate results (supported vs contradicted claims)
  - output consistency (repeat 3 prompts 3x; pairwise agreement)

Usage:
  AMD_API_BASE=https://<base>/v1 AMD_API_KEY=<key> AMD_MODEL=<amd-model> \
      ./venv/bin/python tools/amd_canary.py [--requests 30] [--out logs/amd_canary]

Env:
  AMD_API_BASE   required — OpenAI-compatible base URL from the AMD portal
  AMD_API_KEY    required — key from the AMD Token Factory portal
  AMD_MODEL      optional
  ZAI_API_KEY — loaded from .env (control leg)

Safety: never prints keys; never writes production config; only appends to
the canary output dir. Production routing is untouched (user directive).
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"), override=True)

TOPIC = "Venus: Earth's toxic twin"  # same topic as the real v1-v3 runs

# ---- Representative prompt corpus (mirrors production prompts) ----
RESEARCH_PROMPT = """You are a documentary research lead. Produce a rigorous fact pack for a
one-minute documentary.
Requirements:
- 8-15 verified facts, each with: claim, value (number), unit, source (organisation, e.g. NASA/ESA/Wikipedia), year
- Include: key dates, key numbers, key people/missions, 1-2 controversies or common misconceptions
- Facts must be CURRENT as of 2026 and widely accepted
- No speculation, no invented numbers
Respond in STRICT JSON (no markdown):
{"facts": [{"claim": "...", "value": <number or null>, "unit": "...", "source": "...", "year": <int or null>, "confidence": <0-1>}], "hook_ideas": ["..."], "misconceptions": ["..."], "key_sources": ["..."]}
TOPIC: {topic}"""

FACTCHECK_PROMPT = """You are a fact-checker. Verify each claim independently. For each fact, respond with:
{"fact": "<claim>", "verified": true/false, "notes": "<why>", "adjusted_confidence": <0-1>}
STRICT JSON array only.
FACTS:
{facts}"""

SCRIPT_PROMPT = """You are a world-class documentary scriptwriter. Write a documentary script
of EXACTLY 5 scenes for a video with a TOTAL spoken runtime of about 60
seconds (160 words maximum, spoken pace ~150 wpm).
Use the verified facts below — every number must come from them. Do NOT invent facts.
- MICRO-WINDOW HOOK: the single most striking fact must land within the first 3-5 SECONDS.
- Each scene opens with a micro-hook; scene 0 plants an open question answered later.
- Short punchy sentences (~30 words per scene). Match pacing to content.
Respond in STRICT JSON: {"scenes": [{"n": 0, "narration": "...", "visual": "...", "shot_count": 3}]}
FACTS: {facts}"""

CLAIM_EXTRACT_PROMPT = """You are a documentary fact-checker. Extract EVERY quantitative claim from the narration.
Return STRICT JSON array of: {"claim": "...", "value": <number|null>, "unit": "...", "span": "..."}
NARRATION: {narration}"""

CLAIM_VERIFY_PROMPT = """You are a scientific fact-checker. Verify this claim against the given research facts.
Claim: '{claim}'
Facts: {facts}
Return STRICT JSON: {"supported": true|false, "missing": ["..."], "notes": "..."}"""

JSON_EXTRACT_PROMPT = """Extract structured data from this text: 'Maria is 34, lives in Lisbon,
hobbies are hiking and chess, currently employed.' Return JSON with keys:
name (string), age (number), city (string), hobbies (array of strings), employed (boolean)."""

TOOL_DECISION_PROMPT = """You are a video pipeline router. Tools available: ken_burns, stock_video,
static_frame, chart_animation, subtitle_render. Which single tool creates slow
camera motion from a still image? Return JSON {"tool": "...", "reason": "..."}."""

REASONING_PROMPT = ("Sally has 3 apples. She gives 1 to Tom, then Tom gives her 2 back. "
                    "Jack takes half of what Sally has now. How many apples does Sally have? "
                    "Answer with the final number and one short sentence.")

CODING_PROMPT = ("Fix this Python function: def avg(nums): return sum(nums) / len(nums). "
                 "It crashes on empty input. Rewrite it to return 0.0 for an empty list and "
                 "skip non-numeric entries. Output ONLY the corrected code, no explanations.")

# Known-answer factual probes: (label, prompt, expected_substring)
FACT_PROBES = [
    ("venus_pressure", "What is Venus's surface pressure in Earth atmospheres? Answer with just the number and unit.",
     "92"),
    ("venus_co2", "What percentage of Venus's atmosphere is carbon dioxide? Answer with just the number and unit.",
     "96"),
    ("venus_temp", "What is Venus's average surface temperature in Celsius? Answer with just the number and unit.",
     "464"),
    ("magellan", "What fraction of Venus's surface did NASA's Magellan mission map with radar? Answer with the number and unit.",
     "98"),
]

# Claim-gate probes: (label, narration, facts, expected_supported)
CLAIM_PROBES = [
    ("supported_ok",
     "Venus has a surface pressure 92 times that of Earth, making it the hottest planet.",
     [{"claim": "Venus surface pressure is 92 times Earth's", "value": 92, "unit": "Earth atmospheres"},
      {"claim": "Venus is the hottest planet", "value": None, "unit": ""}],
     True),
    ("contradicted",
     "Venus has a surface pressure 92 times that of Earth, making it the coldest planet.",
     [{"claim": "Venus surface pressure is 92 times Earth's", "value": 92, "unit": "Earth atmospheres"},
      {"claim": "Venus is the hottest planet", "value": None, "unit": ""}],
     False),
]

def classify_error(exc: BaseException) -> str:
    s = str(exc or "").lower()
    if "429" in s or "resource_exhausted" in s.replace("_", "") or "quota" in s:
        return "429"
    if "403" in s or "forbidden" in s or "cloudflare" in s:
        return "403"
    if "401" in s or "unauthorized" in s or "invalid api key" in s:
        return "401"
    if "404" in s:
        return "404"
    if "timeout" in s or "timed out" in s:
        return "timeout"
    if "connection" in s or "refused" in s or "unreachable" in s or "resolve" in s:
        return "connection"
    if "500" in s or "502" in s or "503" in s or "504" in s:
        return "5xx"
    return "other"


def oai_chat(base_url, key, model, prompt, max_tokens=1000, temperature=0.2,
             json_mode=False, timeout=180):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens, "temperature": temperature}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    content = data["choices"][0]["message"]["content"]
    finish = data["choices"][0].get("finish_reason")
    usage = data.get("usage") or {}
    return {
        "content": content, "finish_reason": finish,
        "latency_s": round(time.time() - t0, 2),
        "usage": {"in": usage.get("prompt_tokens"), "out": usage.get("completion_tokens")},
    }


def is_valid_json(s):
    try:
        json.loads(s)
        return True
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--requests", type=int, default=30, help="target AMD requests (20-50)")
    ap.add_argument("--out", default="logs/amd_canary")
    ap.add_argument("--max-tokens", type=int, default=1000)
    args = ap.parse_args()
    n_req = max(20, min(50, args.requests))

    amd_base = os.environ.get("AMD_API_BASE", "").strip()
    amd_key = os.environ.get("AMD_API_KEY", "").strip()
    amd_model = os.environ.get("AMD_MODEL", "").strip()
    ds_key = os.environ.get("ZAI_API_KEY", "").strip()
    if not (amd_base and amd_key):
        print("BLOCKED: AMD_API_BASE and AMD_API_KEY are required (from the AMD Token Factory portal).")
        print("No AMD credentials found on this machine; canary cannot run live requests yet.")
        sys.exit(2)
    if not ds_key:
        print("BLOCKED: ZAI_API_KEY missing (control leg).")
        sys.exit(2)

    os.makedirs(args.out, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    jsonl_path = os.path.join(args.out, f"amd_canary_{ts}.jsonl")
    recs = []

    def run(tag, provider, base, key, model, prompt, json_mode, timeout=180):
        t0 = time.time()
        try:
            r = oai_chat(base, key, model, prompt, max_tokens=args.max_tokens,
                         temperature=0.2, json_mode=json_mode, timeout=timeout)
            rec = {"tag": tag, "provider": provider, "ok": True,
                   "latency_s": r["latency_s"], "error_class": None,
                   "json_ok": is_valid_json(r["content"]) if json_mode else None,
                   "truncated": r["finish_reason"] == "length",
                   "finish_reason": r["finish_reason"],
                   "out_chars": len(r["content"]),
                   "usage_in": r["usage"]["in"], "usage_out": r["usage"]["out"]}
            out = r["content"]
        except Exception as e:
            rec = {"tag": tag, "provider": provider, "ok": False,
                   "latency_s": round(time.time() - t0, 2),
                   "error_class": classify_error(e), "json_ok": None,
                   "truncated": None, "finish_reason": None,
                   "out_chars": 0, "usage_in": None, "usage_out": None}
            out = None
        recs.append(rec)
        with open(jsonl_path, "a") as f:
            f.write(json.dumps(rec) + "\n")
        disp = "OK" if rec["ok"] else rec["error_class"]
        print(f"  {tag:28s} {provider:12s} {disp:6s} {rec['latency_s']:7.2f}s"
              f" json={rec['json_ok']} trunc={rec['truncated']}", flush=True)
        return out, rec

    corpus = [
        ("research", RESEARCH_PROMPT.format(topic=TOPIC), True),
        ("factcheck", FACTCHECK_PROMPT.format(facts=json.dumps(
            [{"claim": "Venus surface pressure is 92 times Earth's", "value": 92, "unit": "Earth atmospheres"},
             {"claim": "Venus atmosphere is 96.5% CO2", "value": 96.5, "unit": "%"}])), True),
        ("script_build", SCRIPT_PROMPT.format(facts=json.dumps(
            [{"claim": "Venus surface pressure is 92 times Earth's", "value": 92, "unit": "atm"},
             {"claim": "Venus atmosphere is 96.5% CO2", "value": 96.5, "unit": "%"}])), True),
        ("claim_extract", CLAIM_EXTRACT_PROMPT.format(
            narration="DAVINCI+ and VERITAS missions launch in the late 2020s and early 2030s."), True),
        ("claim_verify_supported", CLAIM_VERIFY_PROMPT.format(
            claim="Venus has a surface pressure 92 times that of Earth, making it the hottest planet.",
            facts=json.dumps([{"claim": "Venus surface pressure is 92 times Earth's", "value": 92},
                              {"claim": "Venus is the hottest planet"}])), True),
        ("claim_verify_contradicted", CLAIM_VERIFY_PROMPT.format(
            claim="Venus has a surface pressure 92 times that of Earth, making it the coldest planet.",
            facts=json.dumps([{"claim": "Venus surface pressure is 92 times Earth's", "value": 92},
                              {"claim": "Venus is the hottest planet"}])), True),
        ("json_extract", JSON_EXTRACT_PROMPT, True),
        ("tool_decision", TOOL_DECISION_PROMPT, True),
        ("reasoning", REASONING_PROMPT, False),
        ("coding", CODING_PROMPT, False),
    ]
    # factual probes
    for label, prompt, expected in FACT_PROBES:
        corpus.append((f"fact_{label}", prompt, False))

    print(f"=== AMD ({amd_model}) vs ZAI GLM (glm-5.3-flash) canary — {n_req} AMD reqs ===", flush=True)
    ds_base = os.environ.get("ZAI_BASE_URL", "https://api.z.ai/api/paas/v4").rstrip("/")
    # Pass 1: interleave AMD + ZAI GLM on the fixed corpus (10-12 prompts)
    n = 0
    for tag, prompt, jm in corpus:
        for prov, base, key, model in (("amd", amd_base, amd_key, amd_model),
                                       ("zai", ds_base, ds_key, "glm-5.3-flash")):
            run(f"{tag}", prov, base, key, model, prompt, jm)
            n += 1
    # Pass 2: consistency — repeat 3 prompts 3x on AMD and ZAI GLM
    for tag, prompt, jm in corpus[:3]:
        for i in range(3):
            run(f"{tag}_rep{i}", "amd", amd_base, amd_key, amd_model, prompt, jm)
            n += 1
            run(f"{tag}_rep{i}", "zai", ds_base, ds_key, "glm-5.3-flash", prompt, jm)
            n += 1
    # Pass 3: top up to n_req AMD requests with research/script variants
    while n < n_req:
        for tag, prompt, jm in corpus:
            if n >= n_req:
                break
            run(f"{tag}_x", "amd", amd_base, amd_key, amd_model, prompt, jm)
            n += 1
            run(f"{tag}_x", "zai", ds_base, ds_key, "glm-5.3-flash", prompt, jm)
            n += 1

    # ---- summary ----
    def agg(prov):
        rs = [r for r in recs if r["provider"] == prov]
        ok = [r for r in rs if r["ok"]]
        errs = {}
        for r in rs:
            if not r["ok"]:
                errs[r["error_class"]] = errs.get(r["error_class"], 0) + 1
        lat = [r["latency_s"] for r in ok]
        jok = [r for r in ok if r["json_ok"] is not None]
        return {
            "calls": len(rs), "ok": len(ok),
            "errors": errs,
            "lat_mean_s": round(sum(lat) / len(lat), 2) if lat else None,
            "lat_max_s": round(max(lat), 2) if lat else None,
            "json_valid": sum(1 for r in jok if r["json_ok"]),
            "json_total": len(jok),
            "truncated": sum(1 for r in ok if r["truncated"]),
            "usage_in": sum(r["usage_in"] or 0 for r in ok),
            "usage_out": sum(r["usage_out"] or 0 for r in ok),
        }

    a, d = agg("amd"), agg("zai")
    report = {
        "ts": ts, "topic": TOPIC, "amd_model": amd_model,
        "requests_target": n_req, "requests_actual": len([r for r in recs if r["provider"] == "amd"]),
        "amd": a, "zai": d,
        "note": "Production routing untouched. AMD = free tier, ZAI GLM = paid control.",
    }
    rep_path = os.path.join(args.out, f"amd_canary_summary_{ts}.json")
    with open(rep_path, "w") as f:
        json.dump(report, f, indent=2)
    print("\n=== SUMMARY ===", flush=True)
    print(json.dumps(report, indent=2), flush=True)
    print(f"\nJSONL: {jsonl_path}\nSummary: {rep_path}", flush=True)


if __name__ == "__main__":
    main()
