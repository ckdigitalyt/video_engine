"""2026-10-24 analytics review, item 3: the script critic becomes a harder,
better-weighted gate.

- The scorecard's story dimension (retention-weighted critic score) carries
  50 of 100 points. Captions, audio loudness and brand are pass/fail gates
  that add no variable points.
- escalation and emotional_charge got the same >= 3 hard floor as
  hook_strength/payoff_clarity (0-5 critic scale). 2026-10-27: softened to
  >= 2 and down-weighted after the n=20 re-check (see
  tests/test_critic_floor_relax_20261027.py); the tests below were updated
  for that policy.
- The verdict PROPAGATION (check_scorecard -> v15_gate.verdict_of) is
  unchanged; only what feeds it changes.

Fake LLM only; no network, no render.
"""
import copy
import json
import statistics as st
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v15_gate  # noqa: E402
from engine import v16_gate as g  # noqa: E402
from engine import v16_script as S  # noqa: E402
from llm import client  # noqa: E402

WARP = json.loads((ROOT / "tests" / "fixtures" / "warp_bubble_20261015.json").read_text())
WARP_FACTS = {"claims": [{**c, "evidence": c["quote"], "quote_verified": True,
                          "verified": True, "curated": False} for c in WARP["claims"]]}
DIMS = ["hook_strength", "curiosity_gap", "escalation", "payoff_clarity",
        "loop_coherence", "human_voice", "emotional_charge", "one_idea_only"]

# Real uploads (28-day averageViewPercentage) with their story.json critic
# scores, from the 2026-10-24 review join.
REAL = [
    ("pilots", 67.2, dict(hook_strength=4, curiosity_gap=4, escalation=3, payoff_clarity=3,
                          loop_coherence=4, human_voice=3, emotional_charge=3, one_idea_only=5)),
    ("ghost_tree", 44.17, dict(hook_strength=4, curiosity_gap=3, escalation=2, payoff_clarity=3,
                               loop_coherence=3, human_voice=3, emotional_charge=3,
                               one_idea_only=4)),
    ("black_hole", 46.51, dict(hook_strength=3, curiosity_gap=3, escalation=2, payoff_clarity=3,
                               loop_coherence=4, human_voice=3, emotional_charge=2,
                               one_idea_only=4)),
    ("stone_tree", 72.15, dict(hook_strength=3, curiosity_gap=3, escalation=3, payoff_clarity=4,
                               loop_coherence=3, human_voice=4, emotional_charge=3,
                               one_idea_only=5)),
    ("clay", 65.01, dict(hook_strength=4, curiosity_gap=3, escalation=2, payoff_clarity=3,
                         loop_coherence=4, human_voice=3, emotional_charge=3, one_idea_only=3)),
    ("cliff", 60.14, dict(hook_strength=4, curiosity_gap=3, escalation=3, payoff_clarity=3,
                          loop_coherence=4, human_voice=3, emotional_charge=3, one_idea_only=4)),
    ("voyager", 61.28, dict(hook_strength=4, curiosity_gap=3, escalation=2, payoff_clarity=3,
                            loop_coherence=4, human_voice=3, emotional_charge=3,
                            one_idea_only=5)),
    ("crystal", 60.49, dict(hook_strength=3, curiosity_gap=3, escalation=2, payoff_clarity=3,
                            loop_coherence=3, human_voice=3, emotional_charge=3,
                            one_idea_only=3)),
]


def _corr(a, b):
    ma, mb = st.mean(a), st.mean(b)
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (
        sum((x - ma) ** 2 for x in a) ** .5 * sum((y - mb) ** 2 for y in b) ** .5)


# ------------------------------------------------------------ floors --

