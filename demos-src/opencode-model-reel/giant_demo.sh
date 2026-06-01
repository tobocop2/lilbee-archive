#!/usr/bin/env bash
# Stand up an opencode demo of a giant model doing RAG over lilbee's own source:
#   opencode  --(model)-->  llama-server --jinja  (the giant, native tool calls)
#             --(MCP)----->  lilbee serve /mcp  (lilbee_search over src/lilbee/)
#
# Idempotent prep (workspace + index + lilbee serve) runs once; the per-giant
# part launches llama-server for the requested giant and writes opencode.json.
#
# Usage: giant_demo.sh <family> <gguf_path> [chat_template_file]
set -euo pipefail

FAMILY="$1"
GGUF="$2"
TEMPLATE="${3:-}"

LC=/root/llama.cpp            # CUDA llama.cpp built by pod_bootstrap.sh
LM=/root/lilbee               # lilbee checkout (feat/local-model-api) from pod_bootstrap.sh
WS=/root/demo-ws
LS_PORT=8090                      # llama-server (the giant)
EMBED_REF="nomic-ai/nomic-embed-text-v1.5-GGUF"
TINY_CHAT="Qwen/Qwen3-4B-GGUF"    # only so lilbee serve starts; opencode never uses it
export PATH="$HOME/.local/bin:$HOME/.opencode/bin:$PATH"
export LD_LIBRARY_PATH="$LC/build/bin:$LC/build/src:${LD_LIBRARY_PATH:-}"
export LILBEE_DATA="$WS/.lilbee"

cd "$LM"
LILBEE=".venv/bin/lilbee"

# --- one-time prep: workspace + index + serve ---
if [ ! -f "$WS/.lilbee/.demo_indexed" ]; then
  echo "[prep] workspace + models + index"
  mkdir -p "$WS/.lilbee"
  cat > "$WS/.lilbee/config.toml" <<TOML
chat_model = "$TINY_CHAT"
embedding_model = "$EMBED_REF"
TOML
  "$LILBEE" model pull "$EMBED_REF"
  "$LILBEE" model pull "$TINY_CHAT"
  # Index lilbee's own source. A curated subset keeps CPU embedding quick and the
  # demo answers focused on the interesting machinery.
  for d in providers/worker/response_parser providers/llama_cpp providers/families \
           server/chat_completions_api retrieval; do
    [ -d "$LM/src/lilbee/$d" ] && "$LILBEE" add "$LM/src/lilbee/$d" || true
  done
  touch "$WS/.lilbee/.demo_indexed"
fi

# opencode runs in an EMPTY project dir so its file tools can't read the source
# directly -- the lilbee source lives ONLY in lilbee's index, forcing lilbee_search
# (the godot-demo dynamic). AGENTS.md carries the grounding directive so the prompt
# stays a natural dev task.
PROJ=/root/demo-proj
mkdir -p "$PROJ"
cat > "$PROJ/AGENTS.md" <<'AGENTS'
# Working on the lilbee codebase

lilbee is a local-first RAG engine with an OpenAI-compatible server and an
opencode/MCP integration. Your training data does not include lilbee's internals,
and the lilbee source is NOT in this directory.

- The ONLY way to see lilbee's code is the `lilbee_search` tool. Use it to look up
  lilbee's modules, classes, and conventions before writing code. Query the
  class/function/concept; do not guess APIs.
- Cite the files you rely on as `path:Lstart-Lend`.
- No clarifying questions: make reasonable assumptions and implement.
AGENTS

# --- lilbee serve (background, for /mcp) ---
if ! curl -s "http://127.0.0.1:8080/api/health" >/dev/null 2>&1; then
  echo "[prep] starting lilbee serve"
  tmux kill-session -t lilbeeserve 2>/dev/null || true
  tmux new-session -d -s lilbeeserve \
    "cd $LM && LILBEE_DATA=$WS/.lilbee $LILBEE serve --port 8080 > /tmp/lilbee-serve.log 2>&1"
  for _ in $(seq 1 60); do
    curl -s "http://127.0.0.1:8080/api/health" >/dev/null 2>&1 && break; sleep 2
  done
fi
TOKEN=$(python3 -c "import json;print(json.load(open('$WS/.lilbee/data/server.json'))['token'])")
echo "[prep] lilbee serve up; token read"

