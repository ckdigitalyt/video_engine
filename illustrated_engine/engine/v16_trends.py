"""V16 -- periodic external-trend snapshot of competitor Shorts (2026-11-09).

Re-runnable version of the one-off 2026-10-26 competitor study, the one
that found the scale/comparison angle (x1.63 views, p=0.009, n=51, 14
channels; see v16_topics.SCALE_COMPARISON_BONUS). It pulls the recent
public uploads of the same 18 channels through the YouTube Data API,
scores every Short against its own channel, tests the same title, length
and topic patterns, and writes data/trend_signals.json with a timestamp.

    python -m engine.v16_trends [--per-channel 50] [--out PATH] [--dry-run] [--examples]

Run from illustrated_engine/. Read-only, public endpoints only, using the
uploader's OAuth token. Costs about 3 quota units per channel (channels +
playlistItems + videos), ~55 for the full set, against a 10,000/day quota.

NOT wired into topic weighting. A finding here is a lead for a human, or a
later task, to check against our own retention data before any code
changes. That is the path the scale/comparison angle took (8a072a0), and
per the 28955f3 lesson it is never applied automatically. Rules for reading
the output are in the file's own `how_to_use` field (HOW_TO_USE below).

Method, matching the 2026-10-26 study:
  - Shorts = public uploads of at most SHORTS_MAX_S seconds, aged
    MIN_AGE_DAYS..MAX_AGE_DAYS days (views are still climbing in the first
    week).
  - Per-channel normalization: y = ln(views + 1), a = ln(age_days). Both
    are demeaned within each channel, and the pooled within-channel slope b
    of y on a gives residual = y_dm - b * a_dm. A residual of +0.49 means
    "x1.63 this channel's age-adjusted norm", so big channels don't swamp
    small ones.
  - A feature's effect = exp(mean residual with - mean residual without),
    with a two-sided Mann-Whitney U p-value (normal approximation, tie
    corrected) and a direction count: in how many channels (with >= 2
    videos on each side) the feature's median residual is higher.
  - Verdict: "supported" needs p < 0.01, n_with >= 30 and >= 60% of tested
    channels agreeing; "weak" is p < 0.05; anything else is "no effect".
    That is the bar the scale/comparison finding cleared.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # illustrated_engine
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.v16_topics import is_scale_comparison  # noqa: E402

TOKEN_FILE = Path.home() / ".openclaw" / "credentials" / "youtube" / "token.json"
DEFAULT_OUT = REPO / "data" / "trend_signals.json"
PER_CHANNEL = 50
SHORTS_MAX_S = 180
MIN_AGE_DAYS = 7
MAX_AGE_DAYS = 365
VERSION = 1

# The 18 channels analysed on 2026-10-26 (IDs resolved via channels.list on
# 2026-11-09). "analog" = space/science facts, 30-40s, imagery + captions,
# the closest match to @most.amazing.wonders. "adjacent" = bigger "amazing
# facts" channels. Edit this list to change the panel. The output records
# which channels were used.
COMPETITORS = [
    ("UCKWe3mXbIf4KtETT2mvUBdg", "Science Of Infinity", "analog"),
    ("UCOoj8IuW2dXbUAHccI7vGoQ", "Minute of Mystery", "analog"),
    ("UCTbW_SfiOHpvNyrAa-GYgNQ", "Zap Facts", "analog"),
    ("UCSrSd8XW_hQ349ShnQ9-WkQ", "Cosmos Captures", "analog"),
    ("UCkiDuh3-Gawlodboiyw-3gw", "CosmicDropz", "analog"),
    ("UC7mtBSkTRpVHnk2I7zltYpw", "QuirkScience", "analog"),
    ("UCHApHRwamenKgu7HOn7uLxw", "Beyond Earth", "analog"),
    ("UCrE9A07ZBzrvPDcqsQzke-Q", "KnowYourUniverse", "analog"),
    ("UCvz84_Q0BbvZThy75mbd-Dg", "Zack D. Films", "adjacent"),
    ("UCS4uc8cHDqcwwro8lGChaQQ", "FactoHolic", "adjacent"),
    ("UCC6gbNO098rkQKCU0ZaLITQ", "Facts' Mine", "adjacent"),
    ("UCL3rV5PZK_5UYAwmwvyuSqw", "Hoodie Guy", "adjacent"),
    ("UCUeZBocfxALSUdOgNJB5ySA", "Dr Ben Miles", "adjacent"),
    ("UCS3k3REGEKMNp9FeErKOlDA", "FGtheexplainer", "adjacent"),
    ("UC5epkgKdOu7NolxXuj2yylQ", "Why Guy", "adjacent"),
    ("UCm0dvC19ILPjHDi5sN5P9AQ", "James Films", "adjacent"),
    ("UCmDcEeZbiAle33qODw6D_wg", "Atharv Explains Why", "adjacent"),
    ("UC6UZwJO-2is2b4EMcZeO1Fw", "Curiosity Clips", "adjacent"),
]

HOW_TO_USE = [
    "This is a lead list, not a weighting input. Nothing reads this file automatically.",
    "Act only on verdict == 'supported' (p < 0.01, n_with >= 30, >= 60% of tested channels "
    "agree). 'weak' findings are watch-list items: re-run in 2-4 weeks and see if they hold.",
    "Before changing code, check the lead against our own uploads: topic_history rows carry "
    "real_* analytics and tags such as scale_comparison. The scale/comparison angle went "
    "this way: competitor finding (2026-10-26), then a +5 score bonus (8a072a0) plus a history "
    "tag so it can be verified on our data.",
    "Prefer score bonuses or ideation guidance over hard filters. Never add a gate from a "
    "trend signal (28955f3: an 8-video signal collapsed at n=20).",
    "Compare with the previous run (git log -p data/trend_signals.json). A pattern that flips "
    "between runs is noise.",
    "Competitor data is public views only. There is no retention, CTR or subscriber data. Our "
    "own retention (engine.v16_autoweight) remains the primary signal.",
    "Like and comment rate run inversely with reach (14/14 channels on 2026-10-26). Never use "
    "them as a quality signal. like_rate_vs_reach tracks this.",
]

# ------------------------------------------------------------- features --

_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
_CAPS_WORD = re.compile(r"\b[A-Z]{3,}\b")
_NUMBER = re.compile(r"\d")
_FEAR = re.compile(r"\b(?:terrifying|scary|deadly|dangerous|horrifying|creepy|nightmare|"
                   r"die|death|kill|killed|doom)\b", re.I)
_TOPICS = {
    "topic_space": r"\b(?:space|planet|star|sun|moon|galaxy|universe|black hole|nasa|mars|"
                   r"jupiter|saturn|astronaut|orbit|cosmic|asteroid|comet|earth)\b",
    "topic_deep_time": r"\b(?:dinosaur|fossil|million years|billion years|ancient|prehistoric|"
                       r"extinct|extinction|mammoth|ice age|jurassic)\b",
    "topic_body": r"\b(?:body|brain|heart|blood|human|skin|bones?|eyes?|sleep|lungs?|"
                  r"stomach|muscle|dna)\b",
    "topic_animal": r"\b(?:animal|shark|whale|octopus|insect|spider|bird|fish|snake|dog|cat|"
                    r"frog|ant|bee|lion|tiger|elephant|creature|species)\b",
    "topic_physics": r"\b(?:physics|magnet|gravity|sound|light|electric|pressure|heat|"
                     r"temperature|liquid|nitrogen|laser|atom|quantum)\b",
}
_TOPIC_RE = {k: re.compile(v, re.I) for k, v in _TOPICS.items()}

FEATURES = {
    "scale_comparison": lambda v: is_scale_comparison({"title": v["title"]}),
    "question_title": lambda v: v["title"].rstrip().endswith("?"),
    "number_in_title": lambda v: bool(_NUMBER.search(v["title"])),
    "caps_word": lambda v: bool(_CAPS_WORD.search(v["title"])),
    "emoji": lambda v: bool(_EMOJI.search(v["title"])),
    "fear_word": lambda v: bool(_FEAR.search(v["title"])),
    "length_under_30s": lambda v: v["duration_s"] < 30,
    "length_30_45s": lambda v: 30 <= v["duration_s"] <= 45,
    "length_over_60s": lambda v: v["duration_s"] > 60,
    **{k: (lambda r: lambda v: bool(r.search(v["title"])))(r) for k, r in _TOPIC_RE.items()},
}

# ----------------------------------------------------------- YouTube I/O --


def build_service(token_file: Path = TOKEN_FILE):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(token_file))
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def iso_duration_s(s: str) -> int:
    m = _DUR.fullmatch(str(s or ""))
    if not m:
        return 0
    d, h, mi, se = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + se


def fetch_channel(yt, channel_id: str, per_channel: int = PER_CHANNEL) -> dict:
    """-> {channel_id, title, subs, videos: [{id, title, published_at,
    duration_s, views, likes, comments}]} for the channel's latest uploads."""
    ch = yt.channels().list(part="snippet,statistics,contentDetails", id=channel_id).execute()
    items = ch.get("items") or []
    if not items:
        return {"channel_id": channel_id, "error": "channel not found", "videos": []}
    it = items[0]
    uploads = it["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < per_channel:
        res = yt.playlistItems().list(part="contentDetails", playlistId=uploads,
                                      maxResults=min(50, per_channel - len(ids)),
                                      pageToken=token).execute()
        ids += [x["contentDetails"]["videoId"] for x in res.get("items") or []]
        token = res.get("nextPageToken")
        if not token:
            break
    videos = []
    for i in range(0, len(ids), 50):
        res = yt.videos().list(part="snippet,contentDetails,statistics",
                               id=",".join(ids[i:i + 50])).execute()
        for v in res.get("items") or []:
            st = v.get("statistics") or {}
            videos.append({"id": v["id"], "title": v["snippet"].get("title", ""),
                           "published_at": v["snippet"].get("publishedAt", ""),
                           "duration_s": iso_duration_s(v["contentDetails"].get("duration")),
                           "views": int(st.get("viewCount") or 0),
                           "likes": int(st["likeCount"]) if "likeCount" in st else None,
                           "comments": int(st.get("commentCount") or 0)})
    return {"channel_id": channel_id, "title": it["snippet"].get("title", ""),
            "subs": int((it.get("statistics") or {}).get("subscriberCount") or 0),
            "videos": videos}


# ------------------------------------------------------------ statistics --

def _age_days(published_at: str, now: dt.datetime) -> float | None:
    try:
        t = dt.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (now - t).total_seconds() / 86400


def shorts_panel(channels: list, now: dt.datetime) -> list:
    """Flatten to analysable Shorts: [{channel, group, title, duration_s,
    views, likes, age_days}]."""
    out = []
    for ch in channels:
        for v in ch.get("videos") or []:
            age = _age_days(v["published_at"], now)
            if age is None or not (MIN_AGE_DAYS <= age <= MAX_AGE_DAYS):
                continue
            if not (0 < v["duration_s"] <= SHORTS_MAX_S):
                continue
            out.append({**v, "channel": ch.get("name") or ch.get("title"),
                        "group": ch.get("group", ""), "age_days": age})
    return out


def add_residuals(panel: list) -> float:
    """Adds `resid` to each video: ln(views+1) with the channel's level and
    the pooled within-channel age slope removed. -> the slope."""
    by: dict = {}
    for v in panel:
        v["_y"], v["_a"] = math.log(v["views"] + 1), math.log(max(v["age_days"], 1.0))
        by.setdefault(v["channel"], []).append(v)
    sxy = sxx = 0.0
    for vs in by.values():
        my, ma = statistics.fmean(v["_y"] for v in vs), statistics.fmean(v["_a"] for v in vs)
        for v in vs:
            v["_ydm"], v["_adm"] = v["_y"] - my, v["_a"] - ma
            sxy += v["_adm"] * v["_ydm"]
            sxx += v["_adm"] ** 2
    slope = sxy / sxx if sxx > 0 else 0.0
    for v in panel:
        v["resid"] = v["_ydm"] - slope * v["_adm"]
        for k in ("_y", "_a", "_ydm", "_adm"):
            del v[k]
    return slope


def mann_whitney_p(a: list, b: list) -> float:
    """Two-sided Mann-Whitney U p-value, normal approximation with tie
    correction (stdlib only; fine for the n >= ~10 per side we act on)."""
    n1, n2 = len(a), len(b)
    if not n1 or not n2:
        return 1.0
    allv = sorted([(x, 0) for x in a] + [(x, 1) for x in b])
    ranks, i, ties = [0.0] * len(allv), 0, 0.0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        for k in range(i, j + 1):
            ranks[k] = (i + j) / 2 + 1
        t = j - i + 1
        ties += t ** 3 - t
        i = j + 1
    r1 = sum(r for r, (_, g) in zip(ranks, allv) if g == 0)
    u = r1 - n1 * (n1 + 1) / 2
    n = n1 + n2
    var = n1 * n2 / 12 * ((n + 1) - ties / (n * (n - 1))) if n > 1 else 0
    if var <= 0:
        return 1.0
    z = (abs(u - n1 * n2 / 2) - 0.5) / math.sqrt(var)
    return max(0.0, min(1.0, math.erfc(max(z, 0) / math.sqrt(2))))


def pearson(xs: list, ys: list) -> float | None:
    if len(xs) < 3:
        return None
    try:
        return statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        return None


def verdict(mult: float, p: float, n_with: int, agree: int, tested: int) -> str:
    if p < 0.01 and n_with >= 30 and tested and agree / tested >= 0.6:
        return "supported"
    if p < 0.05:
        return "weak"
    return "no effect"


def feature_effects(panel: list) -> list:
    out = []
    for name, fn in FEATURES.items():
        with_, without = [], []
        per_ch: dict = {}
        for v in panel:
            hit = bool(fn(v))
            (with_ if hit else without).append(v["resid"])
            per_ch.setdefault(v["channel"], ([], []))[0 if hit else 1].append(v["resid"])
        if not with_ or not without:
            out.append({"feature": name, "n_with": len(with_), "n_without": len(without),
                        "verdict": "untestable"})
            continue
        mult = math.exp(statistics.fmean(with_) - statistics.fmean(without))
        p = mann_whitney_p(with_, without)
        tested = agree = 0
        for w, wo in per_ch.values():
            if len(w) >= 2 and len(wo) >= 2:
                tested += 1
                same_dir = (statistics.median(w) > statistics.median(wo)) == (mult > 1)
                agree += same_dir
        out.append({"feature": name, "multiplier": round(mult, 3), "p": round(p, 4),
                    "n_with": len(with_), "n_without": len(without),
                    "channels_with": sum(1 for w, _ in per_ch.values() if w),
                    "channels_agree": agree, "channels_tested": tested,
                    "verdict": verdict(mult, p, len(with_), agree, tested)})
    order = {"supported": 0, "weak": 1, "no effect": 2, "untestable": 3}
    return sorted(out, key=lambda f: (order[f["verdict"]], f.get("p", 1.0)))


def channel_profiles(channels: list, panel: list) -> list:
    out = []
    for ch in channels:
        name = ch.get("name") or ch.get("title")
        vs = [v for v in panel if v["channel"] == name]
        ages = [v["age_days"] for v in vs]
        out.append({"name": name, "channel_id": ch["channel_id"], "group": ch.get("group", ""),
                    "subs": ch.get("subs"), "shorts_analysed": len(vs),
                    "posts_per_day": round(len(vs) / max(max(ages) - min(ages), 1.0), 2)
                    if len(vs) > 1 else None,
                    "median_length_s": statistics.median(v["duration_s"] for v in vs) if vs else None,
                    "median_views": statistics.median(v["views"] for v in vs) if vs else None,
                    **({"error": ch["error"]} if ch.get("error") else {})})
    return out


def analyse(channels: list, now: dt.datetime, *, examples: bool = False) -> dict:
    panel = shorts_panel(channels, now)
    slope = add_residuals(panel) if panel else 0.0
    liked = [v for v in panel if v.get("likes") is not None and v["views"] > 0]
    like_r = pearson([v["resid"] for v in liked], [v["likes"] / v["views"] for v in liked])
    len_r = pearson([v["resid"] for v in panel], [float(v["duration_s"]) for v in panel])
    rep = {
        "version": VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "method": "per-channel level + pooled within-channel ln(age) slope removed from "
                  "ln(views+1); feature multiplier = exp(mean residual difference), "
                  "Mann-Whitney p, per-channel direction count -- see engine/v16_trends.py",
        "params": {"shorts_max_s": SHORTS_MAX_S, "min_age_days": MIN_AGE_DAYS,
                   "max_age_days": MAX_AGE_DAYS},
        "n_channels": sum(1 for c in channels if c.get("videos")),
        "n_shorts": len(panel),
        "age_slope": round(slope, 4),
        "length_vs_reach_r": None if len_r is None else round(len_r, 3),
        "like_rate_vs_reach_r": None if like_r is None else round(like_r, 3),
        "findings": feature_effects(panel) if panel else [],
        "channels": channel_profiles(channels, panel),
        "baseline_2026_10_26": {"scale_comparison": {"multiplier": 1.63, "p": 0.009,
                                                     "n_with": 51, "channels": 14},
                                "length_vs_reach_r": 0.03, "n_shorts": 756, "n_channels": 18},
        "how_to_use": HOW_TO_USE,
    }
    if examples:   # public titles of the biggest outliers; off by default (aggregates only)
        top = sorted(panel, key=lambda v: -v["resid"])[:10]
        rep["top_outliers"] = [{"channel": v["channel"], "title": v["title"],
                                "multiplier": round(math.exp(v["resid"]), 2),
                                "age_days": round(v["age_days"])} for v in top]
    return rep


# -------------------------------------------------------------------- run --

def run(*, yt=None, out: Path = DEFAULT_OUT, per_channel: int = PER_CHANNEL,
        competitors=COMPETITORS, dry_run: bool = False, examples: bool = False,
        now: dt.datetime | None = None) -> dict:
    yt = yt or build_service()
    now = now or dt.datetime.now(dt.timezone.utc)
    channels = []
    for cid, name, group in competitors:
        try:
            ch = fetch_channel(yt, cid, per_channel)
        except Exception as e:          # one bad channel must not sink the snapshot
            ch = {"channel_id": cid, "error": f"{type(e).__name__}: {e}", "videos": []}
        channels.append({**ch, "name": name, "group": group})
    rep = analyse(channels, now, examples=examples)
    if not dry_run:
        out = Path(out)
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n")
        os.replace(tmp, out)
    return rep


def format_report(rep: dict) -> str:
    b = rep["baseline_2026_10_26"]
    lines = [f"trend snapshot {rep['generated_at']}: {rep['n_shorts']} Shorts from "
             f"{rep['n_channels']} channels (2026-10-26: {b['n_shorts']} from {b['n_channels']})",
             f"  length vs age-adjusted reach r={rep['length_vs_reach_r']} (2026-10-26: "
             f"{b['length_vs_reach_r']}), like rate vs reach r={rep['like_rate_vs_reach_r']}",
             f"  {'feature':<20}{'mult':>7}{'p':>8}{'n_with':>8}{'agree':>9}  verdict"]
    for f in rep["findings"]:
        if f["verdict"] == "untestable":
            lines.append(f"  {f['feature']:<20}{'-':>7}{'-':>8}{f['n_with']:>8}{'-':>9}  untestable")
            continue
        lines.append(f"  {f['feature']:<20}{f['multiplier']:>7.2f}{f['p']:>8.3f}{f['n_with']:>8}"
                     f"{f['channels_agree']:>4}/{f['channels_tested']:<4}  {f['verdict']}")
    errs = [c for c in rep["channels"] if c.get("error")]
    for c in errs:
        lines.append(f"  channel {c['name']} skipped: {c['error']}")
    for t in rep.get("top_outliers") or []:
        lines.append(f"  outlier x{t['multiplier']:<6} {t['channel']}: {t['title'][:70]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.v16_trends", description=__doc__.split("\n")[0])
    ap.add_argument("--per-channel", type=int, default=PER_CHANNEL,
                    help="latest uploads per channel")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="trend_signals.json to write")
    ap.add_argument("--dry-run", action="store_true", help="fetch and report, write nothing")
    ap.add_argument("--examples", action="store_true",
                    help="include top outlier titles (public metadata) in the output")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args(argv)
    rep = run(out=Path(a.out), per_channel=a.per_channel, dry_run=a.dry_run, examples=a.examples)
    print(json.dumps(rep, indent=1, ensure_ascii=False) if a.json else format_report(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
