"""One-shot data migrations invoked from server startup."""

from __future__ import annotations

from lilbee.migrations.relative_source_paths import (
    MARKER_FILENAME,
    run_relative_source_paths_migration,
)

__all__ = ["MARKER_FILENAME", "run_all", "run_relative_source_paths_migration"]


def run_all() -> None:
    """Run every pending data migration in order.

    Each migration is idempotent: if its marker is present under
    ``cfg.data_dir`` the call is a no-op. Safe to invoke on every server
    start (and from CLI entry points that touch the data dir).
    """
    run_relative_source_paths_migration()
