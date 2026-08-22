"""Learning memory (JADE v0.3 §6, §31–32, §39–40).

The long-term knowledge library lives at repo root `knowledge/`:

    knowledge/
    ├── topics/          # per-topic research/world notes
    ├── visual_patterns/ # reusable visual patterns (signal->processor->output…)
    ├── story_templates/ # narrative structures that worked
    ├── hero_mechanisms/ # hero mechanism successes
    ├── primitives/      # primitive promotion records
    ├── simulations/     # simulation capability notes
    ├── camera_patterns/ # camera moves that worked
    ├── audio_patterns/  # audio treatment notes
    ├── successful_shots/ # shots that passed QA
    ├── failed_shots/     # shots that failed QA (with cause)
    ├── qa_failures/      # gate failures (with cause + fix)
    └── learned_rules/    # promoted reusable rules (learned_rules.yaml)

§31: after every production run, video + QA + critic feedback + repair
history produce learning.json in the run's results dir.
§32: learned rules go into learned_rules.yaml (structured storage), never
directly into code; code changes must go proposal → tests → benchmark →
acceptance → promote.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from engine.qa.critic import Critique
from engine.qa.repair import RepairPlan

# The knowledge library subdirectories (§6).
LIBRARY_DIRS: tuple[str, ...] = (
    "topics", "visual_patterns", "story_templates", "hero_mechanisms",
    "primitives", "simulations", "camera_patterns", "audio_patterns",
    "successful_shots", "failed_shots", "qa_failures", "learned_rules",
)

RULES_FILENAME = "learned_rules.yaml"


def library_root(base: Optional[Path] = None) -> Path:
    """Repo-root knowledge library (creates the §6 tree on first use)."""
    root = Path(base) if base else Path(__file__).resolve().parents[2] / "knowledge"
    for d in LIBRARY_DIRS:
        (root / d).mkdir(parents=True, exist_ok=True)
    return root


# ── learning.json (§31) ────────────────────────────────────────────────
@dataclass
class LearningRecord:
    """One learning entry distilled from a production run (§31)."""
    failure: str = ""
    cause: str = ""
    fix: str = ""
    domain: str = ""
    representation: str = ""
    reusable_rule: str = ""
    outcome: str = ""
    topic: str = ""
    qa_score: int = 0

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "outcome": self.outcome,
            "qa_score": self.qa_score,
            "failure": self.failure,
            "cause": self.cause,
            "fix": self.fix,
            "domain": self.domain,
            "representation": self.representation,
            "reusable_rule": self.reusable_rule,
        }


def distill_learning(topic: str, qa_report: dict,
                     critique: Optional[Critique] = None,
                     repair_plan: Optional[RepairPlan] = None,
                     representation: str = "",
                     domain: str = "") -> LearningRecord:
    """Turn a run's QA + critique + repair history into a LearningRecord.

    This is the §31 learning signal: what failed, why, what fixed it,
    and what reusable rule the next video should remember.
    """
    rec = LearningRecord(
        topic=topic,
        outcome=str((qa_report or {}).get("passed", False)),
        qa_score=int((qa_report or {}).get("score", 0) or 0),
        domain=domain,
        representation=representation,
    )
    if critique and critique.problems:
        worst = sorted(critique.problems, key=lambda p: p.severity)[0]
        rec.failure = worst.problem
        rec.cause = f"beat {worst.beat} ({worst.severity} severity)"
        rec.fix = worst.repair
        rec.reusable_rule = _rule_for(worst.repair, worst.problem)
    elif repair_plan and repair_plan.actions:
        a = repair_plan.actions[0]
        rec.failure = f"repair applied: {a.action} on {a.beat}"
        rec.cause = "identified by post-preview critic"
        rec.fix = a.note or a.action
        rec.reusable_rule = _rule_for(a.action, rec.failure)
    elif qa_report and not qa_report.get("passed"):
        rec.failure = "; ".join((qa_report.get("errors") or [])[:2])
        rec.cause = "QA gate failure"
        rec.fix = "see gate errors"
        rec.reusable_rule = "re-run gates after any visualspec change"
    else:
        rec.failure = ""
        rec.cause = ""
        rec.fix = ""
        rec.reusable_rule = ("promote this run's pattern into the "
                             "library (§40)")
    return rec


def _rule_for(fix: str, problem: str) -> str:
    """Map a repair to a reusable rule (deterministic, §31 example shape)."""
    fix_l = (fix or "").lower()
    if "camera" in fix_l or "zoom" in fix_l:
        return "hero objects need enough active frame area — zoom to the " \
               "mechanism when it is the beat's focal point"
    if "demonstrat" in fix_l or "explanation" in fix_l:
        return "every explanatory beat needs a semantic demonstrating " \
               "action, not decorative motion (§13)"
    if "focal" in fix_l:
        return "one clear focal point per beat; demote secondary objects"
    if "negative" in fix_l or "space" in fix_l:
        return "keep avg empty-area ratio >= 0.20 for attention clarity"
    if "overlap" in fix_l:
        return "avoid simultaneous overlapping entities; spread zones"
    if "explanatory" in fix_l:
        return "demonstrate/illustrate/compare must dominate support classes"
    if not problem:
        return ""
    return f"avoid: {problem}"


def write_learning_json(rec: LearningRecord, out_dir: Path) -> Path:
    """§5 artifact: learning.json in the run's results dir."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "learning.json"
    p.write_text(json.dumps(rec.to_dict(), indent=2))
    return p


