# scripts/migrate_add_imo.py
import sqlite3
from pathlib import Path

DB = Path("tanker.db")

with sqlite3.connect(DB) as con:
    con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist(
          mmsi INTEGER PRIMARY KEY,
          name TEXT,
          class TEXT,
          favorite INTEGER DEFAULT 0,
          imo INTEGER
        )
    """)
    cols = {r[1] for r in con.execute("PRAGMA table_info(watchlist)").fetchall()}
    if "imo" not in cols:
        con.execute("ALTER TABLE watchlist ADD COLUMN imo INTEGER")
        print("[migrate] added watchlist.imo column")
    else:
        print("[migrate] watchlist.imo already present")
    con.commit()
