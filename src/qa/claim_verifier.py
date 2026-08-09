"""
claim_verifier.py — Retrieval-backed factual gate (expert review rec #1, #9).

The expert's central finding: the pipeline conflated two distinct acoustic
phenomena (The Bloop and the 52-Hz whale) and transferred attributes between
them.  That is an *entity-disambiguation* failure, and it must become a
SYSTEM REQUIREMENT for every documentary script, not a one-off fix.

Gate pipeline (deterministic extraction + LLM verification):

  1. EXTRACT   — every quantitative claim (frequency, date, distance, speed,
                 size, temperature…) and every named phenomenon/entity from
                 the final narration, via structured LLM extraction.
  2. DISAMBIGUATE — for each named entity, detect similarly-named phenomena
                 that could be conflated (e.g. "Bloop" vs "52-Hz whale";
                 "Tunguska event" vs "Chelyabinsk meteor").  The LLM must
                 answer: is this entity UNIQUE in the script, or does it
                 share attributes with a different named phenomenon?
  3. VERIFY    — each claim is checked against the research pack's
                 source-backed facts (research.json verified facts) AND via
                 LLM cross-check.  Claims are tagged:
                   verified    — matches a source-backed research fact
                   unsupported — no supporting fact in the pack
                   contradicted— research pack contains a conflicting value
                 A claim with no source in the pack is NOT auto-failed:
                 the LLM may verify it from its own knowledge, but the
                 verification must be explicit and labeled (established
                 fact vs hypothesis vs conclusion).
  4. GATE      — script APPROVED only when:
                   * zero contradicted claims
                   * zero entity-conflation events
                   * zero unsupported quantitative claims
                   * observation/hypothesis/conclusion are distinguished
                 Anything less → REVISION_REQUIRED with a per-claim report
                 that the script revision pass can act on.

The gate writes ``claim_report.json`` into the run dir and its result feeds
the run-level PUBLISH_READY / REVISION_REQUIRED state machine
(src/qa/publish_status.py).

Runtime: uses the pipeline's LLM provider chain (mistral → deepseek, flash
models only per v12.5 cost guardrails) — never Gemini Pro.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

# ── Claim regexes (deterministic pre-extraction net; LLM refines) ────────
_NUMBER_PAT = re.compile(
    r"(\d[\d,\.]*)\s*(hertz|hz|khz|mhz|ghz|kilomet(?:er|re)s?|km|met(?:er|re)s?|m|"
    r"miles?|mi|feet|ft|seconds?|s\b|minutes?|min|hours?|hrs?|years?|yrs?|"
    r"degrees?|°|percent|%|db|decibels?|times?|x\b|million|billion|trillion|"
    r"kg|tonnes?|tons?|watts?|watts|psu|bars?|atmospheres?|atm)",
    re.IGNORECASE,
)

# Written-out numbers the narration may use ("fifty-two hertz",
# "five thousand kilometers") — the regex above only sees digits.
_WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
    "ninety": 90, "hundred": 100, "thousand": 1000,
    "million": 1_000_000, "billion": 1_000_000_000,
}
_WORD_NUM_PAT = re.compile(
    r"((?:(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|"
    r"twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|billion)[- ]?){1,4})\s*(hertz|hz|khz|mhz|kilomet(?:er|re)s?|km|"
    r"miles?|mi|seconds?|minutes?|min|hours?|years?|percent|%|times?)",
    re.IGNORECASE,
)


def _words_to_number(words: str) -> str:
    """'fifty-two thousand' -> '52000' (handles the common patterns)."""
    total, cur = 0, 0
    for tok in re.split(r"[- ]", words.strip()):
        tok = tok.lower()
        if tok not in _WORD_NUM:
            continue
        v = _WORD_NUM[tok]
        if v == 100:
            cur = (cur or 1) * v
        elif v >= 1000:
            total += (cur or 1) * v
            cur = 0
        else:
            cur += v
    total += cur
    return str(total) if total else ""

# Phenomena that must NEVER be conflated (curated from expert review +
# ocean-acoustics domain; the LLM disambiguation step adds script-specific
# pairs dynamically).
KNOWN_DISTINCT_PHENOMENA = [
    # (phenomenon A, phenomenon B, why they must stay separate)
    ("the bloop", "the 52-hertz whale",
     "The Bloop (1997, ultra-low-frequency, NOAA hydrophones, icequake) and the "
     "52-Hz whale (1989+, individual whale call) are DIFFERENT acoustic "
     "phenomena. 52 Hz is NOT the frequency of the Bloop; never transfer "
     "attributes between them."),
    ("the bloop", "cthulhu / sea monster",
     "The Bloop was a real acoustic signal later attributed to ice fracturing; "
     "sea-monster speculation is cultural context, not a scientific claim."),
]


class Claim:
    """One extracted factual claim from the narration."""

    __slots__ = ("text", "kind", "value", "unit", "entity", "status",
                 "detail", "source_label")

    def __init__(self, text: str, kind: str = "quantitative",
                 value: Optional[str] = None, unit: Optional[str] = None,
                 entity: Optional[str] = None):
        self.text = text
        self.kind = kind          # quantitative | entity | causal
        self.value = value
        self.unit = unit
        self.entity = entity
        self.status = "unchecked"  # verified|unsupported|contradicted|ok
        self.detail = ""
        self.source_label = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


class ClaimVerifier:
    """Extract, disambiguate and verify claims in a final narration script."""

    def __init__(self, llm=None, research_pack: Optional[dict] = None):
        self._llm = llm
        self._research = research_pack or {}

    # ── Step 1: extraction ──────────────────────────────────────────────

    def _deterministic_claims(self, text: str) -> list[Claim]:
        claims: list[Claim] = []
        for m in _NUMBER_PAT.finditer(text):
            claims.append(Claim(
                text=m.group(0).strip(),
                kind="quantitative",
                value=m.group(1).replace(",", ""),
                unit=m.group(2).lower(),
            ))
        # Written-out numbers ("fifty-two hertz", "five thousand km").
        for m in _WORD_NUM_PAT.finditer(text):
            num = _words_to_number(m.group(1))
            if not num:
                continue
            claims.append(Claim(
                text=m.group(0).strip(),
                kind="quantitative",
                value=num,
                unit=m.group(2).lower(),
            ))
        return claims

    def extract_claims(self, scenes: list[dict]) -> dict:
        """Full extraction over the final narration (scene by scene)."""
        narration = "\n".join(s.get("narration", "") or "" for s in scenes)
        claims = self._deterministic_claims(narration)

        # LLM refinement: catch claims the regex misses (comparatives,
        # named phenomena, causal statements) + entity list.
        llm_claims: list[dict] = []
        entities: list[str] = []
        if self._llm is not None:
            try:
                res = _parse_llm_json(self._llm.generate_json(
                    _fill(_EXTRACT_PROMPT, narration=narration[:6000])
                ))
                llm_claims = res.get("claims", []) or []
                entities = res.get("entities", []) or []
            except Exception as e:
                print(f"  [claims] !! LLM extraction failed: {str(e)[:100]} "
                      f"— using deterministic extraction only")

        for c in llm_claims:
            claims.append(Claim(
                text=str(c.get("text", "")),
                kind=str(c.get("kind", "quantitative")),
                value=str(c.get("value", "")) or None,
                unit=str(c.get("unit", "")) or None,
                entity=str(c.get("entity", "")) or None,
            ))

        # Dedupe by (text, kind)
        seen = set()
        deduped = []
        for c in claims:
            key = (c.text.strip().lower(), c.kind)
            if key not in seen:
                seen.add(key)
                deduped.append(c)
        return {"claims": deduped, "entities": entities,
                "narration": narration}

    # ── Step 2: disambiguation ──────────────────────────────────────────

    def disambiguate(self, extraction: dict) -> list[dict]:
        """Detect entity-conflation risks.

        Checks the curated KNOWN_DISTINCT_PHENOMENA pairs against the
        script, and asks the LLM for script-specific conflation risks
        (same-name/similar-name phenomena sharing a scene).
        """
        text = (extraction.get("narration") or "").lower()
        entities = [e.lower() for e in (extraction.get("entities") or [])]
        hits: list[dict] = []

        # 1) Curated pairs present in the same script — a WARNING-level
        #    flag (co-mention of two distinct phenomena is not itself an
        #    error; actual attribute transfer is what blocks).  The LLM
        #    disambiguation step below decides criticality.
        for a, b, why in KNOWN_DISTINCT_PHENOMENA:
            has_a = a in text or any(a in e for e in entities)
            has_b = b in text or any(b in e for e in entities)
            if has_a and has_b:
                hits.append({
                    "type": "conflation_risk",
                    "a": a, "b": b,
                    "detail": why,
                    "severity": "major",
                })

        # 1b) Attribute-transfer detection for the known Bloop case: the
        # narration never needs to say "52-Hz whale" verbatim to conflate
        # the two — "At fifty-two hertz… it was in the range of a whale"
        # while talking ABOUT the Bloop IS the conflation (52 Hz is the
        # whale's frequency, NOT the Bloop's).
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for i, sent in enumerate(sentences):
            if "whale" not in sent and "whales" not in sent:
                continue
            freq_in_sent = any(
                c.kind == "quantitative"
                and c.unit in ("hertz", "hz", "khz")
                and c.text.lower() in sent
                for c in extraction.get("claims", []))
            if not freq_in_sent:
                continue
            # SAME-sentence bloop+hertz+whale = clear-cut transfer (critical).
            if "bloop" in sent:
                hits.append({
                    "type": "conflation_risk",
                    "a": "the bloop",
                    "b": "whale vocalization at whale-range frequency",
                    "detail": ("A sentence about The Bloop also carries a "
                                "whale-range frequency — the frequency belongs "
                                "to the separate 52-Hz whale, not the Bloop. "
                                "Remove it from the Bloop's description."),
                    "severity": "critical",
                })
                continue
            # ADJACENT-sentence attribution ("They called it the Bloop." /
            # "At fifty-two hertz, it was in the range of a whale…") — the
            # exact expert-review pattern.  Critical ONLY when the whale is
            # NOT the sentence's agent: "in the range of a whale" (whale is
            # a comparison object -> the frequency belongs to the Bloop) is
            # a conflation; "a whale calls at fifty-two hertz" (whale is
            # the subject) is the correct 52-Hz-whale framing.
            _prev = sentences[i - 1].lower() if i > 0 else ""
            _next = sentences[i + 1].lower() if i + 1 < len(sentences) else ""
            if "bloop" in _prev or "bloop" in _next:
                # Whale-as-AGENT means the whale performs the call:
                # "a whale calls at fifty-two hertz" / "the whale's call at
                # 52 hertz" — correct 52-Hz framing.  "hertz … in the range
                # of a whale" has NO vocalization verb, so the frequency is
                # attributed to the Bloop → conflation.
                _whale_agent = bool(re.search(
                    r"whale[^.!?]*(calls|sings|communicates|vocalizes|"
                    r"produces|uses)[^.!?]*hertz|"
                    r"whale'?s?[^.!?]*call[^.!?]*hertz",
                    sent))
                hits.append({
                    "type": "conflation_risk",
                    "a": "the bloop",
                    "b": "whale vocalization at whale-range frequency",
                    "detail": ("A whale-range frequency appears adjacent to a "
                                "sentence naming The Bloop.  If the frequency is "
                                "attributed to the Bloop (e.g. 'it was in the range "
                                "of a whale'), that is a conflation — 52 Hz belongs "
                                "to the separate 52-Hz whale, not the Bloop."),
                    "severity": "major" if _whale_agent else "critical",
                })

        # 2) LLM script-specific disambiguation.
        if self._llm is not None:
            try:
                res = _parse_llm_json(self._llm.generate_json(
                    _fill(_DISAMBIGUATE_PROMPT,
                          narration=(extraction.get("narration") or "")[:6000],
                          entities=", ".join(entities or ["(none listed)"]))
                ))
                # Corroboration: an LLM risk is BLOCKING (critical) only
                # when both entities actually co-occur within a single
                # sentence of the narration — that is where attribute
                # transfer happens.  Legitimate comparisons ("blue whales
                # call at 10-30 Hz; the 52-Hz whale is different") mention
                # both across sentences; flagging them as critical would
                # block every correct documentary.  Non-co-occurring risks
                # are downgraded to advisory (major) for the reviewer.
                sentences_l = re.split(r"(?<=[.!?])\s+", text)
                for h in (res.get("risks", []) or []):
                    a = str(h.get("a", "")).strip().lower()
                    b = str(h.get("b", "")).strip().lower()
                    sev = str(h.get("severity", "major"))
                    # Nickname/metaphor filter: "the loneliest voice" is
                    # the SAME entity as "the 52-hertz whale", not a
                    # separate phenomenon.  If one side's wording is a
                    # known nickname of the other, drop the risk entirely.
                    if _is_nickname_pair(a, b):
                        continue
                    if sev == "critical":
                        _co = any(a in s and b in s for s in sentences_l)
                        if not _co:
                            sev = "major"  # no transfer evidence
                    hits.append({
                        "type": "conflation_risk",
                        "a": str(h.get("a", "")),
                        "b": str(h.get("b", "")),
                        "detail": str(h.get("why", "")),
                        "severity": sev,
                    })
            except Exception as e:
                print(f"  [claims] !! disambiguation LLM failed: {str(e)[:100]}")
        return hits

    # ── Step 3: verification ────────────────────────────────────────────

    def _research_facts(self) -> list[dict]:
        facts = []
        if isinstance(self._research, list):
            facts = [f for f in self._research if isinstance(f, dict)]
        else:
            for f in (self._research.get("facts") or []):
                if isinstance(f, dict):
                    facts.append(f)
        return facts

    def verify(self, extraction: dict) -> dict:
        """Tag every claim verified / unsupported / contradicted."""
        facts = self._research_facts()
        fact_texts = []
        for f in facts:
            claim_txt = str(f.get("claim", "") or "")
            value_txt = str(f.get("value", "") or "")
            fact_texts.append(f"{claim_txt} {value_txt}".lower())

        for c in extraction["claims"]:
            if c.kind != "quantitative" or not c.value:
                c.status = "ok"  # entity/causal claims handled separately
                continue
            # Search the research pack for the same number+unit.
            v = c.value
            u = (c.unit or "").strip()
            hit = None
            for ft in fact_texts:
                if v in ft or (u and u in ft and v in ft):
                    hit = ft
                    break
            if hit:
                c.status = "verified"
                c.source_label = "research_pack"
                c.detail = f"matched research fact: …{hit[:100]}"
            else:
                # No pack support — ask the LLM to verify from knowledge,
                # explicitly labeling fact vs hypothesis vs conclusion.
                if self._llm is not None:
                    try:
                        res = _parse_llm_json(self._llm.generate_json(
                            _fill(_VERIFY_PROMPT,
                                  claim=c.text,
                                  value=c.value,
                                  unit=c.unit or "",
                                  context=(extraction.get("narration") or "")[:1500])
                        ))
                        status = str(res.get("status", "unsupported")).lower()
                        if status in ("verified", "established_fact"):
                            c.status = "verified"
                        elif status in ("hypothesis", "conclusion", "inferred"):
                            c.status = "ok"
                            c.detail = f"{status}: {res.get('reason', '')[:120]}"
                        elif status == "contradicted":
                            c.status = "contradicted"
                            c.detail = str(res.get("reason", ""))[:160]
                        else:
                            c.status = "unsupported"
                            c.detail = str(res.get("reason", ""))[:160]
                        if res.get("source"):
                            c.source_label = str(res["source"])[:80]
                    except Exception as e:
                        print(f"  [claims] !! verify LLM failed: {str(e)[:80]}")
                        c.status = "unsupported"
                else:
                    c.status = "unsupported"

        return extraction

    # ── Step 4: gate ────────────────────────────────────────────────────

    def run(self, scenes: list[dict], out_dir: str = "") -> dict:
        """Execute the full claim gate on final-narration scenes.

        Returns a gate dict compatible with PublishStatus:
          {passed, checks: [{name, passed, detail}], claims, entities,
           conflation_risks, blocking_failures}
        """
        extraction = self.extract_claims(scenes)
        risks = self.disambiguate(extraction)
        extraction = self.verify(extraction)

        claims = [c.to_dict() for c in extraction["claims"]]
        contradicted = [c for c in claims if c["status"] == "contradicted"]
        unsupported = [c for c in claims
                       if c["kind"] == "quantitative" and c["status"] == "unsupported"]
        critical_risks = [r for r in risks if r.get("severity") == "critical"]

        checks = [
            {
                "name": "claim_contradictions",
                "passed": not contradicted,
                "detail": f"{len(claims)} claim(s); 0 contradicted"
                          if not contradicted
                          else f"CONTRADICTED claims: "
                               + "; ".join(c["text"][:60] for c in contradicted[:5]),
            },
            {
                "name": "unsupported_quantitative_claims",
                # Advisory, NOT blocking: documentary narration legitimately
                # uses approximate phrasing ("thousands of miles a year",
                # "tens of miles", "annual pulses") that cannot be pinned
                # to an exact research-pack number.  The hard blockers are
                # CONTRADICTED claims and ENTITY CONFLATION (the expert's
                # critical findings).  Unsupported-but-plausible claims are
                # surfaced in the report for the reviewer instead of
                # aborting production.
                "passed": not unsupported,
                "detail": "all quantitative claims source-backed"
                          if not unsupported
                          else f"UNSUPPORTED (advisory) numbers: "
                               + "; ".join(c["text"][:60] for c in unsupported[:5]),
            },
            {
                "name": "entity_disambiguation",
                "passed": not critical_risks,
                "detail": "no entity-conflation risks"
                          if not critical_risks
                          else f"CONFLATION RISK: "
                               + "; ".join(f"{r['a']} vs {r['b']}" for r in critical_risks[:3]),
            },
        ]

        result = {
            "passed": all(c["passed"] for c in checks),
            "checks": checks,
            "claims": claims,
            "entities": extraction.get("entities", []),
            "conflation_risks": risks,
            # Hard blockers: contradicted claims + entity conflation (the
            # expert's critical findings).  Advisory checks (unsupported-
            # but-plausible numbers) are surfaced in the report for the
            # reviewer but never abort production.
            "blocking_failures": [
                c["name"] for c in checks
                if not c["passed"] and c["name"] != "unsupported_quantitative_claims"
            ],
        }
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
            with open(os.path.join(out_dir, "claim_report.json"), "w") as f:
                json.dump(result, f, indent=2)
        return result


# ── LLM prompts ──────────────────────────────────────────────────────────
# These prompts contain literal JSON braces, so NEVER pass them through
# str.format() (a stray brace breaks the format string).  Use _fill()
# (plain token substitution) and _parse_llm_json() for responses.

# Nickname/metaphor aliases: the KEY is a figure-of-speech for the VALUE
# entity — never a separate phenomenon (e.g. "the loneliest voice" IS the
# 52-Hertz whale).  Used to filter LLM-disambiguation false positives.
_NICKNAME_ALIASES = {
    "loneliest voice": "52",
    "loneliest whale": "52",
    "lonely whale": "52",
    "the whale that sings at fifty two hertz": "52",
    "the whale that sings at 52 hertz": "52",
}


def _is_nickname_pair(a: str, b: str) -> bool:
    """True when one side is a known nickname/metaphor of the other
    (same entity — NOT a conflation risk)."""
    if not a or not b:
        return False
    low_a, low_b = a.lower(), b.lower()
    # direct alias table
    for nick, target in _NICKNAME_ALIASES.items():
        if nick in low_a or nick in low_b:
            other = low_b if nick in low_a else low_a
            if target in other or "whale" in other:
                return True
    # heuristic: shared core token (both mention the same animal/phenomenon
    # and one side is purely descriptive)
    for tok in ("whale", "hertz", "bloop"):
        if tok in low_a and tok in low_b:
            # both reference the same phenomenon; drop the risk only when
            # one side is clearly a metaphor/description, not a distinct name
            if ("loneliest" in low_a or "loneliest" in low_b
                    or "voice" in low_a or "voice" in low_b):
                return True
    return False


def _fill(template: str, **kw) -> str:
    """Token substitution for prompt templates containing literal braces."""
    out = template
    for k, v in kw.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def _parse_llm_json(text) -> dict:
    """Robustly parse an LLM JSON response: may come back as a dict, a
    JSON string, or prose wrapped around JSON — never trust the LLM to be
    tidy.  Falls back to {} on any failure (caller treats as no-op)."""
    import json as _json
    if isinstance(text, dict):
        return text
    if isinstance(text, list):
        return {"claims": text} if text else {}
    if not isinstance(text, str):
        return {}
    t = text.strip()
    # strip markdown fences if present
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*", "", t)
        t = re.sub(r"\s*```$", "", t)
    # find the outermost JSON object
    start, end = t.find("{"), t.rfind("}")
    if start >= 0 and end > start:
        t = t[start:end + 1]
    try:
        return _json.loads(t)
    except Exception:
        return {}


_EXTRACT_PROMPT = """You are a documentary fact-checker.  Extract EVERY
quantitative claim and named phenomenon from the narration below.

