"""
llm_provider.py — Abstract LLM provider and concrete implementations.

Defines the LLMProvider interface, then implements:
- DeepSeekProvider (planning / script generation)
- GeminiProvider (multimodal critic evaluation)
"""

import os
from abc import ABC, abstractmethod
from typing import Optional

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage

import google.generativeai as genai
import PIL.Image

from src.utils.config import get_config


# ── Abstract base ──────────────────────────────────────────────────────────

class LLMProvider(ABC):
    """Interface for large-language-model providers."""

    @abstractmethod
    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        """
        Send a prompt (and optional image) to the LLM and return the text response.

        Subclasses that do not support images should ignore *image_path*.
        """
        ...

    def generate_json(self, prompt: str, **kwargs) -> str:
        """
        Convenience wrapper: calls generate_text and strips JSON fence markers.

        The default implementation should be sufficient for most providers.
        """
        raw = self.generate_text(prompt, **kwargs)
        return raw.replace("```json", "").replace("```", "").strip()


# ── DeepSeek ───────────────────────────────────────────────────────────────

class DeepSeekProvider(LLMProvider):
    """LLM provider backed by DeepSeek Chat via LangChain's ChatOpenAI."""

    def __init__(self):
        self._llm = ChatOpenAI(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=get_config("providers.deepseek.base_url", "https://api.deepseek.com"),
            model=get_config("llm.deepseek.model", "deepseek-chat"),
            max_tokens=get_config("llm.deepseek.max_tokens", 1000),
        )

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        response = self._llm.invoke([HumanMessage(content=prompt)])
        return response.content


# ── Gemini ─────────────────────────────────────────────────────────────────

class GeminiProvider(LLMProvider):
    """LLM provider backed by Google Gemini (used for multimodal critic)."""

    def __init__(self):
        genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
        model_name = get_config("llm.gemini.model", "gemini-1.5-flash")
        self._model = genai.GenerativeModel(model_name)

    def generate_text(self, prompt: str, image_path: Optional[str] = None, **kwargs) -> str:
        if image_path and os.path.exists(image_path):
            img = PIL.Image.open(image_path)
            contents = [prompt, img]
        else:
            contents = [prompt]

        response = self._model.generate_content(contents)
        return response.text.strip()
