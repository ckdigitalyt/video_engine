"""
conftest.py — Shared fixtures for the video_engine test suite.

All external APIs (ZAI GLM, Gemini, Pexels, Kokoro) are mocked here.
Temp directories are provided for filesystem-backed tests.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator

import pytest
from unittest.mock import MagicMock, patch


# ── Temp-directory fixtures ────────────────────────────────────────────────


@pytest.fixture
def tmp_project(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a temporary project directory with minimal config files.

    Provides a clean project root with a ``configs/`` sub-directory and
    enough YAML to let :func:`~src.utils.config.load_config` succeed.
    """
    config_dir = tmp_path / "configs"
    config_dir.mkdir(parents=True)

    # Minimal config stub so load_config() returns something useful
    min_config = {
        "models.yaml": "llm:\n  zai:\n    model: glm-5.3-flash\n    max_tokens: 8192\n    temperature: 0.7\n  gemini:\n    model: models/gemini-2.5-flash-lite\n",
        "render.yaml": "render:\n  resolution:\n    width: 1920\n    height: 1080\n  fps: 30\n  codec: libx264\n  audio_codec: aac\n  threads: 4\n  preset: fast\nsubtitles:\n  enabled: true\n  font_size: 28\n  bottom_margin: 80\n  color: \"#FFFFFF\"\n  outline: \"#000000\"\n  shadow: \"#000000\"\n  max_words_per_line: 4\n  animation: fade\n  min_silence_ms: 200\n  silence_thresh: -40\neffects:\n  random_seed: 42\n  motion:\n    enabled: true\n    strength: 0.08\n    probability: 0.85\n  transitions:\n    enabled: true\n    default_transition: crossfade\n    transition_duration: 0.5\noutput:\n  default: final_output.mp4\n",
        "pipeline.yaml": "pipeline:\n  max_iterations: 3\n  cache:\n    video: cache/video\n    audio: cache/audio\n  fallback:\n    video: cache/video/none.mp4\n  output:\n    default: final_output.mp4\n  cache_db: cache/asset_cache.db\n  cache_max_size_mb: 500\n  memory:\n    db_path: cache/memory.db\n    retention_days: 90\n    max_execution_logs: 1000\n    cleanup_interval_runs: 10\n  critic:\n    frame_extraction_ss: \"00:00:02\"\n    eval_frame: cache/video/eval_frame.jpg\n",
        "providers.yaml": "providers:\n  pexels:\n    base_url: https://api.pexels.com/videos/search\n    per_page: 5\n    orientation: landscape\n    reuse:\n      enabled: true\n      similarity_threshold: 0.45\n      max_candidates: 5\n  zai:\n    base_url: https://api.z.ai/api/paas/v4\n",
        "voices.yaml": "voices:\n  kokoro:\n    model: kokoro-v0_19.onnx\n    voices_bin: voices.bin\n    default_voice: bm_george\n    speed: 1.0\n    language: en-gb\n  mixing:\n    ducking_db: -12\n    tail_ms: 2000\n    fade_in_ms: 3000\n    fade_out_ms: 3000\n    music_volume_db: 0.0\n    background_music: cache/music/cinematic.mp3\n",
        "logging.yaml": "logging:\n  level: INFO\n  file: logs/video_engine.log\n  format: \"%(asctime)s - %(name)s - %(levelname)s - %(message)s\"\n",
        "planner.yaml": "planner:\n  story_template: documentary\n  target_scene_count: 10\n  target_duration: 120\n  words_per_second: 3\n  narration_style: informative but conversational\n  search_query_style: descriptive, landscape stock footage terms\n  story_templates:\n    documentary:\n      roles:\n        - \"Hook — Open with a compelling question or startling fact\"\n        - \"Context — Provide background and set the stage\"\n        - \"Exploration — Dive deeper with evidence and examples\"\n        - \"Climax — Present the core revelation or key insight\"\n        - \"Conclusion — Summarise and leave the audience thinking\"\n      description: Classic documentary arc: hook to context to exploration to climax to conclusion.\n",
        "evaluator.yaml": "evaluator:\n  output_dir: eval_reports\n  default_formats:\n    - json\n    - csv\n    - md\n  metrics:\n    performance: true\n    assets: true\n    scenes: true\n    subtitles: true\n    effects: true\n    output: true\n    critic: true\n",
    }
    for name, content in min_config.items():
        (config_dir / name).write_text(content)

    cwd = Path.cwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(cwd)


@pytest.fixture
def tmp_db(tmp_path: Path) -> Generator[Path, None, None]:
    """Return a path to a temporary SQLite database that is cleaned up."""
    db = tmp_path / "test.db"
    yield db
    if db.exists():
        db.unlink()


