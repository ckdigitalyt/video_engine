"""V16 — batch runner: preflight, topic selection, quota pause/resume,
per-video packaging (DESIGN.md §13, WP12).

    python3 -m engine.v16_batch --stories stories/a,stories/b --work build/v16/batches/<id>
    python3 -m engine.v16_batch --all --work ...
    python3 -m engine.v16_batch --n 5 [--series tunguska] --work ...   # topic-engine selection
    python3 -m engine.v16_batch --resume --work build/v16/batches/<id>

Stories run SEQUENTIALLY, same CPU-budget reasoning as `v15_batch.py`
(Remotion concurrency<=2 inside one render). `run_pipeline`'s own
content-hash caches (plan/plate/TTS/scene, `v14_cache.py`) make a resumed
batch cheap: re-running a story already done up to some point skips every
cached artifact.

**Lanes (DESIGN §13.3, "video k+1's S1-S7 overlaps video k's S8-S10 render
lock") are NOT implemented in this pass — flagged, not silently skipped.**
DESIGN §1.2's S0-S14 staged pipeline (one artifact + `.done` marker per
stage) does not exist yet: `v15_pipeline.run_pipeline` is one monolithic
function, and the stages that *are* split out as standalone modules
(`v16_research`/`v16_script`, S1-S4) are not wired into the live render
path (confirmed: `v15_pipeline.py` never imports either — same gap WP11's
report flagged). Splitting `run_pipeline` into stage-callables so a real
S1-S7/S8-S10 lock could exist is bigger than this WP's file scope
(`v16_batch.py` only) and risks destabilising a pipeline every prior WP's
render proof depends on. Batch stays sequential; `lanes_overlap` in the
report is always `False` so this is visible, not papered over.

**Quota pause/resume**: every LLM touchpoint inside `run_pipeline`
(`engine.director.text_ask`/`vision_ask`) deliberately CATCHES
`LLMUnavailable` and degrades to a cached/deterministic fallback — a
load-bearing reliability path per AGENTS.md, landed in WP1, never
raised out of `run_pipeline`. So the batch cannot "catch LLMUnavailable
from a video run" (it would never fire) — instead, before starting each
video, `_llm_blocked()` checks `llm.client.available(...)` for the
stages a real (non-degraded) render needs. A genuine quota outage (every
provider for every such stage in cooldown) pauses the batch *before* that
video would silently render in degraded-fallback mode, writes a resumable
checkpoint, prints `retry_at`, and the process exits 75. `--resume`
reloads the checkpoint and continues with whatever stories are still
pending — already-completed ones are not re-run.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # illustrated_engine
REPO = ROOT.parent                                  # video_engine
for _p in (REPO, ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

MAX_PER_CLUSTER = 2             # DESIGN §13.2
MIN_FREE_GB_PER_VIDEO = 2.0
LLM_STAGES = ("visual_plan", "plate_qa", "final_judge")  # every stage a
# real v15_pipeline render touches through the adapter (director.py's
# _STAGE_SCHEMAS + v15_plan.make_plan's default `ask`)


# =============================================================== preflight

def _voice_check() -> dict:
    from engine.voice import VoiceUnavailable, load_config, make_provider
    try:
        cfg = load_config()
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    vid = cfg["channel_voice"]
    vcfg = cfg["voices"][vid]
    try:
        make_provider(vid, cfg)
        ok, err = True, None
    except VoiceUnavailable as e:
        ok, err = False, str(e)
    return {"ok": ok, "error": err, "voice": vid, "provider": vcfg.get("provider"),
            "commercial_ok": bool(vcfg.get("commercial_ok")),
            "license_ref": vcfg.get("license_ref")}


def _llm_check() -> dict:
    from llm import client as llm
    return {stage: llm.available(stage) for stage in LLM_STAGES}


def _image_check() -> dict:
    from engine.v15_plates import image_chain_report
    return image_chain_report()


def _audio_library_check() -> dict:
    from engine.v16_audio import load_music_library, load_sfx_library
    try:
        music = load_music_library(REPO / "assets" / "music")
        sfx = load_sfx_library(REPO / "assets" / "sfx")
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    moods_with_tracks = sorted(m for m, tracks in music.items() if tracks)
    return {"ok": bool(moods_with_tracks) and bool(sfx), "moods": moods_with_tracks,
            "kinds": sorted(sfx)}


def _disk_check(work: Path, n_videos: int) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(work).free / 1e9
    need_gb = MIN_FREE_GB_PER_VIDEO * max(1, n_videos)
    return {"ok": free_gb >= need_gb, "free_gb": round(free_gb, 1), "need_gb": need_gb}


def preflight(work: Path, n_videos: int = 1) -> dict:
    """DESIGN §13.1: Claude CLI quota state, voice availability/clearance,
    image tiers, music/SFX libraries, disk space — no secrets printed
    (every check below reads booleans/paths/cooldown timestamps, never a
    key value). `ok` is False only when NO video in this batch could be
    produced at all (disk too low, or the configured voice has no working
    provider) — Cloudflare being down or the LLM stages being in cooldown
    are reported but are not hard-stops here, because `run_pipeline`
    already has a working fallback chain for both (AGENTS.md: don't treat
    a load-bearing fallback path as a failure)."""
    work = Path(work)
    checks = {
        "llm": _llm_check(),
        "voice": _voice_check(),
        "images": _image_check(),
        "audio_library": _audio_library_check(),
        "disk": _disk_check(work, n_videos),
    }
    ok = bool(checks["disk"]["ok"] and checks["voice"]["ok"])
    return {"ok": ok, "checks": checks}


# =========================================================== topic selection

def select_topics(n: int, *, series: str | None = None,
                  max_per_cluster: int = MAX_PER_CLUSTER,
                  history_path=None, ask=None) -> dict:
    """DESIGN §13.2: "the topic engine picks N distinct topics: <=2 per
    cluster unless --series." `engine.v16_topics.build_queue` ranks a
    queue but does not itself cap cluster concentration (that's a batch
    scheduling policy, not a scoring one) — enforced here, over its
    already-deduped/scored/ranked output. No new LLM calls beyond
    `build_queue`'s own (2 per call, DESIGN §2.5)."""
    from engine.v16_topics import DEFAULT_HISTORY_PATH, build_queue
    raw_n = max(n * 2, n + 5)  # headroom: dedupe/MIN_SCORE reject some (WP11: 20 raw -> 16 queued)
    result = build_queue(n=raw_n, history_path=history_path or DEFAULT_HISTORY_PATH, ask=ask)
    queue = result["queue"]

    def _cluster(entry):
        parts = entry["parts"] if "parts" in entry else [entry]
        return parts[0].get("cluster")

    if series:
        picked = [e for e in queue
                  if series in ([e.get("series_id")] +
                                [p.get("series_id") for p in e.get("parts", [])])]
        return {"picked": picked[:n], "queue": queue, "raw_count": result["raw_count"]}

    picked, per_cluster = [], {}
    for e in queue:
        c = _cluster(e)
        if per_cluster.get(c, 0) >= max_per_cluster:
            continue
        picked.append(e)
        per_cluster[c] = per_cluster.get(c, 0) + 1
        if len(picked) >= n:
            break
    return {"picked": picked, "queue": queue, "raw_count": result["raw_count"]}


