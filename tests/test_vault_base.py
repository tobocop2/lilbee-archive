"""Tests for cfg.vault_base + vault_path stamping on Source responses."""

from __future__ import annotations

from pathlib import Path

import pytest

from lilbee.cli.helpers import clean_result
from lilbee.config import cfg
from lilbee.server.handlers import _validate_vault_base, update_config


@pytest.fixture()
def vault_env(tmp_path: Path):
    """Point cfg at a vault-style layout under tmp_path."""
    vault = tmp_path / "vault"
    docs = vault / "lilbee"
    docs.mkdir(parents=True)
    prev_vault = cfg.vault_base
    prev_docs = cfg.documents_dir
    cfg.documents_dir = docs
    cfg.vault_base = None
    yield vault, docs
    cfg.vault_base = prev_vault
    cfg.documents_dir = prev_docs


class _FakeSearchChunk:
    """Minimal SearchChunk stand-in for clean_result's model_dump path."""

    def __init__(self, source: str) -> None:
        self._source = source

    def model_dump(self, *, exclude, exclude_none):
        return {"source": self._source, "chunk": "body", "distance": 0.1}


class TestVaultBaseValidation:
    def test_accepts_null(self) -> None:
        # Null explicitly allowed — used to unset on switch to external mode.
        _validate_vault_base({"vault_base": None})

    def test_absent_key_is_noop(self) -> None:
        _validate_vault_base({})

    def test_rejects_relative_path(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="absolute"):
            _validate_vault_base({"vault_base": "relative/path"})

    def test_rejects_non_existent(self, tmp_path: Path) -> None:
        missing = tmp_path / "nope"
        with pytest.raises(ValueError, match="not an existing directory"):
            _validate_vault_base({"vault_base": str(missing)})

    def test_rejects_file(self, tmp_path: Path) -> None:
        f = tmp_path / "afile"
        f.write_text("x")
        with pytest.raises(ValueError, match="not an existing directory"):
            _validate_vault_base({"vault_base": str(f)})

    def test_rejects_when_documents_dir_outside(
        self, vault_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        cfg.documents_dir = outside
        with pytest.raises(ValueError, match="must live inside vault_base"):
            _validate_vault_base({"vault_base": str(vault_env[0])})

    def test_accepts_when_updated_documents_dir_inside(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        new_docs = vault / "otherdir"
        new_docs.mkdir()
        # Validated together: new docs is under the vault being set.
        _validate_vault_base(
            {"vault_base": str(vault), "documents_dir": str(new_docs)}
        )


class TestCleanResultStamping:
    def test_no_stamp_when_vault_base_none(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        cfg.vault_base = None
        data = clean_result(_FakeSearchChunk("crawled/example.com/page.md"))
        assert "vault_path" not in data

    def test_stamps_when_vault_base_set(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        cfg.vault_base = vault
        data = clean_result(_FakeSearchChunk("crawled/example.com/page.md"))
        assert data["vault_path"] == "lilbee/crawled/example.com/page.md"

    def test_stamp_forward_slash_on_windows_style_source(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        cfg.vault_base = vault
        # Relative sources are already forward-slash normalized upstream.
        data = clean_result(_FakeSearchChunk("notes/doc.md"))
        assert data["vault_path"] == "lilbee/notes/doc.md"

    def test_no_stamp_when_documents_dir_outside_vault(
        self, vault_env: tuple[Path, Path], tmp_path: Path
    ) -> None:
        # Inconsistent state post-PATCH (shouldn't happen after validation,
        # but clean_result degrades gracefully rather than crashing chat).
        outside = tmp_path / "outside"
        outside.mkdir()
        cfg.documents_dir = outside
        cfg.vault_base = vault_env[0]
        data = clean_result(_FakeSearchChunk("notes/doc.md"))
        assert "vault_path" not in data

    def test_no_stamp_when_source_missing(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        cfg.vault_base = vault

        class _Empty:
            def model_dump(self, *, exclude, exclude_none):
                return {"chunk": "body", "distance": 0.1}

        data = clean_result(_Empty())
        assert "vault_path" not in data


class TestVaultBaseThroughUpdateConfig:
    async def test_round_trip_via_update_config(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        response = await update_config({"vault_base": str(vault)})
        assert "vault_base" in response.updated
        assert cfg.vault_base == vault

    async def test_null_resets_vault_base(
        self, vault_env: tuple[Path, Path]
    ) -> None:
        vault, _ = vault_env
        cfg.vault_base = vault
        response = await update_config({"vault_base": None})
        assert "vault_base" in response.updated
        assert cfg.vault_base is None
