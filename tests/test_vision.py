"""Tests for vision model OCR extraction."""

from pathlib import Path
from unittest import mock

import pytest

from lilbee.app.services import CrawlerSyncState, Services, set_services
from lilbee.providers.worker.health_ticker import HealthTickerHandle


@pytest.fixture()
def mock_provider():
    """Create a mock provider with the full LLMProvider surface.

    ``vision_ocr`` is part of the protocol now, so every concrete provider
    implements it; tests mock it directly rather than the chat fallthrough.
    """
    provider = mock.MagicMock(
        spec=[
            "chat",
            "embed",
            "vision_ocr",
            "list_models",
            "pull_model",
            "show_model",
            "shutdown",
        ]
    )
    store = mock.MagicMock()
    embedder = mock.MagicMock()
    reranker = mock.MagicMock()
    concepts = mock.MagicMock()
    searcher = mock.MagicMock()
    registry = mock.MagicMock()
    services = Services(
        provider=provider,
        store=store,
        embedder=embedder,
        reranker=reranker,
        concepts=concepts,
        clusterer=mock.MagicMock(),
        searcher=searcher,
        registry=registry,
        hf_client=mock.MagicMock(),
        ingest_lock_registry=mock.MagicMock(),
        model_manager=mock.MagicMock(),
        crawler_semaphore=None,
        crawler_sync_state=CrawlerSyncState(),
        worker_pool=mock.MagicMock(),
        pool_runtime=mock.MagicMock(),
        pool_health_ticker=HealthTickerHandle(),
    )
    set_services(services)
    yield provider
    set_services(None)


def _mock_render(num_pages: int):
    """Mock render_pdf_page_to_png: PNG bytes for a valid index, RuntimeError past the end."""

    def render(data, index, dpi=None):
        if index >= num_pages:
            raise RuntimeError(f"Page index {index} out of range (document has {num_pages} pages)")
        return b"\x89PNG" + bytes(f"page-{index}", "utf-8")

    return render


@mock.patch("pathlib.Path.read_bytes", return_value=b"%PDF-fake")
class TestPdfPageCount:
    def test_returns_page_count(self, _read: mock.Mock) -> None:
        with mock.patch("kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(5)):
            from lilbee.vision import pdf_page_count

            assert pdf_page_count(Path("test.pdf")) == 5

    def test_empty_pdf_returns_zero(self, _read: mock.Mock) -> None:
        with mock.patch("kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(0)):
            from lilbee.vision import pdf_page_count

            assert pdf_page_count(Path("empty.pdf")) == 0

    def test_passes_dpi(self, _read: mock.Mock) -> None:
        with mock.patch(
            "kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(1)
        ) as patched:
            from lilbee.vision import _RASTER_DPI, pdf_page_count

            pdf_page_count(Path("test.pdf"))
            patched.assert_any_call(mock.ANY, 0, dpi=_RASTER_DPI)


@mock.patch("pathlib.Path.read_bytes", return_value=b"%PDF-fake")
class TestRasterizePdf:
    def test_yields_index_and_png_bytes(self, _read: mock.Mock) -> None:
        with mock.patch("kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(2)):
            from lilbee.vision import rasterize_pdf

            pages = list(rasterize_pdf(Path("test.pdf")))

        assert len(pages) == 2
        assert pages[0][0] == 0
        assert pages[1][0] == 1
        assert all(data.startswith(b"\x89PNG") for _, data in pages)

    def test_empty_pdf_yields_nothing(self, _read: mock.Mock) -> None:
        with mock.patch("kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(0)):
            from lilbee.vision import rasterize_pdf

            pages = list(rasterize_pdf(Path("empty.pdf")))

        assert pages == []

    def test_stops_at_last_page(self, _read: mock.Mock) -> None:
        """Rendering stops at the RuntimeError boundary instead of looping past the end."""
        with mock.patch(
            "kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(3)
        ) as patched:
            from lilbee.vision import rasterize_pdf

            pages = list(rasterize_pdf(Path("test.pdf")))

        assert [idx for idx, _ in pages] == [0, 1, 2]
        # One extra call probes the out-of-range index that terminates the loop.
        assert patched.call_count == 4

    def test_passes_dpi(self, _read: mock.Mock) -> None:
        with mock.patch(
            "kreuzberg.render_pdf_page_to_png", side_effect=_mock_render(1)
        ) as patched:
            from lilbee.vision import _RASTER_DPI, rasterize_pdf

            list(rasterize_pdf(Path("test.pdf")))
            patched.assert_any_call(mock.ANY, 0, dpi=_RASTER_DPI)


class TestPngToDataUrl:
    def test_encodes_png_bytes(self) -> None:
        import base64

        from lilbee.vision import _png_to_data_url

        png_bytes = b"\x89PNG\r\n\x1a\n"
        result = _png_to_data_url(png_bytes)
        assert result.startswith("data:image/png;base64,")
        # Verify round-trip
        encoded = result.split(",", 1)[1]
        assert base64.b64decode(encoded) == png_bytes


class TestBuildVisionMessages:
    def test_builds_openai_format(self) -> None:
        from lilbee.vision import build_vision_messages

        messages = build_vision_messages("describe this", b"fake-png")
        assert len(messages) == 1
        msg = messages[0]
        assert msg["role"] == "user"
        content = msg["content"]
        assert isinstance(content, list)
        assert len(content) == 2
        assert content[0]["type"] == "image_url"
        assert content[0]["image_url"]["url"].startswith("data:image/png;base64,")
        assert content[1]["type"] == "text"
        assert content[1]["text"] == "describe this"
