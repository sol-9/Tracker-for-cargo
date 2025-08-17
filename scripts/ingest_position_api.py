import time, requests, yaml
from urllib.parse import urljoin
from src.db import init_db, get_conn

if __name__ == "__main__":
    init_db()
    cfg = yaml.safe_load(open("config.yaml"))
    lp = cfg.get("local_api", {})
    base = lp.get("base_url", "http://localhost:5050")
    tmpl = lp.get("path_template", "/location/{mmsi}")
    poll_s = int(lp.get("poll_seconds", 60))
    watch = cfg.get("watchlist") or []
    if not watch:
        print("No MMSIs in watchlist. Edit config.yaml"); raise SystemExit(0)
    print(f"[ingest_api] polling {len(watch)} MMSIs every {poll_s}s from {base}")
    while True:
        t0 = time.time()
        for m in watch:
            try:
                url = urljoin(base, tmpl.format(mmsi=m).lstrip("/"))
                r = requests.get(url, timeout=15)
                if r.status_code != 200:
                    print("[ingest_api]", m, "HTTP", r.status_code); continue
                d = r.json()
                ts = int(d.get("timestamp", time.time()))
                lat = float(d.get("latitude")); lon = float(d.get("longitude"))
                sog = d.get("speed"); cog = d.get("course"); src = d.get("source", "local_api")
                con = get_conn()
                con.execute("INSERT OR IGNORE INTO ships(mmsi) VALUES(?)", (m,))
                con.execute("""INSERT OR IGNORE INTO positions
                    (mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""", (m, ts, lat, lon, sog, cog, None, None, None, src))
                con.commit(); con.close()
                print("[ingest_api] stored", m, ts, lat, lon, src)
            except Exception as e:
                print("[ingest_api] error", m, e)
        dt = time.time()-t0
        time.sleep(max(1.0, poll_s - dt))
