#!/usr/bin/env python3
"""
mission_resume.py — Resume a mission run from stage 13 (video review).

Useful when the pipeline was interrupted after rendering (e.g. review
provider quota failure).  Picks up existing artifacts:

    results/<slug>/script_final.json
    results/<slug>/timeline.json
    results/<slug>/<slug>_v1_mixed.mp4   (or _v1.mp4)

and runs: video review → improvement pass(es) → postmortem.

Usage:
    ./venv/bin/python mission_resume.py --slug voyager_1__the_farthest_human_made_object
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

import mission_run as M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True, help="Results dir slug")
    ap.add_argument("--max-render-iterations", type=int, default=3)
    ap.add_argument("--music", default="cache/music/cinematic.mp3")
    ap.add_argument("--music-db", type=float, default=-6.0)
    args = ap.parse_args()

    mods = M._imports()
    out_dir = os.path.join("results", args.slug)
    if not os.path.isdir(out_dir):
        print(f"!! No results dir: {out_dir}")
        sys.exit(1)

    script_path = os.path.join(out_dir, "script_final.json")
    timeline_path = os.path.join(out_dir, "timeline.json")
    mixed_path = os.path.join(out_dir, f"{args.slug}_v1_mixed.mp4")
    plain_path = os.path.join(out_dir, f"{args.slug}_v1.mp4")
    if os.path.exists(mixed_path):
        review_target = mixed_path
    elif os.path.exists(plain_path):
        review_target = plain_path
    else:
        print("!! No rendered video found")
        sys.exit(1)

    with open(script_path) as f:
        scenes_data = json.load(f)
    topic = scenes_data[0].get("topic") or args.slug.replace("_", " ")

    run_report = {"topic": topic, "resumed": True,
                  "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  "stages": {}}

    # ── Stage 13: video review ────────────────────────────────────────
    review = M.stage_video_review(review_target, scenes_data,
                                  os.path.join(out_dir, "review_v1.json"))
    run_report["stages"]["review_v1"] = {
        "score": review.get("quality_score"),
        "confidence": review.get("confidence"),
        "model_used": review.get("_meta", {}).get("model_used"),
        "elapsed_s": review.get("_meta", {}).get("elapsed_s"),
    }

    # ── Stage 14: improvement passes (bounded) ────────────────────────
    iteration = 1
    max_iter = max(1, min(args.max_render_iterations, 3))
    while iteration < max_iter:
        plan_dict = M.stage_improvement_plan(review, iteration + 1, out_dir,
                                             max_total=max_iter)
        run_report["stages"][f"improve_pass_{iteration}"] = plan_dict
        if plan_dict.get("stopped_early") or not plan_dict.get("applied"):
            print("  → No auto-applicable changes; stopping improvement loop.")
            break
        applied = M.stage_apply_improvements(plan_dict, timeline_path)
        if not applied:
            print("  → No timeline mutations possible; stopping improvement loop.")
            break
        # Re-render (no timeline rebuild), re-mix, re-review
        render_stats = M.stage_render(None, timeline_path, plain_path,
                                      build_timeline=False)
        run_report["stages"][f"render_v{iteration+1}"] = render_stats
        mix_stats = M.stage_music_mix(plain_path, args.music, mixed_path,
                                      music_volume_db=args.music_db)
        run_report["stages"][f"music_v{iteration+1}"] = mix_stats
        review_target = mixed_path if mix_stats.get("mixed") else plain_path
        review = M.stage_video_review(review_target, scenes_data,
                                      os.path.join(out_dir, f"review_v{iteration+1}.json"))
        run_report["stages"][f"review_v{iteration+1}"] = {
            "score": review.get("quality_score"),
            "confidence": review.get("confidence"),
            "model_used": review.get("_meta", {}).get("model_used"),
        }
        iteration += 1

    # ── Stage 15-16: final output + postmortem ────────────────────────
    print("\n[15-16/16] FINAL OUTPUT + POSTMORTEM", flush=True)
    run_report["final"] = {
        "output": review_target,
        "iterations": iteration,
        "final_score": review.get("quality_score"),
        "duration_s": M._probe_duration(review_target),
    }
    M._write_json(os.path.join(out_dir, "run_report.json"), run_report)

    recorder = mods["PostmortemRecorder"]()
    pm_path = recorder.record(
        topic,
        techniques_succeeded=[
            f"resumed from stage 13 after render (review model fallback chain)",
            f"Gemini review (model={review.get('_meta', {}).get('model_used')}) score {review.get('quality_score')}/100",
            f"ffmpeg sidechain music ducking (bed={os.path.basename(args.music)})",
        ],
        techniques_failed=[
            "gemini flash quota 429 on free tier — retrying",
        ],
        prompt_improvements=[
            "review prompt asks for timestamps + prioritized categories",
        ],
        review_feedback=[
            f"{r.get('recommendation', '')[:120]}"
            for r in review.get("prioritized_recommendations", [])[:5]
        ],
        benchmark_results={"video_review_model": review.get("_meta", {}).get("model_used"),
                            "music_mix": "ffmpeg sidechaincompress"},
        metrics={"final_score": review.get("quality_score"),
                 "render_iterations": iteration,
                 "duration_s": M._probe_duration(review_target)},
        artifacts={"video": review_target, "report": os.path.join(out_dir, "run_report.json")},
    )
    run_report["postmortem"] = pm_path
    M._write_json(os.path.join(out_dir, "run_report.json"), run_report)

    print("\n" + "=" * 64)
    print(f"RESUMED RUN COMPLETE — {topic}")
    print(f"  Video:  {review_target}")
    print(f"  Report: {os.path.join(out_dir, 'run_report.json')}")
    print(f"  Postmortem: {pm_path}")
    print(f"  Final review score: {review.get('quality_score')}/100")
    print("=" * 64)


if __name__ == "__main__":
    main()
