"""Compare two capture files (oracle vs candidate) against the QA-matrix invariants.

Structural facts (mode, page count, error parity) are compared exactly; OCR'd text
is compared by ground-truth keyword recall and similarity, because the 4.x->5.x
render-engine swap changes pixels. Exits non-zero if any regression is found
(candidate strictly worse than the oracle).

Usage:
    python -m tools.qa.oracle.compare <oracle.json> <candidate.json>
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from tools.qa.oracle.similarity import keyword_recall, ratio

# Tolerances. Native extraction must be near-identical; OCR is compared by recall
# of known ground-truth keywords (text won't be byte-identical across engines).
_NATIVE_RATIO_MIN = 0.95
_OCR_RECALL_MIN = 0.80
_RECALL_REGRESSION_MARGIN = 0.15
_CHUNK_COUNT_TOL = 0.25

_OCR_CONTENT_TYPES = ("pdf", "image")


class Verdict(StrEnum):
    PASS = "PASS"
    REGRESSION = "REGRESSION"
    IMPROVEMENT = "IMPROVEMENT"
    DIVERGENCE = "DIVERGENCE"


@dataclass(frozen=True)
class Finding:
    item: str
    check: str
    verdict: Verdict
    detail: str


def _err(side: dict[str, Any]) -> str | None:
    return side.get("extract", {}).get("error")


def _content(side: dict[str, Any]) -> str:
    return side.get("extract", {}).get("content_text", "") or ""


def _pages(side: dict[str, Any]) -> int | None:
    return side.get("extract", {}).get("page_count")


def _chunks(side: dict[str, Any]) -> int:
    return side.get("chunks", {}).get("count", 0)


def _error_parity(name: str, o_err: str | None, c_err: str | None) -> Finding | None:
    """A terminal extract-level verdict when either side errored, else None."""
    if o_err and c_err:
        return Finding(name, "extract", Verdict.DIVERGENCE, f"both errored ({c_err[:50]})")
    if c_err:
        return Finding(name, "extract", Verdict.REGRESSION, f"candidate errored: {c_err[:80]}")
    if o_err:
        return Finding(
            name, "extract", Verdict.IMPROVEMENT, "candidate extracts where oracle errored"
        )
    return None


def _text_finding(name: str, ct: str, oracle: dict[str, Any], cand: dict[str, Any]) -> Finding:
    """Recall of known keywords for OCR'd content; similarity ratio for native text."""
    gt = cand.get("ground_truth") or oracle.get("ground_truth")
    keywords = tuple(cand.get("ocr_keywords") or oracle.get("ocr_keywords") or ())
    if not (ct in _OCR_CONTENT_TYPES and gt and keywords):
        r = ratio(_content(oracle), _content(cand))
        verdict = Verdict.PASS if r >= _NATIVE_RATIO_MIN else Verdict.DIVERGENCE
        return Finding(name, "text_similarity", verdict, f"ratio {r:.3f}")
    o_recall = keyword_recall(_content(oracle), keywords)
    c_recall = keyword_recall(_content(cand), keywords)
    if c_recall < o_recall - _RECALL_REGRESSION_MARGIN:
        return Finding(
            name, "ocr_recall", Verdict.REGRESSION, f"recall {o_recall:.2f} -> {c_recall:.2f}"
        )
    if c_recall < _OCR_RECALL_MIN:
        return Finding(
            name,
            "ocr_recall",
            Verdict.DIVERGENCE,
            f"recall {c_recall:.2f} < {_OCR_RECALL_MIN} (oracle {o_recall:.2f})",
        )
    return Finding(
        name, "ocr_recall", Verdict.PASS, f"recall {c_recall:.2f} (oracle {o_recall:.2f})"
    )


def _chunk_finding(name: str, oracle: dict[str, Any], cand: dict[str, Any]) -> Finding:
    oc, cc = _chunks(oracle), _chunks(cand)
    tol = max(1, int(oc * _CHUNK_COUNT_TOL))
    if abs(oc - cc) > tol:
        return Finding(
            name, "chunk_count", Verdict.DIVERGENCE, f"chunks {oc} -> {cc} (tol +/-{tol})"
        )
    return Finding(name, "chunk_count", Verdict.PASS, f"chunks={cc} (oracle {oc})")


def _compare_item(name: str, oracle: dict[str, Any], cand: dict[str, Any]) -> list[Finding]:
    terminal = _error_parity(name, _err(oracle), _err(cand))
    if terminal is not None:
        return [terminal]

    ct = cand.get("content_type", oracle.get("content_type", "?"))
    out: list[Finding] = []

    o_mode = oracle.get("extract", {}).get("mode")
    c_mode = cand.get("extract", {}).get("mode")
    if o_mode != c_mode:
        out.append(Finding(name, "mode", Verdict.REGRESSION, f"mode {o_mode!r} -> {c_mode!r}"))

    op, cp = _pages(oracle), _pages(cand)
    page_verdict = Verdict.PASS if op == cp else Verdict.REGRESSION
    out.append(Finding(name, "page_count", page_verdict, f"pages {op} -> {cp}"))

    out.append(_text_finding(name, ct, oracle, cand))
    out.append(_chunk_finding(name, oracle, cand))
    return out


def compare(oracle_path: Path, cand_path: Path) -> list[Finding]:
    oracle = json.loads(oracle_path.read_text())
    cand = json.loads(cand_path.read_text())
    o_items, c_items = oracle["items"], cand["items"]
    findings: list[Finding] = []
    for name in sorted(set(o_items) | set(c_items)):
        if name not in o_items:
            findings.append(Finding(name, "presence", Verdict.IMPROVEMENT, "only in candidate"))
        elif name not in c_items:
            findings.append(Finding(name, "presence", Verdict.REGRESSION, "missing in candidate"))
        else:
            findings.extend(_compare_item(name, o_items[name], c_items[name]))
    return findings


def main() -> int:
    oracle_path, cand_path = Path(sys.argv[1]), Path(sys.argv[2])
    findings = compare(oracle_path, cand_path)
    icon = {
        Verdict.PASS: "✓",
        Verdict.IMPROVEMENT: "▲",
        Verdict.DIVERGENCE: "~",
        Verdict.REGRESSION: "✗",
    }
    for f in findings:
        print(f"{icon[f.verdict]} {f.verdict:11} {f.item:22} {f.check:16} {f.detail}")
    regressions = [f for f in findings if f.verdict is Verdict.REGRESSION]
    counts = {v: sum(1 for f in findings if f.verdict is v) for v in Verdict}
    print(
        f"\nsummary: {counts[Verdict.PASS]} pass, {counts[Verdict.IMPROVEMENT]} improvement, "
        f"{counts[Verdict.DIVERGENCE]} divergence, {counts[Verdict.REGRESSION]} regression"
    )
    return 1 if regressions else 0


if __name__ == "__main__":
    raise SystemExit(main())
