"""Render two ocr_bench.py outputs (e.g. kreuzberg 4.x vs 5.x) into a shareable
markdown comparison: a metrics table plus the actual extracted text per document.

Usage:
    python -m tools.qa.oracle.bench_report <oracle.json> <candidate.json> [out.md]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _cell(value: Any) -> str:
    return "-" if value is None else str(value)


def _table(oracle: dict[str, Any], cand: dict[str, Any]) -> list[str]:
    ov, cv = oracle["kreuzberg_version"], cand["kreuzberg_version"]
    header = (
        f"| document | CER {ov} | CER {cv} | recall {ov} | recall {cv} "
        f"| chars {ov} | chars {cv} | median s {ov} | median s {cv} |"
    )
    rows = [header, "|---|---|---|---|---|---|---|---|---|"]
    for name in sorted(set(oracle["docs"]) | set(cand["docs"])):
        o, c = oracle["docs"].get(name, {}), cand["docs"].get(name, {})
        rows.append(
            f"| {name} | {_cell(o.get('cer'))} | {_cell(c.get('cer'))} "
            f"| {_cell(o.get('keyword_recall'))} | {_cell(c.get('keyword_recall'))} "
            f"| {_cell(o.get('text_chars'))} | {_cell(c.get('text_chars'))} "
            f"| {_cell(o.get('wall_s_median'))} | {_cell(c.get('wall_s_median'))} |"
        )
    return rows


def render(oracle: dict[str, Any], cand: dict[str, Any]) -> str:
    ov, cv = oracle["kreuzberg_version"], cand["kreuzberg_version"]
    lines = [
        f"# kreuzberg OCR benchmark: {ov} vs {cv}",
        "",
        "Direct `extract_file_sync` calls with forced tesseract OCR (`eng`) on scanned",
        "inputs. CER = character error rate vs known ground truth (0 = perfect); recall =",
        "fraction of ground-truth keywords; median over "
        f"{cand.get('runs', '?')} runs. Synthetic inputs are image-only PDFs / PNGs with",
        "drawn text; `scanned_maintenance.pdf` is a real fixture (no ground truth).",
        "",
        *_table(oracle, cand),
        "",
        "## Extracted text",
        "",
    ]
    for name in sorted(set(oracle["docs"]) | set(cand["docs"])):
        o, c = oracle["docs"].get(name, {}), cand["docs"].get(name, {})
        lines += [
            f"### {name}",
            f"- **{ov}**: `{o.get('text_preview', '')!r}`",
            f"- **{cv}**: `{c.get('text_preview', '')!r}`",
            "",
        ]
    return "\n".join(lines)


def main() -> None:
    oracle = json.loads(Path(sys.argv[1]).read_text())
    cand = json.loads(Path(sys.argv[2]).read_text())
    out = render(oracle, cand)
    if len(sys.argv) > 3:
        Path(sys.argv[3]).write_text(out, encoding="utf-8")
        print(f"wrote {sys.argv[3]}")
    else:
        print(out)


if __name__ == "__main__":
    main()
