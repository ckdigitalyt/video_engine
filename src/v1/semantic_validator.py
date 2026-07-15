"""
semantic_validator.py — V1 semantic validation for asset-narration matching.
"""

from __future__ import annotations

from typing import Any, Optional

from src.validation.semantic_validator import SemanticValidator as _SemanticValidator


class SemanticValidator:
    """Validates that an asset is semantically relevant to a narration.

    Wraps the existing SemanticValidator from src.validation.
    """

    def __init__(self):
        self._inner = _SemanticValidator()

    def validate(self, asset: dict, narration: str) -> dict[str, Any]:
        """Validate semantic match between asset and narration.

        Returns dict with 'score' (0-1), 'passed', 'reason'.
        """
        result = self._inner.validate(asset, narration)
        if isinstance(result, dict):
            return result
        # Handle case where validate returns (bool, reason) tuple
        return {"score": 0.5, "passed": bool(result), "reason": str(result)}
