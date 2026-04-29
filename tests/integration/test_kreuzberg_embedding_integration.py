"""Integration tests for the kreuzberg in-process embedding plugin.

These exercise the real lilbee → kreuzberg dispatch path: kreuzberg's
chunker calls into lilbee's :class:`Embedder` instead of loading an
ONNX preset. They require kreuzberg 4.10+ for the plugin protocol.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.slow


_FIXTURE_MARKDOWN = """
# Embedding-Plugin Integration Fixture

This document is long enough that kreuzberg's semantic chunker will need to
score similarity between sentences. When kreuzberg's plugin path is wired
correctly, those similarity calls go through lilbee's Embedder rather than
loading a separate ONNX preset.

## First section

Sentences in this section discuss embedding models, vector dimensions,
chunk-boundary similarity, and the plugin protocol. They should cluster.

## Second section

These sentences talk about something completely different: cooking pasta,
boiling water, salt, olive oil. They should land in a separate chunk.
"""


@pytest.fixture
def fixture_doc(tmp_path: Path) -> Path:
    path = tmp_path / "fixture.md"
    path.write_text(_FIXTURE_MARKDOWN)
    return path


def test_semantic_chunking_routes_through_lilbee_embedder(
    monkeypatch: pytest.MonkeyPatch,
    fixture_doc: Path,
) -> None:
    """``chunk_text`` with semantic chunking on calls into the lilbee Embedder."""
    from lilbee.core.config import cfg
    from lilbee.core.services import get_services
    from lilbee.data.chunk import chunk_text
    from lilbee.retrieval.embedder import Embedder

    monkeypatch.setattr(cfg, "semantic_chunking", True)
    services = get_services()
    real_embed_batch = services.embedder.embed_batch
    calls: list[list[str]] = []

    def counting_embed_batch(texts: list[str], **kwargs: Any) -> list[list[float]]:
        calls.append(list(texts))
        return real_embed_batch(texts, **kwargs)

    monkeypatch.setattr(Embedder, "embed_batch", counting_embed_batch)

    chunks = chunk_text(fixture_doc.read_text(), mime_type="text/markdown")

    assert chunks, "expected at least one chunk"
    assert calls, "kreuzberg never dispatched into lilbee's embedder"


def test_kreuzberg_cache_dir_remains_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fixture_doc: Path,
) -> None:
    """Plugin path means kreuzberg downloads no ONNX presets to its cache."""
    from lilbee.core.config import cfg
    from lilbee.data.chunk import chunk_text

    cache_dir = tmp_path / "kreuzberg-cache"
    cache_dir.mkdir()
    monkeypatch.setenv("KREUZBERG_CACHE_DIR", str(cache_dir))
    monkeypatch.setattr(cfg, "semantic_chunking", True)

    chunks = chunk_text(fixture_doc.read_text(), mime_type="text/markdown")

    assert chunks
    cached_files = list(cache_dir.rglob("*"))
    assert all(not p.is_file() for p in cached_files), (
        f"kreuzberg wrote to its cache dir: {cached_files}"
    )
