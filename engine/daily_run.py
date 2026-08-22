"""Daily autonomous mode (JADE v0.3 §35–37).

Production command:

    python -m engine.daily_run --topic "Why is the sky blue?"
    python -m engine.daily_run                     # scout picks the topic

Flow (no manual storyboard anywhere):

    choose topic (§24–25 scout)
    -> research (§16 deterministic knowledge)
    -> plan (world -> representation -> story -> hero -> VisualSpec)
    -> PREFLIGHT QA (§28/§37 — a bad plan is rejected BEFORE any
       expensive render; this is the §37 budget rule)
    -> local repair if needed (§30, max iterations)
    -> classify §36 failure policy (PASS / REPAIR / REGENERATE / ABORT)
    -> render + full QA (only when the plan passed preflight)
    -> finalize into results/YYYY-MM-DD/topic_slug/ with all artifacts

The daily system can reject its own bad work (§36): it never forces
publication of a poor output, and it never spends render budget on a
plan that cannot pass planning-level QA (§37).
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from engine.benchmark.suite import REGRESSION_TOPICS
from engine.benchmark.unseen_eval import UNSEEN_TOPICS
from engine.qa.critic import critique_preview
from engine.qa.gates import run_preflight_v2
from engine.qa.repair import (
    ABORT, PASS, REGENERATE, REPAIR, apply_repair, classify_outcome,
)
from engine.scout.topic_scout import (
    TopicCandidate, default_scores, record_topic, select_daily_topic,
)
from engine.world.knowledge import build_world, research
from engine.world.representations import select_representation
from engine.world.story_templates import select_template
from engine.visuals.world_director import build_visualspec

# §37 budget: never render before the plan passes preflight
MAX_REPAIR_ITERATIONS = 3


@dataclass
class DailyResult:
    topic: str
    slug: str
    outcome: str = ABORT
    outcome_reason: str = ""
    qa_passed: bool = False
    qa_score: int = 0
    perceptual_quality: int = 0
    preflight_passed: bool = False
    repair_iterations: int = 0
    artifacts_dir: str = ""
    video: str = ""
    errors: list[str] = field(default_factory=list)
    runtime_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "slug": self.slug,
            "outcome": self.outcome,            # §36 PASS/REPAIR/REGENERATE/ABORT
            "outcome_reason": self.outcome_reason,
            "qa_passed": self.qa_passed,
            "qa_score": self.qa_score,
            "perceptual_quality": self.perceptual_quality,
            "preflight_passed": self.preflight_passed,
            "repair_iterations": self.repair_iterations,
            "artifacts_dir": self.artifacts_dir,
            "video": self.video,
            "errors": list(self.errors),
            "runtime_s": round(self.runtime_s, 1),
        }


def _slugify(topic: str) -> str:
    import re
    s = re.sub(r"[^a-z0-9]+", "_", topic.lower()).strip("_")
    return s[:48] or "topic"


def _default_candidates() -> list[TopicCandidate]:
    """Candidate pool: regression + unseen topics, scored §24."""
    out: list[TopicCandidate] = []
    for topic, _slug in list(REGRESSION_TOPICS) + list(UNSEEN_TOPICS):
        out.append(TopicCandidate(topic=topic, category="science",
                                  scores=default_scores(topic)))
    return out


def _plan(topic: str) -> tuple[dict, dict]:
    """Deterministic plan: world + representation + story + VisualSpec."""
    world = build_world(topic)
    rep = select_representation(topic)
    plan = select_template(topic, rep.primary)
    vs = build_visualspec(topic, world, story_plan=plan)
    return vs, {"world": world, "rep": rep, "plan": plan}


def run_daily(topic: Optional[str] = None,
              out_root: Optional[str | Path] = None,
              render: bool = False,
              resolution: tuple[int, int] = (1280, 720),
              fps: int = 30,
              candidates: Optional[list[TopicCandidate]] = None,
              history_base: Optional[Path] = None) -> DailyResult:
    """One daily production run (§35).  Returns the §36 outcome."""
    t0 = time.time()
    # ── 1) choose topic (§24–25) ─────────────────────────────────────
    if topic is None:
        pool = candidates if candidates is not None else _default_candidates()
        chosen = select_daily_topic(pool, base=history_base)
        topic = chosen.topic
        if not topic:
            return DailyResult(topic="", slug="", outcome=ABORT,
                               outcome_reason="no candidate topics",
                               runtime_s=time.time() - t0)
    slug = _slugify(topic)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = Path(out_root) if out_root else Path("results") / day / slug
    out.mkdir(parents=True, exist_ok=True)
    result = DailyResult(topic=topic, slug=slug, artifacts_dir=str(out))

    try:
        # ── 2) research + plan ───────────────────────────────────────
        research_result = research(topic)
        (out / "research.json").write_text(json.dumps({
            "topic": topic,
            "summary": research_result.summary,
            "facts": [f.__dict__ for f in research_result.facts],
            "sources": research_result.sources,
        }, indent=2))
        vs, ctx = _plan(topic)
        (out / "visualspec.json").write_text(json.dumps(vs, indent=2))
        (out / "story_plan.json").write_text(json.dumps({
            "template": ctx["plan"].template_name,
            "rationale": ctx["plan"].rationale,
            "representation": ctx["rep"].primary.value,
        }, indent=2))

        # ── 3) PREFLIGHT (§28/§37): reject bad plans before rendering ─
        preflight = run_preflight_v2(vs)
        result.preflight_passed = bool(preflight.get("passed"))
        result.perceptual_quality = int(preflight.get("perceptual_quality", 0))
        result.qa_score = int(preflight.get("score", 0))
        (out / "qa_preflight.json").write_text(
            json.dumps(preflight, indent=2))

        # ── 4) local repair loop (§30/§36) ───────────────────────────
        if not result.preflight_passed:
            crit = critique_preview(vs)
            rp = apply_repair(vs, crit, max_iterations=MAX_REPAIR_ITERATIONS)
            result.repair_iterations = rp.iterations
            (out / "repair_plan.json").write_text(
                json.dumps(rp.to_dict(), indent=2))
            preflight2 = run_preflight_v2(vs)
            result.preflight_passed = bool(preflight2.get("passed"))
            result.perceptual_quality = int(
                preflight2.get("perceptual_quality", 0))
            result.qa_score = int(preflight2.get("score", 0))
            (out / "qa_preflight.json").write_text(
                json.dumps(preflight2, indent=2))
            (out / "visualspec.json").write_text(json.dumps(vs, indent=2))

        # ── 5) §36 classification ────────────────────────────────────
        if result.preflight_passed:
            result.outcome = PASS
            result.outcome_reason = "plan passed preflight QA"
        else:
            crit_final = critique_preview(vs)
            result.outcome = classify_outcome(
                crit_final, qa_passed=False,
                fact_verified=bool(research_result.facts)
                or not _fact_checkable(topic))
            if result.outcome == PASS:      # never publish a failed plan
                result.outcome = REGENERATE
            result.outcome_reason = (
                f"preflight failed after {result.repair_iterations} "
                f"repair iterations; perceptual "
                f"{result.perceptual_quality}")

        # ── 6) render ONLY when the plan passed (§37 budget) ─────────
        if result.outcome == PASS and render:
            from engine.cli.autonomous import run_autonomous
            report = run_autonomous(topic, out, resolution=resolution,
                                    fps=fps, render=True, visualspec=vs)
            result.qa_passed = bool(report.get("passed"))
            result.qa_score = int(report.get("score", 0) or 0)
            result.video = str(report.get("video", ""))
            (out / "qa.json").write_text(json.dumps(report, indent=2))
            if not result.qa_passed:
                result.outcome = REPAIR
                result.outcome_reason = (
                    "rendered output failed full QA — repair needed "
                    "(not published)")
                for e in report.get("errors", [])[:5]:
                    result.errors.append(str(e))

        # ── 7) learning + history (§25, §31) ─────────────────────────
        try:
            record_topic(topic, "science", base=history_base)
        except Exception:  # noqa: BLE001
            pass
        from engine.learning.memory import distill_learning
        try:
            rec = distill_learning(topic, {
                "passed": result.qa_passed or result.outcome == PASS,
                "perceptual_quality": result.perceptual_quality,
                "outcome": result.outcome,
            }, {"problem": result.outcome_reason})
            (out / "learning.json").write_text(
                json.dumps(rec.to_dict(), indent=2))
        except Exception:  # noqa: BLE001
            (out / "learning.json").write_text(json.dumps(
                {"status": "not_run"}, indent=2))

        # ── 8) daily summary artifact ────────────────────────────────
        result.runtime_s = time.time() - t0
        (out / "daily_report.json").write_text(
            json.dumps(result.to_dict(), indent=2))
    except Exception as e:  # noqa: BLE001
        result.outcome = ABORT
        result.outcome_reason = f"pipeline exception: {e}"
        result.errors.append(str(e))
        result.runtime_s = time.time() - t0
        (out / "daily_report.json").write_text(
            json.dumps(result.to_dict(), indent=2))
    return result


def _fact_checkable(topic: str) -> bool:
    """§36: REGENERATE research when the topic should have facts."""
    return bool(research(topic).facts)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Daily autonomous mode (§35): topic -> research -> plan "
                    "-> preflight -> repair -> render -> QA -> finalize")
    ap.add_argument("--topic", default="",
                    help="Topic; omit to let the §25 scout choose")
    ap.add_argument("--out", default="",
                    help="Artifact root (default results/YYYY-MM-DD/slug)")
    ap.add_argument("--render", action="store_true",
                    help="Render the final video (default: plan-only)")
    ap.add_argument("--res", choices=["dev", "hd", "4k"], default="dev")
    args = ap.parse_args()
    res = {"dev": (1280, 720), "hd": (1920, 1080),
           "4k": (3840, 2160)}[args.res]
    out = args.out or None
    result = run_daily(topic=args.topic or None, out_root=out,
                       render=args.render, resolution=res)
    print(json.dumps(result.to_dict(), indent=2))
    print(f"\n[{result.outcome}] {result.topic} -> {result.artifacts_dir}")


if __name__ == "__main__":
    main()
