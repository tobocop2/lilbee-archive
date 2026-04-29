"""Unit tests for the lilbee→kreuzberg embedding-plugin adapter."""

from __future__ import annotations

from unittest import mock

import pytest

from lilbee.data.kreuzberg_embedding import (
    KREUZBERG_BACKEND_NAME,
    LilbeeKreuzbergEmbeddingBackend,
    register_lilbee_embedding_backend,
)

_FAKE_VERSION = "9.9.9"
_DEFAULT_DIM = 768
_MISMATCH_DIM = 384
_PROBE_TEXT = "probe"


class _StubConfig:
    def __init__(self, dim: int = _DEFAULT_DIM) -> None:
        self.embedding_dim = dim


class _StubEmbedder:
    """Stand-in for :class:`lilbee.retrieval.embedder.Embedder`."""

    def __init__(self, dim: int = _DEFAULT_DIM, *, vector_dim: int | None = None) -> None:
        self._config = _StubConfig(dim)
        self.calls: list[list[str]] = []
        self._vector_dim = vector_dim if vector_dim is not None else dim

    @property
    def embedding_dim(self) -> int:
        return self._config.embedding_dim

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[0.0] * self._vector_dim for _ in texts]


def test_name_is_constant() -> None:
    backend = LilbeeKreuzbergEmbeddingBackend(_StubEmbedder())

    assert backend.name() == KREUZBERG_BACKEND_NAME == "lilbee"


def test_version_uses_get_version() -> None:
    with mock.patch("lilbee.data.kreuzberg_embedding.get_version", return_value=_FAKE_VERSION):
        backend = LilbeeKreuzbergEmbeddingBackend(_StubEmbedder())

        assert backend.version() == _FAKE_VERSION


def test_dimensions_returns_config_value() -> None:
    backend = LilbeeKreuzbergEmbeddingBackend(_StubEmbedder(dim=_DEFAULT_DIM))

    assert backend.dimensions() == _DEFAULT_DIM


def test_dimensions_is_declarative_not_measured() -> None:
    """``dimensions()`` reflects config, not whatever the embedder actually emits."""
    embedder = _StubEmbedder(dim=_DEFAULT_DIM, vector_dim=_MISMATCH_DIM)
    backend = LilbeeKreuzbergEmbeddingBackend(embedder)

    assert backend.dimensions() == _DEFAULT_DIM
    vectors = backend.embed([_PROBE_TEXT])
    assert len(vectors[0]) == _MISMATCH_DIM


def test_embed_delegates_to_embedder() -> None:
    embedder = _StubEmbedder()
    backend = LilbeeKreuzbergEmbeddingBackend(embedder)

    result = backend.embed(["a", "b"])

    assert embedder.calls == [["a", "b"]]
    assert len(result) == 2


def test_initialize_and_shutdown_are_noops() -> None:
    embedder = _StubEmbedder()
    backend = LilbeeKreuzbergEmbeddingBackend(embedder)

    assert backend.initialize() is None
    assert backend.shutdown() is None
    assert embedder.calls == []


@pytest.fixture
def kreuzberg_registry_mock() -> mock.MagicMock:
    """Patch the three pyo3 registry functions used by the helper.

    Returns a parent ``MagicMock`` with the three sub-mocks attached, so
    ``parent.mock_calls`` records call order across them.
    """
    parent = mock.MagicMock()
    parent.list_embedding_backends = mock.MagicMock(return_value=[])
    parent.register_embedding_backend = mock.MagicMock()
    parent.unregister_embedding_backend = mock.MagicMock()
    with mock.patch.dict(
        "sys.modules",
        {
            "kreuzberg._kreuzberg": mock.MagicMock(
                list_embedding_backends=parent.list_embedding_backends,
                register_embedding_backend=parent.register_embedding_backend,
                unregister_embedding_backend=parent.unregister_embedding_backend,
            )
        },
    ):
        yield parent


def test_register_calls_kreuzberg_register_when_clean(
    kreuzberg_registry_mock: mock.MagicMock,
) -> None:
    kreuzberg_registry_mock.list_embedding_backends.return_value = []
    embedder = _StubEmbedder()

    register_lilbee_embedding_backend(embedder)

    kreuzberg_registry_mock.unregister_embedding_backend.assert_not_called()
    kreuzberg_registry_mock.register_embedding_backend.assert_called_once()
    registered = kreuzberg_registry_mock.register_embedding_backend.call_args.args[0]
    assert isinstance(registered, LilbeeKreuzbergEmbeddingBackend)


def test_register_replaces_when_already_registered(
    kreuzberg_registry_mock: mock.MagicMock,
) -> None:
    kreuzberg_registry_mock.list_embedding_backends.return_value = [KREUZBERG_BACKEND_NAME]
    embedder = _StubEmbedder()

    register_lilbee_embedding_backend(embedder)

    kreuzberg_registry_mock.unregister_embedding_backend.assert_called_once_with(
        KREUZBERG_BACKEND_NAME
    )
    kreuzberg_registry_mock.register_embedding_backend.assert_called_once()
    call_names = [
        c[0]
        for c in kreuzberg_registry_mock.mock_calls
        if c[0]
        in {
            "unregister_embedding_backend",
            "register_embedding_backend",
        }
    ]
    assert call_names == ["unregister_embedding_backend", "register_embedding_backend"]


def test_register_after_reset_services_is_safe(
    kreuzberg_registry_mock: mock.MagicMock,
) -> None:
    """Simulate Services rebuild: register #1, then re-register with a new Embedder."""
    embedder1 = _StubEmbedder()
    embedder2 = _StubEmbedder()

    kreuzberg_registry_mock.list_embedding_backends.return_value = []
    register_lilbee_embedding_backend(embedder1)

    kreuzberg_registry_mock.list_embedding_backends.return_value = [KREUZBERG_BACKEND_NAME]
    register_lilbee_embedding_backend(embedder2)

    assert kreuzberg_registry_mock.register_embedding_backend.call_count == 2
    second_registered = kreuzberg_registry_mock.register_embedding_backend.call_args_list[1].args[0]
    assert second_registered._embedder is embedder2


def test_register_uses_passed_embedder(
    kreuzberg_registry_mock: mock.MagicMock,
) -> None:
    kreuzberg_registry_mock.list_embedding_backends.return_value = []
    custom_embedder = _StubEmbedder()

    register_lilbee_embedding_backend(custom_embedder)

    registered = kreuzberg_registry_mock.register_embedding_backend.call_args.args[0]
    assert registered._embedder is custom_embedder
