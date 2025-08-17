# streamlit_app.py
import time
from pathlib import Path
import sqlite3
import pandas as pd
import pydeck as pdk
import streamlit as st

DB_PATH = Path("tanker.db")
st.set_page_config(page_title="Oil & Cargo Ship Tracker — Live", layout="wide")

# ------------------------------------------------------------
# DB helpers & schema guards
# ------------------------------------------------------------
def conn():
    return sqlite3.connect(DB_PATH)

def ensure_watchlist_table():
    with conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            mmsi INTEGER PRIMARY KEY,
            name TEXT,
            class TEXT,             -- 'Cargo' | 'Tanker' | 'Other' | NULL
            favorite INTEGER DEFAULT 0
        )
        """)
        con.commit()

def load_tables():
    with conn() as con:
        try:
            ships = pd.read_sql_query("SELECT * FROM ships", con)
        except Exception:
            ships = pd.DataFrame(columns=["mmsi","imo","name","ship_type","dwt","max_draught","company","cargo"])
        try:
            pos = pd.read_sql_query(
                "SELECT mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source FROM positions", con
            )
        except Exception:
            pos = pd.DataFrame(columns=["mmsi","ts","lat","lon","sog","cog","heading","draught","nav_status","source"])
        try:
            wl = pd.read_sql_query("SELECT * FROM watchlist", con)
        except Exception:
            wl = pd.DataFrame(columns=["mmsi","name","class","favorite"])
    for df in (ships, pos, wl):
        if not df.empty and "mmsi" in df.columns:
            df["mmsi"] = pd.to_numeric(df["mmsi"], errors="coerce").astype("Int64")
    return ships, pos, wl

def upsert_watchlist_row(mmsi: int, name: str|None, clazz: str|None, favorite: int):
    with conn() as con:
        con.execute("INSERT OR IGNORE INTO watchlist(mmsi) VALUES(?)", (mmsi,))
        con.execute("""
            UPDATE watchlist SET
              name = COALESCE(?, name),
              class = COALESCE(?, class),
              favorite = COALESCE(?, favorite)
            WHERE mmsi = ?
        """, (name, clazz, favorite, mmsi))
        con.commit()

def delete_watchlist_rows(mmsis):
    if not mmsis: return
    with conn() as con:
        con.executemany("DELETE FROM watchlist WHERE mmsi = ?", [(int(m),) for m in mmsis])
        con.commit()

def insert_alert(ts, mmsi, kind, message):
    with conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS alerts(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          ts INTEGER, mmsi INTEGER, kind TEXT, message TEXT
        )""")
        con.execute("INSERT INTO alerts(ts, mmsi, kind, message) VALUES(?,?,?,?)", (ts, mmsi, kind, message))
        con.commit()

# ------------------------------------------------------------
# Sidebar controls (no scrapers started; just UI)
# ------------------------------------------------------------
ensure_watchlist_table()
st.sidebar.header("Controls")

if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
    st.rerun()

auto_refresh = st.sidebar.checkbox("Auto-refresh", value=False)
refresh_sec = st.sidebar.number_input("Every (seconds)", min_value=5, max_value=120, value=20) if auto_refresh else None

time_windows = {
    "Last 3 hours": 3 * 3600,
    "Last 6 hours": 6 * 3600,
    "Last 12 hours": 12 * 3600,
    "Last 24 hours": 24 * 3600,
    "Last 3 days": 3 * 86400,
    "All": None,
}
win_label = st.sidebar.selectbox("Time window", list(time_windows.keys()), index=2)
win_seconds = time_windows[win_label]

mode = st.sidebar.radio("Vessel class", ["All", "Cargo (70–79)", "Tanker (80–89)"], index=0)
track_watchlist_only = st.sidebar.checkbox("Track only watchlist", value=False)
favorites_only = st.sidebar.checkbox("Favorites only (from watchlist)", value=False)

