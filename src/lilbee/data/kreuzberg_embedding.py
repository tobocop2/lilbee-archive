"""kreuzberg embedding-plugin adapter routing through lilbee's Embedder."""

from __future__ import annotations

from lilbee.app.version import get_version
from lilbee.retrieval.embedder import Embedder

KREUZBERG_BACKEND_NAME = "lilbee"


class LilbeeKreuzbergEmbeddingBackend:
    """kreuzberg ``EmbeddingBackend`` that delegates to a lilbee :class:`Embedder`.

    ``dimensions()`` returns the embedder's configured dim, not whatever the
    loaded GGUF actually emits. kreuzberg validates against the declared dim;
    a runtime mismatch surfaces from ``Embedder.validate_vector`` on first
    embed call.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def name(self) -> str:
        return KREUZBERG_BACKEND_NAME

    def version(self) -> str:
        return get_version()

    def initialize(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def dimensions(self) -> int:
        return self._embedder.embedding_dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embedder.embed_batch(texts)


def register_lilbee_embedding_backend(embedder: Embedder) -> None:
    """Register the lilbee adapter, replacing any prior registration of the same name."""
    from kreuzberg._kreuzberg import (
        list_embedding_backends,
        register_embedding_backend,
        unregister_embedding_backend,
    )

    if KREUZBERG_BACKEND_NAME in list_embedding_backends():
        unregister_embedding_backend(KREUZBERG_BACKEND_NAME)
    register_embedding_backend(LilbeeKreuzbergEmbeddingBackend(embedder))
