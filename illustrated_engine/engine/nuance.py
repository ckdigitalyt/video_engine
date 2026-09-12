"""V11 P1 §6 — scientific nuance QA (Jade_todo_v11).

Upgrade of the semantic factual QA: for every scientific claim, classify
the strength of the science —

    ESTABLISHED            textbook/settled, safe to assert
    STRONG_CONSENSUS       broad agreement, may be asserted
    SUPPORTED_BUT_COMPLEX  real evidence, mechanism/scope genuinely complex
    ACTIVE_DEBATE          live disagreement in the literature
    MODEL_DEPENDENT        conclusion depends on the model/simulation used
    UNCERTAIN              weak/unsettled evidence

and forbid CONTESTED classes (SUPPORTED_BUT_COMPLEX, ACTIVE_DEBATE,
MODEL_DEPENDENT, UNCERTAIN) from being narrated as settled facts: the
beats carrying the claim must qualify the wording ("current research
suggests", "tends to", "one explanation", ...). Source existence is NOT
sufficient — a source for the general concept does not license a
settled-fact assertion of a contested mechanism (directive's ice
example: premelting/molecular mobility + temperature/pressure/speed
dependence + newer self-lubrication proposals ≠ "skate melts ice").

Classification order: authored facts.json `nuance.classification` wins
(validated); otherwise a conservative lexicon over the claim wording.
The report carries a deterministic suggested qualified wording for every
contested claim so the author can adopt it; silent narration rewriting
is deliberately NOT done (narration/captions are authored artifacts —
the gate is the enforcement).
"""
from __future__ import annotations

import re

CLASSES = ("ESTABLISHED", "STRONG_CONSENSUS", "SUPPORTED_BUT_COMPLEX",
           "ACTIVE_DEBATE", "MODEL_DEPENDENT", "UNCERTAIN")
CONTESTED = {"SUPPORTED_BUT_COMPLEX", "ACTIVE_DEBATE", "MODEL_DEPENDENT",
             "UNCERTAIN"}

# contested-mechanism markers -> (classification, weight)
_DEBATE_RE = re.compile(
    r"\b(active(?:ly)? debate[d]?|controvers\w+|disagree\w*|remains? "
    r"(?:unsettled|unresolved|open)|open question)\b", re.I)
_MODEL_RE = re.compile(
    r"\b(model[- ]dependent|simulation(?:s)? suggest|depends? on the "
    r"(?:model|simulation)|in (?:some )?models?|under (?:this|that) model)\b",
    re.I)
_COMPLEX_RE = re.compile(
    r"\b(propos(?:ed|es|al)|hypothes\w+|suggest\w*|emerging|newer|"
    r"not fully understood|not (?:yet )?(?:settled|explained)|unclear|"
    r"one explanation|a leading explanation|current (?:research|picture|"
    r"understanding)|recent(?:ly)? (?:work|studies)|self-lubrication|"
    r"mechanisms? (?:are|remain) \w*debate\w*|complex dependence|"
    r"depends? on (?:temperature|pressure|speed))\b", re.I)

# narration-side qualification lexicon (what counts as "qualified wording")
_QUALIFIER_RE = re.compile(
    r"\b(current (?:research|picture|understanding|science|thinking)|"
    r"the real story|best explanation|leading explanation|one explanation|"
    r"suggest\w*|appear\w*|tend(?:s|ing)? to|largely|mostly|generally|"
    r"thought to|believed to|propos\w+|debate\w*|not fully|may |can |"
    r"might |hypothes\w+|models? (?:suggest|indicate)|depending on|"
    r"as far as we know|so far as researchers|evidence (?:points|suggests)|"
    r"research (?:points|suggests|emphas\w+)|still (?:open|debated|being "
    r"worked out)|complex)\b", re.I)

_SUGGESTED = {
    "SUPPORTED_BUT_COMPLEX": "By the current picture, {claim}",
    "ACTIVE_DEBATE": "Researchers still debate the details, but {claim}",
    "MODEL_DEPENDENT": "In the leading models, {claim}",
    "UNCERTAIN": "The evidence is still thin, but {claim}",
}


