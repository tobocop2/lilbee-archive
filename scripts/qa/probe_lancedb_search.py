"""Profile a single LanceDB hybrid search call in isolation.

Bypasses the LLM. The flame is just FTS + vector + filtering.
Used by profile_core_cells.sh as the Core-LanceDB-Hybrid cell.
"""

from __future__ import annotations

import sys

from lilbee.core.services import get_services

_REQUIRED_ARGS = 2  # script name + query


def main() -> int:
    if len(sys.argv) < _REQUIRED_ARGS:
        print("usage: probe_lancedb_search.py <query>", file=sys.stderr)
        return 2
    query = sys.argv[1]
    services = get_services()
    searcher = services.searcher
    results = searcher.search(question=query, top_k=20)
    print(f"results: {len(results)}")
    for r in results[:3]:
        score = getattr(r, "relevance_score", None) or getattr(r, "distance", None)
        print(f"  {r.source[:80]!s:<80} score={score!s:.20s}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
