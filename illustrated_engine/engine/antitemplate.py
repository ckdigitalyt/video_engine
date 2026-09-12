"""V7 P0-10 — Anti-Template structural signatures.

Rolling structural fingerprint of recent videos.  The planner reads the last
N signatures and must DELIBERATELY vary structure (story determines it —
never random variation).  Brand constants (typography, palette, audio) are
not part of the signature; storytelling structure is.

Signature file: editorial_signatures/<story_id>.json
"""

from __future__ import annotations

import ast
import json
import time
from pathlib import Path

SIG_DIR = Path(__file__).resolve().parent.parent / "editorial_signatures"

# Fields compared for diversity.  Sequences use Jaccard distance on
# consecutive-pair shingles; ratios use max-abs delta.
SEQ_FIELDS = ("role_sequence", "class_sequence", "mode_sequence")
RATIO_FIELDS = ("blur_ratio", "diagram_ratio", "cinematic_ratio",
                "avg_shot_dur", "opening_class", "title_behavior")


def build_signature(plan: dict, classes: list) -> dict:
    shots = plan.get("shots", [])
    dur = sum(float(s.get("duration_s") or 0) for s in shots) or 1.0
    blur_d = sum(float(s.get("duration_s") or 0) for s, c in zip(shots, classes)
                 if c["is_generic_blur"])
    diag_d = sum(float(s.get("duration_s") or 0) for s, c in zip(shots, classes)
                 if c["is_evidence"])
    cin_d = sum(float(s.get("duration_s") or 0) for s, c in zip(shots, classes)
                if c["is_cinematic"])
    openings = [s for s in shots if s.get("opening")]
    title_behavior = "opening_only" if not openings else (
        "none" if not str(openings[0].get("title") or "").strip() else "opening_title")
    return {
        "story_id": plan.get("story_id", "unknown"),
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_shots": len(shots),
        "avg_shot_dur": round(dur / max(len(shots), 1), 2),
        "opening_class": classes[0]["primary"] if classes else None,
        "opening_structure": [shots[0].get("shot_type"), shots[0].get("visual_mode")] if shots else [],
        "role_sequence": [s.get("role") for s in shots],
        "class_sequence": [c["primary"] for c in classes],
        "mode_sequence": [s.get("visual_mode") for s in shots],
        "transition_pattern": [s.get("transition_in") for s in shots],
        "title_behavior": title_behavior,
        "blur_ratio": round(blur_d / dur, 3),
        "diagram_ratio": round(diag_d / dur, 3),
        "cinematic_ratio": round(cin_d / dur, 3),
    }


def _shingles(seq, n=2):
    return {"\u0001".join(map(str, seq[i:i + n])) for i in range(max(len(seq) - n + 1, 1))}


def _seq_distance(a, b) -> float:
    sa, sb = _shingles(a), _shingles(b)
    if not sa and not sb:
        return 0.0
    union = sa | sb
    return 1.0 - len(sa & sb) / len(union) if union else 0.0


def compare(sig: dict, recent: list) -> dict:
    """Diversity report of `sig` vs recent signatures (most recent first)."""
    if not recent:
        return {"vs": [], "mean_seq_distance": None, "min_seq_distance": None,
                "ratio_max_delta": {}, "verdict": "no_history",
                "note": "first V7 video — baseline signature recorded"}
    dists, ratios = [], {}
    for r in recent:
        d_list = [_seq_distance(sig.get(f, []), r.get(f, [])) for f in SEQ_FIELDS]
        dists.append(sum(d_list) / len(d_list))
        for f in ("blur_ratio", "diagram_ratio", "cinematic_ratio", "avg_shot_dur"):
            d = abs(float(sig.get(f, 0)) - float(r.get(f, 0)))
            ratios[f] = max(ratios.get(f, 0.0), round(d, 3))
        if sig.get("opening_class") != r.get("opening_class"):
            ratios["opening_class"] = 1.0
        if sig.get("title_behavior") != r.get("title_behavior"):
            ratios["title_behavior"] = 1.0
    mean_d = round(sum(dists) / len(dists), 3)
    min_d = round(min(dists), 3)
    # A new video must not be a structural clone of the closest recent video.
    if min_d >= 0.45 or ratios.get("opening_class") == 1.0:
        verdict = "diverse"
    elif min_d >= 0.25:
        verdict = "acceptable"
    else:
        verdict = "template_clone"
    return {"vs": [r.get("story_id") for r in recent],
            "mean_seq_distance": mean_d, "min_seq_distance": min_d,
            "ratio_max_delta": ratios, "verdict": verdict}


def save(sig: dict) -> Path:
    SIG_DIR.mkdir(parents=True, exist_ok=True)
    p = SIG_DIR / f"{sig['story_id']}.json"
    p.write_text(json.dumps(sig, indent=1))
    return p


