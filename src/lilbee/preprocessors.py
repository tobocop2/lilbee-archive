"""Format-specific preprocessors for structured data files.

Convert structured formats (XML, JSON, CSV) into readable prose
that embeds well for vector search. Each preprocessor takes a Path
and returns a string of human-readable text.
"""

import logging
import xml.etree.ElementTree as ET
from pathlib import Path

log = logging.getLogger(__name__)


def preprocess_xml(path: Path) -> str:
    """Convert XML to readable prose using element tags as labels."""
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        log.warning("Malformed XML, falling back to raw text: %s", path)
        return path.read_text(encoding="utf-8", errors="replace")
    return _walk_element(tree.getroot(), depth=0).strip()


def _walk_element(elem: ET.Element, depth: int) -> str:
    """Recursively convert an XML element tree to readable text."""
    parts: list[str] = []
    tag = elem.tag
    attrs = " ".join(f"{k}: {v}" for k, v in elem.attrib.items())
    label = f"{tag} ({attrs})" if attrs else tag

    if depth == 0:
        parts.append(f"{label}\n")
    elif depth == 1:
        parts.append(f"\n{label}\n")
    else:
        indent = "  " * (depth - 1)
        parts.append(f"{indent}{label}\n")

    text = (elem.text or "").strip()
    if text:
        indent = "  " * max(depth, 1)
        parts.append(f"{indent}{text}\n")

    for child in elem:
        parts.append(_walk_element(child, depth + 1))

    tail = (elem.tail or "").strip()
    if tail:
        indent = "  " * max(depth - 1, 0)
        parts.append(f"{indent}{tail}\n")

    return "".join(parts)
