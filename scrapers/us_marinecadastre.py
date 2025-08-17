import pandas as pd, sqlite3, time, glob, os
from pathlib import Path
from src.db import ensure_tables

DB_PATH = Path(__file__).resolve().parents[1] / "tanker.db"

def ingest_folder(folder="data/us_ais"):
    paths = glob.glob(os.path.join(folder, "*.csv"))
    if not paths:
        print("[us_mc] no CSVs in", folder); return
    con = sqlite3.connect(DB_PATH); ensure_tables(con)
    for p in paths:
        try:
            print("[us_mc] ingesting", p)
            df = pd.read_csv(p)
            rename = {"MMSI":"mmsi","LAT":"lat","LON":"lon","BaseDateTime":"ts","SOG":"sog","COG":"cog"}
            df = df.rename(columns={k:v for k,v in rename.items() if k in df.columns})
            if "ts" in df.columns:
                try:
                    df["ts"] = pd.to_datetime(df["ts"]).astype("int64")//10**9
                except Exception:
                    df["ts"] = int(time.time())
            else:
                df["ts"] = int(time.time())
            keep = ["mmsi","ts","lat","lon","sog","cog"]
            for k in keep:
                if k not in df.columns: df[k] = None
            out = df[keep].copy()
            out["heading"]=None; out["draught"]=None; out["nav_status"]=None; out["source"]="us_csv"
            out.to_sql("positions", con, if_exists="append", index=False)
        except Exception as e:
            print("[us_mc] failed", p, e)
    con.close(); print("[us_mc] done")