st.sidebar.markdown("### Alert thresholds")
course_thresh = st.sidebar.slider("Course change (°) ≥", 5, 90, 25)
speed_drop = st.sidebar.slider("Speed drop (kn) ≥", 1, 15, 5)
stop_speed = st.sidebar.slider("Stop if SOG ≤", 0.0, 2.0, 0.5)

search_q = st.sidebar.text_input("Search (MMSI or name)").strip()

# ------------------------------------------------------------
# Load data (light cache)
# ------------------------------------------------------------
@st.cache_data(ttl=5)
def _load_cached():
    return load_tables()

ships, pos, watchlist = _load_cached()

if pos.empty:
    st.info("No positions yet. Keep your data source running, then press **Refresh now**.")
    st.stop()

# time filter
now_ts = int(time.time())
pos_win = pos.copy()
if win_seconds is not None:
    pos_win = pos_win[pos_win["ts"] >= now_ts - win_seconds]

# latest per MMSI + merge names/types
latest = pos_win.sort_values("ts").groupby("mmsi").tail(1).reset_index(drop=True)
if not ships.empty:
    latest = latest.merge(ships[["mmsi","name","ship_type"]], on="mmsi", how="left")

# vessel class filter
if mode != "All":
    want = "Cargo" if "Cargo" in mode else "Tanker"
    if "ship_type" in latest.columns:
        latest = latest[(latest["ship_type"] == want) | (~latest["ship_type"].notna())]
        pos_win = pos_win[pos_win["mmsi"].isin(latest["mmsi"].unique())]

# watchlist/favorites filters
if track_watchlist_only and not watchlist.empty:
    latest = latest[latest["mmsi"].isin(watchlist["mmsi"].unique())]
    pos_win = pos_win[pos_win["mmsi"].isin(latest["mmsi"].unique())]

if favorites_only and not watchlist.empty:
    favs = watchlist[watchlist["favorite"] == 1]["mmsi"].unique().tolist()
    latest = latest[latest["mmsi"].isin(favs)]
    pos_win  = pos_win[pos_win["mmsi"].isin(favs)]

# search
if search_q:
    if search_q.isdigit():
        want = int(search_q)
        latest = latest[latest["mmsi"] == want]
        pos_win = pos_win[pos_win["mmsi"] == want]
    else:
        if "name" in latest.columns:
            latest = latest[latest["name"].fillna("").str.contains(search_q, case=False)]
            pos_win = pos_win[pos_win["mmsi"].isin(latest["mmsi"].unique())]

if latest.empty:
    st.warning("No ships match the current filters.")
    st.stop()

# ------------------------------------------------------------
# Colors & legend (SAFE)
# ------------------------------------------------------------
COLOR_TANKER   = [220, 60, 60, 170]
COLOR_CARGO    = [60, 120, 230, 170]
COLOR_OTHER    = [150, 150, 150, 140]
COLOR_FAVORITE = [255, 215, 0, 210]

try:
    fav_set = set(
        watchlist.loc[(watchlist["favorite"] == 1) & watchlist["mmsi"].notna(), "mmsi"]
        .astype("Int64").dropna().astype(int).tolist()
    )
except Exception:
    fav_set = set()

def classify_ship_type(val):
    if isinstance(val, str):
        s = val.strip().lower()
        if "tanker" in s: return "tanker"
        if "cargo" in s:  return "cargo"
        return "other"
    try:
        t = int(val)
        if 80 <= t <= 89: return "tanker"
        if 70 <= t <= 79: return "cargo"
    except Exception:
        pass
    return "other"

def _assign_color(row):
    try:
        m = int(row["mmsi"])
    except Exception:
        m = 0
    if m in fav_set:
        return COLOR_FAVORITE
    stype = classify_ship_type(row.get("ship_type"))
    if stype == "tanker": return COLOR_TANKER
    if stype == "cargo":  return COLOR_CARGO
    return COLOR_OTHER

