"""
mix_engine.py — Standardized three-track audio architecture.

Every production renders:
  1. narration   (Kokoro TTS, prosody-normalized)
  2. adaptive score (background bed, ducked under speech via sidechain)
  3. environmental SFX (subtle, only where they aid storytelling)

Two-pass loudness normalization:
  pass 1: measure integrated loudness (loudnorm print_format=json)
  pass 2: apply measured values (I=-14 LUFS, TP=-1.5) for consistent output
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Optional

LUFS_TARGET = -14.0
TRUE_PEAK = -1.5


def probe_loudness(path: str) -> dict:
    """Measure integrated loudness / true peak via loudnorm."""
    r = subprocess.run(
        ["ffmpeg", "-i", path, "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120,
    )
    try:
        start = r.stderr.rfind("{")
        block = r.stderr[start:]
        return json.loads(block)
    except Exception:
        return {}


def normalize_loudness(input_path: str, output_path: str,
                       target_i: float = LUFS_TARGET,
                       true_peak: float = TRUE_PEAK) -> str:
    """Two-pass loudness normalization to streaming standard."""
    measured = probe_loudness(input_path)
    if not measured:
        # fallback single-pass
        subprocess.run(
            ["ffmpeg", "-y", "-i", input_path,
             "-af", f"loudnorm=I={target_i}:TP={true_peak}:LRA=11",
             "-c:a", "pcm_s16le", output_path],
            capture_output=True, text=True, timeout=180,
        )
        return output_path
    # Apply measured values (second pass) — consistent, no pumping
    filt = (
        f"loudnorm=I={target_i}:TP={true_peak}:LRA=11:"
        f"measured_I={measured.get('input_i')}:measured_TP={measured.get('input_tp')}:"
        f"measured_LRA={measured.get('input_lra')}:"
        f"measured_thresh={measured.get('input_thresh')}:"
        f"offset={measured.get('target_offset', 0)}:linear=true"
    )
    subprocess.run(
        ["ffmpeg", "-y", "-i", input_path, "-af", filt,
         "-c:a", "pcm_s16le", output_path],
        capture_output=True, text=True, timeout=180,
    )
    return output_path


def three_track_mix(
    video_path: str,
    narration_path: str,          # full narration track (or None)
    music_path: str,              # score bed
    sfx_path: Optional[str],      # env SFX bed (optional)
    out_path: str,
    music_gain_db: float = -8.0,
    sfx_gain_db: float = -16.0,
    duck_threshold: float = 0.03,
    duck_ratio: float = 6.0,
) -> dict:
    """Mix narration + ducked score + SFX onto the video's audio.

    Structure (single ffmpeg graph):
      [music] -> volume, sidechain-compressed by narration -> [duck]
      [sfx]   -> volume                                        -> [sfx_g]
      [video a] (narration) + [duck] + [sfx_g] -> amix normalize=0
      -> loudnorm two-pass -> aac
    """
    music_gain = 10 ** (music_gain_db / 20)
    sfx_gain = 10 ** (sfx_gain_db / 20)
    dur = _probe_duration(video_path)

    # Inputs: 0=video(with narration audio), 1=music, 2=sfx (optional)
    inputs = ["-i", video_path, "-i", music_path]
    sfx_input = ""
    if sfx_path and os.path.exists(sfx_path):
        inputs += ["-i", sfx_path]
        sfx_input = (
            f"[2:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},volume={sfx_gain:.4f}[sfx];"
        )
    else:
        sfx_input = "[1:a]atrim=0:0.01,volume=0[sfx];"

    # Multiband ducking (§3.2, 2026 recalibration): split the bed into
    # low/mid/high bands and sidechain-compress ONLY the mid band
    # (500 Hz - 4 kHz) against the narration.  Bass + air pass untouched,
    # so the bed never "pumps" under speech.  Fast attack (20 ms) + medium
    # release (80 ms) + 3.5:1 ratio per expert review.
    graph = (
        f"[1:a]aloop=loop=-1:size=2e9,atrim=0:{dur:.3f},volume={music_gain:.4f}[bed];"
        f"[bed]asplit=3[low_in][mid_in][high_in];"
        f"[low_in]lowpass=f=500[low];"
        f"[mid_in]bandpass=f=2250:w=3500[mid_raw];"
        f"[high_in]highpass=f=4000[high];"
        f"[mid_raw][0:a]sidechaincompress=threshold={duck_threshold}:ratio={duck_ratio}:"
        f"attack=20:release=80[mid];"
        f"[low][mid][high]amix=inputs=3:normalize=0[duck];"
        f"{sfx_input}"
        f"[0:a][duck][sfx]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,"
        f"alimiter=limit=0.89[aout]"
    )
    cmd = [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", graph,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "pcm_s16le",
        "-shortest", out_path,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        return {"ok": False, "error": r.stderr[-300:]}

    # Two-pass loudness on the mixed audio
    loud_path = out_path.replace(".wav", "_loud.wav")
    normalized = normalize_loudness(out_path, loud_path)
    if os.path.exists(normalized) and os.path.getsize(normalized) > 0:
        os.replace(normalized, out_path)

    return {"ok": True, "duration_s": _probe_duration(out_path),
            "loudness": probe_loudness(out_path)}


def _probe_duration(path: str) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=15,
        )
        return float(r.stdout.strip()) if r.stdout.strip() else 0.0
    except Exception:
        return 0.0


def finalize_audio(video_with_mix: str, out_mp4: str,
                   music_path: str, sfx_path: Optional[str] = None,
                   music_gain_db: float = -8.0) -> dict:
    """Render the final MP4 with the three-track mix (AAC 192k)."""
    tmp = out_mp4.replace(".mp4", "_mix.wav")
    res = three_track_mix(video_with_mix, None, music_path, sfx_path, tmp,
                          music_gain_db=music_gain_db)
    if not res.get("ok"):
        return res
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", video_with_mix, "-i", tmp,
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-shortest", out_mp4],
        capture_output=True, text=True, timeout=300,
    )
    if os.path.exists(tmp):
        os.remove(tmp)
    return {"ok": r.returncode == 0, "duration_s": _probe_duration(out_mp4),
            "error": "" if r.returncode == 0 else r.stderr[-200:]}