def test_floors_cover_the_four_dimensions_on_the_real_0_to_5_scale():
    # 2026-10-27: escalation/emotional_charge softened 3 -> 2 (n=20 re-check)
    assert S.CRITIC_HARD_FLOORS == {"hook_strength": 3, "payoff_clarity": 3,
                                    "escalation": 2, "emotional_charge": 2}
    props = client.load_schema("script_critic")["properties"]["scores"]["properties"]
    assert all(props[d]["minimum"] == 0 and props[d]["maximum"] == 5 for d in DIMS)
    ok = dict.fromkeys(DIMS, 3)
    assert S.critic_floor_misses(ok) == []
    assert S.critic_floor_misses({**ok, "escalation": 2}) == []
    assert S.critic_floor_misses({**ok, "emotional_charge": 2}) == []
    assert S.critic_floor_misses({**ok, "escalation": 1}) == ["escalation=1 < 2"]
    assert S.critic_floor_misses({**ok, "emotional_charge": 1}) == ["emotional_charge=1 < 2"]
    assert S.critic_floor_misses({**ok, "payoff_clarity": 2}) == ["payoff_clarity=2 < 3"]
    # mean/other-dimension floors stay removed (decision #17)
    assert S.critic_floor_misses({**ok, "loop_coherence": 0, "curiosity_gap": 1}) == []


def test_softened_floor_holds_none_of_the_eight_real_uploads():
    """2026-10-24 this test asserted the >= 3 floor would hold ghost_tree and
    black_hole (escalation=2). That rested on the n=8 escalation +0.59 /
    emotional_charge +0.55 correlation, which fell to +0.06 / -0.05 at
    n=20. None of the eight real uploads is a broken script (all have
    escalation and emotional_charge >= 2, hook and payoff >= 3)."""
    assert [n for n, _, s in REAL if S.critic_floor_misses(s)] == []


class Fake:
    def __init__(self, **q):
        self.q = {k: list(v) for k, v in q.items()}
        self.prompts = []

    def __call__(self, stage, prompt, *, schema=None, prompt_version="", **kw):
        self.prompts.append((stage, prompt))
        return SimpleNamespace(data=copy.deepcopy(self.q[stage].pop(0)), model="fake", cached=False,
                               attempts=1, usage={})


def _fc(script):
    return {"sentences": [{"n": i, "label": "supported", "note": ""}
                          for i in range(1, len(script["sentences"]) + 1)]}


META = {"title": "A Ship That Never Speeds Up", "title_fact_ids": ["f_warp_contract_expand"],
        "description": "x", "hashtags": ["#space", "#physics", "#science"],
        "series_tag": "", "pinned_comment": "?"}


