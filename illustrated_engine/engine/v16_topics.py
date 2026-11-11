"""V16 -- topic engine: clusters, ideation, dedupe, scoring, series planner
(DESIGN.md Sec.9, WP11).

    ideate(n, ask=None)          -> raw candidates, one `topic_ideate` call
    dedupe(candidates, history)  -> (unique, duplicates) vs `data/topic_history.jsonl`
    score_candidates(cands, ask) -> candidates + score/score_breakdown, one `topic_score` call
    plan_series(candidates)      -> groups sharing a `series_id` into 2-3 part series
    build_queue(...)             -> orchestrates all of the above -> ranked queue

Two LLM calls per batch (DESIGN Sec.2.5 budget: "about 2 per batch for
topics"). Dedupe and scoring math are pure code, stdlib only -- DESIGN
Sec.9.2: "This uses the stdlib only. No embedding dependency is justified
yet."
"""
from __future__ import annotations

import csv
import json
import math
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from llm import client as llm  # noqa: E402
from llm.prompts import render  # noqa: E402

DEFAULT_HISTORY_PATH = REPO / "data" / "topic_history.jsonl"
CHANNEL_CSV = REPO / "research" / "phase2" / "channel_videos.csv"
STORIES_DIR = REPO / "illustrated_engine" / "stories"

# ------------------------------------------------------------- clusters --

# 2026-10-24 analytics review (28-day YouTube Analytics joined to each
# upload's topic_history cluster, ~15 videos with real data): the DESIGN
# Sec.9.1 priors were set from the OLD channel's view counts and ranked
# deep_time first. Real retention of the V16 uploads says otherwise --
# median averageViewPercentage per cluster: spectacle_physics ~77% (sound
# levitation 72%, magnet frog 82%; 16 of the window's 21 subscribers came
# from one of them), deep_time ~65%, space_discovery ~60%,
# exotic_space_travel ~57% (its one strong video, "pilots train to black
# out", is a human-body topic, not space travel), general_explainer 44%.
# Yet the last 60 queued topics were 24 deep_time / 22 space_discovery /
# 8 spectacle_physics. Priors now follow retention (x25 points each, see
# score_candidate); CLUSTER_TARGET_SHARE below then shapes the queue order.
CLUSTER_PRIORS = {
    "spectacle_physics": 1.00,
    "deep_time": 0.80,
    "exotic_space_travel": 0.50,
    "space_discovery": 0.50,
    "general_explainer": 0.20,
}
# What each cluster means, shown to the ideation prompt. "spectacle_physics"
# is the channel's human-scale physics / human-body cluster: the pilots/g-force
# video was tagged exotic_space_travel only because a centrifuge "trains
# astronauts" -- the description routes such topics here instead.
CLUSTER_DESCRIPTIONS = {
    "spectacle_physics": "human-scale physics and the human body: one striking thing you "
                         "could see or feel at human scale (an object or animal floating in "
                         "midair, a magnet doing the impossible, sound or pressure moving "
                         "things, what g-force, cold or pressure does to a body)",
    "deep_time": "Earth's deep past: extinctions, fossils, early Earth, rocks that record history",
    "exotic_space_travel": "hypothetical spacecraft, propulsion and far-future travel (honest framing)",
    "space_discovery": "a specific astronomical discovery: a planet, star, moon or galaxy",
    "general_explainer": "an everyday-science explainer that fits none of the above",
}
# Target share of the ranked queue (rank_by_share). The review's retention
# split asks for ~40% human-scale physics and caps the two space-heavy /
# deep-time clusters near 25% each. Clusters missing here (general_explainer)
# get 0: they only fill slots once every targeted cluster is exhausted.
CLUSTER_TARGET_SHARE = {
    "spectacle_physics": 0.40,
    "deep_time": 0.25,
    "space_discovery": 0.25,
    "exotic_space_travel": 0.10,
}
EXCLUDED_CLUSTERS = {"quiz", "crypto", "ai_policy", "asmr"}   # dilute the channel's topical signal

# Auto-weight override layer (2026-11-09). CLUSTER_PRIORS and
# CLUSTER_TARGET_SHARE above stay the hand-set baseline. engine.v16_autoweight
# (run by engine.v16_feedback after it writes real_* analytics onto
# topic_history) writes small, sample-size-shrunk adjustments to
# data/cluster_weight_state.json. score_candidate, rank_by_share and
# clusters_prompt_block read the effective values through cluster_priors() /
# cluster_target_share(), which re-validate the file on every read:
#   - only clusters already in the baseline count. The file can never add a
#     cluster, and a cluster with no target share (general_explainer) stays at 0;
#   - every value is clamped to AUTOWEIGHT_BAND x its baseline, so no prior or
#     share can reach 0. Lesson of 28955f3: an automatically computed weight
#     must never turn into a hard gate;
#   - if the file was computed against different baseline constants (a human
#     re-baselined the dicts above), it is ignored. The human edit wins until
#     the next autoweight run re-anchors on the new baseline;
#   - a missing, unreadable or malformed file, or V16_CLUSTER_WEIGHT_STATE=off,
#     means the baseline is used unchanged.
CLUSTER_WEIGHT_STATE_PATH = REPO / "data" / "cluster_weight_state.json"
WEIGHT_STATE_ENV = "V16_CLUSTER_WEIGHT_STATE"     # alternate path, or "off" to disable
AUTOWEIGHT_BAND = (0.7, 1.3)                       # lifetime bound, x the hand-set baseline

