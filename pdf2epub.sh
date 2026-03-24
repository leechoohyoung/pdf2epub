#!/bin/zsh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ $# -lt 1 ]]; then
  echo "Usage: $(basename "$0") <input.pdf> [-o output.epub] [--dpi 150] [--language ko] [--log-file output.log] [--keep-temp]" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/pdf2epub.py" "$@"
