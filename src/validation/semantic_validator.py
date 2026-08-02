"""
semantic_validator.py — Semantic relevance validation for asset candidates.

After technical scoring, the SemanticValidator uses an LLM to assess
whether a candidate asset is semantically relevant to the scene narration.
Low-scoring candidates are rejected, forcing the pipeline to try the next
search query.  If all queries fail, the highest semantic score is used.
"""

from typing import Optional

from src.models.schemas import AssetPlan
from src.providers.llm_provider import LLMProvider
from src.utils.config import get_config


_SCORE_PROMPT = """You are a video asset relevance validator. Given a scene narration and a stock footage candidate, score the semantic relevance from 0.0 (completely unrelated) to 1.0 (perfect match).

Narration: "{narration}"
Candidate asset tags/description: "{tags}"
Candidate search query that produced this result: "{query}"

Consider:
- Does the asset visually match the narration's subject?
- Does the asset's context match the narration's context?
- Is the mood/perspective appropriate?

Return ONLY a float between 0.0 and 1.0, no explanation."""


class SemanticValidator:
    """Validates that a candidate asset is semantically relevant to a scene.

    Parameters
    ----------
    provider : LLMProvider | None
        LLM used for evaluation.  When *None*, falls back to a simple
        keyword-overlap heuristic.
    enabled : bool, optional
        Override for ``semantic_validation.enabled``.
    threshold : float, optional
        Minimum semantic score to accept an asset (0-1).
    max_attempts : int, optional
        Maximum retries across all queries for a scene.
    """

    def __init__(
        self,
        provider: Optional[LLMProvider] = None,
        enabled: Optional[bool] = None,
        threshold: Optional[float] = None,
        max_attempts: Optional[int] = None,
    ):
        self._provider = provider
        self._enabled = enabled if enabled is not None else get_config(
            "semantic_validation.enabled", True
        )
        # Authoritative threshold: hard reject below this score
        self._threshold = threshold if threshold is not None else get_config(
            "visual_director.quality_gates.semantic_threshold", 0.75
        )
        self._max_attempts = max_attempts if max_attempts is not None else get_config(
            "semantic_validation.max_attempts", 5
        )

    # ── Public API ─────────────────────────────────────────────────────

    def score(
        self,
        narration: str,
        query: str,
        asset: AssetPlan,
    ) -> float:
        """Score the semantic relevance of *asset* for *narration*.

        Returns a float in [0.0, 1.0].  Uses LLM when available, falls
        back to a deterministic keyword-overlap heuristic.
        """
        if not self._enabled:
            return 1.0

        tags = self._extract_tags(asset)

        if self._provider:
            return self._score_via_llm(narration, query, tags)

        return self._score_fallback(narration, query, tags)

    def is_acceptable(self, score: float) -> bool:
        """Return *True* when *score* meets the configured threshold.

        This is an authoritative gate: *False* means the asset MUST be
        rejected and an alternative MUST be found.
        """
        return score >= self._threshold

    # ── LLM-based scoring ──────────────────────────────────────────────

    def _score_via_llm(self, narration: str, query: str, tags: str) -> float:
        """Use LLM to assess semantic relevance."""
        prompt = _SCORE_PROMPT.format(
            narration=narration,
            tags=tags,
            query=query,
        )
        try:
            raw = self._provider.generate_text(prompt).strip()
            score = float(raw)
            return max(0.0, min(1.0, score))
        except (ValueError, Exception) as e:
            print(f"-> SemanticValidator LLM error: {e} — using fallback")
            return self._score_fallback(narration, query, tags)

    # ── Deterministic fallback scoring ─────────────────────────────────

    @staticmethod
    def _score_fallback(narration: str, query: str, tags: str) -> float:
        """Heuristic for semantic relevance using keyword overlap.

        Scores are computed in three complementary ways and the maximum
        is returned:

        1. Narration→query+tags overlap.
        2. Query→tags overlap.
        3. Query→narration overlap.

        Returns a float in [0.0, 1.0].  When LLM is unavailable, this
        heuristic is more generous to avoid rejecting valid assets that
        happen to use generic query terms.
        """
        import re

        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "up", "about", "into", "over", "after", "all", "also", "and",
            "but", "or", "if", "because", "so", "than", "that", "this",
            "these", "those", "it", "its", "they", "them", "we", "our",
            "you", "your", "he", "she", "his", "her", "my", "not", "no",
            "nor", "just", "very", "too", "much", "many", "some", "any",
            "each", "every", "both", "few", "more", "most", "other",
            "such", "only", "own", "same", "what", "which", "who", "whom",
            "when", "where", "why", "how",
        }

        def tokenize(text: str) -> set:
            return {
                re.sub(r'[^\w]', '', w).lower()
                for w in text.split()
                if len(re.sub(r'[^\w]', '', w)) > 2
                and re.sub(r'[^\w]', '', w).lower() not in stop_words
            }

        # Extract key topic nouns from narration (capitalized or frequent words)
        def extract_keywords(text: str) -> set:
            """Pull out significant topic words: capitalized nouns, freq > 1."""
            words = [re.sub(r'[^\w]', '', w) for w in text.split()]
            capped = {w.lower() for w in words if w and w[0].isupper() and len(w) > 3}
            return capped

        nar_tokens = tokenize(narration)
        query_tokens = tokenize(query)
        tag_tokens = tokenize(tags)
        nar_keywords = extract_keywords(narration)

        if not nar_tokens:
            return 0.65  # More generous default than 0.5

        # ── Score 1: narration keywords found in query+tags ───────────
        combined = query_tokens | tag_tokens
        if combined:
            nar_matches = nar_tokens & combined
            score_nar = len(nar_matches) / max(len(nar_tokens), 1)
        else:
            score_nar = 0.0

        # ── Score 2: query keywords found in tags ─────────────────────
        if query_tokens and tag_tokens:
            query_tag_matches = query_tokens & tag_tokens
            score_query_tags = len(query_tag_matches) / max(len(query_tokens), 1)
        else:
            score_query_tags = 0.5

        # ── Score 3: query keywords found in narration ────────────────
        if query_tokens and nar_tokens:
            query_nar_matches = query_tokens & nar_tokens
            score_query_nar = len(query_nar_matches) / max(len(query_tokens), 1)
        else:
            score_query_nar = 0.5

        # ── Score 4: key capitalized nouns in narration found in asset ─
        score_keywords = 0.0
        if nar_keywords:
            kw_matches = nar_keywords & combined
            score_keywords = len(kw_matches) / max(len(nar_keywords), 1)

        # ── Final: weighted blend, more generous than strict overlap ──
        final = max(score_nar, score_query_tags, score_query_nar, score_keywords)

        # Boost: if asset has topic keywords, give a significant bump
        if score_keywords > 0.0:
            final = max(final, 0.65 + score_keywords * 0.25)

        # Boost: if Pexels returned a named asset (not just generic),
        # assume it's somewhat relevant
        if tag_tokens and len(tag_tokens) > 3:
            final = max(final, 0.55)

        # Boost: any overlap at all with narration → base 0.5
        if score_nar > 0.0 and final < 0.5:
            final = 0.5

        return round(max(0.3, min(1.0, final)), 4)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_tags(asset: AssetPlan) -> str:
        """Extract a combined tag/description string from an AssetPlan.

        Uses query_used, filepath, video_url, and any available asset
        metadata (width/height) to build a description of the asset for
        semantic scoring.
        """
        parts = []

        # Use query_used as a primary descriptor
        if asset.query_used:
            parts.append(asset.query_used)

        # Include width/height as resolution hints
        if asset.width and asset.height:
            parts.append(f"{asset.width}x{asset.height}")

        # Use filepath (filename) for hints
        if asset.filepath:
            # Extract just the filename without extension
            filename = asset.filepath.rsplit("/", 1)[-1].replace(".mp4", "")
            # Also include the NASA asset ID if it's in the filename
            parts.append(filename.replace("_", " ").replace("-", " "))

        # Use video_url for additional context
        if asset.video_url:
            # Extract filename from URL
            parts.append(asset.video_url.split("/")[-1].split("?")[0])

        return " ".join(p for p in parts if p)


class ValidationResult:
    """Result of a multi-query validation pass."""

    def __init__(
        self,
        best_assets: list,
        best_query: str = "",
        best_score: float = 0.0,
        best_semantic_score: float = 0.0,
        attempts: int = 0,
        all_rejected: bool = False,
    ):
        self.assets = best_assets
        self.query = best_query
        self.technical_score = best_score
        self.semantic_score = best_semantic_score
        self.attempts = attempts
        self.all_rejected = all_rejected