def _words(text: str) -> set:
    return {w for w in re.findall(r"[a-z-]+", str(text or "").lower()) if w}


def _lexicon_class(text: str) -> str | None:
    t = str(text or "")
    if _DEBATE_RE.search(t):
        return "ACTIVE_DEBATE"
    if _MODEL_RE.search(t):
        return "MODEL_DEPENDENT"
    if _COMPLEX_RE.search(t):
        return "SUPPORTED_BUT_COMPLEX"
    return None


def classify_claim(claim: dict) -> tuple:
    """-> (classification, basis). Authored facts.json nuance wins."""
    nuance = claim.get("nuance") or {}
    authored = str(nuance.get("classification") or "").upper()
    if authored in CLASSES:
        return authored, "authored"
    for src in (claim.get("definition"), claim.get("claim"),
                claim.get("notes")):
        got = _lexicon_class(src)
        if got:
            return got, "lexicon"
    if claim.get("verified") and claim.get("authoritative_source"):
        return "ESTABLISHED", "verified_source_default"
    return "UNCERTAIN", "no_verification_default"


def _beats_for(claim: dict, beats: dict) -> list:
    out = []
    for bid in claim.get("beats", []) or []:
        b = beats.get(str(bid))
        if b:
            out.append(b)
    return out


def check_story(story: dict, facts: dict) -> dict:
    """Classify every claim; contested claims narrated flat -> FAIL."""
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    rows, findings = [], []
    counts = {c: 0 for c in CLASSES}
    for claim in facts.get("claims", []):
        cls, basis = classify_claim(claim)
        counts[cls] += 1
        row = {"id": claim.get("id"), "classification": cls, "basis": basis,
               "beats": [str(x) for x in (claim.get("beats") or [])],
               "qualified": True, "findings": []}
        if cls in CONTESTED:
            carrier_beats = _beats_for(claim, beats)
            if not carrier_beats:
                row["qualified"] = False
                findings.append({
                    "rule": "contested_claim_no_beat_qualifier",
                    "claim_id": claim.get("id"), "classification": cls,
                    "severity": "FAIL",
                    "note": "contested claim has carrier beats, none found in story"})
            for b in carrier_beats:
                narration = str(b.get("narration") or "")
                if _QUALIFIER_RE.search(narration):
                    continue
                row["qualified"] = False
                findings.append({
                    "rule": "contested_mechanism_as_settled_fact",
                    "claim_id": claim.get("id"), "classification": cls,
                    "beat_id": b.get("beat_id"), "severity": "FAIL",
                    "sentence": narration[:140],
                    "suggested_wording": _SUGGESTED.get(cls, "").format(
                        claim=str(claim.get("claim", "")).rstrip(".").lower()),
                    "note": ("source existence is not sufficient — qualify the "
                             "wording or upgrade the claim's evidence")})
        rows.append(row)
    n_fail = sum(1 for f in findings if f.get("severity") == "FAIL")
    return {"claims": rows, "counts": counts, "findings": findings,
            "contested_present": sum(counts[c] for c in CONTESTED),
            "nuance_pass": n_fail == 0}


def run(story_dir) -> dict:
    """Driver over a story directory -> nuance report block."""
    import json
    from pathlib import Path
    from engine.facts import load_facts
    story_dir = Path(story_dir)
    story = json.loads((story_dir / "story.json").read_text())
    facts = load_facts(story_dir)
    res = check_story(story, facts)
    res["story_id"] = story.get("story_id", story_dir.name)
    return res


def write_report(res: dict, qa_dir) -> Path:
    import json
    from pathlib import Path as _Path
    qa_dir = _Path(qa_dir)
    qa_dir.mkdir(parents=True, exist_ok=True)
    p = qa_dir / f"nuance_{res.get('story_id', 'story')}.json"
    p.write_text(json.dumps(res, indent=1) + "\n")
    return p