# Scale/comparison angle (2026-10-27): an angle that cuts across clusters,
# not a new cluster.
#
# Evidence: an external study of 18 competitor channels (756 Shorts) found
# that topics framed around size, depth or distance, or as a direct "X vs Y"
# comparison ("We Are So TINY", "How Deep Does The Ocean Really Go", "Great
# Pyramid vs Olympus Mons"), beat their own channel's baseline x1.63 on views
# (p=0.009, n=51 across 14 channels). The effect held in 5 of the 7 closest
# space/science analogs. Title wording (curiosity gap, question form,
# numbers, caps) had no effect.
#
# Why not a new cluster: the angle applies to space ("rings 200x wider than
# Saturn's"), deep time ("first horses were smaller than a dog") and
# human-scale physics alike. A cluster would also take a slot from the
# retention-based CLUSTER_PRIORS / CLUSTER_TARGET_SHARE (685a2d2), and the
# topic_ideate schema enum, and the cluster-keyed analytics join on
# topic_history.
#
# How it works: code detects the angle from the candidate's title + claim
# (deterministic, so an LLM self-tag cannot inflate it). score_candidate
# then adds SCALE_COMPARISON_BONUS points, the same size as the evergreen
# bonus. That lifts a scale framing within its cluster and over MIN_SCORE
# at the margin. It leaves the cluster share and the still-image floor
# alone. topic_ideate v3 asks for the framing explicitly.
SCALE_COMPARISON_BONUS = 5.0
_SCALE_DIM = (r"(?:big|bigger|large|larger|small|smaller|tall|taller|deep|deeper|wide|wider|"
              r"heavy|heavier|far|farther|further|long|longer|tiny|tinier|huge|vast|thick|"
              r"thicker)")
SCALE_COMPARISON_RE = re.compile(
    r"\bvs\.?\s|\bversus\b|\bcompared\s+(?:to|with)\b"
    r"|\b(?:bigger|larger|smaller|taller|deeper|wider|heavier|farther|further|longer|tinier|"
    r"thicker)\s+than\b"
    r"|\bsize\s+of\s+(?:a|an|the|\d)"
    r"|\bas\s+" + _SCALE_DIM + r"\s+as\b"
    r"|\btimes\s+(?:the\s+size|bigger|larger|smaller|taller|deeper|wider|heavier|farther|"
    r"longer|thicker)\b"
    r"|\bhow\s+(?:deep|big|tall|far|small|tiny|large|long|heavy|wide|vast|huge)\b"
    r"|\bso\s+(?:tiny|small|big|huge|deep|vast)\b"
    r"|\bif\s+(?:the\s+|a\s+|an\s+)?[a-z' -]{2,30}\s+were\s+(?:the\s+size|as\s+"
    + _SCALE_DIM + r"|shrunk|scaled)"
    r"|\bfits?\s+(?:inside|between|into)\b"
    r"|\bto\s+scale\b",
    re.I)

MIN_SCORE = 65
SERIES_PARTS = (2, 3)
DUP_ENTITY_JACCARD = 0.5
DUP_CLAIM_OVERLAP = 0.6

# ---------------------------------------------------------- tokenizing --

_STOPWORDS = frozenset("""
a an the of on in at to for with and or is are was were be been being it its it's
this that these those from by as into over under near very more most than then
when while during about across between why how what which who whose where will
can could would should may might did do does not no yes you your yours our their
his her new part video short watch finally just still really actually
""".split())
_WORD = re.compile(r"[a-zA-Z][a-zA-Z'-]{2,}")


def key_terms(text: str) -> set:
    """Lowercase significant words. The stdlib stand-in DESIGN Sec.9.2 calls
    for instead of an entity-extraction model."""
    return {w.lower() for w in _WORD.findall(str(text or "")) if w.lower() not in _STOPWORDS}


def slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(title or "").lower()).strip("_")
    return f"t_{s[:40]}" or "t_topic"


def _unique_id(base: str, seen: set) -> str:
    cid, i = base, 2
    while cid in seen:
        cid = f"{base}_{i}"
        i += 1
    return cid


# -------------------------------------------------------------- dedupe --

def entity_set(candidate: dict) -> set:
    """Candidate's key-entity set (DESIGN Sec.9.2: subject/place/era/phenomenon),
    falling back to the title's own key terms when no structured entities are given."""
    ents = candidate.get("entities")
    out = set()
    if isinstance(ents, dict):
        for v in ents.values():
            if v:
                out |= key_terms(v)
    elif isinstance(ents, (list, tuple, set)):
        for v in ents:
            out |= key_terms(v)
    return out or key_terms(candidate.get("title", ""))


def claim_tokens(candidate: dict) -> set:
    return key_terms(candidate.get("claim") or candidate.get("title") or "")


