#!/usr/bin/env python3
"""
trace_frame.py — Trace any frame in a rendered video back through the pipeline.

The system must be explainable: for any timestamp, answer WHY this frame
appeared.  Uses the semantic identity embedded in timeline.json (camera
move, asset source/title/query, verification, scene) and the per-shot
diagnostics (entity spec) to reconstruct the decision chain:

    research → beat planning → asset selection → verification →
    timeline placement → camera → render

Usage:
    ./venv/bin/python trace_frame.py <timeline.json> <timestamp_s> [--all]
"""

import argparse
import json
import os
import sys


def load_timeline(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def find_shot(tl: dict, ts: float) -> dict | None:
    for v in tl.get("video_timeline", []):
        if v.get("start_time", 0) <= ts < v.get("end_time", 0):
            return v
    return None


def find_audio(tl: dict, ts: float) -> dict | None:
    for a in tl.get("audio_timeline", []):
        if a.get("start_time", 0) <= ts < a.get("end_time", 0):
            return a
    return None


def explain(tl_path: str, ts: float, all_shots: bool = False) -> str:
    tl = load_timeline(tl_path)
    shot = find_shot(tl, ts)
    if shot is None:
        return f"No video shot at t={ts:.1f}s (check bounds 0–{tl.get('render_settings',{}).get('fps',30)})"

    lines = []
    lines.append(f"FRAME @ {ts:.1f}s")
    lines.append(f"  timeline: {shot['start_time']:.1f}s – {shot['end_time']:.1f}s "
                 f"(duration {shot['end_time']-shot['start_time']:.1f}s)")
    lines.append(f"  shot file: {os.path.basename(shot.get('file',''))}")
    lines.append(f"  scene_id: {shot.get('scene_id','?')}  beat: {shot.get('beat_index','?')}")
    lines.append(f"  asset_source: {shot.get('asset_source','?')}")
    if shot.get("asset_title"):
        lines.append(f"  asset_title: {shot['asset_title']}")
    if shot.get("query_used"):
        lines.append(f"  query_used: {shot['query_used']}")
    lines.append(f"  camera_move: {shot.get('camera_move','?')}  "
                 f"motion_params: {json.dumps(shot.get('motion_params',{}))}")
    lines.append(f"  transition: {shot.get('transition','?')}")
    ver = shot.get("verification_passed")
    if ver is not None:
        lines.append(f"  verification: {'PASSED' if ver else 'FAILED'} "
                     f"(pre_verified={shot.get('pre_verified',False)})")
        if shot.get("verification_reasons"):
            lines.append(f"    reasons: {shot['verification_reasons'][:3]}")

    audio = find_audio(tl, ts)
    if audio:
        lines.append(f"  narration: {os.path.basename(audio.get('file',''))} "
                     f"({audio['start_time']:.1f}s–{audio['end_time']:.1f}s)")

    # Diagnostics cross-reference (entity spec / verification detail)
    diag_path = os.path.join(os.path.dirname(tl_path), "render_diagnostics.json")
    if os.path.exists(diag_path):
        with open(diag_path) as f:
            diag = json.load(f)
        for s in diag.get("shots", []):
            if s.get("timeline_start_s", 0) <= ts < s.get("timeline_end_s", 0):
                if s.get("entity_spec"):
                    es = s["entity_spec"]
                    lines.append(f"  entity_spec: intent={es.get('scene_intent','?')} "
                                 f"required={es.get('required_entities',[])[:3]} "
                                 f"prohibited={es.get('prohibited_entities',[])[:3]}")
                if s.get("verification") and s["verification"].get("signal_scores"):
                    sc = s["verification"]["signal_scores"]
                    lines.append(f"  verification_signals: " + ", ".join(
                        f"{k}={v.get('score',0):.2f}" for k, v in sc.items()))
                break

    if all_shots:
        lines.append("\n  ALL SHOTS:")
        for v in tl.get("video_timeline", []):
            mark = " ◄" if v is shot else ""
            lines.append(f"    {v['start_time']:6.1f}-{v['end_time']:6.1f}s  "
                         f"{os.path.basename(v.get('file','')):28s} "
                         f"{v.get('asset_source','?'):12s} {v.get('camera_move','?')}{mark}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Trace any frame to its production decisions")
    ap.add_argument("timeline", help="path to timeline.json")
    ap.add_argument("timestamp", type=float, help="timestamp in seconds")
    ap.add_argument("--all", action="store_true", help="list all shots")
    args = ap.parse_args()
    print(explain(args.timeline, args.timestamp, all_shots=args.all))


if __name__ == "__main__":
    main()
