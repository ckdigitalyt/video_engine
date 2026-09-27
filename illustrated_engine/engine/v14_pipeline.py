"""V14 Stage 11 — one-command autonomous production (§21, §37 Stage 11).

STORY (stories/<id>/story.json — facts/script/beats already on disk) →
grammar selection → SCENE IR → cache-aware render (§23 backend selection) →
captions → audio → final composite → QA report → publish gate.

Grammar selection is deterministic from beat function + story visual_grammars
hints: HOOK/PAYOFF/ESCALATION → rich_illustrated; CURIOSITY/EXPLANATION →
process_flow; REVEAL → scale_dive when the story hints scale_descent.
Scene content derives ONLY from story text (narration/claim/visual_answer) —
grammars needing structured data (data_graphic values, map_transformation
before/after) are not selected because inventing data violates factual
integrity. Scene duration is narration-driven: TTS first, dur = clamp(tts+1.1).

Cache (§24/§25): every scene key binds specHash (camera + staged asset bytes)
+ style + backend + version + config; renders happen only for misses; the
composite rebuilds only when the §25 plan says so.

Usage:
  python3 -m engine.v14_pipeline --story stories/ice_slippery \
      --work build/v14/pilot_ice [--backend auto] [--report path]
Exit 0 = publish gate PASS; 1 = gate FAIL (report says why).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from engine.camera_depth import plan_depths, verify_camera_continuity
from engine.grammars import available_grammars, build_scene
from engine.scene_ir import spec_hash, validate_scene_spec
from engine.scene_renderer import compile_spec, select_backend
from engine.v14_assembly import DEFAULT_BIBLE, assemble
from engine.v14_cache import (assembly_key, bed_plan_hash, caption_plan_hash,
                              load_index, narration_plan_hash,
                              plan_production, record_assembly, record_scene,
                              save_index, scene_cache_key, style_hash)

RENDER_CONFIG = {"concurrency": 2}
BED_BY_STORY_TYPE = {"science": "science", "history": "history",
                     "geography": "geography", "engineering": "engineering"}
_HINT_MAP = {"scale_descent": "scale_dive", "mechanism_flow": "process_flow",
             "data_explainer": "data_graphic", "place_shift": "map_transformation"}
_CANON = {"rich_illustrated": "RICH_ILLUSTRATED_SCENE",
          "scale_dive": "SCALE_DIVE", "process_flow": "PROCESS_FLOW",
          "data_graphic": "DATA_GRAPHIC",
          "map_transformation": "MAP_TRANSFORMATION"}


def _clauses(text: str, n: int) -> list:
    words = str(text).replace("—", " ").replace(";", ",").split()
    size = max(3, math.ceil(len(words) / max(n, 1)))
    return [" ".join(words[i:i + size]).strip(" ,.")
            for i in range(0, len(words), size)][:n]


def select_grammar(beat: dict, hints: list) -> str:
    fn = (beat.get("function") or "").upper()
    known = [g for g in (_HINT_MAP.get(h, h) for h in (hints or []))
             if _CANON.get(g, g) in available_grammars()]
    if fn == "HOOK":
        return "rich_illustrated"
    if fn == "CURIOSITY":
        return "process_flow" if "process_flow" in known else \
            (known[0] if known else "process_flow")
    if fn == "REVEAL":
        return "scale_dive" if "scale_dive" in known else \
            (known[0] if known else "rich_illustrated")
    if fn == "EXPLANATION":
        return "process_flow"
    return "rich_illustrated"  # ESCALATION / PAYOFF / unknown


def _subject_kind(text: str) -> str:
    """Deterministic procedural-subject kind from the beat text (§9 kinds)."""
    t = str(text).lower()
    for keys, kind in (
        # specific before generic: "DNA" must win over "cell" (V15 fix)
        (("dna", "spiral", "helix", "coil", "spring"), "helix"),
        (("wave", "shock", "explode", "ring", "layer", "molecular",
          "molecule", "lattice"), "rings"),
        (("cell", "biolog", "membrane", "microb", "mitochond"), "cells"),
        (("see", "look", "observe", "eye", "watch"), "eye"),
    ):
        if any(k in t for k in keys):
            return kind
    return "circle"


def beat_content(beat: dict, grammar: str, scene_id: str, dur: float) -> dict:
    if grammar == "process_flow":
        src = beat.get("visual_answer") or beat.get("claim") \
            or beat.get("narration") or "the mechanism"
        n = 3 if dur >= 5.5 else 2
        stages = [{"title": c.upper()} for c in _clauses(src, n)]
        return {"scene_id": scene_id, "duration_s": dur, "stages": stages}
    if grammar == "scale_dive":
        return {"scene_id": scene_id, "duration_s": dur,
                "dive": {"to_scale": 24.0},
                "outer_subject": {"kind": "circle"},
                "inner_subject": {"kind": "circle", "count": 10},
                "stages": [{"until_scale": 2.0, "title": "MACRO"},
                           {"until_scale": 8.0, "title": "MICRO"},
                           {"until_scale": 1e9, "title": "MOLECULAR"}],
                "title": str(beat.get("visual_question") or "")[:60] or None}
    subject_text = beat.get("visual_answer") or beat.get("claim") \
        or beat.get("narration") or "the subject"
    label = (beat.get("visual_question") if (beat.get("function") or "").upper()
             == "HOOK" else subject_text)
    return {"scene_id": scene_id, "duration_s": dur,
            "subject": {"kind": _subject_kind(subject_text),
                        "label": str(label)[:70]},
            "title": str(label)[:70] or None}


def caption_cues(beat: dict, dur: float) -> list:
    """~4-word kinetic cues spanning the narration window of the scene."""
    words = str(beat.get("narration") or "").split()
    if not words:
        return []
    groups = [words[i:i + 4] for i in range(0, len(words), 4)]
    max_groups = max(1, int((dur - 0.6) / 0.45))
    groups = groups[:max_groups]
    t0, span = 0.25, (dur - 0.5) / len(groups)
    cues = []
    for i, g in enumerate(groups):
        cues.append({"t0": round(t0 + i * span, 2),
                     "t1": round(t0 + (i + 1) * span - 0.06, 2),
                     "text": " ".join(g)})
    return cues


def run_pipeline(story_path: Path, work_dir: Path, backend: str = "auto") -> dict:
    story_path, work = Path(story_path), Path(work_dir)
    if story_path.is_dir():
        story_path = story_path / "story.json"
    (work / "scenes").mkdir(parents=True, exist_ok=True)
    story = json.loads(story_path.read_text())
    story_dir = story_path.parent
    beats = story["beats"]
    hints = story.get("visual_grammars") or []
    bed_key = BED_BY_STORY_TYPE.get(story.get("story_type", "science"), "science")
    bible = dict(DEFAULT_BIBLE)
    report: dict = {"story_id": story["story_id"], "backend_request": backend,
                    "scenes": {}, "warnings": []}

    # 1. TTS per beat (cached) -> narration-driven durations
    from engine.tts import tts_beat
    durs, nar_dur = {}, {}
    for b in beats:
        res = tts_beat(story_dir, b["beat_id"], b["narration"])
        nar_dur[b["beat_id"]] = float(res["duration"])
        # narration-driven: the scene serves the narration (no 8s clamp)
        durs[b["beat_id"]] = round(min(30.0, max(2.5, float(res["duration"]) + 1.1)), 2)
    report["durations"] = durs

    # 2. grammar + Scene IR per beat (validator-gated)
    specs = {}
    for b in beats:
        bid = b["beat_id"]
        g = select_grammar(b, hints)
        try:
            spec = build_scene(_CANON.get(g, g),
                               beat_content(b, g, f"{story['story_id']}_{bid}",
                                            durs[bid]))
        except Exception as exc:
            # grammar gate refuses the derived content -> recorded fallback,
            # never a silent downgrade and never invented data
            g = "rich_illustrated"
            spec = build_scene(_CANON[g],
                               beat_content(b, g, f"{story['story_id']}_{bid}",
                                            durs[bid]))
            report.setdefault("grammar_fallbacks", []).append(
                {"scene": bid, "hinted": None, "reason": str(exc)[:160]})
        plan_depths(spec, apply=True)
        ok, errs = validate_scene_spec(spec)
        if not ok:
            raise ValueError(f"{bid} invalid Scene IR: {errs[:3]}")
        specs[bid] = (g, spec)

    # 3. cache keys + §25 production plan
    index = load_index(work)
    scene_inputs, meta, captions = {}, {}, {}
    for b in beats:
        bid = b["beat_id"]
        g, spec = specs[bid]
        be, reason = select_backend(spec, backend)
        key = scene_cache_key(spec_hash(compile_spec(spec)), style_hash(bible),
                              be.name, str(be.capabilities().get("version") or "1"),
                              RENDER_CONFIG)
        out = work / "scenes" / f"{bid}.mp4"
        scene_inputs[bid] = {"key": key, "output": str(out)}
        meta[bid] = {"backend": be, "reason": reason, "spec": spec, "out": out,
                     "grammar": g}
        captions[bid] = caption_cues(b, durs[bid])
    cap_h = caption_plan_hash(captions, bible)
    nar_h = narration_plan_hash({bid: b["narration"] for b in beats})
    beds = {bid: {"grammar": bed_key, "intensity": 0.5} for bid in specs}
    bed_h = bed_plan_hash(beds)
    out_final = work / "final.mp4"
    plan = plan_production(index, scene_inputs, cap_h, nar_h, bed_h, out_final)
    report["plan"] = {k: plan[k] for k in ("render", "reuse", "reasons",
                                           "rebuild_audio", "rebuild_composite")}
    report["backend_reasons"] = {bid: meta[bid]["reason"] for bid in meta}

    # 4. render only what the plan demands
    rendered = []
    for bid in plan["render"]:
        m = meta[bid]
        res = m["backend"].render(m["spec"], m["out"],
                                  concurrency=RENDER_CONFIG["concurrency"])
        if not res.get("ok"):
            raise RuntimeError(f"{bid} render failed: {str(res)[:400]}")
        record_scene(index, scene_inputs[bid]["key"], bid, m["out"],
                     float(m["spec"]["duration_s"]))
        rendered.append(bid)
    report["rendered"] = rendered

    # 5. composite (captions AFTER composition + audio + mux)
    if plan["rebuild_composite"]:
        plan_scenes = [{"scene_id": bid, "video": str(meta[bid]["out"]),
                        "captions": captions[bid],
                        "narration": {"beat_id": bid,
                                      "text": b["narration"]},
                        "bed": beds[bid]}
                       for b in beats for bid in [b["beat_id"]]]
        arep = assemble({"story_id": story["story_id"],
                         "story_dir": str(story_dir), "bible": bible,
                         "scenes": plan_scenes, "out": str(out_final)}, work)
        record_assembly(index, plan["assembly_key"], out_final, cap_h, nar_h,
                        bed_h)
    else:
        arep = {"skipped": "composite cache hit", "final": {}}
    report["assembly"] = {k: arep.get(k) for k in
                          ("total_s", "captions", "final", "warnings")}
    save_index(work, index)

    # 6. QA + publish gate — recomputed from the artifacts themselves, so a
    # §25 composite cache hit is gated exactly like a fresh build
    from engine.v14_assembly import _probe, build_caption_inputs
    starts, t, probed = {}, 0.0, {}
    for b in beats:
        bid = b["beat_id"]
        try:
            probed[bid] = float(_probe(meta[bid]["out"])["format"]["duration"])
        except Exception:
            probed[bid] = float(specs[bid][1]["duration_s"])
        starts[bid] = round(t, 3)
        t += probed[bid]
    cap_dir = work / "qa_captions"
    repairs = []
    for b in beats:
        bid = b["beat_id"]
        _, reps = build_caption_inputs(captions[bid], bible, cap_dir,
                                       offset=starts[bid])
        repairs += [dict(r, scene=bid) for r in reps]
    overruns = []
    for b in beats:
        bid = b["beat_id"]
        if nar_dur.get(bid, 0.0) > probed[bid] + 0.05:
            overruns.append({"scene": bid,
                             "narration_s": round(nar_dur[bid], 3),
                             "scene_s": round(probed[bid], 3)})
    for bid, (g, spec) in specs.items():
        cont = verify_camera_continuity(spec)
        report["scenes"][bid] = {"grammar": g,
                                 "backend": meta[bid]["backend"].name,
                                 "validator": True, "continuity": cont["ok"],
                                 "track": cont.get("track"),
                                 "scene_s": round(probed[bid], 3)}
        if not cont["ok"]:
            report["warnings"].append({"scene": bid,
                                       "warning": "camera_continuity",
                                       "detail": str(cont)[:200]})
    report["caption_repairs"] = repairs
    report["narration_overruns"] = overruns
    final_info = {}
    if Path(out_final).exists():
        try:
            info = _probe(out_final)
            final_info = {"path": str(out_final),
                          "duration_s": round(float(info["format"]["duration"]), 3),
                          "streams": [s["codec_name"] for s in info["streams"]]}
        except Exception as exc:
            report["warnings"].append({"warning": "final_probe_failed",
                                       "reason": str(exc)[:120]})
    report["final_check"] = final_info
    streams_ok = set(final_info.get("streams") or []) >= {"h264", "aac"}
    gate = (not report["warnings"] and not repairs and not overruns
            and streams_ok and bool(final_info))
    report["publish_gate"] = "PASS" if gate else "FAIL"
    (work / "pipeline_report.json").write_text(json.dumps(report, indent=1))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="V14 one-command production pilot")
    ap.add_argument("--story", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--report", default=None)
    args = ap.parse_args()
    rep = run_pipeline(Path(args.story), Path(args.work), args.backend)
    out = Path(args.report) if args.report else Path(args.work) / "pipeline_report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1))
    print(json.dumps({k: rep[k] for k in
                      ("story_id", "durations", "plan", "rendered",
                       "publish_gate")}, indent=1))
    return 0 if rep["publish_gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
