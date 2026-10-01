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

CLUSTER_PRIORS = {                  # DESIGN Sec.9.1, relative to the channel's real views
    "deep_time": 1.00,
    "spectacle_physics": 0.85,
    "exotic_space_travel": 0.70,
    "space_discovery": 0.50,
    "general_explainer": 0.20,
}
EXCLUDED_CLUSTERS = {"quiz", "crypto", "ai_policy", "asmr"}   # dilute the channel's topical signal

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
    A shared `series_id` is the DESIGN Sec.9.2 exception for a planned series part."""
    if candidate.get("series_id") and candidate["series_id"] == history_row.get("series_id"):
        return None
    ej = entity_jaccard(entity_set(candidate), set(history_row.get("entities") or ()))
    if ej >= DUP_ENTITY_JACCARD:
        return (f"entity overlap {ej:.2f} >= {DUP_ENTITY_JACCARD} with "
                f"{history_row.get('id') or history_row.get('title')!r}")
    co = claim_overlap(claim_tokens(candidate), set(history_row.get("claim_tokens") or ()))
    if co >= DUP_CLAIM_OVERLAP:
        return (f"claim overlap {co:.2f} >= {DUP_CLAIM_OVERLAP} with "
                f"{history_row.get('id') or history_row.get('title')!r}")
    return None


def dedupe(candidates: list, history: list) -> tuple:
    """-> (unique, duplicates). Duplicates carry a `duplicate_reason`."""
    unique, dupes = [], []
    for c in candidates:
        reason = next((r for h in history if (r := is_duplicate(c, h))), None)
        (dupes if reason else unique).append({**c, "duplicate_reason": reason} if reason else c)
    return unique, dupes


# ---------------------------------------------------------------- score --

def score_candidate(candidate: dict, score_row: dict) -> tuple:
    """-> (score 0-100 int, breakdown dict). Pure function of its inputs: same
    candidate + same rubric scores always reproduce the same score (DESIGN Sec.9.3)."""
    cluster = candidate.get("cluster")
    if cluster not in CLUSTER_PRIORS or cluster in EXCLUDED_CLUSTERS:
        zero = dict.fromkeys(
            ("cluster_prior", "counter_intuitive", "visualisability", "hook_strength",
             "series_potential", "evidence_strength", "evergreen"), 0.0)
        return 0, {**zero, "excluded_cluster": cluster not in CLUSTER_PRIORS or cluster in EXCLUDED_CLUSTERS}
    pts = {
        "cluster_prior": round(CLUSTER_PRIORS[cluster] * 25, 2),
        "counter_intuitive": round(score_row["counter_intuitive"] / 5 * 20, 2),
        "visualisability": round(score_row["visualisability"] / 5 * 15, 2),
        "hook_strength": round(score_row["hook_strength"] / 5 * 15, 2),
        "series_potential": round(score_row["series_potential"] / 5 * 10, 2),
        "evidence_strength": round(score_row["evidence_strength"] / 5 * 10, 2),
        "evergreen": 5.0 if candidate.get("evergreen") else 0.0,
    }
    return min(round(sum(pts.values())), 100), pts


# ----------------------------------------------------------- LLM calls --

def ideate(n: int = 20, *, avoid_titles: list = (), ask=None) -> list:
    """One `topic_ideate` call -> `n` candidates, each given a stable `id`."""
    ask = ask or llm.ask
    clusters_block = "\n".join(f"- {k} (prior {v:.2f})" for k, v in CLUSTER_PRIORS.items())
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
            raise ValueError(f"topic_score omitted candidate {c['id']!r}")
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
        "status": status,
        "source": source,
    }
    if extra:
        row.update(extra)
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
                persist: bool = True) -> dict:
    """Ideate -> dedupe vs history -> score -> filter (>=MIN_SCORE) -> series-group
    -> ranked queue. -> {"queue", "duplicates", "rejected", "raw_count"}. `queue`
    entries are either a scored candidate dict or a `{"series_id","parts":[...]}`
    group, ranked by score (a group's score is its best-scoring part's)."""
    ask = ask or llm.ask
    history = load_history(history_path)
    avoid_titles = [h["title"] for h in history[-50:]]      # keep the ideation prompt bounded
    raw = ideate(n, avoid_titles=avoid_titles, ask=ask)

    unique, dupes = dedupe(raw, history)
    scored = score_candidates(unique, ask=ask)

    accepted_ids = {c["id"] for c in scored if c["score"] >= MIN_SCORE}
    accepted = [c for c in scored if c["id"] in accepted_ids]
    rejected = [c for c in scored if c["id"] not in accepted_ids]

    groups, standalone = plan_series(accepted)
    queue = sorted(standalone + groups,
                   key=lambda e: e["score"] if "score" in e else max(p["score"] for p in e["parts"]),
                   reverse=True)

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
