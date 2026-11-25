#!/bin/bash
# Optional. Reports which of the deck reader's rendering dependencies are on this
# machine. The skill and the /deck-read and /corpus-* commands ship with the
# comms-engine plugin and need no install step of their own.
set -euo pipefail
echo "Checking dependencies:"
for bin in pdftoppm soffice tesseract; do
  if command -v "$bin" >/dev/null 2>&1; then
    echo "  ok       $bin"
  else
    case "$bin" in
      pdftoppm) echo "  MISSING  $bin   (required for rendering; brew install poppler)" ;;
      soffice)  echo "  missing  $bin   (only needed to render .pptx; brew install --cask libreoffice)" ;;
      tesseract) echo "  missing  $bin  (only needed to OCR image-only slides; brew install tesseract)" ;;
    esac
  fi
done
python3 - <<'PY'
import importlib.util as u
for mod, why in (("pdfplumber", "required, PDF geometry"),
                 ("pptx", "required for .pptx, pip install python-pptx")):
    print(f"  {'ok      ' if u.find_spec(mod) else 'MISSING '} {mod:<12} ({why})")
PY
