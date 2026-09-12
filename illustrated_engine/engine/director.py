"""V5 Creative Director layer (brief §1-13, §19-21).

The engine already produces attractive scenes; this module makes the
EDITORIAL visual choice explicit and gate-able:

  §1  visual argument per beat: claim / visual_question / visual_answer
  §2  one_second_comprehension for diagram/comparison/explanatory frames
  §5  visual mode selection (CINEMATIC never the default)
  §8  hero-asset semantic contract; subject_correctness > style_score
  §9  optional semantic asset validation via a vision model (DeepSeek
      vision endpoint); if no key, caller falls back to human inspection
  §12 narration-visual evidence type; ATMOSPHERIC/DECORATIVE never carry
      a factual claim unless justified
  §13 motion classification; explanatory beats prefer INFORMATION_MOTION
  §19/§21 the only new gate inputs: one_second_comprehension,
      subject_correctness and the §20 creative-director review (PASS).

No new QA subsystems; nothing here duplicates technical/visual/editorial QA.
"""

from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent  # /home/ubuntu/video_engine

VISUAL_MODES = ("CINEMATIC", "DIAGRAM", "COMPARISON", "EVIDENCE", "DETAIL",
                "MAP", "TIMELINE", "SCALE", "TYPOGRAPHY", "SPLIT",
                "TRANSFORMATION", "PAYOFF")

EVIDENCE_TYPES = ("DIRECT_EVIDENCE", "EXPLANATORY_DIAGRAM", "ANALOGY",
                  "ATMOSPHERIC", "DECORATIVE")

MOTION_TYPES = ("CAMERA_MOTION", "OBJECT_MOTION", "INFORMATION_MOTION",
                "REVEAL", "TRANSFORMATION", "TYPOGRAPHIC_MOTION")

# §12: only these may carry a factual/explanatory claim
FACTUAL_CARRYING = ("DIRECT_EVIDENCE", "EXPLANATORY_DIAGRAM")
# §13: motion that does explanatory work
EXPLANATORY_MOTION = ("INFORMATION_MOTION", "REVEAL", "TRANSFORMATION",
                      "TYPOGRAPHIC_MOTION")
# §2: modes whose frames must pass one-second comprehension
ONE_SECOND_MODES = ("DIAGRAM", "COMPARISON", "SPLIT", "SCALE", "TIMELINE",
                    "TRANSFORMATION")

GEMINI_MODEL = "gemini-2.5-flash"  # judge primary (free tier)
# Judge fallback: GLM 5.3 Flash via OpenRouter — owner directive 2026-09-12
# retired DeepSeek from the judge stack entirely (dead 401 key).
GLM_MODEL = "z-ai/glm-5.3-flash"
GLM_URL = "https://openrouter.ai/api/v1/chat/completions"

_ONE_SECOND_GATE = 70.0
_CINEMATIC_SHARE_MAX = 0.5  # §5: cinematic must not become the default


# ----------------------------------------------------------- vision (§9) ----

def _env_key(name: str) -> str:
    """Named key from env or repo .env (same pattern as tts.py)."""
    v = os.environ.get(name)
    if v:
        return v
    envp = REPO / ".env"
    if not envp.exists():
        return ""
    for line in envp.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, val = line.split("=", 1)
        if k.strip() == name and val.strip().strip("\"'"):
            return val.strip().strip("\"'")
    return ""


_LAST_GEMINI_CALL = {"t": 0.0}
_GEMINI_COOLDOWN = {"until": 0.0}  # on quota 429: skip Gemini 1h, GLM carries


