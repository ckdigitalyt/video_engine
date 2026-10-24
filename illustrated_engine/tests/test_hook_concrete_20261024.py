"""2026-10-24 analytics review, item 2: the opening seconds must show a
concrete, literal visual. Most lost viewers left in the first 2-3 s, and
the two abstract-opening uploads ("can't feed itself" 44%, "burns hotter"
47% retention) lost them fastest.

Covers: the code-level hook rule (v16_script.check_hook_concrete), the
targeted critic-rewrite advice, the writer/critic/planner prompt changes,
and the vision judge's new hook_frame_concrete answer. Fake LLM/vision
only -- no network, no render.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_gate as G15  # noqa: E402
from engine import v15_plan as P  # noqa: E402
from engine import v16_gate as G  # noqa: E402
from engine import v16_script as S  # noqa: E402
from llm.prompts import render  # noqa: E402


def _script(hook):
    return {"hook_headline": "A Floating Frog",
            "sentences": [{"text": hook, "role": "hook", "fact_ids": ["f1"]},
                          {"text": "It really happens in a lab.", "role": "payoff",
                           "fact_ids": ["f1"]}]}


# real hooks of shipped uploads, with their 28-day retention where known
ABSTRACT_REAL = [
    "These ghost-white trees can't feed themselves, yet they live.",      # 44%
    "A black hole engine burns hotter as its fuel runs out.",             # 47%
    "The Black Death left a wound Europe couldn't close for centuries.",
]
CONCRETE_REAL = [
    "A live frog can float in midair inside a magnet.",                   # 82%
    "Sound you can't even hear can hold objects in mid-air.",             # 72%
    "Six g can knock you out and into a dream.",                          # 67%
    "About two hundred twenty-five million years ago, these stone logs were trees.",  # 72%
    "Up to thirteen minutes of falling, off one cliff.",
    "A bulb can glow in empty air, with no wires touching it.",
    "Earth's core is still being built.",
    "A failed star colder than six hundred kelvin is out there.",
    "Zero fuel onboard, yet this spacecraft could keep pushing itself along.",
    "Since 1930, Pluto hasn't finished one lap around the Sun.",
]


def test_abstract_state_openers_are_rejected():
    for h in ABSTRACT_REAL:
        errs = S.check_hook_concrete(_script(h))
        assert errs and "abstract state" in errs[0], h
        assert any("abstract state" in e for e in S.check_script(_script(h)))


def test_concrete_openers_pass_including_a_negation_that_is_not_the_claim():
    for h in CONCRETE_REAL:
        assert S.check_hook_concrete(_script(h)) == [], h


def test_a_visible_action_in_the_same_clause_rescues_an_abstract_word():
    assert S.check_hook_concrete(_script("A dying star swallows its own planet.")) == []
    assert S.check_hook_concrete(_script("A dying star gets brighter every year.")) != []


def test_only_the_first_clause_is_judged():
    assert S.hook_first_clause("A frog floats, yet it can't feel it.") == "A frog floats"
    assert S.check_hook_concrete(_script("A frog floats in a magnet, but it never dies.")) == []
    assert S.check_hook_concrete({"sentences": []}) == []


def test_critic_rewrite_asks_for_a_concrete_picture_not_a_number():
    crit = {"scores": {"hook_strength": 2, "payoff_clarity": 4}, "critique": "weak open"}
    bar = S._critic_bar(crit)
    assert "HARD REQUIREMENT" in bar and "hook_strength=2 < 3" in bar
    assert "concrete, visible" in bar
    assert "impossible-sounding" not in bar
    assert "answer the hook's question" not in bar          # payoff advice only on a payoff miss
    ok = S._critic_bar({"scores": {"hook_strength": 4, "payoff_clarity": 4}, "critique": "x"})
    assert "HARD REQUIREMENT" not in ok


def test_writer_and_critic_prompts_define_the_hook_as_a_concrete_picture():
    p, ver = render("script_write", topic="t", facts="f", series_note="", min_words=65,
                    max_words=100, critique_note="")
    assert ver == "5"
    assert "OPENS ON SOMETHING CONCRETE AND VISIBLE" in p and "abstract state" in p
    assert "a specific number or an impossible-sounding claim lands" not in p
    p, ver = render("script_critic", script="1. x")
    assert ver == "3"
    assert "STOP THE SCROLL with a concrete picture" in p
    assert '"burns hotter"' in p and "caps this at 2" in p


def test_planner_hook_shot_must_be_the_literal_picture():
    assert P.PROMPT_VERSION == "bvp/1.10"
    import inspect
    src = inspect.getsource(P)
    assert "LITERAL picture the first" in src and "never a symbol, metaphor" in src


def _judge(answer):
    import engine.director as director
    real_sheet, real_ask = G15._judge_sheet, director.vision_ask
    G15._judge_sheet = lambda *a, **k: (Path("sheet.jpg"), 4)
    director.vision_ask = lambda *a, **k: answer
    try:
        return G15.run_judge(Path("v.mp4"), {"story_id": "s", "beats": []}, {}, Path("."))
    finally:
        G15._judge_sheet, director.vision_ask = real_sheet, real_ask


def test_judge_asks_and_records_hook_frame_concrete_without_holding():
    assert "hook_frame_concrete" in G15.JUDGE_Q and "LITERALLY" in G15.JUDGE_Q
    frames = [{"n": i, "ok": True, "issue": "none"} for i in range(1, 5)]
    base = {"frames": frames, "hook_stops_scroll": True, "ending_resolves": True,
            "template_feel": False, "notes": "n"}
    r = _judge({**base, "hook_frame_concrete": False})
    assert r["ok"] and r["hook_frame_concrete"] is False
    assert any("abstract/symbolic" in s for s in r["soft_fails"])
    assert G15.verdict_of({"judge": r}) == "PASS"           # recorded + scored, never a HOLD
    r = _judge(base)                                        # older answer shape
    assert r["ok"] and r["hook_frame_concrete"] is None and r["soft_fails"] == []


def test_hook_score_counts_concreteness_only_when_judged():
    base = {"hook_stops_scroll": True, "first_word_s": 0.1, "headline_at_frame0": True}
    assert G._score_hook(base) == 100.0                     # unchanged for old judge results
    assert G._score_hook({**base, "hook_frame_concrete": True}) == 100.0
    assert G._score_hook({**base, "hook_frame_concrete": False}) == 75.0
    meta = {"B1_S1": {"beat": "B1"}}
    specs = {"B1_S1": {"meta": {"text_boxes": [{"id": "headline"}]}}}
    timing = {"B1": {"words": [{"t0": 0.0}]}}
    h = G.check_hook(meta, specs, timing, 0.1, {"hook_stops_scroll": True,
                                                "hook_frame_concrete": False})
    assert h["ok"] and h["hook_frame_concrete"] is False
