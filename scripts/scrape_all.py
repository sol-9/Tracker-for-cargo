import time, yaml
from pathlib import Path
from src.db import init_db

CFG_PATH = Path(__file__).resolve().parents[1] / "config.yaml"

def cfg():
    return yaml.safe_load(open(CFG_PATH, "r", encoding="utf-8"))

def run_once():
    c = cfg()
    scr = c.get("scrapers", {})
    if scr.get("vesselfinder", False):
        import scrapers.vesselfinder as vf
        vf.run_loop()
    if scr.get("us_marinecadastre", False):
        import scrapers.us_marinecadastre as usmc
        usmc.ingest_folder("data/us_ais")

if __name__ == "__main__":
    init_db()
    while True:
        run_once()
        time.sleep(300)
