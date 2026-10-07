"""
sigid/debug_page.py — dump raw wikitext of one signal to diagnose infobox parsing
Usage: python debug_page.py
       python debug_page.py "ACARS"
"""
import sys
from scraper import get_page_content, get_all_page_titles, parse_wikitext_infobox

# Use a specific title if given, otherwise grab the first signal from the DB
if len(sys.argv) > 1:
    title = sys.argv[1]
    from scraper import api_get, WIKI_API
    import urllib.parse
    data = api_get({
        "action": "query",
        "titles": title,
        "prop": "revisions|images",
        "rvprop": "ids|content",
        "imlimit": "5",
    })
    pages = data.get("query", {}).get("pages", {})
    page_id = list(pages.keys())[0]
    page_data = {
        "page_id": int(page_id),
        "title": pages[page_id]["title"],
        "wikitext": (pages[page_id].get("revisions", [{}])[0].get("*", "")
                     or pages[page_id].get("revisions", [{}])[0]
                     .get("slots", {}).get("main", {}).get("*", "")),
        "revision_id": pages[page_id].get("revisions", [{}])[0].get("revid"),
        "images": [i["title"] for i in pages[page_id].get("images", [])],
        "categories": [],
    }
else:
    # grab first signal from DB
    from db import get_conn
    conn = get_conn()
    row = conn.execute("SELECT wiki_id, name FROM signals LIMIT 1").fetchone()
    conn.close()
    if not row:
        print("No signals in DB yet.")
        sys.exit(1)
    print(f"Using first DB signal: {row['name']} (wiki_id={row['wiki_id']})")
    page_data = get_page_content(int(row["wiki_id"]))

if not page_data:
    print("Could not fetch page.")
    sys.exit(1)

print(f"\n=== Page: {page_data['title']} ===")
print(f"Images: {page_data['images']}")
print(f"\n--- Raw wikitext (first 2000 chars) ---")
print(page_data["wikitext"][:2000])
print("\n--- Parsed infobox fields ---")
fields = parse_wikitext_infobox(page_data["wikitext"])
if fields:
    for k, v in fields.items():
        print(f"  {k!r:30s} = {v!r}")
else:
    print("  (no infobox fields found)")