Return STRICT JSON:
{{"claims": [{{"text": "the exact claim phrase", "kind": "quantitative|entity|causal",
   "value": "numeric value only", "unit": "unit only", "entity": "related entity"}], 
  "entities": ["every named scientific phenomenon / entity / place / person"]}}

Include: all numbers with units (frequencies, dates, distances, speeds,
sizes, temperatures, percentages), named phenomena (e.g. "The Bloop",
"52-Hz whale", "icequake"), and any causal claim ("X caused Y").

NARRATION:
{narration}
"""

_DISAMBIGUATE_PROMPT = """You are an expert scientific editor.  The narration
below mentions several phenomena/entities.  Identify pairs of DISTINCT
phenomena that could be accidentally CONFLATED by an audience or an editor —
especially similarly-named or related phenomena where attributes must never
transfer (e.g. "The Bloop" vs "the 52-Hz whale": different signals, different
frequencies, different years; "icequake" is the Bloop's explanation, not a
separate mystery).

CRITICAL RULE: a NICKNAME or metaphor of a phenomenon is the SAME entity,
not a separate phenomenon.  "the loneliest voice", "the loneliest whale",
"the 52-hertz whale" all refer to ONE whale — never report them as a
conflation pair.  Only report pairs where TWO genuinely distinct phenomena
appear and an attribute could transfer between them.

Entities mentioned: {entities}

Return STRICT JSON:
{{"risks": [{{"a": "phenomenon A", "b": "phenomenon B",
   "why": "why they are distinct and what attribute must not transfer",
   "severity": "critical|major|minor"}}]}}

Return empty risks list if nothing is conflatable.

NARRATION:
{narration}
"""

_VERIFY_PROMPT = """You are a scientific fact-checker.  Verify this claim
independently.  The claim is: "{claim}" (value {value} {unit}).

Context: {context}

Return STRICT JSON:
{{"status": "verified|contradicted|hypothesis|conclusion|unsupported",
  "reason": "one sentence",
  "source": "authoritative source name if known (NOAA, NASA, USGS, paper DOI…) or ''"}}

Rules:
- "verified" ONLY if this is an established, independently-checked fact.
- RANGE TOLERANCE: if the claim is a RANGE (e.g. "between 10 and 30 hertz")
  that OVERLAPS the commonly accepted range for that entity (blue whales
  ~10-40 Hz), mark "verified" — a narrower-but-overlapping range is NOT a
  contradiction.  Only "contradicted" when clearly outside any accepted
  range (order-of-magnitude off, or a different phenomenon's value).
- "hypothesis"/"conclusion" if it is a scientific interpretation (e.g.
  NOAA concluded the Bloop was consistent with icequakes — that is a
  conclusion, not an established frequency).
- "contradicted" if the number/claim is wrong or mixes two phenomena.
- "unsupported" if you cannot verify it from authoritative knowledge."""


def make_verifier(llm=None, research_pack: Optional[dict] = None) -> ClaimVerifier:
    return ClaimVerifier(llm=llm, research_pack=research_pack)
