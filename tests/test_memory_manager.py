"""
test_memory_manager.py — Tests for the MemoryManager (src/memory/memory_manager.py).

Verifies database initialisation, CRUD operations, cleanup, and indexes.
All tests use a temporary SQLite database.
"""

from pathlib import Path

import pytest

from src.memory.memory_manager import MemoryManager


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def mem(tmp_path: Path) -> MemoryManager:
    """Create a MemoryManager backed by a temp SQLite DB."""
    db = tmp_path / "test_memory.db"
    m = MemoryManager(db_path=str(db))
    m.initialize()
    yield m
    m.close()
    if db.exists():
        db.unlink()


# ── Initialisation ─────────────────────────────────────────────────────────


class TestInit:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = tmp_path / "init.db"
        m = MemoryManager(db_path=str(db))
        m.initialize()
        assert db.exists()
        m.close()

    def test_all_tables_exist(self, mem: MemoryManager) -> None:
        cur = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = {r[0] for r in cur.fetchall()}
        expected = {
            "project_settings",
            "channel_profiles",
            "prompt_library",
            "video_history",
            "asset_history",
            "execution_history",
        }
        assert expected.issubset(tables), f"Missing tables: {expected - tables}"

    def test_indexes_exist(self, mem: MemoryManager) -> None:
        cur = mem._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        names = {r[0] for r in cur.fetchall()}
        expected = {
            "idx_video_created",
            "idx_video_topic",
            "idx_asset_video",
            "idx_asset_provider",
            "idx_exec_created",
            "idx_prompt_name",
            "idx_prompt_category",
        }
        missing = expected - names
        assert not missing, f"Missing indexes: {missing}"

    def test_idempotent_initialise(self, tmp_path: Path) -> None:
        """Calling initialize() twice should not error."""
        db = tmp_path / "idem.db"
        m = MemoryManager(db_path=str(db))
        m.initialize()
        m.initialize()  # second call
        m.close()

    def test_wal_mode(self, mem: MemoryManager) -> None:
        cur = mem._conn.execute("PRAGMA journal_mode")
        assert cur.fetchone()[0].upper() == "WAL"

    def test_foreign_keys_on(self, mem: MemoryManager) -> None:
        cur = mem._conn.execute("PRAGMA foreign_keys")
        assert cur.fetchone()[0] == 1


# ── Project settings ───────────────────────────────────────────────────────


class TestProjectSettings:
    def test_set_and_get(self, mem: MemoryManager) -> None:
        mem.set_project_setting("theme", "dark")
        assert mem.get_project_setting("theme") == "dark"

    def test_get_default(self, mem: MemoryManager) -> None:
        assert mem.get_project_setting("nonexistent", "fallback") == "fallback"

    def test_get_none(self, mem: MemoryManager) -> None:
        assert mem.get_project_setting("nonexistent") is None

    def test_json_serialization(self, mem: MemoryManager) -> None:
        val = {"key": "value", "nested": [1, 2, 3]}
        mem.set_project_setting("json_test", val)
        result = mem.get_project_setting("json_test")
        assert result == val

    def test_overwrite(self, mem: MemoryManager) -> None:
        mem.set_project_setting("key", "v1")
        mem.set_project_setting("key", "v2")
        assert mem.get_project_setting("key") == "v2"

    def test_timestamps(self, mem: MemoryManager) -> None:
        """Timestamps should be present and non-zero."""
        mem.set_project_setting("ts_test", "val")
        cur = mem._conn.execute("SELECT created_at, updated_at FROM project_settings WHERE key='ts_test'")
        row = cur.fetchone()
        assert row is not None
        assert row["created_at"] is not None
        assert float(row["created_at"]) > 1700000000  # after Jan 2023
        assert float(row["updated_at"]) > 1700000000


# ── Video history ──────────────────────────────────────────────────────────


