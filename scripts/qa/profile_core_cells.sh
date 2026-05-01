#!/usr/bin/env bash
# Subprocess-form py-spy flames for the chat/search/embed/llm core
# cells. Each cell drives a CLI subprocess against a tiny corpus and
# qwen 0.6b. Sequential, no inter-cell state shared.
#
# USER RUNS THIS. Requires sudo on macOS.
#
# Usage:
#   sudo bash scripts/qa/profile_core_cells.sh <run_dir> <fixtures_dir>
#
# run_dir defaults to ./flames/core. fixtures_dir defaults to the path
# seed_fixtures.sh wrote (echoed at end of seed run).

set -euo pipefail

RUN_DIR="${1:-./flames/core}"
FIXTURES_DIR="${2:-/tmp/lilbee-qa-pizza/documents}"

mkdir -p "$RUN_DIR"

if [[ ! -d "$FIXTURES_DIR" ]]; then
    echo "!! fixtures dir not found: $FIXTURES_DIR" >&2
    echo "!! run scripts/qa/seed_fixtures.sh first" >&2
    exit 2
fi

export LILBEE_DATA="${LILBEE_DATA:-/tmp/lilbee-qa-pizza/data}"
export LILBEE_LOG_LEVEL="${LILBEE_LOG_LEVEL:-INFO}"
export LILBEE_NO_SPLASH=1
export LILBEE_LLM_PROVIDER="${LILBEE_LLM_PROVIDER:-llama-cpp}"
export LILBEE_CHAT_MODEL="${LILBEE_CHAT_MODEL:-Qwen/Qwen3-0.6B-GGUF}"

mkdir -p "$LILBEE_DATA"

echo ">> LILBEE_DATA   = $LILBEE_DATA"
echo ">> LILBEE_CHAT   = $LILBEE_CHAT_MODEL"
echo ">> fixtures      = $FIXTURES_DIR"
echo ">> output        = $RUN_DIR"
echo ""

PY=".venv/bin/python"
LILBEE=".venv/bin/lilbee"

run_cell() {
    local cell="$1"; shift
    local svg="$RUN_DIR/${cell}.svg"
    echo ">> cell $cell"
    py-spy record -o "$svg" -f flamegraph --rate 250 -- "$@" || {
        echo "!! cell $cell failed; flame may be partial" >&2
    }
}

# Ensure the docs are indexed before the search cells run.
echo ">> seeding index from $FIXTURES_DIR"
"$LILBEE" add "$FIXTURES_DIR" 2>&1 | tail -3 || true
"$LILBEE" sync 2>&1 | tail -3 || true

run_cell "Core-Search-RAG" \
    "$LILBEE" -j ask "What is EV battery technology?"

run_cell "Core-Search-Chat" \
    env LILBEE_CHAT_MODE=chat "$LILBEE" -j ask "What is EV battery technology?"

run_cell "Core-Search-Empty" \
    "$LILBEE" -j ask "zztop quagmire flibbertigibbet xenophanes"

run_cell "Core-Search-Reranker-Off" \
    env LILBEE_RERANKER_MODEL="" "$LILBEE" -j ask "battery technology"

run_cell "Core-Search-Reranker-On" \
    "$LILBEE" -j ask "battery technology"

run_cell "Core-Embed-Batch" \
    "$LILBEE" sync

run_cell "Core-LanceDB-Hybrid" \
    "$PY" scripts/qa/probe_lancedb_search.py "battery technology"

run_cell "Core-Llama-Stream-NoThink" \
    "$PY" scripts/qa/probe_llm_stream.py "/no_think Recite the alphabet from A to Z, one letter per line."

run_cell "Core-Llama-Stream-Thinking" \
    "$PY" scripts/qa/probe_llm_stream.py "What is 17 times 23? Show your reasoning step by step."

echo ""
echo ">> done. flames in $RUN_DIR"
