#!/usr/bin/env python3
"""Refresh the display-name corpus fixture from the live Hugging Face catalog.

Pulls the most-downloaded GGUF repos, runs ``clean_display_name`` over each
repo id, and rewrites ``tests/fixtures/display_name_corpus.json`` with the
results. The committed fixture pins the prettifier's behavior over real-world
names, so a new community naming convention (a fresh quant tag, a new
instruct-style suffix) surfaces as a reviewable fixture diff instead of an
ugly label in the wizard. Tests never touch the network; only this script
does. Run from the repo root:

  uv run --no-sync python scripts/qa/refresh_display_name_corpus.py
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


def main() -> int:
    repos = sorted(
        {m.id for m in list_models(filter="gguf", sort="downloads", limit=CORPUS_SIZE)}
    )
    corpus = [{"repo": repo, "display": clean_display_name(repo)} for repo in repos]
    FIXTURE.write_text(json.dumps(corpus, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(corpus)} entries to {FIXTURE.relative_to(Path.cwd())}")

    suspicious = [e for e in corpus if _SUSPICIOUS.search(e["display"])]
    if suspicious:
        print(f"\n{len(suspicious)} display name(s) still carry noise tokens - review these:")
        for entry in suspicious:
            print(f"  {entry['repo']!r} -> {entry['display']!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
