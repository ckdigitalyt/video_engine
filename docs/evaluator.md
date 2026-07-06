# Evaluation & Benchmark Framework

## Overview

The evaluation framework collects performance, asset, quality, and output
metrics during pipeline execution and exports them as **JSON**, **CSV**, and
**Markdown** reports.

This makes improvements measurable, enables objective comparison across
planner/renderer changes, and detects regressions.

---

## Architecture

```
Pipeline Nodes
  │
  ├── planner_node ──────► EvaluationEngine.start_phase("planning")
  │                         EvaluationEngine.stop_phase("planning")
  │
  ├── execution_node ────► EvaluationEngine.start_phase("execution")
  │                         EvaluationEngine.record_cache_hit/miss/reuse/download()
  │                         EvaluationEngine.stop_phase("execution")
  │
  ├── render_node ───────► EvaluationEngine.start_phase("render")
  │                         EvaluationEngine.stop_phase("render")
  │
  └── critic_node ───────► EvaluationEngine.start_phase("critic")
                            EvaluationEngine.stop_phase("critic")

  ─────────────────────────────────────────────────────────
  Pipeline Complete
  │
  └──► EvaluationEngine.evaluate(scene_count=..., ...)
       EvaluationEngine.export_reports()
         ├── eval_report.json    (machine-parseable)
         ├── eval_report.csv     (spreadsheet-ready)
         └── eval_report.md      (human-readable)
```

### Components

| Component | File | Role |
|-----------|------|------|
| `MetricsCollector` | `src/evaluator/metrics.py` | Timing, asset counters, snapshot assembly |
| `ReportGenerator` | `src/evaluator/report.py` | JSON, CSV, Markdown export |
| `EvaluationEngine` | `src/evaluator/evaluator.py` | Orchestrates collection + reporting |

---

## Metrics Collected

### Performance (seconds)

| Metric | Description |
|--------|-------------|
| `planning_time_s` | Time spent in the planner node |
| `execution_time_s` | Time spent in the execution node (asset search, download, TTS) |
| `render_time_s` | Time spent in the renderer |
| `critic_time_s` | Time spent in the multimodal critic |
| `total_time_s` | Sum of all four phases |

### Asset Pipeline

| Metric | Description |
|--------|-------------|
| `cache_hits` | Assets found in the local cache |
| `cache_misses` | Assets not found in the local cache |
| `library_reuses` | Assets reused from the asset library |
| `downloads_attempted` | Total download attempts to external provider |
| `downloads_succeeded` | Successful downloads |
| `downloads_avoided` | Downloads avoided due to library reuse |

### Scene & Narration

| Metric | Description |
|--------|-------------|
| `scene_count` | Number of scenes in the plan |
| `total_narration_words` | Total words across all narrations |
| `avg_narration_words_per_scene` | Average narration words per scene |
| `total_estimated_duration` | Sum of all scene estimated durations |
| `avg_estimated_duration` | Average estimated duration per scene |

### Search Queries

| Metric | Description |
|--------|-------------|
| `avg_search_query_length` | Average character length of search queries |
| `unique_search_queries` | Number of unique queries |
| `duplicate_search_query_count` | Number of duplicate queries |

### Subtitles

| Metric | Description |
|--------|-------------|
| `subtitle_word_count` | Total words in generated subtitles |
| `subtitle_clip_count` | Number of subtitle clips rendered |

### Output Video

| Metric | Description |
|--------|-------------|
| `output_resolution` | Final video resolution (e.g. `"1920x1080"`) |
| `output_fps` | Frames per second |
| `final_duration_s` | Final video duration in seconds |
| `output_file_size_bytes` | File size in bytes |
| `output_path` | Path to the rendered video |

### Effects

| Metric | Description |
|--------|-------------|
| `num_transitions_non_cut` | Number of non-cut transitions used |
| `motion_types_used` | List of motion effect types applied |

### Critic

| Metric | Description |
|--------|-------------|
| `critic_approved` | Whether the video passed the critic (`True`/`False`) |
| `iteration_count` | Number of pipeline iterations |

---

## Configuration

```yaml
# configs/evaluator.yaml
evaluator:
  output_dir: "eval_reports"          # Directory for report files
  default_formats:                    # Which formats to generate
    - json
    - csv
    - md
  metrics:
    performance: true
    assets: true
    scenes: true
    subtitles: true
    effects: true
    output: true
    critic: true
```

---

## Report Formats

### JSON (`eval_report.json`)

Machine-parseable structured dump. Each key maps to a metric value, plus
`_generated_at` timestamp and `_report_format` identifier.

### CSV (`eval_report.csv`)

Two-column format (`metric, value`) suitable for loading into spreadsheets
or data analysis tools.

### Markdown (`eval_report.md`)

Human-readable report with section headings, metric tables, and summary
sections. Suitable for embedding in PRs or build artifacts.

---

## Usage

```python
from src.evaluator import EvaluationEngine

engine = EvaluationEngine()

# Time a phase
engine.start_phase("planning")
# ... planning work ...
engine.stop_phase("planning")

# Record asset events
engine.record_cache_hit()
engine.record_cache_miss()
engine.record_reuse()
engine.record_download(succeeded=True)

# Final evaluation
snap = engine.evaluate(
    scene_count=10,
    narration_words=350,
    estimated_duration=120,
    search_query_lengths=[25, 30, 35],
    duplicate_queries=0,
    subtitle_words=280,
    subtitle_clips=60,
    resolution="1920x1080",
    fps=30,
    final_duration=115.3,
    file_size=65_000_000,
    output_path="final_output.mp4",
    critic_approved=True,
    iterations=1,
    num_transitions=6,
    motion_types=["zoom_in", "pan_left"],
    tags={"topic": "Fermi Paradox", "template": "documentary"},
)

# Export all formats
paths = engine.export_reports()
print(f"JSON report:   {paths['json']}")
print(f"CSV report:    {paths['csv']}")
print(f"Markdown:      {paths['md']}")
```

---

## Extension Points

### New metrics
Add fields to the `EvalSnapshot` dataclass and pass them in `evaluate()`.

### New report formats
Subclass `ReportGenerator` and add a `to_<format>()` method. Register it
in `EvaluationEngine.export_reports()`.

### Custom tags
The `tags` dict on `EvalSnapshot` accepts arbitrary key-value pairs that
are included in all report formats.
