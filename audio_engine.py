import os
from typing import Optional

from pydub import AudioSegment
from src.utils.config import get_config
from src.providers import KokoroProvider

# Shared TTS provider instance (lazy-loaded on first use)
_tts_provider = KokoroProvider()


def generate_voice(text: str, output_path: str) -> None:
    _tts_provider.generate_voice(text, output_path)


def mix_audio(
    voice_path: str,
    music_path: str,
    output_path: str,
    fade_in_ms: int = 3000,
    fade_out_ms: int = 3000,
    music_volume_db: float = 0.0,
) -> None:
    """Mix a voiceover WAV with background music.

    Args:
        voice_path: Path to the voiceover WAV file.
        music_path: Path to the background music file.
        output_path: Destination path for the mixed WAV.
        fade_in_ms: Fade-in duration for background music (ms).
        fade_out_ms: Fade-out duration for background music (ms).
        music_volume_db: Additional gain applied to the music track
            before ducking (positive = louder, negative = quieter).
    """
    print("Applying dynamic ducking and mixing...")
    voice = AudioSegment.from_wav(voice_path)
    tail_ms = get_config("voices.mixing.tail_ms", 2000)
    ducking_db = get_config("voices.mixing.ducking_db", -12)

    if os.path.exists(music_path):
        music = AudioSegment.from_file(music_path)
    else:
        print("No background music found. Proceeding with voice only.")
        # Create a dummy silent track for testing if missing
        music = AudioSegment.silent(duration=len(voice) + tail_ms)

    # Loop background music to cover voice + tail
    target_len = len(voice) + tail_ms
    if len(music) < target_len:
        repeats = target_len // len(music) + 1
        music = music * repeats

    music = music[:target_len]  # Trim to target length

    # Apply music volume adjustment (positive = boost, negative = cut)
    if music_volume_db:
        music = music + music_volume_db

    # Apply fade in / out to the music bed
    if fade_in_ms > 0:
        music = music.fade_in(fade_in_ms)
    if fade_out_ms > 0:
        music = music.fade_out(fade_out_ms)

    ducked_music = music - abs(ducking_db)  # Drop background music

    mixed = ducked_music.overlay(voice, position=0)
    mixed.export(output_path, format="wav")
    print(f"Final mixed audio saved to {output_path}")




if __name__ == "__main__":
    cache_audio = get_config("pipeline.cache.audio", "cache/audio")
    cache_music = get_config("pipeline.cache.music", "cache/music")
    os.makedirs(cache_audio, exist_ok=True)
    os.makedirs(cache_music, exist_ok=True)

    # Milestone 2 Test Run
    script_text = "Welcome to Most Amazing Wonders. Today, we journey into the heart of the Fermi Paradox. Are we truly alone in the universe?"

    generate_voice(script_text, f"{cache_audio}/scene_1.wav")
    mix_audio(f"{cache_audio}/scene_1.wav", f"{cache_music}/cinematic.mp3", f"{cache_audio}/final_mix.wav")