latest_plot = latest.copy()
for c in ["lat", "lon", "sog", "cog"]:
    if c in latest_plot.columns:
        latest_plot[c] = pd.to_numeric(latest_plot[c], errors="coerce")
latest_plot["color"] = latest_plot.apply(_assign_color, axis=1)

# ---------- Build path polylines SAFELY ----------
pos_for_paths = (
    pos_win[["mmsi", "ts", "lon", "lat"]]
    .dropna()
    .sort_values(["mmsi", "ts"])
)
if pos_for_paths.empty:
    pathdf = pd.DataFrame({"mmsi": pd.Series(dtype="Int64"), "path": pd.Series(dtype="object")})
else:
    pathdf = (
        pos_for_paths
        .groupby("mmsi")[["lon", "lat"]]
        .apply(lambda d: d.values.tolist())
        .reset_index(name="path")
    )
track_df = pathdf.merge(
    latest_plot[["mmsi", "name", "ship_type"]], on="mmsi", how="left"
)

# ------------------------------------------------------------
# Tabs
# ------------------------------------------------------------
tab_map, tab_notif, tab_explorer, tab_watch = st.tabs(["🗺️ Map", "🔔 Notifications", "🔎 Explorer", "⭐ Watchlist"])

# persistent focus state (for clicking alerts -> center map)
if "focus" not in st.session_state:
    st.session_state["focus"] = None  # dict(lat, lon, mmsi) or None

# ---------------- MAP TAB ----------------
with tab_map:
    st.title("🛢️ Oil & 🚢 Cargo Ship Tracker — Live")

    # if an alert set focus, center and draw a highlight ring
    focus = st.session_state.get("focus")
    if focus:
        center_lat, center_lon = float(focus["lat"]), float(focus["lon"])
        zoom = 7
    else:
        try:
            center_lat = float(latest_plot["lat"].mean())
            center_lon = float(latest_plot["lon"].mean())
            if not (center_lat == center_lat) or not (center_lon == center_lon):
                raise ValueError
        except Exception:
            center_lat, center_lon = 20.0, 0.0
        zoom = 3

    view = pdk.ViewState(latitude=center_lat, longitude=center_lon, zoom=zoom)

    tooltip = {
        "html": (
            "MMSI <b>{mmsi}</b><br/>"
            "Name <b>{name}</b><br/>"
            "Type <b>{ship_type}</b><br/>"
            "SOG <b>{sog}</b> kn<br/>"
            "COG <b>{cog}</b>°<br/>"
            "Source <b>{source}</b><br/>"
            "TS <b>{ts}</b>"
        ),
        "style": {"color": "white"},
    }

    layer_lines = pdk.Layer(
        "PathLayer",
        data=track_df,
        get_path="path",
        width_scale=1,
        width_min_pixels=2,
        get_width=3,
        pickable=True,
    )
    layer_points = pdk.Layer(
        "ScatterplotLayer",
        data=latest_plot,
        get_position="[lon, lat]",
        get_radius=25000,
        pickable=True,
        get_fill_color="color",
    )

    layers = [layer_lines, layer_points]

    # If focusing a specific alert, render a highlight ring on top
    if focus:
        layers.append(
            pdk.Layer(
                "ScatterplotLayer",
                data=[{"lon": center_lon, "lat": center_lat}],
                get_position="[lon, lat]",
                get_radius=60000,
                get_fill_color=[255, 0, 0, 0],
                get_line_color=[255, 80, 80, 220],
                line_width_min_pixels=3,
                stroked=True,
            )
        )

    left, right = st.columns([4,1])
    with left:
        st.pydeck_chart(
            pdk.Deck(
                layers=layers,
                initial_view_state=view,
                tooltip=tooltip,
                map_style=None,
            ),
            use_container_width=True,
        )
    with right:
        st.markdown("**Legend**")
        st.markdown(
            """
            <div style="line-height:1.8">
            <span style="background:rgba(220,60,60,0.8);padding:3px 8px;border-radius:8px"></span> Tanker<br/>
            <span style="background:rgba(60,120,230,0.8);padding:3px 8px;border-radius:8px"></span> Cargo<br/>
            <span style="background:rgba(150,150,150,0.8);padding:3px 8px;border-radius:8px"></span> Other/Unknown<br/>
            <span style="background:rgba(255,215,0,0.9);padding:3px 8px;border-radius:8px"></span> Favorite (watchlist)
            </div>
            """,
            unsafe_allow_html=True,
        )

