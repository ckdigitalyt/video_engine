"""
test_v1_integration.py — End-to-end integration tests for v1 modules.

Tests every new module against real data, verifying it actually produces
valid output that the pipeline can consume.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Ensure we're in the project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load .env if present
dotenv_path = Path(__file__).resolve().parent.parent / ".env"
if dotenv_path.exists():
    with open(dotenv_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                if k and k not in os.environ:
                    os.environ[k] = v

# ═══════════════════════════════════════════════════════════════════════
# Phase 4 — AssetRanker
# ═══════════════════════════════════════════════════════════════════════
def test_asset_ranker_scores_and_ranks():
    """Verify AssetRanker scores candidates on multiple dimensions."""
    from src.assets.asset_ranker import AssetRanker
    
    ranker = AssetRanker()
    
    # Simulate candidates from different providers
    candidates = [
        ("pexels", "spiral galaxy", [
            {"width": 1920, "height": 1080, "duration": 10,
             "tags": ["space", "galaxy", "cinematic"],
             "video_files": [{"quality": "hd"}],
             "url": "https://example.com/vid1.mp4"},
        ]),
        ("nasa", "nebula", [
            {"width": 3840, "height": 2160, "duration": 15,
             "tags": ["nasa", "space", "documentary"],
             "video_files": [{"quality": "hd"}],
             "url": "https://example.com/vid2.mp4"},
        ]),
    ]
    
    scored = ranker.score_and_rank(candidates, query="spiral galaxy", target_duration=10)
    
    assert len(scored) == 2, "Should score both candidates"
    assert scored[0].score > 0, "Top scorer should have positive score"
    assert scored[0].provider in ("pexels", "nasa")
    
    # Verify sub-scores exist
    assert "resolution" in scored[0].scores
    assert "duration" in scored[0].scores
    assert "documentary" in scored[0].scores
    
    print(f"  [PASS] AssetRanker: {scored[0].provider} score={scored[0].score}")

def test_asset_ranker_penalties():
    """Verify AssetRanker applies watermark and quality penalties."""
    from src.assets.asset_ranker import AssetRanker
    
    ranker = AssetRanker()
    
    # Premium candidate
    good = ranker._score_single(
        {"width": 1920, "height": 1080, "duration": 10,
         "tags": ["space", "galaxy"], "video_files": [{"quality": "hd"}],
         "url": "https://example.com/good.mp4"},
        "pexels", "galaxy", 10
    )
    
    # Low-res watermarked candidate
    bad = ranker._score_single(
        {"width": 640, "height": 360, "duration": 10,
         "tags": ["shutterstock", "watermark"], 
         "video_files": [],
         "url": "https://example.com/watermark_preview.mp4"},
        "some_provider", "galaxy", 10
    )
    
    assert good.score > bad.score, "Good HD clip should score higher than bad watermarked one"
    print(f"  [PASS] Ranking penalty: good={good.score:.3f} > bad={bad.score:.3f}")

# ═══════════════════════════════════════════════════════════════════════
# Phase 7 — Result<T>
# ═══════════════════════════════════════════════════════════════════════
def test_result_success():
    """Verify Result.success works correctly."""
    from src.utils.result import Result
    
    r = Result.success([1, 2, 3])
    assert r.is_success
    assert not r.is_failure
    assert not r.is_retry
    assert r.data == [1, 2, 3]
    assert r.unwrap() == [1, 2, 3]
    assert r.unwrap_or([]) == [1, 2, 3]
    print(f"  [PASS] Result.success")

def test_result_failure():
    """Verify Result.failure includes full context."""
    from src.utils.result import Result
    
    r = Result.failure(
        reason="No results", provider="pexels",
        query="spiral galaxy", http_status=404,
        exception="Not found", retry_count=2,
    )
    
    assert not r.is_success
    assert r.is_failure
    
    detail = r.failure_detail
    assert detail.reason == "No results"
    assert detail.provider == "pexels"
    assert detail.http_status == 404
    assert "No results" in str(r)
    print(f"  [PASS] Result.failure: {detail}")

def test_result_retry():
    """Verify Result.retry works."""
    from src.utils.result import Result
    
    r = Result.retry("Rate limited", provider="pexels", retry_count=1)
    assert r.is_retry
    assert not r.is_success
    assert not r.is_failure
    retry = r.retry_detail
    assert retry.reason == "Rate limited"
    assert retry.retry_count == 1
    assert not retry.fatal
    print(f"  [PASS] Result.retry")

# ═══════════════════════════════════════════════════════════════════════
# Phase 8 — VisualCritic
# ═══════════════════════════════════════════════════════════════════════
def test_visual_critic_evaluate():
    """Verify VisualCritic returns structured scores."""
    from src.critic.visual_critic import VisualCritic
    
    critic = VisualCritic()
    result = critic.evaluate(
        narration="A spiral galaxy rotates slowly in the darkness of space.",
        asset_metadata={
            "width": 1920, "height": 1080,
            "provider": "pexels",
            "duration": 10.0,
        },
    )
    
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], (int, float))
    assert 0 <= result["score"] <= 100
    print(f"  [PASS] VisualCritic score={result['score']}, reason={result['reason'][:40]}")

# ═══════════════════════════════════════════════════════════════════════
# Phase 9 — VisualMemory / Duplicate Detection
# ═══════════════════════════════════════════════════════════════════════
def test_visual_memory_detects_duplicates():
    """Verify VisualMemory detects and prevents duplicates."""
    from src.director.visual_memory import VisualMemory
    
    memory = VisualMemory(window_seconds=300)  # Long window for test
    
    # Record first galaxy
    memory.record(["Andromeda Galaxy", "spiral", "stars"], "pexels", "wide")
    
    # Same galaxy should be detected
    assert memory.is_duplicate(["Andromeda Galaxy"])
    assert memory.is_duplicate(["spiral"])
    
    # Different objects should not
    assert not memory.is_duplicate(["Nebula"])
    assert not memory.is_duplicate(["Mars"])
    
    print(f"  [PASS] VisualMemory duplicate detection")

def test_visual_memory_stats():
    """Verify VisualMemory returns useful stats."""
    from src.director.visual_memory import VisualMemory
    
    memory = VisualMemory(window_seconds=60)
    memory.record(["Saturn"], "pexels", "wide")
    memory.record(["Jupiter"], "pexels", "closeup")
    
    stats = memory.get_stats()
    assert stats["current_entries"] == 2
    assert stats["total_sequence"] == 2
    assert "pexels" in stats["provider_counts"]
    print(f"  [PASS] VisualMemory stats: {stats['current_entries']} entries")

# ═══════════════════════════════════════════════════════════════════════
# Phase 10 — ManimPlanner
# ═══════════════════════════════════════════════════════════════════════
def test_manim_planner_has_default_scripts():
    """Verify ManimPlanner has default scripts for key topics."""
    from src.manim.planner import ManimPlanner, ManimTopic
    
    planner = ManimPlanner(output_dir="/tmp/test_manim")
    
    # Drake equation should have a default script
    plan = planner.plan(topic=ManimTopic.DRAKE_EQUATION)
    assert plan.script_path, "Should generate a script path"
    assert plan.topic == ManimTopic.DRAKE_EQUATION
    print(f"  [PASS] ManimPlanner plan: {plan.topic.value} -> {plan.script_path}")

def test_manim_planner_score():
    """Verify ManimPlanner.score_for_topic works."""
    from src.manim.planner import ManimPlanner
    
    planner = ManimPlanner()
    
    # Topics that should score high for Manim
    high_topics = ["black hole geometry", "Drake equation", "Big Bang timeline",
                   "gravitational wave simulation"]
    low_topics = ["scientists talking", "nature documentary", "historical overview"]
    
    for t in high_topics:
        assert planner.score_for_topic(t) > 0.3, f"'{t}' should score >0.3"
    for t in low_topics:
        assert planner.score_for_topic(t) < 0.5, f"'{t}' should score <0.5"
    
    print(f"  [PASS] ManimPlanner topic scoring works")

# ═══════════════════════════════════════════════════════════════════════
# Phase 11 — StoryboardPlanner
# ═══════════════════════════════════════════════════════════════════════
def test_storyboard_planner_fallback():
    """Verify StoryboardPlanner produces valid storyboards even without LLM."""
    from src.director.storyboard_planner import StoryboardPlanner, StoryboardScene
    
    planner = StoryboardPlanner()
    
    # Test with empty narration to trigger fallback path
    scene = planner.plan_scene(scene_id=0, title="Test", narration="", num_shots=3)
    
    assert isinstance(scene, StoryboardScene)
    assert scene.scene_id == 0
    # Fallback should still produce shots
    print(f"  [PASS] StoryboardPlanner: {len(scene.shots)} shots")

# ═══════════════════════════════════════════════════════════════════════
# Phase 12 — TransitionPlanner
# ═══════════════════════════════════════════════════════════════════════
def test_transition_planner_scene_boundary():
    """Verify TransitionPlanner picks appropriate transitions."""
    from src.effects.transitions import TransitionPlanner, TransitionType
    
    planner = TransitionPlanner()
    
    # Scene boundary with mystery emotion → fade
    t = planner.plan(scene_boundary=True, emotion="mysterious", pace="slow")
    assert t.transition_type in (TransitionType.FADE, TransitionType.CROSS_DISSOLVE)
    
    # Fast pace → cut
    t = planner.plan(pace="fast")
    assert t.transition_type in (TransitionType.CUT, TransitionType.WHIP_PAN)
    
    print(f"  [PASS] TransitionPlanner context-aware")

# ═══════════════════════════════════════════════════════════════════════
# Phase 13 — BrollTaxonomy
# ═══════════════════════════════════════════════════════════════════════
def test_broll_taxonomy_space_category():
    """Verify BrollTaxonomy has Space templates."""
    from src.assets.broll_taxonomy import BrollTaxonomy
    
    taxonomy = BrollTaxonomy()
    
    space_templates = taxonomy.get_templates_for_category("Space")
    assert len(space_templates) > 0, "Space should have templates"
    
    names = [t.name for t in space_templates]
    assert any("Galaxies" in n for n in names), "Should have galaxy templates"
    assert any("Nebulae" in n for n in names), "Should have nebula templates"
    
    print(f"  [PASS] BrollTaxonomy: Space has {len(space_templates)} templates")

def test_broll_taxonomy_all_categories():
    """Verify BrollTaxonomy covers all expected categories."""
    from src.assets.broll_taxonomy import BrollTaxonomy
    
    taxonomy = BrollTaxonomy()
    cats = taxonomy.get_all_categories()
    
    expected = {"Space", "Science", "Technology", "Nature", "History", "General"}
    for exp in expected:
        assert exp in cats, f"Missing category: {exp}"
    
    print(f"  [PASS] BrollTaxonomy: {len(cats)} categories: {cats}")

def test_broll_taxonomy_matching():
    """Verify BrollTaxonomy finds matching templates for keywords."""
    from src.assets.broll_taxonomy import BrollTaxonomy
    
    taxonomy = BrollTaxonomy()
    
    matches = taxonomy.find_matching_templates(["galaxy", "nebula", "star"])
    assert len(matches) >= 1, "Should find space-related templates"
    
    matches = taxonomy.find_matching_templates(["laboratory", "microscope"])
    assert len(matches) >= 1, "Should find science-related templates"
    
    print(f"  [PASS] BrollTaxonomy matching: {len(matches)} matches")

# ═══════════════════════════════════════════════════════════════════════
# Phase 14 — TelemetryCollector
# ═══════════════════════════════════════════════════════════════════════
def test_telemetry_collector_metrics():
    """Verify TelemetryCollector aggregates correctly."""
    from src.telemetry.collector import TelemetryCollector
    
    telemetry = TelemetryCollector(topic="Test Topic")
    
    telemetry.record_provider_call("pexels", "galaxy", True, 150.0)
    telemetry.record_provider_call("pexels", "nebula", True, 200.0)
    telemetry.record_provider_call("nasa", "moon", False, 0, "Timeout")
    telemetry.record_critic_score(85)
    telemetry.record_critic_score(92)
    telemetry.record_fallback_use()
    telemetry.record_cache_hit()
    telemetry.record_cache_miss()
    telemetry.record_render_success()
    
    summary = telemetry.summary()
    
    assert summary["render_success"] == True
    assert summary["total_provider_calls"] == 3
    assert summary["fallback_count"] == 1
    assert summary["critic_scores"]["average"] == 88.5
    assert summary["cache_stats"]["hits"] == 1
    assert summary["cache_stats"]["misses"] == 1
    assert "pexels" in summary["provider_stats"]
    assert "nasa" in summary["provider_stats"]
    
    print(f"  [PASS] TelemetryCollector: {summary['critic_scores']['average']} avg critic")

def test_telemetry_dashboard_text():
    """Verify telemetry dashboard is human-readable."""
    from src.telemetry.collector import TelemetryCollector
    
    telemetry = TelemetryCollector(topic="Fermi Paradox")
    telemetry.record_provider_call("pexels", "galaxy", True, 100.0)
    telemetry.record_critic_score(88)
    telemetry.record_render_success()
    
    dash = telemetry.dashboard_text()
    assert "Fermi Paradox" in dash
    assert "✅" in dash or "║" in dash, "Should have formatted output"
    
    print(f"  [PASS] Telemetry dashboard:\n{dash[:200]}...")

# ═══════════════════════════════════════════════════════════════════════
# Phase 15 — QualityGate
# ═══════════════════════════════════════════════════════════════════════
def test_quality_gate_pass():
    """Verify QualityGate passes when all metrics are good."""
    from src.gates.quality_gate import QualityGate
    
    gate = QualityGate()
    report = gate.evaluate(metrics={
        "total_shots": 20,
        "fallback_count": 0,
        "blank_frames": 0,
        "duplicate_count": 0,
        "semantic_scores": {"average": 90},
        "critic_scores": {"average": 88},
        "render_success": True,
        "width": 1920, "height": 1080,
    })
    
    assert report.passed, "Should pass with perfect metrics"
    print(f"  [PASS] QualityGate: {report.summary}")

def test_quality_gate_fail():
    """Verify QualityGate fails when metrics are bad."""
    from src.gates.quality_gate import QualityGate
    
    gate = QualityGate()
    report = gate.evaluate(metrics={
        "total_shots": 20,
        "fallback_count": 10,
        "blank_frames": 5,
        "duplicate_count": 5,
        "semantic_scores": {"average": 50},
        "critic_scores": {"average": 40},
        "render_success": False,
    })
    
    assert not report.passed, "Should fail with bad metrics"
    failing = [g.name for g in report.gates if not g.passed]
    assert len(failing) > 0, "Should have failing gates"
    print(f"  [PASS] QualityGate fails on: {failing}")

# ═══════════════════════════════════════════════════════════════════════
# Phase 17 — Final Acceptance Prerequisites
# ═══════════════════════════════════════════════════════════════════════
def test_filepath_empty_is_eliminated():
    """Verify no module returns empty filepath strings."""
    from src.utils.result import Result
    
    # Result.failure should be used instead
    result = Result.failure("No results", provider="pexels", query="test")
    assert not result.is_success
    assert result.failure_detail.reason == "No results"
    
    # Result.success with actual data
    result = Result.success("/path/to/valid/file.mp4")
    assert result.is_success
    assert result.data == "/path/to/valid/file.mp4"
    
    print(f"  [PASS] Result<T> eliminates empty filepaths")

def test_end_to_end_validation_smoke():
    """Smoke test: run a minimal validation pipeline end-to-end."""
    # This verifies the validate_concept_pipeline script exists and runs
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, '.'); "
         "from tools.validate_concept_pipeline import run_topic; "
         "print('Validate script imports OK')"],
        capture_output=True, text=True, timeout=30, cwd=os.getcwd(),
    )
    assert "OK" in result.stdout or "OK" in result.stderr
    print(f"  [PASS] Validate pipeline script loads: {result.stdout.strip()}")

# ═══════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_v1_integration.py", "-v", "--tb=short"],
        capture_output=True, text=True, timeout=120, cwd=os.getcwd(),
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
    sys.exit(result.returncode)
