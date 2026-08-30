"""run.py — Full v3 pipeline runner (Wave 3).

    venv/bin/python -m engine.v3.run --topic "..." --out results/<id> \
        [--dev] [--max-shots N] [--aspect 16:9|9:16] [--force-fail S07] \
        [--budget-file budget.json] [--research research.json] \
        [--shots N-procedural] [--no-vision] [--recap]

topic → research → script → shot plan (v4 two-stage §5 hierarchy by
    default: narrative → perception → cinematography → motion → renderer
    LAST, with class-mix reconciliation, pattern interrupts,
    show-don't-label and micro-event timelines; --planner v3 for legacy)
    → per-shot render → shot QA → selective regen → assembly → audio master
    → full-video QA → §19 publish gate (artifact-measured v4 gates) →
    (§21 re-edit / retention/variety recut loop, max 2 iterations).

Analysis mode (no rendering, no LLM):
    venv/bin/python -m engine.v3.run --analyze results/<id>
    runs the §19 publish gate against the existing master, measuring the
    actual artifact via tools/v4_audit.py; writes
    publish_gate_v4_analysis.json next to it (exit 1 on FAIL).

Deterministic caching at every stage boundary (research.json, script.json,
shotlist.json, shots/, qa/, master.mp4, publish_gate.json); a resumed run
skips completed stages via results/<id>/state.json.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from engine.v3.assemble.assembler import (  # noqa: E402
    assemble_master,
    reframe_916,
)
from engine.v3.plan.planner import plan_shots  # noqa: E402
from engine.v4.planner import plan_shots_v4  # noqa: E402
from engine.v4.reedit import apply_reedit, plan_reedit  # noqa: E402
from engine.v3.plan.style import author_style  # noqa: E402
from engine.v3.qa.shot_qa import qa_shotlist  # noqa: E402
from engine.v3.qa.video_qa import publish_gate  # noqa: E402
from engine.v3.render.runner import (  # noqa: E402
    DEV_MODE,
    FULL_MODE,
    mode_availability,
    render_shot,
)
from engine.v3.repair.regen import selective_regen  # noqa: E402
from engine.v3.story import research as research_mod  # noqa: E402
from engine.v3.story.script import write_script  # noqa: E402
from engine.v3.story.structure import structure_story  # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("engine.v3.run")

RESOLUTIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
DEV_RESOLUTIONS = {"16:9": (960, 540), "9:16": (540, 960)}
MAX_RECUT_ITERATIONS = 2

# Renderers the v3 pipeline never plans as a primary choice (§3 target
# set): legacy adapters and unimplemented specialists stay out of the
# router's way while remaining registered.
ALWAYS_OFF = ("MEDIA", "VECTOR", "GODOT", "OPEN_TOONZ")


# ── Stage state (resumable) ──────────────────────────────────────────────────

class StageState:
    def __init__(self, out_dir: Path) -> None:
        self.path = out_dir / "state.json"
        self.state: dict = {"stages": {}}
        if self.path.exists():
            try:
                self.state = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass

    def done(self, stage: str, artifact: Path | None = None) -> bool:
        info = self.state["stages"].get(stage)
        if not info:
            return False
        if artifact is not None and not artifact.exists():
            return False
        return bool(info.get("done"))

    def mark(self, stage: str, **kw) -> None:
        self.state["stages"][stage] = {"done": True, "ts": time.time(), **kw}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, indent=2),
                             encoding="utf-8")


# ── Pipeline ─────────────────────────────────────────────────────────────────

def run(args: argparse.Namespace) -> int:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env", override=True)

    # §19 analysis mode: gate an EXISTING artifact, render nothing.
    if args.analyze:
        return analyze_artifact(args)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state = StageState(out_dir)
    mode = DEV_MODE if args.dev else FULL_MODE
    width, height = (DEV_RESOLUTIONS if args.dev else
                     RESOLUTIONS).get(args.aspect, RESOLUTIONS["16:9"])
    t0 = time.time()

    def log(stage: str, msg: str) -> None:
        logger.info("[%s] %s", stage, msg)

    # ── Stage: research ──────────────────────────────────────────────────
    research_path = Path(args.research) if args.research \
        else out_dir / "research.json"
    if research_path.exists():
        research = research_mod.load_research(research_path)
        log("research", f"loaded existing doc ({research.get('provenance')})")
    else:
        research = research_mod.build_research(
            args.topic, research_path, use_llm=not args.offline)
        log("research", f"{len(research['claims'])} claims "
                        f"({research.get('provenance')})")
    if args.stop_after == "research":
        log("stop", "--stop-after research: halting before script stage")
        return 0

    # ── Stage: script ────────────────────────────────────────────────────
    script_path = out_dir / "script.json"
    if state.done("script", script_path):
        script_doc = json.loads(script_path.read_text(encoding="utf-8"))
    else:
        structure = structure_story(research, use_llm=not args.offline)
        script_doc = write_script(structure, research,
                                  use_llm=not args.offline,
                                  max_shots=args.max_shots)
        script_path.write_text(json.dumps(script_doc, indent=2),
                               encoding="utf-8")
        state.mark("script", beats=len(script_doc["beats"]))
    log("script", f"{len(script_doc['beats'])} beats, "
                  f"~{script_doc['est_total_sec']}s "
                  f"({script_doc.get('provenance')})")
    if args.stop_after == "script":
        log("stop", "--stop-after script: halting before plan stage")
        return 0

    # ── Stage: style ─────────────────────────────────────────────────────
    style_path = out_dir / "style.json"
    style = author_style(args.topic, style_path, use_llm=not args.offline)
    log("style", style.get("style_name", "?"))

    # ── Stage: plan ──────────────────────────────────────────────────────
    plan_path = out_dir / "shotlist.json"
    budget = _load_budget(args.budget_file)
    availability = mode_availability(
        mode,
        offline_renderers=args.offline_renderers.split(",") if
        args.offline_renderers else None)
    for rid in ALWAYS_OFF:
        availability[rid] = False
    log("plan", f"mode={mode} availability_off="
                f"{sorted(k for k, v in availability.items() if not v)}")

    def build_plan() -> dict:
        if args.planner == "v4":
            # V4 two-stage §5 hierarchy: narrative → perception →
            # cinematography → motion → renderer LAST, then class-mix
            # reconciliation (§12), pattern interrupts (§14),
            # show-don't-label post-check (§13/§24) and micro-event
            # timelines (§4) — all inside plan_shots_v4.
            plan = plan_shots_v4(script_doc, style, budget=budget or None,
                                 availability=availability,
                                 use_llm=not args.offline,
                                 max_shots=args.max_shots)
        else:
            plan = plan_shots(script_doc, style, budget=budget,
                              availability=availability,
                              use_llm=not args.offline,
                              max_shots=args.max_shots)
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return plan

    if state.done("plan", plan_path):
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        plan = build_plan()
        state.mark("plan")
    shots = plan["shots"]
    mix = plan["variety_report"]["renderer_histogram"]
    planner_src = ((plan.get("planning_hierarchy") or {}).get("stage_a") or {}
                   ).get("source", "v3")
    log("plan", f"{len(shots)} shots, planner={args.planner} "
                f"stage_a={planner_src}, mix={mix}")
    label_issues = (plan.get("label_check") or {}).get("issues") or []
    if label_issues:
        log("plan", f"show-don't-label: {len(label_issues)} residual "
                    f"issue(s): {label_issues[:3]}")
    if args.stop_after == "plan":
        log("stop", "--stop-after plan: halting before render stage")
        return 0

    # ── Render/QA/repair loop (recut iterations share this machinery) ────
    force_fail = set(args.force_fail or [])
    qa_dir = out_dir / "qa" / "shots"

    def available_fn(rid: str) -> bool:
        return availability.get(rid, True) and rid != "MANIM"  # no authored VisualSpec

    def do_render(shot: dict, vdir: Path, attempt: int = 0,
                  renderer_override: str | None = None,
                  duration_override: float | None = None) -> dict:
        s = dict(shot)
        if duration_override:
            s = {**shot, "duration_sec": round(duration_override, 2)}
        return render_shot(
            s, style, vdir, fps=30, resolution=(width, height),
            aspect=args.aspect, attempt=attempt,
            renderer_override=renderer_override, available=available_fn)

    def rerender_for_timing(shot: dict, new_duration: float) -> dict:
        rec = do_render(shot, out_dir / "shots" / "timing", attempt=1,
                        duration_override=new_duration)
        return rec

    iteration = 0
    gate: dict | None = None
    records: dict[str, dict] = {}
    reports: dict[str, dict] = {}
    master: Path | None = None

    while True:
        version_tag = f"v1" if iteration == 0 else f"r{iteration}"
        shots_root = out_dir / "shots"

        # ── Stage: render ────────────────────────────────────────────────
        render_state_key = f"render_{version_tag}"
        records_path = out_dir / f"render_records_{version_tag}.json"
        if state.done(render_state_key, records_path):
            records = {k: v for k, v in
                       json.loads(records_path.read_text(
                           encoding="utf-8")).items()}
            log("render", f"resumed {len(records)} records")
        else:
            records = {}
            for shot in shots:
                rec = do_render(shot, shots_root / "v1")
                records[shot["shot_id"]] = rec
                ok = "OK " if rec.get("ok") else "FAIL"
                logger.info("  %s %s via %s",
                            shot["shot_id"], ok,
                            rec.get("renderer_used") or
                            str(rec.get("attempts", [])[-1:]))
            records_path.write_text(
                json.dumps(records, indent=2, default=str),
                encoding="utf-8")
            state.mark(render_state_key)
        ok_n = sum(1 for r in records.values() if r.get("ok"))
        log("render", f"{ok_n}/{len(shots)} shots rendered")

        # ── Stage: shot QA ───────────────────────────────────────────────
        reports = qa_shotlist(
            shots, records, qa_dir, use_vision=not args.no_vision,
            min_height=height // 2, force_fail=False,
            cache=not args.no_qa_cache)
        avg = (sum(r.get("score", 0) for r in reports.values())
               / max(len(reports), 1))
        log("shot_qa", f"avg score {avg:.0f}; "
                       f"{sum(1 for r in reports.values() if r.get('action') == 'regenerate')} flagged")

        # ── Stage: selective regen (§22 — every iteration) ──────────
        regen = selective_regen(
            shots, records, reports, render_fn=do_render,
            qa_dir=qa_dir, shots_root=shots_root, max_retries=1,
            force_fail=force_fail if iteration == 0 else set(),
            use_vision=not args.no_vision)
        records, reports = regen["records"], regen["reports"]
        (out_dir / f"regen_log_{version_tag}.json").write_text(
            json.dumps(regen, indent=2, default=str), encoding="utf-8")
        log("repair", f"regenerated={regen['regenerated']} "
                      f"rerouted={regen['rerouted']}")
        records_path.write_text(
            json.dumps(records, indent=2, default=str), encoding="utf-8")

        # ── Stage: assemble ──────────────────────────────────────────────
        master_name = "master.mp4" if iteration == 0 else f"master_r{iteration}.mp4"
        master = out_dir / master_name
        timing_adjustments = []
        if not (state.done(f"assemble_{version_tag}", master)):
            assembled = assemble_master(
                plan.get("topic", args.topic), shots, script_doc, records,
                out_dir, width=width, height=height, fps=30,
                audio_master=not args.silent,
                rerender_fn=rerender_for_timing)
            timing_adjustments = assembled.get("timing_adjustments", [])
            # assemble_master writes out_dir/master.mp4 — rename for recuts.
            if iteration > 0:
                (out_dir / "master.mp4").replace(master)
            state.mark(f"assemble_{version_tag}",
                       duration=assembled.get("video_duration"),
                       timing=timing_adjustments)
        else:
            timing_adjustments = (state.state["stages"].get(
                f"assemble_{version_tag}", {}).get("timing") or [])
        log("assemble", f"{master.name} "
                        f"({master.stat().st_size // 1024} KB)")

        # Align the plan to the FINAL timeline (actual TTS durations) so
        # the temporal/retention gates judge the real video, not word-count
        # estimates.
        final_durs = {a["shot_id"]: a["final"]
                      for a in timing_adjustments if "shot_id" in a}
        for s in shots:
            if s["shot_id"] in final_durs:
                s["duration_sec"] = final_durs[s["shot_id"]]

        # ── Stage: full-video QA / publish gate ──────────────────────────
        gate_path = out_dir / ("publish_gate.json" if iteration == 0
                               else f"publish_gate_r{iteration}.json")
        gate = publish_gate(
            master, shots, script_doc, research, style, reports, gate_path,
            use_vision=not args.no_vision, use_llm=not args.offline,
            require_audio=not args.silent,
            expected_width=width, expected_height=height,
            records=records)
        log("gate", f"{gate['overall']} failed={gate['failed_gates']}")

        failed = gate["failed_gates"]
        retention_or_variety = {"RETENTION", "VARIETY"} & set(failed)

        # ── §21 re-edit-first repair: the creative critic's
        # recommended_cuts become re-edit operations (trim → shorten →
        # rearrange → replace) on the shotlist/timeline BEFORE any
        # regeneration is considered. apply_reedit mechanically demotes
        # regenerate requests to trim/replace on static/slideshow shots.
        critic = gate.get("critic") or {}
        reedit_ops = plan_reedit(critic, shots) \
            if critic.get("recommended_cuts") else []

        if iteration >= MAX_RECUT_ITERATIONS or \
                (not retention_or_variety and not reedit_ops):
            break

        # ── Recut loop: revise the shot PLAN (§21/§22), rebuild affected
        # shots, reassemble. Max 2 iterations.
        iteration += 1
        log("recut", f"iteration {iteration}: "
                     + "; ".join(filter(None, [
                         f"retention/variety failed" if retention_or_variety
                         else "",
                         f"{len(reedit_ops)} §21 re-edit op(s)" if reedit_ops
                         else ""])))

        reedit_log = None
        if reedit_ops:
            # The heuristic critic emits one cut per measured hold and
            # master-level cuts collapse onto the same longest shot — apply
            # the strongest op per (shot, action) once per iteration.
            seen: set[tuple[str, str]] = set()
            unique: list[dict] = []
            for op in reedit_ops:
                key = (str(op.get("shot_id")), str(op.get("action")))
                if key not in seen:
                    seen.add(key)
                    unique.append(op)
            reedit_ops = unique
            shots, applied, skipped = apply_reedit(shots, reedit_ops)
            if applied:
                reedit_log = {"ops": reedit_ops, "applied": applied,
                              "skipped": skipped}
                log("reedit", f"{len(applied)} op(s) applied, "
                              f"{len(skipped)} skipped: "
                              + ", ".join(f"{a['shot_id']}:{a['action']}"
                                          for a in applied[:6]))
            plan["shots"] = shots

        if retention_or_variety:
            fixes = []
            for g in ("RETENTION", "VARIETY"):
                if not gate["gates"][g]["pass"]:
                    fixes += gate["gates"][g].get("fixes", [])
            plan = _recut_plan(plan, fixes, availability)
            shots = plan["shots"]

        if reedit_log:
            plan["reedit"] = reedit_log
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        if not reedit_log and not retention_or_variety:
            break  # every re-edit op was a no-op — don't loop forever

    # ── Optional 9:16 reframe (16:9 master is always untouched) ──────────
    if args.aspect == "16:9" and not args.no_reframe and master and \
            gate and gate["overall"] == "PASS":
        try:
            shorts = out_dir / "master_916.mp4"
            if not shorts.exists():
                reframe_916(master, shorts)
            log("reframe", "9:16 reframed copy written")
        except Exception as exc:  # noqa: BLE001 — optional pass
            log("reframe", f"skipped: {exc}")

    elapsed = time.time() - t0
    summary = {
        "topic": args.topic, "mode": mode,
        "elapsed_sec": round(elapsed, 1),
        "master": str(master), "gate_overall": gate and gate["overall"],
        "renderer_mix": plan["variety_report"]["renderer_histogram"],
        "failed_gates": gate and gate["failed_gates"],
    }
    (out_dir / "run_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    log("done", json.dumps(summary))
    return 0


def _load_budget(path: str | None) -> dict:
    if not path:
        return {}
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── §19 analysis mode ────────────────────────────────────────────────────────

def analyze_artifact(args: argparse.Namespace) -> int:
    """Run the §19 publish gate in analysis mode against an existing video
    directory (no rendering, no LLM).

    The gates measure THE ARTIFACT — the exact file probed via ffprobe and
    decoded pixels (tools/v4_audit.py) is recorded in the report under
    ``artifact.path``. Writes publish_gate_v4_analysis.json next to the
    master and prints per-gate verdicts. Exit code 1 on FAIL (CI-usable).
    """
    from engine.v4.gates import run_v4_gates

    art = Path(args.analyze)
    if art.is_dir():
        out_dir = art
        master = art / "master.mp4"
        if not master.exists():
            candidates = sorted(p for p in art.glob("*.mp4"))
            if not candidates:
                logger.error("--analyze: no master.mp4 (or any *.mp4) in %s",
                             art)
                return 2
            master = candidates[0]
    else:
        master = art
        out_dir = art.parent
    if not master.exists():
        logger.error("--analyze: artifact not found: %s", master)
        return 2

    # Best-effort context: the plan the artifact was built from (its
    # renderer mix / cinematography fields feed SHOT_DIVERSITY and
    # CINEMATIC) and the render records (AI_VIDEO_COVERAGE chain evidence).
    shots: list[dict] = []
    shotlist_path = out_dir / "shotlist.json"
    if shotlist_path.exists():
        try:
            shots = json.loads(shotlist_path.read_text(
                encoding="utf-8")).get("shots", []) or []
        except json.JSONDecodeError:
            logger.warning("--analyze: unparseable shotlist.json — "
                           "plan-derived gates run planless")

    render_records: list[dict] = []
    for name in ("render_records_v1.json", "render_records.json"):
        rp = out_dir / name
        if rp.exists():
            try:
                raw = json.loads(rp.read_text(encoding="utf-8"))
                by_id = {s.get("shot_id"): s for s in shots}
                for r in raw.values():
                    planned = (by_id.get(r.get("shot_id")) or {}).get(
                        "renderer")
                    render_records.append({**r,
                                           "renderer": r.get("renderer_used"),
                                           "planned_renderer": planned})
                break
            except json.JSONDecodeError:
                pass

    # Declared spec: assembled duration from state.json when present,
    # otherwise the gate ffprobes the file and judges metadata consistency
    # against the pipeline defaults.
    expected = {"codec": "h264", "width": 1920, "height": 1080, "fps": 30}
    state_path = out_dir / "state.json"
    if state_path.exists():
        try:
            st = json.loads(state_path.read_text(encoding="utf-8"))
            dur = (st.get("stages", {}).get("assemble_v1", {})
                   or {}).get("duration")
            if dur:
                expected["duration_sec"] = round(float(dur), 2)
        except (json.JSONDecodeError, ValueError):
            pass

    doc = run_v4_gates(master, shots=shots, render_records=render_records,
                       expected_spec=expected, analysis_mode=True)

    out_path = out_dir / "publish_gate_v4_analysis.json"
    out_path.write_text(json.dumps(doc, indent=2, default=str),
                        encoding="utf-8")

    logger.info("=== §19 publish gate (analysis mode) — %s ===",
                doc["artifact"]["path"])
    for name, g in doc["gates"].items():
        logger.info("  %-9s %-20s %s", "PASS" if g["pass"] else "FAIL",
                    name, g["detail"])
        for fix in g.get("fixes", [])[:3]:
            logger.info("            ↳ %s", fix)
    logger.info("OVERALL: %s (failed: %s) — report: %s",
                doc["overall"], ", ".join(doc["failed_gates"]) or "none",
                out_path)
    return 0 if doc["overall"] == "PASS" else 1


def _recut_plan(plan: dict, fixes: list[str],
                availability: dict[str, bool]) -> dict:
    """Revise the shot plan (not the script) after a RETENTION/VARIETY
    failure: re-run the variety enforcement with interrupts forced, and
    alternate compositions deterministically on the lowest-scored shots."""
    from engine.v3.plan.variety import enforce_variety

    shots = plan["shots"]
    # Diversify compositions on the tail shots (deterministic alternation).
    alternates = ["wide establishing", "close-up detail", "overhead graphic",
                  "medium shot", "silhouette wide"]
    for i, s in enumerate(shots):
        if s.get("generation_priority") == "hero":
            continue
        s["composition"] = alternates[i % len(alternates)]
    shots, changes, report = enforce_variety(
        shots, availability=availability, protect_hero=True)
    plan["shots"] = shots
    plan["variety_report"] = report
    plan.setdefault("planner_notes", {})[f"recut_fixes"] = fixes[:10]
    return plan


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="engine.v3.run",
                                description="Jade v3 full pipeline runner")
    p.add_argument("--topic", default=None)
    p.add_argument("--out", default=None, help="results/<video_id>")
    p.add_argument("--analyze", default=None, metavar="ARTIFACT",
                   help="§19 analysis mode: gate an existing video file or "
                        "results directory (no rendering); writes "
                        "publish_gate_v4_analysis.json")
    p.add_argument("--stop-after", default=None,
                   choices=["research", "script", "plan"],
                   help="run the pipeline only up to the named stage and "
                        "exit 0 (resumable — later invocations continue)")
    p.add_argument("--planner", default="v4", choices=["v4", "v3"],
                   help="shot planner: v4 = two-stage §5 hierarchy "
                        "(default), v3 = legacy planner")
    p.add_argument("--dev", action="store_true",
                   help="offline providers only, tiny render")
    p.add_argument("--offline", action="store_true",
                   help="disable LLM calls (story/plan/critics)")
    p.add_argument("--max-shots", type=int, default=None)
    p.add_argument("--aspect", default="16:9", choices=["16:9", "9:16"])
    p.add_argument("--force-fail", action="append", default=[],
                   help="force shot QA failure (dev flag), e.g. S07")
    p.add_argument("--budget-file", default=None,
                   help="visual_budget_v1 JSON override")
    p.add_argument("--research", default=None,
                   help="pre-seeded research.json path")
    p.add_argument("--offline-renderers", default=None,
                   help="comma-separated renderer ids to disable (full mode)")
    p.add_argument("--no-vision", action="store_true",
                   help="skip vision QA (technical-only scoring)")
    p.add_argument("--no-qa-cache", action="store_true")
    p.add_argument("--silent", action="store_true",
                   help="skip narration/music (video-only master)")
    p.add_argument("--no-reframe", action="store_true",
                   help="skip the optional 9:16 reframe pass")
    args = p.parse_args(argv)
    if not args.analyze:
        if not args.topic or not args.out:
            p.error("--topic and --out are required unless --analyze is used")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
