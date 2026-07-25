"""The device probe's failures must reach the user, not vanish."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import pytest

from lilbee.providers.base import ProviderError
from lilbee.providers.fleet import devices as devices_mod


class TestASpawnFailureIsReported:
    """An unrunnable probe looked exactly like a host with no GPU."""

    def test_the_reason_the_probe_could_not_run_is_logged(self, monkeypatch, caplog) -> None:
        def _boom(_binary, _timeout):
            raise OSError("Exec format error")

        monkeypatch.setattr(devices_mod, "_run_list_devices", _boom)
        with caplog.at_level(logging.WARNING, logger="lilbee.providers.fleet.devices"):
            probe = devices_mod.probe_devices(Path("/bin/llama-server"))
        assert probe.devices == []
        assert probe.spoke_protocol is False
        assert "Exec format error" in caplog.text


class TestATimeoutKeepsWhatTheProbeSaid:
    """The probe's own partial output beats fixed advice about someone else's GPU."""

    def test_partial_output_is_carried_into_the_error(self, monkeypatch) -> None:
        def _timeout(*_a, **_k):
            raise subprocess.TimeoutExpired(
                cmd="llama-server --list-devices",
                timeout=30,
                output=b"ggml_vulkan: device 0 hung\n",
            )

        monkeypatch.setattr(devices_mod, "run_bounded", _timeout)
        with pytest.raises(ProviderError) as excinfo:
            devices_mod._run_list_devices(Path("/bin/llama-server"), 30.0)
        assert "ggml_vulkan: device 0 hung" in str(excinfo.value)

    def test_the_advice_names_every_vendor_not_just_one(self, monkeypatch) -> None:
        # An AMD or Intel host hanging in its own driver was told to run nvidia-smi,
        # a tool it does not have, about a GPU it does not own.
        def _timeout(*_a, **_k):
            raise subprocess.TimeoutExpired(cmd="x", timeout=30)

        monkeypatch.setattr(devices_mod, "run_bounded", _timeout)
        with pytest.raises(ProviderError) as excinfo:
            devices_mod._run_list_devices(Path("/bin/llama-server"), 30.0)
        message = str(excinfo.value)
        for tool in ("nvidia-smi", "rocm-smi", "xpu-smi"):
            assert tool in message


class TestACrashAfterTheHeaderIsNotAnUnsupportedFlag:
    """Two different failures wore the same message."""

    def test_a_probe_that_answered_then_died_says_it_crashed(self, monkeypatch, caplog) -> None:
        monkeypatch.setattr(
            devices_mod,
            "_run_list_devices",
            lambda _b, _t: (
                "Available devices:\n  CUDA0: gpu (1 MiB, 1 MiB free)\nSegfault\n",
                139,
            ),
        )
        with caplog.at_level(logging.WARNING, logger="lilbee.providers.fleet.devices"):
            devices_mod.probe_devices(Path("/bin/llama-server"))
        assert "does not appear to support" not in caplog.text
        assert "crashed" in caplog.text

    def test_a_probe_that_never_answered_still_says_unsupported(self, monkeypatch, caplog) -> None:
        monkeypatch.setattr(
            devices_mod, "_run_list_devices", lambda _b, _t: ("usage: llama-server [options]\n", 1)
        )
        with caplog.at_level(logging.WARNING, logger="lilbee.providers.fleet.devices"):
            devices_mod.probe_devices(Path("/bin/llama-server"))
        assert "does not appear to support" in caplog.text


class TestEveryVendorGetsTheWarning:
    """The silent-CPU warning was gated to hosts with an NVIDIA card.

    An Intel Arc or an AMD card the engine failed to enumerate produced exactly
    the same symptom, a fleet planned for CPU, and said nothing at all.
    """

    @staticmethod
    def _probe_reporting_nothing(monkeypatch, vendor_ids: set[int]) -> None:
        from lilbee.providers.fleet import planning as planning_mod
        from lilbee.providers.fleet.devices import DeviceProbe

        monkeypatch.setattr(
            planning_mod, "probe_devices", lambda _b: DeviceProbe([], "", spoke_protocol=True)
        )
        monkeypatch.setattr(
            "lilbee.providers.fleet.cuda_runtime.assert_gpu_devices_usable", lambda *_a: None
        )
        monkeypatch.setattr(
            "lilbee.providers.fleet.gpu_hardware.installed_gpu_vendor_ids",
            lambda: frozenset(vendor_ids),
        )

    @pytest.mark.parametrize(
        ("vendor_id", "vendor"),
        [(0x10DE, "NVIDIA"), (0x1002, "AMD"), (0x8086, "Intel")],
        ids=["nvidia", "amd", "intel"],
    )
    def test_an_unenumerated_card_of_any_vendor_is_reported(
        self, monkeypatch, caplog, vendor_id: int, vendor: str
    ) -> None:
        from lilbee.providers.fleet import planning as planning_mod

        self._probe_reporting_nothing(monkeypatch, {vendor_id})
        with caplog.at_level(logging.WARNING, logger="lilbee.providers.fleet.planning"):
            planning_mod.resolve_devices(Path("/bin/llama-server"))
        assert vendor in caplog.text
        assert "reported none" in caplog.text

    def test_a_host_with_no_gpu_at_all_stays_quiet(self, monkeypatch, caplog) -> None:
        from lilbee.providers.fleet import planning as planning_mod

        self._probe_reporting_nothing(monkeypatch, set())
        with caplog.at_level(logging.WARNING, logger="lilbee.providers.fleet.planning"):
            planning_mod.resolve_devices(Path("/bin/llama-server"))
        assert "reported none" not in caplog.text
