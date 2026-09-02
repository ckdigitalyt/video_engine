"""Edit-plan builder v2 — narration-first timing, clause captions, grammar
cameras, novelty-filled events, region-resolved overlays.

Reads: story.json, visual_plan.json, audio/timing.json
Writes: build/edit_plan.json  (engine: "v2")
"""

from __future__ import annotations

import json
from pathlib import Path

from engine import grammar, layout, subs

PAD = 0.7  # silence after each beat's narration


def make_edit_plan_v2(paths, story_id: str = "tallest_mountain"):
    story_dir = Path(paths.stories) / story_id
    story = json.loads((story_dir / "story.json").read_text())
    vp = json.loads((story_dir / "visual_plan.json").read_text())
    tp = story_dir / "audio" / "timing.json"
    timing = json.loads(tp.read_text()) if tp.exists() else {}
    rep = {"ok": [], "warnings": [], "errors": []}

    story_beats = {b.get("beat_id"): b for b in story.get("beats") or []}
    regions = vp.get("regions", {})
    shots_out = []

    for vb in vp.get("beats") or []:
        bid = vb.get("beat_id")
        sb = story_beats.get(bid) or {}
        narration = sb.get("narration", "")
        vshots = vb.get("shots") or []
        if not vshots:
            continue

        audio_dur = float((timing.get(bid) or {}).get("duration", 0.0))
        est_sum = sum(float(s.get("duration_est", 4.0)) for s in vshots) or 1.0
        if audio_dur > 0:
            beat_target = audio_dur + PAD
        else:
            beat_target = float(vb.get("duration_est", est_sum))
            rep["warnings"].append(f"{bid}: no TTS timing, falling back to duration_est")
        scale = beat_target / est_sum
        durs = [float(s.get("duration_est", 4.0)) * scale for s in vshots]
        starts, acc = [], 0.0
        for d in durs:
            starts.append(acc)
            acc += d

        # clause captions across the beat, word-proportional
        phrases = subs.segment_phrases(narration)
        total_words = sum(len(p.split()) for p in phrases) or 1
        cues, cacc = [], 0.0
        for ph in phrases:
            d = beat_target * (len(ph.split()) / total_words)
            cues.append({"text": ph, "t0": cacc, "t1": cacc + d})
            cacc += d

        for i, s in enumerate(vshots):
            sid = str(s["shot_id"])
            dur = durs[i]
            off = starts[i]

            shot_cues = []
            if str(s.get("captions", "phrase")) == "phrase":
                for c in cues:
                    mid = (c["t0"] + c["t1"]) / 2.0
                    if off <= mid < off + dur or (i == len(vshots) - 1 and mid >= off):
                        shot_cues.append({
                            "text": c["text"],
                            "t0": round(max(0.0, c["t0"] - off), 3),
                            "t1": round(min(dur, c["t1"] - off), 3),
                        })

            events = grammar.build_events(s, dur)
            grammar.fill_novelty(s, events, dur)
            for ev in events:
                spec = ev.setdefault("spec", {})
                tgt = spec.get("target") or spec.get("region")
                if isinstance(tgt, str):
                    spec["rect"] = regions.get(tgt, [0.30, 0.35, 0.40, 0.30] if tgt == "center" else None)
                elif isinstance(tgt, list):
                    spec["rect"] = tgt

            shots_out.append({
                "shot_id": sid,
                "shot_type": str(s.get("shot_type", "EXPLAIN")).upper(),
                "asset": s["asset"],
                "duration_s": round(dur, 3),
                "camera": grammar.camera_for(s),
                "events": events,
                "captions": shot_cues,
                "transition_in": str(s.get("transition_in", "CUT")).upper(),
                "opening": bool(s.get("opening")),
                "title": s.get("title", ""),
                "tag": s.get("tag", ""),
                "crop_bias_y": float(s.get("crop_bias_y", 0.42)),
                "end_card": s.get("end_card"),
            })

    eplan = {
        "story_id": story.get("story_id", story_id),
        "engine": "v2",
        "fps": 30,
        "size": [1080, 1920],
        "brand": story.get("brand", ""),
        "visual_rect": list(layout.VISUAL_RECT),
        "caption_rect": list(layout.CAPTION_RECT),
        "shots": shots_out,
    }
    out = Path(paths.build) / "edit_plan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(eplan, indent=2) + "\n")
    return eplan, rep
