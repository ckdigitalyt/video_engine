"""run.py — Full v3 pipeline runner (Wave 3).

    venv/bin/python -m engine.v3.run --topic "..." --out results/<id> \
        [--dev] [--max-shots N] [--aspect 16:9|9:16] [--force-fail S07] \
        [--budget-file budget.json] [--research research.json] \
        [--shots N-procedural] [--no-vision] [--recap]

topic → research → script → shot plan → per-shot render → shot QA →
selective regen → assembly → audio master → full-video QA → publish gate
→ (retention/variety recut loop, max 2 iterations).

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
    log("plan", f"mode={mode} availability_off="
                f"{sorted(k for k, v in availability.items() if not v)}")

    def build_plan() -> dict:
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
    log("plan", f"{len(shots)} shots, mix={mix}")

    # ── Render/QA/repair loop (recut iterations share this machinery) ────
    force_fail = set(args.force_fail or [])
    qa_dir = out_dir / "qa" / "shots"

    def available_fn(rid: str) -> bool:
        return availability.get(rid, True) and rid != "MANIM"

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

        # ── Stage: selective regen ───────────────────────────────────────
        if iteration == 0:
            regen = selective_regen(
                shots, records, reports, render_fn=do_render,
                qa_dir=qa_dir, shots_root=shots_root, max_retries=1,
                force_fail=force_fail, use_vision=not args.no_vision)
            records, reports = regen["records"], regen["reports"]
            (out_dir / "regen_log.json").write_text(
                json.dumps(regen, indent=2, default=str), encoding="utf-8")
            log("repair", f"regenerated={regen['regenerated']} "
                          f"rerouted={regen['rerouted']}")
            # Persist regen results into the v1 records.
            records_path.write_text(
                json.dumps(records, indent=2, default=str),
                encoding="utf-8")

        # ── Stage: assemble ──────────────────────────────────────────────
        master_name = "master.mp4" if iteration == 0 else f"master_r{iteration}.mp4"
        master = out_dir / master_name
        if not (state.done(f"assemble_{version_tag}", master)):
            assembled = assemble_master(
                plan.get("topic", args.topic), shots, script_doc, records,
                out_dir, width=width, height=height, fps=30,
                audio_master=not args.silent,
                rerender_fn=rerender_for_timing)
            # assemble_master writes out_dir/master.mp4 — rename for recuts.
            if iteration > 0:
                (out_dir / "master.mp4").replace(master)
            state.mark(f"assemble_{version_tag}",
                       duration=assembled.get("video_duration"))
        log("assemble", f"{master.name} "
                        f"({master.stat().st_size // 1024} KB)")

        # ── Stage: full-video QA / publish gate ──────────────────────────
        gate_path = out_dir / ("publish_gate.json" if iteration == 0
                               else f"publish_gate_r{iteration}.json")
        gate = publish_gate(
            master, shots, script_doc, research, style, reports, gate_path,
            use_vision=not args.no_vision, use_llm=not args.offline,
            require_audio=not args.silent)
        log("gate", f"{gate['overall']} failed={gate['failed_gates']}")

        failed = gate["failed_gates"]
        retention_or_variety = {"RETENTION", "VARIETY"} & set(failed)
        if not retention_or_variety or iteration >= MAX_RECUT_ITERATIONS:
            break

        # ── Recut loop: revise the shot PLAN only (§22), rebuild affected
        # shots, reassemble. Max 2 iterations.
        iteration += 1
        log("recut", f"iteration {iteration}: revising shot plan "
                     f"(retention/variety failed)")
        fixes = []
        for g in ("RETENTION", "VARIETY"):
            if not gate["gates"][g]["pass"]:
                fixes += gate["gates"][g].get("fixes", [])
        plan = _recut_plan(plan, fixes, availability)
        shots = plan["shots"]
        plan_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

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
    p.add_argument("--topic", required=True)
    p.add_argument("--out", required=True, help="results/<video_id>")
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
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