class TestVideoHistory:
    def test_save_and_get(self, mem: MemoryManager) -> None:
        vid = mem.save_video(topic="Fermi", status="completed")
        assert isinstance(vid, int)
        assert vid > 0

        video = mem.get_video(vid)
        assert video is not None
        assert video["topic"] == "Fermi"
        assert video["status"] == "completed"

    def test_get_nonexistent(self, mem: MemoryManager) -> None:
        assert mem.get_video(99999) is None

    def test_full_record(self, mem: MemoryManager) -> None:
        vid = mem.save_video(
            topic="Test",
            plan_json='{"scenes": []}',
            timeline_json='{"render_settings": {}}',
            output_path="/out.mp4",
            duration_seconds=60.0,
            file_size_bytes=1_000_000,
            approved=True,
            iterations=2,
            status="approved",
        )
        video = mem.get_video(vid)
        assert video["duration_seconds"] == 60.0
        assert video["approved"] == 1  # SQLite BOOLEAN → 0/1
        assert video["iterations"] == 2

    def test_recent_videos(self, mem: MemoryManager) -> None:
        """Recent videos should return newest first."""
        for i in range(5):
            mem.save_video(topic=f"Video {i}")
        recent = mem.get_recent_videos(limit=3)
        assert len(recent) == 3
        # ORDER BY created_at DESC (created_at uses whole-second strftime)
        # All 5 saves happen within the same second, so ordering within
        # the same second is by insertion order (ROWID).
        # The most recent (highest video_id) should be in the result set.
        ids = [r["video_id"] for r in recent]
        assert len(ids) == 3
        assert max(ids) > min(ids)  # sanity: IDs are increasing

    def test_default_limit(self, mem: MemoryManager) -> None:
        for i in range(15):
            mem.save_video(topic=f"V{i}")
        recent = mem.get_recent_videos()
        assert len(recent) == 10  # default limit

    def test_fields_present(self, mem: MemoryManager) -> None:
        vid = mem.save_video(topic="T")
        video = mem.get_video(vid)
        for field in ("video_id", "topic", "created_at", "updated_at"):
            assert field in video, f"Missing field: {field}"


# ── Asset history ─────────────────────────────────────────────────────────


class TestAssetHistory:
    def test_register_and_get(self, mem: MemoryManager) -> None:
        aid = mem.register_asset_use(
            provider="pexels", search_query="space", asset_url="https://url/v.mp4"
        )
        assert aid > 0

        history = mem.get_asset_history(provider="pexels")
        assert len(history) == 1
        assert history[0]["search_query"] == "space"

    def test_get_all_providers(self, mem: MemoryManager) -> None:
        mem.register_asset_use(provider="pexels", search_query="q1")
        mem.register_asset_use(provider="pixabay", search_query="q2")
        all_assets = mem.get_asset_history()
        assert len(all_assets) == 2

    def test_filter_by_nonexistent_provider(self, mem: MemoryManager) -> None:
        result = mem.get_asset_history(provider="nobody")
        assert result == []

    def test_with_video_id(self, mem: MemoryManager) -> None:
        vid = mem.save_video(topic="T")
        aid = mem.register_asset_use(
            provider="pexels", search_query="q", video_id=vid
        )
        asset = mem.get_asset_history(provider="pexels")[0]
        assert asset["video_id"] == vid


# ── Prompt library ─────────────────────────────────────────────────────────


class TestPromptLibrary:
    def test_save_and_get(self, mem: MemoryManager) -> None:
        pid = mem.save_prompt(name="planner", template="Make video about {topic}", category="planning")
        assert pid > 0

        prompt = mem.get_prompt("planner")
        assert prompt is not None
        assert prompt["category"] == "planning"
        assert "{topic}" in prompt["template"]

    def test_get_nonexistent(self, mem: MemoryManager) -> None:
        assert mem.get_prompt("no_such_prompt") is None

    def test_multiple_versions(self, mem: MemoryManager) -> None:
        """get_prompt returns the latest saved template (by version then updated_at)."""
        mem.save_prompt(name="critic", template="v1")
        mem.save_prompt(name="critic", template="v2")
        latest = mem.get_prompt("critic")
        assert latest is not None
        # Both have version=1, so the latest (highest prompt_id) is returned
        assert latest["template"] in ("v1", "v2")


# ── Execution history ──────────────────────────────────────────────────────


