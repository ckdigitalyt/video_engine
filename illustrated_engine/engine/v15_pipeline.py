"""V15 — one-command autonomous production: story -> publish-gated MP4.

    story.json (+facts/bible) -> TTS per beat (cached) -> word timing
    (v15_timing) -> Beat Visual Plan (v15_plan: 1 cached LLM call, validated,
    deterministic fallback) -> one AI plate per shot through the image
    fallback chain (v15_plates, global cache) + 1 plate-QA vision call with
    one regeneration round -> subject analysis -> shot grammars -> Scene IR
    (v15_shots, one scene per shot) -> §24/§25 cache-aware render (existing
    select_backend + v14_cache) -> assembly (existing v14_assembly: concat
    filter, phrase captions on measured word times burned AFTER composition,
    narration + underscore + SFX, loudnorm) -> v15_gate (deterministic hard
    checks + 1 vision-judge call) -> PASS / HOLD with reasons.

Everything V14 built is reused; V15 adds the semantic plan, the plate layer,
timing, and an honest gate. v14_pipeline stays runnable as the floor path.

Usage:
  python3 -m engine.v15_pipeline --story stories/ice_slippery \\
      --work build/v15/ice_slippery [--no-llm] [--no-judge] [--backend auto]
Exit 0 = publish gate PASS, 1 = HOLD (report says why), 2 = error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPO = ROOT.parent
for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from engine.scene_ir import spec_hash, validate_scene_spec  # noqa: E402
from engine.scene_renderer import compile_spec, select_backend  # noqa: E402
from engine.v14_assembly import assemble  # noqa: E402
from engine.v14_cache import (bed_plan_hash, caption_plan_hash,  # noqa: E402
                              load_index, narration_plan_hash,
                              plan_production, record_assembly, record_scene,
                              save_index, scene_cache_key, style_hash)
from engine.v15_plan import make_plan  # noqa: E402
from engine.v15_plates import (analyze_subject, generate_plate,  # noqa: E402
                               image_chain_report, plate_qa,
                               providers_for_beat_function)
from engine.v15_shots import compile_shot  # noqa: E402
from engine.v15_style import image_prompt, load_style  # noqa: E402
from engine.v15_timing import beat_timing  # noqa: E402

LEAD_S = 0.30      # silence before a beat's narration (breath + first frame)
TAIL_S = 0.55      # hold after the narration ends
CUT_EARLY_S = 0.12  # cut slightly BEFORE the word that starts a shot
MIN_SHOT_S = 1.4
RENDER_CONFIG = {"concurrency": 2, "pipeline": "v15"}
INTENSITY = {"HOOK": 0.75, "CURIOSITY": 0.62, "REVEAL": 0.85,
             "EXPLANATION": 0.66, "ESCALATION": 0.82, "PAYOFF": 0.88}
_PUNCT_ONLY = re.compile(r"^[\W_]+$")
_FUNCTION_WORDS = {"a", "an", "the", "of", "to", "in", "on", "at", "by", "for",
                   "and", "but", "or", "so", "your", "its", "their", "his",
                   "her", "you", "we", "it", "is", "are", "was", "can",
                   "that", "this", "with", "from", "into", "than", "as"}


# ---------------------------------------------------------------- captions --

def _binds_forward(word: str) -> bool:
    """Function words and bare figures belong with the NEXT word (a number
    with its unit, an article with its noun) unless punctuation ends them."""
    if re.search(r"[,.;:!?\u2014]$", word):
        return False
    w = word.lower()
    return w in _FUNCTION_WORDS or bool(re.fullmatch(r"[\d.,]+", w))


def caption_cues(timing: dict, lead: float) -> list:
    """Phrase cues (<= 4 words, break after punctuation or a pause) on the
    measured word times; per-word starts drive the active-word highlight."""
    words = []
    for w in timing["words"]:
        if _PUNCT_ONLY.match(w["w"]) and words:
            words[-1] = dict(words[-1], w=words[-1]["w"] + " " + w["w"],
                             t1=w["t1"])
            continue
        words.append(dict(w))
    groups, cur = [], []
    for i, w in enumerate(words):
        cur.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        # a length break never strands a function word at the cue end
        # ("...STAYS A" / "RUMOR YOU CAN"): it carries into the next cue
        if len(cur) >= 4 and nxt is not None:
            k = len(cur)
            while k > 1 and _binds_forward(cur[k - 1]["w"]):
                k -= 1
            if k < len(cur):
                groups.append(cur[:k])
                cur = cur[k:]
                continue
        brk = (len(cur) >= 4
               or re.search(r"[.!?]$", w["w"])
               or re.search(r"[,;:—]$", w["w"]) and len(cur) >= 2
               or (nxt is not None and nxt["t0"] - w["t1"] > 0.25
                   and len(cur) >= 2))
        if brk or nxt is None:
            groups.append(cur)
            cur = []
    # a 1-word tail group merges back (a lone word flashes too fast)
    if len(groups) > 1 and len(groups[-1]) == 1:
        tail = groups.pop()  # (not `groups[-2] += groups.pop()`: the target
        groups[-1] = groups[-1] + tail  # index resolves before the pop)
    cues = []
    for gi, g in enumerate(groups):
        t0 = lead + g[0]["t0"]
        nxt_t0 = lead + groups[gi + 1][0]["t0"] if gi + 1 < len(groups) else None
        t1 = (nxt_t0 - 0.06) if nxt_t0 is not None else lead + g[-1]["t1"] + 0.3
        cues.append({"t0": round(t0, 3), "t1": round(max(t1, t0 + 0.4), 3),
                     "text": " ".join(w["w"] for w in g),
                     "word_starts": [round(lead + w["t0"], 3) for w in g]})
    return cues


# ------------------------------------------------------------------ shots --

def shot_timeline(beat: dict, bplan: dict, timing: dict, tts_s: float) -> list:
    """Beat -> [{shot, t0, t1}] in beat-local seconds; shots shorter than
    MIN_SHOT_S merge into the previous one (recorded)."""
    beat_dur = LEAD_S + tts_s + TAIL_S
    wt = [w["t0"] for w in timing["words"]]
    starts = []
    for k, sh in enumerate(bplan["shots"]):
        t = 0.0 if k == 0 else LEAD_S + wt[min(sh["start_word"], len(wt) - 1)] \
            - CUT_EARLY_S
        starts.append((t, sh))
    out = []
    for i, (t, sh) in enumerate(starts):
        t1 = starts[i + 1][0] if i + 1 < len(starts) else beat_dur
        if out and t1 - t < MIN_SHOT_S:
            out[-1]["t1"] = t1
            out[-1].setdefault("merged", []).append(sh["kind"])
            continue
        if not out and i + 1 < len(starts) and t1 - t < MIN_SHOT_S:
            starts[i + 1] = (t, starts[i + 1][1])  # first too short -> drop
            continue
        out.append({"shot": sh, "t0": round(t, 3), "t1": round(t1, 3)})
    out[-1]["t1"] = round(beat_dur, 3)
    return out


MAX_HOLD_S = 4.4  # gate allows 4.5 s between visual changes


def _split_one(s: dict, wt: list, bt: list, max_hold_s: float,
               margin_s: float) -> list | None:
    """One shot -> [first, second] split at its single worst gap, or None
    if it's already within max_hold_s or has no valid split word (every
    candidate would land within `margin_s` of a gap edge, producing a
    sliver shot)."""
    sh = s["shot"]
    if sh["kind"] != "plate":
        return None
    ev = [s["t0"]] + sorted(LEAD_S + wt[min(sh[k]["word"], len(wt) - 1)]
                            for k in ("number", "label") if sh.get(k)) \
        + [s["t1"]]
    gaps = [(ev[i], ev[i + 1]) for i in range(len(ev) - 1)]
    a, b = max(gaps, key=lambda g: g[1] - g[0])
    if b - a <= max_hold_s:
        return None
    mid = (a + b) / 2
    cands = [i for i, t in enumerate(bt) if a + margin_s <= t <= b - margin_s
             and s["t0"] + margin_s <= t <= s["t1"] - margin_s]
    if not cands:
        return None
    wi = min(cands, key=lambda i: abs(bt[i] - mid))
    first = {k: v for k, v in sh.items()}
    second = {"kind": "plate", "subject": sh["subject"],
              "composition": sh.get("composition", "centered"),
              "camera": "punch_in", "start_word": wi, "derived": "punch_in"}
    for k in ("number", "label"):
        if sh.get(k) and sh[k]["word"] >= wi:
            second[k] = first.pop(k)
    return [dict(s, shot=first, t1=round(bt[wi], 3)),
            {"shot": second, "t0": round(bt[wi], 3), "t1": s["t1"]}]


def split_long_holds(tl: list, timing: dict, max_hold_s: float = MAX_HOLD_S,
                     margin_s: float | None = None) -> list:
    """Plate shots whose longest stretch without a visual change exceeds
    `max_hold_s` (default MAX_HOLD_S=4.4, the V15 gate floor) are split at
    the word nearest the gap's middle into a CUT to a tighter framing of
    the same plate (camera punch_in) — an editorial punch-in, not new
    content; planned elements move with their words. Splitting repeats
    (each half re-checked) so a shot with more than one long gap gets more
    than one cut, not just its single worst one. `margin_s` bounds how
    close a split word may sit to either edge of the gap it's splitting
    (no sliver shots); it defaults to min(1.5, max_hold_s/3) so it scales
    down with a tighter threshold instead of making splitting impossible
    for gaps only slightly over a small max_hold_s. WP7 callers pass the
    tighter engine.v15_gate.MAX_HOLD_1_8_S=1.8 target (DESIGN §8.2); the
    V15 pipeline itself keeps calling this with the default."""
    if margin_s is None:
        margin_s = min(1.5, max_hold_s / 3)
    wt = [w["t0"] for w in timing["words"]]
    bt = [LEAD_S + t - CUT_EARLY_S for t in wt]  # beat-time cut per word
    changed = True
    while changed:
        changed = False
        out = []
        for s in tl:
            split = _split_one(s, wt, bt, max_hold_s, margin_s)
            if split is None:
                out.append(s)
            else:
                out.extend(split)
                changed = True
        tl = out
    return tl


def _prompts_for(shot: dict, bible: dict) -> list:
    if shot["kind"] == "zoom_through":
        return [image_prompt(bible, lv["subject"], "centered")
                for lv in shot["levels"]]
    return [image_prompt(bible, shot["subject"],
                         shot.get("composition", "centered"))]


def _seed(prompt: str, salt: int = 0) -> int:
    from src.providers.image_gen import deterministic_seed
    return deterministic_seed(prompt, salt)


# --------------------------------------------------------------- pipeline --

def run_pipeline(story_dir: Path, work: Path, *, backend: str = "auto",
                 use_llm: bool = True, use_judge: bool = True,
                 plate_qa_on: bool = True) -> dict:
    t_start = time.time()
    story_dir, work = Path(story_dir), Path(work)
    if story_dir.name == "story.json":
        story_dir = story_dir.parent
    (work / "scenes").mkdir(parents=True, exist_ok=True)
    story = json.loads((story_dir / "story.json").read_text())
    sid = story["story_id"]
    bible = load_style(story_dir, story)
    report: dict = {"story_id": sid, "pipeline": "v15",
                    "deck": bible.get("deck"), "warnings": [], "timings": {},
                    "costs": {"llm_calls": 0, "image_calls": 0,
                              "vision_calls": 0}}

    # 1. narration audio (voice layer: ONE voice for the whole video, lexicon,
    #    round-trip QA) + measured word timing
    from engine.voice import synthesize_video
    vo = synthesize_video(story_dir, story["beats"])
    report["voice"] = vo["voice"]
    tts, timing = {}, {}
    for b in story["beats"]:
        res = vo["beats"][b["beat_id"]]
        tts[b["beat_id"]] = float(res["duration"])
        timing[b["beat_id"]] = beat_timing(story_dir / res["file"],
                                           b["narration"])
    report["timing"] = {bid: {"anchored": t["anchored"],
                              "boundaries": t["boundaries"]}
                        for bid, t in timing.items()}

    # 2. Beat Visual Plan
    t0 = time.time()
    bvp = make_plan(story, bible, use_llm=use_llm)
    report["costs"]["llm_calls"] += bvp["llm_calls"]
    report["plan"] = {"source": bvp["source"], "key": bvp["key"],
                      "errors": bvp["errors"][:10]}
    if bvp["source"] == "fallback":
        report["warnings"].append({"warning": "plan_fallback",
                                   "detail": bvp["errors"][:5]})
    (work / "visual_plan.json").write_text(json.dumps(bvp["plan"], indent=1))
    plan_by = {b["beat_id"]: b for b in bvp["plan"]["beats"]}
    report["timings"]["plan_s"] = round(time.time() - t0, 1)

    # 3. shot timeline
    shots = []  # flat: {beat, idx, shot, t0, t1, prompts}
    for b in story["beats"]:
        tl = split_long_holds(
            shot_timeline(b, plan_by[b["beat_id"]], timing[b["beat_id"]],
                          tts[b["beat_id"]]), timing[b["beat_id"]])
        for k, s in enumerate(tl):
            shots.append({"beat": b, "idx": k, **s,
                          "prompts": _prompts_for(s["shot"], bible)})
        if any(s.get("merged") for s in tl):
            report["warnings"].append({"beat": b["beat_id"],
                                       "warning": "short_shot_merged"})

    # 4. plates (image fallback chain, global cache) + plate QA
    t0 = time.time()
    uniq = sorted({p for s in shots for p in s["prompts"]})
    fail_log: list = []
    report["image_chain"] = image_chain_report()  # WP8/DESIGN §6.2 preflight visibility
    # WP8/DESIGN §6.1: "Pollinations ... never for hero shots" — a prompt is
    # hero when ANY shot using it belongs to a HOOK/PAYOFF beat (the same
    # function field v15_gate.check_assets already treats as the hero
    # signal for asset_tier).
    hero_prompts = {p for s in shots if s["beat"].get("function") in ("HOOK", "PAYOFF")
                    for p in s["prompts"]}

    def _gen(prompt, salt=0, providers=None):
        if providers is None and prompt in hero_prompts:
            providers = providers_for_beat_function("HOOK")
        kw = {"providers": providers} if providers else {}
        return prompt, generate_plate(prompt, _seed(prompt, salt),
                                      log=fail_log, **kw)

    with ThreadPoolExecutor(max_workers=3) as ex:
        plates = dict(ex.map(_gen, uniq))
    report["costs"]["image_calls"] += sum(1 for r in plates.values()
                                          if r.get("ok") and not r.get("cached"))
    qa = {"checked": False}
    plate_realistic_by_prompt: dict = {}   # DESIGN §11 disclosure (WP10)
    if plate_qa_on:
        items = [{"path": plates[p]["path"], "subject": p.split(". ")[1]
                  if ". " in p else p, "prompt": p}
                 for p in uniq if plates[p].get("ok")]
        qa = plate_qa(items, bible.get("illustration_style", ""),
                      work / "plate_sheet.jpg")
        report["costs"]["vision_calls"] += 1
        for i, it in enumerate(items):
            plate_realistic_by_prompt[it["prompt"]] = (qa.get("realistic")
                                                        or {}).get(i)
        if qa.get("fail"):
            regen = [items[i]["prompt"] for i in qa["fail"]]
            from engine.v15_plates import PROVIDER_ORDER

            def _next_chain(p):  # a different MODEL, not just a new seed
                used = plates[p].get("provider")
                i = PROVIDER_ORDER.index(used) if used in PROVIDER_ORDER else -1
                return list(PROVIDER_ORDER[i + 1:]) + list(PROVIDER_ORDER[:i + 1])

            with ThreadPoolExecutor(max_workers=3) as ex:
                redo = dict(ex.map(lambda p: _gen(p, 1, _next_chain(p)), regen))
            report["costs"]["image_calls"] += sum(
                1 for r in redo.values() if r.get("ok") and not r.get("cached"))
            ok_redo = {p: r for p, r in redo.items() if r.get("ok")}
            qa2 = plate_qa([{"path": r["path"], "subject": p.split(". ")[1]
                             if ". " in p else p} for p, r in ok_redo.items()],
                           bible.get("illustration_style", ""),
                           work / "plate_sheet_regen.jpg") if ok_redo else {}
            report["costs"]["vision_calls"] += 1 if ok_redo else 0
            still = set()
            for j, (p, r) in enumerate(ok_redo.items()):
                if j in qa2.get("fail", {}):  # incl. OCR hits (no LLM needed)
                    still.add(p)
                plates[p] = r  # regenerated plate replaces the failed one
                plate_realistic_by_prompt[p] = (qa2.get("realistic")
                                                or {}).get(j)
            for p in regen:
                if p not in ok_redo:
                    still.add(p)
            qa["regenerated"] = len(regen)
            qa["still_failing"] = sorted(x[:100] for x in still)
            qa["second_check"] = bool(qa2.get("checked"))
            for p in still:
                plates[p] = dict(plates[p], qa_fail=True)
    report["plate_qa"] = {k: qa.get(k) for k in
                          ("checked", "ocr_checked", "fail", "ocr_hits",
                           "regenerated", "still_failing", "second_check",
                           "reason")}
    # final prompt -> path map, AFTER any regeneration replaced a path;
    # None (unknown/unanswered) is kept as None, never defaulted here —
    # engine.v16_manifest treats None conservatively (assume realistic).
    report["plate_realistic"] = {
        plates[p]["path"]: v for p, v in plate_realistic_by_prompt.items()
        if plates.get(p, {}).get("ok")}
    if not plate_qa_on:
        report["plate_qa"]["reason"] = "plate QA disabled (--no-plate-qa)"
    report["plate_failures"] = fail_log
    providers = {}
    for r in plates.values():
        if r.get("ok"):
            providers[r["provider"]] = providers.get(r["provider"], 0) + 1
    report["plate_providers"] = providers
    info = {}
    for p, r in plates.items():
        if r.get("ok"):
            info[p] = analyze_subject(r["path"])
    report["timings"]["plates_s"] = round(time.time() - t0, 1)

    # 5. shot grammars -> Scene IR
    specs, events, meta = {}, {}, {}
    for s in shots:
        b = s["beat"]
        scene_id = f"{sid}_{b['beat_id']}_S{s['idx'] + 1}"
        dur = round(s["t1"] - s["t0"], 3)
        wts = [w["t0"] for w in timing[b["beat_id"]]["words"]]
        base = s["t0"]

        def t_of(word, _w=wts, _b=base, _d=dur):
            t = LEAD_S + _w[min(max(0, int(word)), len(_w) - 1)] - _b
            return round(min(max(t, 0.15), max(0.2, _d - 0.35)), 3)

        pl = [({"path": plates[p]["path"], "info": info.get(p)}
               if plates.get(p, {}).get("ok") else None) for p in s["prompts"]]
        res = compile_shot({"scene_id": scene_id, "duration": dur,
                            "shot": s["shot"], "plates": pl, "t_of": t_of,
                            "first": b is story["beats"][0] and s["idx"] == 0},
                           bible)
        ok, errs = validate_scene_spec(res["spec"])
        if not ok:
            raise ValueError(f"{scene_id} invalid Scene IR: {errs[:3]}")
        key = f"{b['beat_id']}_S{s['idx'] + 1}"
        specs[key] = res["spec"]
        events[key] = res["events"]
        meta[key] = {"beat": b["beat_id"], "t0": s["t0"], "dur": dur,
                     "kind": s["shot"]["kind"], "tier": res["asset_tier"],
                     "qa_fail": any(plates.get(p, {}).get("qa_fail")
                                    for p in s["prompts"]),
                     "function": b.get("function")}
        (work / "scenes" / f"{key}.spec.json").write_text(
            json.dumps(res["spec"], indent=1))

    # 6. §24 keys + §25 production plan + render
    t0 = time.time()
    index = load_index(work)
    scene_inputs, backends = {}, {}
    for key, spec in specs.items():
        be, reason = select_backend(spec, backend)
        from engine.asset_pipeline import stage_assets
        from engine.scene_renderer import RENDER_PROJECT
        staged, _ = stage_assets(spec, RENDER_PROJECT / "public")
        k = scene_cache_key(spec_hash(compile_spec(staged)), style_hash(bible),
                            be.name, str(be.capabilities()["version"]),
                            RENDER_CONFIG)
        scene_inputs[key] = {"key": k,
                             "output": str(work / "scenes" / f"{key}.mp4")}
        backends[key] = (be, reason)
    captions, narr, beds = {}, {}, {}
    first_shot = {}
    for key, m in meta.items():
        first_shot.setdefault(m["beat"], key)
    for b in story["beats"]:
        bid = b["beat_id"]
        captions[first_shot[bid]] = caption_cues(timing[bid], LEAD_S)
    cap_h = caption_plan_hash({"c": captions, "e": events}, bible)
    nar_h = narration_plan_hash({b["beat_id"]: b["narration"]
                                 for b in story["beats"]})

    # V16 (WP9): mood-tagged music selected from the story arc (per-shot
    # "function" weighted by duration), library SFX, and the WP6 brand
    # sting — each with a load-bearing fallback to the existing procedural
    # bed/SFX when the on-disk library has nothing for a mood/kind.
    from engine.v16_audio import load_sfx_library, select_music_for_story
    from engine import brand as brand_mod
    music_sel = select_music_for_story(
        [m["function"] for m in meta.values()],
        [m["dur"] for m in meta.values()], REPO / "assets" / "music",
        seed=sid)
    sfx_lib = load_sfx_library(REPO / "assets" / "sfx")
    audio_brand = brand_mod.load_brand()
    sting_path = work / "sting.wav"
    brand_mod.sting_audio(sting_path, audio_brand)
    report["audio_v16"] = {"mood": music_sel["mood"],
                           "mood_weights": music_sel["weights"],
                           "track": (str(music_sel["track"]["path"])
                                     if music_sel["track"] else None),
                           "sfx_kinds": sorted(sfx_lib.keys())}

    bed_h = bed_plan_hash({
        "intensity": {k: INTENSITY.get(m["function"], 0.6)
                      for k, m in meta.items()},
        "track": report["audio_v16"]["track"],
        "sfx": {k: str(v["path"]) for k, v in sfx_lib.items()},
        "brand_sting": {"version": audio_brand.get("version"),
                        "sting": audio_brand.get("sting")}})
    out_final = work / "final.mp4"
    plan = plan_production(index, scene_inputs, cap_h, nar_h, bed_h, out_final)
    report["production"] = {k: plan[k] for k in ("render", "reuse", "reasons",
                                                 "rebuild_audio",
                                                 "rebuild_composite")}
    render_s = {}
    for key in plan["render"]:
        be = backends[key][0]
        tr = time.time()
        res = be.render(specs[key], scene_inputs[key]["output"],
                        concurrency=RENDER_CONFIG["concurrency"])
        if not res.get("ok"):
            raise RuntimeError(f"{key} render failed: {str(res)[:400]}")
        record_scene(index, scene_inputs[key]["key"], key,
                     Path(scene_inputs[key]["output"]),
                     float(specs[key]["duration_s"]))
        render_s[key] = round(time.time() - tr, 1)
        save_index(work, index)
    report["render_seconds"] = render_s
    report["timings"]["render_s"] = round(time.time() - t0, 1)

    # 7. assembly: captions AFTER composition + audio + mux
    t0 = time.time()
    arep = {}
    if plan["rebuild_composite"]:
        scenes = []
        beat_of = {b["beat_id"]: b for b in story["beats"]}
        for key, m in meta.items():
            bid = m["beat"]
            sc = {"scene_id": key, "video": scene_inputs[key]["output"],
                  "intensity": INTENSITY.get(m["function"], 0.6),
                  "sfx": list(events.get(key) or [])}
            if first_shot[bid] == key:
                beat_dur = LEAD_S + tts[bid] + TAIL_S
                sc["captions"] = captions[key]
                sc["narration"] = {"beat_id": bid,
                                   "text": beat_of[bid]["narration"],
                                   "offset": LEAD_S, "span_s": beat_dur}
                if bid != story["beats"][0]["beat_id"]:
                    sc["sfx"].insert(0, {"t": 0.0, "kind": "whoosh",
                                         "gain": 0.55})
            scenes.append(sc)
        from engine.v15_shots import lighten
        cap_bible = json.loads(json.dumps(bible))  # readable active word
        cap_bible["palette"]["accent"] = lighten(bible["palette"]["accent"],
                                                 165.0)
        music_dict = {"track": music_sel["track"]["path"], "gain": 0.16} \
            if music_sel["track"] else {"gain": 0.9}
        arep = assemble({"story_id": sid, "story_dir": str(story_dir),
                         "bible": cap_bible, "scenes": scenes,
                         "music": music_dict, "sfx_library": sfx_lib,
                         "sting_audio": str(sting_path),
                         "single_pass": True,
                         "out": str(out_final)}, work)
        (work / "assembly_report.json").write_text(json.dumps(arep, indent=1))
        record_assembly(index, plan["assembly_key"], out_final, cap_h, nar_h,
                        bed_h)
        save_index(work, index)
    report["timings"]["assembly_s"] = round(time.time() - t0, 1)
    # manifest_rows computed unconditionally (not just on a fresh composite
    # rebuild): `events` (step 5) carries every shot's sfx kinds regardless
    # of the render/assembly cache state, so a cache-hit run still gets a
    # complete audio asset list for the manifest (WP10).
    kinds_used = {ev["kind"] for evs in events.values() for ev in (evs or [])}
    if len(story["beats"]) > 1:
        kinds_used.add("whoosh")  # per-beat whoosh, inserted at assembly time
    from engine.v16_audio import manifest_rows
    report["audio_v16"]["manifest_rows"] = manifest_rows(
        music_sel["track"], {k: v for k, v in sfx_lib.items() if k in kinds_used},
        sting_path)

    # 8. gate (recomputed from artifacts; composite cache hit gated alike)
    #    + WP10: distinctness + §10.2 scorecard, + the license manifest.
    from engine.v16_gate import run_gate
    from engine.v16_manifest import (build_manifest, check_manifest_complete,
                                     llm_calls_since, load_distinctness_history,
                                     record_distinctness)
    t0 = time.time()
    history = load_distinctness_history()
    gate = run_gate(work, story, meta, specs, timing, captions, LEAD_S,
                    use_judge=use_judge, plate_qa=report["plate_qa"],
                    voice=report["voice"], brand=audio_brand,
                    plates=plates, sting_present=sting_path.exists(),
                    video_id=sid, history=history)
    report["costs"]["vision_calls"] += gate.get("judge_calls", 0)
    report["gate"] = gate
    report["publish_gate"] = gate["verdict"]
    report["timings"]["gate_s"] = round(time.time() - t0, 1)
    report["shots"] = meta

    # manifest (DESIGN §11, WP10): built from the same provenance the gate
    # just checked, saved regardless of verdict (a HOLD/FAIL still needs an
    # explainable manifest) and cross-checked against the render asset log.
    from engine.v15_gate import _plate_paths
    plate_paths_used = _plate_paths(specs)
    manifest = build_manifest(
        video_id=sid, brand=audio_brand, voice=report["voice"], plates=plates,
        plate_realistic=report.get("plate_realistic"),
        audio_rows=report["audio_v16"].get("manifest_rows") or [],
        llm_calls=llm_calls_since(t_start, time.time()), verdict=gate["verdict"])
    manifest["completeness"] = check_manifest_complete(
        manifest, plate_paths=plate_paths_used, voice_wav=work / "voice.wav",
        audio_rows=report["audio_v16"].get("manifest_rows") or [])
    manifest_dir = ROOT / "build" / "v16" / sid
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=1))
    (work / "manifest.json").write_text(json.dumps(manifest, indent=1))
    report["manifest_path"] = str(manifest_path)
    report["manifest"] = manifest
    record_distinctness({
        "video_id": sid,
        "signature": gate["checks"]["distinctness"]["signature"],
        "plate_hashes": gate["checks"]["distinctness"]["plate_hashes"]})

    report["timings"]["total_s"] = round(time.time() - t_start, 1)
    (work / "pipeline_report.json").write_text(json.dumps(report, indent=1))
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="V15 autonomous production")
    ap.add_argument("--story", required=True)
    ap.add_argument("--work", required=True)
    ap.add_argument("--backend", default="auto")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-plate-qa", action="store_true")
    a = ap.parse_args()
    rep = run_pipeline(Path(a.story), Path(a.work), backend=a.backend,
                       use_llm=not a.no_llm, use_judge=not a.no_judge,
                       plate_qa_on=not a.no_plate_qa)
    print(json.dumps({k: rep.get(k) for k in
                      ("story_id", "deck", "plan", "plate_providers",
                       "plate_qa", "timings", "costs", "publish_gate")},
                     indent=1))
    print(json.dumps(rep["gate"].get("failures"), indent=1))
    return 0 if rep["publish_gate"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
