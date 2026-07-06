# Build Artifacts — video_engine

## Overview

Certain files produced during pipeline execution are **generated artifacts**
and are deliberately excluded from version control.  This document lists
each artifact, explains why it is not committed, and how it is produced.

## Generated Artifacts

| File / Pattern    | Source                              | Reason Not Committed            |
|-------------------|-------------------------------------|---------------------------------|
| `timeline.json`   | Node 2 — Timeline Builder           | Regenerated every pipeline run  |
| `final_output.mp4`| Node 3 — MoviePy Renderer           | Large binary (~70 MB)           |
| `cache/`          | Pexels downloads + TTS audio        | Repopulated on cache miss       |
| `.coverage`       | `pytest --cov` report data          | Developer-only tooling          |
| `*.mp4`           | Various (render output, clips)      | Large, regenerable              |
| `*.wav / *.mp3`   | Kokoro TTS output                   | Regenerated on cache miss       |
| `*.onnx`          | Kokoro TTS model files              | Not part of source              |
| `voices.bin`      | Kokoro voice embeddings             | Not part of source              |
| `__pycache__/`    | Python bytecode cache               | Standard Python practice        |
| `venv/`           | Virtual environment                 | Reproducible via `requirements.txt` |

## Why `timeline.json` Is Not Tracked

`timeline.json` is written by the `TimelineBuilder` during every pipeline run.
Its contents depend on:

- The planner's generated scene list (different each run)
- The exact durations of downloaded audio files
- The exact durations of downloaded video files

Committing it would:

1. Leave the working tree dirty after every pipeline run.
2. Create noise in `git status` that obscures real changes.
3. Risk reverting a stale timeline onto disk via `git checkout`.

## Determining What to Ignore

When adding a new generated artifact to the pipeline:

1. Confirm it is produced by a pipeline node, not written by hand.
2. Add a pattern or filename to `.gitignore`.
3. If it was previously tracked, run `git rm --cached <file>`.
4. Verify `git status` is clean after a full pipeline run.

## Related

- `.gitignore` — all ignore rules live here
- `configs/pipeline.yaml` — output paths for generated files