def _vision_gemini(image_path, question: str, max_tokens: int):
    """Gemini free-tier fallback (approved alternative). -> text or None.

    Rate-limited politely: >=4 s between calls, backoff on 429/5xx —
    the free tier rejects bursts and an UNVERIFIED storm helps nobody.
    """
    key = _env_key("GEMINI_API_KEY")
    if not key:
        return None
    import time as _t
    from urllib.error import HTTPError
    if _t.time() < _GEMINI_COOLDOWN["until"]:
        return None

    try:
        import urllib.request

        gap = _t.time() - _LAST_GEMINI_CALL["t"]
        if gap < 4.0:
            _t.sleep(4.0 - gap)
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        body = {"contents": [{"parts": [
            {"text": question},
            {"inline_data": {"mime_type": "image/png", "data": b64}},
        ]}],
            "generationConfig": {"temperature": 0,
                                 "maxOutputTokens": max(1024, max_tokens * 3),
                                 # 2.5-flash is a thinking model — without an
                                 # explicit budget the answer arrives empty
                                 "thinkingConfig": {"thinkingBudget": 0}}}
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={key}")
        for attempt in range(3):
            _LAST_GEMINI_CALL["t"] = _t.time()
            req = urllib.request.Request(
                url, data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=90) as r:
                    data = json.loads(r.read())
                parts = data["candidates"][0]["content"]["parts"]
                return " ".join(p.get("text", "") for p in parts).strip() or None
            except HTTPError as e:
                if e.code in (429, 500, 503) and attempt < 2:
                    _t.sleep(12.0 * (attempt + 1))
                    continue
                if e.code == 429:
                    _GEMINI_COOLDOWN["until"] = _t.time() + 3600.0
                raise
    except Exception:
        return None
    return None


