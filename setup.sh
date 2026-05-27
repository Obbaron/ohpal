#!/usr/bin/env bash
set -e

echo "  ampm-analysis setup"
echo

if command -v python3 &> /dev/null; then
    PY=python3
elif command -v python &> /dev/null; then
    PY=python
else
    echo "  ERROR: Python not found on PATH."
    echo "  Install Python 3.11+ from https://www.python.org/downloads/"
    exit 1
fi

PYVER=$($PY --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PYVER" | cut -d. -f1)
MINOR=$(echo "$PYVER" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
    echo "  ERROR: Python 3.11+ required, found $PYVER"
    exit 1
fi
echo "  Found Python $PYVER"

if [ -d .venv ]; then
    echo "  .venv already exists, skipping creation"
else
    echo "  Creating virtual environment..."
    $PY -m venv .venv
fi

echo "  Installing dependencies..."
source .venv/bin/activate
pip install -e . --quiet

echo
echo "Done!"