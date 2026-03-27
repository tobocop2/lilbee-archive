"""Web crawling — fetch pages as markdown and save to the documents directory.

Requires optional ``crawler`` extra: ``pip install lilbee[crawler]``.
When the dependency is missing, ``crawler_available()`` returns False and
callers should show the install hint before attempting any crawl operations.
"""

from __future__ import annotations


def crawler_available() -> bool:
    """Check if crawl4ai is installed."""
    try:
        import crawl4ai  # noqa: F401

        return True
    except ImportError:
        return False


def is_url(value: str) -> bool:
    """Check if a string is an HTTP/HTTPS URL."""
    return value.startswith(("http://", "https://"))
