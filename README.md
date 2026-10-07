# Signal ID — Termux Edition

Local Signal ID Wiki browser and RF signal identifier for Android.
Runs entirely in Termux, accessed via browser at `http://localhost:8080`.

## Install (Termux)

```bash
# 1. Update packages
pkg update && pkg upgrade

# 2. Install dependencies
pkg install python git sqlite

# 3. Install Python packages
pip install flask requests beautifulsoup4

# 4. Clone or copy this project
#    (or just create the sigid/ folder manually)

# 5. Initial DB scrape (takes ~10-20 min depending on connection)
cd sigid
python scraper.py

# 6. Start the server
python server.py
```

Then open **http://localhost:8080** in your Android browser.

## Usage

1. Enter the frequency you're seeing in RF Analyzer (MHz)
2. Select the modulation type if known
3. Optionally take a screenshot of the waterfall and upload it
4. Toggle AI identification on if you have internet (uses Claude API)
5. Hit Identify

## Update the database

- **In the browser UI** — tap "Update DB" for incremental, "Full Rescrape" to rebuild
- **From Termux** — `python scraper.py --update`

## Auto-update (optional cron via Termux)

```bash
pkg install cronie termux-services
sv-enable crond
crontab -e
# Add: 0 3 * * 0 cd ~/sigid && python scraper.py --update >> scraper.log 2>&1
```

## Files

```
sigid/
├── db.py         # SQLite schema + query helpers
├── scraper.py    # Signal ID Wiki → SQLite scraper
├── matcher.py    # Signal matching + Claude API vision
├── server.py     # Flask web UI on localhost:8080
├── sigid.db      # Local database (created on first run)
└── media/        # Cached waterfall images + audio samples
```
