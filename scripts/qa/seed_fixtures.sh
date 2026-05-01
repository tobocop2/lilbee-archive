#!/usr/bin/env bash
# Seed minimal QA fixtures under <documents_dir>. Idempotent: rerun is
# safe. Builds:
#   - notes/ev-notes.md         scripted EV battery paragraph
#   - notes/coffee-notes.md     scripted cross-doc reranker target
#   - notes/large.md            ~200 KB lorem with embedded fact
#   - code/searcher.py          cp from src for code-chunker cell
#   - pdf/star-wars-5p.pdf      5-page slice of the X-Wing guide
#
# Usage:
#   scripts/qa/seed_fixtures.sh <documents_dir>

set -euo pipefail

DOCS="${1:-/tmp/lilbee-qa-pizza/documents}"
SRC_PDF="/Users/tobias/Downloads/Star Wars X-Wing Collector's Edition - Guide.pdf"
SRC_CODE="src/lilbee/retrieval/query/searcher.py"

mkdir -p "$DOCS/notes" "$DOCS/code" "$DOCS/pdf"

# Notes: EV ground truth + coffee cross-doc target.
cat > "$DOCS/notes/ev-notes.md" <<'EOF'
# EV battery technology

Lithium-ion batteries dominate electric vehicles in 2025. The chemistry
balances energy density, cost, and cycle life. NMC (nickel manganese
cobalt) cells favour energy density. LFP (lithium iron phosphate) cells
favour cycle life and thermal stability and have become the default for
mass-market EVs.

Solid-state batteries replace the liquid electrolyte with a solid one,
promising higher energy density and reduced fire risk. Toyota and QuantumScape
publish solid-state roadmaps; commercial cells remain rare.
EOF

cat > "$DOCS/notes/coffee-notes.md" <<'EOF'
# Coffee notes

Espresso shots run 25 to 30 seconds at 9 bar through a 7 g basket.
Light roasts pull longer; dark roasts faster. Water temperature 92 to 96 C.
A 1:2 brew ratio (in to out) is the typical modern espresso baseline.
Filter coffee uses a coarser grind, longer contact time, and lower pressure.
Battery-powered grinders exist but corded burr grinders dominate cafes.
EOF

# Large note: 200 KB lorem with one embedded fact.
{
    head -c 99000 /dev/urandom | base64 | tr -d '\n' | fold -w 80
    printf '\n\nThe quasi-stellar object 3C273 has a redshift of 0.158 (BURIED FACT).\n\n'
    head -c 99000 /dev/urandom | base64 | tr -d '\n' | fold -w 80
} > "$DOCS/notes/large.md"

# Code fixture for the code-chunker self-RAG cell.
cp "$SRC_CODE" "$DOCS/code/searcher.py"

# PDF: 5 page slice of the Star Wars X-Wing guide.
if [[ -f "$DOCS/pdf/star-wars-5p.pdf" ]]; then
    echo ">> star-wars-5p.pdf already present, skipping"
else
    if [[ ! -f "$SRC_PDF" ]]; then
        echo "!! source PDF missing: $SRC_PDF" >&2
        echo "!! skipping pdf fixture; vision cells will be unavailable"
    else
        TMP=$(mktemp -d)
        pdfseparate -f 1 -l 5 "$SRC_PDF" "$TMP/p-%d.pdf"
        pdfunite "$TMP"/p-*.pdf "$DOCS/pdf/star-wars-5p.pdf"
        rm -rf "$TMP"
        echo ">> built $DOCS/pdf/star-wars-5p.pdf ($(du -h "$DOCS/pdf/star-wars-5p.pdf" | cut -f1))"
    fi
fi

echo ""
echo ">> fixtures seeded under $DOCS"
ls -la "$DOCS/notes" "$DOCS/code" "$DOCS/pdf"
