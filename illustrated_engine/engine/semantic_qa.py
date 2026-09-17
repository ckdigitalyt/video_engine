"""V7 P0-8 — semantic factual verification layer over facts.py (V4 §1).

facts.py (V4) guarantees: every superlative/record claim has a facts.json
entry with definition, date, source.  V7 raises the bar — the EXACT
narration wording is verified, not just the general concept:

  R1 SUPERLATIVE_UNQUALIFIED  superlative whose beat lacks a verified claim
                              entry, or lacks an in-video defining qualifier
  R2 QUANTITY_UNQUALIFIED     number+unit assertion with no variant/context
                              qualifier in its sentence and no claim entry
                              ("A 747 weighs 400 tonnes" without "loaded" /
                              "up to" / variant is rejected)
  R3 PERSPECTIVE_REQUIRED     perspective-sensitive predicates ("time runs
                              slower", "appears") without an observer
                              qualifier ("as seen by", "as measured by")
  R4 EXACT_WORDING            DeepSeek verifies each claim entry against the
                              narration wording: a source supporting the
                              general concept is insufficient if the exact
                              narration overstates it

Deterministic rules run always; R4 runs when a judge key (GEMINI_API_KEY or
OPENROUTER_API_KEY) is present and reports skipped honestly otherwise.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from engine.facts import SUPERLATIVE_RE, load_facts
from engine.director import _env_key, text_ask

_QUALIFIER_RE = re.compile(
    r"\b(loaded|unloaded|up to|at least|at most|about|roughly|approximately|"
    r"around|nearly|estimated|measured|typical|average|variant|version|model|"
    r"sea level|as of|on record|per year|per second|at rest|full.thrust|dry|"
    r"maximum|takeoff|cruis\w+|known|recorded|documented|source[sd]?)\b", re.I)

_PERSPECTIVE_RE = re.compile(
    r"\b(time (?:runs|moves|passes|flows|goes) (?:slower|faster)|"
    r"runs? (?:slower|faster)|passes? (?:slower|faster)|"
    r"ticks? (?:slower|faster)|age[sd]? (?:slower|faster)|"
    r"appear(?:s|ed)?(?: to)?|seem(?:s|ed)? to|"
    r"looks? (?:like|as if)|observ\w+|perceiv\w+)\b", re.I)

_OBSERVER_RE = re.compile(
    r"\b(as seen (?:by|from)|from (?:the|a|our|your) (?:distant|far|outside|near)|"
    r"to (?:a|the|any) (?:distant|far|outside) (?:observer|clock|watcher)|"
    r"as measured by|relative to|compared to|distant observer|far away|"
    r"from outside|to you|for you|on the ground|farther from|closer to|"
    r"for (?:a|the) (?:distant|far|outside)|than yours|than its twin|"
    r"than (?:a|the|one) (?:far|distant|outside))\b", re.I)

_UNIT_RE = re.compile(
    r"\b(\d+(?:[.,]\d+)?)\s*(tonnes?|tons?|kilotons?|kg|kilograms?|"
    r"kilometres?|kilometers?|km|metres?|meters?|miles?|mph|km/h|"
    r"\u00b0C|\u00b0F|celsius|fahrenheit|kelvin|years?|days?|hours?|minutes?|"
    r"seconds?|ms|milliseconds?|billion|million|trillion|%|percent|"
    r"watts?|kilowatts?|megawatts?|gigawatts?|litres?|liters?|gallons?|"
    r"degrees?|times)\b\.?", re.I)

_STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "for", "and", "or",
         "is", "are", "was", "were", "it", "its"}


def _tokens(text: str) -> set:
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower()) if t not in _STOP}


def _overlap(a: str, b: str, min_hits: int = 3) -> bool:
    return len(_tokens(a) & _tokens(b)) >= min_hits


def _sentences(text: str) -> list:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or "")) if s.strip()]


# ------------------------------------------------------------- deterministic
def check_story(story: dict, facts: dict) -> dict:
    findings = []
    claims_by_beat: dict = {}
    for c in facts.get("claims", []):
        for bid in c.get("beats", []) or []:
            claims_by_beat.setdefault(str(bid), []).append(c)

    for b in story.get("beats", []):
        bid = str(b.get("beat_id"))
        sents = _sentences(b.get("narration"))
        claims = claims_by_beat.get(bid, [])
        prev = ""
        for sent in sents:
            # R1 — superlatives need claim coverage AND an in-video qualifier
            for m in SUPERLATIVE_RE.finditer(sent):
                covered = any(_overlap(sent, c.get("claim", ""), 2) or
                              str(bid) in [str(x) for x in c.get("beats", [])]
                              for c in claims)
                qualified = bool(_QUALIFIER_RE.search(sent)) or any(
                    c.get("definition") and _overlap(sent, c["definition"], 2)
                    for c in claims)
                if covered and qualified:
                    continue
                findings.append({
                    "rule": "R1_superlative_unqualified", "beat_id": bid,
                    "match": m.group(0).lower(), "sentence": sent,
                    "severity": "FAIL" if not covered else "WARN",
                    "note": "needs verified facts.json claim + in-video defining qualifier"})
            # R2 — quantities need context or claim coverage
            for m in _UNIT_RE.finditer(sent):
                if _QUALIFIER_RE.search(sent) or claims:
                    continue
                findings.append({
                    "rule": "R2_quantity_unqualified", "beat_id": bid,
                    "match": m.group(0), "sentence": sent, "severity": "FAIL",
                    "note": "state the variant/context (loaded? at sea level? up to?) "
                            "or add a facts.json claim"})
            # R3 — perspective-sensitive predicates need an observer
            pm = _PERSPECTIVE_RE.search(sent)
            if pm and not _OBSERVER_RE.search(sent) and not _OBSERVER_RE.search(prev):
                findings.append({
                    "rule": "R3_perspective_required", "beat_id": bid,
                    "match": pm.group(0), "sentence": sent, "severity": "FAIL",
                    "note": "whose clock/perspective? add 'as seen by', 'as measured by', ..."})
            prev = sent
    counts = {"FAIL": 0, "WARN": 0}
    for f in findings:
        counts[f["severity"]] += 1
    return {"findings": findings, "counts": counts,
            "deterministic_pass": counts["FAIL"] == 0}


# ------------------------------------------------------------------- R4 (LLM)
def semantic_verify(story: dict, facts: dict) -> dict:
    if not (_env_key("GEMINI_API_KEY") or _env_key("OPENROUTER_API_KEY")):
        return {"status": "skipped", "reason": "no judge key (GEMINI/OPENROUTER)"}
    claims = facts.get("claims", [])
    if not claims:
        return {"status": "skipped", "reason": "no facts.json claims"}
    beats_txt = "\n".join(f"[{b.get('beat_id')}] {b.get('narration')}"
                          for b in story.get("beats", []))
    prompt = (
        "You are a strict fact-checker for a short science/history video.\n"
        "Below are the narration beats and the verified claim entries with their "
        "authoritative sources.\n"
        "For EACH claim entry, decide whether the EXACT narration wording is "
        "supported: a source supporting the general concept is NOT enough if the "
        "narration overstates it (wrong scope, missing qualifier, wrong observer "
        "perspective, inflated number, undefined superlative).\n"
        "Reply with ONLY a JSON array: "
        '[{"id": "<claim id>", "verdict": "supported|overstated|unsupported", '
        '"reason": "<one line>"}]\n\n'
        f"NARRATION BEATS:\n{beats_txt}\n\nCLAIM ENTRIES:\n"
        f"{json.dumps(claims, indent=1)}")
    content = text_ask(prompt, temperature=0.1, max_tokens=2000)
    if content is None:
        return {"status": "error", "reason": "all judge providers failed"}
    try:
        m = re.search(r"\[.*\]", content, re.S)
        verdicts = json.loads(m.group(0)) if m else []
    except Exception as e:  # parse failure must not silently pass
        return {"status": "error", "reason": str(e)[:200]}
    overstated = [v for v in verdicts if str(v.get("verdict", "")).lower() != "supported"]
    return {"status": "ok", "verdicts": verdicts,
            "n_claims": len(claims), "n_overstated": len(overstated),
            "exact_wording_pass": len(overstated) == 0}


# -------------------------------------------------------------------- driver
def verify(story_dir: Path) -> dict:
    story_dir = Path(story_dir)
    story = json.loads((story_dir / "story.json").read_text())
    facts = load_facts(story_dir)
    det = check_story(story, facts)
    r4 = semantic_verify(story, facts)
    # V11 P1 §6 — scientific nuance: contested mechanisms must not be
    # presented as settled facts (classification + wording-qualification
    # gate; engine/nuance.py).
    from engine import nuance as _nuance
    nun = _nuance.check_story(story, facts)
    nun["story_id"] = story.get("story_id", story_dir.name)
    _nuance.write_report(nun, Path("build/qa"))
    # V12 P1 — evidence-support implication QA: does visual + narration
    # imply MORE than the evidence supports? Plan-aware when the planv9
    # snapshot exists (visual-side contested-mechanism check).
    plan = None
    _snap = Path("build") / f"edit_plan_{story.get('story_id', story_dir.name)}.json"
    if _snap.exists():
        try:
            plan = json.loads(_snap.read_text())
        except Exception:
            plan = None
    ev = _nuance.evidence_support(story, facts, plan)
    gates = {
        "deterministic_rules": det["deterministic_pass"],
        "exact_wording": r4.get("exact_wording_pass") if r4.get("status") == "ok" else None,
        "nuance_qualification": nun["nuance_pass"],
        # reported gate: FAIL-severity implication findings (causal
        # overreach, inflated certainty, contested-drawn-definitive) block;
        # WARN findings are honest advisory findings with suggested wording
        "evidence_support": ev["evidence_support_pass"],
    }
    required = [gates["deterministic_rules"], gates["nuance_qualification"],
                gates["evidence_support"]]
    if gates["exact_wording"] is not None:
        required.append(gates["exact_wording"])
    return {"story_id": story.get("story_id", story_dir.name),
            "deterministic": det, "judges": r4,
            "nuance": {k: nun[k] for k in ("counts", "contested_present",
                                            "nuance_pass")},
            "evidence_support": {k: ev[k] for k in (
                "n_findings", "n_fail", "rule_counts",
                "evidence_support_pass")},
            "evidence_support_findings": ev["findings"],
            "gates": gates,
            "SEMANTIC_PASS": all(required)}


def write_report(result: dict, qa_dir: Path) -> Path:
    qa_dir = Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    p = qa_dir / f"semqa_{result['story_id']}.json"
    p.write_text(json.dumps(result, indent=1))
    return p
