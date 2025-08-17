import time, sqlite3
from pathlib import Path
import requests
from bs4 import BeautifulSoup
import yaml
from src.db import ensure_tables

DB_PATH = Path(__file__).resolve().parents[1] / "tanker.db"
CFG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

def _cfg():
    return yaml.safe_load(open(CFG_PATH, "r", encoding="utf-8"))

def _insert(mmsi, lat, lon):
    con = sqlite3.connect(DB_PATH)
    ensure_tables(con)
    con.execute("INSERT OR IGNORE INTO ships(mmsi, ship_type) VALUES(?,?)", (mmsi, "Tanker"))
    con.execute("""INSERT OR IGNORE INTO positions
        (mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source)
        VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (mmsi, int(time.time()), float(lat), float(lon), None, None, None, None, None, "vesselfinder"))
    con.commit(); con.close()

def scrape_ship(mmsi: int):
    url = f"https://www.vesselfinder.com/vessels?mmsi={mmsi}"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code != 200:
            print(f"[vesselfinder] {mmsi} HTTP {r.status_code}")
            return False
        soup = BeautifulSoup(r.text, "lxml")
        # Attempt 1: map_canvas data attributes
        div = soup.find("div", id="map_canvas")
        if div and div.has_attr("data-lat") and div.has_attr("data-lon"):
            lat = div["data-lat"]; lon = div["data-lon"]
            _insert(mmsi, lat, lon); print(f"[vesselfinder] {mmsi} -> {lat},{lon}")
            return True
        # Attempt 2: meta tags fallback
        mlat = soup.find("meta", attrs={"property": "vf:lat"}) or soup.find("meta", attrs={"name": "vf:lat"})
        mlon = soup.find("meta", attrs={"property": "vf:lon"}) or soup.find("meta", attrs={"name": "vf:lon"})
        if mlat and mlon and mlat.get("content") and mlon.get("content"):
            _insert(mmsi, mlat["content"], mlon["content"]); print(f"[vesselfinder] {mmsi} -> {mlat['content']},{mlon['content']}")
            return True
        print(f"[vesselfinder] {mmsi} no coords found")
        return False
    except Exception as e:
        print(f"[vesselfinder] {mmsi} error {e}")
        return False

def run_loop():
    cfg = _cfg()
    watch = cfg.get("watchlist") or []
    if not watch:
        print("[vesselfinder] empty watchlist"); return
    for m in watch:
        try:
            scrape_ship(int(m))
        except Exception as e:
            print("[vesselfinder] error on", m, e)
        time.sleep(5)
