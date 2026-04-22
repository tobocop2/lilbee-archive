"""Migration 0001 — rewrite absolute ``chunks.source`` to paths relative to ``documents_dir``.

Early lilbee builds stored ``chunks.source`` as an absolute path, which made
``documents_dir`` effectively immovable (moving the tree invalidated every
row). The current codebase always writes relative paths (see
``ingest._relative_name``), but any database ingested with the old code still
holds absolutes. This migration rewrites those rows in place, and fixes the
``crawl_meta.json`` sidecar the same way.

The migration is idempotent: on first success it writes a marker file under
``cfg.data_dir`` and subsequent invocations short-circuit before touching the
DB. It's safe to call unconditionally from server startup.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from lilbee.config import CHUNKS_TABLE, cfg
from lilbee.store import escape_sql_string

if TYPE_CHECKING:
    import lancedb.table

log = logging.getLogger(__name__)

MARKER_FILENAME = ".migration-relative-paths-complete"


def _marker_path() -> Path:
    return cfg.data_dir / MARKER_FILENAME


def _legacy_prefix() -> str:
    """Prefix used to detect legacy absolute-path rows.

    ``documents_dir`` + a single trailing separator. Any ``source`` starting
    with this prefix can be safely relativised by stripping the prefix.
    """
    return str(cfg.documents_dir).rstrip(os.sep) + os.sep


def _relativise(abs_source: str, prefix: str) -> str:
    """Strip ``prefix`` from ``abs_source`` and normalise to forward slashes."""
    relative = abs_source[len(prefix) :]
    return relative.replace(os.sep, "/") if os.sep != "/" else relative


def _rewrite_chunks_table(prefix: str) -> int:
    """Rewrite absolute ``source`` values in the ``chunks`` table.

    Returns the number of distinct source values rewritten. Zero means the
    table was absent, empty, or already clean.
    """
    # Import lazily so unit tests that don't need lancedb don't pay the cost.
    import lancedb

    lancedb_dir = cfg.lancedb_dir
    if not lancedb_dir.exists():
        return 0
    db = lancedb.connect(str(lancedb_dir))
    try:
        names = db.list_tables()
        try:
            table_names = list(names.tables)  # type: ignore[union-attr]
        except AttributeError:
            table_names = list(names)  # type: ignore[arg-type]
        if CHUNKS_TABLE not in table_names:
            return 0
        table = db.open_table(CHUNKS_TABLE)
        return _rewrite_table_sources(table, prefix)
    finally:
        # lancedb has no close(); drop the reference so the event loop can
        # shut down cleanly when the caller exits.
        del db


def _rewrite_table_sources(table: lancedb.table.Table, prefix: str) -> int:
    """Rewrite absolute ``source`` values on an already-opened table."""
    rows = table.to_arrow().to_pylist()
    legacy_sources: set[str] = {
        row["source"]
        for row in rows
        if isinstance(row.get("source"), str) and row["source"].startswith(prefix)
    }
    if not legacy_sources:
        return 0
    for abs_source in legacy_sources:
        rel_source = _relativise(abs_source, prefix)
        table.update(
            where=f"source = '{escape_sql_string(abs_source)}'",
            values={"source": rel_source},
        )
        log.info("Migrated chunks.source %r -> %r", abs_source, rel_source)
    return len(legacy_sources)


def _rewrite_crawl_meta(prefix: str) -> int:
    """Rewrite absolute paths inside ``crawl_meta.json``.

    Both keys (URLs, normally) and the embedded ``file`` field are checked —
    a misconfigured older build wrote absolute URLs for local sources. Returns
    the number of entries rewritten.
    """
    meta_path = cfg.data_dir / "crawl_meta.json"
    if not meta_path.exists():
        return 0
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("crawl_meta.json unreadable, skipping migration: %s", meta_path)
        return 0
    if not isinstance(raw, dict):
        return 0

    new_data: dict[str, dict[str, str]] = {}
    changed = 0
    for key, value in raw.items():
        if isinstance(key, str) and key.startswith(prefix):
            new_key = _relativise(key, prefix)
        else:
            new_key = key
        if not isinstance(value, dict):
            new_data[new_key] = value
            if new_key != key:
                changed += 1
            continue
        new_value = dict(value)
        file_val = new_value.get("file")
        if isinstance(file_val, str) and file_val.startswith(prefix):
            new_value["file"] = _relativise(file_val, prefix)
            changed += 1
        elif new_key != key:
            changed += 1
        new_data[new_key] = new_value

    if changed == 0:
        return 0

    _atomic_write_json(meta_path, new_data)
    log.info("Migrated %d crawl_meta entries under %s", changed, meta_path)
    return changed


def _atomic_write_json(path: Path, data: object) -> None:
    """Write ``data`` to ``path`` atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".tmp", delete=False) as tmp:
            tmp_name = tmp.name
            tmp.write(json.dumps(data, indent=2).encode("utf-8"))
        Path(tmp_name).replace(path)
    except BaseException:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        raise


def _mark_complete() -> None:
    marker = _marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.touch()


def run_relative_source_paths_migration() -> dict[str, int]:
    """Run the migration idempotently.

    Returns a summary dict with the count of sources rewritten in the chunks
    table and the crawl_meta sidecar. When the marker file exists both values
    are zero and no DB work happens.
    """
    marker = _marker_path()
    summary = {"chunks_updated": 0, "crawl_meta_updated": 0}
    if marker.exists():
        return summary

    # Group work under a single logical name so log scrapers can find it.
    prefix = _legacy_prefix()
    summary["chunks_updated"] = _rewrite_chunks_table(prefix)
    summary["crawl_meta_updated"] = _rewrite_crawl_meta(prefix)
    _mark_complete()
    log.info(
        "Relative-source-paths migration complete: chunks=%d crawl_meta=%d",
        summary["chunks_updated"],
        summary["crawl_meta_updated"],
    )
    return summary
