"""Tests for lilbee.crawler module."""

from __future__ import annotations

import sys
from unittest.mock import patch

from lilbee.crawler import crawler_available, is_url


def test_crawler_available_when_installed() -> None:
    """Returns True when crawl4ai can be imported."""
    import types

    fake_module = types.ModuleType("crawl4ai")
    with patch.dict("sys.modules", {"crawl4ai": fake_module}):
        assert crawler_available()


def test_crawler_available_when_missing() -> None:
    """Returns False when crawl4ai is not installed."""
    with patch.dict(sys.modules, {"crawl4ai": None}):
        assert not crawler_available()


def test_is_url_http() -> None:
    assert is_url("http://example.com")


def test_is_url_https() -> None:
    assert is_url("https://example.com/page")


def test_is_url_rejects_file_path() -> None:
    assert not is_url("/tmp/file.txt")


def test_is_url_rejects_relative() -> None:
    assert not is_url("file.txt")


def test_is_url_rejects_ftp() -> None:
    assert not is_url("ftp://example.com")
