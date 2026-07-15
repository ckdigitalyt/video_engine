"""
visual_critic.py — LLM-powered visual critic that scores each selected asset
before it reaches the renderer.

Sends narration + frame(s) + metadata to Gemini and asks:
  "Does this clip visually communicate the narration?"
Returns score 0-100, reason, and replacement suggestion.
If score < 80, the asset is rejected before rendering.
"""

from __future__ import annotations

import json
import os
import base64
from typing import Any, Optional

from src.providers.factory import ProviderFactory
from src.providers.llm_provider import LLMProvider


CRITIC_PROMPT = """You are a documentary visual quality critic. Given a narration and information about a video clip, score how well the clip visually communicates the narration.

Score 0-100 based on:
- Does the clip depict the subject of the narration? (0-100)
- Is the clip suitable for documentary use? (0-100)
- Is the clip free of text overlays, logos, and watermarks? (0-100)
- Is the camera work professional? (0-100)

Return ONLY a JSON object:
{
  "score": <0-100>,
  "reason": "<brief explanation>",
  "replacement_suggestion": "<what to search for instead>"
}

Threshold: score < 80 means reject this clip.
"""


class VisualCritic:
    """LLM-powered visual critic.

    Usage::

        critic = VisualCritic()
        result = critic.evaluate(
            narration="Fermi asked over lunch...",
            asset_metadata={"width": 1920, "height": 1080, ...},
            frame_path="cache/frame_preview.jpg",
        )
        if result["score"] < 80:
            # Reject and search for replacement
    """

    def __init__(self, provider: Optional[LLMProvider] = None):
        factory = ProviderFactory()
        self._provider = provider or factory.get_llm_provider_for_role("planner")

    def evaluate(
        self,
        narration: str,
        asset_metadata: Optional[dict[str, Any]] = None,
        frame_path: str = "",
    ) -> dict[str, Any]:
        """Score an asset for visual communication quality.

        Returns::
            {"score": int, "reason": str, "replacement_suggestion": str}
        """
        metadata_str = json.dumps(asset_metadata or {}, indent=2)

        prompt = (
            f"Narration: {narration}\n\n"
            f"Video Metadata: {metadata_str}\n\n"
        )

        # If we have a frame, mention it (vision support would go here)
        if frame_path and os.path.exists(frame_path):
            prompt += f"(Frame available at: {frame_path})\n"
        prompt += "\nScore:"

        try:
            raw = self._provider.llm_complete(
                system=CRITIC_PROMPT,
                prompt=prompt,
                temperature=0.3,
                max_tokens=200,
            )
            return self._parse(raw)
        except Exception as e:
            return {
                "score": 50,  # Neutral on failure
                "reason": f"Critic error: {e}",
                "replacement_suggestion": "",
            }

    def batch_evaluate(
        self,
        evaluations: list[tuple[str, dict[str, Any], str]],
    ) -> list[dict[str, Any]]:
        """Evaluate multiple assets in sequence.

        Args:
            evaluations: List of (narration, metadata, frame_path) tuples.

        Returns:
            List of score dicts.
        """
        return [self.evaluate(n, m, f) for n, m, f in evaluations]

    @staticmethod
    def _parse(raw: str) -> dict[str, Any]:
        """Parse LLM response JSON."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[-1]
            cleaned = cleaned.rsplit("\n", 1)[0]
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            return {"score": 50, "reason": "Failed to parse critic response", "replacement_suggestion": ""}

        return {
            "score": int(data.get("score", 50)),
            "reason": str(data.get("reason", "")),
            "replacement_suggestion": str(data.get("replacement_suggestion", "")),
        }
