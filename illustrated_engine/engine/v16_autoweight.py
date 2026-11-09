"""V16 -- auto-weight: real retention -> cluster priors / target shares
(2026-11-09).

Closes the loop that engine.v16_feedback opened. Feedback writes real YouTube
Analytics (real_retention_pct, real_views, real_subs_gained, ...) onto
data/topic_history.jsonl rows. This module reads those rows back, measures
each topic cluster's retention against the channel average, and writes small,
sample-size-shrunk adjustments of the hand-set CLUSTER_PRIORS /
CLUSTER_TARGET_SHARE to data/cluster_weight_state.json. engine.v16_topics
layers that file over its constants (cluster_priors() /
cluster_target_share()).

    python -m engine.v16_autoweight [--history PATH] [--state PATH] [--dry-run] [--json]

Run from illustrated_engine/. engine.v16_feedback runs this automatically
right after it writes real_* fields, so one feedback command does both.
Pure stdlib, no network.

DESIGN -- the failure mode this is built around (28955f3): quality floors fit
to 8 videos (r = +0.55 / +0.59) fell to noise at n = 20 (+0.06 / -0.05), and
the floor blocked the exact topic category another re-weighting was
promoting. So:

 1. Per-video cleaning. Rows under MIN_VIEWS views are dropped, because
    retention on 3-20 views is noise (live history has 3-, 12- and 20-view
    rows). Retention above RETENTION_IMPLAUSIBLE is dropped as a measurement
    artifact (live history has a 1099% row on 52 views). Shorts loops push
    real retention past 100%, so the remaining values are winsorized at
    RETENTION_CAP and one looping video cannot dominate a cluster mean.
    Each video counts once (latest row per real_video_id).

 2. Shrinkage toward the hand-set prior (normal-normal empirical Bayes with
    a fixed pseudo-count). A cluster's observed relative retention
    rel = mean_c / channel_mean is trusted with confidence n / (n + PSEUDO_N),
    which is the posterior weight on the data when the prior is worth
    PSEUDO_N videos. PSEUDO_N = 20 ~ sigma^2 / tau^2: per-video retention
    scatter sigma is about 20 points on the 2026-10-26 sample, and plausible
    true differences between clusters tau are about 4-5 points. The hand
    priors were themselves set from roughly 15-20 videos. Clusters with
    fewer than MIN_N clean videos get confidence 0 and no change at all.
    n=5 -> 0.20, n=10 -> 0.33, n=30 -> 0.60, n=60 -> 0.75. A fixed
    pseudo-count was chosen over estimating tau^2 from the data, because a
    method-of-moments tau^2 over 5 clusters swings between 0 and huge
    exactly when samples are small.
        factor_c = 1 + GAIN * confidence_c * (rel_c - 1)
    GAIN = 1.5 turns a retention gap into a weight gap at roughly the rate
    the 2026-10-24 review did between its two best-measured clusters
    (spectacle_physics vs deep_time: 77% vs 65% retention, an 18% gap,
    became priors 1.0 vs 0.8, a 25% gap).

 3. A non-compounding target. Each run recomputes the target from the
    hand-set baseline x factor, over all clean data. It never multiplies
    the previous state, so re-running on the same data cannot ratchet a
    weight. A run whose data fingerprint matches the last run is a no-op.

 4. Per-update step cap, a second line of defense behind the shrinkage.
    A prior moves at most MAX_STEP (20%) of its current value per update.
    Shares move along the straight line toward their target, cut short so
    no cluster's share moves more than MAX_STEP of its current value. That
    keeps the sum at exactly 1.

 5. Lifetime band, no gates. Every prior and share stays within
    v16_topics.AUTOWEIGHT_BAND (0.7x-1.3x) of its hand-set baseline,
    enforced here and again when v16_topics reads the file. Nothing can
    reach 0, nothing is added or removed from targeting, and MIN_SCORE, the
    still-image floor and the critic floors are untouched. At the band's
    edge a cluster prior is worth +/-7.5 score points at most (prior x 25).

Secondary signals: real_views and real_subs_gained are reported per cluster
in the state file, but they do not move weights. Views over a rolling 28-day
window are confounded by upload age (topic_history rows carry no publish
date), they are heavy-tailed (12 to 1,189 on the 2026-10-26 sample), and
22 of 25 annotated videos gained 0-2 subscribers. Using them needs
age-adjusted views first. Retention is age-robust.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # illustrated_engine
REPO = ROOT.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine import v16_topics as T  # noqa: E402

STATE_VERSION = 1
STATE_FILENAME = "cluster_weight_state.json"

MIN_VIEWS = 25                 # per-video: fewer views -> retention is noise
RETENTION_IMPLAUSIBLE = 250.0  # per-video: above this -> measurement artifact, dropped
RETENTION_CAP = 120.0          # per-video: winsorize looping Shorts here
MIN_N = 5                      # per-cluster: fewer clean videos -> no adjustment
PSEUDO_N = 20                  # prior strength in videos (confidence = n / (n + PSEUDO_N))
GAIN = 1.5                     # retention gap -> weight gap
MAX_STEP = 0.20                # max relative move of any weight per update

PARAMS = {"min_views": MIN_VIEWS, "retention_implausible": RETENTION_IMPLAUSIBLE,
          "retention_cap": RETENTION_CAP, "min_n": MIN_N, "pseudo_n": PSEUDO_N,
          "gain": GAIN, "max_step": MAX_STEP, "band": list(T.AUTOWEIGHT_BAND)}


def default_state_path(history_path: Path | None = None) -> Path:
    """The state file lives next to the history it was computed from. That
    is data/cluster_weight_state.json for the production history, and a
    temp-dir history (tests, experiments) never touches production state."""
    if history_path is None or Path(history_path).resolve() == T.DEFAULT_HISTORY_PATH.resolve():
        return T.CLUSTER_WEIGHT_STATE_PATH
    return Path(history_path).parent / STATE_FILENAME


# ------------------------------------------------------------- samples --

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def video_samples(rows: list) -> tuple:
    """-> (samples, excluded). One sample per real video: {video_id, cluster,
    retention (winsorized), retention_raw, views, subs}. `excluded` counts
    dropped videos per reason."""
    latest: dict = {}
    for r in rows:
        if "real_retention_pct" not in r:
            continue
        vid = r.get("real_video_id") or r.get("id")
        if vid not in latest or str(r.get("real_updated_at") or "") >= \
                str(latest[vid].get("real_updated_at") or ""):
            latest[vid] = r
    samples, excluded = [], {}

    def drop(reason):
        excluded[reason] = excluded.get(reason, 0) + 1

    for vid, r in latest.items():
        cluster = r.get("cluster")
        if cluster not in T.CLUSTER_PRIORS or cluster in T.EXCLUDED_CLUSTERS:
            drop("unknown_cluster")
            continue
        ret, views = _num(r.get("real_retention_pct")), _num(r.get("real_views")) or 0.0
        if ret is None or ret <= 0:
            drop("bad_retention")
        elif ret > RETENTION_IMPLAUSIBLE:
            drop("implausible_retention")
        elif views < MIN_VIEWS:
            drop("low_views")
        else:
            samples.append({"video_id": vid, "cluster": cluster,
                            "retention": min(ret, RETENTION_CAP), "retention_raw": ret,
                            "views": views, "subs": _num(r.get("real_subs_gained")) or 0.0})
    return samples, excluded


def confidence(n: int) -> float:
    """Posterior weight on a cluster's own data: 0 below MIN_N clean videos,
    else n / (n + PSEUDO_N)."""
    return 0.0 if n < MIN_N else n / (n + PSEUDO_N)


def cluster_factors(samples: list) -> tuple:
    """-> (channel_mean_retention or None, {cluster: stats}). Every cluster in
    CLUSTER_PRIORS gets an entry. `factor` is the shrunk, band-clamped
    multiplier for its baseline weights (1.0 = no change)."""
    lo, hi = T.AUTOWEIGHT_BAND
    grand = statistics.fmean(s["retention"] for s in samples) if samples else None
    out = {}
    for c in T.CLUSTER_PRIORS:
        cs = [s for s in samples if s["cluster"] == c]
        n = len(cs)
        st = {"n": n, "confidence": round(confidence(n), 4), "factor": 1.0}
        if cs:
            mean = statistics.fmean(s["retention"] for s in cs)
            views = sum(s["views"] for s in cs)
            st.update(mean_retention=round(mean, 2),
                      median_views=statistics.median(s["views"] for s in cs),
                      subs_per_1k_views=round(1000 * sum(s["subs"] for s in cs) / views, 2)
                      if views else 0.0)
            if grand:
                rel = mean / grand
                factor = 1 + GAIN * confidence(n) * (rel - 1)
                st.update(rel_retention=round(rel, 4),
                          factor=round(min(max(factor, lo), hi), 6))
        out[c] = st
    return grand, out


# --------------------------------------------------------------- update --

def target_weights(factors: dict) -> tuple:
    """-> (target priors, target shares) = hand-set baseline x factor, both
    inside the band. Shares are renormalized to sum to 1."""
    priors = {c: T.band_clamp(b * factors[c]["factor"], b) for c, b in T.CLUSTER_PRIORS.items()}
    shares = T.normalize_shares({c: b * factors[c]["factor"]
                                 for c, b in T.CLUSTER_TARGET_SHARE.items()},
                                T.CLUSTER_TARGET_SHARE)
    return priors, shares


def step_priors(prev: dict, target: dict, max_step: float = MAX_STEP) -> dict:
    """Each prior moves toward its target by at most max_step x its current
    value, and stays inside the band."""
    out = {}
    for c, b in T.CLUSTER_PRIORS.items():
        p = prev.get(c, b)
        out[c] = T.band_clamp(min(max(target[c], p * (1 - max_step)), p * (1 + max_step)), b)
    return out


def step_shares(prev: dict, target: dict, max_step: float = MAX_STEP) -> dict:
    """Move the share vector along the straight line prev -> target, cut short
    so that no cluster's share moves more than max_step x its current value.
    A convex combination of two vectors that are inside the band and sum to 1
    is also inside the band and sums to 1, so no renormalization is needed
    afterwards (renormalizing would break the cap)."""
    lam = 1.0
    for c, p in prev.items():
        d = abs(target[c] - p)
        if d > 1e-15:
            lam = min(lam, max_step * p / d)
    return {c: p + lam * (target[c] - p) for c, p in prev.items()}


def fingerprint(samples: list) -> str:
    key = json.dumps([PARAMS, T.CLUSTER_PRIORS, T.CLUSTER_TARGET_SHARE,
                      sorted((s["video_id"], s["cluster"], s["views"], s["retention_raw"])
                             for s in samples)], sort_keys=True)
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _prev_weights(prev_state: dict | None) -> tuple:
    """-> (priors, shares, valid). The previous state counts only if it was
    computed against today's hand-set baseline, else we restart from it."""
    if (isinstance(prev_state, dict)
            and T._same_base(prev_state.get("base_priors"), T.CLUSTER_PRIORS)
            and T._same_base(prev_state.get("base_shares"), T.CLUSTER_TARGET_SHARE)
            and isinstance(prev_state.get("priors"), dict)
            and isinstance(prev_state.get("shares"), dict)):
        pp, ps = prev_state["priors"], prev_state["shares"]
        priors = {c: T.band_clamp(float(pp[c]), b) if T._finite(pp.get(c)) else b
                  for c, b in T.CLUSTER_PRIORS.items()}
        shares = T.normalize_shares({c: float(ps[c]) if T._finite(ps.get(c)) else b
                                     for c, b in T.CLUSTER_TARGET_SHARE.items()},
                                    T.CLUSTER_TARGET_SHARE)
        return priors, shares, True
    return dict(T.CLUSTER_PRIORS), dict(T.CLUSTER_TARGET_SHARE), False


