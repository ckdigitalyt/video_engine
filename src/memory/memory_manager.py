"""
memory_manager.py — Structured memory layer for the video_engine pipeline.

Stores only structured facts (project settings, video/asset history, prompts,
execution logs).  Does NOT store chat history, LLM conversations, reasoning,
or transient execution state.
"""

import os
import json
import sqlite3
import time
from typing import Any, Optional


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS project_settings (
    key         TEXT    PRIMARY KEY,
    value       TEXT    NOT NULL,
    created_at  REAL    NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at  REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS channel_profiles (
    channel_id      TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL DEFAULT '',
    niche           TEXT    NOT NULL DEFAULT '',
    target_audience TEXT    NOT NULL DEFAULT '',
    created_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS prompt_library (
    prompt_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL,
    category    TEXT    NOT NULL DEFAULT 'general',
    template    TEXT    NOT NULL,
    version     INTEGER NOT NULL DEFAULT 1,
    created_at  REAL    NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at  REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS video_history (
    video_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT    NOT NULL,
    plan_json       TEXT,
    timeline_json   TEXT,
    output_path     TEXT,
    duration_seconds REAL,
    file_size_bytes  INTEGER,
    approved        BOOLEAN,
    iterations      INTEGER DEFAULT 0,
    status          TEXT    NOT NULL DEFAULT 'pending',
    created_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now')),
    updated_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS asset_history (
    asset_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id        INTEGER REFERENCES video_history(video_id) ON DELETE SET NULL,
    provider        TEXT    NOT NULL,
    search_query    TEXT    NOT NULL DEFAULT '',
    asset_url       TEXT    NOT NULL DEFAULT '',
    local_path      TEXT,
    file_size_bytes INTEGER,
    created_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE TABLE IF NOT EXISTS execution_history (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic           TEXT,
    status          TEXT    NOT NULL DEFAULT 'running',
    duration_seconds REAL,
    iteration_count INTEGER DEFAULT 0,
    critic_approved BOOLEAN,
    error_message   TEXT,
    created_at      REAL    NOT NULL DEFAULT (strftime('%s', 'now'))
);
"""

INDEXES_SQL = [
    "CREATE INDEX IF NOT EXISTS idx_video_created ON video_history(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_video_topic ON video_history(topic)",
    "CREATE INDEX IF NOT EXISTS idx_asset_video ON asset_history(video_id)",
    "CREATE INDEX IF NOT EXISTS idx_asset_provider ON asset_history(provider)",
    "CREATE INDEX IF NOT EXISTS idx_exec_created ON execution_history(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_prompt_name ON prompt_library(name)",
    "CREATE INDEX IF NOT EXISTS idx_prompt_category ON prompt_library(category)",
]


class MemoryManager:
    """
    SQLite-backed structured memory for the video_engine pipeline.

    Stores project settings, channel profiles, prompts, video/asset history,
    and execution logs.  Designed for facts, not conversations.
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or "cache/memory.db"
        os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        self._conn = sqlite3.connect(self._db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    # ── Lifecycle ──────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create all tables and indexes if they do not exist."""
        self._conn.executescript(SCHEMA_SQL)
        for idx in INDEXES_SQL:
            self._conn.execute(idx)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def cleanup(
        self,
        retention_days: int = 90,
        max_exec_logs: int = 1000,
    ) -> dict[str, int]:
        """
        Remove stale records according to the configured retention policy.

        Args:
            retention_days: Remove execution_history older than this many days.
            max_exec_logs:  Trim execution_history to at most this many rows.

        Returns:
            Dict with count of deleted rows per table.
        """
        cutoff = time.time() - (retention_days * 86400)
        deleted: dict[str, int] = {}

        # Old execution logs
        cur = self._conn.execute(
            "DELETE FROM execution_history WHERE created_at < ?", (cutoff,)
        )
        deleted["execution_history (age)"] = cur.rowcount

        # Trim execution logs to max rows (keep newest)
        cur = self._conn.execute(
            "DELETE FROM execution_history WHERE run_id NOT IN "
            "(SELECT run_id FROM execution_history ORDER BY created_at DESC LIMIT ?)",
            (max_exec_logs,),
        )
        deleted["execution_history (size)"] = cur.rowcount

        # Orphan asset_history rows (video_id deleted)
        cur = self._conn.execute(
            "DELETE FROM asset_history WHERE video_id IS NOT NULL "
            "AND video_id NOT IN (SELECT video_id FROM video_history)"
        )
        deleted["asset_history (orphans)"] = cur.rowcount

        self._conn.commit()
        return deleted

    # ── Project settings ────────────────────────────────────────────────

    def get_project_setting(self, key: str, default: Any = None) -> Any:
        cur = self._conn.execute(
            "SELECT value FROM project_settings WHERE key = ?", (key,)
        )
        row = cur.fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return row[0]

    def set_project_setting(self, key: str, value: Any) -> None:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        self._conn.execute(
            """INSERT INTO project_settings (key, value, created_at, updated_at)
               VALUES (?, ?, strftime('%s', 'now'), strftime('%s', 'now'))
               ON CONFLICT(key) DO UPDATE SET
                   value      = excluded.value,
                   updated_at = strftime('%s', 'now')""",
            (key, serialized),
        )
        self._conn.commit()

    # ── Video history ───────────────────────────────────────────────────

    def save_video(
        self,
        topic: str,
        plan_json: Optional[str] = None,
        timeline_json: Optional[str] = None,
        output_path: Optional[str] = None,
        duration_seconds: Optional[float] = None,
        file_size_bytes: Optional[int] = None,
        approved: Optional[bool] = None,
        iterations: int = 0,
        status: str = "pending",
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO video_history
               (topic, plan_json, timeline_json, output_path,
                duration_seconds, file_size_bytes, approved,
                iterations, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (topic, plan_json, timeline_json, output_path,
             duration_seconds, file_size_bytes, approved,
             iterations, status),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_video(self, video_id: int) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT * FROM video_history WHERE video_id = ?", (video_id,)
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    def get_recent_videos(self, limit: int = 10) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM video_history ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [dict(r) for r in cur.fetchall()]

    # ── Asset history ───────────────────────────────────────────────────

    def register_asset_use(
        self,
        provider: str,
        search_query: str = "",
        asset_url: str = "",
        local_path: Optional[str] = None,
        file_size_bytes: Optional[int] = None,
        video_id: Optional[int] = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO asset_history
               (video_id, provider, search_query, asset_url, local_path, file_size_bytes)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (video_id, provider, search_query, asset_url, local_path, file_size_bytes),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_asset_history(
        self,
        provider: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        if provider:
            cur = self._conn.execute(
                "SELECT * FROM asset_history WHERE provider = ? ORDER BY created_at DESC LIMIT ?",
                (provider, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT * FROM asset_history ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [dict(r) for r in cur.fetchall()]

    # ── Prompt library ──────────────────────────────────────────────────

    def save_prompt(
        self,
        name: str,
        template: str,
        category: str = "general",
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO prompt_library (name, category, template)
               VALUES (?, ?, ?)""",
            (name, category, template),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_prompt(self, name: str) -> Optional[dict]:
        cur = self._conn.execute(
            "SELECT * FROM prompt_library WHERE name = ? ORDER BY version DESC LIMIT 1",
            (name,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return dict(row)

    # ── Execution history ───────────────────────────────────────────────

    def log_execution(
        self,
        topic: Optional[str] = None,
        status: str = "running",
        duration_seconds: Optional[float] = None,
        iteration_count: int = 0,
        critic_approved: Optional[bool] = None,
        error_message: Optional[str] = None,
    ) -> int:
        cur = self._conn.execute(
            """INSERT INTO execution_history
               (topic, status, duration_seconds, iteration_count, critic_approved, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (topic, status, duration_seconds, iteration_count, critic_approved, error_message),
        )
        self._conn.commit()
        return cur.lastrowid
