"""Tests for the FleetModal overlay: open with ctrl+g, dismiss with escape."""

from __future__ import annotations

import pytest

from tests._lilbee_app_test_host import LilbeeAppHost

GIB = 1024**3


def _make_view(*, manual: bool = False):  # type: ignore[no-untyped-def]
    from lilbee.app.placement import GpuInfo, PlacementView, RolePlacementView
    from lilbee.providers.roles import WorkerRole

    return PlacementView(
        gpus=tuple(
            GpuInfo(i, "CUDA", f"CUDA{i}", "NVIDIA A40", 44 * GIB, 44 * GIB) for i in range(2)
        ),
        roles=(
            RolePlacementView(WorkerRole.EMBED, "org/embed.gguf", (0,), None, 1),
            RolePlacementView(WorkerRole.CHAT, "org/chat.gguf", (1,), None, 1),
        ),
        unplaceable=(),
        manual=manual,
        spec_json=None,
    )


class LilbeeTestApp(LilbeeAppHost):
    """Minimal app host for fleet-modal tests."""

    CSS = ""


@pytest.mark.asyncio
async def test_ctrl_g_opens_fleet_modal_and_esc_closes(monkeypatch):
    """ctrl+g opens FleetModal; escape dismisses it and returns to the prior screen."""
    from lilbee.cli.tui.widgets import fleet_body as fbm
    from lilbee.cli.tui.widgets import gpu_fleet_panel as gfp
    from lilbee.cli.tui.widgets.fleet_modal import FleetModal

    monkeypatch.setattr(fbm, "get_placement", lambda: _make_view())
    monkeypatch.setattr(gfp, "probe_gpu_stats", lambda devices: {})

    app = LilbeeTestApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, FleetModal)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FleetModal)


@pytest.mark.asyncio
async def test_ctrl_g_does_not_stack_second_fleet_modal(monkeypatch):
    """Pressing ctrl+g while FleetModal is open is a no-op (re-entry guard)."""
    from lilbee.cli.tui.widgets import fleet_body as fbm
    from lilbee.cli.tui.widgets import gpu_fleet_panel as gfp
    from lilbee.cli.tui.widgets.fleet_modal import FleetModal

    monkeypatch.setattr(fbm, "get_placement", lambda: _make_view())
    monkeypatch.setattr(gfp, "probe_gpu_stats", lambda devices: {})

    app = LilbeeTestApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, FleetModal)
        depth_before = len(app.screen_stack)
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, FleetModal)
        assert len(app.screen_stack) == depth_before


@pytest.mark.asyncio
async def test_fleet_modal_shows_gpu_table(monkeypatch):
    """FleetModal mounts FleetBody which renders the GPU DataTable."""
    from textual.widgets import DataTable

    from lilbee.cli.tui.widgets import fleet_body as fbm
    from lilbee.cli.tui.widgets import gpu_fleet_panel as gfp
    from lilbee.cli.tui.widgets.fleet_body import _GPU_TABLE_ID
    from lilbee.cli.tui.widgets.fleet_modal import FleetModal

    monkeypatch.setattr(fbm, "get_placement", lambda: _make_view())
    monkeypatch.setattr(gfp, "probe_gpu_stats", lambda devices: {})

    app = LilbeeTestApp()
    async with app.run_test(size=(140, 44)) as pilot:
        await pilot.pause()
        await pilot.press("ctrl+g")
        await pilot.pause()
        assert isinstance(app.screen, FleetModal)
        table = app.screen.query_one(_GPU_TABLE_ID, DataTable)
        assert table.row_count == 2
