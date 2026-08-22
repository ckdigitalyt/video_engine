"""Phase F tests (§6, §31–32): learning memory + knowledge library.

- library_root() creates the §6 knowledge/ tree
- distill_learning() turns QA + critique + repair history into a
  LearningRecord (learning.json contract §31)
- propose_rule() adds rules as PROPOSALS (never live) and
  promote_rule() accepts them (§32)
- rules_for_domain() returns accepted, domain-matched rules (§39)
"""

from __future__ import annotations

import json

import pytest

from engine.learning.memory import (
    LIBRARY_DIRS,
    distill_learning,
    library_root,
    load_learned_rules,
    promote_rule,
    propose_rule,
    rules_for_domain,
    write_learning_json,
)
from engine.qa.critic import Problem, critique_preview
from engine.qa.repair import RepairAction, RepairPlan


@pytest.fixture()
def tmp_lib(tmp_path):
    return library_root(tmp_path)


def test_library_tree_created(tmp_lib):
    for d in LIBRARY_DIRS:
        assert (tmp_lib / d).is_dir(), f"missing knowledge/{d} (§6)"


def test_distill_learning_from_critique(tmp_lib):
    rec = distill_learning(
        "Why is the sky blue?",
        {"passed": False, "score": 62},
        critique=_FakeCritique(),
        representation="SIMULATION",
        domain="science",
    )
    assert rec.failure
    assert rec.cause
    assert rec.fix
    assert rec.reusable_rule
    assert rec.qa_score == 62
    d = rec.to_dict()
    assert set(d) >= {"topic", "outcome", "qa_score", "failure", "cause",
                      "fix", "domain", "representation", "reusable_rule"}


def test_distill_learning_pass_run(tmp_lib):
    rec = distill_learning(
        "Why does popcorn pop?",
        {"passed": True, "score": 95},
        representation="EXPERIMENT",
    )
    assert rec.outcome == "True"
    assert "promote" in rec.reusable_rule.lower()


def test_write_learning_json(tmp_path):
    rec = distill_learning("x", {"passed": True, "score": 90})
    p = write_learning_json(rec, tmp_path)
    assert p.name == "learning.json"
    data = json.loads(p.read_text())
    assert data["topic"] == "x"


def test_propose_rule_is_pending_not_accepted(tmp_lib):
    rec = distill_learning(
        "How do noise-cancelling headphones work?",
        {"passed": False, "score": 70},
        critique=_FakeCritique(),
        representation="SIGNAL_FLOW",
        domain="technology",
    )
    rule = propose_rule(rec, tmp_lib)
    assert rule["status"] == "proposed"
    assert rule["accepted"] is False
    rules = load_learned_rules(tmp_lib)
    assert any(r["rule"] == rec.reusable_rule and not r["accepted"]
               for r in rules["rules"])


def test_promote_rule_accepts(tmp_lib):
    rec = distill_learning("x", {"passed": False, "score": 70},
                           critique=_FakeCritique())
    propose_rule(rec, tmp_lib)
    assert promote_rule(rec.reusable_rule, tmp_lib) is True
    rules = load_learned_rules(tmp_lib)
    assert any(r["rule"] == rec.reusable_rule and r["accepted"]
               for r in rules["rules"])


def test_rules_for_domain_filters_accepted(tmp_lib):
    rec1 = distill_learning("a", {"passed": False, "score": 60},
                            critique=_FakeCritique(), domain="science")
    rec2 = distill_learning("b", {"passed": False, "score": 60},
                            critique=_FakeCritique(), domain="technology")
    propose_rule(rec1, tmp_lib)
    propose_rule(rec2, tmp_lib)
    promote_rule(rec1.reusable_rule, tmp_lib)  # only science accepted
    got = rules_for_domain("science", tmp_lib)
    assert all(r["domain"] == "science" and r["accepted"] for r in got)
    assert not rules_for_domain("technology", tmp_lib)


def test_rules_deduplicate(tmp_lib):
    rec = distill_learning("x", {"passed": False, "score": 70},
                           critique=_FakeCritique())
    propose_rule(rec, tmp_lib)
    propose_rule(rec, tmp_lib)
    rules = load_learned_rules(tmp_lib)
    assert sum(1 for r in rules["rules"]
               if r["rule"] == rec.reusable_rule) == 1


class _FakeCritique:
    """Minimal Critique-shaped object with one beat-tied problem."""
    problems = [
        Problem(beat="b004", problem="hero mechanism too small",
                severity="high",
                repair="zoom camera to the scattering field"),
    ]


def test_distill_maps_camera_repair_to_rule(tmp_lib):
    rec = distill_learning("x", {"passed": False, "score": 70},
                           critique=_FakeCritique())
    assert "active frame area" in rec.reusable_rule
