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

        1. Narration→query+tags overlap (catches narration leak into
           search queries).
        2. Query→tags overlap (measures how well the search result
           matches what was searched for).
        3. Query→narration overlap (measures how well the search query
           relates to the narration topic).

        Returns a float in [0.0, 1.0].  Includes punctuation stripping
        and stem-less matching for better coverage.
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
            """Split, strip punctuation, remove stop words and short tokens."""
            return {
                re.sub(r'[^\w]', '', w).lower()
                for w in text.split()
                if len(re.sub(r'[^\w]', '', w)) > 2
                and re.sub(r'[^\w]', '', w).lower() not in stop_words
            }

        nar_tokens = tokenize(narration)
        query_tokens = tokenize(query)
        tag_tokens = tokenize(tags)

        if not nar_tokens:
            return 0.5

        # ── Score 1: narration keywords found in query+tags ───────────
        combined = query_tokens | tag_tokens
        if combined:
            nar_matches = nar_tokens & combined
            score_nar = len(nar_matches) / max(len(nar_tokens), 1)
        else:
            score_nar = 0.0

        # ── Score 2: query keywords found in tags (asset relevance) ───
        if query_tokens and tag_tokens:
            query_tag_matches = query_tokens & tag_tokens
            score_query_tags = len(query_tag_matches) / max(len(query_tokens), 1)
        else:
            score_query_tags = 0.5

        # ── Score 3: query keywords found in narration (topic match) ──
        if query_tokens and nar_tokens:
            query_nar_matches = query_tokens & nar_tokens
            score_query_nar = len(query_nar_matches) / max(len(query_tokens), 1)
        else:
            score_query_nar = 0.5

        # Take the maximum of narration-derived scores only.
        # Query-tag matching alone ("search returned what I asked for")
        # is NOT evidence of narration relevance.
        # Only query-tag matching > 0 AND some narration overlap counts.
        if score_nar > 0.0 or score_query_nar > 0.0:
            final = max(score_nar, score_query_tags, score_query_nar)
        else:
            final = max(score_nar, score_query_nar)

        # Bonus: when there IS some narration signal AND the query was
        # a good search match, bump the score.
        if (score_nar > 0.0 or score_query_nar > 0.0) and score_query_tags >= 0.5:
            final = max(final, min(1.0, final + 0.1))

        return round(max(0.0, min(1.0, final)), 4)

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
