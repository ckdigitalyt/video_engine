"""V6 3-layer audio architecture: narration + continuous bed + SFX.

Brief P0:
  1. NARRATION        - dominant; never ducked out of dominance
  2. CONTINUOUS BED   - one video-level ambience/music bed, cross-cuts
                         must not restart it; ~300-1000ms crossfade if it
                         must change
  3. SFX              - shot-specific, editorial reason only; not the bed

Brief P0 narration ducking:
  - narration is the dominant layer
  - bed underneath is automatically ducked when narration is present
  - smooth recovery on narration pauses (no pumping, no abrupt level change)
  - keep current loudness-normalization strategy (composev2 uses loudnorm
    I=-14:TP=-1.5:LRA=11)

Output: a single mixed .wav at 44.1k stereo, ready for AAC encoding.

This module is the AUTHORITATIVE mixer. The legacy composev2.make_audio_master
falls back to a flat narration-only master if no bed is provided; V6 callers
should use audio_mix.mix(...) which enforces the 3-layer contract.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

# Bed change crossfade (ms) — brief: 300-1000ms depending on material
BED_CROSSFADE_MS = 600

# Ducking parameters (ffmpeg sidechaincompress)
#   threshold  - dB below which the bed starts ducking
#   ratio      - 6:1 means a 6 dB rise above threshold -> 1 dB rise in bed
#   attack     - 20ms (quick response to narration onset)
#   release    - 800ms (smooth recovery on narration pauses)
#   makeup     - 0dB (bed natural level after duck)
DUCK_THRESHOLD = "-18dB"
DUCK_RATIO = "6"
# V11 P1 §9 — gentler ducking for intentional SFX: yields under speech,
# keeps its punch in pauses.
SFX_DUCK_THRESHOLD = "-30dB"
SFX_DUCK_RATIO = "2"
DUCK_ATTACK_MS = 20
DUCK_RELEASE_MS = 800
DUCK_MAKEUP = "0dB"

# Final loudness target — must match composev2 (so V5 and V6 outputs have
# the same perceived loudness)
LOUDNORM = "I=-14:TP=-1.5:LRA=11"


def _run(cmd, **kw):
    """Run a subprocess, raise on non-zero, return CompletedProcess."""
    p = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if p.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(str(c) for c in cmd)}\n{p.stderr[-1500:]}")
    return p


def _probe_duration(path: Path) -> float:
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "csv=p=0", str(path)])
    return float(p.stdout.strip())


def _make_silence(out: Path, duration_s: float, sr: int = 44100) -> None:
    _run(["ffmpeg", "-nostdin", "-y", "-f", "lavfi",
          "-i", f"anullsrc=r={sr}:cl=stereo", "-t", f"{duration_s:.3f}", str(out)])


def _normalize_bed(bed_in: Path, bed_out: Path, target_lufs: float = -24.0,
                   sr: int = 44100) -> None:
    """Two-pass loudnorm the bed to a low target so ducking still leaves
    the bed audible. -24 LUFS is a typical ambience level."""
    pass1 = bed_out.with_suffix(".pass1.wav")
    _run(["ffmpeg", "-nostdin", "-y", "-i", str(bed_in),
          "-af", f"loudnorm=I={target_lufs}:TP=-2:LRA=11:print_format=json",
          "-f", "null", "-"], check=True)
    # Two-pass would require parsing the JSON; for V6 we use single-pass
    # with a target the bed is mixed to (the mastering loudnorm at the
    # end applies the final correction).
    _run(["ffmpeg", "-nostdin", "-y", "-i", str(bed_in),
          "-af", f"loudnorm=I={target_lufs}:TP=-2:LRA=11",
          "-ar", str(sr), "-ac", "2", str(bed_out)])


def _concat_beds(beds: list, out: Path, total_s: float = 0.0,
                 shot_durations: list = None,
                 crossfade_ms: int = BED_CROSSFADE_MS) -> Path:
    """Build ONE continuous bed for the full video duration.

    Rules (brief P0):
      - If ALL entries are None (no bed), emit a silence wav of total_s.
      - If a single bed file is used everywhere, pad/trim it to total_s.
      - If multiple bed files are listed (planned changes), use acrossfade
        at the seams. We do NOT synthesize silence in between (gaps are
        a continuity failure detected by audio_continuity, not papered
        over).
    """
    out = Path(out)
    if not beds or all(b is None for b in beds):
        _make_silence(out, total_s or 0.0)
        return out
    real_beds = [b for b in beds if b is not None]
    unique_beds = []
    for b in real_beds:
        if not unique_beds or unique_beds[-1] != b:
            unique_beds.append(b)
    if len(unique_beds) == 1:
        bed = unique_beds[0]
        _run(["ffmpeg", "-nostdin", "-y", "-i", bed,
              "-t", f"{total_s:.3f}", "-ar", "44100", "-ac", "2",
              "-c:a", "pcm_s16le", str(out)])
        return out
    # Multiple distinct beds: trim each to its segment length, then
    # acrossfade. Segment lengths come from shot_durations (per-shot);
    # the segment for bed[i] spans the consecutive shots where beds[i]
    # was active. Falls back to flat 5s/segment if shot_durations is None
    # (smoke / sandbox).
    n = len(unique_beds)
    cmd = ["ffmpeg", "-nostdin", "-y"]
    for b in unique_beds:
        cmd += ["-i", b]
    seg_durs = _bed_segment_durations(beds, unique_beds, shot_durations or [])
    filter_parts = []
    for i, dur in enumerate(seg_durs):
        filter_parts.append(f"[{i}:a]atrim=0:{dur:.3f},asetpts=PTS-STARTPTS[a{i}]")
    prev = "a0"
    for i in range(1, n):
        out_label = f"a{i:02d}" if i < n - 1 else "aout"
        cf = crossfade_ms / 1000.0
        filter_parts.append(
            f"[{prev}][a{i}]acrossfade=d={cf:.3f}:c1=tri:c2=tri[{out_label}]")
        prev = out_label
    cmd += ["-filter_complex", ";".join(filter_parts),
            "-map", "[aout]", "-ar", "44100", "-ac", "2",
            "-c:a", "pcm_s16le", str(out)]
    _run(cmd)
    return out


def _bed_segment_durations(beds: list, unique_beds: list,
                           shot_durations: list) -> list:
    """For each unique bed, the total duration of the consecutive shots
    where it was the active bed. Sum of per-shot durations in that run."""
    segs = []
    cur_bed = None
    cur_total = 0.0
    for i, b in enumerate(beds):
        d = shot_durations[i] if i < len(shot_durations) else 5.0
        if b != cur_bed:
            if cur_bed is not None:
                segs.append(cur_total)
            cur_bed = b
            cur_total = 0.0
        cur_total += float(d)
    if cur_bed is not None:
        segs.append(cur_total)
    if not segs and unique_beds:
        segs = [5.0] * len(unique_beds)
    return segs


def _concat_sfx(sfx: list, shot_durations: list, total_s: float,
                out: Path) -> Path:
    """Lay each SFX at its shot's start time onto a silence track of the
    full video duration. Output is 44.1k stereo, total length total_s."""
    sil = out.with_suffix(".silence.wav")
    _make_silence(sil, total_s)
    if not sfx:
        return sil
    inputs = [str(sil)]
    for s in sfx:
        inputs.append(str(s["file"]))
    # adelay each SFX by (shot_start * 1000) ms, then amix
    # Layout: [0]silence, [1..N]sfx, each delayed by shot_t0
    filter_parts = []
    delayed_labels = []
    for i, s in enumerate(sfx, start=1):
        delay_ms = int(round(float(s["at"]) * 1000.0))
        label = f"d{i}"
        filter_parts.append(f"[{i}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        delayed_labels.append(f"[{label}]")
    mix_inputs = "[0:a]" + "".join(delayed_labels)
    filter_parts.append(
        f"{mix_inputs}amix=inputs={1 + len(sfx)}:duration=first:dropout_transition=0,"
        f"aresample=44100[out]")
    cmd = ["ffmpeg", "-nostdin", "-y", "-i", str(sil)]
    for s in sfx:
        cmd += ["-i", str(s["file"])]
    cmd += ["-filter_complex", ";".join(filter_parts),
            "-map", "[out]", "-ar", "44100", "-ac", "2", str(out)]
    _run(cmd)
    return out


def _concat_narration(beats: list, shot_durations: list, total_s: float,
                      out: Path) -> Path:
    """Concat the per-beat narration wavs, pad with `silence_pad` between
    beats. The pad is small (0.2s) so a 'blow-through' feel remains but
    there is no dead gap that would let the bed swell unnaturally."""
    if not beats:
        return None
    pad = 0.2
    inputs = []
    for b in beats:
        if b.get("file"):
            inputs.append(b["file"])
    if not inputs:
        return None
    # Build a small concat list (each beat, then a short silence pad)
    list_path = out.with_suffix(".txt")
    sil = out.parent / "_sil_pad.wav"
    _make_silence(sil, pad)
    lines = []
    for b in beats:
        if b.get("file"):
            # concat demuxer resolves file paths relative to the list file,
            # not the CWD — use absolute paths to be safe
            abs_p = Path(b["file"]).resolve()
            lines.append(f"file '{abs_p}'")
            lines.append(f"file '{sil.resolve()}'")
    list_path.write_text("\n".join(lines) + "\n")
    _run(["ffmpeg", "-nostdin", "-y", "-f", "concat", "-safe", "0",
          "-i", str(list_path), "-ar", "44100", "-ac", "2", str(out)])
    return out


def mix(narration_beats: list, bed_files: list, sfx: list,
        shot_durations: list, total_s: float, out_wav: Path,
        bed_pad_each: float = 0.0,
        story_type: str = None, intensities: list = None) -> dict:
    """Build the final 3-layer audio mix.

    Args:
      narration_beats: list of {file, duration} dicts (one per beat, in order)
      bed_files:       list of bed file Paths, one per shot (None = continue
                        previous bed). Bed is cross-faded only at the seams
                        where the file changes.
      sfx:             list of {file, at, dur} dicts; SFX are laid at
                        `at` (seconds from shot start) on a full-duration
                        silence track and amixed.
      shot_durations:  list of per-shot durations (seconds)
      total_s:         total video duration in seconds
      out_wav:         output wav path (44.1k stereo)

    Returns:
      { "narration": path, "bed": path, "sfx": path, "mixed": path,
        "bed_segments": [(shot_idx, file, crossfade_in_ms), ...] }
    """
    out_wav = Path(out_wav)
    work = out_wav.parent
    work.mkdir(parents=True, exist_ok=True)

    # 1) Concat the bed (one continuous ambience/music, crossfade on changes)
    bed_path = work / "v6_bed.wav"
    _concat_beds(bed_files, bed_path, total_s=total_s,
                 shot_durations=shot_durations)

    # 2) Lay SFX on a full-duration silence track
    sfx_path = work / "v6_sfx.wav"
    _concat_sfx(sfx or [], shot_durations, total_s, sfx_path)

    # 3) Concat narration (with small pad)
    nar_path = work / "v6_narration.wav"
    _concat_narration(narration_beats, shot_durations, total_s, nar_path)

    # 3b) V9 4-stem procedural mix (flag-gated; ANY failure falls back to
    # the V6 graph below so audio can never hard-fail a render):
    #   L1 voice      - mastered to -14 LUFS (loudnorm)
    #   L2 underscore - procedural documentary bed, gain pegged per shot to
    #                   the planv8 intensity tier, ducked -16 dB under the
    #                   narration (250 ms attack / 500 ms release, exact
    #                   envelope math in procedural_audio)
    #   L3 sfx        - existing event-synced whoosh/tick/pulse track
    #   L4 ambience   - low-level room tone by story_grammar key
    _v9 = False
    try:
        from engine import flags as _fl
        _v9 = bool(_fl.audio9())
    except Exception:
        _v9 = False
    if _v9:
        try:
            from engine import procedural_audio as proc
            from engine.story_grammar import grammar_key as _gkey
            voice = None
            if nar_path:
                voice = work / "v9_voice.wav"
                _run(["ffmpeg", "-nostdin", "-y", "-i", str(nar_path),
                      "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
                      "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
                      str(voice)])
            und = work / "v9_underscore.wav"
            proc.write_underscore(total_s, intensities, shot_durations, und)
            undd = work / "v9_underscore_ducked.wav"
            proc.duck_under(voice, und, undd)
            amb = work / "v9_ambience.wav"
            proc.write_ambience(total_s, _gkey(story_type or ""), amb)
            # V11 P1 §9 — the SFX stem ducks under narration too
            sfx_stem = None
            if sfx and sfx_path:
                if voice:
                    sfxd = work / "v9_sfx_ducked.wav"
                    proc.duck_under(voice, sfx_path, sfxd)
                    sfx_stem = sfxd
                else:
                    sfx_stem = sfx_path
            pre = work / "v9_premaster.wav"
            proc.sum_stems([(voice, 1.0) if voice else None,
                            (undd, 1.0),
                            (amb, 1.0),
                            (sfx_stem, 1.0) if sfx_stem else None],
                           total_s, pre)
            _run(["ffmpeg", "-nostdin", "-y", "-i", str(pre),
                  "-af", f"loudnorm={LOUDNORM},"
                         "alimiter=limit=0.95:attack=5:release=80:"
                         "level=disabled",
                  "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le",
                  str(out_wav)])
            return {
                "narration": str(nar_path) if nar_path else None,
                "bed": None,
                "sfx": str(sfx_path) if sfx and sfx_path else None,
                "mixed": str(out_wav),
                "sfx_ducked": bool(voice and sfx and sfx_path),
                "v9_stems": {
                    "voice": str(voice) if voice else None,
                    "underscore": str(undd),
                    "ambience": str(amb),
                    "grammar": _gkey(story_type or ""),
                    "duck_db": proc.DUCK_DB,
                    "attack_ms": int(proc.DUCK_ATTACK_S * 1000),
                    "release_ms": int(proc.DUCK_RELEASE_S * 1000),
                    "intensities": list(intensities or []),
                },
            }
        except Exception as e:  # pragma: no cover — safety net
            print(f"audio_mix: V9 4-stem mix failed ({type(e).__name__}: {e})"
                  f" — falling back to the V6 mix")
            _v9 = False

    # 4) Mix narration + (bed-under-narration) + sfx
    #    Bed is sidechain-compressed by narration: when narration is present
    #    the bed ducks; when narration is silent the bed recovers smoothly.
    inputs = []
    if nar_path:
        inputs.append(str(nar_path))
    if bed_path:
        inputs.append(str(bed_path))
    if sfx_path and sfx:
        inputs.append(str(sfx_path))
    n_in = len(inputs)
    if n_in == 0:
        _make_silence(out_wav, total_s)
        return {"mixed": str(out_wav)}

    cmd = ["ffmpeg", "-nostdin", "-y"]
    for inp in inputs:
        cmd += ["-i", inp]
    # Index labels
    nar_idx = 0 if nar_path else None
    bed_idx = 1 if (nar_path and bed_path) else (0 if bed_path and not nar_path else None)
    sfx_idx = None
    if nar_path and bed_path and sfx and sfx_path:
        sfx_idx = 2
    elif (nar_path and not bed_path and sfx and sfx_path):
        sfx_idx = 1
    elif (not nar_path and bed_path and sfx and sfx_path):
        sfx_idx = 1

    # Build the filter graph
    parts = []
    sfx_ducked = False
    # V11 P1 §9 — audio hierarchy: NARRATION > intentional SFX. The SFX
    # stem sidechain-ducks under narration (gentler than the bed: 2:1),
    # so transients still punctuate pauses but never mask speech.
    if bed_path and nar_path is not None:
        # Sidechain: bed ducks when narration is loud.
        # sidechaincompress consumes [main][sidechain] and produces a new
        # output stream. We use asplit to produce two copies of the narration
        # (one for the amix output, one as the sidechain key) so labels
        # are never reused. Numeric labels (0xaa etc.) avoid the
        # underscore-stream-specifier parser quirk some ffmpeg builds have.
        if sfx_idx is not None:
            graph = (
                f"[{nar_idx}:a]aresample=44100,asplit=3[0xa1][0xa2][0xa3];"
                f"[{bed_idx}:a]aresample=44100[0xb1];"
                f"[{sfx_idx}:a]aresample=44100[0xc1];"
                f"[0xb1][0xa2]sidechaincompress="
                f"threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
                f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}:"
                f"makeup={DUCK_MAKEUP}[0xd1];"
                f"[0xc1][0xa3]sidechaincompress="
                f"threshold={SFX_DUCK_THRESHOLD}:ratio={SFX_DUCK_RATIO}:"
                f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}:"
                f"makeup={DUCK_MAKEUP}[0xd2];"
                f"[0xd1][0xd2][0xa1]amix=inputs=3:duration=first:"
                f"dropout_transition=0[0xe1]"
            )
            sfx_ducked = True
        else:
            graph = (
                f"[{nar_idx}:a]aresample=44100,asplit=2[0xa1][0xa2];"
                f"[{bed_idx}:a]aresample=44100[0xb1];"
                f"[0xb1][0xa2]sidechaincompress="
                f"threshold={DUCK_THRESHOLD}:ratio={DUCK_RATIO}:"
                f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}:"
                f"makeup={DUCK_MAKEUP}[0xd1];"
                f"[0xd1][0xa1]amix=inputs=2:duration=first:"
                f"dropout_transition=0[0xe1]"
            )
            sfx_ducked = False
    elif nar_path is not None and sfx and sfx_path:
        # V11 P1 §9 default case: narration + intentional SFX, bed-free —
        # the SFX stem still ducks under the narration (hierarchy:
        # NARRATION > intentional SFX > silence).
        graph = (
            f"[{nar_idx}:a]aresample=44100,asplit=2[0xa1][0xa2];"
            f"[{sfx_idx}:a]aresample=44100[0xc1];"
            f"[0xc1][0xa2]sidechaincompress="
            f"threshold={SFX_DUCK_THRESHOLD}:ratio={SFX_DUCK_RATIO}:"
            f"attack={DUCK_ATTACK_MS}:release={DUCK_RELEASE_MS}:"
            f"makeup={DUCK_MAKEUP}[0xd2];"
            f"[0xd2][0xa1]amix=inputs=2:duration=first:"
            f"dropout_transition=0[0xe1]"
        )
        sfx_ducked = True
    else:
        # No narration: just mix bed + sfx
        labels = []
        graph_parts = []
        for i in range(n_in):
            graph_parts.append(f"[{i}:a]aresample=44100[0x{i}a]")
            labels.append(f"[0x{i}a]")
        graph = ";".join(graph_parts) + ";" + (
            "".join(labels) + f"amix=inputs={n_in}:duration=first:"
            f"dropout_transition=0[0xee]"
        )

    # Final loudness normalization (matches composev2)
    graph += (
        f";[0xe1]loudnorm={LOUDNORM}:print_format=summary,"
        f"alimiter=limit=0.95:attack=5:release=80:level=disabled[0xff]"
    ) if nar_path is not None else (
        f";[0xee]loudnorm={LOUDNORM}:print_format=summary,"
        f"alimiter=limit=0.95:attack=5:release=80:level=disabled[0xff]"
    )

    cmd += ["-filter_complex", graph, "-map", "[0xff]",
            "-ar", "44100", "-ac", "2", "-c:a", "pcm_s16le", str(out_wav)]
    _run(cmd)
    return {
        "narration": str(nar_path) if nar_path else None,
        "bed": str(bed_path) if bed_path else None,
        "sfx": str(sfx_path) if sfx and sfx_path else None,
        "mixed": str(out_wav),
        "bed_crossfade_ms": BED_CROSSFADE_MS,
        "sfx_ducked": bool(sfx_ducked) if nar_path is not None else False,
        "duck": {
            "threshold": DUCK_THRESHOLD, "ratio": DUCK_RATIO,
            "attack_ms": DUCK_ATTACK_MS, "release_ms": DUCK_RELEASE_MS,
        },
    }


def audio_continuity(bed_files: list, shot_durations: list) -> dict:
    """Analyze the bed plan: are segments continuous? Are there any places
    where a shot has no bed source AND the previous shot did?
    Returns:
        {
          "segments": [{"shot_idx": int, "bed": str|None, "transition": str}, ...],
          "gaps": [int, ...]              # shot indices with no bed where prev had one
          "restarts": [int, ...]          # shot indices where bed file changes (ok)
          "continuous": bool
        }
    """
    segs, gaps, restarts = [], [], []
    prev = None
    for i, b in enumerate(bed_files):
        transition = "continue" if b == prev else ("silence" if b is None else
                                                   "change")
        segs.append({"shot_idx": i, "bed": str(b) if b else None,
                     "transition": transition})
        if transition == "change" and prev is not None:
            restarts.append(i)
        if prev is not None and b is None:
            gaps.append(i)
        prev = b
    # Continuity is preserved if the bed doesn't restart (only changes are
    # planned changes, which use crossfade). The brief: "The listener should
    # perceive one continuous acoustic world." A single bed file across all
    # shots is the strictest pass; a planned change with crossfade also
    # passes; an unplanned silence-gap fails.
    continuous = len(gaps) == 0
    return {"segments": segs, "gaps": gaps, "restarts": restarts,
            "continuous": continuous}
