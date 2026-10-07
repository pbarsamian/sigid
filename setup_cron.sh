#!/data/data/com.termux/files/usr/bin/bash
# sigid/setup_cron.sh — configure automatic weekly DB updates via cron
# Safe to run multiple times — won't add duplicate entries

set -e

echo "=== Signal ID — Cron Setup ==="

# 1. Install cronie and termux-services if not already present
echo "[1/3] Installing cronie and termux-services..."
pkg install -y cronie termux-services

# 2. Enable crond service
echo "[2/3] Enabling crond service..."
sv-enable crond
sv up crond 2>/dev/null || true   # start it now if not already running

# 3. Add crontab entry if not already present
echo "[3/3] Configuring crontab..."

SIGID_DIR="$(cd "$(dirname "$0")" && pwd)"
CRON_CMD="0 3 * * 0 cd ${SIGID_DIR} && git pull -q && python scraper.py --update >> ${SIGID_DIR}/scraper.log 2>&1"
CRON_MARKER="sigid-autoupdate"

# Check if already installed
if crontab -l 2>/dev/null | grep -q "${CRON_MARKER}"; then
    echo "  Cron entry already exists — skipping."
else
    # Append to existing crontab (preserve any other entries)
    (crontab -l 2>/dev/null; echo "# ${CRON_MARKER}"; echo "${CRON_CMD}") | crontab -
    echo "  Cron entry added."
fi

echo ""
echo "Done. Schedule: every Sunday at 3am"
echo "  - Pulls latest code from git"
echo "  - Runs incremental wiki DB update"
echo "  - Logs to: ${SIGID_DIR}/scraper.log"
echo ""
echo "To check the crontab:  crontab -l"
echo "To view logs:          tail -f ${SIGID_DIR}/scraper.log"
echo "To run update now:     cd ${SIGID_DIR} && python scraper.py --update"
