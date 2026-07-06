# Memory Manager

The **Memory Manager** (`src/memory/memory_manager.py`) provides a structured,
SQLite-backed memory layer for the video_engine pipeline.  It stores only
**structured facts** — no chat history, no LLM conversations, no reasoning,
and no transient execution state.

---

## Database Schema

The memory database (`cache/memory.db` by default) contains six tables:

### `project_settings`

Key-value store for project-wide configuration and state.

| Column | Type | Description |
|--------|------|-------------|
| `key` | `TEXT PK` | Setting name |
| `value` | `TEXT` | JSON-serialised value |
| `created_at` | `REAL` | Unix timestamp |
| `updated_at` | `REAL` | Unix timestamp |

### `channel_profiles`

YouTube channel metadata (reserved for future use).

| Column | Type | Description |
|--------|------|-------------|
| `channel_id` | `TEXT PK` | YouTube channel ID |
| `name` | `TEXT` | Channel name |
| `niche` | `TEXT` | Content niche |
| `target_audience` | `TEXT` | Target demographics |
| `created_at` | `REAL` | Unix timestamp |
| `updated_at` | `REAL` | Unix timestamp |

### `prompt_library`

Versioned repository of prompt templates.

| Column | Type | Description |
|--------|------|-------------|
| `prompt_id` | `INTEGER PK` | Auto-increment ID |
| `name` | `TEXT` | Prompt name (e.g. `"planner"`) |
| `category` | `TEXT` | Prompt category |
| `template` | `TEXT` | Prompt template body |
| `version` | `INTEGER` | Version number |
| `created_at` | `REAL` | Unix timestamp |
| `updated_at` | `REAL` | Unix timestamp |

### `video_history`

Record of every video produced by the pipeline.

| Column | Type | Description |
|--------|------|-------------|
| `video_id` | `INTEGER PK` | Auto-increment ID |
| `topic` | `TEXT` | Video topic |
| `plan_json` | `TEXT` | Full plan JSON |
| `timeline_json` | `TEXT` | Timeline JSON |
| `output_path` | `TEXT` | Path to output file |
| `duration_seconds` | `REAL` | Video duration |
| `file_size_bytes` | `INTEGER` | Output file size |
| `approved` | `BOOLEAN` | Critic approval status |
| `iterations` | `INTEGER` | Number of planner iterations |
| `status` | `TEXT` | Pipeline status |
| `created_at` | `REAL` | Unix timestamp |
| `updated_at` | `REAL` | Unix timestamp |

### `asset_history`

Log of every asset fetched by a provider.

| Column | Type | Description |
|--------|------|-------------|
| `asset_id` | `INTEGER PK` | Auto-increment ID |
| `video_id` | `INTEGER FK` | FK → `video_history.video_id` |
| `provider` | `TEXT` | Provider name (`"pexels"`) |
| `search_query` | `TEXT` | Search string |
| `asset_url` | `TEXT` | Remote URL |
| `local_path` | `TEXT` | Local file path |
| `file_size_bytes` | `INTEGER` | File size on disk |
| `created_at` | `REAL` | Unix timestamp |

### `execution_history`

Audit trail of pipeline runs.

| Column | Type | Description |
|--------|------|-------------|
| `run_id` | `INTEGER PK` | Auto-increment ID |
| `topic` | `TEXT` | Topic processed |
| `status` | `TEXT` | `"running"`, `"success"`, `"failed"` |
| `duration_seconds` | `REAL` | Wall-clock duration |
| `iteration_count` | `INTEGER` | Critic loop count |
| `critic_approved` | `BOOLEAN` | Final critic decision |
| `error_message` | `TEXT` | Error details on failure |
| `created_at` | `REAL` | Unix timestamp |

---

## Indexes

| Index | Table | Columns | Purpose |
|-------|-------|---------|---------|
| `idx_video_created` | `video_history` | `created_at DESC` | Recent-video queries |
| `idx_video_topic` | `video_history` | `topic` | Topic-based lookups |
| `idx_asset_video` | `asset_history` | `video_id` | Asset-by-video joins |
| `idx_asset_provider` | `asset_history` | `provider` | Provider-based queries |
| `idx_exec_created` | `execution_history` | `created_at DESC` | Recent-run queries |
| `idx_prompt_name` | `prompt_library` | `name` | Name-based prompt lookups |
| `idx_prompt_category` | `prompt_library` | `category` | Category filtered queries |

---

## Responsibilities

- **project_settings** — persists pipeline configuration overrides between runs.
- **channel_profiles** — stores YouTube channel metadata for future publisher integration.
- **prompt_library** — provides versioned prompt templates for the planner and critic.
- **video_history** — records every produced video for analytics and traceability.
- **asset_history** — logs every provider asset fetch for cost/usage tracking.
- **execution_history** — provides an audit trail for pipeline runs.

---

## Cleanup Policy

`MemoryManager.cleanup()` applies three retention rules:

| Rule | Table | Behaviour |
|------|-------|-----------|
| Age-based | `execution_history` | Delete rows older than `retention_days` |
| Size-based | `execution_history` | Keep only the most recent `max_execution_logs` rows |
| Orphan removal | `asset_history` | Delete rows whose `video_id` references a deleted video |

### Configuration

| Config key | Default | Description |
|------------|---------|-------------|
| `pipeline.memory.db_path` | `"cache/memory.db"` | SQLite database path |
| `pipeline.memory.retention_days` | `90` | Execution history retention |
| `pipeline.memory.max_execution_logs` | `1000` | Max execution log entries |
| `pipeline.memory.cleanup_interval_runs` | `10` | Runs between cleanup cycles (reserved) |

---

## What Is Intentionally NOT Stored

The Memory Manager explicitly avoids storing:

- **Chat history** — no Slack, Telegram, or Signal conversations.
- **LLM conversations** — no raw LLM request/response pairs.
- **Reasoning / chain-of-thought** — no internal agent reasoning traces.
- **Transient execution state** — no LangGraph checkpoint data.
- **Audio or video binary data** — only metadata and file paths.
- **API keys or secrets** — those remain in `.env` only.

---

## Future: Semantic Memory Integration

The current implementation is **episodic / factual** — it stores what happened,
not what was learned.  A future semantic memory layer could:

- Use embeddings + vector search (e.g. SQLite `vec0` or ChromaDB).
- Store lessons from failed critic reviews.
- Enable the planner to recall and reuse effective search queries.
- Provide RAG context to the planner and critic.

The `prompt_library` and `project_settings` tables are designed to serve as
the bridge: semantic insights can be persisted as settings or as tagged prompts
without schema changes.
