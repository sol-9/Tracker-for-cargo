# src/ingest/aisstream_ws.py
import json, time, traceback
from websocket import create_connection, WebSocketConnectionClosedException
from ..db import get_conn, ensure_tables

# World-ish box (docs require lat,lon corner pairs)
WORLD_BBOX = [[[-85.0, -179.9], [85.0, 179.9]]]

def _subscribe_payload(api_key, bbox, mmsi_list=None):
    p = {
        "APIKey": api_key,
        "BoundingBoxes": bbox,
        # Keep traffic manageable; you can remove this to get all types
        "FilterMessageTypes": ["PositionReport"],
    }
    if mmsi_list:
        # Up to 50 MMSIs (strings)
        p["FiltersShipMMSI"] = [str(x) for x in mmsi_list][:50]
    return p

def run_aisstream(api_key: str, tanker_only: bool = True, watch_mmsi=None):
    """AISStream client matching official docs: key in payload + required BoundingBoxes."""
    backoff = 5
    url = "wss://stream.aisstream.io/v0/stream"
    while True:
        ws = None
        try:
            print(f"[AISStream] Connecting to {url} …")
            # Keep pings so the server sees us alive
            ws = create_connection(url, timeout=30, ping_interval=25, ping_timeout=10)

            # Send subscription payload WITHIN 3 SECONDS (docs requirement)
            sub = _subscribe_payload(api_key, WORLD_BBOX, watch_mmsi)
            ws.send(json.dumps(sub))
            print("[AISStream] Sent subscription:", sub)
            print("[AISStream] Subscribed. Receiving messages…")

            conn = get_conn(); ensure_tables(conn)
            backoff = 5

            while True:
                try:
                    msg = ws.recv()
                    print("[AISStream][RAW]", msg)
                except WebSocketConnectionClosedException:
                    raise

                if not msg:
                    continue

                # Error frames per docs are JSON with {"error": "..."}
                try:
                    obj = json.loads(msg)
                except Exception:
                    continue

                if isinstance(obj, dict) and ("error" in obj or "Error" in obj):
                    print("[AISStream] Server error:", obj)
                    raise RuntimeError(str(obj))

                # Expect doc-format: MessageType, Message{...}, MetaData{...}
                mtype = obj.get("MessageType")
                if mtype != "PositionReport":
                    # You can broaden if you remove FilterMessageTypes
                    continue

                meta = obj.get("MetaData") or {}
                body = (obj.get("Message") or {}).get("PositionReport") or {}

                # MMSI
                mmsi = meta.get("MMSI") or body.get("UserID")
                try:
                    mmsi = int(mmsi)
                except Exception:
                    continue

                # Optional tanker filter via ShipType (if present in a static message elsewhere,
                # meta may not include it consistently for PositionReport — we keep client-side filter loose)
                ship_type = body.get("Type") or meta.get("ShipType")
                if tanker_only and ship_type is not None:
                    try:
                        if not (80 <= int(ship_type) <= 89):
                            continue
                    except Exception:
                        pass  # if unknown, don't drop

                # Position: prefer MetaData.latitude/longitude per docs
                lat = meta.get("latitude")
                lon = meta.get("longitude")
                if lat is None or lon is None:
                    lat = body.get("Latitude")
                    lon = body.get("Longitude")
                try:
                    lat = float(lat); lon = float(lon)
                except Exception:
                    continue

                sog = body.get("Sog")
                cog = body.get("Cog")
                heading = body.get("TrueHeading")
                draught = None
                nav_status = body.get("NavigationalStatus")
                name = meta.get("ShipName")

                # Store
                ts = int(time.time())
                conn.execute("INSERT OR IGNORE INTO ships(mmsi, ship_type, name) VALUES(?,?,?)",
                             (mmsi, "Tanker" if ship_type and 80 <= int(ship_type) <= 89 else None, name))
                conn.execute("""INSERT OR IGNORE INTO positions
                    (mmsi, ts, lat, lon, sog, cog, heading, draught, nav_status, source)
                    VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (mmsi, ts, lat, lon,
                     float(sog) if sog is not None else None,
                     float(cog) if cog is not None else None,
                     float(heading) if heading is not None else None,
                     float(draught) if draught is not None else None,
                     nav_status,
                     "aisstream"))
                conn.commit()

        except Exception as e:
            print("[AISStream] Connection lost / error:", repr(e))
            print((traceback.format_exc(limit=2) or "").strip())
            try:
                if ws: ws.close()
            except Exception:
                pass
            print(f"[AISStream] Reconnecting in {backoff}s …")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
