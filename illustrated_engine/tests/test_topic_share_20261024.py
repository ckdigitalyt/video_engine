"""2026-10-24 analytics review, item 1: topic selection re-weighted toward
human-scale physics (spectacle_physics) by real retention, with target
queue shares (~40% spectacle_physics, ~25% each deep_time/space_discovery).

Fake `ask` only -- no network, no LLM, no render.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]      # illustrated_engine
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from engine import v16_topics as T  # noqa: E402
from llm.prompts import render  # noqa: E402


def _e(cid, cluster, score):
    return {"id": cid, "title": cid, "cluster": cluster, "score": score}


def test_priors_follow_real_retention_order():
    p = T.CLUSTER_PRIORS
    # median retention: spectacle 77% > deep_time 65% > space ~60/57% > general 44%
    assert p["spectacle_physics"] == max(p.values()) == 1.0
    assert p["spectacle_physics"] > p["deep_time"] > p["space_discovery"] > p["general_explainer"]
    assert p["deep_time"] > p["exotic_space_travel"]
    # the taxonomy itself is unchanged: history rows keep their cluster names
    assert set(p) == {"spectacle_physics", "deep_time", "exotic_space_travel",
                      "space_discovery", "general_explainer"}
    assert set(T.CLUSTER_TARGET_SHARE) <= set(p)
    assert abs(sum(T.CLUSTER_TARGET_SHARE.values()) - 1.0) < 1e-9
    assert T.CLUSTER_TARGET_SHARE["spectacle_physics"] == 0.40
    assert T.CLUSTER_TARGET_SHARE["deep_time"] == T.CLUSTER_TARGET_SHARE["space_discovery"] == 0.25


def test_same_rubric_scores_spectacle_physics_above_deep_time_and_space():
    row = dict.fromkeys(["counter_intuitive", "visualisability", "hook_strength",
                         "series_potential", "evidence_strength", "still_image_fit"], 4)
    s = {c: T.score_candidate({"cluster": c, "evergreen": True}, row)[0]
         for c in ("spectacle_physics", "deep_time", "space_discovery")}
    assert s["spectacle_physics"] - s["deep_time"] == 5           # 25 vs 20 prior points
    assert s["deep_time"] > s["space_discovery"]
    bd = T.score_candidate({"cluster": "spectacle_physics", "evergreen": True}, row)[1]
    assert bd["cluster_prior"] == 25.0


def test_rank_by_share_hits_the_targets_on_a_space_heavy_queue():
    """The real failure mode: deep_time/space_discovery out-score and
    out-number spectacle_physics, so a pure score sort starved it (last 60
    queued topics: 24 deep_time / 22 space / 8 spectacle)."""
    entries = ([_e(f"d{i}", "deep_time", 90 - i) for i in range(8)]
               + [_e(f"s{i}", "space_discovery", 89 - i) for i in range(8)]
               + [_e(f"p{i}", "spectacle_physics", 70 - i) for i in range(4)]
               + [_e(f"x{i}", "exotic_space_travel", 80 - i) for i in range(2)])
    plain = sorted(entries, key=lambda e: e["score"], reverse=True)
    assert all(e["cluster"] != "spectacle_physics" for e in plain[:10])

    q = T.rank_by_share(entries)
    assert len(q) == len(entries) and {e["id"] for e in q} == {e["id"] for e in entries}
    assert q[0]["cluster"] == "spectacle_physics"
    share10 = T.queue_share(q[:10])
    assert share10["spectacle_physics"] == 0.4
    assert share10["deep_time"] <= 0.3 and share10["space_discovery"] <= 0.3
    # within a cluster, score order is kept
    for c in ("deep_time", "space_discovery", "spectacle_physics"):
        sc = [e["score"] for e in q if e["cluster"] == c]
        assert sc == sorted(sc, reverse=True)


def test_rank_by_share_first_three_slots_mix_clusters():
    entries = ([_e(f"d{i}", "deep_time", 95) for i in range(3)]
               + [_e(f"s{i}", "space_discovery", 94) for i in range(3)]
               + [_e("p0", "spectacle_physics", 66)])
    q = T.rank_by_share(entries)
    assert [e["cluster"] for e in q[:3]] == ["spectacle_physics", "deep_time", "space_discovery"]


def test_rank_by_share_falls_back_when_a_cluster_runs_dry_and_untargeted_last():
    entries = [_e("g0", "general_explainer", 99)] + \
              [_e(f"d{i}", "deep_time", 80 - i) for i in range(3)]
    q = T.rank_by_share(entries)
    assert [e["id"] for e in q] == ["d0", "d1", "d2", "g0"]
    # single cluster: plain score order, unchanged behaviour
    one = [_e(f"d{i}", "deep_time", s) for i, s in enumerate((70, 90, 80))]
    assert [e["score"] for e in T.rank_by_share(one)] == [90, 80, 70]
    assert T.rank_by_share([]) == []


def test_rank_by_share_handles_series_groups():
    group = {"series_id": "s1", "parts": [_e("a", "spectacle_physics", 70),
                                          _e("b", "spectacle_physics", 72)]}
    q = T.rank_by_share([_e("d0", "deep_time", 99), group])
    assert q[0] is group


def test_ideation_prompt_carries_shares_and_the_body_cluster_description():
    block = T.clusters_prompt_block()
    assert "spectacle_physics (prior 1.00; aim for ~40% of candidates)" in block
    assert "g-force" in block and "human body" in block
    assert "general_explainer (prior 0.20; use sparingly)" in block
    prompt, ver = render("topic_ideate", clusters=block, n=10, avoid_titles="(none)")
    assert ver == "3" and "target share" in prompt and "abstract state" in prompt
    prompt, ver = render("topic_score", candidates="id: t_1\ntitle: x")
    assert ver == "4" and "Sound Waves That Levitate Objects" in prompt
    assert "suspended or frozen STATE is still-image friendly" in prompt


def test_build_queue_orders_by_share(tmp_path):
    clusters = ["deep_time"] * 4 + ["space_discovery"] * 4 + ["spectacle_physics"] * 2
    raw = [{"title": f"Topic {i} {c} distinct words{i}", "cluster": c, "claim": f"claim {i} {c}",
            "entities": {"subject": f"subj{i}", "place": "", "era": "", "phenomenon": ""},
            "hooks": ["h1", "h2", "h3"], "templates": ["BIG_NUMBER"],
            "series_id": None, "series_part": None, "evergreen": True}
           for i, c in enumerate(clusters)]
    ids, seen = [], set()
    for c in raw:
        cid = T._unique_id(T.slugify(c["title"]), seen)
        seen.add(cid)
        ids.append(cid)
    hi = {"counter_intuitive": 5, "visualisability": 5, "hook_strength": 5,
          "series_potential": 4, "evidence_strength": 5, "still_image_fit": 5, "best_hook": "h"}
    lo = {**hi, "counter_intuitive": 3, "series_potential": 2}
    scores = [{"id": cid, **(lo if c == "spectacle_physics" else hi)}
              for cid, c in zip(ids, clusters)]
    q = {"topic_ideate": [{"candidates": raw}], "topic_score": [{"scores": scores}]}
    prompts = []

    def ask(stage, prompt, **kw):
        prompts.append((stage, prompt))
        return SimpleNamespace(data=q[stage].pop(0), model="fake", cached=False,
                               attempts=1, usage={})
    res = T.build_queue(n=10, history_path=tmp_path / "h.jsonl", ask=ask, persist=True)
    queue = res["queue"]
    assert len(queue) == 10
    assert queue[0]["cluster"] == "spectacle_physics"          # lower score, still first
    assert T.queue_share(queue[:5])["spectacle_physics"] == 0.4
    assert "aim for ~40% of candidates" in prompts[0][1]
    rows = [json.loads(x) for x in (tmp_path / "h.jsonl").read_text().splitlines()]
    assert sum(r["status"] == "queued" for r in rows) == 10
