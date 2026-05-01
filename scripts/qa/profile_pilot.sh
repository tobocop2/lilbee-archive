#!/usr/bin/env bash
# Wraps the full TUI pilot harness with py-spy. One invocation, one
# aggregate flame, one speedscope JSON. The runner emits a per-step
# timestamp file alongside it so individual gestures can be windowed
# in speedscope.
#
# USER RUNS THIS. Requires sudo on macOS.
#
# Usage:
#   sudo bash scripts/qa/profile_pilot.sh <run_dir>
#
# run_dir defaults to ./flames/profile.

set -euo pipefail

RUN_DIR="${1:-./flames/profile}"
mkdir -p "$RUN_DIR"

# When running under sudo, py-spy spawns the wrapped python as the
# original user. Files written by that child (timeline JSON, etc.)
# would fail with EACCES against the root-owned run_dir. Fix by
# chowning the dir back to the invoking user.
if [[ -n "${SUDO_USER:-}" ]]; then
    chown -R "$SUDO_USER" "$RUN_DIR"
fi

SVG="$RUN_DIR/profile_tui.svg"
SPEEDSCOPE="$RUN_DIR/profile_tui.speedscope.json"
TIMELINE="$RUN_DIR/profile_tui.timeline.json"

echo ">> writing flame:      $SVG"
echo ">> writing speedscope: $SPEEDSCOPE"
echo ">> writing timeline:   $TIMELINE"
echo ""

# Invoke the venv's python directly. `uv run` adds a shim parent that
# py-spy attaches to instead of the actual python child, surfacing as
# 'Failed to find python version from target process'.
PY=".venv/bin/python"

py-spy record \
    -o "$SVG" \
    -f flamegraph \
    --rate 250 \
    -- \
    "$PY" scripts/qa/profile_tui.py --timeline-out "$TIMELINE"

py-spy record \
    -o "$SPEEDSCOPE" \
    -f speedscope \
    --rate 250 \
    -- \
    "$PY" scripts/qa/profile_tui.py

echo ""
echo ">> done. open $SVG for at-a-glance, $SPEEDSCOPE in speedscope.app for drill-in."
echo ">> use $TIMELINE to map gesture name -> (t_start_unix, t_end_unix) when windowing."