def test_real_warp_draft_with_escalation_2_is_scored_again():
    """2026-10-24 this real draft (escalation=2) held. Under the softened
    2026-10-27 floor it is scored and produced."""
    d1 = WARP["draft1"]
    c1 = WARP["critic1"]
    assert c1["scores"]["escalation"] == 2
    f = Fake(script_write=[d1, d1, d1], script_critic=[c1, c1, c1],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    assert res["candidates"][0]["status"] == "scored"
    # escalation=2 is not a hard miss, so no HARD REQUIREMENT for it
    rewrite_prompt = [p for st_, p in f.prompts if st_ == "script_write"][1]
    assert "escalation=2 <" not in rewrite_prompt


def test_genuinely_flat_draft_escalation_1_still_holds_after_its_targeted_rewrite():
    d1 = WARP["draft1"]
    c1 = {**WARP["critic1"], "scores": dict(WARP["critic1"]["scores"], escalation=1)}
    f = Fake(script_write=[d1, d1, d1], script_critic=[c1, c1, c1])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "HOLD"
    cand = res["candidates"][0]
    assert cand["status"] == "hold" and "escalation=1 < 2" in cand["reason"]
    # the rewrite was told exactly what to fix
    rewrite_prompt = [p for st_, p in f.prompts if st_ == "script_write"][1]
    assert "HARD REQUIREMENT" in rewrite_prompt and "escalation=1 < 2" in rewrite_prompt
    assert "raise the stakes about the SAME subject" in rewrite_prompt


def test_second_rewrite_attempt_can_rescue_a_story_the_first_one_missed():
    """2026-10-24 live evidence (first batch under the new escalation/
    emotional_charge floors): two human-scale-physics topics -- G-Force
    pilot, lung pressure, exactly the category topic selection just
    boosted -- held on escalation=2 after their one rewrite attempt.
    RANK_REWRITE_BUDGET went 1 -> 2 so a floor miss that the first
    rewrite doesn't fix gets one more shot before holding."""
    d1 = WARP["draft1"]
    # 2026-10-27: escalation=2 no longer misses, so this uses a payoff_clarity
    # miss (still a >= 3 floor) to exercise the same second-attempt rescue.
    c1 = {**WARP["critic1"], "scores": dict(WARP["critic1"]["scores"], payoff_clarity=2)}
    fixed = {"scores": dict.fromkeys(DIMS, 4), "critique": ""}
    # 1st rewrite (index 1) still misses the floor (same c1 again); the
    # 2nd rewrite (index 2) finally clears it -- only possible because
    # the budget now allows a 2nd attempt.
    f = Fake(script_write=[d1, d1, d1], script_critic=[c1, c1, fixed],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    assert len([p for st_, p in f.prompts if st_ == "script_write"]) == 3


def test_rewrite_that_lifts_escalation_and_emotion_is_picked():
    d1 = WARP["draft1"]
    # 2026-10-27: floor is now 2, so a hard miss (and its advice) needs a 1
    weak = {"scores": dict(dict.fromkeys(DIMS, 4), escalation=1, emotional_charge=1),
            "critique": "flat"}
    # mean 4 / min 4 clears critic_pass (mean>=4, min>=3) so the rewrite
    # loop exits after this one attempt regardless of RANK_REWRITE_BUDGET.
    fixed = {"scores": dict.fromkeys(DIMS, 4), "critique": ""}
    f = Fake(script_write=[d1, d1], script_critic=[weak, fixed],
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Warp", WARP_FACTS)], ask=f)
    assert res["verdict"] == "PASS", res
    rewrite_prompt = [p for st_, p in f.prompts if st_ == "script_write"][1]
    assert "Make the viewer FEEL it" in rewrite_prompt


# ------------------------------------------------- weighted story score --

def test_critic_points_follow_the_critic_prompts_own_anchors():
    assert [S.critic_points(v) for v in range(6)] == [0, 15, 40, 75, 92, 100]
    assert S.critic_points(3.5) == 83.5 and S.critic_points(9) == 100 and S.critic_points(-1) == 0
    assert S.critic_weighted_score(dict.fromkeys(DIMS, 5)) == 100.0
    assert S.critic_weighted_score(dict.fromkeys(DIMS, 3)) == 75.0
    assert S.critic_weighted_score({}) is None
    assert S.critic_weighted_score({"hook": 5, "clarity": 5}) == 100.0     # unknown names count
    assert abs(sum(S.STORY_DIM_WEIGHTS.values()) - 1.0) < 1e-9
    top = sorted(S.STORY_DIM_WEIGHTS, key=S.STORY_DIM_WEIGHTS.get, reverse=True)[:4]
    # 2026-10-27: escalation/emotional_charge dropped out of the top four
    assert set(top) == {"payoff_clarity", "human_voice", "hook_strength", "curiosity_gap"}


def test_weighted_story_tracks_real_retention_better_than_the_plain_mean():
    ret = [r for _, r, _ in REAL]
    plain = [st.mean(s.values()) for _, _, s in REAL]
    weighted = [S.critic_weighted_score(s) for _, _, s in REAL]
    # 2026-10-24 weights: 0.73 vs 0.60 (n=8, in-sample -- the escalation/
    # emotion weights were fit to these same 8). 2026-10-27 weights: 0.65.
    # Still not worse than the plain mean on the old sample.
    assert _corr(weighted, ret) >= _corr(plain, ret)


def test_rank_pick_prefers_hook_payoff_curiosity_over_escalation_and_emotion():
    """2026-10-24 this asserted the opposite (escalation/emotion won). After
    the n=20 re-check (+0.06 / -0.05) they count less than hook/payoff/
    curiosity, so equal lifts favour the hook/payoff/curiosity draft."""
    moving = dict(dict.fromkeys(DIMS, 3), escalation=4, emotional_charge=4)
    hooky = dict(dict.fromkeys(DIMS, 3), hook_strength=4, payoff_clarity=4)
    assert st.mean(hooky.values()) == st.mean(moving.values())         # plain mean: a tie
    assert S.critic_weighted_score(hooky) > S.critic_weighted_score(moving)
    d1 = WARP["draft1"]
    # RANK_REWRITE_BUDGET=2: neither score ever reaches critic_pass's
    # mean>=4 bar, so both topics now spend both rewrite attempts.
    f = Fake(script_write=[d1] * 6,
             script_critic=[{"scores": moving, "critique": ""}] * 3
                           + [{"scores": hooky, "critique": ""}] * 3,
             fact_check=[_fc(d1)], metadata_pack=[META])
    res = S.rank_write_story([("Moving", WARP_FACTS), ("Hooky", WARP_FACTS)], ask=f)
    assert res["picked_topic"] == "Hooky"
    assert all("weighted" in c for c in res["candidates"])


# ------------------------------------------------------------ scorecard --

def _checks(lufs=-14.0, clause_ok=True):
    return {
        "judge": {"ok": True, "hook_stops_scroll": True, "frames_flagged": []},
        "hook": {"ok": True, "hook_stops_scroll": True, "first_word_s": 0.1,
                 "headline_at_frame0": True},
        "caption_identity": {"ok": True}, "text_bounds": {"ok": True},
        "caption_safe": {"ok": True},
        "caption_clause_breaks": {"ok": clause_ok, "warning": True},
        "audio": {"ok": True, "lufs": lufs},
    }


def _meta_specs(n=12, dur=2.6):
    meta = {f"B{i}_S1": {"kind": "plate", "beat": f"B{i}"} for i in range(1, n + 1)}
    specs = {k: {"duration_s": dur + (0.8 if i % 2 else -0.4), "layers": []}
             for i, k in enumerate(meta)}
    return meta, specs


def _sc(story_scores, checks=None, sting=True):
    meta, specs = _meta_specs()
    return g.compute_scorecard(checks=checks or _checks(), meta=meta, specs=specs,
                               story={"critic": {"scores": story_scores}}, plates={},
                               brand={}, sting_present=sting)


def test_weights_story_is_half_and_near_constant_checks_are_gates():
    assert g.SCORE_WEIGHTS == {"story": 50, "hook": 20, "visuals": 15, "pacing": 15}
    assert sum(g.SCORE_WEIGHTS.values()) == 100
    assert set(g.SCORE_GATES) == {"captions", "audio", "brand"}
    sc = _sc(dict.fromkeys(DIMS, 4))
    assert set(sc["dimensions"]) == set(g.SCORE_WEIGHTS)        # gates add no points
    assert set(sc["gates"]) == set(g.SCORE_GATES) and sc["failed_gates"] == []
    assert sc["total"] == round(sum(sc["dimensions"][k] * g.SCORE_WEIGHTS[k] / 100
                                    for k in g.SCORE_WEIGHTS), 1)


def test_typical_current_pass_render_still_passes():
    """The three surviving 2026-10-24 PASS scorecards had story=62.5 (critic
    mean 3.125), hook 100, visuals 60-80, pacing 94-100. Re-weighting alone
    must not turn them into HOLDs."""
    story = dict(dict.fromkeys(DIMS, 3), one_idea_only=4)
    w = S.critic_weighted_score(story)
    for vis, pac in ((80.0, 100.0), (60.0, 94.4)):
        total = w * .5 + 100 * .2 + vis * .15 + pac * .15
        assert total >= 80, (vis, pac, total)


def test_story_quality_now_moves_the_verdict():
    strong = _sc(dict(dict.fromkeys(DIMS, 4)))
    weak = _sc(dict(dict.fromkeys(DIMS, 2)))
    assert strong["verdict"] == "PASS"
    assert weak["verdict"] in ("HOLD", "REJECT")
    assert strong["total"] - weak["total"] >= 25


def test_audio_gate_holds_a_would_be_pass_without_costing_points():
    on = _sc(dict.fromkeys(DIMS, 4), _checks(lufs=-14.7))      # real renders: -14.6..-14.8
    assert on["verdict"] == "PASS" and on["gates"]["audio"]["ok"]
    off = _sc(dict.fromkeys(DIMS, 4), _checks(lufs=-16.0))
    assert off["total"] == on["total"]                          # no variable points
    assert off["verdict"] == "HOLD" and off["failed_gates"] == ["audio"]
    c = g.check_scorecard(off)
    assert not c["ok"] and not c["critical"] and "failed pass/fail gates: audio" in c["fails"][0]
    assert v15_gate.verdict_of({"scorecard": c}) == "HOLD"


def test_brand_and_caption_gates():
    assert _sc(dict.fromkeys(DIMS, 4), sting=False)["failed_gates"] == ["brand"]
    # a decision #13 warning check failing does not fail the captions gate
    assert _sc(dict.fromkeys(DIMS, 4), _checks(clause_ok=False))["gates"]["captions"]["ok"]
    hard = _checks()
    hard["caption_safe"] = {"ok": False}
    assert set(_sc(dict.fromkeys(DIMS, 4), hard)["failed_gates"]) == {"captions", "brand"}
    none_ran = {k: v for k, v in _checks().items() if not k.startswith(("caption", "text"))}
    assert not _sc(dict.fromkeys(DIMS, 4), none_ran)["gates"]["captions"]["ok"]
    assert not g._gate_audio({})["ok"]


def test_failed_gate_never_upgrades_a_reject():
    sc = _sc(dict.fromkeys(DIMS, 0), _checks(lufs=-17.0))
    assert sc["verdict"] == "REJECT"
    assert g.check_scorecard(sc)["critical"] is True


def test_run_gate_propagation_is_unchanged(monkeypatch):
    """Same wiring as tests/test_gate_scorecard_blocks.py: a scorecard HOLD
    from a failed gate reaches the final verdict as HOLD via the untouched
    check_scorecard -> verdict_of path."""
    base = {"checks": {k: v for k, v in _checks(lufs=-16.0).items() if k != "hook"},
            "verdict": "PASS", "failures": {}}
    base["checks"]["av"] = {"ok": True, "fails": [], "duration_s": 36.0}
    for v in base["checks"].values():
        v.setdefault("fails", [])
    monkeypatch.setattr(v15_gate, "run_gate", lambda *a, **k: base)
    monkeypatch.setattr(v15_gate, "_plate_paths", lambda specs: [])
    meta, specs = _meta_specs()
    for k in specs:
        specs[k]["meta"] = {"text_boxes": [{"id": "headline"}]}
    story = {"story_id": "s", "critic": {"scores": dict.fromkeys(DIMS, 4)},
             "beats": [{"beat_id": "B1"}]}
    out = g.run_gate("/nonexistent", story, meta, specs, {"B1": {"words": [{"t0": 0.0}]}},
                     {}, 0.1, brand={}, plates={}, sting_present=True, video_id="v")
    assert out["scorecard"]["failed_gates"] == ["audio"]
    assert out["verdict"] == "HOLD" and "scorecard" in out["failures"]