# ============================================================ quota gating

def _llm_blocked(stages=LLM_STAGES) -> dict | None:
    """None if at least one provider for at least one stage could still be
    called; else `{"stages": [...], "retry_at": iso-str|None}` — the batch
    pause signal. See module docstring for why this gates BEFORE a video
    run rather than catching an exception from inside one."""
    from llm import client as llm
    if any(llm.available(s) for s in stages):
        return None
    try:
        cooldowns = json.loads((llm.build_dir() / "llm_state.json").read_text()
                               ).get("cooldown", {})
    except Exception:
        cooldowns = {}
    relevant = {p: t for p, t in cooldowns.items()}
    retry_at = min(relevant.values()) if relevant else None
    return {"stages": list(stages), "retry_at": retry_at}


# ================================================================ packaging

def _ffmpeg_cover(video: Path, out_png: Path, t: float = 0.8) -> bool:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-ss", f"{max(0.0, t):.3f}",
         "-i", str(video), "-frames:v", "1", str(out_png)], capture_output=True)
    return p.returncode == 0 and out_png.exists()


def _ffmpeg_proxy(video: Path, out_mp4: Path, width: int = 640) -> bool:
    p = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(video), "-vf",
         f"scale={width}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out_mp4)],
        capture_output=True)
    return p.returncode == 0 and out_mp4.exists()