# ------------------------------------------------- similarity normalizing --
#
# 2026-11-11 review (108 batches): plain token Jaccard missed near-identical
# subjects worded differently -- "fulgurite" was PUBLISHED TWICE
# (JR53-E2EOio 2026-11-05, yvjF7jSO8b4 2026-11-09): the second candidate's
# entities {fulgurite, lightning-fused, sand} vs the published {fulgurite,
# fused, glass, sand} scored 2/5 = 0.40 < 0.5 because "fused" !=
# "lightning-fused"; "fossil"/"fossilized"/"fossils" and "raindrop"/
# "raindrops" never matched either. Comparison now runs on normalized
# terms: hyphen/apostrophe-split, light hand-rolled stemming (no NLP
# dependency is installed, DESIGN Sec.9.2 stays stdlib-only), and generic
# deep-time filler ("ancient", "years", "billion") dropped so it can't
# dilute the subject overlap. Stored history rows keep their raw
# entities/claim_tokens; both sides are normalized at compare time.

_STEM_RULES = (
    # longest first; (suffix, replacement)
    ("ifications", "if"), ("ification", "if"), ("ified", "if"), ("ifies", "if"),
    ("ifying", "if"), ("ify", "if"),
    ("izations", ""), ("isations", ""), ("ization", ""), ("isation", ""),
    ("izing", ""), ("ising", ""), ("ized", ""), ("ised", ""), ("izes", ""), ("ize", ""),
    ("ies", "y"), ("ied", "y"),
    ("ing", ""), ("ed", ""),
)
_GENERIC_TERMS = frozenset("""
ancient deep time era eon epoch period age year ago billion million thousand hundred
earth early old record preserve today modern scientist astronomer found discover show
reveal turn make form exist still once
""".split())


def stem_term(word: str) -> str:
    """Light suffix-stripping stemmer (plural/tense/derivation variants only):
    fossils/fossilized/fossilization -> fossil, petrified/petrification ->
    petrif, raindrops -> raindrop, galaxies -> galaxy, fused/fuse -> fus.
    Deterministic and only ever applied to BOTH sides of a comparison, so
    an imperfect stem (striking -> strik) still matches its own variants."""
    w = str(word or "").lower().strip("'")
    if w.endswith("'s"):
        w = w[:-2]
    for suf, rep in _STEM_RULES:
        if w.endswith(suf) and len(w) - len(suf) + len(rep) >= 3:
            w = w[: -len(suf)] + rep
            if suf in ("ing", "ed") and len(w) >= 4 and w[-1] == w[-2] and w[-1] not in "lsz":
                w = w[:-1]                                   # stopped -> stop
            break
    else:
        if w.endswith(("sses", "xes", "zes", "ches", "shes")) and len(w) > 5:
            w = w[:-2]                                       # glasses -> glass
        elif w.endswith("s") and not w.endswith(("ss", "us", "is")) and len(w) > 3:
            w = w[:-1]                                       # raindrops -> raindrop
    if w.endswith("e") and len(w) >= 4:
        w = w[:-1]                                           # fuse -> fus (= fused)
    return w


def norm_terms(tokens, *, drop_generic: bool = True) -> set:
    """Raw key terms (stored entities / claim_tokens, or key_terms output)
    -> the normalized set the dedupe comparison runs on. Falls back to the
    unfiltered stems when every term is generic, so a row is never emptied."""
    stems = set()
    for t in tokens or ():
        for part in re.split(r"[-'\s/]+", str(t).lower()):
            if len(part) >= 3 and part not in _STOPWORDS:
                s = stem_term(part)
                if len(s) >= 3:
                    stems.add(s)
    if not drop_generic:
        return stems
    specific = {s for s in stems if s not in _GENERIC_STEMS}
    return specific or stems


_GENERIC_STEMS = frozenset(stem_term(w) for w in _GENERIC_TERMS)


