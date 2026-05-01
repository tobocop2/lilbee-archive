# ruff: noqa: S603, S607, S108, S112
"""Drive the lilbee QA matrix via tmux send-keys.

The runner spawns a fresh tmux session named ``lilbee-qa-pizza`` (the
user's other sessions are never touched), launches the TUI in one
window, and walks a list of cells. Each cell sends a gesture, waits for
the pane to settle, captures it, and asserts expected fragments are
present. Per-cell timestamps are recorded for the long-running py-spy
attach (script 3) so individual gestures can be windowed in speedscope.

Cells live in ``CELLS``. Each cell carries:

- id          stable label, used as artefact filename
- pane        tmux window name to target
- gesture     list of (action, *args) tuples; "send" sends literal text,
              "key" sends a tmux key name, "sleep" pauses
- fragments   substrings (or regex when prefixed with ``re:``) that must
              appear in the captured pane after the gesture; checked in
              order
- timeout     max idle wait per gesture step (default 10s)
- pre         optional callable that runs before the gesture (env tweak,
              fixture seed, etc.)

Usage::

    uv run python scripts/qa/run_matrix.py            # full walk
    uv run python scripts/qa/run_matrix.py --from TUI-Cat-1
    uv run python scripts/qa/run_matrix.py --cell TUI-Chat-1
    uv run python scripts/qa/run_matrix.py --no-tui    # skip TUI cells
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SESSION = "lilbee-qa-pizza"
TMUX_WIDTH = 200
TMUX_HEIGHT = 60
DEFAULT_IDLE_TIMEOUT = 10.0
DEFAULT_IDLE_POLL = 0.4

# Windows the runner creates. The first window is created with the
# session; the rest are added after.
WINDOWS = ("srv", "w-cli", "w-http", "w-mcp", "w-tui", "crawl", "driver")


def _tmux(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["tmux", *args]
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def _tmux_target(window: str) -> str:
    # Single-pane windows: just session:window. tmux 3.6 rejects the
    # explicit .0 pane suffix when the window has no split panes.
    return f"{SESSION}:{window}"


def _send_text(target: str, text: str) -> None:
    _tmux("send-keys", "-t", target, "-l", text)


def _send_key(target: str, key: str) -> None:
    _tmux("send-keys", "-t", target, key)


def _capture(target: str) -> str:
    out = _tmux("capture-pane", "-t", target, "-p", "-J", check=False)
    return out.stdout


def _wait_idle(
    target: str, timeout: float = DEFAULT_IDLE_TIMEOUT, poll: float = DEFAULT_IDLE_POLL
) -> bool:
    """Poll the pane until two consecutive captures match.

    Returns True if the pane settled, False on timeout.
    """
    deadline = time.monotonic() + timeout
    prev = _capture(target)
    while time.monotonic() < deadline:
        time.sleep(poll)
        cur = _capture(target)
        if cur == prev:
            return True
        prev = cur
    return False


def _wait_for_text(
    target: str, needle: str, timeout: float = DEFAULT_IDLE_TIMEOUT, poll: float = 0.3
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if needle in _capture(target):
            return True
        time.sleep(poll)
    return False


@dataclass
class Cell:
    id: str
    pane: str
    gesture: list[tuple]
    fragments: list[str] = field(default_factory=list)
    timeout: float = DEFAULT_IDLE_TIMEOUT
    pre: Callable[[], None] | None = None
    needs_tui: bool = True


@dataclass
class CellResult:
    id: str
    pane: str
    pass_: bool
    captured: str
    missing_fragments: list[str]
    elapsed_ms: float
    t_start_unix: float
    t_end_unix: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "pane": self.pane,
            "pass": self.pass_,
            "missing_fragments": self.missing_fragments,
            "elapsed_ms": round(self.elapsed_ms, 2),
            "t_start_unix": self.t_start_unix,
            "t_end_unix": self.t_end_unix,
            "error": self.error,
        }


def _check_fragments(captured: str, fragments: list[str]) -> list[str]:
    missing: list[str] = []
    for frag in fragments:
        if frag.startswith("re:"):
            if not re.search(frag[3:], captured):
                missing.append(frag)
        elif frag not in captured:
            missing.append(frag)
    return missing


def _run_gesture(target: str, gesture: list[tuple], timeout: float) -> None:
    for step in gesture:
        action = step[0]
        if action == "send":
            _send_text(target, step[1])
        elif action == "key":
            _send_key(target, step[1])
        elif action == "sleep":
            time.sleep(float(step[1]))
        elif action == "wait_for":
            _wait_for_text(target, step[1], timeout=timeout)
        else:
            raise ValueError(f"unknown gesture action: {action!r}")
        # short pause between gesture steps so tmux flushes
        time.sleep(0.05)


def run_cell(cell: Cell, run_dir: Path) -> CellResult:
    target = _tmux_target(cell.pane)
    if cell.pre is not None:
        cell.pre()
    t_start_unix = time.time()
    t0 = time.perf_counter()
    err: str | None = None
    try:
        _run_gesture(target, cell.gesture, cell.timeout)
        _wait_idle(target, timeout=cell.timeout)
    except Exception as exc:  # surface and keep going
        err = f"{type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - t0) * 1000
    t_end_unix = time.time()
    captured = _capture(target)
    cell_dir = run_dir / "cells" / cell.id
    cell_dir.mkdir(parents=True, exist_ok=True)
    (cell_dir / "pane.txt").write_text(captured)
    missing = _check_fragments(captured, cell.fragments)
    return CellResult(
        id=cell.id,
        pane=cell.pane,
        pass_=err is None and not missing,
        captured=captured,
        missing_fragments=missing,
        elapsed_ms=elapsed_ms,
        t_start_unix=t_start_unix,
        t_end_unix=t_end_unix,
        error=err,
    )


# === Session setup ===


def setup_session(run_dir: Path, *, env: dict[str, str]) -> None:
    teardown_session()
    _tmux(
        "new-session",
        "-d",
        "-s",
        SESSION,
        "-n",
        WINDOWS[0],
        "-x",
        str(TMUX_WIDTH),
        "-y",
        str(TMUX_HEIGHT),
    )
    for w in WINDOWS[1:]:
        _tmux("new-window", "-t", SESSION, "-n", w)

    # Push environment into every window with a single set-environment
    # call per var. Variables propagate to children spawned by send-keys.
    for k, v in env.items():
        _tmux("set-environment", "-t", SESSION, k, v)

    # cd every window into the worktree.
    cwd = os.getcwd()
    for w in WINDOWS:
        _send_text(_tmux_target(w), f"cd {cwd}")
        _send_key(_tmux_target(w), "Enter")
        # Apply env in the shell too (set-environment alone doesn't
        # inject into already-running shells).
        env_prefix = " ".join(f"{k}={v!r}" for k, v in env.items())
        _send_text(_tmux_target(w), f"export {env_prefix}")
        _send_key(_tmux_target(w), "Enter")
        time.sleep(0.05)


def teardown_session() -> None:
    _tmux("kill-session", "-t", SESSION, check=False)


def launch_tui() -> None:
    _send_text(_tmux_target("w-tui"), "uv run lilbee")
    _send_key(_tmux_target("w-tui"), "Enter")
    # Wait for the splash to clear and the chat screen to appear.
    _wait_for_text(_tmux_target("w-tui"), "Search", timeout=30.0)
    time.sleep(1.5)


def launch_server(host: str = "127.0.0.1", port: int = 7433) -> bool:
    """Start lilbee serve in the srv window and wait for /api/health.

    Returns True if the server became reachable within 60 s.
    """
    _send_text(_tmux_target("srv"), f"uv run lilbee serve --host {host} --port {port}")
    _send_key(_tmux_target("srv"), "Enter")
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        time.sleep(1.0)
        try:
            out = subprocess.run(
                ["curl", "-s", f"http://{host}:{port}/api/health"],
                capture_output=True,
                text=True,
                timeout=2.0,
                check=False,
            )
            if "ok" in out.stdout:
                return True
        except subprocess.TimeoutExpired:
            continue
    return False


def tui_pid() -> int | None:
    """Return the pid of the python process inside the TUI window."""
    out = _tmux(
        "list-panes",
        "-t",
        _tmux_target("w-tui"),
        "-F",
        "#{pane_pid}",
        check=False,
    )
    pane_pid = out.stdout.strip()
    if not pane_pid:
        return None
    try:
        children = subprocess.run(
            ["pgrep", "-P", pane_pid],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None
    pids = [int(p) for p in children.stdout.split() if p.strip()]
    if not pids:
        return None
    # Walk the tree until we find the python process.
    for pid in pids:
        try:
            cmd = subprocess.run(
                ["ps", "-o", "command=", "-p", str(pid)],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
        except Exception:
            continue
        if "python" in cmd:
            return pid
        # Recurse one level for shells wrapping uv.
        sub = subprocess.run(
            ["pgrep", "-P", str(pid)],
            capture_output=True,
            text=True,
            check=False,
        )
        for sub_pid in sub.stdout.split():
            try:
                sub_cmd = subprocess.run(
                    ["ps", "-o", "command=", "-p", sub_pid],
                    capture_output=True,
                    text=True,
                    check=False,
                ).stdout.strip()
            except Exception:
                continue
            if "python" in sub_cmd or "lilbee" in sub_cmd:
                return int(sub_pid)
    return pids[0]


# === Cell library ===


def _tui_cells() -> list[Cell]:
    cells: list[Cell] = []
    cells.append(
        Cell(
            id="TUI-Boot",
            pane="w-tui",
            gesture=[("sleep", 0.5)],
            fragments=["Search"],
        )
    )
    cells.append(
        Cell(
            id="TUI-Chat-Type",
            pane="w-tui",
            gesture=[("send", "hello world"), ("sleep", 0.5)],
            fragments=["hello world"],
        )
    )
    cells.append(
        Cell(
            id="TUI-Chat-Clear",
            pane="w-tui",
            gesture=[("key", "Escape"), ("send", "/clear"), ("key", "Enter"), ("sleep", 0.5)],
            fragments=[],
        )
    )
    cells.append(
        Cell(
            id="TUI-Cat-Open",
            pane="w-tui",
            gesture=[("key", "F2"), ("sleep", 1.0)],
            fragments=["Catalog"],
            timeout=15.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Cat-Search",
            pane="w-tui",
            gesture=[("key", "/"), ("send", "qwen"), ("sleep", 1.0)],
            fragments=["qwen"],
        )
    )
    cells.append(
        Cell(
            id="TUI-Cat-ToggleList",
            pane="w-tui",
            gesture=[("key", "Escape"), ("key", "v"), ("sleep", 0.5)],
            fragments=[],
        )
    )
    cells.append(
        Cell(
            id="TUI-Cat-ToggleGrid",
            pane="w-tui",
            gesture=[("key", "v"), ("sleep", 0.5)],
            fragments=[],
        )
    )
    cells.append(
        Cell(
            id="TUI-Set-Open",
            pane="w-tui",
            gesture=[("key", "F3"), ("sleep", 1.5)],
            fragments=["Settings"],
            timeout=15.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Stat-Open",
            pane="w-tui",
            gesture=[("key", "F4"), ("sleep", 1.5)],
            fragments=["re:Configuration|Storage|Documents"],
            timeout=15.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Tasks-Open",
            pane="w-tui",
            gesture=[("key", "F5"), ("sleep", 1.0)],
            fragments=["Task"],
            timeout=15.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Crawl-OpenDialog",
            pane="w-tui",
            gesture=[
                ("key", "F1"),
                ("sleep", 0.5),
                ("key", "i"),
                ("send", "/crawl"),
                ("key", "Enter"),
                ("sleep", 1.0),
            ],
            fragments=["re:Crawl|crawl|URL|url"],
            timeout=15.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Crawl-Cancel",
            pane="w-tui",
            gesture=[("key", "Escape"), ("sleep", 0.5)],
            fragments=[],
        )
    )
    # Thinking and non-thinking chat paths -- profiled side by side
    # under script 3 (TUI attach). User reported a soft LOCK during the
    # thinking phase. We capture both so the flames can be compared.
    # Both prompts go through real qwen 0.6b streaming.
    cells.append(
        Cell(
            id="TUI-Chat-NoThink",
            pane="w-tui",
            gesture=[
                ("key", "F1"),
                ("sleep", 1.0),
                ("key", "i"),
                ("send", "/no_think Reply with one word: yes."),
                ("key", "Enter"),
                ("sleep", 15.0),
            ],
            fragments=["re:yes|no|Yes|No"],
            timeout=30.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Chat-Thinking",
            pane="w-tui",
            gesture=[
                ("key", "Escape"),
                ("send", "/clear"),
                ("key", "Enter"),
                ("sleep", 1.0),
                ("key", "i"),
                ("send", "What is 17 times 23? Show your reasoning step by step."),
                ("key", "Enter"),
                ("sleep", 60.0),
            ],
            fragments=["re:391|17.*23|thinking|reasoning"],
            timeout=120.0,
        )
    )
    cells.append(
        Cell(
            id="TUI-Chat-ThinkingDuringStream",
            pane="w-tui",
            gesture=[
                ("key", "Escape"),
                ("send", "/clear"),
                ("key", "Enter"),
                ("sleep", 1.0),
                ("key", "i"),
                ("send", "List the first 50 prime numbers and explain why each is prime."),
                ("key", "Enter"),
                ("sleep", 90.0),
            ],
            fragments=["re:prime|2|3|5|7"],
            timeout=180.0,
        )
    )
    return cells


def _http_cells() -> list[Cell]:
    return [
        Cell(
            id="HTTP-Stream",
            pane="w-http",
            needs_tui=False,
            gesture=[
                (
                    "send",
                    "curl -s -N -X POST http://127.0.0.1:7433/api/chat/stream "
                    '-H "Content-Type: application/json" '
                    '-d \'{"messages":[{"role":"user","content":"hi"}]}\' | head -20',
                ),
                ("key", "Enter"),
                ("sleep", 8.0),
            ],
            fragments=["re:event:|TOKEN|DONE"],
            timeout=20.0,
        ),
    ]


def _mcp_cells() -> list[Cell]:
    return [
        Cell(
            id="MCP-Search",
            pane="w-mcp",
            needs_tui=False,
            gesture=[
                (
                    "send",
                    "uv run python scripts/qa/mcp_driver.py search 'battery technology'",
                ),
                ("key", "Enter"),
                ("sleep", 8.0),
            ],
            fragments=["re:result|results|chunks|source"],
            timeout=30.0,
        ),
    ]


def all_cells() -> list[Cell]:
    return [*_tui_cells(), *_http_cells(), *_mcp_cells()]


# === Main ===


def main() -> int:  # noqa: PLR0915
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--run-dir", default=None, help="artefact root (default: /tmp/lilbee-qa-runs/pizza-<ISO>)"
    )
    parser.add_argument("--cell", default=None, help="run only this cell id")
    parser.add_argument("--from", dest="from_id", default=None, help="start at this cell id")
    parser.add_argument("--no-tui", action="store_true", help="skip cells that require the TUI")
    parser.add_argument(
        "--keep-session", action="store_true", help="leave the tmux session alive on exit"
    )
    parser.add_argument("--data-dir", default="/tmp/lilbee-qa-pizza/data")
    parser.add_argument("--documents-dir", default="/tmp/lilbee-qa-pizza/documents")
    args = parser.parse_args()

    iso = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_dir = Path(args.run_dir or f"/tmp/lilbee-qa-runs/pizza-{iso}")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "flames").mkdir(exist_ok=True)
    print(f">> run dir: {run_dir}")

    env = {
        "LILBEE_DATA": args.data_dir,
        "LILBEE_NO_SPLASH": "1",
        "LILBEE_LOG_LEVEL": "DEBUG",
    }
    Path(args.data_dir).mkdir(parents=True, exist_ok=True)

    setup_session(run_dir, env=env)
    print(f">> tmux session up: {SESSION}")

    cells = all_cells()
    if args.cell:
        cells = [c for c in cells if c.id == args.cell]
    elif args.from_id:
        idx = next((i for i, c in enumerate(cells) if c.id == args.from_id), 0)
        cells = cells[idx:]
    if args.no_tui:
        cells = [c for c in cells if not c.needs_tui]

    if any(c.id.startswith("HTTP-") for c in cells):
        print(">> launching lilbee serve in window srv...")
        if not launch_server():
            print("!! server did not become reachable; HTTP cells will fail")

    if any(c.needs_tui for c in cells):
        print(">> launching TUI in window w-tui...")
        launch_tui()
        pid = tui_pid()
        duration_estimate = max(60, int(sum(c.timeout for c in cells if c.needs_tui) + 30))
        print()
        print("=" * 70)
        print(">> TUI READY for py-spy attach (script 3)")
        print(f">> PID: {pid}")
        print(f">> estimated duration: {duration_estimate}s")
        print(">> run in another shell:")
        attach_cmd = (
            f">>     sudo bash scripts/qa/profile_tui_attach.sh "
            f"{pid} {duration_estimate} {run_dir}/flames/tui"
        )
        print(attach_cmd)
        print("=" * 70)
        with contextlib.suppress(EOFError):
            input(">> press ENTER once py-spy is recording (or to skip and keep going)... ")

    results: list[CellResult] = []
    for cell in cells:
        if cell.needs_tui and args.no_tui:
            continue
        print(f">> cell {cell.id} (pane={cell.pane})")
        res = run_cell(cell, run_dir)
        results.append(res)
        marker = "PASS" if res.pass_ else "FAIL"
        print(f"   {marker}  {res.elapsed_ms:.1f} ms  missing={res.missing_fragments}")

    # Write timestamps file (used by speedscope time-windowing).
    timestamps = {
        r.id: {"t_start_unix": r.t_start_unix, "t_end_unix": r.t_end_unix} for r in results
    }
    (run_dir / "flames" / "tui_walk.timestamps.json").write_text(json.dumps(timestamps, indent=2))
    (run_dir / "results.json").write_text(json.dumps([r.to_dict() for r in results], indent=2))
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r.pass_),
        "failed": sum(1 for r in results if not r.pass_),
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print()
    print(
        f">> {summary['passed']}/{summary['total']} passed; results in {run_dir / 'results.json'}"
    )

    if not args.keep_session:
        teardown_session()

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
