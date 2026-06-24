"""Capture lilbee's PIPELINE OCR text (page_texts) independent of the embedder.

``ingest_document`` populates ``page_texts_out`` before it chunks and embeds, so
OCR text is recoverable even when embedding is unavailable (e.g. the pre-migration
build's in-process llama_cpp engine). This captures OCR where each build actually
performs it -- the oracle's own pipeline (rasterize + tesseract) vs the candidate's
kreuzberg backend -- which the extract_file capture cannot compare apples-to-apples.

Usage:
    LILBEE_ENABLE_OCR=true python -m tools.qa.oracle.pipeline_ocr <corpus_dir> <out.json>
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import Any

from tools.qa.oracle.corpus import build_corpus
from tools.qa.oracle.similarity import keyword_recall


async def _pipeline_ocr_text(path: Path, content_type: str) -> str:
    from lilbee.data.ingest import ingest_document
    from lilbee.data.store import PageTextRecord

    page_texts: list[PageTextRecord] = []
    # Embed may be unavailable (e.g. the oracle's in-process engine); page_texts
    # are populated before the embed step, so suppress and read what was captured.
    with contextlib.suppress(Exception):
        await ingest_document(path, path.name, content_type, page_texts_out=page_texts)
    # PageTextRecord is a dict in 4.x and an object in 5.x.
    return "\n".join(pt["text"] if isinstance(pt, dict) else pt.text for pt in page_texts)


def capture(corpus_dir: Path) -> dict[str, Any]:
    items = build_corpus(corpus_dir, regenerate=False)
    out: dict[str, Any] = {}
    for it in items:
        text = asyncio.run(_pipeline_ocr_text(it.path, it.content_type))
        out[it.name] = {
            "content_type": it.content_type,
            "text_len": len(text),
            "pipeline_ocr_recall": (
                keyword_recall(text, it.ocr_keywords) if it.ocr_keywords else None
            ),
        }
    return out


def main() -> None:
    corpus_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    payload = capture(corpus_dir)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    scanned = {k: v for k, v in payload.items() if v["content_type"] in ("pdf", "image")}
    print(f"pipeline OCR captured {len(payload)} items -> {out_path}")
    for name, rec in sorted(scanned.items()):
        print(f"  {name:20} recall={rec['pipeline_ocr_recall']} len={rec['text_len']}")


if __name__ == "__main__":
    main()
