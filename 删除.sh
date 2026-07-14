#!/usr/bin/env bash
# ── 清空全部飞书数据表 + 本地 SQLite ──
# Mac/Linux 一键脚本。账号管理表不受影响。
set -euo pipefail

cd "$(dirname "$0")"

echo "============================================================"
echo "  Delete ALL data from Feishu Bitable"
echo "============================================================"
echo ""
echo "  This will delete ALL records from:"
echo "    - account_summary"
echo "    - note_metrics"
echo "    - daily_snapshot"
echo "    - competitor_comparison"
echo "  + local SQLite database"
echo ""
echo "  Note: account_manager table is NOT affected."
echo ""

read -rp "Type YES to confirm delete: " CONFIRM

if [ "$CONFIRM" != "YES" ]; then
    echo ""
    echo "  Cancelled."
    exit 0
fi

echo ""
echo "  Deleting..."
echo ""

# ── Detect Python ──
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
    echo "ERROR: Python 3.11+ not found."
    read -rp "Press Enter to exit..." _
    exit 1
fi

$PYTHON -m src.cli.main clear --all --confirm

if [ $? -eq 0 ]; then
    echo ""
    echo "============================================================"
    echo "  Done."
    echo "============================================================"
else
    echo ""
    echo "============================================================"
    echo "  ERROR: Delete failed with code $?"
    echo "============================================================"
    read -rp "Press Enter to exit..." _
    exit $?
fi
