#!/usr/bin/env bash
# Long-running py-spy attach over the entire TUI tmux walk. Aggregate
# flame; per-cell windows recoverable via flames/tui_walk.timestamps.json
# (written by run_matrix.py as it walks cells).
#
# USER RUNS THIS. Requires sudo on macOS.
#
# Usage (after run_matrix.py prints PID + duration):
#   sudo bash scripts/qa/profile_tui_attach.sh <PID> <DURATION_S> [<run_dir>]

set -euo pipefail

PID="${1:?usage: profile_tui_attach.sh <PID> <DURATION_S> [<run_dir>]}"
DURATION="${2:?usage: profile_tui_attach.sh <PID> <DURATION_S> [<run_dir>]}"
RUN_DIR="${3:-./flames/tui}"

mkdir -p "$RUN_DIR"

# Same root-ownership fix as profile_pilot.sh.
if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "$SUDO_USER" "$RUN_DIR"
fi

SVG="$RUN_DIR/tui_walk.svg"
SPEEDSCOPE="$RUN_DIR/tui_walk.speedscope.json"

echo ">> attaching to PID $PID for ${DURATION}s"
echo ">> writing flame:      $SVG"
echo ">> writing speedscope: $SPEEDSCOPE"
echo ""

# Flame SVG and speedscope JSON in one record session is not supported
# by py-spy 0.4 (one --format per invocation), so do two passes if both
# wanted. Doing flamegraph first (cheaper to inspect at-a-glance); the
# user can run this script a second time with a fresh PID for speedscope.
py-spy record \
    -o "$SVG" \
    -f flamegraph \
    --rate 200 \
    --duration "$DURATION" \
    --pid "$PID" \
    --idle

echo ""
echo ">> flame done: $SVG"
echo ">> for speedscope drill-in, re-run with -f speedscope on a fresh TUI PID."
