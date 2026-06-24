"""Benchmark kreuzberg's OCR (render + tesseract) directly, isolated from lilbee.

Calls ``kreuzberg.extract_file_sync`` with forced tesseract OCR on scanned inputs
and reports, per document: median wall time over N runs, character error rate and
keyword recall against known ground truth, extracted character count, and the text
itself. Run it in each build's venv (kreuzberg 4.x vs 5.x) and diff the two JSONs
to compare versions head to head.

Usage:
    python -m tools.qa.oracle.ocr_bench <corpus_dir> <out.json> [runs] [extra_scan ...]
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from tools.qa.oracle.corpus import build_corpus
from tools.qa.oracle.similarity import keyword_recall, normalize

_DEFAULT_RUNS = 3
_TEXT_PREVIEW = 600
_SCANNED_TYPES = ("pdf", "image")


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _cer(pred: str, truth: str) -> float:
    """Character error rate over normalized text (0.0 = perfect)."""
    t, p = normalize(truth), normalize(pred)
    return _levenshtein(p, t) / max(1, len(t))


def _forced_ocr_config() -> Any:
    """ExtractionConfig forcing tesseract OCR. 4.x needs an object (no dict coercion);
    4.x OcrConfig.language is a str, 5.x is a list."""
    from kreuzberg import ExtractionConfig, OcrConfig

    try:  # 5.x: language is a list
        ocr = OcrConfig(backend="tesseract", language=["eng"])
    except TypeError:  # 4.x: language is a str
        ocr = OcrConfig(backend="tesseract", language="eng")
    return ExtractionConfig(force_ocr=True, ocr=ocr)


def _bench_one(
    path: Path, truth: str | None, keywords: tuple[str, ...], runs: int
) -> dict[str, Any]:
    from kreuzberg import extract_file_sync

    config = _forced_ocr_config()
    times: list[float] = []
    text = ""
    error: str | None = None
    for _ in range(runs):
        start = time.perf_counter()
        try:
            result = extract_file_sync(str(path), config=config)
            text = str(getattr(result, "content", "") or "")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            break
        times.append(time.perf_counter() - start)
    times.sort()
    return {
        "wall_s_median": round(times[len(times) // 2], 3) if times else None,
        "wall_s_min": round(times[0], 3) if times else None,
        "text_chars": len(text),
        "cer": round(_cer(text, truth), 4) if (truth and not error) else None,
        "keyword_recall": round(keyword_recall(text, keywords), 3)
        if (keywords and not error)
        else None,
        "text_preview": text[:_TEXT_PREVIEW],
        "error": error,
    }


def benchmark(corpus_dir: Path, runs: int, extra: list[Path]) -> dict[str, Any]:
    import kreuzberg

    items = [
        it for it in build_corpus(corpus_dir, regenerate=False) if it.content_type in _SCANNED_TYPES
    ]
    docs: dict[str, Any] = {}
    for it in items:
        docs[it.name] = {
            "ground_truth": it.ground_truth,
            **_bench_one(it.path, it.ground_truth, it.ocr_keywords, runs),
        }
    for path in extra:
        docs[path.name] = {"ground_truth": None, **_bench_one(path, None, (), runs)}
    return {
        "kreuzberg_version": getattr(kreuzberg, "__version__", "unknown"),
        "runs": runs,
        "docs": docs,
    }


def main() -> None:
    corpus_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2])
    runs = int(sys.argv[3]) if len(sys.argv) > 3 else _DEFAULT_RUNS
    extra = [Path(p) for p in sys.argv[4:]]
    payload = benchmark(corpus_dir, runs, extra)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"kreuzberg {payload['kreuzberg_version']} ({runs} runs/doc) -> {out_path}")
    for name, d in sorted(payload["docs"].items()):
        print(
            f"  {name:22} cer={d['cer']!s:7} recall={d['keyword_recall']!s:6} "
            f"chars={d['text_chars']:5} median={d['wall_s_median']}s err={(d['error'] or '')[:30]}"
        )


if __name__ == "__main__":
    main()
