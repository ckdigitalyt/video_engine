"""
test_evaluator.py — Tests for the Evaluation & Benchmark Framework.

Verifies:
- MetricsCollector timing, asset recording, snapshot assembly
- ReportGenerator JSON, CSV, Markdown output
- EvaluationEngine orchestration
- Config parsing
- Edge cases (zero values, empty timelines, disabled metrics)
"""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.evaluator import EvaluationEngine, MetricsCollector, ReportGenerator
from src.evaluator.metrics import EvalSnapshot


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def sample_snapshot() -> EvalSnapshot:
    return EvalSnapshot(
        planning_time_s=2.5,
        execution_time_s=15.3,
        render_time_s=45.2,
        critic_time_s=3.1,
        total_time_s=66.1,
        cache_hits=12,
        cache_misses=3,
        library_reuses=5,
        downloads_attempted=8,
        downloads_succeeded=7,
        downloads_avoided=5,
        scene_count=10,
        total_narration_words=350,
        avg_narration_words_per_scene=35.0,
        total_estimated_duration=120.0,
        avg_estimated_duration=12.0,
        avg_search_query_length=28.5,
        unique_search_queries=10,
        duplicate_search_query_count=0,
        subtitle_word_count=280,
        subtitle_clip_count=60,
        output_resolution="1920x1080",
        output_fps=30,
        final_duration_s=115.3,
        output_file_size_bytes=65_000_000,
        output_path="final_output.mp4",
        critic_approved=True,
        iteration_count=1,
        num_transitions_non_cut=6,
        motion_types_used=["zoom_in", "pan_left", "none"],
        tags={"topic": "Fermi Paradox", "template": "documentary"},
    )


# ── MetricsCollector ──────────────────────────────────────────────────────


