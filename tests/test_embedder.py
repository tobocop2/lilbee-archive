"""Tests for the fastembed embedding wrapper (mocked — no model download needed)."""

import os
from unittest import mock

import numpy as np
import pytest

import lilbee.embedder as mod


class TestTruncate:
    def test_short_text_unchanged(self):
        text = "short text"
        assert mod._truncate(text) == text

    def test_long_text_truncated(self):
        text = "x" * (mod._MAX_EMBED_CHARS + 500)
        result = mod._truncate(text)
        assert len(result) == mod._MAX_EMBED_CHARS

    def test_exact_limit_unchanged(self):
        text = "a" * mod._MAX_EMBED_CHARS
        assert mod._truncate(text) == text


def _env_without(*keys: str) -> dict[str, str]:
    """Return a copy of os.environ without the specified keys."""
    return {k: v for k, v in os.environ.items() if k not in keys}


class TestGetProviders:
    def test_default_cpu(self):
        env = _env_without("LILBEE_EMBEDDING_PROVIDERS")
        with mock.patch.dict("os.environ", env, clear=True):
            providers = mod._get_providers()
            assert "CPUExecutionProvider" in providers

    def test_env_override(self):
        override = "CUDAExecutionProvider,CPUExecutionProvider"
        with mock.patch.dict("os.environ", {"LILBEE_EMBEDDING_PROVIDERS": override}):
            providers = mod._get_providers()
            assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]

    def test_onnxruntime_import_error_falls_back_to_cpu(self):
        env = _env_without("LILBEE_EMBEDDING_PROVIDERS")
        # Simulate onnxruntime not installed by making import raise
        import_orig = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def mock_import(name, *args, **kwargs):
            if name == "onnxruntime":
                raise ImportError("No module named 'onnxruntime'")
            return import_orig(name, *args, **kwargs)

        with (
            mock.patch.dict("os.environ", env, clear=True),
            mock.patch("builtins.__import__", side_effect=mock_import),
        ):
            providers = mod._get_providers()
            assert providers == ["CPUExecutionProvider"]

    def test_cuda_auto_detected(self):
        mock_ort = mock.MagicMock()
        mock_ort.get_available_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider",
        ]
        env = _env_without("LILBEE_EMBEDDING_PROVIDERS")
        with (
            mock.patch.dict("os.environ", env, clear=True),
            mock.patch.dict("sys.modules", {"onnxruntime": mock_ort}),
        ):
            providers = mod._get_providers()
            assert providers == ["CUDAExecutionProvider", "CPUExecutionProvider"]


class TestGetModel:
    def setup_method(self):
        self._original = mod._model
        mod._model = None

    def teardown_method(self):
        mod._model = self._original

    def test_creates_singleton(self):
        mock_cls = mock.MagicMock()
        mock_instance = mock.MagicMock()
        mock_cls.return_value = mock_instance
        with mock.patch.dict("sys.modules", {"fastembed": mock.MagicMock(TextEmbedding=mock_cls)}):
            result = mod._get_model()
            assert result is mock_instance
            mock_cls.assert_called_once()

    def test_reuses_singleton(self):
        sentinel = object()
        mod._model = sentinel
        assert mod._get_model() is sentinel


class TestEmbed:
    def test_returns_vector(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.1] * 768)]
        with mock.patch.object(mod, "_get_model", return_value=mock_model):
            vec = mod.embed("test")
            assert vec == pytest.approx([0.1] * 768)
            mock_model.embed.assert_called_once_with(["test"])

    def test_truncates_long_input(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.0] * 768)]
        with mock.patch.object(mod, "_get_model", return_value=mock_model):
            long_text = "a" * (mod._MAX_EMBED_CHARS + 1000)
            mod.embed(long_text)
            actual_input = mock_model.embed.call_args[0][0][0]
            assert len(actual_input) == mod._MAX_EMBED_CHARS


class TestEmbedBatch:
    def test_returns_multiple_vectors(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.1] * 768), np.array([0.2] * 768)]
        with mock.patch.object(mod, "_get_model", return_value=mock_model):
            result = mod.embed_batch(["a", "b"])
            assert len(result) == 2
            mock_model.embed.assert_called_once_with(["a", "b"])

    def test_empty_input_returns_empty(self):
        assert mod.embed_batch([]) == []

    def test_truncates_long_texts(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.0] * 768), np.array([0.0] * 768)]
        with mock.patch.object(mod, "_get_model", return_value=mock_model):
            texts = ["short", "x" * (mod._MAX_EMBED_CHARS + 500)]
            mod.embed_batch(texts)
            call_input = mock_model.embed.call_args[0][0]
            assert call_input[0] == "short"
            assert len(call_input[1]) == mod._MAX_EMBED_CHARS


class TestValidateVector:
    def test_valid_vector_passes(self):
        mod._validate_vector([0.1] * 768)  # Should not raise

    def test_wrong_dim_raises(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.1, 0.2])]
        with (
            mock.patch.object(mod, "_get_model", return_value=mock_model),
            pytest.raises(ValueError, match="dimension mismatch"),
        ):
            mod.embed("test")

    def test_nan_raises(self):
        import math

        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([math.nan] + [0.1] * 767)]
        with (
            mock.patch.object(mod, "_get_model", return_value=mock_model),
            pytest.raises(ValueError, match="invalid value"),
        ):
            mod.embed("test")

    def test_inf_raises(self):
        import math

        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([math.inf] + [0.1] * 767)]
        with (
            mock.patch.object(mod, "_get_model", return_value=mock_model),
            pytest.raises(ValueError, match="invalid value"),
        ):
            mod.embed("test")

    def test_embed_batch_wrong_dim_raises(self):
        mock_model = mock.MagicMock()
        mock_model.embed.return_value = [np.array([0.1, 0.2])]
        with (
            mock.patch.object(mod, "_get_model", return_value=mock_model),
            pytest.raises(ValueError, match="dimension mismatch"),
        ):
            mod.embed_batch(["test"])


class TestValidateModel:
    def test_calls_get_model(self):
        with mock.patch.object(mod, "_get_model") as mock_get:
            mod.validate_model()
            mock_get.assert_called_once()
