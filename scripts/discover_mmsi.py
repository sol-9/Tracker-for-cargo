# scripts/discover_mmsi.py
import argparse, csv, os, re
from pathlib import Path
import sqlite3
import glob
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "tanker.db"
DATA = ROOT / "data"
SEEDS_DIR = DATA / "seeds"
HTML_DIR  = DATA / "html"
OUT_CSV   = DATA / "discovered_mmsi.csv"

MMSI_RE = re.compile(r"\b([2-7]\d{8})\b")  # valid MMSI starts 2-7 and 9 digits

DATA.mkdir(exist_ok=True)
SEEDS_DIR.mkdir(parents=True, exist_ok=True)
HTML_DIR.mkdir(parents=True, exist_ok=True)

def _conn():
    return sqlite3.connect(DB)

def create_watchlist_if_needed():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            mmsi INTEGER PRIMARY KEY,
            name TEXT,
            class TEXT,
            favorite INTEGER DEFAULT 0
        )""")
        con.commit()

def from_db_ships(target: str|None):
    """
    Harvest MMSIs we already learned via AISStream StaticData (ships table).
    target None = all; 'Cargo'/'Tanker' to filter.
    """
    rows = []
    with _conn() as con:
        if target:
            q = "SELECT mmsi, COALESCE(name,''), COALESCE(ship_type,'') FROM ships WHERE ship_type=?"
            args = (target,)
        else:
            q = "SELECT mmsi, COALESCE(name,''), COALESCE(ship_type,'') FROM ships"
            args = ()
        cur = con.execute(q, args)
        for mmsi, name, sclass in cur.fetchall():
            if not mmsi: 
                continue
            rows.append({"mmsi": int(mmsi), "name": name or None, "class": sclass or None, "source": "db_ships"})
    return rows

def from_seed_csvs():
    rows = []
    for path in glob.glob(str(SEEDS_DIR / "*.csv")):
        try:
            df = pd.read_csv(path)
        except Exception:
            continue
        for _, r in df.iterrows():
            m = str(r.get("MMSI") or r.get("mmsi") or "").strip()
            if not m.isdigit() or len(m) != 9: 
                continue
            rows.append({
                "mmsi": int(m),
                "name": (r.get("Name") or r.get("name") or None),
                "class": (r.get("Class") or r.get("class") or None),
                "source": f"seed_csv:{Path(path).name}",
            })
    return rows

def from_saved_html():
    """
    Parse any saved HTML pages in data/html/ and regex out MMSIs.
    (Use for manual exports; avoids live scraping TOS issues.)
    """
    rows = []
    for path in glob.glob(str(HTML_DIR / "*.html")):
        try:
            text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        seen_here = set()
        for mm in MMSI_RE.findall(text):
            if mm in seen_here: 
                continue
            seen_here.add(mm)
            # naive class hint based on nearby words
            lower = text.lower()
            idx = lower.find(mm)
            window = lower[max(0, idx-120): idx+120]
            clazz = None
            if "tanker" in window:
                clazz = "Tanker"
            elif "cargo" in window:
                clazz = "Cargo"
            rows.append({
                "mmsi": int(mm),
                "name": None,
                "class": clazz,
                "source": f"html:{Path(path).name}",
            })
    return rows

def merge_dedupe(*lists):
    merged = {}
    for lst in lists:
        for r in lst:
            m = int(r["mmsi"])
            prev = merged.get(m, {})
            merged[m] = {
                "mmsi": m,
                "name": r.get("name") or prev.get("name"),
                "class": r.get("class") or prev.get("class"),
                "source": (prev.get("source") or r.get("source")),
            }
    return list(merged.values())

def write_csv(rows):
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["mmsi","name","class","source"])
        w.writeheader()
        for r in rows:
            w.writerow(r)

def upsert_watchlist(rows, default_class=None):
    create_watchlist_if_needed()
    with _conn() as con:
        for r in rows:
            m = int(r["mmsi"])
            nm = r.get("name")
            cl = r.get("class") or default_class
            con.execute("INSERT OR IGNORE INTO watchlist(mmsi) VALUES (?)", (m,))
            con.execute("""
              UPDATE watchlist
                 SET name = COALESCE(?, name),
                     class = COALESCE(?, class)
               WHERE mmsi = ?
            """, (nm, cl, m))
        con.commit()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="db,seeds,html",
                    help="comma list: db,seeds,html")
    ap.add_argument("--class", dest="force_class", default=None,
                    help="Force class for entries lacking it (Cargo/Tanker/Other)")
    ap.add_argument("--only", dest="target_class", default=None,
                    help="Limit DB harvest to a class (Cargo/Tanker)")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    lists = []
    parts = [p.strip() for p in args.sources.split(",") if p.strip()]
    if "db" in parts:
        lists.append(from_db_ships(args.target_class))
    if "seeds" in parts:
        lists.append(from_seed_csvs())
    if "html" in parts:
        lists.append(from_saved_html())

    rows = merge_dedupe(*lists)
    if args.limit:
        rows = rows[: args.limit]

    write_csv(rows)
    print(f"[discover] wrote {len(rows)} to {OUT_CSV}")

    if not args.dry_run:
        upsert_watchlist(rows, default_class=args.force_class)
        print(f"[discover] upserted {len(rows)} rows into watchlist")
    else:
        print("[discover] dry-run: not updating watchlist")

if __name__ == "__main__":
    main()
