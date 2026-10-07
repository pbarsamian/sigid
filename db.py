"""
sigid/db.py — SQLite schema and query helpers
"""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "sigid.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            wiki_id         TEXT UNIQUE NOT NULL,   -- MediaWiki page ID
            name            TEXT NOT NULL,
            url             TEXT,
            description     TEXT,
            -- RF characteristics (all nullable -- wiki entries vary in completeness)
            freq_lower_mhz  REAL,
            freq_upper_mhz  REAL,
            bandwidth_hz    TEXT,                   -- stored as text e.g. "25 kHz" -- varies too much to normalise
            modulation      TEXT,                   -- AM / FM / SSB / OFDM / FSK etc
            acf             TEXT,                   -- autocorrelation function value
            symbol_rate     TEXT,
            mode            TEXT,
            location        TEXT,                   -- geographic region of use
            -- Media
            waterfall_url   TEXT,                   -- remote URL
            waterfall_local TEXT,                   -- local cached path
            audio_url       TEXT,
            audio_local     TEXT,
            -- Housekeeping
            wiki_revision   INTEGER,                -- last seen revision ID
            last_updated    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS signal_categories (
            signal_id   INTEGER REFERENCES signals(id) ON DELETE CASCADE,
            category    TEXT NOT NULL,
            PRIMARY KEY (signal_id, category)
        );

        CREATE TABLE IF NOT EXISTS meta (
            key     TEXT PRIMARY KEY,
            value   TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_signals_modulation ON signals(modulation);
        CREATE INDEX IF NOT EXISTS idx_signals_freq ON signals(freq_lower_mhz, freq_upper_mhz);
        CREATE INDEX IF NOT EXISTS idx_signals_name ON signals(name COLLATE NOCASE);
    """)

    conn.commit()
    conn.close()
    print("DB initialised.")


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def search_signals(freq_mhz=None, modulation=None, name_fragment=None, limit=20):
    """
    Return signals matching any supplied filters (AND logic).
    All filters are optional.
    """
    conn = get_conn()
    c = conn.cursor()

    clauses = []
    params = []

    if freq_mhz is not None:
        # match signals whose frequency range overlaps the given frequency
        # handles entries that only have one bound set
        clauses.append("""
            (
                (freq_lower_mhz IS NULL OR freq_lower_mhz <= ?)
                AND
                (freq_upper_mhz IS NULL OR freq_upper_mhz >= ?)
            )
        """)
        params.extend([freq_mhz, freq_mhz])

    if modulation:
        clauses.append("modulation LIKE ?")
        params.append(f"%{modulation}%")

    if name_fragment:
        clauses.append("name LIKE ?")
        params.append(f"%{name_fragment}%")

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    query = f"SELECT * FROM signals {where} ORDER BY name LIMIT ?"
    params.append(limit)

    rows = c.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_signal(wiki_id):
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM signals WHERE wiki_id = ?", (wiki_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_meta(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_meta(key, value):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, str(value))
    )
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
