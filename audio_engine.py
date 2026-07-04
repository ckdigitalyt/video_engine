import os
import soundfile as sf
from kokoro_onnx import Kokoro
from pydub import AudioSegment

def generate_voice(text, output_path):
    print("Loading Kokoro TTS engine...")
    kokoro = Kokoro("kokoro-v0_19.onnx", "voices.bin")
    
    print(f"Synthesizing speech: '{text[:40]}...'")
    # Using bm_george (British male) for the documentary feel
    samples, sample_rate = kokoro.create(text, voice="bm_george", speed=1.0, lang="en-gb")
    sf.write(output_path, samples, sample_rate)
    print(f"Voice track saved to {output_path}")

def mix_audio(voice_path, music_path, output_path):
    print("Applying dynamic ducking and mixing...")
    voice = AudioSegment.from_wav(voice_path)
    
    if os.path.exists(music_path):
        music = AudioSegment.from_file(music_path)
    else:
        print("No background music found. Proceeding with voice only.")
        # Create a dummy silent track for testing if missing
        music = AudioSegment.silent(duration=len(voice) + 2000)

    # Loop background music if it is shorter than the voice clip
    if len(music) < len(voice):
        music = music * (len(voice) // len(music) + 1)
        
    music = music[:len(voice) + 2000] # Add a 2-second tail
    ducked_music = music - 12 # Drop background music by 12 decibels
    
    mixed = ducked_music.overlay(voice, position=0)
    mixed.export(output_path, format="wav")
    print(f"Final mixed audio saved to {output_path}")

if __name__ == "__main__":
    os.makedirs("cache/audio", exist_ok=True)
    os.makedirs("cache/music", exist_ok=True)
    
    # Milestone 2 Test Run
    script_text = "Welcome to Most Amazing Wonders. Today, we journey into the heart of the Fermi Paradox. Are we truly alone in the universe?"
    
    generate_voice(script_text, "cache/audio/scene_1.wav")
    mix_audio("cache/audio/scene_1.wav", "cache/music/cinematic.mp3", "cache/audio/final_mix.wav")
