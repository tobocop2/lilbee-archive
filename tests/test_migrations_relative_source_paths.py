"""Tests for the relative-source-paths migration (migrations/relative_source_paths.py)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from lilbee.config import cfg
from lilbee.migrations import run_all
from lilbee.migrations.relative_source_paths import (
    MARKER_FILENAME,
    run_relative_source_paths_migration,
)
from lilbee.store import Store


def _make_record(source: str, dim: int, chunk_index: int = 0) -> dict:
    return {
        "source": source,
        "content_type": "text",
        "chunk_type": "raw",
        "page_start": 0,
        "page_end": 0,
        "line_start": 0,
        "line_end": 0,
        "chunk": f"chunk {chunk_index} for {source}",
        "chunk_index": chunk_index,
        "vector": [0.1] * dim,
    }


@pytest.fixture()
def migration_env(tmp_path: Path):
    """Point cfg at a scratch data/documents layout for migration tests."""
    cfg.documents_dir = tmp_path / "documents"
    cfg.data_dir = tmp_path / "data"
    cfg.lancedb_dir = tmp_path / "data" / "lancedb"
    cfg.documents_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path


class TestRewriteChunksTable:
    def test_noop_when_lancedb_dir_absent(self, migration_env: Path) -> None:
        # lancedb_dir hasn't been created yet
        result = run_relative_source_paths_migration()
        assert result == {"chunks_updated": 0, "crawl_meta_updated": 0}
        assert (cfg.data_dir / MARKER_FILENAME).exists()

    def test_rewrites_absolute_sources(self, migration_env: Path) -> None:
        store = Store(cfg)
        abs_source = str(cfg.documents_dir / "report.pdf")
        store.add_chunks(
            [
                _make_record(abs_source, cfg.embedding_dim, 0),
                _make_record(abs_source, cfg.embedding_dim, 1),
                _make_record("notes.md", cfg.embedding_dim, 0),
            ]
        )

        result = run_relative_source_paths_migration()
        assert result["chunks_updated"] == 1  # distinct source count

        table = store.open_table("chunks")
        assert table is not None
        rows = table.to_arrow().to_pylist()
        sources = {r["source"] for r in rows}
        assert sources == {"report.pdf", "notes.md"}

    def test_second_run_is_noop(self, migration_env: Path) -> None:
        store = Store(cfg)
        abs_source = str(cfg.documents_dir / "doc.md")
        store.add_chunks([_make_record(abs_source, cfg.embedding_dim, 0)])

        first = run_relative_source_paths_migration()
        assert first["chunks_updated"] == 1

        # Put a sentinel absolute row back in; the migration should NOT touch
        # it because the marker short-circuits everything.
        store.add_chunks(
            [_make_record(str(cfg.documents_dir / "should-not-migrate.md"), cfg.embedding_dim, 0)]
        )
        second = run_relative_source_paths_migration()
        assert second == {"chunks_updated": 0, "crawl_meta_updated": 0}

        table = store.open_table("chunks")
        assert table is not None
        sources = {r["source"] for r in table.to_arrow().to_pylist()}
        assert str(cfg.documents_dir / "should-not-migrate.md") in sources

    def test_leaves_already_relative_rows_alone(self, migration_env: Path) -> None:
        store = Store(cfg)
        store.add_chunks(
            [
                _make_record("already/relative.md", cfg.embedding_dim, 0),
                _make_record("other.md", cfg.embedding_dim, 0),
            ]
        )
        result = run_relative_source_paths_migration()
        assert result["chunks_updated"] == 0

        table = store.open_table("chunks")
        assert table is not None
        sources = {r["source"] for r in table.to_arrow().to_pylist()}
        assert sources == {"already/relative.md", "other.md"}

    def test_search_results_preserved_after_migration(self, migration_env: Path) -> None:
        store = Store(cfg)
        abs_source = str(cfg.documents_dir / "x.md")
        records = [_make_record(abs_source, cfg.embedding_dim, i) for i in range(3)]
        store.add_chunks(records)

        before = store.search([0.1] * cfg.embedding_dim, top_k=5)
        assert len(before) == 3

        run_relative_source_paths_migration()

        # Reconnect so LanceDB sees the update
        store.close()
        after = store.search([0.1] * cfg.embedding_dim, top_k=5)
        assert len(after) == 3
        assert {r.source for r in after} == {"x.md"}


class TestRewriteCrawlMeta:
    def test_rewrites_absolute_file_paths(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        abs_file = str(cfg.documents_dir / "_web/example.com/page.md")
        meta_path.write_text(
            json.dumps(
                {
                    "https://example.com/page": {
                        "file": abs_file,
                        "content_hash": "abc",
                        "crawled_at": "2026-01-01T00:00:00+00:00",
                    },
                    "https://example.com/other": {
                        "file": "_web/example.com/other.md",
                        "content_hash": "def",
                        "crawled_at": "2026-01-01T00:00:00+00:00",
                    },
                }
            )
        )
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 1

        data = json.loads(meta_path.read_text())
        assert data["https://example.com/page"]["file"] == "_web/example.com/page.md"
        assert data["https://example.com/other"]["file"] == "_web/example.com/other.md"

    def test_rewrites_absolute_keys(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        abs_key = str(cfg.documents_dir / "legacy.md")
        meta_path.write_text(
            json.dumps(
                {
                    abs_key: {
                        "file": "legacy.md",
                        "content_hash": "abc",
                        "crawled_at": "2026-01-01T00:00:00+00:00",
                    },
                }
            )
        )
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 1

        data = json.loads(meta_path.read_text())
        assert "legacy.md" in data
        assert abs_key not in data

    def test_noop_when_meta_missing(self, migration_env: Path) -> None:
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 0

    def test_noop_when_already_relative(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        payload = {
            "https://x.com/y": {
                "file": "_web/x.com/y.md",
                "content_hash": "abc",
                "crawled_at": "2026-01-01",
            }
        }
        meta_path.write_text(json.dumps(payload))
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 0
        assert json.loads(meta_path.read_text()) == payload

    def test_handles_unreadable_meta_gracefully(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        meta_path.write_text("{not json")
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 0

    def test_handles_non_dict_top_level(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        meta_path.write_text(json.dumps(["not", "a", "mapping"]))
        result = run_relative_source_paths_migration()
        assert result["crawl_meta_updated"] == 0

    def test_handles_non_dict_values(self, migration_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        meta_path.write_text(
            json.dumps(
                {
                    "some-key": "not-a-dict",
                    "other": {"file": "relative.md"},
                }
            )
        )
        result = run_relative_source_paths_migration()
        # No rewrites needed — both values are already clean
        assert result["crawl_meta_updated"] == 0


class TestMarker:
    def test_marker_written_after_run(self, migration_env: Path) -> None:
        run_relative_source_paths_migration()
        assert (cfg.data_dir / MARKER_FILENAME).exists()

    def test_run_all_runs_once(self, migration_env: Path) -> None:
        # run_all is the orchestrator. First call should work, second is noop.
        run_all()
        marker = cfg.data_dir / MARKER_FILENAME
        assert marker.exists()
        # Corrupt crawl_meta to verify second call doesn't touch it.
        meta_path = cfg.data_dir / "crawl_meta.json"
        abs_key = str(cfg.documents_dir / "a.md")
        meta_path.write_text(json.dumps({abs_key: {"file": abs_key}}))
        run_all()
        # Still absolute because marker short-circuits.
        data = json.loads(meta_path.read_text())
        assert abs_key in data


class TestAtomicWrite:
    def test_temp_cleanup_on_replace_failure(self, migration_env: Path) -> None:
        from lilbee.migrations.relative_source_paths import _atomic_write_json

        target = cfg.data_dir / "crawl_meta.json"

        with (
            mock.patch("pathlib.Path.replace", side_effect=OSError("boom")),
            pytest.raises(OSError, match="boom"),
        ):
            _atomic_write_json(target, {"x": 1})

        # No stray .tmp files left behind.
        leftovers = [p for p in cfg.data_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


class TestLegacyPrefix:
    def test_prefix_uses_os_sep(self, migration_env: Path) -> None:
        from lilbee.migrations.relative_source_paths import _legacy_prefix

        prefix = _legacy_prefix()
        assert prefix.endswith(os.sep)
        assert prefix.startswith(str(cfg.documents_dir))
