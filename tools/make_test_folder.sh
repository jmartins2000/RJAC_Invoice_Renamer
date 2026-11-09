#!/usr/bin/env bash
# Fresh copy of the sample invoices to try the app on (safe to rename/delete).
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf test-run && mkdir test-run
cp samples/*.pdf samples/edge-cases/not_an_invoice_slide.pdf test-run/
echo "Ready: $(pwd)/test-run ($(ls test-run | wc -l | tr -d ' ') PDFs)"
