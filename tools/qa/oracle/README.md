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

- **Tier 0-1 — `capture.py` + `compare.py`:** content-type routing, native
  extraction, image OCR, JPEG-2000 render, page counts, deterministic chunking,
  compared at kreuzberg's `extract_file` level.
- **Pipeline OCR — `pipeline_ocr.py`:** captures `ingest_document`'s `page_texts`
  (OCR text) without the embedder, so it compares OCR *where each build performs
  it* -- the oracle's own pipeline (rasterize+tesseract) vs the candidate's
  kreuzberg backend. This is the apples-to-apples scanned-PDF comparison.
- **Tier 2-3 — `e2e_diff.py`:** runs the full stack via `lilbee add` + `lilbee
  search` and measures ground-truth recall. With `LILBEE_VISION_MODEL` set, the
  scanned inputs exercise the vision-OCR path.

### Engine-migration caveat

The merge-base oracle (`bb037407`) predates lilbee's in-process -> llama-server
engine migration: its embedding and vision OCR run through the in-process
`llama_cpp` module, which the current build removed. So the oracle's **search**
and **vision** paths can't run without compiling `llama-cpp-python` into the
oracle venv -- and doing so would test the *engine* migration, not kreuzberg.
Those tiers are therefore validated end-to-end on the candidate against ground
truth (the oracle's contract was to recover the same text); `pipeline_ocr.py`
still captures the oracle's tesseract OCR for a direct scanned-PDF comparison.

## Findings

- **Fixed regression:** image + tesseract OCR failed under kreuzberg 5.x because
  lilbee left the OCR language empty (`language=[]`); 4.x's `OcrConfig.language`
  was a `str` that defaulted to English, 5.x is a `list` that errors when empty.
  Fixed by setting `language=["eng"]` in `data/ingest/extract.py::_ocr_config`
  (bb-jhq), with a regression test.
- **Improvement, not regression:** scanned-PDF OCR recall went from 0.6 (oracle,
  150-DPI rasterize+tesseract) to 1.0 (candidate, kreuzberg backend). JPEG-2000
  scans (`#1158`) extract correctly. Vision OCR (LightOnOCR) recovers 1.0 recall
  on all scanned inputs; end-to-end search retrieves 7/7 corpus items.
- **Benign divergences:** CSV-to-markdown formatting changed across versions
  (data preserved); single images now route to `PAGINATED` (one page) instead of
  `MARKDOWN` (intentional).
