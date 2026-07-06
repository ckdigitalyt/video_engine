"""
test_asset_cache.py — Tests for the asset cache (src/assets/asset_cache.py).

Verifies lookup, registration, LRU cleanup, and SQLite integrity.
Uses a temporary SQLite database for each test to avoid side effects.
"""

import os
import time
from pathlib import Path

import pytest

from src.assets.asset_cache import AssetCache


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest.fixture
def cache(tmp_path: Path) -> AssetCache:
    """Create an AssetCache backed by a temp SQLite DB with a small max size."""
    db = tmp_path / "test_cache.db"
    c = AssetCache(db_path=str(db), max_size_mb=1)  # 1 MB = quick eviction
    yield c
    c.close()
    if db.exists():
        db.unlink()


@pytest.fixture
def populated_cache(cache: AssetCache, tmp_path: Path) -> AssetCache:
    """Populate the cache with several known entries."""
    # Create a real small file for each entry so cleanup() can measure it
    for i in range(3):
        f = tmp_path / f"asset_{i}.mp4"
        f.write_bytes(b"x" * 100)  # 100 bytes each
        cache.register(f"provider_{i}", f"query_{i}", f"https://url/{i}", local_path=str(f))
    return cache


# ── Initialisation ─────────────────────────────────────────────────────────


class TestInit:
    def test_creates_db_file(self, tmp_path: Path) -> None:
        db = tmp_path / "new_cache.db"
        c = AssetCache(db_path=str(db), max_size_mb=500)
        assert db.exists()
        c.close()

    def test_schema_tables_exist(self, cache: AssetCache) -> None:
        cur = cache._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='assets'"
        )
        assert cur.fetchone() is not None

    def test_indexes_exist(self, cache: AssetCache) -> None:
        cur = cache._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
        names = {r[0] for r in cur.fetchall()}
        assert "idx_assets_url" in names
        assert "idx_assets_last_used" in names


# ── Lookup ─────────────────────────────────────────────────────────────────


class TestLookup:
    def test_miss_on_empty(self, cache: AssetCache) -> None:
        assert cache.lookup("pexels", "nonexistent") is None

    def test_miss_on_missing_file(self, cache: AssetCache) -> None:
        """Registered entry whose local file has been deleted should be a miss."""
        cache.register("p", "q", "https://url")
        cache.update_local_path("https://url", "/tmp/_no_such_file_xyz")
        assert cache.lookup("p", "q") is None

    def test_hit(self, cache: AssetCache, tmp_path: Path) -> None:
        f = tmp_path / "hit.mp4"
        f.write_bytes(b"data")
        cache.register("pexels", "space", "https://pexels.com/v.mp4", local_path=str(f))
        result = cache.lookup("pexels", "space")
        assert result is not None
        assert result["asset_url"] == "https://pexels.com/v.mp4"
        assert result["local_path"] == str(f)


# ── Register ────────────────────────────────────────────────────────────────


