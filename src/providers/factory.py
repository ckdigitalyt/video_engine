"""
factory.py — A factory for creating provider instances.
"""
import importlib
from typing import Type
from src.utils.config import get_config
from .llm_provider import LLMProvider
from .asset_provider import AssetProvider
from .tts_provider import TTSProvider


class ProviderFactory:
    """
    A factory for creating and managing provider instances.

    This factory ensures that providers are singletons, instantiated only once
    with the correct configuration from the merged YAML files.
    """

    def __init__(self):
        self._providers = {}

    # Mapping from config provider names to actual class names
    _LLM_CLASS_MAP = {
        "deepseek": "DeepSeekProvider",
        "gemini": "GeminiProvider",
        "grok": "GrokProvider",
        "groq": "GroqProvider",
        "openrouter": "OpenRouterProvider",
        "mistral": "MistralProvider",
    }

    def get_llm_provider(self, name: str) -> LLMProvider:
        """
        Get an instance of an LLM provider by name (e.g., "deepseek", "gemini").
        """
        if name not in self._providers:
            class_name = self._LLM_CLASS_MAP.get(name)
            if not class_name:
                raise ValueError(f"Unknown LLM provider name: {name}")
            provider_class = self._get_class(f"src.providers.llm_provider.{class_name}")
            if not issubclass(provider_class, LLMProvider):
                raise TypeError(f"{provider_class} is not a valid LLMProvider")
            
            # Get the model config for this provider
            config = get_config(f"llm.{name}", {})
            self._providers[name] = provider_class(**config)
        return self._providers[name]

    def get_llm_provider_for_role(self, role: str) -> LLMProvider:
        """
        Get the configured LLM provider for a specific role (e.g., "planner", "critic").
        """
        provider_name = get_config(f"pipeline.roles.{role}")
        if not provider_name:
            raise ValueError(f"No LLM provider configured for role: {role}")
        
        return self.get_llm_provider(provider_name)

    def get_default_llm_provider(self) -> LLMProvider:
        """
        Get the default LLM provider from YAML config.
        Defaults to 'gemini' if not configured.
        """
        provider_name = get_config("pipeline.roles.default", "gemini")
        return self.get_llm_provider(provider_name)

    def get_cost_chain_llm_provider(self, primary: str) -> LLMProvider:
        """Build a runtime fallback chain: primary -> gemini/grok/mistral
        (whichever have keys) -> deepseek last.  Lets the pipeline use
        Gemini/Grok as much as possible so DeepSeek cost stays minimal.
        Chain order (configured): primary first, then roles.chain, with
        deepseek always last.
        """
        from src.providers.llm_provider import ChainLLMProvider

        chain_names = [primary]
        for name in get_config("pipeline.roles.chain", ["gemini", "grok", "mistral"]):
            if name not in chain_names:
                chain_names.append(name)
        if "deepseek" not in chain_names:
            chain_names.append("deepseek")

        providers = []
        for name in chain_names:
            try:
                providers.append(self.get_llm_provider(name))
            except Exception:
                # Missing key / unsupported provider — skip, next in chain
                continue
        if not providers:
            raise RuntimeError("No LLM provider available in cost chain")
        if len(providers) == 1:
            return providers[0]
        return ChainLLMProvider(providers)

    def get_fallback_llm_provider(self) -> LLMProvider:
        """
        Get the fallback LLM provider from YAML config.
        Defaults to 'deepseek' if not configured.
        """
        provider_name = get_config("pipeline.roles.fallback", "deepseek")
        return self.get_llm_provider(provider_name)

    def _get_class(self, class_path: str) -> Type:
        """Dynamically import and return a class from a string path."""
        try:
            module_path, class_name = class_path.rsplit('.', 1)
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Could not import class: {class_path}") from e