def _vision_glm(image_path, question: str, max_tokens: int):
    """GLM 5.3 Flash judge via OpenRouter (OpenAI-compatible). -> text or None."""
    key = _env_key("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        import time as _t
        import urllib.request
        from urllib.error import HTTPError

        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        body = {
            "model": GLM_MODEL,
            "temperature": 0,
            "max_tokens": max(512, max_tokens),
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": question},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            }],
        }
        req = urllib.request.Request(
            GLM_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                msg = data["choices"][0]["message"]
                return ((msg.get("content") or "").strip()
                        or None)
            except HTTPError as e:
                if e.code in (429, 500, 502, 503) and attempt < 2:
                    _t.sleep(8.0 * (attempt + 1))
                    continue
                raise
    except Exception:
        return None
    return None


def _text_gemini(prompt: str, temperature: float, max_tokens: int):
    """Gemini text judge (generateContent). -> text or None."""
    key = _env_key("GEMINI_API_KEY")
    if not key:
        return None
    try:
        import time as _t
        import urllib.request
        from urllib.error import HTTPError
        if _t.time() < _GEMINI_COOLDOWN["until"]:
            return None

        body = {"contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": temperature,
                                     "maxOutputTokens": max(1024, max_tokens * 3),
                                     "thinkingConfig": {"thinkingBudget": 0}}}
        url = ("https://generativelanguage.googleapis.com/v1beta/models/"
               f"{GEMINI_MODEL}:generateContent?key={key}")
        for attempt in range(3):
            try:
                req = urllib.request.Request(
                    url, data=json.dumps(body).encode(),
                    headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = json.loads(r.read())
                parts = data["candidates"][0]["content"]["parts"]
                return " ".join(p.get("text", "") for p in parts).strip() or None
            except HTTPError as e:
                if e.code in (429, 500, 503) and attempt < 2:
                    _t.sleep(12.0 * (attempt + 1))
                    continue
                if e.code == 429:
                    _GEMINI_COOLDOWN["until"] = _t.time() + 3600.0
                raise
    except Exception:
        return None
    return None


def _text_glm(prompt: str, temperature: float, max_tokens: int):
    """GLM 5.3 Flash text judge via OpenRouter. -> text or None."""
    key = _env_key("OPENROUTER_API_KEY")
    if not key:
        return None
    try:
        import urllib.request

        body = {"model": GLM_MODEL, "temperature": temperature,
                "max_tokens": max(512, max_tokens),
                "messages": [{"role": "user", "content": prompt}]}
        req = urllib.request.Request(
            GLM_URL, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.loads(r.read())
        return (data["choices"][0]["message"].get("content") or "").strip() or None
    except Exception:
        return None


def text_ask(prompt: str, temperature: float = 0.1, max_tokens: int = 2000):
    """Text judge chain: Gemini primary, GLM 5.3 Flash fallback.

    None only when both judges fail — callers must treat that as an explicit
    error/skip, never as a pass.
    """
    return (_text_gemini(prompt, temperature, max_tokens)
            or _text_glm(prompt, temperature, max_tokens))


def vision_ask(image_path, question: str, max_tokens: int = 400):
    """One vision question -> parsed JSON dict, or None if no path/failure.

    Judge chain (2026-09-12 owner directive): Gemini primary, GLM 5.3 Flash
    (OpenRouter) fallback; DeepSeek retired. Used ONLY as an acceptance check
    on high-value assets/frames (§9). If it returns None the caller keeps the
    explicit human-inspection path.
    """
    text = _vision_gemini(image_path, question, max_tokens)
    if text is None:
        text = _vision_glm(image_path, question, max_tokens)
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group()) if m else {"raw": text}


def subject_check(image_path, contract: dict) -> dict:
    """§8/§9: 'What is actually depicted?' vs the asset's semantic contract.

    contract: expected_subject, required[], forbidden[], role
    Returns {"ok", "verdict", "depicted", "missing", "forbidden_found",
             "via"}  (via = vision | unverified).
    """
    req = [str(x) for x in (contract.get("required") or [])]
    forbid = [str(x) for x in (contract.get("forbidden") or [])]
    prompt = (
        "You are an asset acceptance inspector for an illustrated documentary. "
        "Subject correctness outranks style.\n"
        f"expected_subject: {contract.get('expected_subject', '')}\n"
        f"required attributes (all must be present): {req}\n"
        f"forbidden attributes (any presence fails): {forbid}\n"
        "Question: what is actually depicted?\n"
        'Answer with strict JSON only: {"depicted": "<one sentence>", '
        '"required_present": [...], "required_missing": [...], '
        '"forbidden_found": [...], "verdict": "PASS"|"FAIL"}'
    )
    res = vision_ask(image_path, prompt)
    if not res or "verdict" not in res:
        return {"ok": None, "verdict": "UNVERIFIED", "depicted": "",
                "missing": req, "forbidden_found": [], "via": "unverified",
                "raw": res}
    ok = str(res.get("verdict", "")).upper() == "PASS" \
        and not res.get("forbidden_found")
    return {"ok": ok, "verdict": "PASS" if ok else "FAIL",
            "depicted": str(res.get("depicted", "")),
            "missing": res.get("required_missing") or [],
            "forbidden_found": res.get("forbidden_found") or [],
            "via": "vision"}


# --------------------------------------------- one-second comprehension ----

def one_second_static(shot: dict, card_paths: list) -> dict:
    """§2 static pass: can the frame carry its relationship in one second?

    Uses the shot's declared design (labels/big_number/relationship) plus a
    pixel-mass analysis of each stage card: a dominant information object
    must own the frame; label lists and absent big numbers are penalized.
    """
    spec = shot.get("one_second") or {}
    labels = spec.get("labels") or []
    reasons = []
    score = 100.0
    if len(labels) > 6:
        score -= 25.0
        reasons.append(f"{len(labels)} labels (list, not relationship)")
    elif len(labels) > 4:
        score -= 10.0
        reasons.append("too many labels for one glance")
    if not spec.get("relationship"):
        score -= 15.0
        reasons.append("no declared visual relationship")
    if spec.get("number_claim") and not spec.get("big_number"):
        score -= 25.0
        reasons.append("numeric claim without a large number")

    mass = _dominant_mass(card_paths)
    if mass is not None:
        if mass < 0.15:
            score -= 35.0
            reasons.append(f"dominant object only {mass:.0%} of frame")
        elif mass < 0.30:
            score -= 20.0
            reasons.append(f"dominant object only {mass:.0%} of frame")
    if spec.get("relationship"):
        reasons.insert(0, f"relationship: {spec['relationship']}")
    return {"score": max(0.0, min(100.0, score)), "reasons": reasons,
            "via": "static"}


def _dominant_mass(card_paths: list):
    """Fraction of the card owned by the strongest non-background color mass."""
    try:
        from collections import Counter

        from PIL import Image
        best = None
        for cp in card_paths[:3]:
            img = Image.open(cp).convert("RGB")
            img.thumbnail((180, 180))
            px = list(img.getdata())
            q = Counter((r // 32, g // 32, b // 32) for r, g, b in px)
            bg, bg_n = q.most_common(1)[0]
            # dominant object = largest non-background quantized bin
            for col, n in q.most_common(8):
                if col != bg:
                    frac = n / len(px)
                    if best is None or frac > best:
                        best = frac
                    break
        return best
    except Exception:
        return None


def one_second_vision(frame_path, visual_answer: str) -> dict:
    """§2 vision pass on a rendered frame (optional acceptance check)."""
    prompt = (
        "This frame is shown silently for ONE second. What single "
        "relationship should the viewer identify?\n"
        f"Intended relationship: {visual_answer}\n"
        'Answer strict JSON only: {"relationship_seen": "<short>", '
        '"matches_contract": true|false, "confidence": 0.0-1.0}'
    )
    res = vision_ask(frame_path, prompt)
    if not res or "matches_contract" not in res:
        return {"ok": None, "via": "unverified"}
    return {"ok": bool(res.get("matches_contract")), "via": "vision",
            "seen": str(res.get("relationship_seen", "")),
            "confidence": float(res.get("confidence", 0) or 0)}


# --------------------------------------------------- plan-level director ----

def _shot_fields(shot: dict) -> dict:
    return {
        "mode": str(shot.get("visual_mode", "")).upper(),
        "evidence": str(shot.get("evidence_type", "")).upper(),
        "motion": str(shot.get("motion_type", "")).upper(),
        "contract": shot.get("subject_contract"),
    }


def plan_review(story: dict, vp: dict, eplan: dict) -> dict:
    """Pre-render editorial pass over the plan (§1/§5/§12/§13/§17).

    Returns violations lists; empty critical list == plan is directable.
    """
    beats = {b.get("beat_id"): b for b in story.get("beats", [])}
    shots = []
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            s = dict(s)
            s["_beat"] = b.get("beat_id")
            shots.append(s)

    crit, warn = [], []

    # §1 visual argument per beat
    for bid, b in beats.items():
        for field in ("claim", "visual_question", "visual_answer"):
            if not str(b.get(field) or "").strip():
                warn.append(f"{bid}: missing {field} (§1 visual argument)")

    # §5 mode coverage / cinematic share
    modes = {}
    for s in shots:
        f = _shot_fields(s)
        if not f["mode"]:
            crit.append(f"{s['shot_id']}: no visual_mode (§5)")
        elif f["mode"] not in VISUAL_MODES:
            crit.append(f"{s['shot_id']}: unknown visual_mode {f['mode']}")
        else:
            modes[f["mode"]] = modes.get(f["mode"], 0) + 1
    n = max(1, len(shots))
    if modes.get("CINEMATIC", 0) / n > _CINEMATIC_SHARE_MAX:
        warn.append(f"CINEMATIC is the default: "
                    f"{modes.get('CINEMATIC', 0)}/{len(shots)} shots (§5)")

    # §12 evidence type vs factual claims
    numbered = re.compile(r"\d")
    for s in shots:
        f = _shot_fields(s)
        beat = beats.get(s.get("_beat"), {})
        claim = str(s.get("claim") or beat.get("claim") or "")
        factual = bool(numbered.search(claim)) or bool(beat.get("fact_ids"))
        if factual and f["evidence"] and f["evidence"] not in FACTUAL_CARRYING:
            justified = bool(s.get("evidence_justification"))
            (crit if not justified else warn).append(
                f"{s['shot_id']}: factual claim on {f['evidence']}"
                f"{' (justified)' if justified else ''} (§12)")
        if not f["evidence"]:
            warn.append(f"{s['shot_id']}: no evidence_type (§12)")

    # §13 motion
    cam_principal = 0
    for s in shots:
        f = _shot_fields(s)
        beat_fn = str(beats.get(s.get("_beat"), {}).get("function", "")).upper()
        if not f["motion"]:
            warn.append(f"{s['shot_id']}: no motion_type (§13)")
            continue
        if beat_fn in ("REVEAL", "EXPLANATION", "ESCALATION", "TWIST") \
                and f["motion"] not in EXPLANATORY_MOTION:
            warn.append(f"{s['shot_id']}: {beat_fn} beat uses {f['motion']} "
                        f"(prefer {'/'.join(EXPLANATORY_MOTION)}) (§13)")
        if f["motion"] == "CAMERA_MOTION":
            cam_principal += 1
    if cam_principal / n > _CINEMATIC_SHARE_MAX:
        warn.append(f"camera motion is the principal animation in "
                    f"{cam_principal}/{len(shots)} shots (§13)")

    # §8 contracts on hero/detail plate assets
    for s in shots:
        f = _shot_fields(s)
        if f["mode"] in ("CINEMATIC", "EVIDENCE", "DETAIL", "PAYOFF") \
                and not f["contract"]:
            warn.append(f"{s['shot_id']}: hero/detail asset has no "
                        f"subject_contract (§8)")

    # §17 payoff: last shot is a PAYOFF mode shot, nothing after it
    if shots:
        last = shots[-1]
        if str(last.get("visual_mode", "")).upper() not in ("PAYOFF",):
            warn.append("final shot is not PAYOFF mode (§17)")
    return {"critical": crit, "warnings": warn, "modes": modes,
            "shots": len(shots)}


# ------------------------------------------------ final review (§20/§21) ----

REVIEW_QUESTIONS = [
    "best visual representation of the narration",
    "main idea immediately obvious",
    "visual doing explanatory work",
    "nothing decorative without purpose",
    "composition appropriate to the beat",
    "no shot runs long without new information",
    "shot not too similar to the previous",
    "strongest visual element is the strongest",
    "ending provides a memorable payoff",
]


def creative_director_review(story: dict, vp: dict, eplan: dict,
                             plate_dir=None, sample_frames=None) -> dict:
    """§20 nine-question shot-by-shot review -> {verdict, rows, notes}.

    Static answers come from the plan; vision spot-checks (when a key
    exists) run on up to three rendered frames. A video can pass numeric
    gates and still fail here (§21).
    """
    beats = {b.get("beat_id"): b for b in story.get("beats", [])}
    beat_of = {}
    for b in vp.get("beats", []):
        for s in b.get("shots", []):
            beat_of[str(s["shot_id"])] = b.get("beat_id")
    shots = {str(s["shot_id"]): s for s in eplan.get("shots", [])}

    rows, fails = [], 0
    prev_mode = None
    prev_asset = None
    for sid in sorted(shots):
        s, f = shots[sid], _shot_fields(shots.get(sid, {}))
        vp_shot = next((x for b in vp.get("beats", [])
                        for x in b.get("shots", []) if x["shot_id"] == sid), {})
        beat = beats.get(beat_of.get(sid), {})
        evs = [str(e.get("kind", "")).lower() for e in s.get("events", [])]
        q, notes = {}, []

        # Q1 best representation: factual claims ride factual evidence
        claim = str(s.get("claim") or beat.get("claim") or "")
        factual = bool(re.search(r"\d", claim)) or bool(beat.get("fact_ids"))
        q[1] = not (factual and f["evidence"]
                    and f["evidence"] not in FACTUAL_CARRYING)
        if not q[1]:
            notes.append("factual claim on non-factual evidence type")

        # Q2 immediately obvious: declared relationship + contract status
        q[2] = bool(vp_shot.get("one_second", {}).get("relationship")) \
            or f["mode"] in ("CINEMATIC", "TYPOGRAPHY", "PAYOFF")
        if not q[2]:
            notes.append("no declared one-second relationship")

        # Q3 explanatory work: info motion or info events
        q[3] = f["motion"] in EXPLANATORY_MOTION \
            or ("stage_overlay" in evs or "number_pop" in evs
                or "highlight" in evs)
        if not q[3]:
            notes.append("camera motion only, no information motion")

        # Q4 decorative without purpose
        q[4] = f["evidence"] != "DECORATIVE" \
            or bool(vp_shot.get("evidence_justification"))
        if not q[4]:
            notes.append("decorative without justification")

        # Q5 composition vs beat (§7): cinematic -> minimal chrome
        chrome = str(s.get("chrome") or "none")
        q[5] = not (f["mode"] in ("CINEMATIC", "PAYOFF")
                    and chrome not in ("none", "chapter"))
        if not q[5]:
            notes.append(f"cinematic/payoff shot carries chrome={chrome}")

        # Q6 length without information (§16)
        dur = float(s.get("duration_s", 4.0))
        info_events = [e for e in evs if e in ("stage_overlay", "number_pop",
                                               "highlight", "callout")]
        gap_ok = dur <= 5.0 or bool(info_events) \
            or f["motion"] in EXPLANATORY_MOTION
        q[6] = gap_ok
        if not q[6]:
            notes.append(f"{dur:.1f}s with no information change")

        # Q7 similarity to previous shot
        asset = str(vp_shot.get("asset", ""))
        q[7] = not (f["mode"] == prev_mode and asset and asset == prev_asset)
        if not q[7]:
            notes.append("same mode and same plate as previous shot")
        prev_mode, prev_asset = f["mode"], asset

        # Q8 strongest element is strongest: mass check on the staged info
        # cards (same heuristic one_second_static uses). Full-bleed plates
        # are governed by subject contracts (Section 8/9) - the color-bin
        # mass heuristic misreads line-art/gradient/full-photo plates as a
        # "tiny subject" because it assumes subject-vs-flat-background.
        cards = [e["spec"]["png"] for e in s.get("events", [])
                 if e.get("kind") == "stage_overlay"
                 and e.get("spec", {}).get("png")]
        oc = one_second_static(vp_shot, cards) if cards else None
        q[8] = oc is None or oc.get("score", 100.0) >= 50.0
        if not q[8]:
            notes.append("one-second composition below 50: "
                         + "; ".join(oc.get("reasons", [])[:2]))

        shot_ok = all(q.values())
        fails += 0 if shot_ok else 1
        rows.append({"shot_id": sid, "beat": beat_of.get(sid), "mode":
                     f["mode"], "ok": shot_ok, "questions": q,
                     "notes": notes})

    # Q9 payoff ending
    q9 = True
    last = rows[-1] if rows else None
    last_beat_fn = str(beats.get(beat_of.get(last["shot_id"], ""),
                                 {}).get("function", "")).upper() \
        if last else ""
    if last_beat_fn != "PAYOFF":
        q9 = False
        fails += 1
    payoff_note = "" if q9 else "video does not end on a PAYOFF beat (§17)"

    # vision spot-checks: hero, one diagram, payoff (optional, §9)
    vision_notes = []
    if sample_frames:
        for sid, fpath in list(sample_frames.items())[:3]:
            vp_shot = next((x for b in vp.get("beats", [])
                            for x in b.get("shots", [])
                            if x["shot_id"] == sid), {})
            ans = (vp_shot.get("one_second") or {}).get("relationship")
            if not ans:
                continue
            r = one_second_vision(fpath, ans)
            if r.get("via") == "vision" and r["ok"] is False:
                vision_notes.append(f"{sid}: frame reads as "
                                    f"'{r.get('seen', '?')}' not '{ans}'")

    verdict = "PASS" if fails == 0 and not vision_notes else "FAIL"
    return {"verdict": verdict, "failed_shots": fails, "rows": rows,
            "questions": REVIEW_QUESTIONS, "payoff_note": payoff_note,
            "vision_notes": vision_notes}
