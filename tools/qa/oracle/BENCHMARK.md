# kreuzberg OCR benchmark: 4.9.2 vs 5.0.0-rc.35

## Results

| document | what it is | chars read (4.9.2 → rc.35) | words found (4.9.2 → rc.35) | mistakes/CER (4.9.2 → rc.35) | time (4.9.2 → rc.35) |
|---|---|---|---|---|---|
| image_scan.png | picture of text (PNG) | 77 → 77 | all → all | none → none | 0.49s → 0.51s |
| pdf_scanned_raster.pdf | picture of text in a PDF | **35 → 77** | **60% → 100%** | **55% → 0%** | 0.66s → 0.61s |
| pdf_scanned_jpx.pdf | same, JPEG-2000 encoded | **35 → 77** | **60% → 100%** | **55% → 0%** | 0.69s → 0.63s |
| pdf_text_layer.pdf | PDF with real selectable text | 77 → 77 | all → all | none → none | 0.62s → 0.61s |
| scanned_maintenance.pdf | a real scanned PDF | 175 → 175 (identical) | n/a | n/a | 0.72s → 0.70s |

**One-line takeaway:** rc.35 reads scanned documents at least as well as 4.9.2, and noticeably *better* on image-only PDFs — where 4.9.2 recovered only about half the page, rc.35 recovered all of it, error-free. Speed is the same. Nothing got worse.

## What this measures (plain English)

OCR = reading text back out of a picture. We took documents that are just *images* of text (a scan has no real, selectable text in it), handed them to kreuzberg, and asked it to read the words out. Then we compared the **old** kreuzberg (4.9.2) against the **new** one (5.0.0-rc.35) on the exact same files.

Because we *made* the synthetic documents ourselves, we know the exact correct answer, so we can score the readings precisely:

- **chars read** — how many characters of text it managed to read out. Higher = read more of the page.
- **words found ("recall")** — of the handful of distinctive words we printed on the page, the fraction it actually read back. `100%` = found them all, `60%` = missed about four in ten. **Higher is better.**
- **mistakes ("CER", character error rate)** — how garbled the reading was, character by character. `0%` = a perfect transcription; `55%` = roughly half wrong (here, mostly *missing* text rather than misspelled). **Lower is better.**
- **time** — how long the read took (median of 3 runs).

So "recall is better" means: **the new version found more of the words.** On the two image-only PDFs it went from 60% to 100%.

## The dataset

All five files are in `tools/qa/oracle/sample_corpus/` (attach them as-is). Four are synthetic, with this exact text drawn onto them:

```
LILBEE ORACLE CHECK
INVOICE NUMBER 4471
TOTAL DUE 982 DOLLARS
STATUS APPROVED
```

- **image_scan.png** — that text rendered onto a 1000×600 white image. A plain picture of text.
- **pdf_scanned_raster.pdf** — that same image wrapped in a PDF, with no text layer (a stand-in for a normal scan).
- **pdf_scanned_jpx.pdf** — the same, but the page image is stored as **JPEG-2000** (`/JPXDecode`). This is the exact format that early 5.x couldn't decode and rc.35 fixed.
- **pdf_text_layer.pdf** — a control: a normal PDF with real selectable text (no OCR needed). Both versions should ace it.
- **scanned_maintenance.pdf** — a real scanned PDF fixture from the test suite, to sanity-check against something we didn't make. (No "correct answer" on file, so it's only checked for char count / timing / identical output.)

Confirmed the two synthetic scans contain **no** hidden text — reading them genuinely requires OCR.

## The approach

1. Call kreuzberg's `extract_file_sync` on each file with OCR forced on (tesseract, English). Same call, same files, in two environments: one with kreuzberg 4.9.2 installed, one with 5.0.0-rc.35.
2. Run each file 3 times, take the median time.
3. Score the read text against the known correct text (chars / words found / mistakes).
4. Both versions use the *same* OCR engine (tesseract), so any difference comes from how kreuzberg turns the PDF page into an image before reading it — i.e. its rendering, not the text recognizer.

## Honest caveats

- The big 4.9.2→rc.35 jump showed up on **synthetic image-only PDFs**. On the **real** scanned PDF, both versions produced byte-identical text. So treat "rc.35 reads scanned PDFs better" as demonstrated on these synthetic inputs; the real-world gap may be smaller. It points at PDF-page rendering fidelity, worth a closer look if of interest.
- This is kreuzberg's **render → tesseract** pipeline, not tesseract alone.

## Reproduce

```bash
# in each build's environment:
python -m tools.qa.oracle.ocr_bench <corpus_dir> bench.json 3
# then render the comparison:
python -m tools.qa.oracle.bench_report bench_4x.json bench_5x.json report.md
```
