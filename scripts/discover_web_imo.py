# scripts/discover_web_imo.py
import re, time
from pathlib import Path
import requests
import pandas as pd
from bs4 import BeautifulSoup

OUT = Path("data/discovered_imo.csv")
OUT.parent.mkdir(parents=True, exist_ok=True)

IMO_RE = re.compile(r"\bIMO\s?(\d{7})\b", re.I)

SITES = [
    # Wikipedia pages that list tankers / cargo ships
    "https://en.wikipedia.org/wiki/List_of_oil_tankers",
    "https://en.wikipedia.org/wiki/List_of_LNG_tankers",
    "https://en.wikipedia.org/wiki/List_of_container_ships",
    "https://en.wikipedia.org/wiki/List_of_bulk_carriers",
]

HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) IMO-Discover/0.1"}

def scrape(url):
    r = requests.get(url, headers=HDRS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ")
    imos = set(m for m in IMO_RE.findall(text))
    # also scan table cells that say “IMO: 9xxxxx”
    for td in soup.select("td, li, p"):
        t = td.get_text(" ", strip=True)
        for m in IMO_RE.findall(t):
            imos.add(m)
    return sorted(imos)

def main():
    all_imo = set()
    for url in SITES:
        print(f"[discover-imo] {url}")
        try:
            found = scrape(url)
            print(f"  + {len(found)} IMOs")
            all_imo.update(found)
        except Exception as e:
            print(f"  ! error: {e}")
        time.sleep(1.2)  # be polite

    df = pd.DataFrame({"imo": sorted(all_imo)})
    df.to_csv(OUT, index=False)
    print(f"[discover-imo] wrote {len(df)} to {OUT}")

if __name__ == "__main__":
    main()