class TestRegister:
    def test_insert(self, cache: AssetCache) -> None:
        cache.register("pexels", "milky_way", "https://pexels.com/mw.mp4")
        cur = cache._conn.execute(
            "SELECT * FROM assets WHERE provider='pexels' AND search_query='milky_way'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row["asset_url"] == "https://pexels.com/mw.mp4"

    def test_upsert_updates_use_count(self, cache: AssetCache) -> None:
        cache.register("p", "q", "https://url/1")
        cache.register("p", "q", "https://url/2")  # same PK
        cur = cache._conn.execute(
            "SELECT use_count, asset_url FROM assets WHERE provider='p' AND search_query='q'"
        )
        row = cur.fetchone()
        assert row["use_count"] == 2  # incremented
        assert row["asset_url"] == "https://url/2"  # updated

    def test_register_without_local_path(self, cache: AssetCache) -> None:
        """Pre-register at search time, local_path can be null."""
        cache.register("p", "q", "https://url")
        cur = cache._conn.execute(
            "SELECT local_path FROM assets WHERE provider='p' AND search_query='q'"
        )
        row = cur.fetchone()
        assert row["local_path"] is None

    @pytest.mark.parametrize("count", [1, 5, 100])
    def test_multiple_registrations(self, cache: AssetCache, tmp_path: Path, count: int) -> None:
        for i in range(count):
            f = tmp_path / f"bulk_{i}.mp4"
            f.write_bytes(b"x")
            cache.register(f"p_{i}", f"q_{i}", f"https://url/{i}", local_path=str(f))
        cur = cache._conn.execute("SELECT COUNT(*) FROM assets")
        assert cur.fetchone()[0] == count


# ── update_local_path ────────────────────────────────────────────────────────


class TestUpdateLocalPath:
    def test_updates_path_and_count(self, cache: AssetCache, tmp_path: Path) -> None:
        cache.register("p", "q", "https://url")
        f = tmp_path / "updated.mp4"
        f.write_bytes(b"data")
        cache.update_local_path("https://url", str(f))
        cur = cache._conn.execute(
            "SELECT local_path, use_count FROM assets WHERE provider='p' AND search_query='q'"
        )
        row = cur.fetchone()
        assert row["local_path"] == str(f)
        assert row["use_count"] == 2  # register set it to 1, update increments

    def test_update_nonexistent_url(self, cache: AssetCache) -> None:
        """Should not error (no rows matched)."""
        cache.update_local_path("https://no-such-url", "/tmp/fake.mp4")  # should be no-op


# ── touch ───────────────────────────────────────────────────────────────────


class TestTouch:
    def test_increments_use_count(self, cache: AssetCache, tmp_path: Path) -> None:
        f = tmp_path / "touched.mp4"
        f.write_bytes(b"data")
        cache.register("p", "q", "https://url", local_path=str(f))
        cache.touch(str(f))
        cur = cache._conn.execute(
            "SELECT use_count FROM assets WHERE local_path=?", (str(f),)
        )
        assert cur.fetchone()["use_count"] == 2


# ── Cleanup ────────────────────────────────────────────────────────────────


class TestCleanup:
    def test_noop_when_under_limit(self, cache: AssetCache, tmp_path: Path) -> None:
        """No files should be deleted if total size is under max_size_mb."""
        f = tmp_path / "tiny.mp4"
        f.write_bytes(b"x")
        cache.register("p", "q", "https://url", local_path=str(f))
        deleted = cache.cleanup()
        assert deleted == 0
        assert f.exists()

    def test_evicts_lru_when_over_limit(self, cache: AssetCache, tmp_path: Path) -> None:
        """When total exceeds max_size_mb, the oldest entry should be evicted."""
        # Create files totalling > 1 MB
        f1 = tmp_path / "old.mp4"
        f1.write_bytes(b"x" * (600 * 1024))  # 600 KB
        f2 = tmp_path / "new.mp4"
        f2.write_bytes(b"x" * (600 * 1024))  # 600 KB (total 1.2 MB > 1 MB)

        cache.register("p1", "q1", "https://url/1", local_path=str(f1))
        time.sleep(0.01)
        cache.register("p2", "q2", "https://url/2", local_path=str(f2))

        deleted = cache.cleanup()
        assert deleted == 1
        assert not f1.exists()  # f1 is older → evicted
        assert f2.exists()      # f2 is newer → kept

    def test_removes_orphan_db_rows(self, cache: AssetCache, tmp_path: Path) -> None:
        """Entries whose files are already gone get cleaned up without error."""
        cache.register("p", "q", "https://url", local_path="/tmp/_will_be_gone")
        cache.cleanup()  # should not raise


# ── Integrity ──────────────────────────────────────────────────────────────


class TestIntegrity:
    def test_no_duplicate_primary_keys(self, cache: AssetCache) -> None:
        """Primary key constraint prevents duplicate (provider, query)."""
        cache.register("p", "q", "https://url/1")
        cache.register("p", "q", "https://url/2")
        cur = cache._conn.execute(
            "SELECT COUNT(*) FROM assets WHERE provider='p' AND search_query='q'"
        )
        assert cur.fetchone()[0] == 1  # upsert, not insert

    def test_lookup_returns_copy(self, cache: AssetCache, tmp_path: Path) -> None:
        f = tmp_path / "copy_test.mp4"
        f.write_bytes(b"data")
        cache.register("p", "q", "https://url", local_path=str(f))
        result = cache.lookup("p", "q")
        assert result["asset_url"] == "https://url"
