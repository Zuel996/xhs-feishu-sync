#!/usr/bin/env bash
# ── XHS Data Sync - Chrome Debug Mode Launcher (Mac/Linux) ──
# Close all Chrome windows before running this script.
# First use: log in to creator.xiaohongshu.com in the opened browser.
set -euo pipefail

# ── Detect Chrome ──
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

if [ -z "$CHROME" ]; then
    echo "[ERROR] Chrome not found."
    echo "Please install Google Chrome, or set CHROME environment variable."
    echo "  macOS: https://www.google.com/chrome/"
    echo "  Linux: sudo apt install google-chrome-stable"
    read -rp "Press Enter to exit..." _
    exit 1
fi

PROFILE_DIR="${HOME}/chrome-debug-profile"
CDP_PORT=9222
START_URL="https://creator.xiaohongshu.com"

echo "========================================"
echo "  XHS Data Sync - Chrome Debug Mode"
echo "========================================"
echo ""
echo "  Chrome:  $CHROME"
echo "  Profile: $PROFILE_DIR"
echo "  Port:    $CDP_PORT"
echo "  URL:     $START_URL"
echo ""
echo "After launch, confirm you are logged in to creator.xiaohongshu.com."
echo "========================================"
echo ""

"$CHROME" \
    --remote-debugging-port="$CDP_PORT" \
    --user-data-dir="$PROFILE_DIR" \
    "$START_URL" &
CHROME_PID=$!

echo "Chrome launched (PID $CHROME_PID). Waiting 5s to verify connection..."

# Wait up to 15s for CDP to respond
for i in $(seq 1 5); do
    sleep 3
    if curl -s "http://localhost:$CDP_PORT/json/version" &>/dev/null; then
        echo "[OK] CDP port $CDP_PORT connected"
        echo ""
        echo "You can now run: xhs-feishu run"
        exit 0
    fi
done

echo "[WARN] CDP port not responding. Confirm Chrome has fully started."
echo "       You may need to close all Chrome windows and try again."
echo ""
