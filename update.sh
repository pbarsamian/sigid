#!/data/data/com.termux/files/usr/bin/bash
# sigid/update.sh — pull latest code from git
# Usage: bash update.sh
# Optionally also updates the Signal ID Wiki DB: bash update.sh --db

set -e

echo "=== Signal ID — Code Update ==="

# 1. Pull latest code
echo "[1/2] Pulling latest from git..."
git pull origin main

# 2. Optionally update the wiki DB
if [[ "$1" == "--db" ]]; then
    echo "[2/2] Updating Signal ID Wiki database..."
    python scraper.py --update
else
    echo "[2/2] Skipping DB update (pass --db to include it)"
fi

echo ""
echo "Done. Restart the server to apply changes:"
echo "  python server.py"
