#!/bin/bash
# ─────────────────────────────────────────────────────
#  PDF OCR Tool — Shell Wrapper
#
#  Usage:
#    ./ocr.sh "My Book.pdf"          Process one file
#    ./ocr.sh ~/Desktop/scans/       Process all PDFs in a folder
#    ./ocr.sh --all                  Process all PDFs in lit/
#    ./ocr.sh --setup                First-time configuration
#    ./ocr.sh --cleanup              Remove temp files
# ─────────────────────────────────────────────────────

# Check if running on macOS
if [ "$(uname)" != "Darwin" ]; then
    echo "⚠️ Warning: This tool is designed for macOS and might not work correctly on other operating systems."
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew is not installed on this Mac."
    echo "   Homebrew is required to install dependencies like the Google Cloud CLI."
    echo "   To install Homebrew, copy and paste this command into your terminal:"
    echo ""
    echo '   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    echo ""
    echo "   After installing Homebrew, restart your terminal and run this script again."
    exit 1
fi

# Check that venv exists
if [ ! -d "$SCRIPT_DIR/.venv" ]; then
    echo "❌ Python virtual environment not found."
    echo "   Run these commands first:"
    echo ""
    echo "   cd $SCRIPT_DIR"
    echo "   /opt/homebrew/bin/python3 -m venv .venv"
    echo "   source .venv/bin/activate"
    echo "   pip install -r requirements.txt"
    exit 1
fi

# Activate venv
source "$SCRIPT_DIR/.venv/bin/activate"

# Route arguments
if [ $# -eq 0 ]; then
    python "$SCRIPT_DIR/ocr.py" --help
elif [ "$1" = "--setup" ] || [ "$1" = "--all" ] || [ "$1" = "--cleanup" ] || [ "$1" = "--resume" ] || [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    python "$SCRIPT_DIR/ocr.py" "$@"
elif [ -d "$1" ]; then
    python "$SCRIPT_DIR/ocr.py" --dir "$@"
elif [ -f "$1" ]; then
    python "$SCRIPT_DIR/ocr.py" "$@"
else
    python "$SCRIPT_DIR/ocr.py" "$@"
fi
