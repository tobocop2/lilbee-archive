#!/usr/bin/env bash
# Fresh-pod build stage for the opencode model reel (RunPod 2xH200, ephemeral /root).
#
# This is the EXACT model-independent bootstrap that runs first on a fresh pod:
# system deps -> uv -> clone lilbee -> uv sync -> build a CUDA llama-server from
# source (no prebuilt CUDA Linux binary ships in ggml-org releases). It writes
# progress to /root/run.log and ends with the BUILD_STAGE_DONE marker.
#
# It is launched detached inside the `work` tmux session so it survives SSH drops
# and so the run can be monitored with `tmux attach -t work` or `tail -F /root/run.log`.
#
# After this completes, the per-model serve/index/record pipeline runs:
#   giant_demo.sh  -> warm a giant on llama-server + index a codebase + lilbee serve /mcp
#   build_reel.sh  -> record the live opencode TUI tape + cold-start card + review gate
#
# Capture is done on the Mac (opencode over an SSH tunnel to this pod's llama-server
# :8090 and lilbee /mcp :8080), NOT with VHS on the pod: VHS's go-rod/ttyd pipeline
# captures 0 frames on the heavy pod after bootstrap. The pod only serves models +
# the search index; the Mac renders and records the TUI.
set -uo pipefail
LOG=/root/run.log
exec >>"$LOG" 2>&1
ts(){ date -u +%H:%M:%S; }
step(){ echo "[$(ts)] === STEP: $* ==="; }
fail(){ echo "[$(ts)] !!! FAIL: $* !!!"; echo "BOOTSTRAP_FAILED"; exit 1; }
export DEBIAN_FRONTEND=noninteractive
export PATH=$HOME/.local/bin:$PATH

step "apt build deps"
apt-get update -qq || fail "apt update"
apt-get install -y -qq cmake build-essential pkg-config ccache >/dev/null || fail "apt install"
echo "[$(ts)] apt OK"

step "install uv"
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh || fail "uv install"
export PATH=$HOME/.local/bin:$PATH
command -v uv >/dev/null || fail "uv missing after install"
echo "[$(ts)] uv $(uv --version)"

step "clone lilbee (public)"
cd /root
[ -d /root/lilbee ] || git clone -q https://github.com/tobocop2/lilbee.git || fail "clone lilbee"
cd /root/lilbee
git fetch -q origin || true
git checkout feat/local-model-api || fail "checkout branch"
echo "[$(ts)] lilbee @ $(git rev-parse --short HEAD)"

step "uv sync lilbee (slow)"
uv sync || fail "uv sync"
echo "[$(ts)] uv sync OK"

step "clone + build CUDA llama-server (long pole ~10-20min)"
cd /root
[ -d /root/llama.cpp ] || git clone -q --depth 1 https://github.com/ggml-org/llama.cpp || fail "clone llama.cpp"
cd /root/llama.cpp
cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=90 -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF || fail "cmake configure"
echo "[$(ts)] cmake configured, compiling llama-server..."
cmake --build build -j --target llama-server || fail "cmake build"
test -f build/bin/llama-server || fail "llama-server binary missing"
ln -sf /root/llama.cpp/build/bin/llama-server /usr/local/bin/llama-server
echo "[$(ts)] llama-server: $(command -v llama-server)"

mkdir -p /root/models
echo "[$(ts)] ====== BUILD_STAGE_DONE ======"
