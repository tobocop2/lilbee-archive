"""Reproduce the JPEG-2000 (#1158) render fix with a pixel-level check.

Renders a normal raster PDF and a JPEG-2000 (/JPXDecode) PDF -- the same image,
different stream encoding -- and reports luminance extrema. A page that decoded is
``(0, 255)`` (has dark text on white); a page that failed to decode is ``(255, 255)``
(all white = blank). This is independent of DPI and of OCR. Run it against any
installed kreuzberg to see whether that build decodes JPEG-2000.

Usage:
    python -m tools.qa.oracle.jpx_demo <raster.pdf> <jpx.pdf>
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from PIL import Image


def _verdict(png: bytes) -> str:
    im = Image.open(io.BytesIO(png)).convert("L")
    lo, hi = im.getextrema()
    state = "BLANK (decode failed)" if (lo, hi) == (255, 255) else "has content (decoded)"
    return f"{im.width}x{im.height} luminance=({lo},{hi}) -> {state}"


def main() -> None:
    import kreuzberg

    print(f"kreuzberg {kreuzberg.__version__}")
    for label, path in zip(("raster (control)", "jpeg-2000"), sys.argv[1:3], strict=False):
        png = kreuzberg.render_pdf_page_to_png(Path(path).read_bytes(), 0, dpi=150)
        print(f"  {label:18} {Path(path).name:24} {_verdict(png)}")


if __name__ == "__main__":
    main()
