"""Profile TUI screens via Textual's pilot harness.

Runs the same gestures a manual tester would (open each screen, type
text, press chord keys, toggle views) and measures the latency of each
step end-to-end. The TUI is a real LilbeeApp running in the same
process, so the measurements include compose + on_mount + watcher
re-renders, just like a real session.

Output:
    [ms]   step
    -----  ----------------------------------
      4.2  open Chat (default)
     38.7  switch to Catalog
      0.4  press v (toggle to list)
    ...

Anything over the per-step budget is flagged with a >>>SLOW<<< marker
so a reader skimming the report sees the regressions immediately.

Usage::

    uv run python scripts/qa/profile_tui.py            # text report
    uv run python scripts/qa/profile_tui.py --json     # machine readable

Exit code is non-zero when at least one step exceeds its budget so the
script can gate CI.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

# Default per-step latency budget (ms). Steps marked with their own
# explicit budget below override this. Conservative on a dev box; CI
# would set tighter budgets via env once a baseline is established.
_DEFAULT_BUDGET_MS = 250.0

# Some steps legitimately take longer (first model-bar paint imports
# heavy provider modules). The budget reflects what's tolerable; it is
# NOT a measurement target, just a regression gate.
_BUDGETS_MS: dict[str, float] = {
    # Boot is heavy (services init, theme load, screen install).
    "boot LilbeeApp + open Chat": 1500.0,
    # Switch budgets target time-to-interactive, not "until every
    # worker settles." The earlier numbers buried the actual switch
    # cost under a fixed 500 ms settle wait that wasn't doing real
    # work, just blocking on pilot.pause(0.05) ten times.
    "switch to Catalog": 500.0,
    "switch to Settings": 600.0,
    "switch to Tasks": 350.0,
    "switch to Status": 350.0,
    "switch to Wiki": 500.0,
    "switch to Catalog (re-entry)": 250.0,
    "type 5 chars in chat input": 500.0,  # Textual TextArea ~75ms/char
    "type 5 chars in catalog search": 800.0,
    "press v (toggle to list view)": 700.0,
    "press v (toggle back to grid)": 600.0,
    "press [": 250.0,
    "press ]": 250.0,
    "press escape (chat normal mode)": 250.0,
    "press i (chat insert mode)": 250.0,
    # Stress budgets. ``type+clear long catalog filter`` types 28 chars
    # then deletes 28; debounce collapses it to two filter passes total.
    # The toggle storm is 8 keystrokes against the list cache. The
    # paging stress is 40 scroll keys with no remount cost.
    "stress: type+clear long catalog filter": 6000.0,
    "stress: 8x grid <-> list toggle": 5500.0,
    "stress: 40x pgdn/pgup in catalog": 6000.0,
    "open ModelPicker (chat)": 600.0,
    "type 5 chars in ModelPicker": 500.0,
    "dismiss ModelPicker": 250.0,
    "switch to Catalog Frontier tab": 800.0,
    "type 5 chars in Frontier search": 500.0,
    "Settings tab: Models": 600.0,
    "Settings tab: Ingest": 400.0,
    "Settings tab: Retrieval": 400.0,
    "Settings tab: Generation": 600.0,
    "Settings tab: Display": 400.0,
    "Settings tab: API-Keys": 400.0,
    "Settings tab: Crawling": 400.0,
    "Settings tab: Wiki": 400.0,
    "Wiki: focus search": 250.0,
    "Wiki: type 5 chars in search": 500.0,
    "Status: expand Configuration": 350.0,
    "Status: expand Documents": 350.0,
    "Status: expand Architecture": 350.0,
    "Status: expand Storage": 350.0,
    "open CrawlDialog": 600.0,
    "type URL in CrawlDialog": 500.0,
    "expand CrawlDialog advanced": 250.0,
    "dismiss CrawlDialog": 250.0,
    "stream 200 reasoning tokens": 4000.0,
    "stream 200 content tokens": 4000.0,
    "switch reasoning collapsed -> open": 250.0,
    "stress: 500 reasoning tokens (burst, real-stream cadence)": 8000.0,
    "stress: 500 content tokens (burst, real-stream cadence)": 8000.0,
}


@dataclass
class StepResult:
    name: str
    ms: float
    budget_ms: float
    over_budget: bool
    error: str | None = None
    t_start_unix: float = 0.0
    t_end_unix: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "ms": round(self.ms, 2),
            "budget_ms": self.budget_ms,
            "over_budget": self.over_budget,
            "error": self.error,
            "t_start_unix": self.t_start_unix,
            "t_end_unix": self.t_end_unix,
        }


@dataclass
class ProfileReport:
    steps: list[StepResult] = field(default_factory=list)

    def add(self, step: StepResult) -> None:
        self.steps.append(step)

    @property
    def any_over_budget(self) -> bool:
        return any(s.over_budget for s in self.steps)

    @property
    def total_ms(self) -> float:
        return sum(s.ms for s in self.steps)

    def render_text(self) -> str:
        out: list[str] = []
        out.append(f"{'ms':>10}  {'step':<60} {'budget':>8}")
        out.append("-" * 88)
        for s in self.steps:
            mark = " >>>SLOW<<<" if s.over_budget else ""
            err = f"  ERROR: {s.error}" if s.error else ""
            out.append(f"{s.ms:>10.2f}  {s.name:<60} {s.budget_ms:>8.0f}{mark}{err}")
        out.append("-" * 88)
        out.append(f"{self.total_ms:>10.2f}  total")
        return "\n".join(out)

    def to_json(self) -> str:
        return json.dumps(
            {
                "total_ms": round(self.total_ms, 2),
                "any_over_budget": self.any_over_budget,
                "steps": [s.to_dict() for s in self.steps],
            },
            indent=2,
        )


class _Profiler:
    """Async helper that times pilot operations against a LilbeeApp."""

    def __init__(self, report: ProfileReport) -> None:
        self.report = report

    async def step(self, name: str, fn, settle: bool = False) -> None:
        """Run *fn* and measure wall time.

        When ``settle`` is True a fixed post-step settle wait runs
        outside the measured window so background workers can land
        before the next step starts. Including the settle in the
        measurement inflates wall time (the pause(0.05) loop dominates)
        without measuring real work.
        """
        budget = _BUDGETS_MS.get(name, _DEFAULT_BUDGET_MS)
        t_start_unix = time.time()
        t0 = time.perf_counter()
        err: str | None = None
        try:
            await fn()
        except Exception as exc:  # surface but keep going so other steps run
            err = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
        ms = (time.perf_counter() - t0) * 1000
        t_end_unix = time.time()
        over = ms > budget or err is not None
        self.report.add(
            StepResult(
                name=name,
                ms=ms,
                budget_ms=budget,
                over_budget=over,
                error=err,
                t_start_unix=t_start_unix,
                t_end_unix=t_end_unix,
            )
        )


async def run_profile() -> ProfileReport:  # noqa: C901, PLR0915
    """Drive a LilbeeApp through every screen + a few interactions."""
    # Imports inside the runner so module-import time doesn't pollute
    # the boot measurement.
    from textual.widgets import Input

    from lilbee.cli.tui.app import LilbeeApp
    from lilbee.cli.tui.widgets.chat_input import ChatInput

    report = ProfileReport()
    profiler = _Profiler(report)

    app = LilbeeApp()

    async with app.run_test(size=(160, 48)) as pilot:

        async def boot() -> None:
            await pilot.pause()

        await profiler.step("boot LilbeeApp + open Chat", boot)

        # Chat input: typing latency.
        async def type_in_chat() -> None:
            inp = app.screen.query_one("#chat-input", ChatInput)
            inp.focus()
            await pilot.pause()
            for ch in "hello":
                await pilot.press(ch)
            await pilot.pause()

        await profiler.step("type 5 chars in chat input", type_in_chat)

        # Brackets must NOT navigate while input has focus (A1 contract).
        async def bracket_in_chat() -> None:
            await pilot.press("left_square_bracket")
            await pilot.pause()
            await pilot.press("right_square_bracket")
            await pilot.pause()

        await profiler.step("press [", bracket_in_chat)

        # Defocus input so brackets navigate at the screen level.
        async def escape_to_normal() -> None:
            await pilot.press("escape")
            await pilot.pause()

        await profiler.step("press escape (chat normal mode)", escape_to_normal)

        async def press_i() -> None:
            await pilot.press("i")
            await pilot.pause()

        await profiler.step("press i (chat insert mode)", press_i)

        # Now defocus and cycle screens.
        await pilot.press("escape")
        await pilot.pause()

        async def to_catalog() -> None:
            app.switch_view("Catalog")
            await pilot.pause()  # one tick: screen mounted + first paint

        async def settle_catalog() -> None:
            for _ in range(10):
                await pilot.pause(0.05)

        await profiler.step("switch to Catalog", to_catalog)
        await settle_catalog()

        async def type_in_catalog() -> None:
            search = app.screen.query_one("#catalog-search", Input)
            search.focus()
            await pilot.pause()
            for ch in "qwen3":
                await pilot.press(ch)
            await pilot.pause()

        await profiler.step("type 5 chars in catalog search", type_in_catalog)

        # Toggle catalog views; B1 ensures this no longer deadlocks.
        async def toggle_to_list() -> None:
            search = app.screen.query_one("#catalog-search", Input)
            search.value = ""
            await pilot.pause()
            # Defocus search so v reaches the screen binding.
            scroll = app.screen.query_one("#catalog-grid")
            scroll.focus()
            await pilot.pause()
            await pilot.press("v")
            await pilot.pause()

        await profiler.step("press v (toggle to list view)", toggle_to_list)

        async def toggle_back() -> None:
            await pilot.press("v")
            await pilot.pause()

        await profiler.step("press v (toggle back to grid)", toggle_back)

        # Settings.
        async def to_settings() -> None:
            app.switch_view("Settings")
            await pilot.pause()

        async def settle_settings() -> None:
            for _ in range(5):
                await pilot.pause(0.05)

        await profiler.step("switch to Settings", to_settings)
        await settle_settings()

        # Settings dropped its filter input -- tabs already group the
        # ~60 settings into 8 small chunks, so search added complexity
        # (debounce, full-DOM walk, populate-all-on-filter) for little
        # navigational value. No "type in settings search" step now.

        async def to_tasks() -> None:
            app.switch_view("Tasks")
            await pilot.pause()

        await profiler.step("switch to Tasks", to_tasks)

        async def to_status() -> None:
            app.switch_view("Status")
            await pilot.pause()

        await profiler.step("switch to Status", to_status)

        # Catalog re-entry should be fast on second visit (install_screen reuse).
        async def to_catalog_again() -> None:
            app.switch_view("Catalog")
            await pilot.pause()

        await profiler.step("switch to Catalog (re-entry)", to_catalog_again)
        await settle_catalog()

        # Stress steps: simulate the kind of heavy catalog navigation a
        # user does while picking a model -- typing a long query,
        # toggling grid <-> list repeatedly, scrolling the list, then
        # clearing and retyping the filter. These exercise paths that
        # were brittle (B1 deadlock, repeat remount on toggle) and
        # produce the "jittery / sluggish" symptoms in user reports.

        async def stress_long_filter() -> None:
            search = app.screen.query_one("#catalog-search", Input)
            search.focus()
            await pilot.pause()
            for ch in "qwen2-instruct-vision-large":
                await pilot.press(ch)
            await pilot.pause(0.2)  # past debounce, single filter pass
            for _ in range(28):
                await pilot.press("backspace")
            await pilot.pause(0.2)

        await profiler.step("stress: type+clear long catalog filter", stress_long_filter)

        async def stress_toggle_storm() -> None:
            scroll = app.screen.query_one("#catalog-grid")
            scroll.focus()
            await pilot.pause()
            for _ in range(8):  # 4 round trips
                await pilot.press("v")
                await pilot.pause()

        await profiler.step("stress: 8x grid <-> list toggle", stress_toggle_storm)

        async def stress_list_pagedown() -> None:
            # Make sure we're in list view, then scroll heavy.
            scroll_id = "#catalog-list" if not app.screen._grid_view else "#catalog-grid"
            scroll = app.screen.query_one(scroll_id)
            scroll.focus()
            await pilot.pause()
            for _ in range(20):
                await pilot.press("pagedown")
            for _ in range(20):
                await pilot.press("pageup")
            await pilot.pause()

        await profiler.step("stress: 40x pgdn/pgup in catalog", stress_list_pagedown)

        # Catalog Frontier sub-tab: lazy-mount + populate. The pane is
        # only added once a frontier-rows worker resolves; in the pilot
        # harness with no API keys we inject a synthetic row so the
        # activation path runs.
        async def to_frontier_tab() -> None:
            from textual.widgets import TabbedContent

            screen = app.screen
            if not getattr(screen, "_frontier_rows", None):
                screen._frontier_rows = list(_synthetic_frontier_rows())
                screen._sync_frontier_tab()
                for _ in range(8):
                    await pilot.pause(0.05)
            tabs = screen.query_one("#catalog-tabs", TabbedContent)
            try:
                tabs.active = "frontier"
            except Exception:
                return
            await pilot.pause()
            for _ in range(6):
                await pilot.pause(0.05)

        await profiler.step("switch to Catalog Frontier tab", to_frontier_tab)

        async def type_frontier_search() -> None:
            search = app.screen.query_one("#catalog-search", Input)
            search.value = ""
            search.focus()
            await pilot.pause()
            for ch in "gpt-4":
                await pilot.press(ch)
            await pilot.pause()

        await profiler.step("type 5 chars in Frontier search", type_frontier_search)

        # ModelPicker modal opens from Chat ModelBar button.
        app.switch_view("Chat")
        await pilot.pause()
        for _ in range(4):
            await pilot.pause(0.05)

        async def open_chat_picker() -> None:
            from lilbee.cli.tui.widgets.model_bar import ModelPickerButton

            btn = app.screen.query_one("#chat-model-button", ModelPickerButton)
            btn.open_picker()
            await pilot.pause()
            for _ in range(4):
                await pilot.pause(0.05)

        await profiler.step("open ModelPicker (chat)", open_chat_picker)

        async def type_in_picker() -> None:
            search = app.screen.query_one("#picker-search", Input)
            search.focus()
            await pilot.pause()
            for ch in "qwen3":
                await pilot.press(ch)
            await pilot.pause()

        await profiler.step("type 5 chars in ModelPicker", type_in_picker)

        async def dismiss_picker() -> None:
            await pilot.press("escape")
            await pilot.pause()

        await profiler.step("dismiss ModelPicker", dismiss_picker)

        # Settings: cycle through every group tab.
        app.switch_view("Settings")
        await pilot.pause()
        for _ in range(6):
            await pilot.pause(0.05)

        for group in (
            "Models",
            "Ingest",
            "Retrieval",
            "Generation",
            "Display",
            "API-Keys",
            "Crawling",
            "Wiki",
        ):
            pane_id = f"settings-tab-{group.lower().replace('-', '_')}"

            async def to_settings_tab(_pid=pane_id) -> None:
                from textual.widgets import TabbedContent

                tabs = app.screen.query_one("#settings-tabs", TabbedContent)
                try:
                    tabs.active = _pid
                except Exception:
                    return
                await pilot.pause()
                for _ in range(4):
                    await pilot.pause(0.05)

            await profiler.step(f"Settings tab: {group}", to_settings_tab)

        # Status: expand each Collapsible section.
        app.switch_view("Status")
        await pilot.pause()
        for _ in range(6):
            await pilot.pause(0.05)

        for label, sec_id in (
            ("Configuration", "config-section"),
            ("Documents", "docs-section"),
            ("Architecture", "arch-section"),
            ("Storage", "storage-section"),
        ):

            async def expand_section(_sid=sec_id) -> None:
                from textual.widgets import Collapsible

                try:
                    section = app.screen.query_one(f"#{_sid}", Collapsible)
                except Exception:
                    return
                section.collapsed = False
                await pilot.pause()
                for _ in range(3):
                    await pilot.pause(0.05)

            await profiler.step(f"Status: expand {label}", expand_section)

        # Wiki: focus + filter (only when wiki view registered).
        from lilbee.core.config import cfg as _cfg

        if _cfg.wiki:
            app.switch_view("Wiki")
            await pilot.pause()
            for _ in range(6):
                await pilot.pause(0.05)

            async def wiki_focus_search() -> None:
                search = app.screen.query_one("#wiki-search", Input)
                search.focus()
                await pilot.pause()

            await profiler.step("Wiki: focus search", wiki_focus_search)

            async def wiki_type_filter() -> None:
                for ch in "alpha":
                    await pilot.press(ch)
                await pilot.pause()

            await profiler.step("Wiki: type 5 chars in search", wiki_type_filter)

        # CrawlDialog modal: open via ChatScreen helper, fill, dismiss.
        app.switch_view("Chat")
        await pilot.pause()
        for _ in range(4):
            await pilot.pause(0.05)

        async def open_crawl_dialog() -> None:
            chat = app.screen
            chat._open_crawl_dialog()
            await pilot.pause()
            for _ in range(4):
                await pilot.pause(0.05)

        await profiler.step("open CrawlDialog", open_crawl_dialog)

        async def type_url_in_crawl() -> None:
            url_in = app.screen.query_one("#crawl-url-input", Input)
            url_in.focus()
            await pilot.pause()
            for ch in "https":
                await pilot.press(ch)
            await pilot.pause()

        await profiler.step("type URL in CrawlDialog", type_url_in_crawl)

        async def expand_crawl_advanced() -> None:
            from textual.widgets import Collapsible

            adv = app.screen.query_one("#crawl-advanced", Collapsible)
            adv.collapsed = False
            await pilot.pause()
            for _ in range(2):
                await pilot.pause(0.05)

        await profiler.step("expand CrawlDialog advanced", expand_crawl_advanced)

        async def dismiss_crawl() -> None:
            await pilot.press("escape")
            await pilot.pause()

        await profiler.step("dismiss CrawlDialog", dismiss_crawl)

        # Thinking-mode rendering. Inject 200 reasoning tokens into a
        # synthetic AssistantMessage and measure the per-update cost of
        # the Collapsible + Static reasoning widget. The actual LLM is
        # not in the loop; this isolates the renderer.
        from lilbee.cli.tui.widgets.message import AssistantMessage

        await pilot.pause()
        chat_log = app.screen.query_one("#chat-log")
        bubble = AssistantMessage()
        await chat_log.mount(bubble)
        await pilot.pause()

        async def stream_reasoning() -> None:
            for i in range(200):
                bubble.append_reasoning(f"thinking step {i} ")
                if i % 20 == 0:
                    await pilot.pause()

        await profiler.step("stream 200 reasoning tokens", stream_reasoning)

        async def stream_content() -> None:
            for i in range(200):
                bubble.append_content(f"answer chunk {i} ")
                if i % 20 == 0:
                    await pilot.pause()

        await profiler.step("stream 200 content tokens", stream_content)

        async def toggle_reasoning() -> None:
            from textual.widgets import Collapsible

            block = bubble.query_one(Collapsible)
            block.collapsed = not block.collapsed
            await pilot.pause()

        await profiler.step("switch reasoning collapsed -> open", toggle_reasoning)

        # Stress: simulate real qwen3 thinking-mode streaming. Reasoning
        # tokens arrive in tight bursts via call_from_thread; the chat
        # screen batches at ~50 ms intervals, but the message widget
        # itself has no debounce on reasoning. With a 60 s thinking
        # phase that produces ~1200 batched calls, full-string rejoin +
        # Static.update on every call is the suspected soft-lock cause.
        # Single pilot.pause at the end so the cost is captured raw.
        bubble2 = AssistantMessage()
        await chat_log.mount(bubble2)
        await pilot.pause()

        async def stress_reasoning_burst() -> None:
            for i in range(500):
                bubble2.append_reasoning(f"r{i} ")
            await pilot.pause()

        await profiler.step(
            "stress: 500 reasoning tokens (burst, real-stream cadence)", stress_reasoning_burst
        )

        bubble3 = AssistantMessage()
        await chat_log.mount(bubble3)
        await pilot.pause()

        async def stress_content_burst() -> None:
            for i in range(500):
                bubble3.append_content(f"c{i} ")
            await pilot.pause()

        await profiler.step(
            "stress: 500 content tokens (burst, real-stream cadence)", stress_content_burst
        )

    return report


def _synthetic_frontier_rows():
    """Two stubbed FrontierCatalogRow rows so the lazy-mount path runs.

    The pilot harness has no API keys configured, so the real fetch
    worker returns an empty list and the Frontier pane never mounts.
    Injecting a tiny synthetic list lets the activation gesture be
    measured without touching live cloud APIs.
    """
    from lilbee.cli.tui.screens.catalog_utils import FrontierCatalogRow, KeyStatus

    return [
        FrontierCatalogRow(
            name="gpt-4o",
            ref="gpt-4o",
            task="chat",
            provider="OpenAI",
            provider_id="openai",
            key_status=KeyStatus.MISSING_KEY,
        ),
        FrontierCatalogRow(
            name="claude-opus-4",
            ref="anthropic/claude-opus-4",
            task="chat",
            provider="Anthropic",
            provider_id="anthropic",
            key_status=KeyStatus.MISSING_KEY,
        ),
    ]


async def _switch_and_settle(app, pilot, expected_type, view_name) -> None:
    app.switch_view(view_name)
    await pilot.pause()
    for _ in range(10):
        await pilot.pause(0.05)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--json", action="store_true", help="emit JSON instead of text")
    parser.add_argument(
        "--timeline-out",
        type=str,
        default=None,
        help="write per-step (start,end) unix timestamps as JSON for speedscope correlation",
    )
    args = parser.parse_args()

    report = asyncio.run(run_profile())

    if args.timeline_out:
        timeline = {
            s.name: {"t_start_unix": s.t_start_unix, "t_end_unix": s.t_end_unix, "ms": s.ms}
            for s in report.steps
        }
        with open(args.timeline_out, "w") as fh:
            json.dump(timeline, fh, indent=2)

    if args.json:
        print(report.to_json())
    else:
        print(report.render_text())

    return 1 if report.any_over_budget else 0


if __name__ == "__main__":
    sys.exit(main())
