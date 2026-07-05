import json
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip

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
        codec="libx264", 
        audio_codec="aac",
        threads=4,
        preset="fast"
    )

if __name__ == "__main__":
    render_timeline("timeline.json", "output_test.mp4")