# Pre-warm the embed engine and verify a real search returns hits BEFORE recording.
# lilbee's fleet warms the embed role lazily and swallows warm-up failures, so the
# first lilbee_search can hit a cold engine and 503 -- which the agent misreads as
# "no embed model installed" and wastes the whole session bootstrapping search.
# Force the embed role warm via the exact path the MCP tool uses (/api/search), and
# abort rather than record a broken demo. (The proper fix is await-embed-warm in
# lilbee itself; this gate guarantees a clean demo regardless.)
echo "[prep] warming embed engine + verifying lilbee_search returns hits"
WARM_OK=0
for _ in $(seq 1 40); do
  if curl -s -H "Authorization: Bearer $TOKEN" \
       "http://127.0.0.1:8080/api/search?q=tool%20call%20parsing&top_k=3" 2>/dev/null \
       | grep -qiE '"source"|\.py'; then
    WARM_OK=1; break
  fi
  sleep 3
done
if [ "$WARM_OK" = "1" ]; then
  echo "[prep] embed engine warm; lilbee_search returns hits -> safe to record"
else
  echo "[giant] ERROR: lilbee_search never returned hits (embed engine did not warm); aborting" >&2
  exit 6
fi

# --- llama-server for the giant ---
echo "[giant] launching llama-server for $FAMILY"
tmux kill-session -t giantsrv 2>/dev/null || true
TMPL_ARG=""
[ -n "$TEMPLATE" ] && TMPL_ARG="--chat-template-file $TEMPLATE"
# Only the 200GB giants need both GPUs. Force-splitting a small model across both
# (-ngl 999 with 2 visible devices) trips llama.cpp's scheduler assert
# (GGML_SCHED_MAX_SPLIT_INPUTS) during the device-memory fit, e.g. gemma-4-E2B.
# Default to a single GPU; set MULTIGPU=1 for the giants that genuinely span both.
GPU_ENV="CUDA_VISIBLE_DEVICES=0"
[ "${MULTIGPU:-0}" = "1" ] && GPU_ENV=""
# --alias makes /v1/models advertise the same id opencode is configured with, so
# the picker shows one "lilbee" model, not a duplicate from auto-discovery.
tmux new-session -d -s giantsrv \
  "$GPU_ENV LD_LIBRARY_PATH=$LC/build/bin:$LC/build/src $LC/build/bin/llama-server --jinja -m '$GGUF' --alias '$FAMILY' -ngl 999 --host 127.0.0.1 --port $LS_PORT -c 32768 --no-webui $TMPL_ARG > /tmp/giant-srv.log 2>&1"
# Measure the cold start empirically: wall time from launch until /health reports
# the model loaded. This is the real number the demo's cold-start intro card shows
# (build_reel.sh reads the sidecar), so the "fast-forwarded cold start" is honest,
# never an invented duration. /health only returns 200 once weights are resident.
COLD_START_TS=$SECONDS
UP=0
for _ in $(seq 1 200); do
  curl -s "http://127.0.0.1:$LS_PORT/health" >/dev/null 2>&1 && { UP=1; break; }; sleep 3
done
COLD_S=$((SECONDS - COLD_START_TS))
if [ "$UP" != "1" ]; then
  echo "[giant] ERROR: $FAMILY llama-server did not come up (see /tmp/giant-srv.log)" >&2
  exit 3
fi
SIZE_GB=$(awk "BEGIN{printf \"%.0f\", $(stat -c %s "$GGUF") / 1073741824}")
# Sidecar consumed by build_reel.sh to render the cold-start intro card.
printf 'model=%s\nsize_gb=%s\ncold_s=%s\ndevices="%s"\n' \
  "$FAMILY" "$SIZE_GB" "$COLD_S" "$([ "${MULTIGPU:-0}" = "1" ] && echo "2x H200" || echo "1x H200")" \
  > "$WS/coldstart-$FAMILY.txt"
echo "[giant] $FAMILY served on :$LS_PORT (cold start ${COLD_S}s, ${SIZE_GB}GB) -> warm; safe to record"

# --- opencode.json: model from llama-server, lilbee_search from lilbee MCP ---
mkdir -p "$WS/.config/opencode"
cat > "$PROJ/opencode.json" <<JSON
{
  "\$schema": "https://opencode.ai/config.json",
  "model": "lilbee/$FAMILY",
  "provider": {
    "lilbee": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "lilbee",
      "options": { "baseURL": "http://127.0.0.1:$LS_PORT/v1", "apiKey": "sk-noauth" },
      "models": { "$FAMILY": { "name": "$FAMILY" } }
    }
  },
  "tools": { "bash": false, "grep": false, "glob": false, "list": false, "read": false, "webfetch": false, "task": false },
  "permission": { "edit": "allow", "external_directory": "deny" },
  "mcp": {
    "lilbee": {
      "type": "remote",
      "url": "http://127.0.0.1:8080/mcp",
      "enabled": true,
      "headers": { "Authorization": "Bearer $TOKEN" }
    }
  }
}
JSON
echo "READY: opencode cwd=$PROJ (empty, forces lilbee_search) ; provider=lilbee model=$FAMILY@:$LS_PORT ; mcp=lilbee@:8080"
