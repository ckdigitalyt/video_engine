"""V16 -- real-performance feedback loop (2026-10-24 analytics review).

Pulls YouTube Analytics for the channel's recent videos, matches each video
back to the story/topic that produced it, and writes the real numbers onto
that topic's row in `data/topic_history.jsonl` as new `real_*` fields
(existing fields and rows are never changed or removed).

    python -m engine.v16_feedback [--days 28] [--dry-run] [--history PATH]

Run from illustrated_engine/. Manual only for now (no cron). Read-only
against YouTube: yt-analytics.readonly + youtube.readonly, using the same
OAuth token the uploader uses
(~/.openclaw/credentials/youtube/token.json). A refreshed access token is
kept in memory and never written back.

Matching, in priority order:
  1. build/v16/batches/*/batch_report.json  rows[].package.youtube.video_id
     -> rows[].story (the story dir name). Exact, recorded at upload time.
  2. Uploaded title == a build/v16/**/manifest.json metadata.title
     (normalised) -> the manifest's video_id (= story dir name). Uploads
     before 2026-10-24 only recorded the YouTube id in batch reports that
     were later cleaned, so most older videos are matched this way. A
     title shared by two different stories is reported, not guessed.
Then stories/<story>/story.json `topic_id` -> the topic_history row with
that `id` (its latest "queued" row, else its latest row).

Lifetime numbers (2026-11-11): `--days` picks which videos are active; the
metrics themselves are read from the earliest known upload's publish date,
and each row records `real_published_at`, so retention is not truncated to
late long-tail viewers once a video ages past the window.

After the history is written, engine.v16_autoweight recomputes the
shrunk, capped cluster-weight override (data/cluster_weight_state.json,
read by engine.v16_topics) from the now-updated rows, so one command does
both (2026-11-09). --no-autoweight skips that step. --dry-run previews it
without writing. An autoweight failure is reported, not raised: the
analytics already written to history are kept.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # illustrated_engine
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

TOKEN_FILE = Path.home() / ".openclaw" / "credentials" / "youtube" / "token.json"
METRICS = ("views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
           "subscribersGained,likes,comments,shares")
BUILD_V16 = ROOT / "build" / "v16"
BATCHES_DIR = BUILD_V16 / "batches"
DEFAULT_DAYS = 28
MAX_RESULTS = 200                 # Analytics API cap for dimensions=video

# Analytics metric -> topic_history field
FIELD_MAP = {
    "views": "real_views",
    "estimatedMinutesWatched": "real_minutes_watched",
    "averageViewDuration": "real_avg_view_s",
    "averageViewPercentage": "real_retention_pct",
    "subscribersGained": "real_subs_gained",
    "likes": "real_likes",
    "comments": "real_comments",
    "shares": "real_shares",
}


def _defaults():
    from engine.v16_topics import DEFAULT_HISTORY_PATH, STORIES_DIR
    return DEFAULT_HISTORY_PATH, STORIES_DIR


# ---------------------------------------------------------------- YouTube --

def build_services(token_file: Path = TOKEN_FILE):
    """-> (youtubeAnalytics v2, youtube v3) clients from the stored token."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_file))
    return (build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False),
            build("youtube", "v3", credentials=creds, cache_discovery=False))


def fetch_video_metrics(analytics, start: dt.date, end: dt.date,
                        max_results: int = MAX_RESULTS) -> dict:
    """-> {youtube_video_id: {metric: number}} for the channel, start..end."""
    res = analytics.reports().query(
        ids="channel==MINE", startDate=start.isoformat(), endDate=end.isoformat(),
        dimensions="video", metrics=METRICS, sort="-views",
        maxResults=max_results).execute()
    names = [h["name"] for h in res.get("columnHeaders") or []]
    out = {}
    for row in res.get("rows") or []:
        rec = dict(zip(names, row))
        vid = rec.pop("video", None)
        if vid:
            out[vid] = rec
    return out


def fetch_video_titles(data_api, ids: list) -> dict:
    """-> {youtube_video_id: {"title", "published_at"}} (50 ids per call)."""
    out = {}
    ids = list(ids)
    for i in range(0, len(ids), 50):
        res = data_api.videos().list(part="snippet", id=",".join(ids[i:i + 50])).execute()
        for it in res.get("items") or []:
            sn = it.get("snippet") or {}
            out[it["id"]] = {"title": sn.get("title", ""),
                             "published_at": sn.get("publishedAt", "")}
    return out


def earliest_publish(titles: dict):
    """-> the earliest publish date (dt.date) among fetch_video_titles'
    results, or None."""
    dates = []
    for t in titles.values():
        d = str((t or {}).get("published_at") or "")[:10]
        try:
            dates.append(dt.date.fromisoformat(d))
        except ValueError:
            continue
    return min(dates) if dates else None


