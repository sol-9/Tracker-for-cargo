from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import sqlite3, time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "tanker.db"
app = FastAPI(title="Local Meta AIS API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

def _con():
    return sqlite3.connect(DB_PATH)

@app.get("/health")
def health():
    return {"ok": True, "db_exists": DB_PATH.exists()}

@app.get("/location/{mmsi}")
def location(mmsi: int):
    con = _con(); cur = con.cursor()
    cur.execute("SELECT ts, lat, lon, sog, cog, source FROM positions WHERE mmsi=? ORDER BY ts DESC LIMIT 1", (mmsi,))
    row = cur.fetchone(); con.close()
    if not row: raise HTTPException(404, "No position found")
    ts, lat, lon, sog, cog, src = row
    return {"mmsi": mmsi, "timestamp": ts, "latitude": lat, "longitude": lon, "speed": sog, "course": cog, "source": src}

@app.get("/history/{mmsi}")
def history(mmsi: int, limit: int = 200):
    con = _con(); cur = con.cursor()
    cur.execute("SELECT ts, lat, lon, sog, cog, source FROM positions WHERE mmsi=? ORDER BY ts DESC LIMIT ?", (mmsi, limit))
    rows = cur.fetchall(); con.close()
    return [{"ts": r[0], "lat": r[1], "lon": r[2], "sog": r[3], "cog": r[4], "source": r[5]} for r in rows]
