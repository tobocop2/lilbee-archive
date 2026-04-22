"""Tests for documents_dir relocation (server/relocate.py + update_config wiring)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from lilbee.config import cfg
from lilbee.server import handlers
from lilbee.server.relocate import (
    LILBEE_MANAGED_SUBFOLDERS,
    RelocationError,
    relocate_documents_dir,
    validate_documents_dir_target,
)


@pytest.fixture()
def relocate_env(tmp_path: Path):
    """Set up cfg with a populated documents_dir + data_dir."""
    cfg.data_root = tmp_path
    cfg.documents_dir = tmp_path / "docs_old"
    cfg.data_dir = tmp_path / "data"
    cfg.lancedb_dir = tmp_path / "data" / "lancedb"
    cfg.documents_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    (cfg.documents_dir / "notes.md").write_text("hello\n")
    (cfg.documents_dir / "crawled").mkdir()
    (cfg.documents_dir / "crawled" / "a.md").write_text("a\n")
    yield tmp_path


class TestValidateDocumentsDirTarget:
    def test_rejects_relative_path(self, relocate_env: Path) -> None:
        with pytest.raises(RelocationError, match="absolute"):
            validate_documents_dir_target(Path("relative/path"))

    def test_rejects_missing_parent(self, tmp_path: Path) -> None:
        target = tmp_path / "nope" / "child"
        with pytest.raises(RelocationError, match="parent does not exist"):
            validate_documents_dir_target(target)

    def test_rejects_non_directory_target(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x")
        with pytest.raises(RelocationError, match="not a directory"):
            validate_documents_dir_target(target)

    def test_rejects_non_empty_target_with_unmanaged_content(self, tmp_path: Path) -> None:
        target = tmp_path / "mixed"
        target.mkdir()
        (target / "random-file.txt").write_text("x")
        with pytest.raises(RelocationError, match="unmanaged entries"):
            validate_documents_dir_target(target)

    def test_accepts_empty_target(self, tmp_path: Path) -> None:
        target = tmp_path / "new"
        target.mkdir()
        assert validate_documents_dir_target(target) == target

    def test_accepts_target_with_only_managed_subfolders(self, tmp_path: Path) -> None:
        target = tmp_path / "layout"
        target.mkdir()
        for name in LILBEE_MANAGED_SUBFOLDERS:
            (target / name).mkdir()
        assert validate_documents_dir_target(target) == target

    def test_accepts_nonexistent_target_when_parent_exists(self, tmp_path: Path) -> None:
        target = tmp_path / "not-yet"
        assert validate_documents_dir_target(target) == target

    def test_same_as_current_short_circuits(self, relocate_env: Path) -> None:
        # Even if current dir has odd contents, validating re-assignment of
        # the same path must not fail.
        same = cfg.documents_dir
        (same / "arbitrary.txt").write_text("ok")
        assert validate_documents_dir_target(same, current=same) == same

    def test_coerces_string_to_path(self, tmp_path: Path) -> None:
        target = tmp_path / "str-target"
        target.mkdir()
        assert validate_documents_dir_target(str(target)) == target  # type: ignore[arg-type]

    def test_rejects_non_writable_target(self, tmp_path: Path) -> None:
        target = tmp_path / "sentinel"
        target.mkdir()
        with (
            mock.patch(
                "lilbee.server.relocate.tempfile.NamedTemporaryFile",
                side_effect=OSError("permission denied"),
            ),
            pytest.raises(RelocationError, match="not writable"),
        ):
            validate_documents_dir_target(target)


class TestRelocateDocumentsDir:
    def test_moves_tree_to_empty_target(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        relocate_documents_dir(new_target)

        assert cfg.documents_dir == new_target
        assert (new_target / "notes.md").read_text() == "hello\n"
        assert (new_target / "crawled" / "a.md").read_text() == "a\n"
        assert not (relocate_env / "docs_old" / "notes.md").exists()

    def test_relocate_back(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        original = cfg.documents_dir
        relocate_documents_dir(new_target)
        relocate_documents_dir(original)

        assert cfg.documents_dir == original
        assert (original / "notes.md").read_text() == "hello\n"

    def test_relocate_into_pre_existing_managed_layout(self, relocate_env: Path) -> None:
        # A pre-existing target with only managed subfolders should merge.
        new_target = relocate_env / "docs_new"
        (new_target / "crawled").mkdir(parents=True)
        (new_target / "crawled" / "stale.md").write_text("will-be-replaced")

        relocate_documents_dir(new_target)

        # "crawled" dir from source replaced the pre-existing one.
        assert (new_target / "crawled" / "a.md").read_text() == "a\n"
        assert not (new_target / "crawled" / "stale.md").exists()

    def test_same_path_is_noop(self, relocate_env: Path) -> None:
        same = cfg.documents_dir
        result = relocate_documents_dir(same)
        assert result == same
        assert (same / "notes.md").exists()

    def test_rejects_relocate_into_non_lilbee_dir(self, relocate_env: Path) -> None:
        bad_target = relocate_env / "not_lilbee"
        bad_target.mkdir()
        (bad_target / "important.txt").write_text("don't blast me")
        with pytest.raises(RelocationError, match="unmanaged entries"):
            relocate_documents_dir(bad_target)
        # cfg untouched
        assert cfg.documents_dir == relocate_env / "docs_old"
        assert (bad_target / "important.txt").exists()

    def test_move_failure_leaves_cfg_unchanged(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        original = cfg.documents_dir
        with (
            mock.patch("shutil.move", side_effect=OSError("disk full")),
            pytest.raises(OSError, match="disk full"),
        ):
            relocate_documents_dir(new_target)
        assert cfg.documents_dir == original

    def test_rewrites_crawl_meta_absolute_paths(self, relocate_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        old = cfg.documents_dir
        abs_file = str(old / "_web" / "example.com" / "page.md")
        meta_path.write_text(
            json.dumps(
                {
                    "https://example.com/page": {
                        "file": abs_file,
                        "content_hash": "abc",
                        "crawled_at": "2026-01-01",
                    },
                    "https://example.com/other": {
                        "file": "_web/example.com/other.md",
                        "content_hash": "def",
                        "crawled_at": "2026-01-01",
                    },
                }
            )
        )

        new_target = relocate_env / "docs_new"
        relocate_documents_dir(new_target)

        data = json.loads(meta_path.read_text())
        expected = str(new_target / "_web" / "example.com" / "page.md")
        assert data["https://example.com/page"]["file"] == expected
        # Already-relative entries are left alone.
        assert data["https://example.com/other"]["file"] == "_web/example.com/other.md"

    def test_missing_source_dir_still_updates_cfg(self, relocate_env: Path) -> None:
        # If the old dir vanished outside our control, relocation should still
        # leave cfg pointing at the (empty) new dir rather than crashing.
        import shutil as _shutil

        _shutil.rmtree(cfg.documents_dir)
        new_target = relocate_env / "docs_new"
        result = relocate_documents_dir(new_target)
        assert result == new_target
        assert cfg.documents_dir == new_target

    def test_crawl_meta_unreadable_skipped(self, relocate_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        meta_path.write_text("{not json")
        new_target = relocate_env / "docs_new"
        # Should not raise despite corrupt sidecar.
        relocate_documents_dir(new_target)
        assert cfg.documents_dir == new_target

    def test_crawl_meta_non_dict_top_skipped(self, relocate_env: Path) -> None:
        meta_path = cfg.data_dir / "crawl_meta.json"
        meta_path.write_text(json.dumps(["list", "top"]))
        new_target = relocate_env / "docs_new"
        relocate_documents_dir(new_target)
        assert cfg.documents_dir == new_target


class TestUpdateConfigRelocation:
    async def test_patch_documents_dir_moves_files(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        result = await handlers.update_config({"documents_dir": str(new_target)})

        assert "documents_dir" in result.updated
        assert cfg.documents_dir == new_target
        assert (new_target / "notes.md").read_text() == "hello\n"

    async def test_patch_combined_docs_dir_and_other_fields(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        result = await handlers.update_config(
            {"documents_dir": str(new_target), "temperature": 0.7}
        )
        assert set(result.updated) == {"documents_dir", "temperature"}
        assert cfg.documents_dir == new_target
        assert cfg.temperature == 0.7

    async def test_relocation_failure_keeps_other_fields_unchanged(
        self, relocate_env: Path
    ) -> None:
        bad_target = relocate_env / "unsafe"
        bad_target.mkdir()
        (bad_target / "keepme.txt").write_text("x")
        original_temp = cfg.temperature

        with pytest.raises(RelocationError):
            await handlers.update_config({"documents_dir": str(bad_target), "temperature": 0.99})

        # Since docs_dir update runs first, the other field should NOT be
        # applied when relocation fails.
        assert cfg.temperature == original_temp
        assert cfg.documents_dir == relocate_env / "docs_old"

    async def test_patch_documents_dir_rejects_null(self, relocate_env: Path) -> None:
        with pytest.raises(ValueError, match="does not accept null"):
            await handlers.update_config({"documents_dir": None})

    async def test_patch_documents_dir_same_value_noop(self, relocate_env: Path) -> None:
        current = str(cfg.documents_dir)
        result = await handlers.update_config({"documents_dir": current})
        assert "documents_dir" in result.updated
        assert (cfg.documents_dir / "notes.md").exists()

    async def test_patch_persisted_to_settings(self, relocate_env: Path) -> None:
        new_target = relocate_env / "docs_new"
        await handlers.update_config({"documents_dir": str(new_target)})
        from lilbee import settings as s

        stored = s.load(cfg.data_root)
        assert stored.get("documents_dir") == str(new_target)

    async def test_patch_documents_dir_relative_rejected(self, relocate_env: Path) -> None:
        with pytest.raises(RelocationError, match="absolute"):
            await handlers.update_config({"documents_dir": "relative/x"})


class TestLegacyPrefixSeparator:
    def test_os_sep_in_crawl_meta_rewrite(self, relocate_env: Path) -> None:
        # Guard against OS-sep divergence: the relocation builds the legacy
        # prefix with os.sep, so pre-existing absolute paths formatted with
        # the native separator get rewritten, but paths with the other
        # separator are left alone (correct — they don't refer to the old
        # documents_dir).
        from lilbee.server.relocate import _rewrite_crawl_meta_for_relocation

        meta_path = cfg.data_dir / "crawl_meta.json"
        old = relocate_env / "docs_old"
        new = relocate_env / "docs_new"
        os_abs = str(old / "file.md")
        meta_path.write_text(
            json.dumps({"key": {"file": os_abs}, "other": {"file": "unrelated.md"}})
        )

        _rewrite_crawl_meta_for_relocation(old, new)
        data = json.loads(meta_path.read_text())
        assert data["key"]["file"] == str(new / "file.md")
        assert data["other"]["file"] == "unrelated.md"

    def test_no_meta_file_is_noop(self, relocate_env: Path) -> None:
        from lilbee.server.relocate import _rewrite_crawl_meta_for_relocation

        # Ensure file absent
        (cfg.data_dir / "crawl_meta.json").unlink(missing_ok=True)
        _rewrite_crawl_meta_for_relocation(
            cfg.documents_dir, cfg.documents_dir.parent / "new"
        )  # no exception


class TestManagedSubfoldersFrozen:
    def test_contains_expected_names(self) -> None:
        # Sanity check that the allow-list matches the documented set.
        assert "documents" in LILBEE_MANAGED_SUBFOLDERS
        assert "crawled" in LILBEE_MANAGED_SUBFOLDERS
        assert "wiki" in LILBEE_MANAGED_SUBFOLDERS
        assert "imported" in LILBEE_MANAGED_SUBFOLDERS
        assert "_web" in LILBEE_MANAGED_SUBFOLDERS
        assert len(LILBEE_MANAGED_SUBFOLDERS) == 5


class TestOsSepEdgeCases:
    def test_relativise_prefix_uses_separator(self) -> None:
        # On unix, os.sep == "/" so _relativise is a simple slice; on win32
        # the join path might embed backslashes. This just pins the public
        # contract on the current platform.
        prefix = str(Path("/tmp/docs")).rstrip(os.sep) + os.sep
        assert prefix.endswith(os.sep)