# --------------------------------------------------------------- matching --

def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def index_uploads(batches_dir: Path = BATCHES_DIR) -> dict:
    """{youtube_video_id: story_dir_name} from every batch_report.json."""
    out = {}
    for f in sorted(Path(batches_dir).glob("*/batch_report.json")):
        try:
            rep = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for row in rep.get("rows") or []:
            vid = (((row.get("package") or {}).get("youtube")) or {}).get("video_id")
            if vid and row.get("story"):
                out[vid] = Path(str(row["story"])).name
    return out


def index_titles(build_dir: Path = BUILD_V16) -> dict:
    """{normalised uploaded title: {story_dir_name, ...}} from manifests."""
    out: dict = {}
    for f in sorted(Path(build_dir).glob("**/manifest.json")):
        try:
            man = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        title = (man.get("metadata") or {}).get("title")
        sid = man.get("video_id")
        if title and sid:
            out.setdefault(norm_title(title), set()).add(str(sid))
    return out


def story_topic_id(story_id: str, stories_dir: Path):
    f = Path(stories_dir) / story_id / "story.json"
    try:
        return json.loads(f.read_text()).get("topic_id")
    except (OSError, json.JSONDecodeError):
        return None


def match_videos(metrics: dict, titles: dict, uploads: dict, title_index: dict,
                 stories_dir: Path) -> tuple:
    """-> (matches, unmatched). A match: {video_id, title, story_id,
    topic_id, matched_by, metrics}. Unmatched entries carry a `reason`."""
    matches, unmatched = [], []
    for vid, m in metrics.items():
        title = (titles.get(vid) or {}).get("title", "")
        story_id, how = uploads.get(vid), "batch_report"
        if not story_id:
            cands = title_index.get(norm_title(title)) or set()
            if len(cands) > 1:
                unmatched.append({"video_id": vid, "title": title,
                                  "reason": f"title shared by stories {sorted(cands)}"})
                continue
            story_id, how = (next(iter(cands)) if cands else None), "title"
        if not story_id:
            unmatched.append({"video_id": vid, "title": title,
                              "reason": "no batch report or manifest for this upload"})
            continue
        topic_id = story_topic_id(story_id, stories_dir)
        if not topic_id:
            unmatched.append({"video_id": vid, "title": title, "story_id": story_id,
                              "reason": "story has no topic_id (hand-authored or missing)"})
            continue
        matches.append({"video_id": vid, "title": title, "story_id": story_id,
                        "topic_id": topic_id, "matched_by": how, "metrics": m})
    return matches, unmatched


# ---------------------------------------------------------------- history --

def _target_row(rows: list, topic_id: str):
    idx = [i for i, r in enumerate(rows) if r.get("id") == topic_id]
    queued = [i for i in idx if rows[i].get("status") == "queued"]
    return (queued or idx or [None])[-1]


def apply_to_history(rows: list, matches: list, *, window: str, now: str) -> tuple:
    """Adds real_* fields to each match's topic row, in place.
    -> (updated [{topic_id, row_index, video_id}], missing [match])."""
    updated, missing = [], []
    for mt in matches:
        i = _target_row(rows, mt["topic_id"])
        if i is None:
            missing.append({**{k: mt[k] for k in ("video_id", "title", "story_id", "topic_id")},
                            "reason": "no topic_history row with this id"})
            continue
        row = rows[i]
        for metric, field in FIELD_MAP.items():
            if metric in mt["metrics"]:
                row[field] = mt["metrics"][metric]
        row.update(real_video_id=mt["video_id"], real_story_id=mt["story_id"],
                   real_title=mt["title"], real_window=window, real_updated_at=now)
        if mt.get("published_at"):
            row["real_published_at"] = mt["published_at"]
        updated.append({"topic_id": mt["topic_id"], "row_index": i,
                        "video_id": mt["video_id"]})
    return updated, missing


def read_history_lines(path: Path) -> list:
    return [ln for ln in Path(path).read_text().splitlines() if ln.strip()] \
        if Path(path).exists() else []


def write_history(path: Path, rows: list, original_lines: list) -> int:
    """Atomic rewrite (tmp + os.replace). Rows appended by a concurrent
    build_queue since `original_lines` was read are kept, unmodified, at
    the end. -> number of such late rows."""
    path = Path(path)
    current = read_history_lines(path)
    if current[:len(original_lines)] != original_lines:
        raise RuntimeError(f"{path} changed underneath the feedback run (not an append); "
                           "re-run it")
    late = current[len(original_lines):]
    tmp = path.with_suffix(path.suffix + ".feedback.tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows)
                   + "".join(ln + "\n" for ln in late))
    os.replace(tmp, path)
    return len(late)


