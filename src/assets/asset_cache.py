"""
asset_cache.py — Managed SQLite asset cache for the video_engine pipeline.

Caches downloaded media assets (videos, images, audio) keyed by
(provider, search_query).  Provides LRU eviction when the total cached
file size exceeds a configurable limit.

v13: the pipeline now runs the director stage with multiple worker threads
(parallel per-scene asset search).  SQLite connections are NOT shareable
across threads by default ("SQLite objects created in a thread can only be
used in that same thread"), so this cache uses a THREAD-LOCAL connection
per thread plus a write lock for serialized inserts/updates.
"""

import os
import sqlite3
import threading
import time
from typing import Optional

from src.utils.config import get_config


class AssetCache:
    """
    SQLite-backed asset cache with use-count tracking and LRU cleanup.

    Schema
    ------
    assets —
        provider      TEXT      — provider name (e.g. "pexels")
        search_query  TEXT      — search string used to fetch the asset
        asset_url     TEXT      — original remote URL
        local_path    TEXT      — local file path (nullable until downloaded)
        use_count     INTEGER   — number of times the asset has been used
        last_used     REAL      — unix timestamp of most recent access
        created_at    REAL      — unix timestamp of first registration

    Primary key is (provider, search_query) — one cached result per query.
    """

    def __init__(self, db_path: Optional[str] = None, max_size_mb: Optional[int] = None):
        self._db_path = db_path or os.path.abspath(
            get_config("pipeline.cache_db", "cache/asset_cache.db")
        )
        self._max_size_mb = max_size_mb or get_config("pipeline.cache_max_size_mb", 500)

        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        # v13: thread-local connections — worker threads each get their own
        # connection to the same DB file (SQLite handles cross-connection
        # locking); a write lock serializes inserts/updates.
        self._local = threading.local()
        self._write_lock = threading.Lock()
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        """Return this thread's dedicated connection (created lazily)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self._db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    # ── Public API ─────────────────────────────────────────────────────

    def lookup(self, provider: str, query: str) -> Optional[dict]:
        """
        Look up a cached asset by provider and search query.

        Returns a dict with keys *asset_url*, *local_path* if found AND the
        local file still exists on disk.  Returns None on miss.
        """
        conn = self._conn()
        cur = conn.execute(
            "SELECT asset_url, local_path FROM assets WHERE provider=? AND search_query=?",
            (provider, query),
        )
        row = cur.fetchone()
        if row is not None and row["local_path"] and os.path.exists(row["local_path"]):
            return {"asset_url": row["asset_url"], "local_path": row["local_path"]}
        return None

    def register(self, provider: str, query: str, asset_url: str, local_path: Optional[str] = None) -> None:
        """
        Insert or update an asset record (upsert on (provider, search_query)).

        Called at search time (without *local_path*) to reserve the entry,
        and again at download time (with *local_path*) to record the file.
        """
        with self._write_lock:
            conn = self._conn()
            conn.execute(
                """INSERT INTO assets (provider, search_query, asset_url, local_path, use_count, last_used)
                   VALUES (?, ?, ?, ?, 1, ?)
                   ON CONFLICT(provider, search_query) DO UPDATE SET
                       asset_url       = excluded.asset_url,
                       local_path      = COALESCE(excluded.local_path, assets.local_path),
                       use_count       = use_count + 1,
                       last_used       = ?""",
                (provider, query, asset_url, local_path, time.time(), time.time()),
            )
            conn.commit()

    def update_local_path(self, provider: str, query: str, asset_url: str, local_path: str) -> None:
        """
        Set the local_path for the row identified by the primary key
        ``(provider, search_query)``.

        Called from download() after the file has been written to disk.
        Uses the full primary key so that different queries returning the
        same remote URL each get their own local_path.
        """
        with self._write_lock:
            conn = self._conn()
            conn.execute(
                """UPDATE assets
                   SET local_path=?, use_count=use_count+1, last_used=?
                   WHERE provider=? AND search_query=?""",
                (local_path, time.time(), provider, query),
            )
            conn.commit()

    def touch(self, provider: str, query: str) -> None:
        """
        Increment use_count and refresh last_used for the asset identified
        by its primary key ``(provider, search_query)``.
        """
        with self._write_lock:
            conn = self._conn()
            conn.execute(
                "UPDATE assets SET use_count=use_count+1, last_used=? WHERE provider=? AND search_query=?",
                (time.time(), provider, query),
            )
            conn.commit()

    def cleanup(self) -> int:
        """
        LRU eviction: delete the least-recently-used cached files until the
        total on-disk size is within *max_size_mb*.

        Returns the number of files deleted.
        """
        with self._write_lock:
            conn = self._conn()
            max_bytes = self._max_size_mb * 1024 * 1024
            rows = conn.execute(
                "SELECT local_path FROM assets WHERE local_path IS NOT NULL ORDER BY last_used ASC"
            ).fetchall()

            total = 0
            paths: list[str] = []
            for (row,) in rows:
                try:
                    total += os.path.getsize(row)
                    paths.append(row)
                except OSError:
                    # File gone; clean up the db row too
                    conn.execute("DELETE FROM assets WHERE local_path=?", (row,))
                    continue

            if total <= max_bytes:
                conn.commit()
                return 0

            deleted = 0
            for path in paths:
                if total <= max_bytes:
                    break
                try:
                    sz = os.path.getsize(path)
                    os.remove(path)
                    total -= sz
                    deleted += 1
                    conn.execute("DELETE FROM assets WHERE local_path=?", (path,))
                except OSError:
                    continue

            conn.commit()
            return deleted

    def close(self) -> None:
        """Close this thread's connection (safe to call from any thread)."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass
            self._local.conn = None

    # ── Internals ───────────────────────────────────────────────────────

    def _init_db(self) -> None:
        with self._write_lock:
            conn = self._conn()
            conn.execute(
                """CREATE TABLE IF NOT EXISTS assets (
                    provider      TEXT    NOT NULL,
                    search_query  TEXT    NOT NULL,
                    asset_url     TEXT    NOT NULL,
                    local_path    TEXT,
                    use_count     INTEGER NOT NULL DEFAULT 0,
                    last_used     REAL,
                    created_at    REAL    DEFAULT (strftime('%s', 'now')),
                    PRIMARY KEY (provider, search_query)
                )"""
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_url ON assets(asset_url)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_assets_last_used ON assets(last_used)"
            )
            conn.commit()
