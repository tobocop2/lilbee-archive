# Retrieval differential sweep

Before/after evaluation of the retrieval pipeline: a baseline probe built
from `origin/main` and a branch probe built from the feature branch run the
same queries against the SAME index, and the report renders metrics, a drift
census, and fatal invariant checks as `EVIDENCE.md`.

The corpus is pluggable. The default manifest pulls public-domain books; pass
`--docs-dir` to run the identical sweep over a private document set instead.
Nothing in the harness assumes anything about corpus content.

## What it checks

**Fatal invariants** (any hit fails the sweep):

1. `INV_SCORE_RANGE`: every branch result carries a canonical score in [0, 1].
2. `INV_DOMINANCE`: within one result list, a row that beats another on both
   vector similarity and BM25 must not score lower. This is an independent
   consistency check on the fusion arithmetic, computed from the provenance
   fields in the output, not by calling the fusion code.
3. `INV_KNOWN_ITEM_REGRESSION`: a known-item query where the baseline found
   the named document in its top-k and the branch did not.
4. `INV_AGGREGATE_ORACLE`: the branch's count answers must equal counts
   recomputed here by scanning the raw Lance table directly with the
   `lancedb` library. The oracle never imports lilbee, so a bug in the
   shipped scan shows up as a mismatch instead of validating itself.

**Census** (counted and listed, not failed): per-query differences in
retrieved (source, chunk) sets and rank order between baseline and branch.
The ranking changes are the point of the branch; the census makes every one
of them visible for audit.

**Metrics**: success@1, success@k, and MRR for known-item queries per side;
exact-match rate against the oracle for aggregates (branch; the baseline has
no count capability, recorded as such).

## Layout

    corpus_manifest.tsv   default public corpus (id, url, filename)
    fetch_corpus.py       manifest -> documents directory, with retries
    make_queries.py       index -> queries.jsonl (known-item self-labeled,
                          aggregate with oracle counts); merges an optional
                          --topical file of hand-written topical queries
    probe.py              queries.jsonl + repo checkout -> results TSV
    make_report.py        two result sets -> EVIDENCE.md
    run_sweep.sh           orchestrates all of the above
    sweep-pod.sky.yaml    SkyPilot definition for running the sweep on a pod

## Running

    ./run_sweep.sh --work /tmp/sweep                 # public corpus
    ./run_sweep.sh --work /tmp/sweep --docs-dir DIR  # private corpus

Requirements: `uv`, `git`, network for the baseline checkout, an embedding
model lilbee can serve (run `lilbee setup` once on the machine, or point
`LILBEE_EMBEDDING_MODEL` at a pulled model), and a runnable `llama-server`.
The sweep venvs install lilbee from source, whose dev engine wheel carries no
binaries: either install the published `lilbee-engine` wheel into both venvs,
have `llama-server` on PATH, or set `LILBEE_LLAMA_SERVER_PATH`. The ingest
step aborts with this message if embeddings cannot start. The chat model is
never used: probes exercise retrieval only, with expansion, HyDE, concept
graph, and reranker disabled so the comparison isolates the retrieval core.

Ground truth needs no judges: known-item queries are generated from the
index's own source names (query by name, the named document is definitionally
the answer; the document's text never leaks into the query), and aggregate
truth comes from the independent full scan.

## Substituting private data

`--docs-dir` replaces only the corpus fetch. Queries are regenerated from
whatever index the corpus produces, so the sweep, invariants, and report are
identical. Hand-written topical queries for the private set go in a JSONL
file passed as `--topical` (`{"qid": ..., "query": ..., "intent": "topical",
"qrels": {"relative/path.md": 1}}`).
