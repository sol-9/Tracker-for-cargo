import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parents[1] / "tanker.db"

SCHEMA = '''
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS ships(
  mmsi INTEGER PRIMARY KEY,
  imo INTEGER,
  name TEXT,
  ship_type TEXT,
  dwt REAL,
  max_draught REAL,
  company TEXT,
  cargo TEXT
);
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mmsi INTEGER, ts INTEGER, lat REAL, lon REAL,
  sog REAL, cog REAL, heading REAL, draught REAL, nav_status TEXT,
  source TEXT,
  UNIQUE(mmsi, ts, source)
);
CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts ON positions(mmsi, ts);
CREATE TABLE IF NOT EXISTS alerts(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER, mmsi INTEGER, kind TEXT, message TEXT
);
'''

def get_conn():
  return sqlite3.connect(DB_PATH)

def init_db():
  con = get_conn(); cur = con.cursor()
  cur.executescript(SCHEMA); con.commit(); con.close()

def ensure_tables(con):
  con.executescript(SCHEMA); con.commit()