# ── learned_rules.yaml (§32) ────────────────────────────────────────────
def load_learned_rules(base: Optional[Path] = None) -> dict:
    """Load learned_rules.yaml (structured storage; never code)."""
    import yaml
    p = library_root(base) / "learned_rules" / RULES_FILENAME
    if not p.exists():
        return {"version": 1, "rules": []}
    try:
        data = yaml.safe_load(p.read_text())
        return data or {"version": 1, "rules": []}
    except Exception:  # noqa: BLE001
        return {"version": 1, "rules": []}


def save_learned_rules(data: dict, base: Optional[Path] = None) -> Path:
    import yaml
    p = library_root(base) / "learned_rules" / RULES_FILENAME
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def propose_rule(rec: LearningRecord, base: Optional[Path] = None) -> dict:
    """§32: add a rule as a PROPOSAL (pending acceptance), never live."""
    rules = load_learned_rules(base)
    rule = {
        "rule": rec.reusable_rule,
        "failure": rec.failure,
        "cause": rec.cause,
        "fix": rec.fix,
        "domain": rec.domain,
        "representation": rec.representation,
        "topic": rec.topic,
        "status": "proposed",
        "accepted": False,
        "source_run_qa_score": rec.qa_score,
    }
    if rec.reusable_rule and not any(
            r.get("rule") == rec.reusable_rule for r in rules["rules"]):
        rules["rules"].append(rule)
        save_learned_rules(rules, base)
    return rule


def promote_rule(rule_text: str, base: Optional[Path] = None) -> bool:
    """§32 acceptance step: a proposed rule becomes live (accepted=True).

    Real code promotion additionally requires proposal → tests →
    benchmark → acceptance; the rule store only marks acceptance.
    """
    rules = load_learned_rules(base)
    for r in rules["rules"]:
        if r.get("rule") == rule_text and not r.get("accepted"):
            r["accepted"] = True
            r["status"] = "accepted"
            save_learned_rules(rules, base)
            return True
    return False


def rules_for_domain(domain: str, base: Optional[Path] = None) -> list[dict]:
    """Accepted rules applicable to a domain (§39: reuse, don't relearn)."""
    rules = load_learned_rules(base)
    return [r for r in rules["rules"]
            if r.get("accepted") and (not domain or r.get("domain") == domain)]
