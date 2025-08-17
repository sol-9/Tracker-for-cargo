# windows\run_all.ps1
param(
  [string]$ProjectRoot = "C:\Users\metal\OneDrive\Documents\oil_tanker_tracker_v6_hybrid_full",
  [string]$ApiPort = "5050",
  [switch]$NoAIS = $false
)

function Launch($title, $cmd) {
  Start-Process powershell -ArgumentList "-NoExit","-Command","`$host.UI.RawUI.WindowTitle='$title'; cd '$ProjectRoot'; .\.venv\Scripts\Activate.ps1; `$env:PYTHONPATH=(Get-Location).Path; $cmd"
}

# 1) API (FastAPI) — adjust module/port if yours is different
Launch "API :$ApiPort" "uvicorn api.main:app --reload --host 0.0.0.0 --port $ApiPort"


# 4) Locator loop (poll your local API for positions of watchlist MMSIs)
Launch "Locator (loop)" "python scripts/locate_from_watchlist.py --base http://localhost:$ApiPort --loop --interval 180"

# 5) AISStream (optional) — comment this line out to disable
if (-not $NoAIS) {
  Launch "AISStream" "python scripts/ingest_stream_aisstream.py"
}

# 6) Dashboard
Launch "Dashboard" "python -m streamlit run streamlit_app.py"
