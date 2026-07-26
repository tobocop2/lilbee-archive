"""Tests for the store primitives the fragment-write ingest path needs."""

from __future__ import annotations

import pytest

from lilbee.core.config import cfg
from lilbee.data.store import ChunkWrite


@pytest.fixture
def store(tmp_path, monkeypatch):
    from lilbee.data.store import Store

    monkeypatch.setattr(cfg, "lancedb_dir", tmp_path / "lancedb")
    monkeypatch.setattr(cfg, "data_dir", tmp_path)
    return Store(cfg)


def _source_names(store) -> set[str]:
    return {row["filename"] for row in store.get_sources()}


def _chunk(source: str, index: int = 0) -> dict:
    return {
        "source": source,
        "content_type": "text",
        "chunk_type": "raw",
        "page_start": 0,
        "page_end": 0,
        "line_start": 0,
        "line_end": 0,
        "chunk": f"body {index}",
        "chunk_index": index,
        "vector": [0.1] * cfg.embedding_dim,
    }


class TestEnsureChunksDataset:
    def test_creates_the_table_and_returns_its_path(self, store):
        uri = store.ensure_chunks_dataset()

        assert uri.endswith("chunks.lance")
        assert store.open_table("chunks") is not None

    def test_stamps_meta_so_workers_do_not_have_to(self, store):
        """Workers append past the write path that would stamp it on first use."""
        assert store.get_meta() is None

        store.ensure_chunks_dataset()

        meta = store.get_meta()
        assert meta is not None
        assert meta["embedding_dim"] == cfg.embedding_dim

    def test_refuses_a_store_built_under_a_different_embedder(self, store):
        """Workers append past the write path that normally checks this on every
        write, so this call is the only place the mismatch can be caught."""
        store.ensure_chunks_dataset()
        monkey_dim = cfg.embedding_dim + 1

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(cfg, "embedding_dim", monkey_dim)
            with pytest.raises(Exception, match=r"(?i)embed|dimension|rebuild"):
                store.ensure_chunks_dataset()

    def test_is_idempotent(self, store):
        first = store.ensure_chunks_dataset()
        second = store.ensure_chunks_dataset()

        assert first == second


class TestPurgeChunksForSources:
    def test_clears_an_updated_source_before_its_file_is_redispatched(self, store):
        store.write_chunks_batch([ChunkWrite("a.txt", "h1", [_chunk("a.txt")], True)])
        assert store.count_chunks() == 1

        store.purge_chunks_for_sources(["a.txt"])

        assert store.count_chunks() == 0

    def test_clears_orphans_a_crashed_worker_left_behind(self, store):
        """A worker commits chunks before the parent writes the source row, so an
        interrupted file leaves rows nothing references; without this the next
        sync re-plans it and appends a second copy."""
        store.ensure_chunks_dataset()
        store._add_chunk_records_unlocked(
            store.get_db(), [_chunk("orphan.txt")], cfg.embedding_model, cfg.embedding_dim
        )
        assert store.count_chunks() == 1
        assert not _source_names(store)  # never got a source row

        store.purge_chunks_for_sources(["orphan.txt"])

        assert store.count_chunks() == 0

    def test_an_empty_list_is_a_no_op(self, store):
        store.ensure_chunks_dataset()
        store.purge_chunks_for_sources([])

        assert store.count_chunks() == 0


class TestWriteSourcesBatch:
    def test_writes_the_source_row_without_touching_chunks(self, store):
        """The worker already committed the chunks; this must not add or delete them."""
        store.ensure_chunks_dataset()
        store._add_chunk_records_unlocked(
            store.get_db(), [_chunk("a.txt")], cfg.embedding_model, cfg.embedding_dim
        )

        store.write_sources_batch([ChunkWrite("a.txt", "h1", [], True)])

        assert store.count_chunks() == 1  # untouched
        assert "a.txt" in _source_names(store)

    def test_does_not_delete_the_rows_the_worker_just_wrote(self, store):
        """needs_cleanup is True here; the normal path would delete by source,
        which in fragment mode would remove the fragment just committed."""
        store.ensure_chunks_dataset()
        store._add_chunk_records_unlocked(
            store.get_db(), [_chunk("a.txt")], cfg.embedding_model, cfg.embedding_dim
        )

        store.write_sources_batch([ChunkWrite("a.txt", "h1", [], True)])

        assert store.count_chunks() == 1

    def test_an_empty_batch_is_a_no_op(self, store):
        store.write_sources_batch([])

        assert store.count_chunks() == 0
