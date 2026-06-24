"""Deterministic differential corpus: one input per migration-relevant content type.

Synthetic inputs carry known ground-truth text, so OCR accuracy is measurable and
the fixtures are reproducible/committable. Scanned PDFs are image-only (no text
layer) to force the OCR path; one uses a JPEG-2000 stream (/JPXDecode) to cover
the kreuzberg-1158 render-engine regression directly. Any extra files dropped into
the corpus directory are picked up too (real office docs, real scans, etc.).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Distinctive, OCR-friendly ground-truth lines (uppercase words + digits).
_TEXT_BODY = "LILBEE ORACLE CHECK\nINVOICE NUMBER 4471\nTOTAL DUE 982 DOLLARS\nSTATUS APPROVED"
_TEXT_KEYWORDS = ("LILBEE", "INVOICE", "4471", "982", "APPROVED")
_CSV_BODY = "item,qty,price\nwidget,12,3.50\ngadget,7,9.99\nsprocket,40,1.25\n"
_CSV_KEYWORDS = ("widget", "gadget", "sprocket", "9.99")
_MD_BODY = "# Quarterly Notes\n\nRevenue rose to **982** units.\n\n- ship widget\n- ship gadget\n"
_MD_KEYWORDS = ("Quarterly", "Revenue", "982", "widget")

# Content-type strings (mirror data.ingest.types.DOCUMENT_EXTENSION_MAP).
_CT_TEXT = "text"
_CT_DATA = "data"
_CT_PDF = "pdf"
_CT_IMAGE = "image"

_IMG_SIZE = (1000, 600)
_FONT_SIZE = 48


@dataclass(frozen=True)
class CorpusItem:
    """One corpus input plus what the differential should recover from it."""

    name: str
    path: Path
    content_type: str
    ground_truth: str | None
    ocr_keywords: tuple[str, ...] = field(default_factory=tuple)


def _font() -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return ImageFont.load_default(size=_FONT_SIZE)


def _text_image(body: str) -> Image.Image:
    """Render text onto a white page-sized image (a synthetic scan)."""
    img = Image.new("RGB", _IMG_SIZE, "white")
    draw = ImageDraw.Draw(img)
    draw.multiline_text((40, 40), body, fill="black", font=_font(), spacing=16)
    return img


def _write_text(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


def _write_text_pdf(path: Path, body: str) -> None:
    """A PDF with a real (selectable) text layer."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=letter)
    text = c.beginText(72, 720)
    for line in body.splitlines():
        text.textLine(line)
    c.drawText(text)
    c.showPage()
    c.save()


def _write_raster_pdf(path: Path, body: str) -> None:
    """An image-only PDF (no text layer) -> forces OCR. Flate/DCT-encoded image."""
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = _text_image(body)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    w, h = _IMG_SIZE
    c = canvas.Canvas(str(path), pagesize=(w, h))
    c.drawImage(ImageReader(buf), 0, 0, width=w, height=h)
    c.showPage()
    c.save()


def _write_jpx_pdf(path: Path, body: str) -> None:
    """An image-only PDF whose page image is a JPEG-2000 stream (/JPXDecode).

    Reproduces the kreuzberg-1158 case directly; reportlab can't emit JPXDecode,
    so the single-page PDF is assembled by hand with computed xref offsets.
    """
    img = _text_image(body)
    jpx = io.BytesIO()
    img.save(jpx, "JPEG2000")
    data = jpx.getvalue()
    w, h = _IMG_SIZE

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {w} {h}] "
            f"/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
        ).encode(),
        (
            f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
            f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /JPXDecode "
            f"/Length {len(data)} >>\nstream\n"
        ).encode()
        + data
        + b"\nendstream",
        (lambda cs: f"<< /Length {len(cs)} >>\nstream\n".encode() + cs + b"\nendstream")(
            f"q {w} 0 0 {h} 0 0 cm /Im0 Do Q".encode()
        ),
    ]

    out = bytearray(b"%PDF-1.5\n")
    offsets: list[int] = []
    for i, body_bytes in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body_bytes + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
    ).encode()
    path.write_bytes(bytes(out))


def _write_png(path: Path, body: str) -> None:
    _text_image(body).save(str(path), "PNG")


@dataclass(frozen=True)
class _Spec:
    name: str
    filename: str
    content_type: str
    body: str
    keywords: tuple[str, ...]
    writer: Callable[[Path, str], None]


_SPECS: tuple[_Spec, ...] = (
    _Spec("plain_text", "plain_text.txt", _CT_TEXT, _TEXT_BODY, _TEXT_KEYWORDS, _write_text),
    _Spec("markdown_doc", "markdown_doc.md", _CT_TEXT, _MD_BODY, _MD_KEYWORDS, _write_text),
    _Spec("csv_table", "csv_table.csv", _CT_DATA, _CSV_BODY, _CSV_KEYWORDS, _write_text),
    _Spec(
        "pdf_text_layer", "pdf_text_layer.pdf", _CT_PDF, _TEXT_BODY, _TEXT_KEYWORDS, _write_text_pdf
    ),
    _Spec(
        "pdf_scanned_raster",
        "pdf_scanned_raster.pdf",
        _CT_PDF,
        _TEXT_BODY,
        _TEXT_KEYWORDS,
        _write_raster_pdf,
    ),
    _Spec(
        "pdf_scanned_jpx",
        "pdf_scanned_jpx.pdf",
        _CT_PDF,
        _TEXT_BODY,
        _TEXT_KEYWORDS,
        _write_jpx_pdf,
    ),
    _Spec("image_scan", "image_scan.png", _CT_IMAGE, _TEXT_BODY, _TEXT_KEYWORDS, _write_png),
)


def build_corpus(corpus_dir: Path, *, regenerate: bool = True) -> list[CorpusItem]:
    """Return the corpus manifest, writing the synthetic inputs when ``regenerate``.

    Both sides of the differential must run on identical bytes, so the corpus is
    generated once (``regenerate=True``) and the oracle reads it (``regenerate=False``).
    Extra files already in the directory (real docs/scans dropped in) are appended
    with content type inferred from extension and no ground truth.
    """
    corpus_dir.mkdir(parents=True, exist_ok=True)
    items: list[CorpusItem] = []
    for spec in _SPECS:
        path = corpus_dir / spec.filename
        if regenerate:
            spec.writer(path, spec.body)
        items.append(CorpusItem(spec.name, path, spec.content_type, spec.body, spec.keywords))

    generated = {it.path.name for it in items}
    for extra in sorted(corpus_dir.iterdir()):
        if extra.is_file() and extra.name not in generated:
            items.append(CorpusItem(extra.stem, extra, _infer_content_type(extra), None))
    return items


def _infer_content_type(path: Path) -> str:
    try:
        from lilbee.data.ingest.types import DOCUMENT_EXTENSION_MAP

        return DOCUMENT_EXTENSION_MAP.get(path.suffix.lower(), "text")
    except ImportError:
        return "text"
