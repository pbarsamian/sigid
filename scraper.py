"""
sigid/scraper.py — Signal ID Wiki → local SQLite

Uses the MediaWiki API to pull signal entries incrementally.
Run standalone:
    python scraper.py           # full initial scrape
    python scraper.py --update  # pull only pages changed since last run
"""

import argparse
import os
import re
import sqlite3
import time
import urllib.request
import urllib.parse
import json
from datetime import datetime, timezone

from db import get_conn, init_db, get_meta, set_meta

WIKI_API   = "https://www.sigidwiki.com/api.php"
WIKI_BASE  = "https://www.sigidwiki.com"
MEDIA_DIR  = os.path.join(os.path.dirname(__file__), "media")

os.makedirs(MEDIA_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Low-level API helpers
# ---------------------------------------------------------------------------

UA = "sigid-termux/1.0 (https://github.com/pbarsamian/sigid; personal SDR tool)"

# Tracks consecutive failures so we can back off adaptively
_consecutive_failures = 0

def api_get(params, retries=5, base_delay=2.0):
    """GET the MediaWiki API and return parsed JSON. Exponential backoff on failure."""
    global _consecutive_failures
    params["format"] = "json"
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            _consecutive_failures = 0   # reset on success
            return data
        except Exception as e:
            _consecutive_failures += 1
            wait = base_delay * (2 ** attempt)   # 2s, 4s, 8s, 16s, 32s
            print(f"  API error (attempt {attempt+1}/{retries}): {e} — waiting {wait:.0f}s")
            time.sleep(wait)
    return None


def download_file(url, dest_path, retries=3):
    """Download a remote file to dest_path. Returns dest_path or None on failure."""
    if os.path.exists(dest_path):
        return dest_path
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as resp:
                with open(dest_path, "wb") as f:
                    f.write(resp.read())
            return dest_path
        except Exception as e:
            wait = 2 * (2 ** attempt)
            print(f"    Download error (attempt {attempt+1}/{retries}): {e} — waiting {wait:.0f}s")
            time.sleep(wait)
    return None


# ---------------------------------------------------------------------------
# Page enumeration — uses Special:Ask (Semantic MediaWiki) to get all signals
# Falls back to namespace walk if SMW ask is unavailable
# ---------------------------------------------------------------------------

def get_all_page_titles():
    """
    Return list of (page_id, title) for every signal page.
    Walks all pages in the main namespace and filters out known meta pages.
    """
    titles = []
    apcontinue = None

    # Pages that are wiki infrastructure, not signals
    SKIP_TITLES = {
        "Signal_Identification_Guide", "Database", "Comments",
        "Adding_a_Signal_Entry", "Requested", "Template:DatabaseUNID",
        "Template:DatabaseQueryUNID", "Regulatory_Databases",
    }
    SKIP_PREFIXES = (
        "Template:", "Help:", "Category:", "Property:",
        "Form:", "Special:", "Talk:", "Signal_Identification_Wiki:",
    )

    while True:
        params = {
            "action":      "query",
            "list":        "allpages",
            "apnamespace": "0",       # main namespace only
            "aplimit":     "500",
        }
        if apcontinue:
            params["apfrom"] = apcontinue

        data = api_get(params)
        if not data:
            break

        pages = data.get("query", {}).get("allpages", [])
        for p in pages:
            title = p["title"]
            if title in SKIP_TITLES:
                continue
            if any(title.startswith(pfx) for pfx in SKIP_PREFIXES):
                continue
            titles.append((p["pageid"], title))

        apcontinue = data.get("continue", {}).get("apcontinue")
        if not apcontinue:
            break
        time.sleep(0.5)

    print(f"Found {len(titles)} signal pages via namespace walk.")
    return titles


def get_recently_changed_titles(since_timestamp):
    """Return (page_id, title) for pages changed since ISO timestamp."""
    titles = []
    rccontinue = None

    while True:
        params = {
            "action": "query",
            "list": "recentchanges",
            "rcstart": since_timestamp,
            "rcdir": "newer",
            "rclimit": "500",
            "rcnamespace": "0",
            "rcprop": "ids|title|timestamp",
            "rctype": "edit|new",
        }
        if rccontinue:
            params["rccontinue"] = rccontinue

        data = api_get(params)
        if not data:
            break

        changes = data.get("query", {}).get("recentchanges", [])
        titles.extend((c["pageid"], c["title"]) for c in changes)

        rccontinue = data.get("continue", {}).get("rccontinue")
        if not rccontinue:
            break

        time.sleep(0.5)

    print(f"Found {len(titles)} recently changed pages.")
    return titles


# ---------------------------------------------------------------------------
# Page parsing
# ---------------------------------------------------------------------------

# Infobox field aliases → our DB column names
FIELD_MAP = {
    "frequencies":      "freq_raw",
    "frequency":        "freq_raw",
    "bandwidth":        "bandwidth_hz",
    "modulation":       "modulation",
    "acf":              "acf",
    "symbol rate":      "symbol_rate",
    "mode":             "mode",
    "location":         "location",
    "used for":         "description_extra",
    "short description":"description",
}

FREQ_PATTERN = re.compile(
    r"([\d,\.]+)\s*(hz|khz|mhz|ghz)", re.IGNORECASE
)

def parse_freq_mhz(raw):
    """
    Try to extract (lower_mhz, upper_mhz) from a raw frequency string.
    Handles ranges like '118-137 MHz', single values, lists.
    Returns (None, None) if unparseable.
    """
    if not raw:
        return None, None

    raw = raw.strip()
    # strip wiki markup
    raw = re.sub(r"\[\[.*?\]\]", "", raw)
    raw = re.sub(r"<.*?>", "", raw)
    raw = raw.replace(",", "")

    # find all frequency mentions
    matches = FREQ_PATTERN.findall(raw)
    if not matches:
        return None, None

    def to_mhz(value, unit):
        v = float(value)
        u = unit.lower()
        if u == "hz":
            return v / 1_000_000
        if u == "khz":
            return v / 1_000
        if u == "mhz":
            return v
        if u == "ghz":
            return v * 1_000
        return v

    freqs = [to_mhz(v, u) for v, u in matches]
    return min(freqs), max(freqs)


def parse_wikitext_infobox(wikitext):
    """
    Extract key/value pairs from a {{Infobox}} style template.
    Returns a dict of raw field values.
    """
    fields = {}

    # find the infobox block
    m = re.search(r"\{\{[Ii]nfobox(.*?)\}\}", wikitext, re.DOTALL)
    if not m:
        return fields

    block = m.group(1)
    # each field is on its own line as | key = value
    for line in block.splitlines():
        line = line.strip().lstrip("|").strip()
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip().lower()
            val = val.strip()
            # strip wiki markup from value
            val = re.sub(r"\[\[([^\|\]]+\|)?([^\]]+)\]\]", r"\2", val)
            val = re.sub(r"'{2,}", "", val)
            val = re.sub(r"<.*?>", "", val)
            if key and val:
                fields[key] = val

    return fields


def get_page_content(page_id):
    """Fetch wikitext + revision info for a single page."""
    data = api_get({
        "action": "query",
        "pageids": page_id,
        "prop": "revisions|images|categories",
        "rvprop": "ids|content",
        "imlimit": "10",
        "cllimit": "20",
    })
    if not data:
        return None

    pages = data.get("query", {}).get("pages", {})
    page = pages.get(str(page_id))
    if not page or "missing" in page:
        return None

    rev = page.get("revisions", [{}])[0]
    wikitext = rev.get("*", "") or rev.get("slots", {}).get("main", {}).get("*", "")
    revision_id = rev.get("revid")

    images = [i["title"] for i in page.get("images", [])]
    categories = [c["title"].replace("Category:", "") for c in page.get("categories", [])]

    return {
        "page_id": page_id,
        "title": page["title"],
        "wikitext": wikitext,
        "revision_id": revision_id,
        "images": images,
        "categories": categories,
    }


def resolve_image_url(image_title):
    """Get the direct URL for a wiki image file."""
    data = api_get({
        "action": "query",
        "titles": image_title,
        "prop": "imageinfo",
        "iiprop": "url",
    })
    if not data:
        return None
    pages = data.get("query", {}).get("pages", {})
    for page in pages.values():
        info = page.get("imageinfo", [{}])
        if info:
            return info[0].get("url")
    return None


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def upsert_signal(page_data):
    """Parse a page and upsert into the DB. Returns True if saved."""
    title    = page_data["title"]
    wiki_id  = str(page_data["page_id"])
    wikitext = page_data["wikitext"]
    revision = page_data["revision_id"]
    cats     = page_data["categories"]
    images   = page_data["images"]

    raw_fields = parse_wikitext_infobox(wikitext)

    # --- frequency ---
    freq_raw = raw_fields.get("freq_raw") or raw_fields.get("frequencies") or raw_fields.get("frequency", "")
    freq_lower, freq_upper = parse_freq_mhz(freq_raw)

    # --- modulation: normalise to uppercase list ---
    modulation = raw_fields.get("modulation", "").upper() or None

    # --- description: first non-empty paragraph outside infobox ---
    desc = raw_fields.get("description") or ""
    if not desc:
        # grab first plain paragraph
        plain = re.sub(r"\{\{.*?\}\}", "", wikitext, flags=re.DOTALL)
        plain = re.sub(r"\[\[([^\|\]]+\|)?([^\]]+)\]\]", r"\2", plain)
        plain = re.sub(r"[=\{\}\[\]|<>]", "", plain).strip()
        paragraphs = [p.strip() for p in plain.splitlines() if len(p.strip()) > 40]
        desc = paragraphs[0] if paragraphs else ""

    # --- media ---
    waterfall_url = None
    audio_url     = None
    waterfall_local = None
    audio_local     = None

    for img_title in images:
        lower = img_title.lower()
        if any(lower.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif")):
            if waterfall_url is None:
                waterfall_url = resolve_image_url(img_title)
                time.sleep(0.3)
        elif any(lower.endswith(ext) for ext in (".mp3", ".ogg", ".wav")):
            if audio_url is None:
                audio_url = resolve_image_url(img_title)
                time.sleep(0.3)

    # cache media locally
    safe_name = re.sub(r"[^\w\-]", "_", title)
    if waterfall_url:
        ext = waterfall_url.rsplit(".", 1)[-1].split("?")[0]
        dest = os.path.join(MEDIA_DIR, f"{safe_name}_wf.{ext}")
        waterfall_local = download_file(waterfall_url, dest)

    if audio_url:
        ext = audio_url.rsplit(".", 1)[-1].split("?")[0]
        dest = os.path.join(MEDIA_DIR, f"{safe_name}_audio.{ext}")
        audio_local = download_file(audio_url, dest)

    # --- DB upsert ---
    conn = get_conn()
    conn.execute("""
        INSERT INTO signals
            (wiki_id, name, url, description,
             freq_lower_mhz, freq_upper_mhz, bandwidth_hz,
             modulation, acf, symbol_rate, mode, location,
             waterfall_url, waterfall_local, audio_url, audio_local,
             wiki_revision, last_updated)
        VALUES
            (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
        ON CONFLICT(wiki_id) DO UPDATE SET
            name            = excluded.name,
            url             = excluded.url,
            description     = excluded.description,
            freq_lower_mhz  = excluded.freq_lower_mhz,
            freq_upper_mhz  = excluded.freq_upper_mhz,
            bandwidth_hz    = excluded.bandwidth_hz,
            modulation      = excluded.modulation,
            acf             = excluded.acf,
            symbol_rate     = excluded.symbol_rate,
            mode            = excluded.mode,
            location        = excluded.location,
            waterfall_url   = excluded.waterfall_url,
            waterfall_local = excluded.waterfall_local,
            audio_url       = excluded.audio_url,
            audio_local     = excluded.audio_local,
            wiki_revision   = excluded.wiki_revision,
            last_updated    = datetime('now')
    """, (
        wiki_id,
        title,
        f"https://www.sigidwiki.com/wiki/{urllib.parse.quote(title.replace(' ', '_'))}",
        desc,
        freq_lower, freq_upper,
        raw_fields.get("bandwidth_hz") or raw_fields.get("bandwidth"),
        modulation,
        raw_fields.get("acf"),
        raw_fields.get("symbol_rate"),
        raw_fields.get("mode"),
        raw_fields.get("location"),
        waterfall_url, waterfall_local,
        audio_url, audio_local,
        revision,
    ))

    # categories
    signal_row = conn.execute(
        "SELECT id FROM signals WHERE wiki_id = ?", (wiki_id,)
    ).fetchone()
    if signal_row:
        sid = signal_row["id"]
        conn.execute("DELETE FROM signal_categories WHERE signal_id = ?", (sid,))
        conn.executemany(
            "INSERT OR IGNORE INTO signal_categories (signal_id, category) VALUES (?,?)",
            [(sid, cat) for cat in cats]
        )

    conn.commit()
    conn.close()
    return True


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def full_scrape():
    """Initial full scrape of all signal pages."""
    print("=== Full scrape starting ===")
    init_db()
    titles = get_all_page_titles()
    total = len(titles)

    for i, (page_id, title) in enumerate(titles, 1):
        print(f"[{i}/{total}] {title}")
        page_data = get_page_content(page_id)
        if page_data:
            upsert_signal(page_data)
        # back off more if we've been hitting errors
        if _consecutive_failures >= 3:
            sleep_time = 5.0
        elif _consecutive_failures >= 1:
            sleep_time = 2.0
        else:
            sleep_time = 1.0   # baseline — polite but not too slow
        time.sleep(sleep_time)

    now = datetime.now(timezone.utc).isoformat()
    set_meta("last_full_scrape", now)
    set_meta("last_update", now)
    print(f"\nFull scrape complete. {total} signals processed.")


def incremental_update():
    """Pull only pages changed since last update."""
    last = get_meta("last_update")
    if not last:
        print("No previous scrape found — running full scrape instead.")
        full_scrape()
        return

    print(f"=== Incremental update since {last} ===")
    titles = get_recently_changed_titles(last)
    if not titles:
        print("No changes since last update.")
    else:
        for i, (page_id, title) in enumerate(titles, 1):
            print(f"[{i}/{len(titles)}] {title}")
            page_data = get_page_content(page_id)
            if page_data:
                upsert_signal(page_data)
            time.sleep(0.5)

    now = datetime.now(timezone.utc).isoformat()
    set_meta("last_update", now)
    print(f"Update complete. {len(titles)} pages processed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal ID Wiki scraper")
    parser.add_argument("--update", action="store_true",
                        help="Incremental update only (default: full scrape)")
    args = parser.parse_args()

    if args.update:
        incremental_update()
    else:
        full_scrape()
