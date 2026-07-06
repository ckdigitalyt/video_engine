import json

# ── Pillow / MoviePy compatibility shim ──────────────────────────────────
# Pillow >= 11 removed the deprecated Image.ANTIALIAS constant.
# MoviePy 1.0.3 still references it in video/fx/resize.py.
# We alias the current LANCZOS resampling filter so MoviePy works unchanged
# with the latest Pillow.  This shim must run before any moviepy import.
#
# Future: upgrade to MoviePy >= 2.x which has a completely refactored API
# and no longer depends on PIL.Image.ANTIALIAS.
import PIL.Image
if not hasattr(PIL.Image, "ANTIALIAS"):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS

from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip
from src.utils.config import get_config

def render_timeline(json_path, output_path):
    with open(json_path, 'r') as f:
        timeline = json.load(f)

    target_res = tuple(timeline['render_settings']['resolution'])

    audio_clips = []
    for audio in timeline['audio_timeline']:
        clip = AudioFileClip(audio['file']).set_start(audio['start_time'])
        audio_clips.append(clip)

    video_clips = []
    for video in timeline['video_timeline']:
        # Enforce the resolution contract on the incoming asset
        clip = VideoFileClip(video['file']).resize(newsize=target_res)
        clip = clip.set_start(video['start_time']).set_end(video['end_time'])
        video_clips.append(clip)

    final_audio = CompositeAudioClip(audio_clips)
    final_video = CompositeVideoClip(video_clips, size=target_res).set_audio(final_audio)

    print(f"Rendering {output_path} on CPU...")
    final_video.write_videofile(
        output_path, 
        fps=timeline['render_settings']['fps'], 
        codec=get_config("render.codec", "libx264"), 
        audio_codec=get_config("render.audio_codec", "aac"),
        threads=get_config("render.threads", 4),
        preset=get_config("render.preset", "fast")
    )

if __name__ == "__main__":
    render_timeline("timeline.json", "output_test.mp4")