# ---------------- NOTIFICATIONS TAB ----------------
with tab_notif:
    st.header("🔔 Notification Center")

    # Build alerts for **current time window**
    alerts = []
    for mmsi, grp in pos_win.sort_values("ts").groupby("mmsi"):
        if len(grp) < 2: 
            continue
        last = grp.iloc[-1]; prev = grp.iloc[-2]
        try:
            sog_now = float(last["sog"]) if pd.notna(last["sog"]) else None
            sog_prev = float(prev["sog"]) if pd.notna(prev["sog"]) else None
            cog_now = float(last["cog"]) if pd.notna(last["cog"]) else None
            cog_prev = float(prev["cog"]) if pd.notna(prev["cog"]) else None
        except Exception:
            continue

        # Course change
        if cog_now is not None and cog_prev is not None:
            dcog = abs((cog_now - cog_prev + 180) % 360 - 180)
            if dcog >= course_thresh:
                alerts.append({"ts": int(last["ts"]), "mmsi": int(mmsi), "kind": "Course change",
                               "value": round(dcog,1), "lat": last["lat"], "lon": last["lon"]})

        # Speed drop
        if sog_now is not None and sog_prev is not None:
            if (sog_prev - sog_now) >= float(speed_drop):
                alerts.append({"ts": int(last["ts"]), "mmsi": int(mmsi), "kind": "Speed drop",
                               "value": round(sog_prev - sog_now,1), "lat": last["lat"], "lon": last["lon"]})

        # Stop
        if sog_now is not None and sog_now <= float(stop_speed):
            alerts.append({"ts": int(last["ts"]), "mmsi": int(mmsi), "kind": "Stop",
                           "value": round(sog_now,1), "lat": last["lat"], "lon": last["lon"]})

    if alerts:
        adf = pd.DataFrame(alerts).sort_values("ts", ascending=False).reset_index(drop=True)
        st.dataframe(adf, use_container_width=True, height=360)
        # Selector to focus the map on an alert
        choices = [f"{i}: {row.kind} • MMSI {row.mmsi} • Δ={row.value} @ {row.lat:.3f},{row.lon:.3f}" 
                   for i, row in adf.iterrows()]
        idx = st.selectbox("Focus on alert (centers the Map tab):", options=list(range(len(choices))), 
                           format_func=lambda i: choices[i] if choices else "", index=0)
        if st.button("Focus on Map"):
            row = adf.iloc[idx]
            st.session_state["focus"] = {"lat": float(row["lat"]), "lon": float(row["lon"]), "mmsi": int(row["mmsi"])}
            st.success("Centered map on selected alert. Switch to the **Map** tab.")
            # persist (optional)
            for a in adf.head(50).itertuples():
                insert_alert(int(a.ts), int(a.mmsi), str(a.kind), f"{a.kind} value={a.value} at {a.lat},{a.lon}")
    else:
        st.info("No alerts in the selected window with current thresholds.")

