# Testing Guide — video_engine

## Overview

The test suite lives under `tests/` and uses **pytest** as the test runner.  
All external APIs (DeepSeek, Gemini, Pexels, Kokoro) are mocked so tests run
offline, quickly, and without API credentials.

## Running the Suite

```bash
# Activate your virtual environment first
source venv/bin/activate

# Set PYTHONPATH so imports from src/ resolve
export PYTHONPATH="/home/ubuntu/video_engine:$PYTHONPATH"

# Run all tests
pytest -v

# Run a specific test file
pytest tests/test_models.py -v

# Run a specific test class or function
pytest tests/test_config.py::TestRequiredKeys -v

# Run with coverage report (requires pytest-cov)
pytest --cov=src --cov=renderer --cov=audio_engine --cov=orchestrator

# Skip slow tests (anything marked @pytest.mark.slow)
pytest -m 'not slow'

# Run with warnings shown
pytest -W default
```

## Test Files

| File | What It Tests |
|------|---------------|
| `test_config.py` | Configuration loader: required keys, missing files, dot-notation lookup, defaults |
| `test_models.py` | All 15 domain dataclasses: construction, defaults, type hints, serialisation |
| `test_timeline_builder.py` | TimelineBuilder: clock-advance, monotonic timestamps, overlap detection, multi-scene, validation |
| `test_asset_cache.py` | AssetCache: SQLite schema, CRUD, LRU cleanup, integrity, edge cases |
| `test_memory_manager.py` | MemoryManager: all 6 tables, CRUD, indexes, cleanup policy, timestamps |
| `test_provider_interfaces.py` | Provider ABC compliance, mocked DeepSeek/Gemini/Pexels/Kokoro, error propagation |
| `test_renderer.py` | Timeline parsing, compatibility shim, render dispatch, invalid input detection |

## What Is Mocked

All 7 test files avoid calling real services:

| Service | Mock Strategy |
|---------|---------------|
| **DeepSeek** (ChatOpenAI) | `mock_deepseek_llm` fixture patches `langchain_openai.ChatOpenAI` |
| **Gemini** (GenerativeModel) | `mock_gemini_llm` fixture patches `google.generativeai.GenerativeModel` |
| **Pexels** (requests.get) | `mock_pexels_api` fixture patches `requests.get` with canned JSON |
| **Kokoro** (ONNX infer) | `mock_kokoro_tts` fixture patches `kokoro_onnx.Kokoro` + `soundfile.write` |
| **MoviePy** (encoding) | Mocked at `VideoFileClip`/`AudioFileClip`/`CompositeVideoClip` level |
| **pydub** (duration) | `mock_audio_duration` fixture patches `AudioSegment.from_wav` |

## Fixtures (conftest.py)

Shared fixtures available to every test:

| Fixture | Purpose |
|---------|---------|
| `tmp_project` | Temp project directory with minimal config files |
| `tmp_db` | Path to a temp SQLite database |
| `small_wav` | Creates a 0.5s silent WAV file for audio I/O tests |
| `short_video` | Creates a 1s black MP4 via ffmpeg for video I/O tests |
| `mock_env_api_keys` | Sets fake `DEEPSEEK_API_KEY`, `GEMINI_API_KEY`, `PEXELS_API_KEY` |
| `mock_pexels_api` | Patches `requests.get` for Pexels search responses |
| `mock_deepseek_llm` | Patches `ChatOpenAI` for DeepSeek text responses |
| `mock_gemini_llm` | Patches `GenerativeModel` for Gemini critic responses |
| `mock_kokoro_tts` | Patches `Kokoro` + `sf.write` for TTS generation |

## Writing Tests

### Guidelines

1. **Mock external calls** — no test should hit a real API.
2. **Use temp directories** — use pytest's built-in `tmp_path` fixture.
3. **One assertion per concept** — prefer multiple simple tests.
4. **Test edge cases** — empty lists, missing files, zero durations, invalid inputs.
5. **Respect ABC contracts** — every concrete provider must satisfy its interface.
6. **No pipeline state** — tests must not depend on the contents of `cache/` or `final_output.mp4`.

### Example

```python
def test_clock_advances(self, builder, mock_audio_duration):
    """Scene start times should be cumulative."""
    mock_audio_duration.return_value.__len__.return_value = 5000  # 5 s
    assets = [
        SceneAsset(scene_id=1, video_path="/v/1.mp4", audio_path="/a/1.wav"),
        SceneAsset(scene_id=2, video_path="/v/2.mp4", audio_path="/a/2.wav"),
    ]
    result = builder._build(assets)
    assert result["audio_timeline"][1]["start_time"] == 5.0
```

## Configuration

`pytest.ini` lives at the project root and sets:
- `testpaths = tests` — default discovery directory
- `python_files = test_*.py` — file name pattern
- Standard warning filters (suppresses Pillow/MoviePy deprecations)

## Future Improvements

- Add integration tests with real (but isolated) FFmpeg invocations
- Add property-based tests (Hypothesis) for TimelineBuilder
- Add performance benchmarks for cache eviction
- Add CI configuration (GitHub Actions)
