# scripts/force_class_nulls.py
import argparse
import sqlite3
from pathlib import Path

DB_PATH = Path("tanker.db")

def force_class(clazz: str):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        # Only update rows where class is NULL
        cur.execute("UPDATE watchlist SET class = ? WHERE class IS NULL", (clazz,))
        con.commit()
        print(f"[force] updated {cur.rowcount} rows to class={clazz}")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--class", dest="clazz", choices=["Cargo","Tanker","Other"], required=True,
                   help="Class to assign to all NULL entries in watchlist")
    args = p.parse_args()
    force_class(args.clazz)
