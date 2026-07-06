"""
validation — Visual quality validation package.

Components:
- SemanticValidator: scores assets for semantic relevance to narration
"""

from .semantic_validator import SemanticValidator

__all__ = ["SemanticValidator"]
