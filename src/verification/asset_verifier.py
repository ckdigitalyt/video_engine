"""
asset_verifier.py — Multi-signal Entity–Asset verification.

Evaluates a candidate asset against a beat's EntitySpec using multiple
independent signals:
  1. metadata       (provider, media type, official title)
  2. captions       (description / alt text / title)
  3. filename       (often the most honest signal for archival assets)
  4. provider tags  (search query that retrieved it, keywords)
  5. vision check   (ONLY when metadata signals cannot confidently decide)

Rules:
  - Any PROHIBITED entity present  -> FATAL (semantic mismatch).
  - Required entities missing with high spec confidence -> FATAL.
  - Ambiguous cases -> vision check (LLM image classification) before the
    asset may enter the timeline.

General framework: entity vocabulary is supplied by the caller (from the
beat's narration/facts), no topic-specific logic here.
"""

from __future__ import annotations

import os
import re
from typing import Optional

from .entity_spec import EntitySpec, VerificationResult


# Off-topic / domain-mismatch signals.  When an asset's metadata contains
# any of these, the asset is rejected REGARDLESS of entity-token matches —
# a title like "File:Pulsar Walibi Belgium overzicht.jpg" (a roller coaster
# at Walibi Belgium) contains the entity token "pulsar" yet is not an
# astronomical pulsar.  General, topic-free guard.
OFF_TOPIC_SIGNALS = [
    "roller coaster", "rollercoaster", "amusement", "theme park",
    "walibi", "water park", "fairground", "ferris wheel", "carousel",
    "bumper car", "fun park", "pleasure park", "trampoline",
    "playground", "kiddie", "festival", "concert", "stadium",
]

# When the query itself already carries domain context (e.g. "pulsar
# astronomy") we don't apply the off-topic guard to description text —
# only to the title — to avoid false rejections of legit assets.
_QUERY_HAS_CONTEXT_RE = re.compile(
    r"(astronomy|star|space|galaxy|cosmic|universe|nebula|solar|planet|astrophys)", re.I)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _tokens(text: str) -> set[str]:
    """Significant tokens (>=3 chars) from normalized text."""
    return {t for t in _norm(text).split() if len(t) >= 3}


def _entity_matches(entity: str, text: str) -> bool:
    """Partial/token-based match: entity matches if its significant tokens
    are largely present in the text (e.g. 'Voyager 1' matches
    'Voyager 1 Launch 1977').  Tolerant of extra words in titles."""
    et = _tokens(entity)
    tt = _tokens(text)
    if not et:
        return False
    hits = et & tt
    # require >= 60% of the entity's significant tokens, or the full
    # normalized entity as a substring
    return (len(hits) / len(et) >= 0.6) or (_norm(entity) in _norm(text))