def _metadata_txt(report: dict, story: dict) -> str:
    manifest = report.get("manifest") or {}
    disclosure = manifest.get("disclosure") or {}
    hook = next((b.get("narration", "") for b in story.get("beats", [])
                if b.get("function") == "HOOK"), "")
    scorecard = (report.get("gate") or {}).get("scorecard") or {}
    lines = [f"Title: {story.get('title', report.get('story_id', ''))}", "", hook, "",
            "--- Disclosure ---"]
    lines += [f"{k}: {v}" for k, v in disclosure.items()]
    if manifest.get("attribution_block"):
        lines += ["", "--- Attribution ---", manifest["attribution_block"]]
    lines += ["", f"Gate verdict: {report.get('publish_gate')}",
             f"Scorecard: {scorecard.get('total', 'n/a')}"]
    return "\n".join(lines) + "\n"


def package_video(story_dir: Path, work_dir: Path, out_dir: Path, *, report: dict) -> dict:
    """DESIGN §13.6: final.mp4, proxy.mp4, cover.png, metadata.txt,
    manifest.json, scorecard.json — the per-video package "Phase 5 posts
    to Discord". Pure post-processing on artifacts `run_pipeline` already
    wrote: no new LLM/image/voice call, so this never touches the owner's
    render-cap budget regardless of how many times it runs."""
    story_dir, work_dir, out_dir = Path(story_dir), Path(work_dir), Path(out_dir)
    final_src = work_dir / "final.mp4"
    if not final_src.exists():
        return {"ok": False, "error": "no final.mp4 (HOLD before render, or render failed)"}
    out_dir.mkdir(parents=True, exist_ok=True)
    final_dst = out_dir / "final.mp4"
    try:
        os.link(final_src, final_dst)
    except OSError:
        shutil.copyfile(final_src, final_dst)
    proxy_ok = _ffmpeg_proxy(final_src, out_dir / "proxy.mp4")
    cover_ok = _ffmpeg_cover(final_src, out_dir / "cover.png")
    manifest_src = work_dir / "manifest.json"
    if manifest_src.exists():
        shutil.copyfile(manifest_src, out_dir / "manifest.json")
    scorecard = (report.get("gate") or {}).get("scorecard")
    if scorecard:
        (out_dir / "scorecard.json").write_text(json.dumps(scorecard, indent=1))
    story = json.loads((story_dir / "story.json").read_text())
    (out_dir / "metadata.txt").write_text(_metadata_txt(report, story))
    return {"ok": True, "final": str(final_dst), "proxy": proxy_ok, "cover": cover_ok,
            "manifest": manifest_src.exists(), "scorecard": bool(scorecard)}


# ============================================================= batch runner

def _checkpoint_path(work: Path) -> Path:
    return Path(work) / "batch_state.json"


