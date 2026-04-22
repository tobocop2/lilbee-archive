"""Shared visual tokens for catalog widgets (grid card + list row)."""

from __future__ import annotations

from lilbee.models import ModelTask

MIDDLE_DOT = "·"

# TODO(rerank-tui): dedicated rerank row/filter in catalog grid
# Rerank shares the embedding pill colour because both are retrieval-precision
# adjuncts — keeps the grid legible without a dedicated palette entry until
# we design a first-class rerank row.
TASK_COLORS: dict[str, str] = {
    ModelTask.CHAT: "$primary",
    ModelTask.EMBEDDING: "$secondary",
    ModelTask.VISION: "$warning",
    ModelTask.RERANK: "$secondary",
}
