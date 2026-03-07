"""In-process embeddings via fastembed (ONNX Runtime)."""

import logging
import math
import os

from lilbee.config import EMBEDDING_DIM, EMBEDDING_MODEL, MAX_EMBED_CHARS

log = logging.getLogger(__name__)

# nomic-embed-text has 8192 token context but uses a BERT tokenizer that counts
# whitespace-heavy text (tables, formatted code) much more expensively than tiktoken.
# Worst-case table text (87% special chars) fails at 2345 chars; 2000 gives ~15% margin.
_MAX_EMBED_CHARS = MAX_EMBED_CHARS

# Lazy singleton — created on first use, reused for the process lifetime.
_model: object | None = None


def _get_providers() -> list[str]:
    """Detect ONNX Runtime execution providers.

    Auto-detects CUDA if available (user installed fastembed-gpu).
    Falls back to CPU. Skips CoreML — it's slower for nomic-embed-text
    due to unsupported rotary embedding ops.
    Override with LILBEE_EMBEDDING_PROVIDERS env var (comma-separated).
    """
    override = os.environ.get("LILBEE_EMBEDDING_PROVIDERS")
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]

    try:
        import onnxruntime

        available = onnxruntime.get_available_providers()
        if "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"]
    except ImportError:
        pass
    return ["CPUExecutionProvider"]


def _get_model() -> "TextEmbedding":  # type: ignore[name-defined]  # noqa: F821
    """Return the fastembed model singleton, creating it on first call."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding

        providers = _get_providers()
        log.info("Loading embedding model %s (providers: %s)", EMBEDDING_MODEL, providers)
        _model = TextEmbedding(model_name=EMBEDDING_MODEL, providers=providers)
    return _model  # type: ignore[return-value]


def _truncate(text: str) -> str:
    """Truncate text to stay within the embedding model's context window."""
    if len(text) <= _MAX_EMBED_CHARS:
        return text
    log.debug("Truncating chunk from %d to %d chars for embedding", len(text), _MAX_EMBED_CHARS)
    return text[:_MAX_EMBED_CHARS]


def _validate_vector(vector: list[float]) -> None:
    """Validate embedding vector dimension and values."""
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(
            f"Embedding dimension mismatch: expected {EMBEDDING_DIM}, got {len(vector)}"
        )
    for i, v in enumerate(vector):
        if math.isnan(v) or math.isinf(v):
            raise ValueError(f"Embedding contains invalid value at index {i}: {v}")


def validate_model() -> None:
    """Load the embedding model, downloading if needed."""
    _get_model()


def embed(text: str) -> list[float]:
    """Embed a single text string, return vector."""
    model = _get_model()
    results = list(model.embed([_truncate(text)]))
    result: list[float] = results[0].tolist()
    _validate_vector(result)
    return result


def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed multiple texts, return list of vectors.

    fastembed handles internal batching — no manual chunking needed.
    """
    if not texts:
        return []
    model = _get_model()
    truncated = [_truncate(t) for t in texts]
    vectors = [arr.tolist() for arr in model.embed(truncated)]
    for vec in vectors:
        _validate_vector(vec)
    return vectors