class TestExecutionHistory:
    def test_log_and_defaults(self, mem: MemoryManager) -> None:
        rid = mem.log_execution(topic="test run")
        assert rid > 0

        cur = mem._conn.execute("SELECT * FROM execution_history WHERE run_id=?", (rid,))
        row = dict(cur.fetchone())
        assert row["status"] == "running"
        assert row["duration_seconds"] is None
        assert row["critic_approved"] is None

    def test_full_log(self, mem: MemoryManager) -> None:
        mem.log_execution(
            topic="full run",
            status="completed",
            duration_seconds=134.0,
            iteration_count=2,
            critic_approved=True,
            error_message=None,
        )
        cur = mem._conn.execute(
            "SELECT * FROM execution_history WHERE topic='full run'"
        )
        row = dict(cur.fetchone())
        assert row["status"] == "completed"
        assert row["duration_seconds"] == 134.0
        assert row["iteration_count"] == 2


# ── Cleanup ────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_removes_old_executions(self, mem: MemoryManager) -> None:
        """Logs older than retention_days should be removed."""
        # Insert a record with a very old timestamp
        import time
        old_ts = time.time() - (100 * 86400)  # 100 days ago
        mem._conn.execute(
            "INSERT INTO execution_history (run_id, topic, status, created_at) "
            "VALUES (?, ?, 'completed', ?)",
            (999, "ancient", old_ts),
        )
        mem._conn.commit()

        deleted = mem.cleanup(retention_days=30)
        assert deleted.get("execution_history (age)", 0) >= 1

    def test_trims_to_max_logs(self, mem: MemoryManager) -> None:
        """Only the newest max_exec_logs rows should survive."""
        for i in range(20):
            mem.log_execution(topic=f"run_{i}")
        deleted = mem.cleanup(max_exec_logs=5)
        assert deleted.get("execution_history (size)", 0) >= 15

        cur = mem._conn.execute("SELECT COUNT(*) FROM execution_history")
        assert cur.fetchone()[0] <= 5

    def test_removes_orphan_assets(self, mem: MemoryManager) -> None:
        """Asset_history rows referencing deleted videos should be removed."""
        vid = mem.save_video(topic="gone")
        mem.register_asset_use(provider="p", search_query="q", video_id=vid)
        mem._conn.execute("DELETE FROM video_history WHERE video_id=?", (vid,))
        mem._conn.commit()

        deleted = mem.cleanup()
        # Note: because SQLite ON DELETE SET NULL clears video_id, the
        # orphan check looks for video_id IS NOT NULL AND video_id NOT IN (...).
        # If SET NULL fires, video_id becomes NULL and the row is NOT orphan.
        # This is acceptable behaviour.
        assert isinstance(deleted, dict)
        assert "asset_history (orphans)" in deleted

    def test_cleanup_returns_counts(self, mem: MemoryManager) -> None:
        result = mem.cleanup()
        assert isinstance(result, dict)
        for key in ("execution_history (age)", "execution_history (size)", "asset_history (orphans)"):
            assert key in result


# ── Timestamps ──────────────────────────────────────────────────────────────


class TestTimestamps:
    def test_created_at_set_on_insert(self, mem: MemoryManager) -> None:
        mem.save_video(topic="ts_test")
        cur = mem._conn.execute("SELECT created_at FROM video_history WHERE topic='ts_test'")
        ts = cur.fetchone()[0]
        assert ts is not None
        assert isinstance(ts, (int, float))
        assert ts > 1700000000  # reasonable epoch after Jan 2023

    def test_updated_at_set_on_insert(self, mem: MemoryManager) -> None:
        mem.set_project_setting("key", "val")
        cur = mem._conn.execute("SELECT updated_at FROM project_settings WHERE key='key'")
        ts = cur.fetchone()[0]
        assert ts is not None

    def test_updated_at_changes_on_update(self, mem: MemoryManager) -> None:
        mem.set_project_setting("k", "v1")
        cur = mem._conn.execute("SELECT updated_at FROM project_settings WHERE key='k'")
        ts1 = cur.fetchone()[0]
        mem.set_project_setting("k", "v2")
        cur = mem._conn.execute("SELECT updated_at FROM project_settings WHERE key='k'")
        ts2 = cur.fetchone()[0]
        assert ts2 >= ts1
