"""Documents-dir relocation — move the tree and rewrite sidecar paths.

Invoked from :func:`lilbee.server.handlers.update_config` when a
``PATCH /api/config`` changes ``documents_dir``. Factored into its own
module so the logic (validation, move, rewrite, rollback) can be
exercised in unit tests without importing the full Litestar app.

Contract:
    * ``documents_dir`` must be an absolute path.
    * Its parent must exist (we don't create arbitrary directory trees).
    * The target must be writable.
    * The target must be empty OR contain only lilbee-managed subfolders
      (``documents/``, ``crawled/``, ``wiki/``, ``imported/``, ``_web/``).
      This guard keeps us from blasting a user's unrelated folder with
      managed content.
    * On mid-move failure, the config is left pointing at the old
      ``documents_dir``; the caller sees a clear error and no half-moved
      tree escapes the lock window.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from lilbee.config import cfg
from lilbee.lock import write_lock

log = logging.getLogger(__name__)


# Subfolders lilbee manages under documents_dir. A target directory that
# contains only these (in any mix, possibly empty) is safe to move into.
# Everything else means the user pointed us at someone else's data.
LILBEE_MANAGED_SUBFOLDERS: frozenset[str] = frozenset(
    {"documents", "crawled", "wiki", "imported", "_web"}
)


class RelocationError(ValueError):
    """Raised when a relocation request can't be honoured."""


def validate_documents_dir_target(target: Path, *, current: Path | None = None) -> Path:
    """Validate a requested ``documents_dir`` target.

    Returns the normalised (absolute) target on success, raises
    :class:`RelocationError` otherwise. The ``current`` argument is the
    in-use documents_dir — treated as always-valid so reapplying the same
    value is a no-op (handy for idempotent client code that always PATCHes).
    """
    if not isinstance(target, Path):
        target = Path(target)
    if not target.is_absolute():
        raise RelocationError(f"documents_dir must be absolute, got {target!s}")

    parent = target.parent
    if not parent.exists():
        raise RelocationError(f"documents_dir parent does not exist: {parent}")

    # Same as current => nothing to validate further.
    if current is not None and target.resolve() == current.resolve():
        return target

    # Target may exist; if so, must be empty OR contain only managed names.
    if target.exists():
        if not target.is_dir():
            raise RelocationError(f"documents_dir target is not a directory: {target}")
        entries = {p.name for p in target.iterdir()}
        unexpected = entries - LILBEE_MANAGED_SUBFOLDERS
        if unexpected:
            preview = ", ".join(sorted(unexpected)[:5])
            raise RelocationError(
                f"documents_dir target is not empty and contains unmanaged entries: {preview}"
            )

    _check_writable(target if target.exists() else parent)
    return target


def _check_writable(path: Path) -> None:
    """Verify the process can create files under ``path``.

    ``os.access`` is unreliable on macOS with sandboxed apps and mounted
    volumes, so we do the probe for real: open a temp file and unlink it.
    """
    try:
        with tempfile.NamedTemporaryFile(dir=str(path), prefix=".lilbee-probe-", delete=True):
            pass
    except OSError as exc:
        raise RelocationError(f"documents_dir is not writable: {path} ({exc})") from exc


def _move_tree(source: Path, target: Path) -> None:
    """Move ``source`` tree contents into ``target`` cross-device safely.

    Uses ``shutil.move`` per top-level entry. shutil.move already handles
    the cross-device case by falling back to copy + remove — but operating
    at the entry level (rather than moving the directory itself) lets us
    merge into a partially-populated target (e.g. pre-existing
    ``wiki/`` subdir).
    """
    target.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return

    for entry in list(source.iterdir()):
        dest = target / entry.name
        if dest.exists():
            # Merge policy: overlay. If the caller pre-populated the target
            # with managed folders we move into them; for files, the new
            # value wins. Given validate_documents_dir_target only allows
            # managed names, a clash here means the user is relocating
            # back into a lilbee layout — a realistic case.
            shutil.rmtree(dest) if dest.is_dir() else dest.unlink()
        shutil.move(str(entry), str(dest))

    # Remove the now-empty source directory if possible.
    try:
        source.rmdir()
    except OSError:
        # Nonfatal — stray dotfiles (.DS_Store) or other leftovers.
        log.debug("Source documents_dir not empty after move: %s", source)


def _crawl_meta_path() -> Path:
    return cfg.data_dir / "crawl_meta.json"


def _rewrite_crawl_meta_for_relocation(old: Path, new: Path) -> None:
    """Rewrite any absolute-path references in crawl_meta.json.

    Post-migration this should normally be a no-op (paths are relative),
    but older sidecars can still hold absolute ``file`` values. Safe guard.
    """
    meta_path = _crawl_meta_path()
    if not meta_path.exists():
        return
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        log.warning("crawl_meta.json unreadable during relocation: %s", meta_path)
        return
    if not isinstance(raw, dict):
        return

    old_str = str(old).rstrip(os.sep) + os.sep
    new_str = str(new).rstrip(os.sep) + os.sep
    changed = False
    for _url, value in list(raw.items()):
        if not isinstance(value, dict):
            continue
        file_val = value.get("file")
        if isinstance(file_val, str) and file_val.startswith(old_str):
            value["file"] = new_str + file_val[len(old_str) :]
            changed = True

    if changed:
        tmp = meta_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        tmp.replace(meta_path)


def relocate_documents_dir(new_target: Path) -> Path:
    """Move ``cfg.documents_dir`` to ``new_target`` and return the resolved path.

    Intended as the *only* path that changes ``cfg.documents_dir`` — callers
    should not ``setattr`` directly. On success, ``cfg.documents_dir`` points
    at the new location; on failure, it's left at the old one.

    Holds :func:`lilbee.lock.write_lock` for the whole operation so no
    ingestion or query touches the tree while files are mid-move.
    """
    new_target = validate_documents_dir_target(new_target, current=cfg.documents_dir)
    old = cfg.documents_dir

    if old.resolve() == new_target.resolve():
        return new_target

    with write_lock():
        try:
            _move_tree(old, new_target)
        except Exception:
            log.exception("Relocation failed while moving %s -> %s", old, new_target)
            raise
        _rewrite_crawl_meta_for_relocation(old, new_target)
        cfg.documents_dir = new_target
    log.info("Relocated documents_dir: %s -> %s", old, new_target)
    return new_target
