# scripts/map_imo_to_mmsi.py
import sqlite3
from pathlib import Path
import pandas as pd

DB  = Path("tanker.db")
CSV = Path("data/discovered_imo.csv")

def conn():
    return sqlite3.connect(DB)

def ensure_watchlist_with_imo():
    with conn() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS watchlist(
              mmsi INTEGER PRIMARY KEY,
              name TEXT,
              class TEXT,
              favorite INTEGER DEFAULT 0,
              imo INTEGER
            )
        """)
        # if the table existed without imo, add it
        con.execute("PRAGMA table_info(watchlist)")
        cols = {r[1] for r in con.fetchall()}
        if "imo" not in cols:
            con.execute("ALTER TABLE watchlist ADD COLUMN imo INTEGER")
        con.commit()

def classify(ship_type):
    if ship_type is None:
        return None
    s = str(ship_type).lower()
    if "tanker" in s or "lng" in s or "lpg" in s or "chem" in s or "oil" in s or "product" in s:
        return "Tanker"
    if "cargo" in s or "bulk" in s or "container" in s or "ro-ro" in s or "general cargo" in s:
        return "Cargo"
    try:
        code = int(ship_type)
        if 80 <= code <= 89: return "Tanker"
        if 70 <= code <= 79: return "Cargo"
    except Exception:
        pass
    return None

def main():
    ensure_watchlist_with_imo()

    if not CSV.exists():
        print(f"[map] {CSV} not found. Run discover_web_imo.py first.")
        return
    imos = pd.read_csv(CSV)["imo"].dropna().astype(int).unique().tolist()
    if not imos:
        print("[map] No IMOs in CSV.")
        return

    with conn() as con:
        try:
            ships = pd.read_sql_query("SELECT mmsi, imo, name, ship_type FROM ships", con)
        except Exception:
            print("[map] ships table not available or empty (run AIS stream to collect static data).")
            return

    if ships.empty:
        print("[map] ships table empty.")
        return

    ships = ships.dropna(subset=["imo"])
    ships["imo"] = ships["imo"].astype(int)
    matches = ships[ships["imo"].isin(imos)]
    if matches.empty:
        print("[map] No overlaps yet between discovered IMOs and AIS static IMOs.")
        return

    with conn() as con:
        n = 0
        for r in matches.itertuples(index=False):
            mmsi = int(r.mmsi) if pd.notna(r.mmsi) else None
            if not mmsi: 
                continue
            cls = classify(r.ship_type)
            con.execute("INSERT OR IGNORE INTO watchlist(mmsi) VALUES(?)", (mmsi,))
            con.execute("""
                UPDATE watchlist
                   SET imo = COALESCE(?, imo),
                       name = COALESCE(?, name),
                       class = COALESCE(?, class)
                 WHERE mmsi = ?
            """, (int(r.imo), r.name, cls, mmsi))
            n += 1
        con.commit()
    print(f"[map] upserted/updated {n} watchlist rows via IMO→MMSI mapping.")

if __name__ == "__main__":
    main()
