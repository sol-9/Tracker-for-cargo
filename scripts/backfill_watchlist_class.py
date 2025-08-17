# scripts/backfill_watchlist_class.py
import sqlite3
from pathlib import Path
import pandas as pd

DB = Path(__file__).resolve().parents[1] / "tanker.db"

def classify(val):
    # Accept string categories or AIS numeric codes
    if isinstance(val, str):
        s = val.strip().lower()
        if "tanker" in s: return "Tanker"
        if "cargo" in s:  return "Cargo"
        # handle some common variants
        if "lng" in s or "lpg" in s or "oil" in s: return "Tanker"
        if "container" in s or "bulk" in s: return "Cargo"
        return None
    try:
        t = int(val)
        if 80 <= t <= 89: return "Tanker"
        if 70 <= t <= 79: return "Cargo"
    except Exception:
        pass
    return None

def main():
    con = sqlite3.connect(DB)
    # pull ships + types (whatever you have)
    try:
        ships = pd.read_sql_query("SELECT mmsi, ship_type FROM ships", con)
    except Exception:
        ships = pd.DataFrame(columns=["mmsi","ship_type"])
    if ships.empty:
        print("[backfill] ships table empty; run AISStream for a bit to learn ship types.")
        return

    ships["mmsi"] = pd.to_numeric(ships["mmsi"], errors="coerce").astype("Int64")
    ships["class_guess"] = ships["ship_type"].apply(classify)

    updates = ships.dropna(subset=["mmsi","class_guess"]).values.tolist()
    if not updates:
        print("[backfill] no class guesses were produced (ship_type missing or unrecognized).")
        return

    # Update only rows with NULL class in watchlist
    cur = con.cursor()
    n = 0
    for mmsi, ship_type, cls in updates:
        cur.execute(
            "UPDATE watchlist SET class = COALESCE(class, ?) WHERE mmsi = ?",
            (cls, int(mmsi))
        )
        n += cur.rowcount
    con.commit()

    # show summary
    rows = con.execute("SELECT class, COUNT(*) FROM watchlist GROUP BY class").fetchall()
    print(f"[backfill] updated rows: ~{n}")
    print("[backfill] watchlist by class:", rows)
    con.close()

if __name__ == "__main__":
    main()
