"""
semantic_validator.py — Semantic relevance validation for asset candidates.

After technical scoring, the SemanticValidator uses an LLM to assess
whether a candidate asset is semantically relevant to the scene narration.
Low-scoring candidates are rejected, forcing the pipeline to try the next
search query.  If all queries fail, the highest semantic score is used.
"""

from typing import Optional

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
        asset: dict,
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
        """Simple keyword-overlap heuristic for semantic relevance.

        Counts how many non-stop-word tokens from the narration appear
        in the query + tags, normalised by total unique tokens.
        """
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

        # Extract meaningful tokens
        nar_tokens = {
            w.lower() for w in narration.split()
            if w.lower() not in stop_words and len(w) > 2
        }
        query_tokens = {
            w.lower() for w in query.split()
            if w.lower() not in stop_words and len(w) > 2
        }
        tag_tokens = {
            w.lower() for w in tags.split()
            if w.lower() not in stop_words and len(w) > 2
        }

        combined = query_tokens | tag_tokens

        if not nar_tokens or not combined:
            return 0.5  # Neutral score when we can't compare

        matches = nar_tokens & combined
        score = len(matches) / min(len(nar_tokens), len(nar_tokens | combined))
        return round(max(0.0, min(1.0, score)), 4)

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _extract_tags(asset: dict) -> str:
        """Extract a combined tag/description string from an asset dict.

        Handles both Pexels and Pixabay formats.
        """
        parts = []

        # Pexels format: tags are in the top-level or nested
        raw_tags = asset.get("tags", asset.get("_raw", {}).get("tags", ""))
        if isinstance(raw_tags, list):
            parts.extend(raw_tags)
        elif isinstance(raw_tags, str) and raw_tags:
            parts.append(raw_tags)

        # Pixabay format: tags stored in _raw.tags as comma string
        raw_raw = asset.get("_raw", {})
        px_tags = raw_raw.get("tags", "")
        if px_tags and isinstance(px_tags, str):
            parts.append(px_tags)

        # URL/source filename can also give hints
        vf = asset.get("video_files", [])
        if vf:
            link = vf[0].get("link", "")
            # Extract filename from URL
            parts.append(link.split("/")[-1].split("?")[0] if link else "")

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