def entity_jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def claim_overlap(a: set, b: set) -> float:
    """Containment, not Jaccard: a short claim fully contained in a longer one
    is still the same story even though their union is large."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_duplicate(candidate: dict, history_row: dict) -> str | None:
    """-> a reason string if `candidate` duplicates `history_row`, else None.
    A shared `series_id` is the DESIGN Sec.9.2 exception for a planned series part.
    Pure comparator: WHICH history rows may block is decided by dedupe()."""
    if candidate.get("series_id") and candidate["series_id"] == history_row.get("series_id"):
        return None
    ea = norm_terms(entity_set(candidate))
    eb = norm_terms(history_row.get("entities") or ())
    ej = entity_jaccard(ea, eb)
    # one shared term out of two ({rock} vs {rock, missing}) is a broad
    # subject word, not the same story: >=2 shared terms, or identical sets
    if ej >= DUP_ENTITY_JACCARD and (len(ea & eb) >= 2 or ea == eb):
        return (f"entity overlap {ej:.2f} >= {DUP_ENTITY_JACCARD} with "
                f"{history_row.get('id') or history_row.get('title')!r}")
    a = norm_terms(claim_tokens(candidate))
    b = norm_terms(history_row.get("claim_tokens") or ())
    co = claim_overlap(a, b)
    # Containment on a 2-3 term claim is noise once terms are stemmed
    # (seed row "How Galaxies form - finally Revealed" -> {galaxy, form,
    # reveal} would contain every "galaxy formed..." claim), so the claim
    # rule also needs DUP_CLAIM_MIN_SHARED terms in common.
    if co >= DUP_CLAIM_OVERLAP and len(a & b) >= DUP_CLAIM_MIN_SHARED:
        return (f"claim overlap {co:.2f} >= {DUP_CLAIM_OVERLAP} with "
                f"{history_row.get('id') or history_row.get('title')!r}")
    return None


# ------------------------------------------------- which rows may block --
#
# 2026-11-11 review: of 920 duplicate matches in recent cycles, 872 were
# against rows that were only ever "queued" (then HELD at research/script
# and never rendered) and only 24 against published videos. Duplicate
# rows also blocked (a copy of a copy), as did "rejected" rows. Ideation's
# ~18 raw candidates/cycle lost ~16 (89%) to dedupe, leaving ~1.56 queued
# per cycle instead of the 3 per slot materialize_candidates assumes.
# Now only these rows block a new candidate:
#   - a real published outcome, any age: status "published" (channel/V15
#     seeds, and v16_batch's PASS record_published rows), a `real_video_id`
#     (v16_feedback matched an upload to it), or an id in `published_ids`
#     (PASS rows of build/v16/batches/*/batch_report.json);
#   - a "queued" row from the last RECENT_QUEUED_BLOCK_DAYS (in flight, or
#     just tried), by its `ts`, or for legacy rows written before `ts`
#     existed, its id appearing in a recent batch's topics_queued.json.
# Older held/queued, rejected and duplicate rows no longer block forever.
RECENT_QUEUED_BLOCK_DAYS = 3.0
PUBLISHED_STATUSES = frozenset({"published"})
DUP_CLAIM_MIN_SHARED = 3
BATCHES_DIR = REPO / "illustrated_engine" / "build" / "v16" / "batches"


def _now() -> float:
    import time
    return time.time()


def _row_epoch(row: dict):
    ts = row.get("ts")
    if not ts:
        return None
    import datetime as _dt
    try:
        d = _dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)
    return d.timestamp()


def is_published_row(row: dict, published_ids=()) -> bool:
    return (row.get("status") in PUBLISHED_STATUSES or bool(row.get("real_video_id"))
            or (row.get("id") in published_ids if published_ids else False))


def is_blocking_row(row: dict, *, now: float | None = None, recent_queued_ids=(),
                    published_ids=(), recent_days: float = RECENT_QUEUED_BLOCK_DAYS) -> bool:
    """True when `row` may block a new candidate (see the block comment above).
    A row with no `status` at all (a hand-built row, not a topic_history
    line) is treated as blocking, the conservative pre-2026-11-11 behaviour."""
    if "status" not in row:
        return True
    if is_published_row(row, published_ids):
        return True
    if row.get("status") != "queued":
        return False
    epoch = _row_epoch(row)
    if epoch is not None:
        return ((now if now is not None else _now()) - epoch) <= recent_days * 86400
    return row.get("id") in recent_queued_ids


def blocking_rows(history: list, **kw) -> list:
    return [h for h in history if is_blocking_row(h, **kw)]


def _story_topic_id(story_name: str):
    try:
        return json.loads((STORIES_DIR / Path(str(story_name)).name / "story.json")
                          .read_text()).get("topic_id")
    except (OSError, ValueError):
        return None


def batch_outcome_ids(batches_dir: Path = BATCHES_DIR, *, now: float | None = None,
                      recent_days: float = RECENT_QUEUED_BLOCK_DAYS) -> tuple:
    """-> (published_ids, recent_queued_ids) read from batch work dirs:
    PASS rows of every batch_report.json (-> story.json topic_id), and
    every topic id in a topics_queued.json written in the last
    `recent_days`. Never raises; a missing dir gives two empty sets."""
    published, recent = set(), set()
    now = now if now is not None else _now()
    try:
        dirs = [d for d in Path(batches_dir).iterdir() if d.is_dir()]
    except OSError:
        return published, recent
    for d in dirs:
        try:
            rep = json.loads((d / "batch_report.json").read_text())
            for r in rep.get("rows") or []:
                if r.get("verdict") == "PASS" and r.get("story"):
                    tid = _story_topic_id(r["story"])
                    if tid:
                        published.add(tid)
        except (OSError, ValueError, AttributeError):
            pass
        tq = d / "topics_queued.json"
        try:
            if now - tq.stat().st_mtime <= recent_days * 86400:
                sel = json.loads(tq.read_text())
                for e in (sel.get("queue") or []) + (sel.get("picked") or []):
                    for p in (e.get("parts") if isinstance(e, dict) and "parts" in e else [e]):
                        if isinstance(p, dict) and p.get("id"):
                            recent.add(p["id"])
        except (OSError, ValueError, AttributeError):
            pass
    return published, recent


def dedupe(candidates: list, history: list, *, now: float | None = None,
           recent_queued_ids=(), published_ids=()) -> tuple:
    """-> (unique, duplicates). Duplicates carry a `duplicate_reason`.
    Only blocking rows (is_blocking_row) are compared against."""
    blockers = blocking_rows(history, now=now, recent_queued_ids=set(recent_queued_ids),
                             published_ids=set(published_ids))
    unique, dupes = [], []
    for c in candidates:
        reason = next((r for h in blockers if (r := is_duplicate(c, h))), None)
        (dupes if reason else unique).append({**c, "duplicate_reason": reason} if reason else c)
    return unique, dupes


AVOID_TITLES_MAX = 80


def avoid_titles_for_prompt(history: list, *, published_ids=(), now: float | None = None,
                            recent_queued_ids=(), limit: int = AVOID_TITLES_MAX) -> list:
    """The ideation prompt's "don't repeat" list. 2026-11-11 review: it was
    the last 50 rows by insertion order, 44/50 of them duplicate-status
    rows -- nearly useless. Now: every published topic first (newest
    first, real_title too when the upload title differs), then recently
    queued in-flight topics, de-duplicated, capped at `limit`."""
    out, seen = [], set()

    def add(t):
        k = " ".join(sorted(norm_terms(key_terms(t), drop_generic=False)))
        if t and k not in seen:
            seen.add(k)
            out.append(t)

    pub = [h for h in history if is_published_row(h, published_ids)]
    # V16 uploads (newest last in the file) before the old channel/V15 seeds
    v16 = [h for h in pub if h.get("source") not in ("channel_csv", "v15_story")]
    seeds = [h for h in pub if h.get("source") in ("channel_csv", "v15_story")]
    for h in reversed(v16):
        add(h.get("title"))
    for h in reversed(history):
        if (h.get("status") == "queued" and not is_published_row(h, published_ids)
                and is_blocking_row(h, now=now, recent_queued_ids=recent_queued_ids)):
            add(h.get("title"))
    for h in reversed(seeds):
        add(h.get("title"))
    return out[:limit]


# ------------------------------------------------ auto-weight override --

_weight_state_cache: dict = {}
_weight_state_warned: set = set()


def _warn_once(msg: str) -> None:
    if msg not in _weight_state_warned:
        _weight_state_warned.add(msg)
        print(f"[v16_topics] {msg}", file=sys.stderr, flush=True)


def weight_state_path():
    """-> the override file to read, or None when disabled by env."""
    env = os.environ.get(WEIGHT_STATE_ENV, "").strip()
    if env.lower() in ("off", "0", "none", "false", "disabled"):
        return None
    return Path(env) if env else CLUSTER_WEIGHT_STATE_PATH


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _same_base(recorded, base: dict) -> bool:
    return (isinstance(recorded, dict) and set(recorded) == set(base)
            and all(_finite(recorded[k]) and abs(recorded[k] - base[k]) < 1e-9 for k in base))


def band_clamp(value: float, base: float) -> float:
    lo, hi = AUTOWEIGHT_BAND
    return min(max(value, base * lo), base * hi)


def normalize_shares(raw: dict, base: dict, iters: int = 20) -> dict:
    """Clamp each share to AUTOWEIGHT_BAND x its baseline, then renormalize
    so the shares sum to 1. Repeats clamp-and-renormalize until both hold,
    because renormalizing can push a value back past its band. Clusters with
    a zero baseline share stay 0."""
    out = {c: band_clamp(float(raw.get(c, b)), b) for c, b in base.items() if b > 0}
    for _ in range(iters):
        total = sum(out.values())
        if total <= 0:
            return {c: b for c, b in base.items() if b > 0}
        out = {c: v / total for c, v in out.items()}
        clamped = {c: band_clamp(v, base[c]) for c, v in out.items()}
        if all(abs(clamped[c] - out[c]) < 1e-12 for c in out):
            break
        out = clamped
    return out


def load_weight_state() -> dict | None:
    """The validated override state, or None (-> baseline). Cached on the
    file's (mtime, size, inode), so the per-candidate score_candidate calls
    cost one stat each, and a rewrite by a concurrent autoweight run (atomic
    os.replace) is picked up on the next call."""
    path = weight_state_path()
    if path is None:
        return None
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size, st.st_ino)
    if key in _weight_state_cache:
        return _weight_state_cache[key]
    state = None
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
        if not (_same_base(data.get("base_priors"), CLUSTER_PRIORS)
                and _same_base(data.get("base_shares"), CLUSTER_TARGET_SHARE)):
            _warn_once(f"{path.name} was computed against different CLUSTER_PRIORS/"
                       "CLUSTER_TARGET_SHARE baselines; ignoring it (re-run engine.v16_autoweight)")
        else:
            state = data
    except (OSError, ValueError) as e:
        _warn_once(f"{path} unreadable ({e}); using hand-set cluster weights")
    _weight_state_cache.clear()
    _weight_state_cache[key] = state
    return state


def cluster_priors() -> dict:
    """Effective cluster -> prior: CLUSTER_PRIORS overlaid with the validated,
    band-clamped auto-weight state. Same keys as CLUSTER_PRIORS, always."""
    state = load_weight_state()
    over = (state or {}).get("priors")
    over = over if isinstance(over, dict) else {}
    return {c: band_clamp(float(over[c]), b) if _finite(over.get(c)) else b
            for c, b in CLUSTER_PRIORS.items()}


def cluster_target_share() -> dict:
    """Effective cluster -> target queue share (sums to 1). Same targeted
    clusters as CLUSTER_TARGET_SHARE, each within AUTOWEIGHT_BAND x baseline."""
    state = load_weight_state()
    over = (state or {}).get("shares")
    if not isinstance(over, dict):
        return dict(CLUSTER_TARGET_SHARE)
    raw = {c: (float(over[c]) if _finite(over.get(c)) else b)
           for c, b in CLUSTER_TARGET_SHARE.items()}
    return normalize_shares(raw, CLUSTER_TARGET_SHARE)


# ---------------------------------------------------------------- score --

_RUBRIC_FIELDS = ("cluster_prior", "counter_intuitive", "visualisability",
                  "hook_strength", "series_potential", "evidence_strength",
                  "evergreen", "still_image_fit", "scale_comparison")
# decision #13 item 4: a topic whose core payoff only reads correctly IN
# MOTION (a dynamic physical process/mechanism) can't be carried by this
# channel's still-image template library, no matter how good the idea is —
# score_row["still_image_fit"] at or below this is hard-skipped, the same
# way EXCLUDED_CLUSTERS is, rather than just lightly penalized.
STILL_IMAGE_FIT_FLOOR = 1


def is_scale_comparison(candidate: dict) -> bool:
    """True when the topic is framed around size, depth or distance, or as a
    direct comparison ("X vs Y", "bigger than", "the size of", "how deep").
    Reads title + claim only; hooks are opening lines, not the topic's
    framing. See SCALE_COMPARISON_RE."""
    text = f"{candidate.get('title') or ''} || {candidate.get('claim') or ''}"
    return bool(SCALE_COMPARISON_RE.search(text))


def score_candidate(candidate: dict, score_row: dict) -> tuple:
    """-> (score 0-100 int, breakdown dict). Pure function of its inputs and
    the effective cluster priors (cluster_priors(): CLUSTER_PRIORS plus the
    validated auto-weight state). The same candidate, rubric scores and
    weight state always reproduce the same score (DESIGN Sec.9.3)."""
    cluster = candidate.get("cluster")
    excluded_cluster = cluster not in CLUSTER_PRIORS or cluster in EXCLUDED_CLUSTERS
    if excluded_cluster:
        zero = dict.fromkeys(_RUBRIC_FIELDS, 0.0)
        return 0, {**zero, "excluded_cluster": True}
    still_fit = score_row["still_image_fit"]
    if still_fit <= STILL_IMAGE_FIT_FLOOR:
        zero = dict.fromkeys(_RUBRIC_FIELDS, 0.0)
        return 0, {**zero, "excluded_still_unfriendly": True}
    pts = {
        "cluster_prior": round(cluster_priors()[cluster] * 25, 2),
        "counter_intuitive": round(score_row["counter_intuitive"] / 5 * 20, 2),
        "visualisability": round(score_row["visualisability"] / 5 * 10, 2),
        "hook_strength": round(score_row["hook_strength"] / 5 * 10, 2),
        "series_potential": round(score_row["series_potential"] / 5 * 10, 2),
        "evidence_strength": round(score_row["evidence_strength"] / 5 * 10, 2),
        "evergreen": 5.0 if candidate.get("evergreen") else 0.0,
        # prefers the channel niche (mysteries/natural wonders/animals/
        # places/history — static subjects and scenes) over a topic whose
        # core content is an action a still frame can't convey.
        "still_image_fit": round(still_fit / 5 * 10, 2),
        # 2026-10-27 competitor study: scale/comparison framing x1.63 views
        "scale_comparison": SCALE_COMPARISON_BONUS if is_scale_comparison(candidate) else 0.0,
    }
    return min(round(sum(pts.values())), 100), pts


# ------------------------------------------------------- share ranking --

def _entry_cluster(entry: dict):
    parts = entry["parts"] if "parts" in entry else [entry]
    return parts[0].get("cluster")


def _entry_score(entry: dict) -> float:
    return entry["score"] if "score" in entry else max(p["score"] for p in entry["parts"])


def rank_by_share(entries: list, shares: dict | None = None) -> list:
    """Order scored queue entries so each prefix of the queue tracks
    CLUSTER_TARGET_SHARE (deficit round-robin): position k goes to the
    cluster whose `share * (k + 1) - already_placed` is largest, and within
    a cluster to its best-scoring entry. Ties go to the cluster holding the
    higher-scoring entry. A cluster with no target share only fills
    positions once every targeted cluster has run out of entries.

    Callers take queue prefixes (v16_batch.select_topics picks the first N,
    materialize_candidates' fallback pool reads on in order), so the share
    holds for any batch size, while score still decides WHICH topic of a
    cluster goes first. Pure function; a single-cluster queue keeps its
    plain score order. shares=None -> cluster_target_share() (the hand-set
    CLUSTER_TARGET_SHARE plus the validated auto-weight state)."""
    shares = cluster_target_share() if shares is None else shares
    pools: dict = {}
    for e in sorted(entries, key=_entry_score, reverse=True):
        pools.setdefault(_entry_cluster(e), []).append(e)
    placed = dict.fromkeys(pools, 0)
    out = []
    for k in range(len(entries)):
        live = [c for c, p in pools.items() if p]

        def want(c):
            return (shares.get(c, 0.0) > 0, shares.get(c, 0.0) * (k + 1) - placed[c],
                    _entry_score(pools[c][0]))
        c = max(live, key=want)
        out.append(pools[c].pop(0))
        placed[c] += 1
    return out


def queue_share(queue: list) -> dict:
    """cluster -> fraction of queue entries (reporting/tests)."""
    if not queue:
        return {}
    n = len(queue)
    out: dict = {}
    for e in queue:
        c = _entry_cluster(e)
        out[c] = out.get(c, 0) + 1
    return {c: round(v / n, 3) for c, v in out.items()}


# ----------------------------------------------------------- LLM calls --

def clusters_prompt_block() -> str:
    """The ALLOWED CLUSTERS block of topic_ideate: prior, target share of
    the candidates and what the cluster means."""
    rows = []
    shares = cluster_target_share()
    for k, v in cluster_priors().items():
        share = shares.get(k, 0.0)
        aim = f"aim for ~{round(share * 100)}% of candidates" if share else "use sparingly"
        rows.append(f"- {k} (prior {v:.2f}; {aim}): {CLUSTER_DESCRIPTIONS.get(k, '')}")
    return "\n".join(rows)


def ideate(n: int = 20, *, avoid_titles: list = (), ask=None) -> list:
    """One `topic_ideate` call -> `n` candidates, each given a stable `id`."""
    ask = ask or llm.ask
    clusters_block = clusters_prompt_block()
    avoid_block = "\n".join(f"- {t}" for t in avoid_titles) or "(none)"
    prompt, ver = render("topic_ideate", clusters=clusters_block, n=n, avoid_titles=avoid_block)
    res = ask("topic_ideate", prompt, schema="topic_ideate", prompt_version=ver)
    out, seen = [], set()
    for c in res.data["candidates"]:
        cid = _unique_id(c.get("id") or slugify(c["title"]), seen)
        seen.add(cid)
        out.append({**c, "id": cid})
    return out


def score_candidates(candidates: list, *, ask=None) -> list:
    """One `topic_score` call scoring every candidate -> candidates annotated
    with `score`, `score_breakdown`, `best_hook`."""
    if not candidates:
        return []
    ask = ask or llm.ask
    block = "\n\n".join(
        f"id: {c['id']}\ntitle: {c['title']}\ncluster: {c['cluster']}\nclaim: {c['claim']}\n"
        f"hooks: {c['hooks']}\ntemplates: {c['templates']}" for c in candidates)
    prompt, ver = render("topic_score", candidates=block)
    res = ask("topic_score", prompt, schema="topic_score", prompt_version=ver)
    by_id = {s["id"]: s for s in res.data["scores"]}
    out = []
    for c in candidates:
        row = by_id.get(c["id"])
        if row is None:
            # 2026-10-30: this used to raise, crashing the whole batch on
            # one omitted candidate. Caught live: a cached topic_score
            # response consistently omitted the same candidate
            # (t_earth_s_oceans_were_once_boiling_hot_fro) on every retry
            # -- an unattended retry loop hit this ~59,667 times in a few
            # hours since the exception gave main() nothing to write, so
            # every call looked like an instant crash-and-retry. Drop the
            # one omitted candidate (it simply doesn't get scored/queued
            # this round) instead of losing the whole batch over it.
            llm.warn(f"topic_score omitted candidate {c['id']!r}, dropping it")
            continue
        score, breakdown = score_candidate(c, row)
        out.append({**c, "score": score, "score_breakdown": breakdown,
                    "best_hook": row.get("best_hook") or (c["hooks"][0] if c["hooks"] else "")})
    return out


# ------------------------------------------------------- series planner --

def plan_series(candidates: list) -> tuple:
    """-> (series_groups, standalone). DESIGN Sec.9.4: a series is 2-3 parts,
    each standing alone. Any other grouping (1 part, >3, or duplicate part
    numbers) is demoted back to standalone candidates."""
    by_series: dict = {}
    standalone = []
    for c in candidates:
        sid = c.get("series_id")
        (by_series.setdefault(sid, []) if sid else standalone).append(c)
    groups = []
    for sid, parts in by_series.items():
        nums = [p.get("series_part") for p in parts]
        if len(parts) in SERIES_PARTS and None not in nums and len(set(nums)) == len(parts):
            groups.append({"series_id": sid, "parts": sorted(parts, key=lambda p: p["series_part"])})
        else:
            standalone.extend({**p, "series_id": None, "series_part": None} for p in parts)
    return groups, standalone


# --------------------------------------------------------------- history --

def _history_row(candidate: dict, status: str, source: str, extra: dict | None = None) -> dict:
    row = {
        "id": candidate.get("id") or slugify(candidate.get("title", "")),
        "title": candidate.get("title", ""),
        "cluster": candidate.get("cluster"),
        "claim": candidate.get("claim", ""),
        "entities": sorted(entity_set(candidate)),
        "claim_tokens": sorted(claim_tokens(candidate)),
        "series_id": candidate.get("series_id"),
        # 2026-10-27: tag the angle so the analytics join (3e74cb9) can check
        # the competitor x1.63 finding against this channel's own uploads.
        "scale_comparison": is_scale_comparison(candidate),
        "status": status,
        "source": source,
        # 2026-11-11: when the row was written, so dedupe can tell an
        # in-flight queued topic from one held weeks ago (is_blocking_row)
        "ts": _utc_iso(),
    }
    if extra:
        row.update(extra)
    return row


def _utc_iso(epoch: float | None = None) -> str:
    import datetime as _dt
    t = _now() if epoch is None else epoch
    return _dt.datetime.fromtimestamp(t, _dt.timezone.utc).isoformat(timespec="seconds")


def record_published(story_dir, history_path: Path = DEFAULT_HISTORY_PATH,
                     extra: dict | None = None) -> dict | None:
    """Append a status="published" row for a story that PASSed the gate
    (v16_batch.run_batch calls this; a PASS auto-uploads). Durable record
    for dedupe: batch work dirs get cleaned (61 of 108 live batches already
    were) and v16_feedback only tags a row once analytics arrive, which for
    a private or very new upload may be never/days. Copies the topic's
    latest history row (entities, claim tokens, cluster) so the dedupe
    comparison sees the same subject. -> the row written, or None for a
    hand-authored story (no topic_id) or an unreadable story.json."""
    try:
        story = json.loads((Path(story_dir) / "story.json").read_text())
    except (OSError, ValueError):
        return None
    tid = story.get("topic_id")
    if not tid:
        return None
    base = next((h for h in reversed(load_history(history_path)) if h.get("id") == tid), None)
    if base is None:
        base = _history_row({"id": tid, "title": story.get("title", ""),
                             "claim": story.get("title", ""),
                             "cluster": story.get("subject")}, "published", "v16_batch")
    row = {k: v for k, v in base.items() if not k.startswith("real_")
           and k not in ("reason", "score")}
    row.update(status="published", source="v16_batch", ts=_utc_iso(),
               story_id=story.get("story_id") or Path(story_dir).name, **(extra or {}))
    append_history([row], history_path)
    return row


def load_history(path: Path = DEFAULT_HISTORY_PATH) -> list:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def append_history(rows: list, path: Path = DEFAULT_HISTORY_PATH) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def seed_from_channel_csv(path: Path = CHANNEL_CSV) -> list:
    """`data/topic_history.jsonl` seed rows from the real channel CSV (DESIGN Sec.9.2)."""
    if not path.exists():
        return []
    rows = []
    with path.open(newline="") as f:
        for r in csv.DictReader(f):
            title = (r.get("title") or "").strip()
            if not title:
                continue
            cand = {"id": f"yt_{r['id']}", "title": title, "claim": title}
            rows.append(_history_row(cand, "published", "channel_csv",
                                      {"views": int(r.get("views") or 0)}))
    return rows


def seed_from_v15_stories(stories_dir: Path = STORIES_DIR) -> list:
    """Seed rows from the V15 story pack titles (DESIGN Sec.9.2: "the 27 V15 stories")."""
    rows = []
    for story_json in sorted(stories_dir.glob("*/story.json")):
        try:
            data = json.loads(story_json.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        story_id = data.get("story_id", story_json.parent.name)
        title = data.get("title") or story_id
        cand = {"id": f"v15_{story_id}", "title": title, "claim": title}
        rows.append(_history_row(cand, "published", "v15_story", {"subject": data.get("subject")}))
    return rows


def build_seed_history() -> list:
    return seed_from_channel_csv() + seed_from_v15_stories()


def seed_history_file(path: Path = DEFAULT_HISTORY_PATH) -> int:
    """Write the initial `data/topic_history.jsonl`. Overwrites; run once,
    then `build_queue`/`append_history` grow the file from there."""
    rows = build_seed_history()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return len(rows)


# ----------------------------------------------------------- orchestration --

def build_queue(*, n: int = 20, history_path: Path = DEFAULT_HISTORY_PATH, ask=None,
                persist: bool = True, batches_dir: Path | None = None) -> dict:
    """Ideate -> dedupe vs history -> score -> filter (>=MIN_SCORE) -> series-group
    -> ranked queue. -> {"queue", "duplicates", "rejected", "raw_count"}. `queue`
    entries are either a scored candidate dict or a `{"series_id","parts":[...]}`
    group (a group's score is its best-scoring part's), ordered by
    `rank_by_share`: score order within a cluster, CLUSTER_TARGET_SHARE
    across clusters (2026-10-24 analytics review).

    `batches_dir`: batch work dirs scanned for PASS outcomes and recently
    queued legacy topics (batch_outcome_ids). Defaults to BATCHES_DIR only
    for the production history file, so a test history stays isolated."""
    ask = ask or llm.ask
    history = load_history(history_path)
    now = _now()
    if batches_dir is None and Path(history_path) == DEFAULT_HISTORY_PATH:
        batches_dir = BATCHES_DIR
    published_ids, recent_ids = (batch_outcome_ids(batches_dir, now=now)
                                 if batches_dir else (set(), set()))
    avoid_titles = avoid_titles_for_prompt(history, published_ids=published_ids, now=now,
                                           recent_queued_ids=recent_ids)
    raw = ideate(n, avoid_titles=avoid_titles, ask=ask)

    unique, dupes = dedupe(raw, history, now=now, recent_queued_ids=recent_ids,
                           published_ids=published_ids)
    scored = score_candidates(unique, ask=ask)

    accepted_ids = {c["id"] for c in scored if c["score"] >= MIN_SCORE}
    accepted = [c for c in scored if c["id"] in accepted_ids]
    rejected = [c for c in scored if c["id"] not in accepted_ids]

    groups, standalone = plan_series(accepted)
    queue = rank_by_share(standalone + groups)

    if persist:
        to_persist = [_history_row(c, "duplicate", "topic_ideate", {"reason": c["duplicate_reason"]})
                      for c in dupes]
        to_persist += [_history_row(c, "rejected", "topic_ideate", {"score": c["score"]}) for c in rejected]
        for e in queue:
            parts = e["parts"] if "parts" in e else [e]
            to_persist += [_history_row(p, "queued", "topic_ideate", {"score": p["score"]}) for p in parts]
        append_history(to_persist, history_path)

    return {"queue": queue, "duplicates": dupes, "rejected": rejected, "raw_count": len(raw)}


if __name__ == "__main__":
    n = seed_history_file()
    print(f"seeded {DEFAULT_HISTORY_PATH.relative_to(REPO)} with {n} rows")
