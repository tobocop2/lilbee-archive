#!/usr/bin/env python3
"""Refresh the display-name corpus fixture from the live Hugging Face catalog.

Pulls the most-downloaded GGUF repos, runs ``clean_display_name`` over each
repo id, and rewrites ``tests/fixtures/display_name_corpus.json`` with the
results. The committed fixture pins the prettifier's behavior over real-world
names, so a new community naming convention (a fresh quant tag, a new
instruct-style suffix) surfaces as a reviewable fixture diff instead of an
ugly label in the wizard. Tests never touch the network; only this script
does.

  uv run --no-sync python scripts/qa/refresh_display_name_corpus.py

``--full`` additionally streams EVERY GGUF-tagged repo on the Hub (tens of
thousands; takes minutes) and reports each display name that still carries a
noise token, without changing the fixture size. Use it to audit the noise
grammar exhaustively before extending it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from huggingface_hub import list_models

from lilbee.catalog.formatting import clean_display_name

CORPUS_SIZE = 250
FIXTURE = Path(__file__).parents[2] / "tests" / "fixtures" / "display_name_corpus.json"

# Tokens that should never survive into a display name; entries still carrying
# one are printed for review so the noise grammar can grow deliberately.
_SUSPICIOUS = re.compile(r"\b(?:gguf|q\d[a-z0-9_]*|f16|f32|instruct)\b", re.IGNORECASE)


def _refresh_fixture() -> None:
    repos = sorted({m.id for m in list_models(filter="gguf", sort="downloads", limit=CORPUS_SIZE)})
    corpus = [{"repo": repo, "display": clean_display_name(repo)} for repo in repos]
    FIXTURE.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(corpus)} entries to {FIXTURE}")

    for entry in corpus:
        if _SUSPICIOUS.search(entry["display"]):
            print(f"  review: {entry['repo']!r} -> {entry['display']!r}")


def _full_audit() -> None:
    """Stream every GGUF-tagged repo and report names that keep noise tokens."""
    scanned = 0
    flagged = 0
    for model in list_models(filter="gguf", limit=None):
        scanned += 1
        display = clean_display_name(model.id)
        if _SUSPICIOUS.search(display):
            flagged += 1
            print(f"  {model.id!r} -> {display!r}")
        if scanned % 10_000 == 0:
            print(f"...scanned {scanned} repos, {flagged} flagged so far", file=sys.stderr)
    print(f"Scanned {scanned} GGUF repos; {flagged} display name(s) still carry noise tokens.")


def main() -> int:
    _refresh_fixture()
    if "--full" in sys.argv[1:]:
        _full_audit()
    return 0


if __name__ == "__main__":
    sys.exit(main())
