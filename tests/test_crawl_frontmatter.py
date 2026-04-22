"""Tests for managed-frontmatter writes + orphan pruning in crawler.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from lilbee.config import cfg
from lilbee.crawler import (
    CrawlMeta,
    _managed_frontmatter,
    _prune_host_orphans,
    _save_single_result,
    parse_managed_frontmatter,
)


class _Result:
    """Stand-in for crawl4ai's CrawlResult (only the fields _save_single_result reads)."""

    def __init__(self, url: str, markdown: str, success: bool = True) -> None:
        self.url = url
        self.markdown = markdown
        self.success = success


@pytest.fixture()
def crawl_env(tmp_path: Path):
    """Point cfg at scratch directories for crawl tests."""
    cfg.documents_dir = tmp_path / "documents"
    cfg.data_dir = tmp_path / "data"
    cfg.lancedb_dir = tmp_path / "data" / "lancedb"
    cfg.documents_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path


class TestManagedFrontmatterRender:
    def test_basic_render(self) -> None:
        block = _managed_frontmatter("https://x.com/y", "2026-04-21T10:00:00+00:00")
        assert block.startswith("---\n")
        assert "lilbee_managed: true" in block
        assert 'source_url: "https://x.com/y"' in block
        assert "crawled_at: 2026-04-21T10:00:00+00:00" in block
        assert block.endswith("---\n\n")

    def test_escapes_double_quotes(self) -> None:
        block = _managed_frontmatter('https://x.com/"quoted"', "2026-04-21")
        assert 'source_url: "https://x.com/\\"quoted\\""' in block

    def test_escapes_backslashes(self) -> None:
        block = _managed_frontmatter("https://x.com/a\\b", "2026-04-21")
        assert 'source_url: "https://x.com/a\\\\b"' in block


class TestParseManagedFrontmatter:
    def test_round_trip(self) -> None:
        block = _managed_frontmatter("https://x.com/a", "2026-04-21T10:00:00+00:00")
        parsed = parse_managed_frontmatter(block + "# body\n")
        assert parsed is not None
        assert parsed["lilbee_managed"] == "true"
        assert parsed["source_url"] == "https://x.com/a"
        assert parsed["crawled_at"] == "2026-04-21T10:00:00+00:00"

    def test_returns_none_without_leading_marker(self) -> None:
        assert parse_managed_frontmatter("# plain body") is None

    def test_returns_none_without_closing_marker(self) -> None:
        assert parse_managed_frontmatter("---\nlilbee_managed: true\n") is None

    def test_returns_none_without_managed_flag(self) -> None:
        text = "---\nfoo: bar\n---\n\nbody"
        assert parse_managed_frontmatter(text) is None

    def test_unescapes_quoted_url(self) -> None:
        block = '---\nlilbee_managed: true\nsource_url: "https://x.com/\\"a\\""\n---\n\n'
        parsed = parse_managed_frontmatter(block)
        assert parsed is not None
        assert parsed["source_url"] == 'https://x.com/"a"'

    def test_handles_missing_colon_lines(self) -> None:
        block = "---\nlilbee_managed: true\nbogus line\nsource_url: https://x.com\n---\n\n"
        parsed = parse_managed_frontmatter(block)
        assert parsed is not None
        assert parsed["source_url"] == "https://x.com"


class TestSaveSingleResultWritesFrontmatter:
    def test_writes_frontmatter_block(self, crawl_env: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "lilbee.crawler.url_to_filename",
            lambda url: "example.com/page.md",
        )
        result = _Result("https://example.com/page", "# Body\n\ncontent")
        meta: dict[str, CrawlMeta] = {}
        path = _save_single_result(result, meta)
        assert path is not None
        body = path.read_text(encoding="utf-8")
        parsed = parse_managed_frontmatter(body)
        assert parsed is not None
        assert parsed["source_url"] == "https://example.com/page"
        assert body.endswith("# Body\n\ncontent")

    def test_skips_empty_markdown(self, crawl_env: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "lilbee.crawler.url_to_filename",
            lambda url: "example.com/page.md",
        )
        result = _Result("https://example.com/page", "   ")
        assert _save_single_result(result, {}) is None

    def test_skips_failed_fetch(self, crawl_env: Path, monkeypatch) -> None:
        monkeypatch.setattr(
            "lilbee.crawler.url_to_filename",
            lambda url: "example.com/page.md",
        )
        result = _Result("https://example.com/page", "real body", success=False)
        assert _save_single_result(result, {}) is None


class TestPruneHostOrphans:
    def _write(self, path: Path, url: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        block = _managed_frontmatter(url, "2026-04-21T10:00:00+00:00")
        path.write_text(block + "# body\n", encoding="utf-8")

    def test_removes_file_not_in_fresh_set(self, crawl_env: Path) -> None:
        web_dir = cfg.documents_dir / "_web" / "example.com"
        kept = web_dir / "kept.md"
        gone = web_dir / "gone.md"
        self._write(kept, "https://example.com/kept")
        self._write(gone, "https://example.com/gone")

        removed = _prune_host_orphans("example.com", {"https://example.com/kept"})
        assert kept.exists()
        assert not gone.exists()
        assert gone in removed

    def test_leaves_non_managed_files_alone(self, crawl_env: Path) -> None:
        web_dir = cfg.documents_dir / "_web" / "example.com"
        web_dir.mkdir(parents=True)
        plain = web_dir / "user-owned.md"
        plain.write_text("# notes I wrote manually\n", encoding="utf-8")

        removed = _prune_host_orphans("example.com", set())
        assert plain.exists()
        assert removed == []

    def test_leaves_other_host_files_alone(self, crawl_env: Path) -> None:
        other_dir = cfg.documents_dir / "_web" / "other.com"
        other = other_dir / "p.md"
        self._write(other, "https://other.com/p")

        removed = _prune_host_orphans("example.com", set())
        assert other.exists()
        assert removed == []

    def test_tolerates_unreadable_files(self, crawl_env: Path, monkeypatch) -> None:
        web_dir = cfg.documents_dir / "_web" / "example.com"
        web_dir.mkdir(parents=True)
        locked = web_dir / "locked.md"
        locked.write_text("dummy", encoding="utf-8")

        original_read = Path.read_text

        def _raise(self, *a, **kw):
            if self == locked:
                raise OSError("permission denied")
            return original_read(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", _raise)
        removed = _prune_host_orphans("example.com", set())
        # Unreadable files are skipped, not crashed on.
        assert locked.exists()
        assert removed == []

    def test_tolerates_unlink_failure(self, crawl_env: Path, monkeypatch) -> None:
        web_dir = cfg.documents_dir / "_web" / "example.com"
        orphan = web_dir / "orphan.md"
        self._write(orphan, "https://example.com/orphan")

        monkeypatch.setattr(Path, "unlink", MagicMock(side_effect=OSError("locked")))
        removed = _prune_host_orphans("example.com", set())
        assert removed == []

    def test_missing_host_dir_returns_empty(self, crawl_env: Path) -> None:
        assert _prune_host_orphans("never-crawled.com", set()) == []

    def test_files_without_source_url_are_not_orphaned(self, crawl_env: Path) -> None:
        web_dir = cfg.documents_dir / "_web" / "example.com"
        web_dir.mkdir(parents=True)
        sneaky = web_dir / "sneaky.md"
        # Managed flag present but no source_url — treat as "we don't know
        # what this is" rather than "delete it".
        sneaky.write_text(
            "---\nlilbee_managed: true\n---\n\nbody", encoding="utf-8"
        )
        removed = _prune_host_orphans("example.com", set())
        assert removed == []
        assert sneaky.exists()
