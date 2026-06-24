"""End-to-end differential (Tiers 2-3): ingest the corpus through the lilbee CLI
and measure ground-truth recall via search.

Runs the FULL pipeline (extract -> OCR -> chunk -> embed -> index -> search) via
``lilbee add`` / ``lilbee search``, so it captures OCR wherever the build performs
it -- lilbee's own pipeline in 4.x, kreuzberg's extract_file in 5.x -- which the
extract-level capture cannot compare apples-to-apples. With a vision model set,
the scanned inputs exercise the vision-OCR path instead of tesseract.

Usage:
    python -m tools.qa.oracle.e2e_diff <corpus_dir> <out.json> [vision_model_ref]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from tools.qa.oracle.corpus import build_corpus
from tools.qa.oracle.similarity import keyword_recall

_SEARCH_TOP_K = 5
_CLI_TIMEOUT_S = 900


def _cli(args: list[str], data_dir: Path, vision_model: str | None) -> dict[str, Any]:
    """Run a `lilbee --json` subcommand in this build's venv and parse its JSON line."""
    env = {**os.environ, "LILBEE_DATA": str(data_dir), "LILBEE_ENABLE_OCR": "true"}
    if vision_model:
        env["LILBEE_VISION_MODEL"] = vision_model
    proc = subprocess.run(
        [sys.executable, "-m", "lilbee", "--json", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=_CLI_TIMEOUT_S,
        check=False,
    )
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except ValueError:
                continue
    return {"_error": (proc.stderr or proc.stdout or "no output")[-300:]}


def capture_e2e(
    corpus_dir: Path, data_dir: Path, vision_model: str | None = None
) -> dict[str, Any]:
    items = build_corpus(corpus_dir, regenerate=False)
    add = _cli(["add", *[str(it.path) for it in items]], data_dir, vision_model)
    added = set(add.get("sync", {}).get("added", []))

    results: dict[str, Any] = {}
    for it in items:
        query = " ".join(it.ocr_keywords) or it.name
        search = _cli(["search", query, "-k", str(_SEARCH_TOP_K)], data_dir, vision_model)
        hits = search.get("results", [])
        sources = [h.get("source") for h in hits]
        own = it.path.name in sources
        top_chunk = hits[0].get("chunk", "") if hits else ""
        recall = keyword_recall(top_chunk, it.ocr_keywords) if own and it.ocr_keywords else None
        results[it.name] = {
            "content_type": it.content_type,
            "added": it.path.name in added,
            "retrieved": own,
            "rank": sources.index(it.path.name) if own else -1,
            "chunk_keyword_recall": recall,
        }
    return {"vision_model": vision_model, "add_ok": "_error" not in add, "results": results}


def main() -> None:
    corpus_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    vision_model = sys.argv[3] if len(sys.argv) > 3 else None
    data_dir = Path(os.environ["LILBEE_DATA"])
    payload = capture_e2e(corpus_dir, data_dir, vision_model)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    retrieved = sum(1 for r in payload["results"].values() if r["retrieved"])
    n = len(payload["results"])
    mode = f"vision={vision_model}" if vision_model else "tesseract"
    print(f"e2e [{mode}]: {retrieved}/{n} retrieved -> {out_path}")


if __name__ == "__main__":
    main()
