#!/usr/bin/env bash
# ── xhs-feishu-sync — One-Click Setup (Mac/Linux) ──
set -euo pipefail

cd "$(dirname "$0")/.."

echo "============================================================"
echo "  xhs-feishu-sync — One-Click Setup"
echo "============================================================"
echo ""

# ── 1. Check Python ──
echo "[1/4] Checking Python environment..."

PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" --version 2>&1)
        if echo "$ver" | grep -qE 'Python (3\.1[1-9]|3\.[2-9][0-9])'; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  [X] Python 3.11+ not found."
    echo "      Download: https://www.python.org/downloads/"
    echo "      macOS: brew install python@3.13"
    echo "      Linux: sudo apt install python3.11"
    read -rp "Press Enter to exit..." _
    exit 1
fi

PYVER=$("$PYTHON" --version 2>&1)
echo "  [OK] $PYVER"

# ── 2. Install dependencies ──
echo ""
echo "[2/4] Installing project dependencies..."
"$PYTHON" -m pip install -e . --quiet
if [ $? -ne 0 ]; then
    echo "  [X] Dependency install failed. Check network and retry."
    read -rp "Press Enter to exit..." _
    exit 1
fi
echo "  [OK] Dependencies installed"

# ── 3. Config files ──
echo ""
echo "[3/4] Checking config files..."

if [ ! -f .env ]; then
    if [ -f .env.example ]; then
        cp .env.example .env
        echo "  [OK] Created .env from .env.example"
        echo "  [!!] Edit .env and fill in your Feishu app credentials"
    else
        echo "  [!!] .env.example not found. Create .env manually."
    fi
else
    echo "  [OK] .env exists, skipping"
fi

# Chrome path detection
CHROME=""
if [[ "$(uname -s)" == "Darwin" ]]; then
    for path in \
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
        "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
        if [ -x "$path" ]; then CHROME="$path"; break; fi
    done
else
    for name in google-chrome chromium-browser google-chrome-stable chromium; do
        if command -v "$name" &>/dev/null; then
            CHROME="$(command -v "$name")"
            break
        fi
    done
fi

if [ -n "$CHROME" ]; then
    echo "  [OK] Chrome: $CHROME"
else
    echo "  [!!] Chrome not detected (CSV-only mode unaffected)"
fi

# accounts.yaml check
if grep -q "your_account" config/accounts.yaml 2>/dev/null; then
    echo "  [!!] accounts.yaml still has placeholder. Edit and fill in real accounts."
else
    echo "  [OK] accounts.yaml configured"
fi

# ── 4. Initialize database ──
echo ""
echo "[4/4] Initializing database and Feishu tables..."
"$PYTHON" -m src.cli.main setup
if [ $? -ne 0 ]; then
    echo "  [!!] Setup partially completed (Feishu tables may need .env config)"
else
    echo "  [OK] Initialization complete"
fi

# ── Done ──
echo ""
echo "============================================================"
echo "  Setup Complete!"
echo "============================================================"
echo ""
echo "  Next steps:"
echo "  1. Edit .env with Feishu credentials"
echo "  2. Edit config/accounts.yaml with XHS accounts"
echo "    — or fill in the '账号管理' table in Feishu Bitable"
echo "  3. $PYTHON -m src.cli.main test-feishu   # Verify Feishu"
echo "  4. scripts/start_chrome.sh   # Start Chrome debug mode"
echo "  5. $PYTHON -m src.cli.main run   # First data sync"
echo ""
