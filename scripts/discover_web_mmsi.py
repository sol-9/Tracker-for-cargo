# scripts/discover_web_mmsi.py
import argparse, re, time, random, os
from pathlib import Path
import sqlite3
import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
DB   = ROOT / "tanker.db"
DATA = ROOT / "data"
OUT_CSV = DATA / "web_discovered_mmsi.csv"
DATA.mkdir(exist_ok=True)

MMSI_RE = re.compile(r"\b([2-7]\d{8})\b")  # 9 digits, starting 2–7 typically

# Basic keywords to bias toward commercial cargo/tankers
TANKER_WORDS = {"tanker","vlcc","suezmax","aframax","lr1","lr2","mr tanker","oil","crude","lng","lpg","chem","product tanker"}
CARGO_WORDS  = {"cargo","bulk","bulker","container","feeder","handymax","panamax","kamsarmax","cape","ro-ro","general cargo","boxship"}

# --- DB utils ---
def _conn():
    return sqlite3.connect(DB)

def ensure_watchlist():
    with _conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist(
          mmsi INTEGER PRIMARY KEY,
          name TEXT,
          class TEXT,        -- 'Cargo' | 'Tanker' | 'Other' | NULL
          favorite INTEGER DEFAULT 0
        )""")
        con.commit()

def upsert_watchlist(rows):
    with _conn() as con:
        cur = con.cursor()
        for r in rows:
            m = int(r["mmsi"])
            nm = r.get("name")
            cl = r.get("clazz")
            cur.execute("INSERT OR IGNORE INTO watchlist(mmsi) VALUES (?)", (m,))
            cur.execute("UPDATE watchlist SET name = COALESCE(?,name) WHERE mmsi = ?", (nm, m))
            if cl:
                cur.execute("UPDATE watchlist SET class = COALESCE(?,class) WHERE mmsi = ?", (cl, m))
        con.commit()

# --- classification helpers ---
def classify_text(snippet: str):
    s = (snippet or "").lower()
    t_hits = sum(1 for w in TANKER_WORDS if w in s)
    c_hits = sum(1 for w in CARGO_WORDS if w in s)
    if t_hits > c_hits and t_hits > 0:
        return "Tanker"
    if c_hits > t_hits and c_hits > 0:
        return "Cargo"
    return None

def maybe_ai_classify(snippet: str):
    """
    Optional: if OPENAI_API_KEY is set, ask the model to label as Tanker/Cargo/Other.
    We keep it simple; if no key, return None.
    """
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return None
    try:
        # lazy import to avoid dependency if unused
        import json, requests
        prompt = f"Label this vessel text strictly as one word: Tanker, Cargo, or Other.\nText:\n{snippet[:1200]}"
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}","Content-Type":"application/json"},
            json={
                "model":"gpt-4o-mini",
                "messages":[{"role":"user","content":prompt}],
                "temperature":0
            },
            timeout=20
        )
        out = resp.json()
        label = out["choices"][0]["message"]["content"].strip().split()[0].capitalize()
        if label in ("Tanker","Cargo","Other"):
            return label
    except Exception:
        return None
    return None

# --- fetchers ---
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ShipDiscoveryBot/0.1 (+for research; contact: local)"
}

def search_duckduckgo(query: str, max_results=30):
    """
    Use DDG HTML (lite) to avoid API keys.
    """
    params = {"q": query, "kl": "us-en"}
    r = httpx.get(
        "https://html.duckduckgo.com/html/",   # <-- FIXED
        params=params,
        headers=HEADERS,
        timeout=20,
        follow_redirects=True                  # <-- ALLOW REDIRECTS
    )
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    links = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if not href:
            continue
        links.append(href)
        if len(links) >= max_results:
            break
    return links


def fetch_page(url: str):
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        if r.status_code >= 400:
            return None
        return r.text
    except Exception:
        return None

def extract_mmsi_and_name(html: str):
    """
    Return list of dicts: {mmsi:int, name:str|None, snippet:str}
    We regex MMSI; for name, try cheap patterns around 'Name:' or <title>.
    """
    out = []
    if not html:
        return out
    # MMSIs
    hits = list(dict.fromkeys(MMSI_RE.findall(html)))  # unique preserve order
    if not hits:
        return out

    # crude name extraction: look for "Name" or "Vessel" lines near the match; fallback to title
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.text.strip() if soup.title and soup.title.text else ""
    text = soup.get_text("\n", strip=False)

    for m in hits:
        name = None
        # local window
        idx = text.find(m)
        if idx >= 0:
            window = text[max(0, idx-200): idx+200]
            # Common patterns
            for pat in [r"Name[:\s]+([A-Z0-9\-\s]{3,40})",
                        r"Vessel\s*name[:\s]+([A-Z0-9\-\s]{3,40})",
                        r"Ship\s*name[:\s]+([A-Z0-9\-\s]{3,40})"]:
                mm = re.search(pat, window, flags=re.I)
                if mm:
                    name = mm.group(1).strip()
                    break
        if not name:
            # try title slice
            mm = re.search(r"([A-Z0-9][A-Z0-9\-\s]{2,40})", title, flags=re.I)
            if mm:
                name = mm.group(1).strip()
        # snippet for classification
        snip = text[max(0, idx-350): idx+350] if idx >= 0 else text[:600]
        out.append({"mmsi": int(m), "name": name, "snippet": snip})
    return out

def run_discovery(queries, max_links, per_site_delay, use_ai):
    discovered = {}
    for q in queries:
        print(f"[discover] searching: {q}")
        urls = search_duckduckgo(q, max_results=max_links)
        for u in urls:
            # avoid hammering the same host
            time.sleep(per_site_delay + random.random()*0.5)
            html = fetch_page(u)
            if not html:
                continue
            for rec in extract_mmsi_and_name(html):
                m = rec["mmsi"]
                prev = discovered.get(m, {})
                # merge
                name = prev.get("name") or rec.get("name")
                # classify
                guess = classify_text(rec["snippet"])
                if use_ai and not guess:
                    guess = maybe_ai_classify(rec["snippet"])
                discovered[m] = {
                    "mmsi": m,
                    "name": name,
                    "clazz": guess or prev.get("clazz"),
                    "source": "web",
                }
    return list(discovered.values())

def write_csv(rows):
    import csv
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["mmsi","name","class","source"])
        w.writeheader()
        for r in rows:
            w.writerow({"mmsi": r["mmsi"], "name": r.get("name"), "class": r.get("clazz"), "source": r.get("source")})

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-links", type=int, default=30, help="Max search results per query")
    ap.add_argument("--delay", type=float, default=1.0, help="Seconds delay between page fetches")
    ap.add_argument("--use-ai", action="store_true", help="Use OPENAI_API_KEY to improve classification")
    ap.add_argument("--tankers", action="store_true", help="Bias queries toward tankers")
    ap.add_argument("--cargo", action="store_true", help="Bias queries toward cargo")
    args = ap.parse_args()

    # Build query set
    base = [
        "site:twitter.com MMSI tanker",
        "MMSI oil tanker list",
        "MMSI VLCC",
        "MMSI Aframax",
        "MMSI Suezmax",
        "MMSI LNG tanker",
        "MMSI LPG tanker",
        "MMSI product tanker",
        "MMSI crude tanker",
        "MMSI bulk carrier",
        "MMSI container ship",
        "MMSI general cargo ship",
    ]
    if args.tankers and not args.cargo:
        base = [q for q in base if "tanker" in q.lower() or "vlcc" in q.lower() or "suezmax" in q.lower() or "aframax" in q.lower()]
    if args.cargo and not args.tankers:
        base = [q for q in base if "cargo" in q.lower() or "container" in q.lower() or "bulk" in q.lower()]

    ensure_watchlist()
    rows = run_discovery(base, max_links=args.max_links, per_site_delay=args.delay, use_ai=args.use_ai)
    print(f"[discover] candidates: {len(rows)}")
    write_csv(rows)

    # Upsert to watchlist
    # Only write class if we have a clear guess; otherwise leave NULL
    upsert_watchlist(rows)
    # quick summary
    with _conn() as con:
        print("[watchlist] counts by class:",
              con.execute("SELECT COALESCE(class,'(NULL)'), COUNT(*) FROM watchlist GROUP BY class").fetchall())

if __name__ == "__main__":
    main()
