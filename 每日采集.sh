#!/usr/bin/env bash
# ── 小红书 → 飞书 数据自动采集同步 ──
# Mac/Linux 一键脚本。双击终端运行，或命令行执行。
set -euo pipefail

cd "$(dirname "$0")"

# ── 1. Detect Python ──
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
    echo "============================================================"
    echo "  ERROR: Python 3.11+ not found."
    echo "  Install from https://www.python.org/downloads/"
    echo "  macOS: brew install python@3.13"
    echo "============================================================"
    read -rp "Press Enter to exit..." _
    exit 1
fi

# ── 2. Check / Auto-start Chrome CDP ──
if curl -s http://localhost:9222/json/version &>/dev/null; then
    echo "Chrome CDP connected."
else
    echo "Chrome CDP port 9222 not responding. Trying to auto-start Chrome..."

    # Detect Chrome
    CHROME=""
    if [[ "$(uname -s)" == "Darwin" ]]; then
        for path in \
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
            "/Applications/Chromium.app/Contents/MacOS/Chromium"; do
            if [ -x "$path" ]; then CHROME="$path"; break; fi
        done
    else
        for path in google-chrome chromium-browser google-chrome-stable; do
            if command -v "$path" &>/dev/null; then
                CHROME="$(command -v "$path")"
                break
            fi
        done
    fi

    if [ -z "$CHROME" ]; then
        echo "============================================================"
        echo "  ERROR: Chrome not found. Please install Chrome first,"
        echo "  or switch to CSV-only mode in config/settings.yaml."
        echo "============================================================"
        read -rp "Press Enter to exit..." _
        exit 1
    fi

    echo "  Chrome: $CHROME"
    echo "  Starting Chrome with remote debugging on port 9222..."
    echo "  (Log in to creator.xiaohongshu.com if this is your first run)"

    PROFILE_DIR="${HOME}/chrome-debug-profile"
    "$CHROME" \
        --remote-debugging-port=9222 \
        --user-data-dir="$PROFILE_DIR" \
        "https://creator.xiaohongshu.com" &
    CHROME_PID=$!

    # Wait up to 30 seconds for CDP
    for i in $(seq 1 15); do
        sleep 2
        if curl -s http://localhost:9222/json/version &>/dev/null; then
            echo "Chrome CDP connected."
            break
        fi
        if [ "$i" -eq 15 ]; then
            echo "============================================================"
            echo "  ERROR: Chrome started but CDP port not responding."
            echo "  Close all Chrome windows and try again."
            echo "============================================================"
            read -rp "Press Enter to exit..." _
            exit 1
        fi
    done
fi

# ── 3. Run collection ──
echo "Starting data collection..."
$PYTHON -m src.cli.main run -s bitable

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo "  Collection done."
    echo "============================================================"
else
    echo ""
    echo "============================================================"
    echo "  ERROR: Collection failed with code $?"
    echo "============================================================"
    read -rp "Press Enter to exit..." _
    exit $?
fi
