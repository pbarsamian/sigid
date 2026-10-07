#!/data/data/com.termux/files/usr/bin/bash
# sigid/setup.sh — fresh Termux setup
# Usage: bash setup.sh

set -e

echo "=== Signal ID — Termux Setup ==="

# 1. System packages
echo "[1/4] Installing system packages..."
pkg update -y
pkg install -y python git sqlite

# 2. Python packages
echo "[2/4] Installing Python packages..."
pip install --quiet flask requests beautifulsoup4

# 3. Init DB
echo "[3/4] Initialising database..."
python db.py

# 4. Set up cron for automatic weekly updates
echo "[4/4] Setting up automatic weekly updates..."
bash setup_cron.sh

echo ""
echo "Setup complete."
echo ""
echo "Next steps:"
echo "  Initial DB scrape (do this once, needs WiFi, takes 30-60 min):"
echo "    python scraper.py"
echo ""
echo "  Then start the server:"
echo "    python server.py"
echo ""
echo "  Then open in browser: http://localhost:8080"
