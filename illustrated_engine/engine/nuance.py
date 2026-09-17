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

from engine.facts import SUPERLATIVE_RE

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


# --- V12 P1 — evidence-support implication checks (Jade_todo_v12 §P1) -------
# Upgrade from "is the statement true?" to "does the visual + narration
# imply MORE than the evidence supports?" Ten deterministic checks over
# each claim's carrier sentences (and, when a plan is supplied, the visual
# grammar the beat declares). Findings carry a suggested wording; silent
# narration rewriting is deliberately NOT done — same policy as above.

_CAUSAL_RE = re.compile(
    r"\b(because|caus\w+|makes?|due to|leads? to|led to|results? in|"
    r"which is why|driv(?:es|en)|so that)\b", re.I)
_CERTAIN_RE = re.compile(
    r"\b(definitely|certainly|undoubtedly|proves?|proven|guaranteed|"
    r"without question)\b", re.I)
_PERMANENCE_RE = re.compile(
    r"\b(always|never|forever|to this day|still today|ever since)\b", re.I)
_UNIFORM_RE = re.compile(
    r"\b(everywhere|uniformly|uniform|identical(?:ly)?|the same everywhere|"
    r"across the (?:globe|planet|world)|no matter where)\b", re.I)
_GLOBALITY_RE = re.compile(
    r"\b(the (?:world|planet|globe)|global\w*)\b", re.I)
_AVERAGE_RE = re.compile(
    r"\b(on average|averaged|global mean|mean temperature|typical(?:ly)?)\b",
    re.I)
_STRONG_QUANT_RE = re.compile(
    r"\b(all|every|everyone|everything|none|nothing|no)\b", re.I)
_FRACTION_RE = re.compile(
    r"\b(?:\d+(?:[.,]\d+)?\s?(?:%|percent)(?=\W|$)|one fifth|one quarter|"
    r"one third|half of|most of|fifth\b)", re.I)
_PERSPECTIVE_RE = re.compile(
    r"\b(appear\w*|seem\w*|looks? like|as seen|as measured|relative to|"
    r"frame of reference|observer)\b", re.I)
_CHANGE_RE = re.compile(
    r"\b(cool\w*|warm\w*|heat\w*|rose|fell|drop\w*|shift\w*|change\w*|"
    r"affect\w*|scatter\w*)\b", re.I)
_KNOWLEDGE_ASIDE_RE = re.compile(
    r"\b(no|none|nobody|nothing)\s+(one|body|could|knew|knows|connect\w*|"
    r"underst\w*|said|says)\b", re.I)
_SUPERLATIVE_SKIP_RE = re.compile(
    r"\b(most|only)\s+(a|an|the|people|of\s+us|of\s+the|folks)\b|"
    r"\b(recorded|documented|in history)\b", re.I)
_EXTRACTION_RE = re.compile(
    r"\b(strip\w*|pull\w* out|remov\w*|extract\w*|draw\w* out|recov\w*)\s+"
    r"(?:out\s+)?(?:the\s+)?(nitrogen|phosphorus|potassium|nutrient\w*|"
    r"sugars?)\b", re.I)
_SUPERLATIVE_HEDGE_RE = re.compile(
    r"\b(about|roughly|approximately|around|nearly|estimated|some|"
    r"a range|varies|at least|just over|just under)\b", re.I)


def _tokens(text: str) -> set:
    """Content tokens for claim-subject overlap checks."""
    return {t for t in re.findall(r"[a-z0-9]+", str(text or "").lower())
            if len(t) > 3}


