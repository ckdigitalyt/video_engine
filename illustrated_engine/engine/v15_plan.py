"""V15 — Beat Visual Plan (BVP): the semantic layer between story and Scene IR.

V14 derived visuals from keyword `if`s (`_subject_kind`), clause-chopped the
image-prompt field into process nodes, and put raw `visual_question` /
`visual_answer` prompt text on screen. The BVP replaces that with ONE cached
LLM call per story (director.text_ask -> llm adapter, stage visual_plan)
that returns, per beat, 1-3 SHOTS:

  plate         {subject, composition, camera, headline?, number?, label?}
  zoom_through  {levels: [{subject, label, word}] x2-4}   (scale descent)
  process       {subject, steps: [{text, word}] x2-4}      (causal chain)

Every shot starts on a narration WORD INDEX, so cuts/reveals land on speech
(times come from v15_timing). Deterministic validation after the call:
  - shot kinds/cameras/compositions from closed enums; word indices valid
    and strictly increasing, first shot at word 0
  - on-screen copy length caps (headline <= 5 words, labels/steps <= 4)
  - FACTUAL INTEGRITY: any digit sequence shown on screen must occur
    verbatim in the beat narration (narration is the fact-checked text) —
    the model cannot invent a number
  - image subjects non-empty, bounded, no request for on-image text
On failure: one retry with the error list appended; then the DETERMINISTIC
fallback plan (story fields only; recorded as degraded) — the V14-style path
remains the floor, never a silent downgrade.

Cache: build/cache/v15_plans/<key>.json, key = sha16(beats + title + bible
style + PROMPT_VERSION). Same inputs -> same plan (selection is
deterministic given the cache; the model runs at temperature 0).

CLI: python3 -m engine.v15_plan <story_dir> [--no-llm] [--force]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "build" / "cache" / "v15_plans"
PROMPT_VERSION = "bvp/1.6"

SHOT_KINDS = ("plate", "zoom_through", "process")
CAMERAS = ("push_in", "pull_out", "pan_left", "pan_right", "rise", "descend")
COMPOSITIONS = ("subject_low", "subject_high", "centered")
# decision #18 item 3: per-shot VIEW (scale/viewpoint). Dry run 5's plan put
# 15/21 shots on "a small icy world floating in space" — same scale, same
# viewpoint, noun-swappable; the judge called it templated. Every plate/
# process shot now names its view, and variety_errors() enforces spread.
VIEWS = ("wide", "medium", "close", "surface", "cutaway", "comparison",
         "observer")
VARIETY_MAX_SHARE = 0.4     # no view on more than 40% of shots (>= 6 shots)
VARIETY_MIN_DISTINCT = 4    # at least 4 distinct views (>= 8 shots)
MAX_SHOTS = 3
MIN_SHOT_WORDS = 4  # a shot shorter than ~4 words (~1.3 s) is a flicker
WORDS_PER_SHOT = 13  # ~4 s of speech: longer beats need another shot

_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_NUMWORD = re.compile(r"(?i)\b(one|two|three|four|five|six|seven|eight|nine|"
                      r"ten|twelve|twenty|thirty|forty|fifty|hundred|"
                      r"thousand|million|billion|trillion|half|tenth|"
                      r"hundredth|thousandth|dozen)\b")
_TEXTY = re.compile(r"\b(text|caption|label(?:led|s)?|title|words?|letters?|"
                    r"typography|infographic|chart)\b", re.I)


def _digits(s: str) -> list:
    return [m.group().replace(",", "") for m in _NUM.finditer(str(s))]


def _spoken_digits(narration: str) -> set:
    """decision #18 item 6: figures SPOKEN in the narration, whether written
    as digits or spelled out. Auto-generated narration spells numbers for
    the TTS ("four hundred thirty"), so the old verbatim-digit check
    rejected every correct on-screen figure ("430") and burned the plan's
    one retry (dry run 5's plan came from llm_retry for this reason). The
    caption pipeline's own numeralizer defines what counts as spoken."""
    from engine.voice.text import numeralize_cue_words
    words = [{"w": w, "t0": 0.0, "t1": 0.0} for w in str(narration).split()]
    num = " ".join(w["w"] for w in numeralize_cue_words(words))
    return set(_digits(narration)) | set(_digits(num))


def _words(narration: str) -> list:
    return str(narration).split()


# --------------------------------------------------------------- prompt --

def _identity_block(subject: dict | None) -> str:
    """decision #18 item 2: the recurring subject's identity (engine.
    subject_bible) so the planner writes every shot about THIS specific
    thing instead of a generic stand-in."""
    subject = subject or {}
    if not subject.get("description"):
        return ""
    name = subject.get("name") or str(subject.get("concept_id") or "").replace("_", " ")
    return (f"\nRECURRING SUBJECT: {name} — {subject['description']}\n"
            f"Whenever a shot shows it, call it \"{name}\" in the subject and "
            "describe it consistently with that look: it must read as this "
            "specific thing, never a generic stand-in.\n")


def build_prompt(story: dict, bible: dict, subject: dict | None = None) -> str:
    beats_txt = []
    for b in story["beats"]:
        ws = _words(b["narration"])
        numbered = " ".join(f"{i}:{w}" for i, w in enumerate(ws))
        beats_txt.append(
            f"- {b['beat_id']} [{b.get('function', '')}] words: {numbered}\n"
            f"  visual idea (hint, may improve): {b.get('visual_answer', '')}")
    style = bible.get("illustration_style", "editorial illustration")
    return f"""You are the visual director of a vertical (9:16) explainer short.
Title: {story.get('title', story['story_id'])}
Illustration style (applied automatically to every image; do NOT repeat it): {style}
{_identity_block(subject)}
For EACH beat below, plan 1-{MAX_SHOTS} SHOTS that SHOW what the narration says,
changing picture roughly every 2.5-4 seconds (about every 8-12 words):
a beat of N words needs at least ceil(N/{WORDS_PER_SHOT}) shots.
Each shot starts at a word index of that beat ("start_word"); the first shot
of a beat starts at 0; indices strictly increase; >= {MIN_SHOT_WORDS} words per shot.

Shot kinds:
 "plate": one illustrated image. Fields: subject, view, composition, camera,
    optional headline, optional number, optional label.
 "zoom_through": a continuous dive through 2-4 nested scales (e.g. hair ->
    cell -> mitochondrion -> DNA). Fields: levels=[{{subject, label, word}}].
    Use ONLY when the narration itself moves through sizes/scales.
 "process": a cause->effect chain over a background image. Fields: subject
    (the background image), view, start_word, steps=[{{text, word}}] (2-4
    steps, each <= 4 words).
    Use for mechanisms ("X causes Y, so Z").

Field rules:
 subject: ONE concrete, physically drawable scene for an illustrator: the
    real thing(s) and what is happening to them, specific to this beat's
    words. Never an abstract idea, graph or "comparison of layers" — show
    the physical thing it happens to. Do not add people/figures unless the
    narration itself is about people. No words, letters, labels or diagram text
    in the image. NO digits, numbers, text, labels, rulers-with-readings or
    charts in the subject (figures are added as overlay typography).
    No split panels. <= 45 words.
 view: the shot's scale/viewpoint, one of {', '.join(VIEWS)}:
    wide = establishing view with surroundings; medium = the subject and its
    immediate context; close = extreme close-up of a surface/detail filling
    the frame; surface = standing ON or right next to it, ground-level;
    cutaway = cross-section / inside view; comparison = two things side by
    side; observer = people observing it (ONLY if the narration mentions
    people). The view is applied to the image automatically.
 composition: "subject_low" (subject large in the lower two thirds, top
    third calm for a headline), "subject_high", or "centered".
 camera: one of {', '.join(CAMERAS)} — choose the move that fits the idea
    (push_in = focus/discover, pull_out = reveal context/scale, pans = travel
    along a process, rise/descend = up/down a structure).
 headline: <= 5 words of editorial on-screen copy (NOT a caption, NOT the
    narration verbatim). Use for the hook question and the payoff.
 number: {{"text": "...", "word": i}} — a figure the narration SAYS at word i,
    shown as a giant number with its unit (e.g. "0.1°C", "2 nm", "30 TRILLION").
    Only a figure the narration actually says (spelled-out numbers count:
    "four hundred thirty" may be shown as "430").
 label: {{"text": "<= 3 words", "word": i}} names the main subject when spoken.
 levels[].label / steps[].text: <= 4 words; digits only if spoken.
 word fields: index of the narration word where that element should appear.

SHOT VARIETY (checked automatically): consecutive shots never share the
same view; no view on more than {int(VARIETY_MAX_SHARE * 100)}% of all shots; use at least
{VARIETY_MIN_DISTINCT} different views across the video. The recurring subject shown whole and
floating in empty space is ONE view ("wide" or "medium") — do not repeat it
shot after shot; go to its surface, a close detail, a cutaway, or the
event/context around it instead.

The FIRST beat's first shot must be a striking "plate" with a headline that
poses the question. If that beat's narration contrasts or compares two or
more named things, the hook shot's subject must show ALL of them together
in frame 0 (not just one) — the contradiction IS the hook. The hook shot
must stop a scroll on its own: never the recurring subject shown whole and
floating in empty space (that is the reusable template shot); show it close,
from a dramatic angle, at the moment something is happening to it, or right
beside what contradicts it. Its view is "medium" (framed close and dramatic
automatically), "comparison", "surface" or "cutaway" — not "wide". The last beat
should resolve it with a headline that echoes the hook's own wording or
imagery (the viewer should recognize the hook again, now resolved).

Beats:
{chr(10).join(beats_txt)}

Return ONLY JSON:
{{"beats":[{{"beat_id":"B1","shots":[{{"kind":"plate","start_word":0,"subject":"...","view":"medium","composition":"subject_low","camera":"push_in","headline":"..."}}]}}]}}"""


# ------------------------------------------------------------ validation --

def _check_copy(txt, max_words: int, narr_digits: set, where: str,
                errs: list) -> None:
    if not isinstance(txt, str) or not txt.strip():
        errs.append(f"{where}: empty text")
        return
    if len(txt.split()) > max_words:
        errs.append(f"{where}: {txt!r} exceeds {max_words} words")
    if len(txt) > 34:
        errs.append(f"{where}: {txt!r} longer than 34 characters")
    for d in _digits(txt):
        if d not in narr_digits:
            errs.append(f"{where}: number {d!r} is not spoken in the "
                        f"narration (factual integrity)")


def _check_word(v, n_words: int, where: str, errs: list) -> None:
    if not isinstance(v, int) or not (0 <= v < n_words):
        errs.append(f"{where}: word index {v!r} out of range 0..{n_words - 1}")


def _check_subject(v, where: str, errs: list) -> None:
    if not isinstance(v, str) or len(v.split()) < 3:
        errs.append(f"{where}: subject must be a concrete description")
    elif len(v.split()) > 60:
        errs.append(f"{where}: subject longer than 60 words")
    elif _NUM.search(v) or _TEXTY.search(v):
        # image models render requested numbers/labels as garbled lettering;
        # figures belong in the vector typography layer, not the plate
        errs.append(f"{where}: subject must not ask the image for numbers, "
                    f"text, labels or charts (shown by the overlay instead)")


def validate_plan(plan: dict, story: dict) -> list:
    errs = []
    if not isinstance(plan, dict) or not isinstance(plan.get("beats"), list):
        return ["plan must be {\"beats\": [...]}"]
    by_id = {b.get("beat_id"): b for b in plan["beats"] if isinstance(b, dict)}
    for beat in story["beats"]:
        bid = beat["beat_id"]
        pb = by_id.get(bid)
        if not pb:
            errs.append(f"{bid}: missing from plan")
            continue
        ws = _words(beat["narration"])
        n = len(ws)
        digits = _spoken_digits(beat["narration"])
        shots = pb.get("shots")
        if not isinstance(shots, list) or not (1 <= len(shots) <= MAX_SHOTS):
            errs.append(f"{bid}: needs 1-{MAX_SHOTS} shots")
            continue
        # shot count vs length is prompt GUIDANCE, not a hard error: the
        # pipeline's punch-in split (v15_pipeline.split_long_holds) enforces
        # the <= 4.5 s visual-hold rule deterministically for plate shots
        prev = -1
        for si, sh in enumerate(shots):
            w = f"{bid}.shots[{si}]"
            if not isinstance(sh, dict):
                errs.append(f"{w}: must be an object")
                continue
            kind = sh.get("kind")
            if kind not in SHOT_KINDS:
                errs.append(f"{w}: kind must be one of {SHOT_KINDS}")
                continue
            sw = sh.get("start_word")
            _check_word(sw, n, f"{w}.start_word", errs)
            if si == 0 and sw != 0:
                errs.append(f"{w}: first shot must start at word 0")
            if isinstance(sw, int):
                if si > 0 and sw - prev < MIN_SHOT_WORDS:
                    errs.append(f"{w}: starts {sw - prev} words after the "
                                f"previous shot (min {MIN_SHOT_WORDS})")
                prev = sw
            if kind in ("plate", "process"):
                _check_subject(sh.get("subject"), w, errs)
                if sh.get("view") is not None and sh["view"] not in VIEWS:
                    errs.append(f"{w}: view must be one of {VIEWS}")
            if kind == "plate":
                if sh.get("camera") not in CAMERAS:
                    errs.append(f"{w}: camera must be one of {CAMERAS}")
                if sh.get("composition", "centered") not in COMPOSITIONS:
                    errs.append(f"{w}: composition must be one of {COMPOSITIONS}")
                if sh.get("headline") is not None:
                    _check_copy(sh["headline"], 5, digits, f"{w}.headline", errs)
                for key, mx in (("number", 4), ("label", 3)):
                    el = sh.get(key)
                    if el is None:
                        continue
                    if not isinstance(el, dict):
                        errs.append(f"{w}.{key}: must be an object")
                        continue
                    _check_copy(el.get("text"), mx, digits, f"{w}.{key}", errs)
                    _check_word(el.get("word"), n, f"{w}.{key}.word", errs)
                    if key == "number" and not _digits(el.get("text", "")) \
                            and not _NUMWORD.search(str(el.get("text"))):
                        errs.append(f"{w}.number: must contain a figure")
            elif kind == "zoom_through":
                lv = sh.get("levels")
                if not isinstance(lv, list) or not (2 <= len(lv) <= 4):
                    errs.append(f"{w}: zoom_through needs 2-4 levels")
                    continue
                lw = -1
                for li, lev in enumerate(lv):
                    lp = f"{w}.levels[{li}]"
                    if not isinstance(lev, dict):
                        errs.append(f"{lp}: must be an object")
                        continue
                    _check_subject(lev.get("subject"), lp, errs)
                    _check_copy(lev.get("label"), 4, digits, f"{lp}.label", errs)
                    _check_word(lev.get("word"), n, f"{lp}.word", errs)
                    if isinstance(lev.get("word"), int):
                        if lev["word"] <= lw:
                            errs.append(f"{lp}: level words must increase")
                        lw = lev["word"]
            elif kind == "process":
                st = sh.get("steps")
                if not isinstance(st, list) or not (2 <= len(st) <= 4):
                    errs.append(f"{w}: process needs 2-4 steps")
                    continue
                for ti, step in enumerate(st):
                    tp = f"{w}.steps[{ti}]"
                    if not isinstance(step, dict):
                        errs.append(f"{tp}: must be an object")
                        continue
                    _check_copy(step.get("text"), 4, digits, tp, errs)
                    _check_word(step.get("word"), n, f"{tp}.word", errs)
    first = (by_id.get(story["beats"][0]["beat_id"]) or {}).get("shots") or []
    if first and isinstance(first[0], dict) and not (
            first[0].get("kind") == "plate" and first[0].get("headline")):
        errs.append(f"{story['beats'][0]['beat_id']}.shots[0]: the hook shot "
                    "must be a plate with a headline")
    return errs


def variety_errors(plan: dict) -> list:
    """decision #18 item 3: per-shot visual variety across the whole video
    (plate/process shots in timeline order). Kept OUT of validate_plan: a
    plan failing only these is still a valid plan (make_plan accepts it
    with recorded warnings after the retry rather than dropping to the
    salvage/fallback floor, which has less variety, not more)."""
    seq = [(pb.get("beat_id"), sh.get("view"))
           for pb in (plan.get("beats") or []) if isinstance(pb, dict)
           for sh in (pb.get("shots") or [])
           if isinstance(sh, dict) and sh.get("kind") in ("plate", "process")]
    errs = []
    missing = [b for b, v in seq if v not in VIEWS]
    if missing:
        errs.append(f"every plate/process shot needs a view ({', '.join(VIEWS)}); "
                    f"missing in {sorted(set(missing))[:6]}")
    views = [v for _, v in seq if v in VIEWS]
    for k in range(1, len(seq)):
        if seq[k][1] in VIEWS and seq[k][1] == seq[k - 1][1]:
            errs.append(f"{seq[k][0]}: same view '{seq[k][1]}' as the previous "
                        "shot — change the viewpoint/scale")
    n = len(views)
    if n >= 6:
        for v in sorted(set(views)):
            if views.count(v) / n > VARIETY_MAX_SHARE:
                errs.append(f"view '{v}' used on {views.count(v)}/{n} shots "
                            f"(max {int(VARIETY_MAX_SHARE * 100)}%)")
    if n >= 8 and len(set(views)) < VARIETY_MIN_DISTINCT:
        errs.append(f"only {len(set(views))} distinct views across {n} shots "
                    f"(need >= {VARIETY_MIN_DISTINCT})")
    return errs


def _repair(plan: dict, story: dict) -> dict:
    """Deterministic, meaning-preserving normalizations applied BEFORE
    validation: clamp element words into their shot, uppercase copy, drop
    composition typos to 'centered'. Never invents content."""
    by_id = {b["beat_id"]: b for b in story["beats"]}
    for pb in plan.get("beats", []) if isinstance(plan, dict) else []:
        if not isinstance(pb, dict) or pb.get("beat_id") not in by_id:
            continue
        for si, sh in enumerate(pb.get("shots") or []):
            if not isinstance(sh, dict):
                continue
            # decision #18 item 6: a beat's first shot always starts at
            # word 0 — fill an omitted index instead of failing the plan
            if si == 0 and sh.get("start_word") is None:
                sh["start_word"] = 0
            # degenerate multi-element shots collapse to a plate (content
            # kept: the single step/level becomes the label/subject)
            if sh.get("kind") == "process" and isinstance(sh.get("steps"), list) \
                    and len(sh["steps"]) < 2:
                one = (sh.pop("steps") or [None])[0]
                sh["kind"] = "plate"
                sh.setdefault("camera", "push_in")
                if isinstance(one, dict) and one.get("text"):
                    sh["label"] = {"text": one["text"],
                                   "word": one.get("word", sh.get("start_word", 0))}
            if sh.get("kind") == "zoom_through" and \
                    isinstance(sh.get("levels"), list) and len(sh["levels"]) < 2:
                one = (sh.pop("levels") or [{}])[0] or {}
                sh["kind"] = "plate"
                sh.setdefault("camera", "push_in")
                sh.setdefault("subject", one.get("subject"))
            if sh.get("kind") in ("process", "zoom_through") and \
                    sh.get("camera") not in CAMERAS:
                sh["camera"] = "push_in"
            if sh.get("kind") == "plate" and \
                    sh.get("composition") not in COMPOSITIONS:
                sh["composition"] = "centered"
            if isinstance(sh.get("view"), str):
                sh["view"] = sh["view"].strip().lower()
            if "view" in sh and sh.get("view") not in VIEWS:
                sh.pop("view")
            for key in ("headline",):
                if isinstance(sh.get(key), str):
                    sh[key] = sh[key].strip().upper()
            for key in ("number", "label"):
                if isinstance(sh.get(key), dict) and \
                        isinstance(sh[key].get("text"), str):
                    sh[key]["text"] = sh[key]["text"].strip().upper()
            for coll, fld in (("levels", "label"), ("steps", "text")):
                for el in sh.get(coll) or []:
                    if isinstance(el, dict) and isinstance(el.get(fld), str):
                        el[fld] = el[fld].strip().upper()
    return plan


# -------------------------------------------------------------- fallback --

def _image_safe(text: str) -> str:
    """Strip figures and on-image-text requests from a subject sentence."""
    toks = [t for t in str(text).split()
            if not _NUM.search(t) and not _TEXTY.fullmatch(t.strip(".,;:"))]
    out = " ".join(toks)
    return _TEXTY.sub("", out).replace("  ", " ").strip(" ,.;:—")


def _cap_words(text: str, n: int, chars: int = 34) -> str:
    ws = str(text).split()[:n]
    while ws and len(" ".join(ws)) > chars:
        ws = ws[:-1]
    return " ".join(ws)


def _splits(ws: list, k: int) -> list:
    """k shot start indices: near-equal spans snapped to punctuation."""
    starts = [0]
    for j in range(1, k):
        target = round(j * len(ws) / k)
        cands = [i + 1 for i, w in enumerate(ws[:-1])
                 if re.search(r"[,.;:—]$", w)
                 and abs(i + 1 - target) <= 3]
        cut = min(cands, key=lambda c: abs(c - target)) if cands else target
        if cut - starts[-1] >= MIN_SHOT_WORDS and len(ws) - cut >= MIN_SHOT_WORDS:
            starts.append(cut)
    return starts


def fallback_plan(story: dict) -> dict:
    """Deterministic plan from story fields only (no LLM). Floor tier:
    plate shots split on punctuation near equal spans; subjects from the
    story's own visual fields made image-safe; hook headline = the story
    title; first spoken figure as a number (verbatim from narration, so
    factual integrity holds by construction). Valid by construction."""
    beats = []
    cams = ("push_in", "pull_out", "pan_right", "rise", "pan_left", "descend")
    for bi, b in enumerate(story["beats"]):
        ws = _words(b["narration"])
        k = min(MAX_SHOTS, max(1, -(-len(ws) // WORDS_PER_SHOT)))
        srcs = [b.get("visual_answer"), b.get("claim"), b["narration"],
                b.get("visual_question")]
        subjects = [x for x in (_image_safe(t) for t in srcs if t)
                    if len(x.split()) >= 3] or ["an evocative scene of "
                                                + story.get("title", "the topic")]
        shots = []
        for si, st in enumerate(_splits(ws, k)):
            shots.append({"kind": "plate", "start_word": st,
                          "subject": " ".join(subjects[si % len(subjects)]
                                              .split()[:45]),
                          "composition": "subject_low" if (bi == 0 and si == 0)
                          else "centered",
                          "camera": cams[(bi + si) % len(cams)],
                          "view": VIEWS[(len(shots) + sum(
                              len(x["shots"]) for x in beats)) % 4]})
        if bi == 0:
            shots[0]["headline"] = _cap_words(
                str(story.get("title") or story["story_id"]).upper(), 5)
        for i, w in enumerate(ws):
            if _digits(w):
                owner = [s for s in shots if s["start_word"] <= i][-1]
                nxt = ws[i + 1].strip(".,;:") if i + 1 < len(ws) else ""
                txt = w.strip(".,;:") + ("" if _digits(nxt) else " " + nxt)
                owner["number"] = {"text": _cap_words(txt.upper(), 2, 20),
                                   "word": i}
                break
        beats.append({"beat_id": b["beat_id"], "shots": shots})
    return {"beats": beats}


def salvage(plan: dict, story: dict) -> tuple:
    """Deterministic salvage of an LLM plan that failed validation twice:
    DROP (never invent) whatever is invalid — an unspoken number, an
    over-long copy line, a 4th shot, a cut too close to the previous one —
    strip figures from image subjects, fill a missing beat or hook headline
    from the deterministic fallback. -> (plan, dropped[])."""
    fb = {b["beat_id"]: b for b in fallback_plan(story)["beats"]}
    by_id = {b.get("beat_id"): b for b in (plan.get("beats") or [])
             if isinstance(b, dict)}
    dropped, beats = [], []
    for beat in story["beats"]:
        bid = beat["beat_id"]
        ws = _words(beat["narration"])
        n, digits = len(ws), _spoken_digits(beat["narration"])
        pb = by_id.get(bid)
        shots = [sh for sh in (pb or {}).get("shots") or []
                 if isinstance(sh, dict) and sh.get("kind") in SHOT_KINDS]
        if not shots:
            dropped.append(f"{bid}: beat replaced by fallback")
            beats.append(fb[bid])
            continue
        keep, prev = [], None
        for sh in shots[:MAX_SHOTS]:
            sw = sh.get("start_word") if not keep else sh.get("start_word")
            if not keep:
                sh["start_word"] = 0
            elif not isinstance(sw, int) or sw >= n or \
                    sw - prev < MIN_SHOT_WORDS:
                dropped.append(f"{bid}: shot at word {sw} dropped")
                continue
            prev = sh["start_word"]
            for key in ("subject",):
                if isinstance(sh.get(key), str):
                    sh[key] = _image_safe(sh[key])
            for key, mx in (("headline", 5), ("number", 4), ("label", 3)):
                el = sh.get(key)
                if el is None:
                    continue
                e = []
                if key == "headline":
                    _check_copy(el, mx, digits, key, e)
                elif isinstance(el, dict):
                    _check_copy(el.get("text"), mx, digits, key, e)
                    _check_word(el.get("word"), n, key, e)
                else:
                    e.append("bad")
                if e:
                    sh.pop(key)
                    dropped.append(f"{bid}: {key} dropped ({e[0][:60]})")
            for coll, fld, mx in (("levels", "label", 4), ("steps", "text", 4)):
                if isinstance(sh.get(coll), list):
                    good = []
                    for el in sh[coll]:
                        e = []
                        if isinstance(el, dict):
                            _check_copy(el.get(fld), mx, digits, fld, e)
                            _check_word(el.get("word"), n, fld, e)
                            if coll == "levels":
                                el["subject"] = _image_safe(el.get("subject", ""))
                                _check_subject(el.get("subject"), fld, e)
                        if isinstance(el, dict) and not e and (
                                not good or el["word"] > good[-1]["word"]):
                            good.append(el)
                        else:
                            dropped.append(f"{bid}: {coll[:-1]} dropped")
                    sh[coll] = good
            keep.append(sh)
        beats.append({"beat_id": bid, "shots": keep})
    out = _repair({"beats": beats}, story)
    first = out["beats"][0]["shots"][0]
    if first.get("kind") != "plate" or not first.get("headline"):
        hook = fb[story["beats"][0]["beat_id"]]["shots"][0]
        if first.get("kind") != "plate":
            out["beats"][0]["shots"][0] = hook
        else:
            first["headline"] = hook["headline"]
        dropped.append("hook headline from story title")
    return out, dropped


# ------------------------------------------------------------------ API --

def _parse_json(text: str):
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    for cand in (m.group(), re.sub(r",\s*([}\]])", r"\1", m.group())):
        try:
            return json.loads(cand)
        except Exception:
            pass
    return None


def plan_key(story: dict, bible: dict, subject: dict | None = None) -> str:
    blob = json.dumps({
        "subject": (subject or {}).get("description"),
        "v": PROMPT_VERSION, "title": story.get("title"),
        "beats": [{k: b.get(k) for k in ("beat_id", "function", "narration",
                                          "visual_answer")}
                  for b in story["beats"]],
        "style": bible.get("illustration_style")}, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def make_plan(story: dict, bible: dict, *, use_llm: bool = True,
              force: bool = False, ask=None, subject: dict | None = None) -> dict:
    """-> {"plan", "source": llm|llm_retry|cache|fallback, "errors", "key",
    "llm_calls"}. `ask` overrides the text judge (tests). `subject` is the
    engine.subject_bible result (decision #18), part of the cache key."""
    key = plan_key(story, bible, subject)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cp = CACHE_DIR / f"{key}.json"
    if cp.exists() and not force:
        data = json.loads(cp.read_text())
        if not validate_plan(data["plan"], story):
            return dict(data, source="cache", llm_calls=0)
    calls, errors, plan_last = 0, [], None
    if use_llm:
        if ask is None:
            from functools import partial

            from engine.director import text_ask
            ask = partial(text_ask, stage="visual_plan")
        prompt = build_prompt(story, bible, subject)
        for attempt in range(2):
            p = prompt if attempt == 0 else (
                prompt + "\n\nYour previous answer had these errors — fix "
                "them and return the full JSON again:\n- "
                + "\n- ".join(errors[:25]))
            calls += 1
            raw = ask(p, 0.0, 6000)
            (CACHE_DIR / f"{key}.attempt{attempt}.txt").write_text(
                str(raw))  # diagnosis trail (no secrets: model output only)
            plan = _parse_json(raw)
            if plan is None:
                errors = ["response was not parseable JSON"]
                continue
            plan = _repair(plan, story)
            plan_last = plan
            hard = validate_plan(plan, story)
            soft = variety_errors(plan) if not hard else []
            errors = hard + soft
            if not hard and (not soft or attempt == 1):
                # decision #18 item 3: variety is asked for twice; a valid
                # plan still short on variety after the retry ships with
                # the shortfall recorded (never a silent pass, never a drop
                # to the less-varied salvage/fallback floor).
                src = "llm" if attempt == 0 else "llm_retry"
                data = {"plan": plan, "source": src, "key": key,
                        "errors": [], "variety_warnings": soft,
                        "prompt_version": PROMPT_VERSION}
                cp.write_text(json.dumps(data, indent=1))
                return dict(data, llm_calls=calls)
    if use_llm and plan_last is not None:
        sal, dropped = salvage(json.loads(json.dumps(plan_last)), story)
        if not validate_plan(sal, story):
            data = {"plan": sal, "source": "llm_salvaged", "key": key,
                    "errors": errors, "dropped": dropped,
                    "prompt_version": PROMPT_VERSION}
            cp.write_text(json.dumps(data, indent=1))
            return dict(data, llm_calls=calls)
    plan = fallback_plan(story)
    fb_errs = validate_plan(plan, story)
    if fb_errs:  # the floor itself must be valid — loud, never silent
        raise ValueError(f"fallback plan invalid: {fb_errs[:5]}")
    return {"plan": plan, "source": "fallback", "key": key,
            "errors": errors or (["llm disabled"] if not use_llm else []),
            "llm_calls": calls, "prompt_version": PROMPT_VERSION}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.v15_plan")
    ap.add_argument("story_dir")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    from engine.v15_style import load_style
    sd = Path(a.story_dir)
    story = json.loads((sd / "story.json").read_text())
    res = make_plan(story, load_style(sd, story), use_llm=not a.no_llm,
                    force=a.force)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
