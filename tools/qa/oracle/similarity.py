"""Text-similarity helpers for the oracle differential.

The 4.x->5.x render-engine swap (pdfium -> pdf_oxide) changes OCR input pixels,
so OCR'd text is compared by similarity, not equality. Structural facts (page
counts, chunk counts, schema) are compared exactly by the caller.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"\w+")


def normalize(text: str) -> str:
    """Lowercase and collapse whitespace for tolerant comparison."""
    return _WS_RE.sub(" ", text.lower()).strip()


def ratio(a: str, b: str) -> float:
    """difflib similarity ratio over normalized text, in [0, 1]."""
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def token_jaccard(a: str, b: str) -> float:
    """Jaccard overlap of word tokens, in [0, 1]."""
    ta = set(_WORD_RE.findall(normalize(a)))
    tb = set(_WORD_RE.findall(normalize(b)))
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def keyword_recall(text: str, keywords: tuple[str, ...]) -> float:
    """Fraction of expected keywords present in text (case-insensitive), in [0, 1]."""
    if not keywords:
        return 1.0
    hay = normalize(text)
    hits = sum(1 for k in keywords if normalize(k) in hay)
    return hits / len(keywords)
