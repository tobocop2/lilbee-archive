"""Capture lilbee's extraction + chunking behavior over the corpus into golden JSON.

Runs unchanged in both the oracle worktree (kreuzberg 4.9.x) and at HEAD
(kreuzberg 5.x): it only touches interfaces that exist identically in both
(``content_type_to_mode``, ``extraction_config``, ``chunk_text``, kreuzberg's
``extract_file_sync``) and adapts the one thing that drifted -- the result's
page shape (4.x dicts vs 5.x PageContent objects).

Usage:
    LILBEE_ENABLE_OCR=true python -m tools.qa.oracle.capture <corpus_dir> <out.json>
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from tools.qa.oracle.corpus import build_corpus


def _page_texts(result: Any) -> list[tuple[int, str]]:
    """Read (page_number, text) pairs, tolerating 4.x dict pages and 5.x PageContent."""
    pages = getattr(result, "pages", None) or []
    out: list[tuple[int, str]] = []
    for p in pages:
        if isinstance(p, dict):
            out.append((int(p.get("page_number", 0)), str(p.get("content") or p.get("text") or "")))
        else:
            num = int(getattr(p, "page_number", 0))
            txt = getattr(p, "content", None) or getattr(p, "text", "") or ""
            out.append((num, str(txt)))
    return out


def _ocr_facts(config: Any) -> tuple[bool, str | None]:
    """Read (ocr_enabled, backend_name) from lilbee's config (a dict of kreuzberg kwargs)."""
    ocr = config.get("ocr") if isinstance(config, dict) else getattr(config, "ocr", None)
    if ocr is None:
        return False, None
    enabled = bool(getattr(ocr, "enabled", True))
    backend = getattr(ocr, "backend", None)
    return enabled, (str(backend) if backend is not None else None)


def _extract_one(path: Path, content_type: str) -> dict[str, Any]:
    from kreuzberg import extract_file_sync

    from lilbee.data.ingest import content_type_to_mode, extraction_config

    mode = str(content_type_to_mode(content_type))
    config = extraction_config(content_type_to_mode(content_type))
    ocr_enabled, ocr_backend = _ocr_facts(config)
    try:
        result = extract_file_sync(str(path), config=config)
    except Exception as exc:
        return {
            "mode": mode,
            "ocr_enabled": ocr_enabled,
            "ocr_backend": ocr_backend,
            "error": f"{type(exc).__name__}: {exc}",
        }

    pages = _page_texts(result)
    content = str(getattr(result, "content", "") or "")
    return {
        "mode": mode,
        "ocr_enabled": ocr_enabled,
        "ocr_backend": ocr_backend,
        "content_text": content,
        "page_count": len(pages),
        "page_texts": [t for _, t in sorted(pages)],
        "error": None,
    }


def _chunk_one(content_text: str, content_type: str) -> dict[str, Any]:
    from lilbee.data.chunk import chunk_text

    mime = "text/markdown" if content_type == "text" else "text/plain"
    # use_semantic=False keeps chunking deterministic and model-free (semantic
    # chunking needs an embedder; that path is exercised by the search tier).
    chunks = chunk_text(content_text, mime_type=mime, use_semantic=False)
    return {"count": len(chunks), "lengths": [len(c) for c in chunks]}


def capture(corpus_dir: Path, *, regenerate: bool = True) -> dict[str, Any]:
    import kreuzberg

    items = build_corpus(corpus_dir, regenerate=regenerate)
    captured: dict[str, Any] = {}
    for it in items:
        extract = _extract_one(it.path, it.content_type)
        chunks = _chunk_one(extract.get("content_text", "") or "", it.content_type)
        captured[it.name] = {
            "content_type": it.content_type,
            "ground_truth": it.ground_truth,
            "ocr_keywords": list(it.ocr_keywords),
            "extract": extract,
            "chunks": chunks,
        }
    return {
        "kreuzberg_version": getattr(kreuzberg, "__version__", "unknown"),
        "items": captured,
    }


def main() -> None:
    corpus_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    regenerate = os.environ.get("ORACLE_CORPUS_REGENERATE", "1") != "0"
    payload = capture(corpus_dir, regenerate=regenerate)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    n = len(payload["items"])
    print(f"captured {n} items (kreuzberg {payload['kreuzberg_version']}) -> {out_path}")


if __name__ == "__main__":
    main()