def load_recent(exclude_story: str = None, n: int = 5) -> list:
    """Most recent N signatures, oldest last, excluding `exclude_story`."""
    if not SIG_DIR.exists():
        return []
    sigs = []
    for p in sorted(SIG_DIR.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
        try:
            s = json.loads(p.read_text())
        except Exception:
            continue
        if exclude_story and s.get("story_id") == exclude_story:
            continue
        sigs.append(s)
        if len(sigs) >= n:
            break
    return sigs


# ------------------------------------------------------------------ V11 P1 §3 / P2
# Cross-topic MOTIF fingerprint.  The orange-circle / navy-strip / cream-panel
# combination became a V10 visual fingerprint.  BRAND stays (palette,
# typography, compositing quality); the decorative GEOMETRIC VOCABULARY must
# vary by topic and never recur across unrelated topics unless the plan
# declares a semantic justification (story-level `motif_justification`).
#
# Fingerprint = primitive-family × palette-role counts from two sources:
#   - plate authoring: AST scan of the story's make_cards.py (ellipse /
#     rectangle / rounded_rectangle / polygon calls + the colour constant in
#     their fill= kwarg)
#   - plan-drawn primitives: overlay/living event kinds mapped to families
# Variation must come from story/subject/mechanism/grammar/information
# structure — layout randomization is explicitly NOT done (P2).

_PLATE_FAMILIES = {"ellipse": "circle", "rectangle": "strip",
                   "rounded_rectangle": "panel", "polygon": "polygon"}
_PLAN_FAMILIES = {"highlight": "circle", "flow": "circle",
                  "consequence": "circle", "fill_state": "strip",
                  "frame_reveal": "panel", "frame_isolate": "panel",
                  "stage_overlay": "panel", "number_pop": "panel"}
_ROLE_WORDS = {
    "accent": ("rust", "accent", "red", "orange"),
    "dark": ("navy", "ink", "dark", "grey", "gray"),
    "light": ("cream", "highlight", "light", "white"),
    "parchment": ("parch",),
}


def _role_of(color_name: str) -> str:
    n = color_name.lower()
    for role, words in _ROLE_WORDS.items():
        if any(w in n for w in words):
            return role
    return "other"


def _scan_make_cards(path: Path) -> dict:
    """{family_role: count} from the story's plate authoring source."""
    if not path.exists():
        return {}
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return {}
    counts: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        attr = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else "")
        family = _PLATE_FAMILIES.get(attr)
        if not family:
            continue
        role = "other"
        for kw in node.keywords:
            if kw.arg == "fill":
                v = kw.value
                name = v.id if isinstance(v, ast.Name) else (
                    v.attr if isinstance(v, ast.Attribute) else "")
                role = _role_of(str(name))
                break
        counts[f"{family}_{role}"] = counts.get(f"{family}_{role}", 0) + 1
    return counts


def motif_signature(story_dir: Path, plan: dict, story: dict) -> dict:
    """Motif fingerprint of one story (plate + plan primitives)."""
    plate = _scan_make_cards(Path(story_dir) / "make_cards.py")
    planv: dict = {}
    for s in plan.get("shots", []):
        for e in s.get("events") or []:
            fam = _PLAN_FAMILIES.get(str((e or {}).get("kind") or ""))
            if fam:
                planv[f"{fam}_plan"] = planv.get(f"{fam}_plan", 0) + 1
    return {
        "plate": plate,
        "plan": planv,
        "subject": str(story.get("subject") or ""),
        "story_type": str(story.get("story_type") or ""),
        "justification": str(story.get("motif_justification") or "").strip(),
    }


def _motif_vec(m: dict) -> dict:
    v = {k: float(n) for k, n in (m.get("plate") or {}).items()}
    for k, n in (m.get("plan") or {}).items():
        v[k] = v.get(k, 0.0) + float(n)
    return v


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0.0) for k in a)
    na = sum(x * x for x in a.values()) ** 0.5
    nb = sum(x * x for x in b.values()) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def compare_motifs(sig: dict, recent: list) -> dict:
    """Cross-topic motif recurrence check vs recent signatures.

    Recurrence only means something across UNRELATED topics: same-subject
    signatures are skipped.  A close motif mix on a different subject is a
    recurrence unless the story declares a semantic justification.
    """
    mine = sig.get("motif") or {}
    if not mine:
        return {"verdict": "no_motif_data"}
    my_subject = str(mine.get("subject") or "")
    my_vec = _motif_vec(mine)
    best, best_id = 0.0, None
    for r in recent:
        rm = r.get("motif") or {}
        if not rm:
            continue
        if str(rm.get("subject") or "") == my_subject and my_subject:
            continue  # same topic may share vocabulary
        sim = _cosine(my_vec, _motif_vec(rm))
        if sim > best:
            best, best_id = sim, r.get("story_id")
    out = {"closest": best_id, "similarity": round(best, 3),
           "motif_mix": {k: int(n) for k, n in sorted(my_vec.items())}}
    if not best_id:
        out["verdict"] = "no_comparable_history"
    elif mine.get("justification"):
        out["verdict"] = "justified_recurrence"
        out["justification"] = mine["justification"]
    elif best >= 0.65:
        out["verdict"] = "motif_recurrence"
    else:
        out["verdict"] = "varied"
    return out
