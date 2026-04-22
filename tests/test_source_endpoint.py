"""Tests for GET /api/source handler + route."""

from __future__ import annotations

from pathlib import Path

import pytest

from lilbee.config import cfg
from lilbee.crawler import _managed_frontmatter
from lilbee.server import handlers
from lilbee.server.handlers import (
    SourceNotFoundError,
    get_source_bytes,
    get_source_text,
    raw_content_type,
)


@pytest.fixture()
def source_env(tmp_path: Path):
    cfg.documents_dir = tmp_path / "documents"
    cfg.data_dir = tmp_path / "data"
    cfg.documents_dir.mkdir(parents=True, exist_ok=True)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    yield tmp_path


class TestGetSourceText:
    async def test_returns_plain_markdown(self, source_env: Path) -> None:
        path = cfg.documents_dir / "notes" / "doc.md"
        path.parent.mkdir(parents=True)
        path.write_text("# Title\n\nhello", encoding="utf-8")

        result = await get_source_text("notes/doc.md")
        assert result.markdown == "# Title\n\nhello"
        assert result.content_type == "markdown"
        assert result.source == "notes/doc.md"
        assert result.title == "Title"
        assert result.crawled_at is None
        assert result.source_url is None

    async def test_strips_managed_frontmatter(self, source_env: Path) -> None:
        path = cfg.documents_dir / "crawled.md"
        body = _managed_frontmatter(
            "https://example.com/a", "2026-04-21T10:00:00+00:00"
        ) + "# Crawled Page\n\nbody\n"
        path.write_text(body, encoding="utf-8")

        result = await get_source_text("crawled.md")
        assert result.markdown.startswith("# Crawled Page")
        assert result.source_url == "https://example.com/a"
        assert result.crawled_at == "2026-04-21T10:00:00+00:00"
        assert result.title == "Crawled Page"

    async def test_returns_plain_text_for_non_markdown(self, source_env: Path) -> None:
        path = cfg.documents_dir / "notes.txt"
        path.write_text("just a text file", encoding="utf-8")
        result = await get_source_text("notes.txt")
        assert result.content_type == "text"
        assert result.markdown == "just a text file"
        assert result.title is None

    async def test_pdf_rejected_in_text_mode(self, source_env: Path) -> None:
        path = cfg.documents_dir / "doc.pdf"
        path.write_bytes(b"%PDF-fake\n")
        with pytest.raises(SourceNotFoundError, match="raw=1"):
            await get_source_text("doc.pdf")

    async def test_404_when_missing(self, source_env: Path) -> None:
        with pytest.raises(SourceNotFoundError, match="not found"):
            await get_source_text("no-such-file.md")

    async def test_rejects_path_escape(self, source_env: Path) -> None:
        with pytest.raises(SourceNotFoundError, match="not under documents_dir"):
            await get_source_text("../etc/passwd")

    async def test_rejects_absolute_path_outside_docs(self, source_env: Path) -> None:
        with pytest.raises(SourceNotFoundError):
            await get_source_text("/etc/passwd")

    async def test_title_none_when_no_heading(self, source_env: Path) -> None:
        path = cfg.documents_dir / "nh.md"
        path.write_text("body without heading\n", encoding="utf-8")
        result = await get_source_text("nh.md")
        assert result.title is None

    async def test_title_none_for_empty_markdown(self, source_env: Path) -> None:
        path = cfg.documents_dir / "empty.md"
        path.write_text("", encoding="utf-8")
        result = await get_source_text("empty.md")
        assert result.title is None


class TestGetSourceBytes:
    async def test_returns_pdf_bytes(self, source_env: Path) -> None:
        path = cfg.documents_dir / "doc.pdf"
        payload = b"%PDF-1.4 fake"
        path.write_bytes(payload)
        data, ct = await get_source_bytes("doc.pdf")
        assert data == payload
        assert ct == "application/pdf"

    async def test_returns_markdown_bytes(self, source_env: Path) -> None:
        path = cfg.documents_dir / "a.md"
        path.write_text("# x", encoding="utf-8")
        data, ct = await get_source_bytes("a.md")
        assert data == b"# x"
        assert "text/markdown" in ct

    async def test_missing_raises(self, source_env: Path) -> None:
        with pytest.raises(SourceNotFoundError):
            await get_source_bytes("no.md")

    async def test_unknown_extension_defaults_to_octet_stream(
        self, source_env: Path
    ) -> None:
        path = cfg.documents_dir / "weird.xyz"
        path.write_bytes(b"stuff")
        _, ct = await get_source_bytes("weird.xyz")
        assert ct == "application/octet-stream"


class TestRawContentType:
    @pytest.mark.parametrize(
        "suffix, expected",
        [
            (".pdf", "application/pdf"),
            (".md", "text/markdown; charset=utf-8"),
            (".txt", "text/plain; charset=utf-8"),
            (".html", "text/html; charset=utf-8"),
            (".png", "image/png"),
            (".jpg", "image/jpeg"),
            (".unknown", "application/octet-stream"),
        ],
    )
    def test_content_type_mapping(self, suffix: str, expected: str) -> None:
        assert raw_content_type(Path(f"file{suffix}")) == expected


class TestIsDirectoryGuard:
    async def test_directory_not_treated_as_source(self, source_env: Path) -> None:
        d = cfg.documents_dir / "adir"
        d.mkdir()
        with pytest.raises(SourceNotFoundError):
            await get_source_text("adir")


class TestUnreadableFile:
    async def test_os_error_on_read_becomes_404(self, source_env: Path, monkeypatch) -> None:
        path = cfg.documents_dir / "locked.md"
        path.write_text("# title\n", encoding="utf-8")
        original = Path.read_text

        def _raise(self, *a, **kw):
            if self == path:
                raise OSError("ebusy")
            return original(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", _raise)
        with pytest.raises(SourceNotFoundError, match="unreadable"):
            await get_source_text("locked.md")

    async def test_os_error_on_read_bytes_becomes_404(
        self, source_env: Path, monkeypatch
    ) -> None:
        path = cfg.documents_dir / "locked.pdf"
        path.write_bytes(b"x")
        original = Path.read_bytes

        def _raise(self):
            if self == path:
                raise OSError("ebusy")
            return original(self)

        monkeypatch.setattr(Path, "read_bytes", _raise)
        with pytest.raises(SourceNotFoundError, match="unreadable"):
            await get_source_bytes("locked.pdf")


class TestHandlersReExport:
    """get_source_text/get_source_bytes must be reachable via handlers module."""

    def test_reexports(self) -> None:
        assert hasattr(handlers, "get_source_text")
        assert hasattr(handlers, "get_source_bytes")
        assert hasattr(handlers, "SourceNotFoundError")


class TestCleanedChunkVaultPath:
    def test_default_is_none(self) -> None:
        from lilbee.server.models import CleanedChunk

        chunk = CleanedChunk(source="a.md", content_type="text", chunk="x")
        assert chunk.vault_path is None

    def test_stamp_value(self) -> None:
        from lilbee.server.models import CleanedChunk

        chunk = CleanedChunk(
            source="a.md",
            content_type="text",
            chunk="x",
            vault_path="lilbee/a.md",
        )
        assert chunk.vault_path == "lilbee/a.md"