# ---------------- EXPLORER TAB ----------------
with tab_explorer:
    st.header("🔎 Ship Explorer")
    show_cols = [c for c in ["mmsi","name","ts","lat","lon","sog","cog","ship_type","source"] if c in latest_plot.columns]
    st.dataframe(latest_plot.sort_values("ts", ascending=False)[show_cols].head(500),
                 use_container_width=True, height=420)

    mmsis = latest_plot.sort_values("ts", ascending=False)["mmsi"].astype("Int64").astype(str).unique().tolist()
    pick = st.selectbox("Select MMSI for recent track", mmsis, index=0 if mmsis else None)
    if pick:
        m = int(pick)
        recent = pos_win[pos_win["mmsi"] == m].sort_values("ts", ascending=False).head(500).reset_index(drop=True)
        st.dataframe(recent, use_container_width=True)

# ---------------- WATCHLIST TAB ----------------
with tab_watch:
    st.header("⭐ Watchlist manager")
    wl_cols = ["mmsi","name","class","favorite"]
    if watchlist.empty:
        st.info("Watchlist is empty. Add ships below.")
    else:
        show = watchlist[wl_cols].sort_values("favorite", ascending=False)
        st.dataframe(show, use_container_width=True, height=360)

    with st.expander("Add or update a single ship"):
        c1, c2, c3, c4 = st.columns([1,2,1,1])
        mmsi_in = c1.text_input("MMSI", value="", key="wl_mmsi")
        name_in = c2.text_input("Name (optional)", value="", key="wl_name")
        clazz_in = c3.selectbox("Class", ["Auto", "Cargo", "Tanker", "Other"], index=0, key="wl_class")
        fav_in = c4.checkbox("Favorite", value=False, key="wl_fav")
        if st.button("Save to watchlist"):
            try:
                m = int(mmsi_in)
                inferred = None
                if clazz_in == "Auto":
                    row = ships[ships["mmsi"] == m]
                    if not row.empty:
                        inferred = row["ship_type"].iloc[0]
                final_class = inferred if inferred else (None if clazz_in == "Auto" else clazz_in)
                upsert_watchlist_row(m, name_in.strip() or None, final_class, 1 if fav_in else 0)
                st.success(f"Saved MMSI {m} to watchlist.")
                st.cache_data.clear(); st.rerun()
            except Exception as e:
                st.error(f"Failed to save: {e}")

    with st.expander("Bulk import MMSIs (one per line)"):
        bulk = st.text_area("Paste MMSIs here", height=120, key="wl_bulk_text")
        clazz_bulk = st.selectbox("Assign class to all", ["Auto", "Cargo", "Tanker", "Other"], index=0, key="wl_bulk_class")
        fav_bulk = st.checkbox("Mark all as favorite", value=False, key="wl_bulk_fav")
        if st.button("Import list"):
            count = 0
            for line in bulk.splitlines():
                t = line.strip()
                if not t or not t.isdigit(): 
                    continue
                m = int(t)
                inferred = None
                if clazz_bulk == "Auto":
                    row = ships[ships["mmsi"] == m]
                    if not row.empty:
                        inferred = row["ship_type"].iloc[0]
                final_class = inferred if inferred else (None if clazz_bulk == "Auto" else clazz_bulk)
                upsert_watchlist_row(m, None, final_class, 1 if fav_bulk else 0)
                count += 1
            st.success(f"Imported {count} MMSIs.")
            st.cache_data.clear(); st.rerun()

    with st.expander("Delete from watchlist"):
        if watchlist.empty:
            st.write("Watchlist is empty.")
        else:
            sel = st.multiselect("Select MMSIs to delete", watchlist["mmsi"].astype(str).tolist())
            if st.button("Delete selected"):
                try:
                    delete_watchlist_rows([int(x) for x in sel])
                    st.success(f"Deleted {len(sel)} entries.")
                    st.cache_data.clear(); st.rerun()
                except Exception as e:
                    st.error(f"Delete failed: {e}")

# Auto-refresh (optional)
if auto_refresh:
    st.caption(f"Auto-refreshing every {int(refresh_sec)}s …")
    time.sleep(int(refresh_sec))
    st.cache_data.clear()
    st.rerun()