class TestMetricsCollector:
    def test_start_stop_records_time(self) -> None:
        mc = MetricsCollector()
        mc.start("planning")
        mc.stop("planning")
        assert mc.elapsed("planning") > 0

    def test_no_stop_returns_zero(self) -> None:
        mc = MetricsCollector()
        assert mc.elapsed("render") == 0.0

    def test_unknown_phase_returns_zero(self) -> None:
        mc = MetricsCollector()
        assert mc.elapsed("nonexistent") == 0.0

    def test_asset_counters(self) -> None:
        mc = MetricsCollector()
        mc.record_cache_hit()
        mc.record_cache_hit()
        mc.record_cache_miss()
        mc.record_reuse()
        mc.record_download(True)
        mc.record_download(False)

        snap = mc.snapshot()
        assert snap.cache_hits == 2
        assert snap.cache_misses == 1
        assert snap.library_reuses == 1
        assert snap.downloads_attempted == 2
        assert snap.downloads_succeeded == 1
        assert snap.downloads_avoided == 1

    def test_snapshot_scene_metrics(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(
            scene_count=5,
            narration_words=150,
            estimated_duration=60.0,
        )
        assert snap.scene_count == 5
        assert snap.total_narration_words == 150
        assert snap.avg_narration_words_per_scene == 30.0
        assert snap.total_estimated_duration == 60.0
        assert snap.avg_estimated_duration == 12.0

    def test_snapshot_search_queries(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(
            search_query_lengths=[25, 30, 35],
            duplicate_queries=0,
        )
        assert snap.avg_search_query_length == 30.0
        assert snap.unique_search_queries == 3

    def test_snapshot_zero_scene_no_division_error(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(scene_count=0)
        assert snap.avg_narration_words_per_scene == 0.0
        assert snap.avg_estimated_duration == 0.0

    def test_snapshot_effect_metrics(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(num_transitions=4, motion_types=["zoom_in", "pan_left"])
        assert snap.num_transitions_non_cut == 4
        assert snap.motion_types_used == ["zoom_in", "pan_left"]

    def test_snapshot_output_metrics(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(
            resolution="3840x2160",
            fps=60,
            final_duration=120.5,
            file_size=100_000_000,
            output_path="test.mp4",
        )
        assert snap.output_resolution == "3840x2160"
        assert snap.output_fps == 60
        assert snap.final_duration_s == 120.5
        assert snap.output_file_size_bytes == 100_000_000
        assert snap.output_path == "test.mp4"

    def test_snapshot_critic(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(critic_approved=True, iterations=2)
        assert snap.critic_approved is True
        assert snap.iteration_count == 2

    def test_snapshot_tags(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(tags={"env": "test"})
        assert snap.tags == {"env": "test"}

    def test_reset_clears_all(self) -> None:
        mc = MetricsCollector()
        mc.start("planning")
        mc.stop("planning")
        mc.record_cache_hit()
        mc.reset()
        snap = mc.snapshot()
        assert snap.planning_time_s == 0.0
        assert snap.cache_hits == 0

    def test_stop_without_start_no_error(self) -> None:
        mc = MetricsCollector()
        mc.stop("render")  # should not raise

    def test_stop_all_phases_then_total(self) -> None:
        mc = MetricsCollector()
        for phase in ("planning", "execution", "render", "critic"):
            mc.start(phase)
            mc.stop(phase)
        snap = mc.snapshot()
        assert snap.total_time_s > 0


# ── ReportGenerator ───────────────────────────────────────────────────────


class TestReportGenerator:
    def test_to_json_creates_file(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_json(sample_snapshot)
        assert os.path.exists(path)

    def test_to_json_valid_content(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_json(sample_snapshot)
        with open(path) as f:
            data = json.load(f)
        assert data["planning_time_s"] == 2.5
        assert data["scene_count"] == 10
        assert data["critic_approved"] is True
        assert "_generated_at" in data
        assert "_report_format" in data

    def test_to_csv_creates_file(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_csv(sample_snapshot)
        assert os.path.exists(path)

    def test_to_csv_content(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_csv(sample_snapshot)
        with open(path) as f:
            rows = f.readlines()
        assert len(rows) > 1  # header + data rows
        assert any("planning_time_s" in row for row in rows)
        assert any("scene_count" in row for row in rows)

    def test_to_markdown_creates_file(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_markdown(sample_snapshot)
        assert os.path.exists(path)

    def test_to_markdown_contains_sections(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_markdown(sample_snapshot)
        with open(path) as f:
            text = f.read()
        assert "## Performance" in text
        assert "## Asset Pipeline" in text
        assert "## Scene" in text
        assert "## Search Queries" in text
        assert "## Subtitles" in text
        assert "## Output Video" in text
        assert "## Effects" in text
        assert "## Critic" in text

    def test_to_markdown_metrics_values(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        path = rg.to_markdown(sample_snapshot)
        with open(path) as f:
            text = f.read()
        assert "2.50" in text
        assert "115.30s" in text
        assert "62.0 MB" in text

    def test_custom_output_dir(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        custom = str(tmp_path / "my_reports")
        rg = ReportGenerator(output_dir=custom)
        path = rg.to_json(sample_snapshot)
        assert custom in path
        assert os.path.exists(path)

    def test_flatten_nested_dict(self) -> None:
        flat = ReportGenerator._flatten({"a": {"b": 1, "c": "x"}, "d": [1, 2]})
        assert flat["a.b"] == 1
        assert flat["a.c"] == "x"
        assert "d" in flat


# ── EvaluationEngine ─────────────────────────────────────────────────────


class TestEvaluationEngine:
    def test_orchestrates_collector_and_reporter(self, tmp_path: Path) -> None:
        engine = EvaluationEngine(
            report_generator=ReportGenerator(output_dir=str(tmp_path)),
        )
        engine.start_phase("planning")
        engine.stop_phase("planning")
        engine.record_cache_hit()
        snap = engine.evaluate(scene_count=3)
        assert snap.planning_time_s > 0
        assert snap.cache_hits == 1
        assert snap.scene_count == 3

    def test_export_reports(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        engine = EvaluationEngine(
            report_generator=ReportGenerator(output_dir=str(tmp_path)),
        )
        # Manually set snapshot
        engine._snapshot = sample_snapshot
        paths = engine.export_reports(formats=["json", "csv", "md"])
        assert "json" in paths
        assert "csv" in paths
        assert "md" in paths
        for p in paths.values():
            assert os.path.exists(p)

    def test_export_no_snapshot_raises(self) -> None:
        engine = EvaluationEngine()
        with pytest.raises(ValueError, match="No snapshot to export"):
            engine.export_reports()

    def test_reset(self) -> None:
        engine = EvaluationEngine()
        engine.start_phase("planning")
        engine.stop_phase("planning")
        engine.reset()
        assert engine.collector.elapsed("planning") == 0.0
        assert engine._snapshot is None

    def test_record_reuse(self) -> None:
        engine = EvaluationEngine()
        engine.record_reuse()
        snap = engine.evaluate()
        assert snap.library_reuses == 1
        assert snap.downloads_avoided == 1

    def test_record_download(self) -> None:
        engine = EvaluationEngine()
        engine.record_download(True)
        engine.record_download(False)
        snap = engine.evaluate()
        assert snap.downloads_attempted == 2
        assert snap.downloads_succeeded == 1

    def test_cache_helpers(self) -> None:
        engine = EvaluationEngine()
        engine.record_cache_hit()
        engine.record_cache_miss()
        snap = engine.evaluate()
        assert snap.cache_hits == 1
        assert snap.cache_misses == 1


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_snapshot(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot()
        assert snap.planning_time_s == 0.0
        assert snap.scene_count == 0
        assert snap.cache_hits == 0

    def test_metrics_collector_reuse(self) -> None:
        mc = MetricsCollector()
        s1 = mc.snapshot(scene_count=5)
        s2 = mc.snapshot(scene_count=10)
        assert s2.scene_count == 10  # snapshot is fresh each time

    def test_report_formats_all(self, tmp_path: Path, sample_snapshot: EvalSnapshot) -> None:
        rg = ReportGenerator(output_dir=str(tmp_path))
        p1 = rg.to_json(sample_snapshot)
        p2 = rg.to_csv(sample_snapshot)
        p3 = rg.to_markdown(sample_snapshot)
        assert os.path.getsize(p1) > 0
        assert os.path.getsize(p2) > 0
        assert os.path.getsize(p3) > 0

    def test_config_loading(self, tmp_project: Path) -> None:
        from src.utils.config import get_config
        assert get_config("evaluator.output_dir") is not None
        assert get_config("evaluator.default_formats") is not None
        assert get_config("evaluator.metrics.performance") is True

    def test_large_file_size(self) -> None:
        mc = MetricsCollector()
        snap = mc.snapshot(file_size=1_500_000_000)
        assert snap.output_file_size_bytes == 1_500_000_000
