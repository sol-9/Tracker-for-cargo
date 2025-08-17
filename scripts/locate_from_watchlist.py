# scripts/locate_from_watchlist.py
import argparse, time, json
from pathlib import Path
import sqlite3
import requests

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "tanker.db"

def _conn():
    return sqlite3.connect(DB)

def ensure_tables():
    with _conn() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS ships(
            mmsi INTEGER PRIMARY KEY, imo INTEGER, name TEXT, ship_type TEXT,
            dwt REAL, max_draught REAL, company TEXT, cargo TEXT
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS positions(
            mmsi INTEGER, ts INTEGER, lat REAL, lon REAL,
            sog REAL, cog REAL, heading REAL, draught REAL,
            nav_status TEXT, source TEXT,
            PRIMARY KEY (mmsi, ts)
        )""")
        con.commit()

def _watchlist():
    with _conn() as con:
        cur = con.execute("SELECT mmsi FROM watchlist ORDER BY mmsi")
        return [int(r[0]) for r in cur.fetchall() if r and r[0]]

def _insert_position(mmsi, ts, lat, lon, sog, cog, heading=None, draught=None, nav_status=None, source="local_api"):
    with _conn() as con:
        con.execute("""INSERT OR IGNORE INTO positions
            (mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source)
            VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (int(mmsi), int(ts), float(lat), float(lon),
             None if sog is None else float(sog),
             None if cog is None else float(cog),
             None if heading is None else float(heading),
             None if draught is None else float(draught),
             nav_status, source))
        con.commit()

def fetch_one(base, mmsi, timeout=15):
    url = f"{base.rstrip('/')}/location/{mmsi}"
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()

def normalize_and_store(mmsi, payload, source="local_api"):
    """
    Expecting payload like:
      {"mmsi":..., "lat":..., "lon":..., "ts":..., "sog":..., "cog":...}
    If your API returns a different shape, adjust here.
    """
    lat = payload.get("lat") or payload.get("latitude")
    lon = payload.get("lon") or payload.get("longitude")
    ts  = payload.get("ts") or payload.get("timestamp") or int(time.time())
    sog = payload.get("sog"); cog = payload.get("cog")
    heading = payload.get("heading"); draught = payload.get("draught")
    nav_status = payload.get("nav_status")
    if lat is None or lon is None:
        return False
    _insert_position(mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source=source)
    return True

def run_once(base):
    ensure_tables()
    wl = _watchlist()
    if not wl:
        print("[locate] watchlist empty — add MMSIs first.")
        return
    ok = 0; fail = 0
    for m in wl:
        try:
            payload = fetch_one(base, m)
            if normalize_and_store(m, payload, source="position_api"):
                ok += 1
            else:
                fail += 1
        except Exception as e:
            print(f"[locate] {m}: error {e}")
            fail += 1
    print(f"[locate] stored ok={ok} fail={fail}")

def run_loop(base, every):
    while True:
        run_once(base)
        time.sleep(every)

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:5050", help="Base URL of your local API")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--interval", type=int, default=180, help="Seconds between loops")
    args = ap.parse_args()
    if args.once or not args.loop:
        run_once(args.base)
    else:
        run_loop(args.base, args.interval)
