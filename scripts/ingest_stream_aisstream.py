# scripts/ingest_stream_aisstream.py
import os, yaml
from dotenv import load_dotenv
from src.db import init_db
from src.ingest.aisstream_ws import run_aisstream

if __name__ == "__main__":
    load_dotenv()
    init_db()
    api_key = os.getenv("AISSTREAM_API_KEY")
    if not api_key:
        raise RuntimeError("Set AISSTREAM_API_KEY in .env")
    # optional: read tanker_only from config if you want
    try:
        cfg = yaml.safe_load(open("config.yaml"))
        tanker_only = bool(cfg.get("ui", {}).get("tanker_only", True))
    except Exception:
        tanker_only = True
    run_aisstream(api_key, tanker_only=tanker_only)