def compute_state(rows: list, prev_state: dict | None = None, *, now: str | None = None) -> dict:
    """Pure: topic_history rows + previous state -> new state dict."""
    now = now or dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    samples, excluded = video_samples(rows)
    grand, factors = cluster_factors(samples)
    fp = fingerprint(samples)
    prev_p, prev_s, prev_ok = _prev_weights(prev_state)
    if prev_ok and prev_state.get("data_fingerprint") == fp:
        priors, shares, changed = prev_p, prev_s, False          # same data -> no-op
    else:
        tgt_p, tgt_s = target_weights(factors)
        priors, shares = step_priors(prev_p, tgt_p), step_shares(prev_s, tgt_s)
        changed = True
    for c, st in factors.items():
        st["prior"] = round(priors[c], 6)
        if c in shares:
            st["share"] = round(shares[c], 6)
    return {
        "version": STATE_VERSION,
        "updated_at": now if changed else (prev_state or {}).get("updated_at", now),
        "checked_at": now,
        "changed_on_last_check": changed,
        "method": "empirical-Bayes shrinkage of per-cluster relative retention toward the "
                  "hand-set baseline (confidence n/(n+pseudo_n), 0 below min_n), "
                  "non-compounding target, per-update step cap, lifetime band "
                  "-- see engine/v16_autoweight.py",
        "params": PARAMS,
        "base_priors": dict(T.CLUSTER_PRIORS),
        "base_shares": dict(T.CLUSTER_TARGET_SHARE),
        "priors": {c: round(v, 6) for c, v in priors.items()},
        "shares": {c: round(v, 6) for c, v in shares.items()},
        "n_videos": len(samples),
        "excluded_videos": excluded,
        "channel_mean_retention": round(grand, 2) if grand else None,
        "clusters": factors,
        "data_fingerprint": fp,
    }


