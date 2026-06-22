"""Helpers for PDF rasterisation and vision-model OCR.

Multi-page vision OCR runs through ``LlamaCppProvider.pdf_ocr`` and the
persistent worker pool; this module hosts the small helpers (page count,
rasterisation, prompt + chat-message construction, and the shared
:class:`PageText` / :class:`PdfOcrChunk` types) that both the worker and
the parent need.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

log = logging.getLogger(__name__)


class PageText(NamedTuple):
    """Extracted text for a single PDF page."""

    page: int
    text: str


class PdfOcrChunk(NamedTuple):
    """One streaming PDF-OCR worker frame: page index, total pages, page text."""

    page: int
    total: int
    text: str


OCR_PROMPT = (
    "Extract ALL text from this page as clean markdown. "
    "Preserve table structure using markdown table syntax. "
    "Include all rows, columns, headers, and page text exactly as shown."
)

_RASTER_DPI = 150


def _render_pages(data: bytes) -> Iterator[bytes]:
    """Yield each PDF page as PNG bytes, stopping when the index runs past the end."""
    from kreuzberg import render_pdf_page_to_png  # lazy: heavy dependency

    index = 0
    while True:
        try:
            yield render_pdf_page_to_png(data, index, dpi=_RASTER_DPI)
        except RuntimeError:
            return  # page index past the last page
        index += 1


def pdf_page_count(path: Path) -> int:
    """Return the number of pages in a PDF.

    kreuzberg 5.x exposes no cheap page-count API (only per-page rendering), so
    this rasterizes each page to count them.
    """
    return sum(1 for _ in _render_pages(path.read_bytes()))


def rasterize_pdf(path: Path) -> Iterator[tuple[int, bytes]]:
    """Yield (0-based index, PNG bytes) for each page of a PDF."""
    yield from enumerate(_render_pages(path.read_bytes()))


def _png_to_data_url(png_bytes: bytes) -> str:
    """Convert raw PNG bytes to a base64 data URL for OpenAI-compatible messages."""
    import base64

    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def build_vision_messages(prompt: str, png_bytes: bytes) -> list[dict]:
    """Build OpenAI-compatible messages with image content for vision models.

    Uses the multipart content format expected by llama.cpp's mtmd pipeline.
    """
    return [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": _png_to_data_url(png_bytes)}},
                {"type": "text", "text": prompt},
            ],
        }
    ]
