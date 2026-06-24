# Validating the kreuzberg 4.x → 5.x migration (independent check)

I migrated a project (lilbee) from kreuzberg `4.9.x` to `5.0.0-rc.35` and built a
small differential harness to check for behavior changes. Two results worth
sharing, both reproducible. Everything ran on one machine, same tesseract
(`5.5.2`), same input files.

## 1. The JPEG-2000 (`#1158`) render fix — confirmed

This is a pixel-level check, independent of OCR and DPI. Same image, encoded two
ways inside a PDF; render the page and look at it:

| same file | rc.33 (pre-fix) | rc.35 | 4.9.2 |
|---|---|---|---|
| normal raster PDF (control) | has content | has content | has content |
| **JPEG-2000 PDF** (`/JPXDecode`) | **blank (all white)** | **has content** | has content |

"Blank" = the rendered page's luminance extrema are `(255, 255)`, i.e. every pixel
is white — nothing decoded. "Has content" = `(0, 255)`, dark text on white. So
pre-fix 5.x rendered the JPEG-2000 page as blank (and downstream OCR therefore got
nothing); rc.35 renders it correctly.

Note the same JPEG-2000 file decodes fine in **4.9.2** *and* **rc.35** — only the
pre-fix 5.x build (older `pd_oxide`) failed it. So the file is valid; this isolates
the regression to the `pd_oxide` JPEG-2000 decoder and confirms rc.35's fix.

Reproduce against any installed build:
```
python -m tools.qa.oracle.jpx_demo sample_corpus/pdf_scanned_raster.pdf sample_corpus/pdf_scanned_jpx.pdf
```

## 2. OCR accuracy and no regression vs 4.x

I drew known text onto image-only PDFs and a PNG (so the correct answer is known
exactly), and ran `extract_file_sync` with forced tesseract OCR in both 4.9.2 and
rc.35.

| document | CER 4.9.2 → rc.35 | keyword recall 4.9.2 → rc.35 | median time |
|---|---|---|---|
| image_scan.png | 0% → 0% | 100% → 100% | 0.49s → 0.51s |
| pdf_text_layer.pdf (control) | 0% → 0% | 100% → 100% | 0.62s → 0.61s |
| scanned_maintenance.pdf (real) | identical text | identical text | 0.72s → 0.70s |

rc.35 transcribes known-text scans with zero character errors, and on the real
fixture produces byte-identical text to 4.9.2. No regressions; timing is on par.

(CER = character error rate vs the known text, 0 = perfect. Recall = fraction of
the planted keywords found. Median of 3 runs.)

## Method

- `extract_file_sync` with `force_ocr=True`, tesseract, `eng`. Identical call and
  files in two environments (kreuzberg 4.9.2 vs 5.0.0-rc.35); same machine, same
  tesseract 5.5.2.
- Synthetic inputs carry known ground truth, so CER/recall are exact. CER is
  Levenshtein distance over normalized text divided by reference length.
- Both builds use the same OCR engine, so any OCR difference is in kreuzberg's
  render→image step, not the recognizer.

## Dataset

In `sample_corpus/` (regenerable byte-for-byte via `corpus.py`). The synthetic
files all carry this text:

```
LILBEE ORACLE CHECK
INVOICE NUMBER 4471
TOTAL DUE 982 DOLLARS
STATUS APPROVED
```

- `image_scan.png` — text rendered to a 1000×600 image.
- `pdf_scanned_raster.pdf` — that image in a PDF, no text layer (confirmed: 0 chars without OCR).
- `pdf_scanned_jpx.pdf` — same, page image stored as JPEG-2000 (the `#1158` case).
- `pdf_text_layer.pdf` — control: real selectable text.
- `scanned_maintenance.pdf` — a real scanned fixture (no ground truth on file).

## Limitations (so nobody has to point them out)

- Synthetic inputs are clean rendered text, not noisy real-world scans; they're a
  best case for OCR. The accuracy numbers say "rc.35 is correct here", not "rc.35
  is good on hard scans". The `#1158` result does not depend on this — it's a
  render check on a valid file.
- One real scanned fixture; small sample. Happy to run a larger/real corpus.
- rc.33 stands in for "pre-fix 5.x"; the actual fix is the `pd_oxide` version bump.
- I observed one oddity I am **not** drawing a conclusion from: on my synthetic
  image-only PDFs, 4.9.2 returned only part of the text while rc.35 returned all
  of it — but rc.35 reads the same page correctly even at 72 DPI, the real fixture
  was identical across versions, and I couldn't find a mechanism, so I'm treating
  it as unexplained rather than a "5.x is better" claim.