# ------------------------------------------------------------------- I/O --

def load_state(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write_state(path: Path, state: dict) -> None:
    """Atomic (tmp + os.replace): a v16_topics read never sees half a file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=1, sort_keys=False) + "\n")
    os.replace(tmp, path)


def run(*, history_path: Path | None = None, state_path: Path | None = None,
        dry_run: bool = False, now: str | None = None) -> dict:
    history_path = Path(history_path or T.DEFAULT_HISTORY_PATH)
    state_path = Path(state_path or default_state_path(history_path))
    prev = load_state(state_path)
    state = compute_state(T.load_history(history_path), prev, now=now)
    if not dry_run and (state["changed_on_last_check"] or prev is None):
        write_state(state_path, state)
    return {"state_path": str(state_path), "dry_run": dry_run, "state": state,
            "previous_priors": (prev or {}).get("priors"),
            "previous_shares": (prev or {}).get("shares")}


def format_report(rep: dict) -> str:
    st = rep["state"]
    verb = "would write" if rep["dry_run"] else "wrote"
    if not st["changed_on_last_check"]:
        verb = "unchanged (same data as last run)"
    lines = [f"auto-weight: {st['n_videos']} clean videos, channel mean retention "
             f"{st['channel_mean_retention']}%, excluded {st['excluded_videos'] or 'none'}; "
             f"{verb} {rep['state_path']}",
             f"  {'cluster':<20}{'n':>3}{'conf':>6}{'ret%':>7}{'rel':>7}{'factor':>8}"
             f"{'prior':>14}{'share':>16}"]
    for c, s in st["clusters"].items():
        base_p, base_s = st["base_priors"][c], st["base_shares"].get(c)
        share = (f"{base_s:.3f}->{s['share']:.3f}" if base_s is not None else "-")
        lines.append(f"  {c:<20}{s['n']:>3}{s['confidence']:>6.2f}"
                     f"{s.get('mean_retention', float('nan')):>7.1f}"
                     f"{s.get('rel_retention', float('nan')):>7.3f}{s['factor']:>8.3f}"
                     f"{base_p:>7.3f}->{s['prior']:.3f}{share:>16}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="engine.v16_autoweight",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--history", default=None, help="topic_history.jsonl to read")
    ap.add_argument("--state", default=None, help="state file to write "
                    "(default: cluster_weight_state.json next to the history)")
    ap.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    a = ap.parse_args(argv)
    rep = run(history_path=a.history, state_path=a.state, dry_run=a.dry_run)
    print(json.dumps(rep, indent=1, default=str) if a.json else format_report(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main())