def run_batch(story_dirs: list, work: Path, *, resume: bool = False,
             package: bool = True, **kw) -> dict:
    """-> batch report dict, also written to `<work>/batch_report.json`
    after every video (so a kill mid-batch loses at most one in-flight
    video's row). A story that HOLDs or errors never stops the batch — it
    is recorded with its reasons, same as `v15_batch`. A genuine quota
    outage DOES stop the batch (see `_llm_blocked`): checkpoint saved,
    `paused: True`, `exit_code: 75`."""
    from engine.v15_pipeline import run_pipeline
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    cp = _checkpoint_path(work)
    if resume and cp.exists():
        state = json.loads(cp.read_text())
    else:
        state = {"batch_id": work.name, "pending": [str(Path(s)) for s in story_dirs],
                 "done": [], "rows": [],
                 "totals": {"llm_calls": 0, "image_calls": 0, "vision_calls": 0},
                 "started_at": time.time(), "lanes_overlap": False}
    t0 = time.time()
    use_llm = kw.get("use_llm", True)
    while state["pending"]:
        sd = Path(state["pending"][0])
        if use_llm:
            blocked = _llm_blocked()
            if blocked:
                cp.write_text(json.dumps(state, indent=1))
                return {**state, "wall_s": round(time.time() - t0, 1), "paused": True,
                       "retry_at": blocked["retry_at"], "blocked_stages": blocked["stages"],
                       "exit_code": 75}
        ts = time.time()
        row = {"story": sd.name}
        try:
            rep = run_pipeline(sd, work / sd.name, **kw)
            row.update(verdict=rep["publish_gate"], failures=rep["gate"]["failures"],
                      duration_s=rep["gate"]["checks"]["av"].get("duration_s"),
                      plan=rep["plan"]["source"], plates=rep.get("plate_providers"),
                      costs=rep["costs"], timings=rep["timings"],
                      scorecard=(rep["gate"].get("scorecard") or {}).get("total"),
                      distinctness_ok=rep["gate"]["checks"]["distinctness"]["ok"],
                      manifest_complete=rep["manifest"]["completeness"]["ok"])
            for k in state["totals"]:
                state["totals"][k] += rep["costs"].get(k, 0)
            if package:
                row["package"] = package_video(
                    sd, work / sd.name, work / sd.name / "package", report=rep)
        except Exception as e:  # never stop the batch on a per-story error
            row.update(verdict="ERROR", error=f"{type(e).__name__}: {e}"[:400],
                      trace=traceback.format_exc()[-1200:])
        row["wall_s"] = round(time.time() - ts, 1)
        state["rows"].append(row)
        state["done"].append(str(sd))
        state["pending"].pop(0)
        cp.write_text(json.dumps(state, indent=1))
        (work / "batch_report.json").write_text(json.dumps(
            {**state, "wall_s": round(time.time() - t0, 1)}, indent=1))
    return {**state, "wall_s": round(time.time() - t0, 1), "paused": False}


# ===================================================================== CLI

def main() -> int:
    ap = argparse.ArgumentParser(prog="engine.v16_batch")
    ap.add_argument("--stories", default="")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--n", type=int, default=0, help="auto-select N topics via the topic engine")
    ap.add_argument("--series", default=None)
    ap.add_argument("--work", required=True)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--no-package", action="store_true")
    a = ap.parse_args()
    work = Path(a.work)

    if a.n:
        sel = select_topics(a.n, series=a.series)
        print(f"topic engine selected {len(sel['picked'])}/{a.n} "
              f"({sel['raw_count']} raw candidates)")
        # DESIGN §13.2's selection step is real above; turning a freshly
        # ideated topic into a renderable `stories/<id>/story.json` needs
        # the research+script engine (WP4) wired live, which it is not
        # yet (module docstring / WP11's own report flag this gap) — so
        # auto-selected topics are reported/queued here, not rendered.
        work.mkdir(parents=True, exist_ok=True)
        (work / "topics_queued.json").write_text(json.dumps(sel, indent=1, default=str))
        if not a.stories and not a.all:
            print("no --stories/--all given: nothing renderable this run "
                 "(auto-selected topics are queued, not yet materialized "
                 "into story dirs) — see topics_queued.json")
            return 0

    pf = preflight(work, n_videos=max(a.n, 1))
    print(json.dumps(pf, indent=1, default=str))
    if not pf["ok"]:
        print("preflight: hard-stop (disk or voice unavailable)", file=sys.stderr)
        return 2

    if a.all:
        dirs = sorted(p.parent for p in (ROOT / "stories").glob("*/story.json"))
    else:
        dirs = [Path(s) for s in a.stories.split(",") if s.strip()]
    if not dirs and not a.resume:
        ap.error("no stories given (--stories/--all/--resume)")

    rep = run_batch(dirs, work, resume=a.resume, package=not a.no_package,
                    use_llm=not a.no_llm, use_judge=not a.no_judge)
    for r in rep["rows"]:
        print(f"{r['story']:<24} {r.get('verdict', '?'):<6} {r.get('wall_s', 0):>7.1f}s "
              f"score={r.get('scorecard')} "
              f"{'; '.join(sum((v[:1] for v in (r.get('failures') or {}).values()), []))[:80] or r.get('error', '')}")
    print(json.dumps(rep.get("totals"), default=str))
    if rep.get("paused"):
        print(f"PAUSED: quota exhausted on {rep.get('blocked_stages')}, "
             f"retry_at={rep.get('retry_at')} — re-run with --resume", file=sys.stderr)
        return 75
    return 0 if all(r.get("verdict") == "PASS" for r in rep["rows"]) else 1


if __name__ == "__main__":
    sys.exit(main())
