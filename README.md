🚢 Oil & Cargo Ship Tracker — Hybrid AIS + Web

This project tracks **oil tankers and cargo ships worldwide** by combining:

* **AIS live streams** (via [AISStream.io](https://aisstream.io))
* **Web scrapers** to discover MMSI/IMO numbers and ship details
* **Local database & watchlist** for long-term tracking
* **Interactive dashboard** (Streamlit) with maps, alerts, and notifications

The goal: give traders, analysts, and researchers a **real-time edge** by detecting unusual vessel activity before markets react.

---

## ✨ Features

* **Live AIS tracking** (global bounding box, filter by cargo/tanker)
* **Web scrapers** to enrich MMSI/IMO data from public sources
* **Watchlist manager** (bulk import/export, favorites, auto-classification)
* **Notifications** when ships stop, slow, or change course
* **Multi-tab dashboard** (map, alerts, ship explorer, watchlist)
* **Color-coded map** (tankers, cargo, others, favorites)
* **SQLite database** for persistence across runs

---

## 📂 Project Structure

```
oil_tanker_tracker_v6_hybrid_full/
├── streamlit_app.py            # Main UI dashboard
├── scripts/
│   ├── ingest_stream_aisstream.py  # Connect to AISStream websocket
│   ├── discover_mmsi.py            # Discover MMSI from seeds/db/html
│   ├── discover_web_mmsi.py        # Crawl/search web for MMSI/IMO
│   ├── backfill_watchlist_class.py # Infer ship class when missing
│   └── run_all.py                  # Launches API + scrapers + dashboard
├── tanker.db                   # SQLite database (auto-created)
├── data/
│   └── discovered_mmsi.csv      # Saved MMSI discoveries
└── README.md
```

---

## 🚀 Quick Start

### 1. Clone and install

```bash
git clone https://github.com/yourname/oil_tanker_tracker.git
cd oil_tanker_tracker
python -m venv .venv
source .venv/bin/activate   # (Linux/Mac)
.venv\Scripts\Activate.ps1  # (Windows)
pip install -r requirements.txt
```

### 2. Add API key

Create a `.env` file in the project root:

```
AISSTREAM_API_KEY=your_key_here
```

### 3. Run everything with one command

```bash
python scripts/run_all.py
```

This will:
✅ Connect to AISStream
✅ Run scrapers in background
✅ Launch Streamlit dashboard at `http://localhost:8501`

---

## 🗺️ Dashboard

* **Map view**: live tanker/cargo positions
* **Notification Center**: see sudden stops, course changes, speed drops
* **Ship Explorer**: drill down into historical track per vessel
* **Watchlist**: manage tracked MMSIs (manual or bulk import)

---

## ⚡ Roadmap

* [ ] Improve IMO/MMSI enrichment with AI-powered scrapers
* [ ] Add historical CSV backfill
* [ ] Add Telegram/Discord alerts
* [ ] Integration with financial data feeds

---

## ⚖️ Disclaimer

This project is for **research and educational purposes only**.
Do not use it for navigation or safety-critical operations.