class AssetVerifier:
    """Verifies candidate assets against EntitySpecs."""

    def __init__(
        self,
        vision_enabled: bool = True,
        # v26: gemini-2.5-flash is 429 quota-exhausted (production risk);
        # default to 3.5-flash which the audit verified working for vision.
        vision_model: str = "gemini-3.5-flash",
        fatal_on_vision_fail: bool = True,
    ):
        self._vision_enabled = vision_enabled
        self._vision_model = vision_model
        self._fatal_on_vision_fail = fatal_on_vision_fail
        # Circuit breaker: after consecutive vision infra errors, disable
        # vision for the rest of the process (one 429 must not hammer the
        # provider for every asset in the run).
        self._vision_error_streak = 0
        self._vision_max_streak = 2
        self._vision_broken = False

    # ── Public API ─────────────────────────────────────────────────────

    def verify(
        self,
        spec: EntitySpec,
        *,
        asset_path: str = "",
        title: str = "",
        description: str = "",
        filename: str = "",
        provider: str = "",
        tags: Optional[list[str]] = None,
        query_used: str = "",
    ) -> VerificationResult:
        """Run all signals and return a VerificationResult.

        ``asset_path`` may point at an image/video frame for the vision
        check when metadata signals are inconclusive.
        """
        res = VerificationResult(asset_path=asset_path, beat_id=spec.beat_id)
        signals = {
            "metadata": self._score_metadata(spec, title, description, provider),
            "captions": self._score_text(spec, description or title),
            "filename": self._score_text(spec, filename),
            "provider_tags": self._score_tags(spec, tags or ([query_used] if query_used else [])),
        }
        res.signal_scores = signals

        # Aggregate: weighted mean (metadata + captions strongest)
        weights = {"metadata": 0.3, "captions": 0.3, "filename": 0.2, "provider_tags": 0.2}
        total_w = sum(weights.get(k, 0.2) for k, v in signals.items() if v is not None)
        res.score = sum(
            weights.get(k, 0.2) * v.get("score", 0)
            for k, v in signals.items() if v is not None
        ) / max(total_w, 1e-9)

        # Combined evidence text for positive required-entity matching
        evidence_text = " ".join([
            title, description, filename, provider,
            " ".join(tags or []), query_used,
        ])

        # ── Domain relevance guard (off-topic metadata) ────────────────
        # A required-entity token match is NOT sufficient: an amusement-park
        # roller coaster named "Pulsar" must never illustrate a pulsar scene.
        # When vision is unavailable this is the ONLY signal that can catch
        # such semantic mismatches, so it is treated as fatal.
        evidence_all = " ".join([title, description, filename, provider,
                                 " ".join(tags or []), query_used])
        evidence_norm = _norm(evidence_all)
        bare_query = not _QUERY_HAS_CONTEXT_RE.search(query_used or "")
        off_topic_hits = [
            sig for sig in OFF_TOPIC_SIGNALS
            if sig in evidence_norm and (bare_query or sig in _norm(title))
        ]
        if off_topic_hits:
            res.violated_prohibited.append(f"off-topic:{off_topic_hits[0]}")
            res.reasons.append(
                f"fatal: off-topic metadata signal ({off_topic_hits[0]}) — "
                f"entity token alone is insufficient")

        # Prohibited entities are always fatal: any signal detecting a ban
        for ent in spec.prohibited_entities:
            if self._ban_in_signals(ent, signals):
                res.violated_prohibited.append(ent)
                res.reasons.append(f"PROHIBITED entity present: {ent}")
        # Required entities: matched when tokens largely present in evidence.
        # Uses the alias layer (match_terms) so terse official titles match
        # semantic entities (e.g. entity "Earth" matches "Pale Blue Dot").
        for ent in spec.required_entities:
            terms = spec.match_terms.get(ent) or [ent]
            if any(_entity_matches(t, evidence_text) for t in terms):
                res.matched_required.append(ent)
        res.missing_required = [
            e for e in spec.required_entities if e not in res.matched_required
        ]

        if res.violated_prohibited:
            res.passed = False
            res.reasons.append("fatal: prohibited entity violation")
            return res

        # Required coverage: accept when ANY required entity is matched at a
        # strong score (not ALL — a good asset need not mention every subject
        # in its metadata; missing detail is a flag, not a fatal mismatch).
        any_required = not spec.required_entities or bool(res.matched_required)
        strong_score = res.score >= 0.55
        if not res.violated_prohibited and any_required and strong_score:
            res.passed = True
            res.reasons.append(f"signals confirm (score={res.score:.2f})")
            return res

        # Ambiguous -> vision check if a frame/image is available.
        # Vision INFRASTRUCTURE failure (quota/network) is NOT a semantic
        # mismatch: degrade gracefully (metadata decides, low-confidence
        # flag) and trip the circuit breaker.  Only a vision check that
        # SUCCESSFULLY runs and confirms a mismatch is fatal.
        vision_ok = self._vision_enabled and not self._vision_broken
        if vision_ok and asset_path and os.path.exists(asset_path):
            vision = self._vision_check(spec, asset_path)
            res.vision_check = vision
            if vision.get("error"):
                self._vision_error_streak += 1
                if self._vision_error_streak >= self._vision_max_streak:
                    self._vision_broken = True
                    print(f"  [vision] circuit breaker tripped after "
                          f"{self._vision_error_streak} errors")
                # Vision down: metadata decides, but ONLY with a strong
                # score AND at least one required entity matched.  Off-topic
                # violations (set above) remain fatal.  This closes the hole
                # where a 0.34 metadata match sailed through on quota errors.
                strong = res.score >= 0.55 and bool(res.matched_required)
                res.passed = (not res.violated_prohibited) and strong
                res.reasons.append(
                    f"vision unavailable ({vision.get('error','')[:40]}); "
                    f"metadata fallback score={res.score:.2f} "
                    f"({'strong accept' if res.passed else 'REJECT — insufficient evidence'})"
                )
                return res
            # Vision ran successfully
            self._vision_error_streak = 0
            if vision.get("passed"):
                res.passed = True
                res.reasons.append("vision check confirmed")
                return res
            if self._fatal_on_vision_fail:
                res.passed = False
                res.reasons.append(f"fatal: vision check failed ({vision.get('subject','?')})")
            else:
                res.passed = (not res.violated_prohibited) and any_required
                res.reasons.append("vision check failed but non-fatal mode")
            return res

        # No vision available: metadata decides, but NEVER block the pipeline
        # on infrastructure.  Prohibited/off-topic violations still fatal;
        # weak scores (< 0.55) or missing required entities are rejected.
        strong = res.score >= 0.55 and (not spec.required_entities or bool(res.matched_required))
        if not res.violated_prohibited and strong:
            res.passed = True
            res.reasons.append(f"metadata-only accept (score={res.score:.2f}); "
                               f"vision {'broken' if self._vision_broken else 'disabled'}")
            return res
        res.passed = False
        res.reasons.append(f"unverified: score={res.score:.2f}, missing={res.missing_required}")
        return res

    # ── Vision-only AI still verification ──────────────────────────────

    def verify_ai_still(self, spec: EntitySpec, *, asset_path: str = "",
                        query_used: str = "") -> VerificationResult:
        """Verify an AI-generated still with the VISION check only.

        v33 (review 2026-08-13 C-1): AI stills have no authoritative
        metadata (empty title/provider, prompt is the only evidence), so
        metadata scoring is meaningless — it would reject every AI still
        at ~0.33 when vision is down.  Give metadata a NEUTRAL score and
        let the vision check alone decide.  Fail-open when vision is
        unavailable (quota/network): an infra blip must never stall the
        scene; the post-render video-level gates own the final verdict.
        """
        res = VerificationResult(asset_path=asset_path, beat_id=spec.beat_id)
        res.signal_scores = {
            "metadata": {"score": 0.5, "evidence": "AI still (neutral)"},
            "provider_tags": {"score": 0.5, "evidence": query_used},
        }
        res.score = 0.5
        vision_ok = self._vision_enabled and not self._vision_broken
        if not (vision_ok and asset_path and os.path.exists(asset_path)):
            res.passed = True  # fail-open: no vision signal available
            res.reasons.append("AI still: vision unavailable — fail-open")
            return res
        vision = self._vision_check(spec, asset_path)
        res.vision_check = vision
        if vision.get("error"):
            self._vision_error_streak += 1
            if self._vision_error_streak >= self._vision_max_streak:
                self._vision_broken = True
                print(f"  [vision] circuit breaker tripped after "
                      f"{self._vision_error_streak} errors")
            res.passed = True  # fail-open on infra error
            res.reasons.append(
                f"AI still: vision error — fail-open ({vision.get('error','')[:40]})")
            return res
        self._vision_error_streak = 0
        if vision.get("passed"):
            res.passed = True
            res.reasons.append("vision check confirmed")
        else:
            res.passed = False
            res.reasons.append(
                f"AI still: vision check failed (subject={vision.get('subject','?')[:60]})")
        return res

    # ── Signal scorers ─────────────────────────────────────────────────

    def _score_metadata(self, spec, title, description, provider) -> dict:
        text = f"{title} {description} {provider}"
        hits = [e for e in spec.required_entities if _norm(e) in _norm(text)]
        bans = [e for e in spec.prohibited_entities if _norm(e) in _norm(text)]
        score = 0.7 if hits or not spec.required_entities else 0.3
        if bans:
            score = 0.0
        return {"score": score, "evidence": f"hits={hits}, bans={bans}"}

    def _score_text(self, spec, text: str) -> dict:
        t = _norm(text)
        if not t:
            return {"score": 0.5, "evidence": "no text"}
        hits = [e for e in spec.required_entities if _norm(e) in t]
        bans = [e for e in spec.prohibited_entities if _norm(e) in t]
        score = 0.8 if hits or not spec.required_entities else 0.2
        if bans:
            score = 0.0
        return {"score": score, "evidence": f"hits={hits}, bans={bans}"}

    def _score_tags(self, spec, tags: list[str]) -> dict:
        joined = _norm(" ".join(tags))
        hits = [e for e in spec.required_entities if _norm(e) in joined]
        bans = [e for e in spec.prohibited_entities if _norm(e) in joined]
        score = 0.75 if hits or not spec.required_entities else 0.25
        if bans:
            score = 0.0
        return {"score": score, "evidence": f"tags={tags[:4]}, hits={hits}, bans={bans}"}

    @staticmethod
    def _ban_in_signals(entity: str, signals: dict) -> bool:
        """True when any signal's score collapsed to 0.0 (ban detected)."""
        e = _norm(entity)
        if not e:
            return False
        for sig in signals.values():
            if not sig:
                continue
            if sig.get("score", 1.0) <= 0.0 and e in _norm(str(sig.get("evidence", ""))):
                return True
        return False

    # ── Vision check ───────────────────────────────────────────────────

    def _vision_check(self, spec: EntitySpec, asset_path: str) -> dict:
        """Ask a vision LLM whether the asset matches the beat's intent."""
        try:
            from google import genai
            from google.genai import types
            import os as _os
            from dotenv import load_dotenv
            load_dotenv(_os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(
                _os.path.abspath(__file__)))), ".env"))
            client = genai.Client(api_key=_os.environ.get("GEMINI_API_KEY", ""))
            mime = "image/jpeg" if asset_path.lower().endswith((".jpg", ".jpeg")) else "image/png"
            img = types.Part.from_bytes(data=open(asset_path, "rb").read(), mime_type=mime)
            prompt = (
                "You verify documentary footage. The scene REQUIRES these subjects: "
                f"{spec.required_entities or '(none specific)'}. It must NEVER show: "
                f"{spec.prohibited_entities or '(none)'}. Scene intent: {spec.scene_intent}. "
                "What is actually shown? Respond STRICT JSON: "
                '{"subject": "...", "required_present": true/false, '
                '"prohibited_present": true/false, "notes": "..."}'
            )
            resp = client.models.generate_content(
                model=self._vision_model, contents=[prompt, img],
                config=types.GenerateContentConfig(temperature=0.1, response_mime_type="application/json"),
            )
            import json as _json
            text = resp.text.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            data = _json.loads(text)
            passed = data.get("required_present", False) and not data.get("prohibited_present", False)
            return {"subject": data.get("subject", ""), "passed": passed,
                    "notes": data.get("notes", ""), "model": self._vision_model}
        except Exception as e:  # noqa: BLE001
            return {"subject": "", "passed": False, "error": str(e)[:120],
                    "model": self._vision_model}
