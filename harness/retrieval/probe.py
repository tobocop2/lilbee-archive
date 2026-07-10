#!/usr/bin/env python3
"""Run the query set through whichever lilbee is installed in this venv.

The same script probes both sides of the differential: run_sweep.sh installs
the baseline checkout in one venv and the branch in another, and this script
feature-detects capabilities (aggregate routing) instead of assuming them.

Retrieval-only configuration: expansion, HyDE, concept graph, reranker, and
temporal filtering are all off, so the comparison isolates the retrieval
core. No chat model is ever invoked.

Output: one TSV row per retrieved chunk (qid, rank, source, chunk_index,
score, distance, bm25) plus one `answer` row per aggregate query.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top-k", type=int, default=12)
    args = parser.parse_args()

    from lilbee.api import Lilbee
    from lilbee.core.config import cfg

    config = cfg.model_copy(
        update={
            "data_root": args.data_root,
            "documents_dir": args.data_root / "documents",
            "data_dir": args.data_root / "data",
            "lancedb_dir": args.data_root / "data" / "lancedb",
            "query_expansion_count": 0,
            "hyde": False,
            "concept_graph": False,
            "reranker_model": "",
            "temporal_filtering": False,
            "memory_enabled": False,
        }
    )
    bee = Lilbee(config=config)
    searcher = bee.searcher
    can_route_aggregates = hasattr(searcher, "route_direct_answer")

    rows: list[str] = []
    queries = [json.loads(line) for line in args.queries.read_text().splitlines() if line.strip()]
    for q in queries:
        qid, query, intent = q["qid"], q["query"], q["intent"]
        if intent == "aggregate":
            if can_route_aggregates:
                answer = searcher.route_direct_answer(query) or ""
                numbers = re.findall(r"\d+", answer)
                rows.append("\t".join([qid, "answer", answer.replace("\t", " "), *numbers]))
            else:
                rows.append("\t".join([qid, "answer", "UNSUPPORTED"]))
            continue
        results = bee.search(query, top_k=args.top_k)
        for rank, r in enumerate(results, 1):
            rows.append(
                "\t".join(
                    [
                        qid,
                        str(rank),
                        r.source,
                        str(r.chunk_index),
                        _fmt(getattr(r, "score", None)),
                        _fmt(r.distance),
                        _fmt(r.bm25_score),
                    ]
                )
            )
    args.out.write_text("\n".join(rows) + "\n")
    print(f"probed {len(queries)} queries -> {args.out}")
    bee.close()
    return 0


def _fmt(value: float | None) -> str:
    return "" if value is None else f"{value:.6f}"


if __name__ == "__main__":
    sys.exit(main())
