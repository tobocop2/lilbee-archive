# kreuzberg 4.x -> 5.x oracle differential

Validates the kreuzberg 4.x -> 5.x migration by treating the **pre-migration
build as the oracle**: the same deterministic corpus is run through the old build
(kreuzberg 4.x) and the current build (kreuzberg 5.x), and the two are compared
against a fixed set of behavioral invariants.

The migration moved lilbee's whole PDF/OCR pipeline (rasterization, OCR
orchestration, the per-page OCR cache) out of lilbee and into kreuzberg 5.x via a
custom OCR backend. The render engine also changed (pdfium -> pd_oxide), so OCR'd
text is not byte-identical across versions. The differential therefore compares
*structural* facts exactly and *OCR'd text* by ground-truth keyword recall.

## Run it

```bash
tools/qa/oracle/run.sh            # oracle = merge-base(HEAD, main)
tools/qa/oracle/run.sh <git_ref>  # pin a specific pre-migration ref
```

The script generates the corpus once, captures the candidate (HEAD), creates a
detached worktree at the oracle ref with its own kreuzberg-4.x venv, captures the
oracle, and prints the differential. It exits non-zero if any **regression**
(candidate strictly worse than the oracle) is found.

## Corpus

`corpus.py` generates deterministic inputs with known ground truth (so OCR
accuracy is directly measurable and the fixtures are reproducible):

| item | content type | exercises |
|------|--------------|-----------|
| `plain_text.txt`, `markdown_doc.md` | text | native text extraction |
| `csv_table.csv` | data | tabular extraction |
| `pdf_text_layer.pdf` | pdf | text-layer PDF (no OCR) |
| `pdf_scanned_raster.pdf` | pdf | image-only PDF -> OCR |
| `pdf_scanned_jpx.pdf` | pdf | JPEG-2000 (`/JPXDecode`) scan -> the kreuzberg-1158 render case |
| `image_scan.png` | image | single-image OCR |

Drop any real file (office docs, real scans) into the corpus dir and it is picked
up automatically (content type inferred from extension, no ground truth).

## Invariants (the QA matrix)

`compare.py` checks, per item: error parity, extraction mode, page count, text
similarity (native) or OCR keyword recall (scanned/image), and chunk count.
Verdicts: `PASS`, `IMPROVEMENT` (candidate better), `DIVERGENCE` (changed but
within tolerance / a routing decision to review), `REGRESSION` (candidate worse;
fails the run).

## Tiers

- **Tier 0-1 (this harness):** content-type routing, native extraction, image
  OCR, JPEG-2000 render, page counts, deterministic (model-free) chunking.
- **Tier 2-3 (end-to-end, separate run):** scanned-**PDF** OCR, vision-model OCR,
  and embedding/search recall must be compared at lilbee's **pipeline/CLI** level,
  not at `extract_file`. The migration moved PDF OCR from lilbee's pipeline (oracle)
  into kreuzberg's `extract_file` (candidate), so the two are only comparable
  through `lilbee add` + `lilbee search` with the fleet running. Capturing those
  needs an embedder (and, for vision, a vision model) on both sides.

## Findings to date

- **Fixed regression:** image + tesseract OCR failed under kreuzberg 5.x because
  lilbee left the OCR language empty (`language=[]`); 5.x errors instead of
  defaulting to English the way 4.x did. Fixed by setting `language=["eng"]` in
  `data/ingest/extract.py::_ocr_config`.
- **Benign divergences:** CSV-to-markdown formatting changed across versions
  (data preserved); single images now route to `PAGINATED` (one page) instead of
  `MARKDOWN` (intentional).
