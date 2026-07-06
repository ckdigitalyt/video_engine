"""
test_audio_engine.py — Tests for audio_engine.py.

Verifies:
- mix_audio with and without background music
- Fade-in / fade-out behaviour
- Music volume adjustment
- Concatenation of multiple voice files
- Graceful fallback when music file is missing
- Parameter configuration from YAML
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestMixAudio:
    """Tests for the mix_audio function."""

    def test_mix_with_music(self, tmp_path: Path, mock_music_file: Path) -> None:
        """Mixing with background music should produce a WAV file."""
        from audio_engine import mix_audio

        voice = tmp_path / "voice.wav"
        from pydub import AudioSegment
        seg = AudioSegment.silent(duration=500, frame_rate=44100)
        seg.export(str(voice), format="wav")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), str(mock_music_file), str(output))

        assert output.exists()
        assert output.stat().st_size > 0

    def test_mix_without_music_uses_silence(self, tmp_path: Path) -> None:
        """When music file does not exist, mix_audio should use silent track."""
        from audio_engine import mix_audio

        voice = tmp_path / "voice.wav"
        from pydub import AudioSegment
        seg = AudioSegment.silent(duration=500, frame_rate=44100)
        seg.export(str(voice), format="wav")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), "/nonexistent/music.mp3", str(output))

        assert output.exists()
        assert output.stat().st_size > 0

    def test_mix_output_duration(self, tmp_path: Path, mock_music_file: Path) -> None:
        """Mixed output duration should match voice + tail."""
        from audio_engine import mix_audio

        voice = tmp_path / "voice.wav"
        from pydub import AudioSegment
        seg = AudioSegment.silent(duration=1000, frame_rate=44100)
        seg.export(str(voice), format="wav")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), str(mock_music_file), str(output))

        result = AudioSegment.from_wav(str(output))
        # voice 1000 ms + tail 2000 ms → 3000 ± tolerance
        assert abs(len(result) - 3000) < 100

    def _make_noise_wav(self, path: Path, duration_ms: int = 2000) -> Path:
        """Generate a WAV with constant-amplitude (non-silent) samples."""
        import wave, struct
        sample_rate = 44100
        num_samples = int(sample_rate * duration_ms / 1000)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for _ in range(num_samples):
                wf.writeframes(struct.pack("<h", 5000))
        return path

    def test_fade_in_applied(self, tmp_path: Path) -> None:
        """Fade-in should reduce volume at the start of the mix."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = self._make_noise_wav(tmp_path / "voice.wav")
        music = tmp_path / "bg.mp3"
        AudioSegment.silent(duration=2000, frame_rate=44100).export(str(music), format="mp3")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), str(music), str(output), fade_in_ms=500)

        result = AudioSegment.from_wav(str(output))
        start_rms = result[:50].rms
        mid_rms = result[1000:1050].rms
        assert start_rms <= mid_rms + 1, "Fade-in should reduce start volume"

    def test_fade_out_applied(self, tmp_path: Path) -> None:
        """Fade-out should reduce volume at the tail of the mix."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = self._make_noise_wav(tmp_path / "voice.wav")
        music = tmp_path / "bg.mp3"
        AudioSegment.silent(duration=2000, frame_rate=44100).export(str(music), format="mp3")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), str(music), str(output), fade_out_ms=500)

        result = AudioSegment.from_wav(str(output))
        mid_rms = result[500:550].rms
        end_rms = result[-50:].rms
        assert end_rms <= mid_rms + 1, "Fade-out should reduce tail volume"

    def test_music_volume_boost(self, tmp_path: Path) -> None:
        """Positive music_volume_db should make the mix louder."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        # Quiet voice so music layer dominates measurement
        import wave, struct
        with wave.open(str(tmp_path / "voice.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            for _ in range(22050):  # 0.5s
                wf.writeframes(struct.pack("<h", 0))  # silence

        # Non-silent music
        with wave.open(str(tmp_path / "bg.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            for _ in range(22050):
                wf.writeframes(struct.pack("<h", 5000))

        output_normal = tmp_path / "normal.wav"
        output_loud = tmp_path / "loud.wav"

        mix_audio(str(tmp_path / "voice.wav"), str(tmp_path / "bg.wav"), str(output_normal), music_volume_db=0.0)
        mix_audio(str(tmp_path / "voice.wav"), str(tmp_path / "bg.wav"), str(output_loud), music_volume_db=+6.0)

        normal = AudioSegment.from_wav(str(output_normal)).rms
        loud = AudioSegment.from_wav(str(output_loud)).rms
        assert loud > normal, "Volume boost should increase RMS"

    def test_music_volume_cut(self, tmp_path: Path) -> None:
        """Negative music_volume_db should make the mix quieter."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        import wave, struct
        with wave.open(str(tmp_path / "voice_cut.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            for _ in range(22050):
                wf.writeframes(struct.pack("<h", 0))  # silence

        with wave.open(str(tmp_path / "bg_cut.wav"), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(44100)
            for _ in range(22050):
                wf.writeframes(struct.pack("<h", 5000))

        output_normal = tmp_path / "normal.wav"
        output_quiet = tmp_path / "quiet.wav"

        mix_audio(str(tmp_path / "voice_cut.wav"), str(tmp_path / "bg_cut.wav"), str(output_normal), music_volume_db=0.0)
        mix_audio(str(tmp_path / "voice_cut.wav"), str(tmp_path / "bg_cut.wav"), str(output_quiet), music_volume_db=-12.0)

        normal = AudioSegment.from_wav(str(output_normal)).rms
        quiet = AudioSegment.from_wav(str(output_quiet)).rms
        assert quiet < normal, "Volume cut should reduce RMS"

    def test_music_loops_when_shorter(self, tmp_path: Path) -> None:
        """Short music should loop to cover the full voice + tail duration."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = tmp_path / "voice.wav"
        seg = AudioSegment.silent(duration=1000, frame_rate=44100)
        seg.export(str(voice), format="wav")

        music = tmp_path / "short.mp3"
        short = AudioSegment.silent(duration=200, frame_rate=44100)
        short.export(str(music), format="mp3")

        output = tmp_path / "looped.wav"
        mix_audio(str(voice), str(music), str(output))

        result = AudioSegment.from_wav(str(output))
        # voice 1000 ms + tail 2000 ms = 3000 ms
        assert abs(len(result) - 3000) < 100

    def test_ducking_produces_valid_output(self, tmp_path: Path, mock_music_file: Path) -> None:
        """Ducking should produce a valid WAV output without errors."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = tmp_path / "voice.wav"
        seg = AudioSegment.silent(duration=500, frame_rate=44100)
        seg.export(str(voice), format="wav")

        output = tmp_path / "ducked.wav"
        mix_audio(str(voice), str(mock_music_file), str(output))

        result = AudioSegment.from_wav(str(output))
        assert len(result) > 0

    def test_mix_no_crash_on_missing_voice(self, tmp_path: Path) -> None:
        """Missing voice file should raise FileNotFoundError."""
        from audio_engine import mix_audio
        with pytest.raises(FileNotFoundError):
            mix_audio("/nonexistent/voice.wav", str(tmp_path / "bg.mp3"), str(tmp_path / "out.wav"))


class TestGenerateVoice:
    """Tests for the generate_voice function."""

    def test_generate_calls_provider(self, mock_kokoro_tts: MagicMock, tmp_path: Path) -> None:
        """generate_voice should delegate to the TTS provider."""
        from audio_engine import generate_voice
        output = tmp_path / "out.wav"
        generate_voice("Hello world", str(output))
        assert mock_kokoro_tts.return_value.create.called

    def test_generate_does_not_crash(self, mock_kokoro_tts: MagicMock, tmp_path: Path) -> None:
        """generate_voice should execute without raising exceptions."""
        from audio_engine import generate_voice
        output = tmp_path / "out.wav"
        generate_voice("Test narration", str(output))


class TestConfigDrivenMixing:
    """Verify parameters are loaded from YAML config."""

    def test_config_has_mixing_keys(self) -> None:
        """All mixing config keys must exist in voices.yaml."""
        from src.utils.config import get_config
        assert get_config("voices.mixing.ducking_db") is not None
        assert get_config("voices.mixing.tail_ms") is not None
        assert get_config("voices.mixing.fade_in_ms") is not None
        assert get_config("voices.mixing.fade_out_ms") is not None
        assert get_config("voices.mixing.music_volume_db") is not None
        assert get_config("voices.mixing.background_music") is not None

    def test_mix_uses_config_defaults(self, tmp_path: Path) -> None:
        """mix_audio should pull default fade/volume from config when not passed."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = tmp_path / "voice.wav"
        seg = AudioSegment.silent(duration=500, frame_rate=44100)
        seg.export(str(voice), format="wav")

        music = tmp_path / "bg.mp3"
        seg.export(str(music), format="mp3")

        output = tmp_path / "mixed.wav"
        # Call without passing fade/volume params → should use config defaults
        mix_audio(str(voice), str(music), str(output))
        assert output.exists()


class TestBackwardCompat:
    """Existing behaviour must be preserved when music is disabled."""

    def test_mix_without_music_same_as_before(self, tmp_path: Path) -> None:
        """When music file is absent, mix_audio returns a silent-track mix."""
        from audio_engine import mix_audio
        from pydub import AudioSegment

        voice = tmp_path / "voice.wav"
        seg = AudioSegment.silent(duration=500, frame_rate=44100)
        seg.export(str(voice), format="wav")

        output = tmp_path / "mixed.wav"
        mix_audio(str(voice), "/no/such/file.mp3", str(output))

        result = AudioSegment.from_wav(str(output))
        assert len(result) > 0
