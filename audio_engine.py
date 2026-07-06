import os
from pydub import AudioSegment
from src.utils.config import get_config
from src.providers import KokoroProvider

# Shared TTS provider instance (lazy-loaded on first use)
_tts_provider = KokoroProvider()


def generate_voice(text, output_path):
    _tts_provider.generate_voice(text, output_path)


def mix_audio(voice_path, music_path, output_path):
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

    # Loop background music if it is shorter than the voice clip
    if len(music) < len(voice):
        music = music * (len(voice) // len(music) + 1)

    music = music[:len(voice) + tail_ms]  # Add a 2-second tail
    ducked_music = music - ducking_db  # Drop background music by 12 decibels

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