def _sentences(text: str) -> list:
    """Split narration into sentences (same split as semantic_qa)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", str(text or ""))
            if s.strip()]


def _claim_context(claim: dict) -> str:
    """All evidence-side wording for a claim: claim + definition + note."""
    return " ".join(str(claim.get(k) or "") for k in
                    ("claim", "definition", "notes")) + " " + str(
        (claim.get("nuance") or {}).get("note") or "")


def _denominator_words(claim: dict) -> set:
    """Content words of the claim's OWN comparison denominator — the noun
    phrase after the fraction ('one fifth OF Earth's unfrozen fresh
    surface water'). The narration's fraction must keep these scope words.
    """
    m = re.search(
        r"\b(?:of|per)\s+((?:[a-z-]+\s+){0,4})(Earth|earth|the|all|its|"
        r"North|South)?", str(claim.get("claim") or ""))
    tail = str(claim.get("claim") or "").lower()
    m2 = re.search(r"\b(?:fifth|half|quarter|third|%|percent)\s*of\s+([^,;.]+)",
                   tail)
    words = set()
    if m2:
        words |= {w for w in re.findall(r"[a-z-]+", m2.group(1))
                  if w not in {"the", "a", "an", "all", "earth", "earth's",
                               "its", "on", "in", "and", "more", "than"}}
    return {w for w in words if len(w) > 2}


def evidence_support(story: dict, facts: dict, plan: dict | None = None) -> dict:
    """Implication QA: does visual + narration imply more than the
    evidence supports? Ten checks per claim-carrier sentence:

    object, number, timeframe, geography, population/scope, causal
    strength, certainty, perspective, comparison denominator, superlative
    qualification. Plan-aware: a contested claim drawn with a definitive
    visual mechanism (planv9 should already downgrade it) is flagged.
    """
    beats = {str(b.get("beat_id")): b for b in (story.get("beats") or [])}
    findings = []
    rows = []
    for claim in facts.get("claims", []):
        cid = claim.get("id")
        cls, _basis = classify_claim(claim)
        ctx = _claim_context(claim)
        denom = _denominator_words(claim)
        contested = cls in CONTESTED
        row = {"id": cid, "classification": cls, "findings": []}
        for bid in claim.get("beats", []) or []:
            b = beats.get(str(bid))
            if not b:
                continue
            for sent in _sentences(str(b.get("narration") or "")):
                low = sent.lower()
                qualified = bool(_QUALIFIER_RE.search(sent))
                # 1 object / 9 comparison denominator — a fraction whose
                # noun phrase drops the claim's own denominator words
                if _FRACTION_RE.search(sent) and len(denom) >= 2:
                    missing = {w for w in denom if w not in low}
                    if len(missing) >= 2:
                        row["findings"].append({
                            "rule": "denominator_or_object_unqualified",
                            "beat_id": str(bid), "sentence": sent[:140],
                            "severity": "WARN",
                            "missing_qualifiers": sorted(missing)[:4],
                            "suggested_wording": "about ... of Earth's "
                                                + "/".join(sorted(denom)[:4]),
                            "note": "the evidence supports the fraction only "
                                    "for the qualified denominator"})
                # 2 number — a figure the claim never states (only for
                # sentences that are really about THIS claim)
                if len(_tokens(sent) & _tokens(
                        str(claim.get("claim") or ""))) >= 3:
                    for m in re.findall(
                            r"\d+(?:[.,]\d+)?\s?(?:%|percent|metres?|meters?|"
                            r"km|km\u00b2|degrees?|°C|°F|tonnes?|million|"
                            r"billion|years?)", sent, re.I):
                        num = re.sub(r"[^0-9.,]", "", m).strip(".,")
                        if (num and num not in ctx.replace(",", "")
                                and num not in ctx):
                            row["findings"].append({
                                "rule": "number_beyond_evidence",
                                "beat_id": str(bid), "figure": m,
                                "sentence": sent[:140], "severity": "WARN",
                                "note": "figure does not appear in the "
                                        "claim's evidence wording"})
                            break
                # 3 timeframe — permanence implied past a dated claim
                if _PERMANENCE_RE.search(sent) and re.search(
                        r"\b(1[0-9]{3}|20[0-9]{2}|million years|1815|1816)\b",
                        ctx):
                    row["findings"].append({
                        "rule": "timeframe_unbounded", "beat_id": str(bid),
                        "sentence": sent[:140], "severity": "WARN",
                        "note": "evidence is dated/bounded; narration implies "
                                "permanence"})
                # 4 geography — a uniform field implied by a global-mean
                # claim ("the world cooled" without 'on average'), or an
                # explicit everywhere/uniform marker
                if _UNIFORM_RE.search(sent) or (
                        _GLOBALITY_RE.search(sent) and _CHANGE_RE.search(sent)
                        and not _AVERAGE_RE.search(sent)
                        and re.search(r"varies|global.mean|reconstruction",
                                      ctx, re.I)):
                    row["findings"].append({
                        "rule": "geographic_uniformity", "beat_id": str(bid),
                        "sentence": sent[:140], "severity": "WARN",
                        "suggested_wording": "on average, ...",
                        "note": "a global mean is not a uniform field — add "
                                "the average/qualifier or vary the visual"})
                # 5 population/scope — quantifier strengthened past the
                # evidence, about the claim's SUBJECT (spatial/temporal
                # extents and knowledge asides are not population claims)
                if not _KNOWLEDGE_ASIDE_RE.search(sent):
                    for m in _STRONG_QUANT_RE.finditer(sent):
                        word = m.group(0).lower()
                        rest = sent[m.end():m.end() + 24]
                        if re.match(r"\s+of\s+[A-Z]", rest) or re.match(
                                r"\s+(summer|winter|spring|fall|autumn|year|"
                                r"day|time|history)", rest, re.I):
                            continue  # spatial extent / temporal cover
                        # "one fifth of ALL the ..." — the fraction phrase's
                        # own totality, not a population claim
                        if re.search(r"(?:fifth|half|quarter|third|%|percent)"
                                     r"\s*of\s*$", sent[:m.start()], re.I):
                            continue
                        if re.search(r"\b(most|many|some|roughly|about)\b",
                                     ctx, re.I) and len(
                                _tokens(sent) & _tokens(
                                    str(claim.get("claim") or ""))) >= 2:
                            row["findings"].append({
                                "rule": "quantifier_strengthened",
                                "beat_id": str(bid), "quantifier": word,
                                "sentence": sent[:140], "severity": "WARN",
                                "note": "evidence supports a weaker "
                                        "quantifier — match the claim's "
                                        "wording"})
                        break
                # 6 causal strength — UNQUALIFIED asserted causation for a
                # contested claim (a hedged frame — 'the current picture:',
                # 'one leading idea:' — keeps the causal verb honest)
                if contested and _CAUSAL_RE.search(sent) and not qualified:
                    row["findings"].append({
                        "rule": "causal_overreach", "beat_id": str(bid),
                        "classification": cls, "sentence": sent[:140],
                        "severity": "FAIL",
                        "suggested_wording": _SUGGESTED.get(cls, "").format(
                            claim=str(claim.get("claim", "")).rstrip(".")
                            .lower()),
                        "note": "asserted causation beyond the claim's "
                                "classification"})
                # distinct-process conflation (directive autumn fixture):
                # a contested claim whose carrier sentence fuses the claim's
                # process with a nutrient-extraction action
                if contested and _EXTRACTION_RE.search(sent):
                    row["findings"].append({
                        "rule": "process_conflation", "beat_id": str(bid),
                        "sentence": sent[:140], "severity": "WARN",
                        "note": "represent the two processes as related but "
                                "DISTINCT — the pigment is not the agent of "
                                "nutrient resorption",
                        "suggested_wording": "split into two statements: the "
                                             "pigment's role, then the tree's "
                                             "nutrient resorption"})
                # 7 certainty — certainty adverbs on contested claims
                if contested and _CERTAIN_RE.search(sent):
                    row["findings"].append({
                        "rule": "certainty_inflated", "beat_id": str(bid),
                        "classification": cls, "sentence": sent[:140],
                        "severity": "FAIL",
                        "note": "certainty adverb on a contested claim"})
                # 8 perspective — perception predicate presented as mechanism
                if contested and _PERSPECTIVE_RE.search(sent) and (
                        _CAUSAL_RE.search(sent)):
                    row["findings"].append({
                        "rule": "perspective_dropped", "beat_id": str(bid),
                        "sentence": sent[:140], "severity": "WARN",
                        "note": "perspective-dependent wording fused into a "
                                "causal assertion"})
                # 10 superlative qualification — hedged evidence, unhedged
                # narration superlative (R1 covers claim COVERAGE; this
                # covers the missing hedge)
                sup = SUPERLATIVE_RE.search(sent)
                if sup and not _SUPERLATIVE_SKIP_RE.search(sent) \
                        and re.search(r"\d", sent) \
                        and re.search(r"varies|range|roughly|about", ctx,
                                      re.I) \
                        and not _SUPERLATIVE_HEDGE_RE.search(sent):
                    row["findings"].append({
                        "rule": "superlative_unhedged", "beat_id": str(bid),
                        "sentence": sent[:140], "severity": "WARN",
                        "note": "evidence states a range; narration states a "
                                "bare superlative"})
        # visual side — contested claim drawn as a definitive mechanism
        if plan is not None and contested:
            bm = ((plan.get("beat_model") or {}).get("beats") or {})
            for bid in claim.get("beats", []) or []:
                t = str((bm.get(str(bid)) or {}).get(
                    "state_transformation") or "")
                if t in ("cause_to_consequence", "mechanism_visible",
                         "object_transforms"):
                    row["findings"].append({
                        "rule": "contested_causation_drawn_definitive",
                        "beat_id": str(bid), "transformation": t,
                        "classification": cls, "severity": "FAIL",
                        "note": "contested causation drawn as definitive "
                                "mechanism arrows — use hypothesis_branches "
                                "or qualify (planv9 downgrades this)"})
        if row["findings"]:
            findings.extend({"claim_id": cid, **f} for f in row["findings"])
        rows.append(row)
    # dedupe: two claims sharing a beat must not double-report one sentence
    seen, deduped = set(), []
    for f in findings:
        key = (f["rule"], f.get("beat_id"), f.get("sentence"))
        if key not in seen:
            seen.add(key)
            deduped.append(f)
    findings = deduped
    n_fail = sum(1 for f in findings if f["severity"] == "FAIL")
    counts = {}
    for f in findings:
        counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    return {"claims": rows, "findings": findings, "rule_counts": counts,
            "n_findings": len(findings), "n_fail": n_fail,
            "evidence_support_pass": n_fail == 0}


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
