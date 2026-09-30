"""V16 — planner v2: the §8 scene-template library + deterministic template
assignment on top of v15_plan's beat/shot output.

DESIGN §8.1 draws a line between two layers:
  - the LLM (v15_plan.make_plan) proposes SHOT KINDS (plate/zoom_through/
    process) and their content (headline/number/label/levels/steps) —
    unchanged by this module.
  - a DETERMINISTIC pass (this module) then assigns each shot a TEMPLATE
    from the §8.2 library — the editorial/pacing choice of *how* that shot
    is composed and cut, never invented content, never an LLM call.

TEMPLATE_LIBRARY declares, per template: which v15_shots.compile_shot
`kind` it renders as, its duration bounds, its motion-signature target (the
max gap the template design promises between visible changes — tighter
than the §8.2 pacing gate itself, see engine.v15_gate.MAX_HOLD_1_8_S), its
interrupt type, and (when it has one) the content signal that calls for it.

assign_templates() is pure and deterministic: same plan + story -> same
template sequence every time (ties broken by hashing story_id, per §8.1 —
never a random choice at render time). It enforces, repairing where
possible:
  - content signal -> template (number -> BIG_NUMBER, place -> MAP_PIN,
    time span -> TIMELINE_DEEPTIME, two sizes/compare -> SCALE_COMPARE,
    process -> PROCESS_OVER_PLATE, scale dive -> ZOOM_THROUGH)
  - no template appears twice in a row
  - >= 5 distinct templates per video (when it has >= 5 shots)
  - no single template takes more than 35% of total screen time
  - frame 0 is HOOK_PLATE or KINETIC_CLAIM; the last shot is LOOP_BRIDGE

Shot durations aren't known until v15_pipeline's word-timing pass runs, so
this module approximates them from word counts (the same 8-12-words/
2.5-4s calibration v15_plan.build_prompt already uses) purely to rank
templates by screen-time share; the pipeline's real per-shot duration is
authoritative once available (see PROGRESS.md WP7 for the wiring note).

CLI: python3 -m engine.v16_plan <story_dir> [--no-llm]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WORDS_PER_SEC = 13 / 4.0  # matches v15_plan's "8-12 words ~= 2.5-4 s"
MIN_SHOT_S = 0.8


@dataclass(frozen=True)
class TemplateSpec:
    name: str
    shot_kind: str                    # engine.v15_shots.compile_shot `kind`
    duration_bounds: tuple            # (min_s, max_s)
    motion_signature_s: float         # design promise: a change at least
                                       # this often (<=1.0s per DESIGN §8.1)
    interrupt_type: str
    content_signal: str | None = None  # which signal maps to this template
    allowed_beat_functions: tuple = field(default_factory=tuple)  # () = any


TEMPLATE_LIBRARY: dict = {
    "HOOK_PLATE": TemplateSpec(
        "HOOK_PLATE", "plate", (1.5, 3.5), 1.0, "—",
        allowed_beat_functions=("HOOK",)),
    "PLATE_PUSH": TemplateSpec(
        "PLATE_PUSH", "plate", (1.2, 4.4), 1.0, "camera change"),
    "ZOOM_THROUGH": TemplateSpec(
        "ZOOM_THROUGH", "zoom_through", (2.0, 6.0), 1.0, "scale jump",
        content_signal="scale"),
    "PROCESS_OVER_PLATE": TemplateSpec(
        "PROCESS_OVER_PLATE", "process", (2.0, 8.0), 1.0, "overlay build",
        content_signal="process"),
    "PARALLAX_25D": TemplateSpec(
        "PARALLAX_25D", "parallax", (1.5, 3.5), 1.0, "depth move"),
    "KINETIC_CLAIM": TemplateSpec(
        "KINETIC_CLAIM", "kinetic_claim", (0.8, 2.0), 0.6, "type slam"),
    "BIG_NUMBER": TemplateSpec(
        "BIG_NUMBER", "big_number", (1.2, 2.5), 0.8, "number pop",
        content_signal="number"),
    "SCALE_COMPARE": TemplateSpec(
        "SCALE_COMPARE", "scale_compare", (1.5, 3.0), 0.8, "split",
        content_signal="compare"),
    "MAP_PIN": TemplateSpec(
        "MAP_PIN", "map_pin", (1.5, 3.0), 0.8, "map zoom",
        content_signal="place"),
    "TIMELINE_DEEPTIME": TemplateSpec(
        "TIMELINE_DEEPTIME", "timeline", (1.8, 3.5), 0.8, "scroll",
        content_signal="time_span"),
    "LOOP_BRIDGE": TemplateSpec(
        "LOOP_BRIDGE", "loop_bridge", (1.0, 2.5), 1.0, "—",
        allowed_beat_functions=("PAYOFF",)),
}

# Templates with no strong content signal — the pool planner v2 rotates
# through (deterministically) for shots that don't ask for a specific one.
GENERIC_POOL = ("PLATE_PUSH", "PARALLAX_25D", "KINETIC_CLAIM")
MIN_DISTINCT = 5
MAX_SHARE = 0.35

# ZOOM_THROUGH/PROCESS_OVER_PLATE render a v15_shots kind (zoom_through/
# process) that needs fields (levels/steps) only a shot already of that
# ORIGINAL v15_plan kind carries. BIG_NUMBER's compiler has no sensible
# degrade without a number (there is nothing else the template IS).
# Every other template degrades safely off headline/label, which any plate
# shot may or may not have, so it's never a hard requirement. Repair
# passes must not hand a shot a template its own content can't back.
def _compatible(shot: dict, template_name: str) -> bool:
    if template_name == "ZOOM_THROUGH":
        return shot.get("kind") == "zoom_through"
    if template_name == "PROCESS_OVER_PLATE":
        return shot.get("kind") == "process"
    if template_name == "BIG_NUMBER":
        return bool(shot.get("number"))
    if template_name == "KINETIC_CLAIM":
        # its whole point is on-screen type; without a short headline/claim
        # it would fall back to the plate-prompt `subject` sentence, which
        # is 3-60 words of image-generation prose, not on-screen copy.
        return bool(shot.get("headline") or shot.get("claim"))
    return True


def _generic_pool_for(shot: dict) -> tuple:
    pool = tuple(t for t in GENERIC_POOL if _compatible(shot, t))
    return pool or ("PLATE_PUSH",)  # PLATE_PUSH never needs headline/claim


# Wider than GENERIC_POOL: every template with no strict structural
# requirement (MAP_PIN/TIMELINE_DEEPTIME/SCALE_COMPARE all degrade to a
# generic default without their natural content, see each compiler's
# docstring) — repair passes may draw from this to satisfy >=5 distinct /
# <=35% share when the 3-member GENERIC_POOL alone can't (e.g. a run of
# shots with no headline at all excludes KINETIC_CLAIM, leaving only 2).
SAFE_POOL = ("PLATE_PUSH", "PARALLAX_25D", "KINETIC_CLAIM", "MAP_PIN",
            "TIMELINE_DEEPTIME", "SCALE_COMPARE")


def _safe_pool_for(shot: dict) -> tuple:
    pool = tuple(t for t in SAFE_POOL if _compatible(shot, t))
    return pool or ("PLATE_PUSH",)

# ----------------------------------------------------- content signals --

_COMPARE_RE = re.compile(
    r"(?i)\b(compared to|the size of|bigger than|smaller than|"
    r"larger than|as big as|as large as|times (?:the size|bigger|"
    r"larger|smaller)|vs\.?\b)")
_TIME_RE = re.compile(
    r"(?i)\b(million years?|billion years?|thousand years?|\d[\d,]*\s*"
    r"years? ago|centur(?:y|ies)|millenni(?:um|a)|\beons?\b|\beras?\b|"
    r"\bepochs?\b|ago\b)")
_PLACE_RE = re.compile(
    r"\b(?:in|near|at|across|beneath|above|over|from)\s+(?:the\s+)?"
    r"([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){0,2})\b")


def _content_signal(shot: dict, narration: str) -> str | None:
    """Heuristic only (presentation variety, not a factual claim) — unlike
    v15_plan's digit/word validation, a missed or over-eager signal here
    just picks a slightly different template, never wrong on-screen text."""
    if shot.get("number"):
        return "number"
    kind = shot.get("kind")
    if kind == "process":
        return "process"
    if kind == "zoom_through":
        return "scale"
    if _COMPARE_RE.search(narration):
        return "compare"
    if _TIME_RE.search(narration):
        return "time_span"
    m = _PLACE_RE.search(narration)
    if m and m.start() > 0:  # skip a sentence-initial capital (not a place)
        return "place"
    return None


SIGNAL_TEMPLATE = {spec.content_signal: name
                   for name, spec in TEMPLATE_LIBRARY.items()
                   if spec.content_signal}


def _hash_pick(key: str, options: tuple) -> str:
    """Deterministic choice among `options`, keyed by `key` (DESIGN §8.1:
    'ties are broken by hashing story_id, never by a random choice')."""
    idx = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)
    return options[idx]


# ------------------------------------------------------------- flatten --

def _flatten(plan: dict, story: dict) -> list:
    """-> [{"beat_id", "shot_idx", "shot", "narration", "duration"}], one
    entry per shot, in timeline order, with an approximate duration."""
    by_id = {b["beat_id"]: b for b in story.get("beats", [])}
    out = []
    for pb in plan.get("beats", []) if isinstance(plan, dict) else []:
        if not isinstance(pb, dict):
            continue
        bid = pb.get("beat_id")
        beat = by_id.get(bid)
        narration = beat["narration"] if beat else ""
        n_words = len(str(narration).split())
        shots = [sh for sh in (pb.get("shots") or []) if isinstance(sh, dict)]
        starts = [sh.get("start_word", 0) if isinstance(sh.get("start_word"), int)
                 else 0 for sh in shots]
        for si, sh in enumerate(shots):
            end = starts[si + 1] if si + 1 < len(shots) else n_words
            words = max(1, end - starts[si])
            out.append({"beat_id": bid, "shot_idx": si, "shot": sh,
                        "narration": narration, "template": sh.get("template"),
                        "duration": max(MIN_SHOT_S, words / WORDS_PER_SEC)})
    return out


def _write_back(plan: dict, items: list) -> None:
    """Writes each shot's assigned template name AND retargets its `kind`
    to that template's engine.v15_shots.compile_shot kind — without this,
    compile_shot would keep rendering v15_plan's original plate/
    zoom_through/process kind and the template assignment would be inert
    metadata. content_signal-selected templates (PROCESS_OVER_PLATE,
    ZOOM_THROUGH) only ever get assigned to a shot whose kind already
    matches (see _content_signal), so this is a no-op for those; it only
    actually changes `kind` for plate shots re-cast as one of the new
    single-plate templates (§8.1 "one plate can drive three templates")."""
    by_pos = {}
    for pb in plan.get("beats", []):
        for si, sh in enumerate(pb.get("shots") or []):
            by_pos[(pb.get("beat_id"), si)] = sh
    for it in items:
        target = by_pos.get((it["beat_id"], it["shot_idx"]))
        if target is not None:
            target["template"] = it["template"]
            spec = TEMPLATE_LIBRARY.get(it["template"])
            if spec is not None:
                target["kind"] = spec.shot_kind


# --------------------------------------------------------------- repair --

def _repair_no_repeats(items: list, story_id: str) -> None:
    n = len(items)
    for i in range(1, n):
        if items[i]["template"] != items[i - 1]["template"]:
            continue
        if i == n - 1:  # last is pinned to LOOP_BRIDGE by the caller
            continue
        nxt = items[i + 1]["template"] if i + 1 < n else None
        cands = tuple(t for t in _safe_pool_for(items[i]["shot"])
                      if t != items[i - 1]["template"] and t != nxt)
        if not cands:
            cands = tuple(t for t in TEMPLATE_LIBRARY
                          if t != items[i - 1]["template"] and t != nxt
                          and _compatible(items[i]["shot"], t)) \
                or tuple(t for t in TEMPLATE_LIBRARY
                        if _compatible(items[i]["shot"], t))
        items[i]["template"] = _hash_pick(f"{story_id}:norepeat:{i}", cands)


def _repair_min_distinct(items: list, story_id: str) -> None:
    if len(items) < MIN_DISTINCT:
        return  # physically impossible with fewer shots than templates
    used = {it["template"] for it in items}
    missing = [t for t in TEMPLATE_LIBRARY if t not in used]
    if not missing:
        return
    counts = Counter(it["template"] for it in items)
    # candidates: interior shots (never frame 0 / last) whose template has
    # more than one instance, most-duplicated first — swapping those loses
    # the least of any deliberate content-signal assignment.
    order = sorted(range(1, len(items) - 1),
                   key=lambda i: -counts[items[i]["template"]])
    for i in order:
        if not missing:
            break
        cur = items[i]["template"]
        if counts[cur] <= 1:
            continue
        cand = next((t for t in missing if _compatible(items[i]["shot"], t)), None)
        if cand is None:
            continue
        if items[i - 1]["template"] == cand or items[i + 1]["template"] == cand:
            continue
        counts[cur] -= 1
        items[i]["template"] = cand
        counts[cand] = counts.get(cand, 0) + 1
        missing = [t for t in TEMPLATE_LIBRARY
                  if t not in {it["template"] for it in items}]


def _repair_max_share(items: list, story_id: str) -> None:
    total = sum(it["duration"] for it in items)
    if total <= 0:
        return
    for _pass in range(10):
        by_t: dict = {}
        for it in items:
            by_t.setdefault(it["template"], []).append(it)
        over = [(t, sum(x["duration"] for x in xs) / total)
                for t, xs in by_t.items()]
        over = [(t, s) for t, s in over if s > MAX_SHARE]
        if not over:
            return
        t = max(over, key=lambda x: x[1])[0]
        cands = [it for it in by_t[t]
                 if 0 < items.index(it) < len(items) - 1]
        if not cands:
            return
        victim = min(cands, key=lambda it: it["duration"])
        i = items.index(victim)
        alt = tuple(c for c in _safe_pool_for(victim["shot"]) if c != t
                    and c != items[i - 1]["template"]
                    and c != items[i + 1]["template"])
        if not alt:
            return
        victim["template"] = _hash_pick(f"{story_id}:share:{i}", alt)


# ------------------------------------------------------------------ API --

def assign_templates(plan: dict, story: dict) -> dict:
    """-> {"plan": plan (mutated in place, each shot gets "template"),
    "templates_used": [...], "counts": {...}, "errors": [...]}."""
    items = _flatten(plan, story)
    story_id = story.get("story_id", "story")
    if not items:
        return {"plan": plan, "templates_used": [], "counts": {},
                "errors": ["plan has no shots"]}
    for it in items:
        sig = _content_signal(it["shot"], it["narration"])
        it["template"] = SIGNAL_TEMPLATE.get(sig) or _hash_pick(
            f"{story_id}:{it['beat_id']}:{it['shot_idx']}",
            _generic_pool_for(it["shot"]))
    # §8.1: frame 0 is HOOK_PLATE or KINETIC_CLAIM; the last shot is
    # LOOP_BRIDGE (skip the "last" pin for a single-shot plan — frame 0
    # wins, there is no meaningful "last shot" distinct from the hook).
    # v15_plan's real planner guarantees shot 0 has a headline (its own
    # validation: "the hook shot must be a plate with a headline"); a
    # synthetic/test plan may not, so KINETIC_CLAIM still needs the same
    # _compatible gate as everywhere else.
    hook_pool = tuple(t for t in ("HOOK_PLATE", "KINETIC_CLAIM")
                      if _compatible(items[0]["shot"], t)) or ("HOOK_PLATE",)
    items[0]["template"] = _hash_pick(f"{story_id}:hook", hook_pool)
    if len(items) > 1:
        items[-1]["template"] = "LOOP_BRIDGE"
    _repair_no_repeats(items, story_id)
    _repair_min_distinct(items, story_id)
    _repair_max_share(items, story_id)
    _write_back(plan, items)
    return {"plan": plan, "templates_used": sorted({it["template"] for it in items}),
            "counts": dict(Counter(it["template"] for it in items)),
            "errors": validate_templates(plan, story)}


def validate_templates(plan: dict, story: dict) -> list:
    """Pure-code rule tests (DESIGN §8.1 + WP7 acceptance): no repeats,
    >=5 distinct templates, <=35% screen-time share, frame0/last."""
    items = _flatten(plan, story)
    errs = []
    if not items:
        return ["plan has no shots"]
    seq = [it["template"] for it in items]
    for t in seq:
        if t not in TEMPLATE_LIBRARY:
            errs.append(f"unknown template {t!r}")
    for i in range(1, len(seq)):
        if seq[i] == seq[i - 1]:
            errs.append(f"template {seq[i]!r} repeats back-to-back at shot {i}")
    if len(items) >= MIN_DISTINCT and len(set(seq)) < MIN_DISTINCT:
        errs.append(f"only {len(set(seq))} distinct templates used "
                    f"(need >= {MIN_DISTINCT})")
    total = sum(it["duration"] for it in items) or 1.0
    by_t: dict = {}
    for it in items:
        by_t[it["template"]] = by_t.get(it["template"], 0.0) + it["duration"]
    for t, s in by_t.items():
        share = s / total
        if share > MAX_SHARE + 1e-6:
            errs.append(f"{t} takes {share:.0%} of screen time (> "
                        f"{MAX_SHARE:.0%})")
    if seq[0] not in ("HOOK_PLATE", "KINETIC_CLAIM"):
        errs.append(f"frame 0 template {seq[0]!r} must be HOOK_PLATE or "
                    f"KINETIC_CLAIM")
    if len(items) > 1 and seq[-1] != "LOOP_BRIDGE":
        errs.append(f"last shot template {seq[-1]!r} must be LOOP_BRIDGE")
    return errs


def median_shot_s(plan: dict, story: dict) -> float:
    durs = sorted(it["duration"] for it in _flatten(plan, story))
    n = len(durs)
    if not n:
        return 0.0
    return durs[n // 2] if n % 2 else (durs[n // 2 - 1] + durs[n // 2]) / 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.v16_plan")
    ap.add_argument("story_dir")
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args(argv)
    from engine.v15_plan import make_plan
    from engine.v15_style import load_style
    sd = Path(a.story_dir)
    story = json.loads((sd / "story.json").read_text())
    bible = load_style(sd, story)
    plan_res = make_plan(story, bible, use_llm=not a.no_llm)
    res = assign_templates(plan_res["plan"], story)
    print(json.dumps({"templates_used": res["templates_used"],
                      "counts": res["counts"], "errors": res["errors"],
                      "median_shot_s": median_shot_s(res["plan"], story)},
                     indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