@pytest.fixture
def small_wav(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a tiny valid WAV file (mono, 16-bit, 44100 Hz, 0.5 s)."""
    import struct
    import wave

    path = tmp_path / "test_audio.wav"
    sample_rate = 44100
    duration = 0.5
    num_samples = int(sample_rate * duration)

    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        for _ in range(num_samples):
            wf.writeframes(struct.pack("<h", 0))  # silent sample

    yield path
    if path.exists():
        path.unlink()


@pytest.fixture
def short_video(tmp_path: Path) -> Generator[Path, None, None]:
    """Create a tiny valid MP4 file (black frame, 1 second, 30 fps).

    Requires ffmpeg on PATH.
    """
    import subprocess

    path = tmp_path / "test_video.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            "color=c=black:s=160x120:d=1:r=30",
            "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(path),
        ],
        capture_output=True,
    )
    yield path
    if path.exists():
        path.unlink()


# ── Audio mixing fixtures ──────────────────────────────────────────────────


@pytest.fixture
def mock_music_file(tmp_path: Path) -> Path:
    """Create a tiny valid MP3 file for background music tests."""
    from pydub import AudioSegment
    path = tmp_path / "bg_music.mp3"
    seg = AudioSegment.silent(duration=1000, frame_rate=44100)
    seg.export(str(path), format="mp3")
    return path


@pytest.fixture
def mock_voice_wav(tmp_path: Path) -> Path:
    """Create a tiny valid WAV file (0.2 sec, silence)."""
    from pydub import AudioSegment
    path = tmp_path / "voice.wav"
    seg = AudioSegment.silent(duration=200, frame_rate=44100)
    seg.export(str(path), format="wav")
    return path


# ── External-API mocks ─────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def mock_env_api_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Provide fake API keys for every external service.

    This ensures tests never accidentally hit a live endpoint even if a
    credential is set in the real environment.
    """
    monkeypatch.setenv("ZAI_API_KEY", "sk-test-zai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("PEXELS_API_KEY", "test-pexels-key")
    monkeypatch.setenv("PIXABAY_API_KEY", "test-pixabay-key")


@pytest.fixture
def mock_pexels_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock the ``requests.get`` call inside PexelsProvider.search().

    Also sets realistic-looking API keys so that ``_is_provider_ready``
    doesn't skip providers during testing.
    """
    monkeypatch.setenv("PEXELS_API_KEY", "test_pexels_key_12345")
    monkeypatch.setenv("PIXABAY_API_KEY", "test_pixabay_key_12345")
    monkeypatch.setenv("NASA_API_KEY", "test_nasa_key_12345")

    mock = MagicMock()
    mock.return_value.json.return_value = {
        "videos": [
            {
                "id": 1,
                "video_files": [
                    {"link": "https://test.pexels.com/video.mp4", "quality": "hd"}
                ],
            }
        ]
    }
    import src.providers.asset_provider
    monkeypatch.setattr(src.providers.asset_provider.requests, "get", mock)
    return mock


@pytest.fixture
def mock_pixabay_api(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Mock the ``requests.get`` call inside PixabayProvider.search().

    Also sets realistic-looking API keys for _is_provider_ready checks.
    """
    monkeypatch.setenv("PIXABAY_API_KEY", "test_pixabay_key_12345")
    monkeypatch.setenv("NASA_API_KEY", "test_nasa_key_12345")
    mock = MagicMock()
    mock.return_value.json.return_value = {
        "hits": [
            {
                "id": 999,
                "duration": 8,
                "tags": "nature, forest, trees",
                "views": 5000,
                "downloads": 200,
                "user": "testuser",
                "videos": {
                    "large": {
                        "url": "https://test.pixabay.com/video_large.mp4",
                        "width": 1920,
                        "height": 1080,
                        "size": 3000000,
                    },
                    "medium": {
                        "url": "https://test.pixabay.com/video_medium.mp4",
                        "width": 1280,
                        "height": 720,
                        "size": 1500000,
                    },
                    "small": {
                        "url": "https://test.pixabay.com/video_small.mp4",
                        "width": 640,
                        "height": 360,
                        "size": 500000,
                    },
                },
            }
        ]
    }
    import src.providers.asset_provider
    monkeypatch.setattr(src.providers.asset_provider.requests, "get", mock)
    return mock


@pytest.fixture
def mock_zai_llm() -> Generator[MagicMock, None, None]:
    """Mock the ZAI GLM LangChain call."""
    with patch("src.providers.llm_provider.ChatOpenAI") as mock:
        instance = MagicMock()
        instance.invoke.return_value.content = '{"scenes": []}'
        mock.return_value = instance
        yield mock


@pytest.fixture
def mock_gemini_llm() -> Generator[MagicMock, None, None]:
    """Mock the Gemini client (google.genai SDK)."""
    with patch("src.providers.llm_provider.genai.Client") as mock:
        client_instance = MagicMock()
        response = MagicMock()
        response.text = "APPROVED"
        client_instance.models.generate_content.return_value = response
        mock.return_value = client_instance
        yield mock


@pytest.fixture
def mock_kokoro_tts() -> Generator[MagicMock, None, None]:
    """Mock the Kokoro TTS engine so it never loads ONNX models."""
    with (
        patch("src.providers.tts_provider.Kokoro") as mock_kokoro,
        patch("src.providers.tts_provider.sf.write") as mock_write,
    ):
        engine_instance = MagicMock()
        engine_instance.create.return_value = ([0] * 44100, 44100)
        mock_kokoro.return_value = engine_instance
        yield mock_kokoro


@pytest.fixture
def mock_subtitle_wav(tmp_path: Path) -> Path:
    """Create a minimal valid WAV file for subtitle timing tests."""
    import wave, struct
    path = tmp_path / "narration.wav"
    sample_rate = 44100
    num_samples = int(sample_rate * 0.5)  # 0.5 s
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for _ in range(num_samples):
            wf.writeframes(struct.pack("<h", 5000))
    return path