# -------------------------------------------------------------------- run --

def run(*, days: int = DEFAULT_DAYS, history_path: Path | None = None,
        stories_dir: Path | None = None, batches_dir: Path = BATCHES_DIR,
        build_dir: Path = BUILD_V16, services=None, dry_run: bool = False,
        today: dt.date | None = None, autoweight: bool = True,
        weight_state_path: Path | None = None) -> dict:
    hp_default, sd_default = _defaults()
    history_path = Path(history_path or hp_default)
    stories_dir = Path(stories_dir or sd_default)
    analytics, data_api = services or build_services()
    end = today or dt.date.today()
    start = end - dt.timedelta(days=days)
    metrics = fetch_video_metrics(analytics, start, end)
    lines = read_history_lines(history_path)
    rows = [json.loads(ln) for ln in lines]
    known = [r["real_video_id"] for r in rows if r.get("real_video_id")]
    titles = fetch_video_titles(data_api, list(dict.fromkeys(list(metrics) + known)))
    # 2026-11-11 review: a rolling `days` window truncates older videos'
    # data -- one video had 420 lifetime views but 35 in-window, and its
    # 36.7% "retention" described only late long-tail viewers. The window
    # query above still decides which videos are active; when any known
    # upload predates it, the metrics are re-read from the earliest publish
    # date, so every video's numbers are lifetime numbers.
    lifetime_start = earliest_publish(titles)
    if lifetime_start and lifetime_start < start:
        start = lifetime_start
        metrics = fetch_video_metrics(analytics, start, end)
    matches, unmatched = match_videos(metrics, titles, index_uploads(batches_dir),
                                      index_titles(build_dir), stories_dir)
    for mt in matches:
        mt["published_at"] = (titles.get(mt["video_id"]) or {}).get("published_at") or None
    window = f"{start.isoformat()}..{end.isoformat()}"
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    updated, missing = apply_to_history(rows, matches, window=window, now=now)
    late = 0
    if updated and not dry_run:
        late = write_history(history_path, rows, lines)
    return {"window": window, "videos": len(metrics), "matched": len(matches),
            "updated_rows": len(updated), "dry_run": dry_run,
            "history_path": str(history_path), "late_rows_kept": late,
            "matches": [{k: v for k, v in mt.items()} for mt in matches],
            "unmatched": unmatched + missing,
            "autoweight": _run_autoweight(history_path, weight_state_path, dry_run, rows)
            if autoweight else None}


def _run_autoweight(history_path: Path, state_path, dry_run: bool, rows: list) -> dict:
    """Recompute cluster weights from the just-written history. In a dry run
    the history on disk is unchanged, so preview from the in-memory rows."""
    from engine import v16_autoweight as AW
    try:
        if not dry_run:
            return AW.run(history_path=history_path, state_path=state_path)
        sp = Path(state_path or AW.default_state_path(history_path))
        return {"state_path": str(sp), "dry_run": True,
                "state": AW.compute_state(rows, AW.load_state(sp))}
    except Exception as e:          # never lose the analytics write over this step
        return {"error": f"{type(e).__name__}: {e}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.v16_feedback", description=__doc__.split("\n")[0])
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS, help="analytics window (days)")
    ap.add_argument("--history", default=None, help="topic_history.jsonl to update")
    ap.add_argument("--dry-run", action="store_true", help="match and report, write nothing")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    ap.add_argument("--no-autoweight", action="store_true",
                    help="skip recomputing data/cluster_weight_state.json")
    a = ap.parse_args(argv)
    rep = run(days=a.days, history_path=a.history, dry_run=a.dry_run,
              autoweight=not a.no_autoweight)
    if a.json:
        print(json.dumps(rep, indent=1, default=str))
        return 0
    print(f"window {rep['window']}: {rep['videos']} videos with data, {rep['matched']} "
          f"matched to topics, {rep['updated_rows']} topic_history rows "
          f"{'would be ' if rep['dry_run'] else ''}updated ({rep['history_path']})")
    for mt in sorted(rep["matches"], key=lambda m: -float(m["metrics"].get("views") or 0)):
        m = mt["metrics"]
        print(f"  {mt['video_id']}  views={m.get('views'):>5}  "
              f"ret={float(m.get('averageViewPercentage') or 0):5.1f}%  "
              f"subs={m.get('subscribersGained')}  [{mt['matched_by']}] {mt['topic_id']}")
    for u in rep["unmatched"]:
        print(f"  unmatched {u['video_id']} {u.get('title', '')[:50]!r}: {u['reason']}")
    aw = rep.get("autoweight")
    if aw and "error" in aw:
        print(f"  auto-weight FAILED (history update kept): {aw['error']}")
    elif aw:
        from engine import v16_autoweight as AW
        print(AW.format_report(aw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
