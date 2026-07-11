#!/usr/bin/env bash
# Differential retrieval sweep: baseline (origin/main) vs branch (HEAD) over
# one shared index. See README.md for what it checks.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../.." && pwd)"
WORK=""
DOCS_DIR=""
TOPICAL=""
BASELINE_REF="origin/main"

while [ $# -gt 0 ]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --docs-dir) DOCS_DIR="$2"; shift 2 ;;
    --topical) TOPICAL="$2"; shift 2 ;;
    --baseline-ref) BASELINE_REF="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$WORK" ] || { echo "usage: run_sweep.sh --work DIR [--docs-dir DIR] [--topical FILE]" >&2; exit 2; }

mkdir -p "$WORK"
DATA_ROOT="$WORK/data_root"
mkdir -p "$DATA_ROOT/documents"
# The sweep must start from a pristine index: a prior failed run leaves sync
# bookkeeping (skip ledgers, partial tables) that makes the next ingest treat
# every document as already handled.
rm -rf "$DATA_ROOT/data"
rm -f "$DATA_ROOT/skipped_sources.json" "$DATA_ROOT/skip_reasons.json"

# 1. Corpus: fetch the public manifest unless a private set is supplied.
if [ -n "$DOCS_DIR" ]; then
  echo "== using private corpus: $DOCS_DIR"
  cp -R "$DOCS_DIR/." "$DATA_ROOT/documents/"
else
  echo "== fetching public corpus"
  python3 "$HERE/fetch_corpus.py" --manifest "$HERE/corpus_manifest.tsv" --out "$DATA_ROOT/documents"
fi

# 2. Two venvs: branch = this checkout, baseline = a clean origin/main worktree.
BRANCH_VENV="$WORK/venv-branch"
BASE_VENV="$WORK/venv-baseline"
BASE_SRC="$WORK/baseline-src"
if [ ! -d "$BASE_SRC" ]; then
  git -C "$REPO_ROOT" worktree add --detach "$BASE_SRC" "$BASELINE_REF"
fi
[ -d "$BRANCH_VENV" ] || uv venv "$BRANCH_VENV"
[ -d "$BASE_VENV" ] || uv venv "$BASE_VENV"
echo "== installing branch"
VIRTUAL_ENV="$BRANCH_VENV" uv pip install -q -e "$REPO_ROOT"
echo "== installing baseline ($BASELINE_REF)"
VIRTUAL_ENV="$BASE_VENV" uv pip install -q -e "$BASE_SRC"
# Source installs resolve lilbee-engine from the in-repo stub wheel, which
# carries no binaries; pull the published wheel (real llama-server) into both
# venvs. Engine wheels live on the lilbee.sh channel indexes, not PyPI; set
# LILBEE_ENGINE_INDEX=https://lilbee.sh/cu125/ for a CUDA pod. Best-effort:
# PATH or LILBEE_LLAMA_SERVER_PATH still work without it.
ENGINE_INDEX="${LILBEE_ENGINE_INDEX:-https://lilbee.sh/cpu/}"
for venv in "$BRANCH_VENV" "$BASE_VENV"; do
  VIRTUAL_ENV="$venv" uv pip install -q --no-sources --reinstall --prerelease allow \
    --extra-index-url "$ENGINE_INDEX" lilbee-engine \
    || echo "note: published lilbee-engine unavailable; relying on PATH / LILBEE_LLAMA_SERVER_PATH"
done

# 3. Ingest ONCE with the branch build (no store schema changes on this
#    branch, so both sides read the same index; the differential isolates
#    query-time behavior).
echo "== ingesting"
"$BRANCH_VENV/bin/python" - "$DATA_ROOT" <<'PY'
import sys
from pathlib import Path
from lilbee.api import Lilbee
from lilbee.core.config import cfg

root = Path(sys.argv[1])
config = cfg.model_copy(update={
    "data_root": root,
    "documents_dir": root / "documents",
    "data_dir": root / "data",
    "lancedb_dir": root / "data" / "lancedb",
    "concept_graph": False,
    "wiki": False,
})
bee = Lilbee(config=config)
result = bee.sync()
print(f"ingested: {result}")
bee.close()
if not (result.added or result.updated or result.unchanged):
    raise SystemExit(
        "ingest produced no chunks; the sweep cannot proceed. The usual cause "
        "is no runnable llama-server for embeddings: install the lilbee-engine "
        "wheel in the sweep venvs, put llama-server on PATH, or set "
        "LILBEE_LLAMA_SERVER_PATH."
    )
PY

# 4. Queries from the built index (self-labeled + oracle counts).
echo "== generating queries"
"$BRANCH_VENV/bin/python" "$HERE/make_queries.py" \
  --lancedb "$DATA_ROOT/data/lancedb" --out "$WORK/queries.jsonl" \
  ${TOPICAL:+--topical "$TOPICAL"}

# 5. Probe both sides.
echo "== probing branch"
"$BRANCH_VENV/bin/python" "$HERE/probe.py" \
  --data-root "$DATA_ROOT" --queries "$WORK/queries.jsonl" --out "$WORK/branch.tsv"
echo "== probing baseline"
"$BASE_VENV/bin/python" "$HERE/probe.py" \
  --data-root "$DATA_ROOT" --queries "$WORK/queries.jsonl" --out "$WORK/baseline.tsv"

# 6. Report.
echo "== report"
"$BRANCH_VENV/bin/python" "$HERE/make_report.py" \
  --queries "$WORK/queries.jsonl" --baseline "$WORK/baseline.tsv" \
  --branch "$WORK/branch.tsv" --out "$WORK/EVIDENCE.md"
echo "evidence: $WORK/EVIDENCE.md"
