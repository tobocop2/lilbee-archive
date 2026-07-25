"""What the engine actually allocated, read back from its own startup report.

The plan is otherwise open-loop: every budget in :mod:`lilbee.providers.fleet.planning`
is a pure function of a snapshot taken before launch, and nothing ever checks
whether it was right. A wrong estimate surfaces as a failed request much later,
with no way to tell an under-estimate from a genuinely full card.

llama.cpp prints its per-device buffer sizes on every load, so the truth is
already in the log. Reading it back turns silent estimator drift into one warning
naming the role, the estimate and the reality, and it costs a regex over a log
tail that is already on disk.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lilbee.providers.roles import WorkerRole

log = logging.getLogger(__name__)

MIB = 1024 * 1024

# "load_tensors:  MTL0_Mapped model buffer size =    82.41 MiB", plus the KV,
# compute and output lines that follow under different prefixes (load_tensors,
# llama_context, llama_kv_cache, sched_reserve). The device label is whatever the
# backend calls itself: CUDA0, MTL0, Vulkan1, CPU. Sizes are always MiB.
# A timestamp and level prefix the line when the engine writes to --log-file, so
# the match is not anchored to the start.
_BUFFER_RE = re.compile(
    r"\S+:\s+(?P<device>\S+)\s+(?:model|KV|compute|output)\s+"
    r"buffer size\s*=\s*(?P<mib>[\d.]+)\s*MiB"
)
# The engine names an mmapped weight buffer "<device>_Mapped" beside the same
# device's other buffers. Same memory, so the suffix is folded away rather than
# splitting one card's total across two keys.
_MAPPED_SUFFIX = "_Mapped"
# Devices that are host memory rather than a GPU. The engine names the mmapped
# weight buffer CPU_Mapped and its scratch CPU; neither occupies VRAM, so
# charging them against a card's budget would report a phantom overrun on every
# partially offloaded model.
_HOST_DEVICES = ("CPU",)


def _is_host_device(device: str) -> bool:
    """Whether *device* names host memory rather than a GPU."""
    return device.upper().startswith(_HOST_DEVICES)


def parse_device_buffers(text: str) -> dict[str, int]:
    """Bytes the engine reported allocating, per device label, from *text*.

    Sums the model, KV, compute and output buffers, which is the same total the
    estimate predicts. Empty when the text carries no buffer report: a load that
    failed before allocating, a log that has rotated past it, or an engine whose
    verbosity is below the level that prints it.
    """
    totals: dict[str, int] = {}
    for match in _BUFFER_RE.finditer(text):
        device = match.group("device").removesuffix(_MAPPED_SUFFIX)
        totals[device] = totals.get(device, 0) + int(float(match.group("mib")) * MIB)
    return totals


def device_footprint(text: str) -> int:
    """Total GPU bytes the engine reported, host buffers excluded."""
    return sum(
        size for device, size in parse_device_buffers(text).items() if not _is_host_device(device)
    )


def report_divergence(
    role: WorkerRole,
    model: str,
    estimated_bytes: int,
    actual_bytes: int,
    *,
    tolerance: float,
) -> bool:
    """Warn when the engine's real footprint diverges materially from the estimate.

    Returns whether a warning was emitted, so a caller can record that this
    instance has already been checked and not repeat it on every request.

    Both directions are worth saying. An under-estimate is how a plan that fit on
    paper OOMs, and it is the one that ends in a failed load. A large
    over-estimate is quieter but costs capacity: it is why a role gets fewer
    slots, a narrower context, or a split it did not need.
    """
    if estimated_bytes <= 0 or actual_bytes <= 0:
        return False
    ratio = actual_bytes / estimated_bytes
    if abs(ratio - 1.0) <= tolerance:
        return False
    log.warning(
        "The %s model %s allocated %.1f GiB of GPU memory but was planned for %.1f GiB "
        "(%+.0f%%). Placement decisions for this model were made on the smaller figure; "
        "if it fails to load or runs slowly, that gap is why.",
        role.value,
        model,
        actual_bytes / 1024**3,
        estimated_bytes / 1024**3,
        (ratio - 1.0) * 100,
    )
    return True


# The engine's own log, one per instance, beside the swap process's log. Named
# by model id so a role's replicas do not overwrite each other.
_ENGINE_LOG_TEMPLATE = "engine-{model_id}.log"
# Env the engine reads for its log destination and threshold. Set through the
# environment rather than argv because the launch is planned before the data
# directory that holds these logs is chosen, and because neither affects sizing,
# which is what the estimate-versus-launch argv parity test covers.
ENV_LOG_FILE = "LLAMA_LOG_FILE"
ENV_LOG_VERBOSITY = "LLAMA_LOG_VERBOSITY"
# Level 4 ("trace") is where the per-device buffer report appears. Measured
# against the bundled engine: the default 3 omits it entirely, and 5 adds a
# per-layer and per-slot flood for the same six lines.
LOAD_REPORT_VERBOSITY = "4"


def engine_log_path(log_dir: Path, model_id: str) -> Path:
    """Where the engine serving *model_id* writes its own log."""
    return log_dir / _ENGINE_LOG_TEMPLATE.format(model_id=model_id)


def engine_log_env(log_dir: Path, model_id: str) -> dict[str, str]:
    """Environment that makes the engine report what it allocated, and where."""
    return {
        ENV_LOG_FILE: str(engine_log_path(log_dir, model_id)),
        ENV_LOG_VERBOSITY: LOAD_REPORT_VERBOSITY,
    }


def check_launch(
    log_dir: Path, model_id: str, role: WorkerRole, model: str, estimated_bytes: int
) -> bool:
    """Compare the engine's own report for *model_id* against the estimate.

    Returns whether a warning was emitted. Silent when the log is absent or
    carries no report yet: the engine writes it during load, and a caller that
    asks too early should get nothing rather than a fabricated comparison.
    """
    try:
        text = engine_log_path(log_dir, model_id).read_text(errors="replace")
    except OSError:
        return False
    actual = device_footprint(text)
    return report_divergence(role, model, estimated_bytes, actual, tolerance=_TOLERANCE)


# How far the engine may land from the estimate before it is worth saying. Wide
# enough that the estimator's normal error is quiet, narrow enough to catch the
# whole-slot and whole-cache mistakes this exists to surface.
_TOLERANCE = 0.25
