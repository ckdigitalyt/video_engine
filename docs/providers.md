# Provider Architecture

The video_engine pipeline uses a **provider abstraction layer** to decouple
business logic from external API and service implementations.  Every external
interaction (LLM calls, asset search/download, text-to-speech) goes through a
well-defined interface, making it straightforward to swap implementations,
mock during testing, or add new backends.

---

## Interface Overview

| Interface | Methods | Concrete |
|-----------|---------|----------|
| `LLMProvider` | `generate_text()`, `generate_json()` | `ZaiProvider`, `GeminiProvider` |
| `AssetProvider` | `search()`, `download()` | `PexelsProvider` (wrapped by `AssetLibrary`) |
| `TTSProvider` | `generate_voice()` | `KokoroProvider` |

All interfaces live in `src/providers/`.

---

## LLMProvider

**File:** `src/providers/llm_provider.py`

Abstract base class for large-language-model interactions.

```python
class LLMProvider(ABC):
    def generate_text(self, prompt: str, image_path: str | None = None, **kwargs) -> str: ...
    def generate_json(self, prompt: str, **kwargs) -> str: ...
```

- `generate_text` — sends a text prompt (optionally with an image for multimodal backends) and returns the model's response.
- `generate_json` — convenience wrapper that calls `generate_text` and strips JSON fence markers (` ```json ` / ` ``` `).

### ZaiProvider

> 2026-08-30: DeepSeek was retired across the whole repo (user directive:
> "Don't use deepseek at all anywhere") and replaced by ZAI GLM
> (`glm-5.3-flash`) in every chain. Chain lengths are unchanged — GLM took
> DeepSeek's slot in each fallback/cost chain.

Wraps `langchain_openai.ChatOpenAI` pointed at the Z.AI API
(OpenAI-compatible). Used in the Planner node for script generation.

Note: `glm-5.3-flash` always engages in thinking — never send a
`thinking` field (rejected with HTTP 400 code 1210) and set `max_tokens`
generously (reasoning tokens count). Responses carry `reasoning_content`
alongside `content`; only `content` is used.

| Config key | Default |
|------------|---------|
| `llm.zai.model` | `"glm-5.3-flash"` |
| `llm.zai.max_tokens` | `8192` |
| `providers.zai.base_url` | `"https://api.z.ai/api/paas/v4"` |

**Environment:** `ZAI_API_KEY` (optional overrides: `ZAI_BASE_URL`, `ZAI_MODEL`)

### GeminiProvider

Wraps `google.genai.Client` for multimodal frame analysis in the Critic node.
When `image_path` is provided, the image is loaded with PIL and sent as a content part.

Internally calls `client.models.generate_content()` with the configured model name.

| Config key | Default |
|------------|---------|
| `llm.gemini.model` | `"models/gemini-2.5-flash-lite"` |

**Environment:** `GEMINI_API_KEY`

---

## AssetProvider

**File:** `src/providers/asset_provider.py`

Abstract base class for media-asset search and download.

```python
class AssetProvider(ABC):
    def search(self, query: str, **kwargs) -> list: ...
    def download(self, url: str, output_path: str) -> str: ...
```

- `search` — returns a list of result dicts (structure is provider-specific).
- `download` — fetches a remote URL and writes to `output_path`; returns the local path.

### PexelsProvider

Wraps the Pexels video search API (`requests`-based). Used in the Execution
node to find and download background video clips.

| Config key | Default |
|------------|---------|
| `providers.pexels.base_url` | `"https://api.pexels.com/videos/search"` |
| `providers.pexels.per_page` | `5` |
| `providers.pexels.orientation` | `"landscape"` |

**Environment:** `PEXELS_API_KEY`

---

## TTSProvider

**File:** `src/providers/tts_provider.py`

Abstract base class for text-to-speech synthesis.

```python
class TTSProvider(ABC):
    def generate_voice(self, text: str, output_path: str) -> None: ...
```

### KokoroProvider

Wraps the `kokoro_onnx.Kokoro` engine (local ONNX model). The engine is
lazy-loaded on the first call to `generate_voice` so importing the provider
does not block on model loading.

| Config key | Default |
|------------|---------|
| `voices.kokoro.model` | `"kokoro-v0_19.onnx"` |
| `voices.kokoro.voices_bin` | `"voices.bin"` |
| `voices.kokoro.default_voice` | `"bm_george"` |
| `voices.kokoro.speed` | `1.0` |
| `voices.kokoro.language` | `"en-gb"` |

**No environment variables** — Kokoro runs entirely locally.

---

## Adding a New Provider

1. Create a new class in the appropriate `src/providers/*.py` file that
   inherits from the corresponding ABC.
2. Implement all abstract methods.
3. In `orchestrator.py` (or `audio_engine.py`), swap the instantiation.
4. Add any new configuration keys to the relevant `configs/*.yaml` file and
   document them in `docs/configuration.md`.

---

## Package Export

All provider classes are re-exported from `src/providers/__init__.py`:

```python
from .llm_provider import LLMProvider, ZaiProvider, GeminiProvider
from .asset_provider import AssetProvider, PexelsProvider
from .tts_provider import TTSProvider, KokoroProvider
```

Consumer code should import from the package:

```python
from src.providers import ZaiProvider, KokoroProvider
```
