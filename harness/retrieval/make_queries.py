#!/usr/bin/env python3
"""Generate the query set from a built index: self-labeled known-item queries
plus aggregate queries whose true counts come from an independent oracle.

The oracle deliberately uses the ``lancedb`` library directly and never
imports lilbee: if the shipped scan is wrong, the sweep fails instead of the
bug validating itself. Known-item queries are built from source NAMES only;
no document text leaks into any query.
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import re
import sys
from pathlib import Path

import lancedb

KNOWN_ITEM_TEMPLATES = (
    "summarize {name}",
    "what is document {stem} about?",
)

# Aggregate terms are sampled at mid document-frequency: rare terms make the
# scan trivial, ubiquitous ones make it degenerate.
TERM_DF_LOW = 0.05
TERM_DF_HIGH = 0.4
TERM_COUNT = 8
KNOWN_ITEM_COUNT = 24
_WORD_RE = re.compile(r"[a-z]{5,16}")


def scan_chunks(lancedb_dir: Path):
    db = lancedb.connect(str(lancedb_dir))
    table = db.open_table("chunks")
    arrow = table.to_arrow().select(["source", "chunk"])
    for batch in arrow.to_batches(max_chunksize=20_000):
        yield from zip(
            batch.column("source").to_pylist(), batch.column("chunk").to_pylist(), strict=True
        )


def oracle_counts(lancedb_dir: Path, term: str) -> tuple[int, int]:
    """Exact (chunk, source) mention counts, computed independently of lilbee."""
    needle = term.lower()
    chunks = 0
    sources: set[str] = set()
    for source, text in scan_chunks(lancedb_dir):
        if text and needle in text.lower():
            chunks += 1
            sources.add(source)
    return chunks, len(sources)


def sample_terms(lancedb_dir: Path, rng: random.Random) -> list[str]:
    doc_freq: collections.Counter[str] = collections.Counter()
    total_sources: set[str] = set()
    per_source_terms: dict[str, set[str]] = {}
    for source, text in scan_chunks(lancedb_dir):
        total_sources.add(source)
        terms = per_source_terms.setdefault(source, set())
        if text and len(terms) < 20_000:
            terms.update(_WORD_RE.findall(text.lower()))
    for terms in per_source_terms.values():
        doc_freq.update(terms)
    n = len(total_sources)
    band = [
        t for t, df in doc_freq.items() if TERM_DF_LOW <= df / n <= TERM_DF_HIGH
    ]
    rng.shuffle(band)
    return band[:TERM_COUNT]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lancedb", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--topical", type=Path, help="optional hand-written topical queries")
    parser.add_argument("--seed", type=int, default=20260709)
    args = parser.parse_args()
    rng = random.Random(args.seed)

    db = lancedb.connect(str(args.lancedb))
    sources = sorted({row["filename"] for row in db.open_table("_sources").to_arrow().to_pylist()})
    if not sources:
        print("no sources in index", file=sys.stderr)
        return 1

    queries: list[dict] = []
    picks = rng.sample(sources, min(KNOWN_ITEM_COUNT, len(sources)))
    for i, name in enumerate(picks):
        template = KNOWN_ITEM_TEMPLATES[i % len(KNOWN_ITEM_TEMPLATES)]
        stem = Path(name).stem
        queries.append(
            {
                "qid": f"ki{i:03d}",
                "query": template.format(name=name, stem=stem),
                "intent": "known_item",
                "qrels": {name: 1},
            }
        )

    for i, term in enumerate(sample_terms(args.lancedb, rng)):
        chunk_hits, source_hits = oracle_counts(args.lancedb, term)
        queries.append(
            {
                "qid": f"ag{i:03d}",
                "query": f"how many documents mention {term}?",
                "intent": "aggregate",
                "oracle": {"term": term, "chunks": chunk_hits, "sources": source_hits},
            }
        )

    if args.topical:
        for line in args.topical.read_text().splitlines():
            if line.strip():
                queries.append(json.loads(line))

    with args.out.open("w") as fh:
        for q in queries:
            fh.write(json.dumps(q) + "\n")
    by_intent = collections.Counter(q["intent"] for q in queries)
    print(f"wrote {len(queries)} queries: {dict(by_intent)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
