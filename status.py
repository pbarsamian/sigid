"""
sigid/status.py — quick DB health check
Usage: python status.py
"""

from db import get_conn, get_meta

conn = get_conn()

total     = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
with_freq = conn.execute("SELECT COUNT(*) FROM signals WHERE freq_lower_mhz IS NOT NULL").fetchone()[0]
with_mod  = conn.execute("SELECT COUNT(*) FROM signals WHERE modulation IS NOT NULL").fetchone()[0]
with_wf   = conn.execute("SELECT COUNT(*) FROM signals WHERE waterfall_local IS NOT NULL").fetchone()[0]
with_audio= conn.execute("SELECT COUNT(*) FROM signals WHERE audio_local IS NOT NULL").fetchone()[0]
no_data   = conn.execute("""
    SELECT COUNT(*) FROM signals
    WHERE freq_lower_mhz IS NULL AND modulation IS NULL AND description = ''
""").fetchone()[0]

conn.close()

last_full   = get_meta("last_full_scrape", "never")
last_update = get_meta("last_update", "never")

print("=== Signal ID — DB Status ===")
print(f"Total signals:        {total}")
print(f"With frequency data:  {with_freq}  ({100*with_freq//total if total else 0}%)")
print(f"With modulation data: {with_mod}  ({100*with_mod//total if total else 0}%)")
print(f"With waterfall image: {with_wf}")
print(f"With audio sample:    {with_audio}")
print(f"Empty entries:        {no_data}")
print(f"Last full scrape:     {last_full}")
print(f"Last update:          {last_update}")
