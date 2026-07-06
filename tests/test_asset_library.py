"""
test_asset_library.py — Tests for the reusable Asset Library.

Verifies:
- exact query reuse (same query → cache hit)
- partial keyword overlap reuse (similar query → cache hit)
- cache miss when similarity is below threshold
- cache miss when reuse is disabled
- automatic indexing on download
- provider fallback on no match
- disabled reuse bypasses local lookup entirely
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.assets.asset_library import AssetLibrary
from src.assets.asset_cache import AssetCache


# ── Fixtures ───────────────────────────────────────────────────────────────


class FakeProvider:
    """A trivial AssetProvider stand-in for unit tests."""

    def __init__(self):
        self.search_calls: list[str] = []
        self.download_calls: list[tuple[str, str]] = []

    def search(self, query: str, **kwargs) -> list:
        self.search_calls.append(query)
        return [{"video_files": [{"link": "https://fake.provider/v.mp4"}]}]

    def download(self, url: str, output_path: str) -> str:
        self.download_calls.append((url, output_path))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"fake_video")
        return output_path


@pytest.fixture
def cache(tmp_path: Path) -> AssetCache:
    """Isolated AssetCache backed by a temp SQLite DB."""
    db = tmp_path / "lib_cache.db"
    c = AssetCache(db_path=str(db), max_size_mb=500)
    yield c
    c.close()
    if db.exists():
        db.unlink()


@pytest.fixture
def fake_provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def library(fake_provider: FakeProvider, cache: AssetCache) -> AssetLibrary:
    """AssetLibrary wired to FakeProvider, reuse enabled, low threshold.
    Diversity is disabled so existing core-reuse tests remain valid."""
    return AssetLibrary(
        provider=fake_provider,
        cache=cache,
        enabled=True,
        threshold=0.3,
        max_candidates=5,
        diversity_enabled=False,
    )


@pytest.fixture
def library_disabled(fake_provider: FakeProvider, cache: AssetCache) -> AssetLibrary:
    """AssetLibrary with reuse disabled."""
    return AssetLibrary(
        provider=fake_provider,
        cache=cache,
        enabled=False,
        threshold=0.3,
    )


# ── Tokenisation & Similarity ─────────────────────────────────────────────


class TestSimilarity:
    def test_identical_queries(self) -> None:
        assert AssetLibrary._keyword_similarity("deep space", "deep space") == 1.0

    def test_case_insensitive(self) -> None:
        assert AssetLibrary._keyword_similarity("Deep Space", "deep space") == 1.0

    def test_partial_overlap(self) -> None:
        s = AssetLibrary._keyword_similarity("milky way galaxy", "galaxy stars milky")
        assert 0.5 <= s <= 1.0

    def test_no_overlap(self) -> None:
        s = AssetLibrary._keyword_similarity("cat dog", "tree rock")
        assert s == 0.0

    def test_one_empty(self) -> None:
        assert AssetLibrary._keyword_similarity("cat dog", "") == 0.0
        assert AssetLibrary._keyword_similarity("", "cat dog") == 0.0

    def test_normalize_whitespace(self) -> None:
        assert AssetLibrary._normalize("  Deep   Space  ") == "deep space"


# ── Search: reuse enabled ─────────────────────────────────────────────────


class TestSearchReuse:
    def test_exact_query_reuse(self, library: AssetLibrary, fake_provider: FakeProvider) -> None:
        """Same query twice → second call reuses, no provider call."""
        # First call: cache miss, delegates to provider
        r1 = library.search("milky way galaxy")
        assert len(fake_provider.search_calls) == 1

        # Second call: should hit the index from download-time registration
        # First, simulate download so indexing happens
        library.download("https://fake/v.mp4", "/tmp/_test_exact_reuse.mp4")

        # Reset provider call count
        fake_provider.search_calls.clear()

        # Third search with same query → should find cached entry
        r2 = library.search("milky way galaxy")
        assert len(fake_provider.search_calls) == 0  # no provider call
        assert len(r2) > 0
        assert r2[0]["video_files"][0]["link"] is not None

    def test_similar_query_reuse(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """Partially overlapping queries should match above threshold."""
        # Index an asset for a query
        f = tmp_path / "space_scene.mp4"
        f.write_bytes(b"space_video")
        library._index_asset("deep space galaxy stars", "https://url/space", str(f))

        # Search with a similar query (overlap: "deep", "space", "stars" ≈ 3/5 tokens)
        # Jaccard: {deep,space,stars} / {deep,space,galaxy,stars,nebula} = 3/5 = 0.6 > 0.3
        result = library.search("deep space stars nebula")
        assert len(fake_provider.search_calls) == 0  # reuse happened
        assert len(result) > 0

    def test_threshold_below_prevents_reuse(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """If similarity is below threshold, fall through to provider."""
        f = tmp_path / "animals.mp4"
        f.write_bytes(b"animal_video")
        library._index_asset("cat dog fish", "https://url/animal", str(f))

        library.search("quantum physics black hole")
        assert len(fake_provider.search_calls) == 1  # missed

    def test_cache_miss_no_entries(self, library: AssetLibrary, fake_provider: FakeProvider) -> None:
        """Empty index → always delegates to provider."""
        library.search("something new")
        assert len(fake_provider.search_calls) == 1

    def test_cache_miss_deleted_file(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """Indexed entry whose file was deleted triggers provider call."""
        f = tmp_path / "_gone.mp4"
        f.write_bytes(b"video")
        library._index_asset("gone query", "https://url/gone", str(f))
        os.remove(str(f))

        library.search("gone query")
        assert len(fake_provider.search_calls) == 1  # missed because file gone

    def test_download_triggers_indexing(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """After download, the entry should be findable by a similar query."""
        out = tmp_path / "idx_test.mp4"
        library.search("nebula dust cloud")
        library.download("https://fake/v.mp4", str(out))

        # Verify it's indexed
        entries = library._get_all_indexed()
        assert len(entries) >= 1
        assert any("nebula" in e["query"] for e in entries)


# ── Search: reuse disabled ────────────────────────────────────────────────


class TestSearchDisabled:
    def test_disabled_reuse_always_calls_provider(self, library_disabled: AssetLibrary, fake_provider: FakeProvider) -> None:
        """When reuse is disabled, every search calls the provider."""
        library_disabled.search("space")
        library_disabled.search("space")  # same query again
        assert len(fake_provider.search_calls) == 2

    def test_disabled_does_not_index(self, library_disabled: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """When reuse is disabled, download should NOT index assets."""
        out = tmp_path / "_no_idx.mp4"
        library_disabled.search("some query")
        library_disabled.download("https://fake/v.mp4", str(out))

        entries = library_disabled._get_all_indexed()
        assert len(entries) == 0

    def test_disabled_download_still_succeeds(self, library_disabled: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """Download should still work when reuse is disabled."""
        out = tmp_path / "_still_works.mp4"
        library_disabled.search("any")
        result = library_disabled.download("https://fake/v.mp4", str(out))
        assert result == str(out)
        assert Path(out).exists()


# ── Download ──────────────────────────────────────────────────────────────


class TestDownload:
    def test_download_delegates_to_provider(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        out = tmp_path / "delegate.mp4"
        library.search("test query")
        library.download("https://fake/v.mp4", str(out))
        assert len(fake_provider.download_calls) == 1
        assert fake_provider.download_calls[0][0] == "https://fake/v.mp4"

    def test_download_indexes_asset(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        out = tmp_path / "idx_check.mp4"
        library.search("will be indexed")
        library.download("https://fake/v.mp4", str(out))

        entries = library._get_all_indexed()
        assert len(entries) == 1
        assert entries[0]["query"] == AssetLibrary._normalize("will be indexed")

    def test_download_index_does_not_duplicate(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """Same query downloaded twice should upsert, not duplicate."""
        out1 = tmp_path / "dup_a.mp4"
        out2 = tmp_path / "dup_b.mp4"
        library.search("dup query")
        library.download("https://fake/v1.mp4", str(out1))

        library.search("dup query")
        library.download("https://fake/v2.mp4", str(out2))

        entries = library._get_all_indexed()
        assert len(entries) == 1  # upsert keeps it at 1

    def test_download_without_prior_search(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """If download is called without a prior search, it still works but no indexing."""
        out = tmp_path / "_no_search.mp4"
        result = library.download("https://fake/v.mp4", str(out))
        assert result == str(out)
        entries = library._get_all_indexed()
        assert len(entries) == 0  # no _last_query → no index


# ── Provider fallback ─────────────────────────────────────────────────────


class TestProviderFallback:
    def test_provider_called_on_miss(self, library: AssetLibrary, fake_provider: FakeProvider) -> None:
        library.search("brand new never seen before query")
        assert len(fake_provider.search_calls) == 1

    def test_provider_called_multiple_queries(self, library: AssetLibrary, fake_provider: FakeProvider) -> None:
        for q in ["aaa", "bbb", "ccc"]:
            library.search(q)
        assert len(fake_provider.search_calls) == 3

    def test_provider_errors_propagate(self, fake_provider: FakeProvider, cache: AssetCache) -> None:
        """Errors from the backing provider should propagate."""
        def _search_fail(*a, **kw):
            raise RuntimeError("provider down")
        fake_provider.search = _search_fail  # type: ignore

        lib = AssetLibrary(provider=fake_provider, cache=cache, enabled=True, threshold=0.3)
        with pytest.raises(RuntimeError):
            lib.search("anything")


# ── Constructor / config ─────────────────────────────────────────────────


class TestConfig:
    def test_constructor_overrides(self, fake_provider: FakeProvider, cache: AssetCache) -> None:
        lib = AssetLibrary(
            provider=fake_provider,
            cache=cache,
            enabled=False,
            threshold=0.9,
            max_candidates=1,
        )
        assert lib._enabled is False
        assert lib._threshold == 0.9
        assert lib._max_candidates == 1

    def test_defaults_from_yaml(self, tmp_project: Path, fake_provider: FakeProvider) -> None:
        """When no constructor override is given, defaults come from config."""
        lib = AssetLibrary(provider=fake_provider)
        # The tmp_project fixture creates minimal providers.yaml; reuse section
        # is absent, so the code falls back to hard-coded defaults in get_config.
        assert lib._enabled is not None
        assert 0 <= lib._threshold <= 1.0


# ── Edge cases ────────────────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_query(self, library: AssetLibrary, fake_provider: FakeProvider) -> None:
        """Empty query should still be delegated to provider."""
        library.search("")
        assert len(fake_provider.search_calls) == 1

    def test_single_token_queries(self, library: AssetLibrary, fake_provider: FakeProvider, tmp_path: Path) -> None:
        """Single-token queries should match when identical."""
        f = tmp_path / "space_only.mp4"
        f.write_bytes(b"x")
        library._index_asset("space", "https://url/space", str(f))

        library.search("space")
        assert len(fake_provider.search_calls) == 0  # reuse
