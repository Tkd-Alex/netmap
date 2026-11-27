"""Netmap: live map of a home network. TP-Link router (via Home Assistant) + GL.iNet/OpenWrt AP (via SSH).

Run with a SINGLE process (polling lives in a thread):
    waitress-serve --listen=0.0.0.0:8080 --threads=4 app:app
"""
import hashlib
import hmac
import os
import re
import threading
import time

from flask import Flask, Response, jsonify, render_template, request

import builder  # builder.STATE is rebound at every cycle: always read it through the module
from config import CFG, KUMA_CHECKS, norm_mac, ROOT, TYPES, UPLINK_ID
from database import dbx, read_meta, read_names, write_meta, write_names
from builder import COND, META, start_worker, WAKE


app = Flask(__name__)
NAMES_LOCK = threading.Lock()
META_LOCK = threading.Lock()


# ───────────────────────────── HTTP ─────────────────────────────

@app.before_request
def guard():
    if CFG["auth_user"]:
        auth = request.authorization
        ok = auth and hmac.compare_digest((auth.username or "").encode(), CFG["auth_user"].encode()) \
            and hmac.compare_digest((auth.password or "").encode(), CFG["auth_pass"].encode())
        if not ok:
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Netmap"'})
    # Custom header prevents third-party pages from writing/updating the dashboard (CSRF).
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.headers.get("X-Requested-With") != "dashboard":
        return jsonify(error="Invalid request"), 400


def _asset_version():
    """Short hash of static/: a new deploy changes the CSS/JS URLs, so browsers do not keep stale copies."""
    digest = hashlib.sha1()
    for path in sorted((ROOT / "static").rglob("*")):
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()[:10]


ASSET_V = _asset_version()


@app.get("/")
def index():
    return render_template("index.html", poll=CFG["poll"], asset_v=ASSET_V)


@app.get("/api/data")
def api_data():
    since = request.args.get("since", type=float)
    state = builder.STATE
    if since is not None and state["ts"] == since:
        return jsonify(unchanged=True)
    return jsonify(state)


@app.get("/api/health")
def api_health():
    """200 if everything is fine, 503 otherwise: meant for Uptime Kuma and other monitors."""
    state, now = builder.STATE, time.time()
    if not state["ts"]:
        return jsonify(status="starting"), 503
    failing = [k for k, h in state["health"]["sources"].items() if h["ok"] is False]
    age = int(now - state["ts"])
    ok = not failing and age <= CFG["poll"] * 3
    return jsonify(status="ok" if ok else "degraded", failing=failing, last_cycle_age_s=age,
                   cycles=state["health"]["cycle"]), (200 if ok else 503)


@app.get("/api/events")
def api_events():
    """AP/band changes, connections and disconnections. ?mac= filters one device, ?hours= the range."""
    try:
        hours = min(CFG["retention_days"] * 24, max(1, int(request.args.get("hours", "24"))))
    except ValueError:
        hours = 24
    mac = norm_mac(request.args["mac"]) if request.args.get("mac") else None
    since = time.time() - hours * 3600
    with dbx() as db:
        sql, args = "SELECT ts,mac,name,kind,src,dst FROM events WHERE ts>=?", [since]
        if mac:
            sql, args = sql + " AND mac=?", args + [mac]
        rows = db.execute(sql + " ORDER BY ts DESC LIMIT 300", args).fetchall()
        totals = dict(db.execute("SELECT kind, COUNT(*) FROM events WHERE ts>=? GROUP BY kind", (since,)).fetchall())
        summary = [] if mac else db.execute(
            "SELECT mac, MAX(name), SUM(kind='move_ap'), SUM(kind='move_band'), SUM(kind='disconnect') FROM events "
            "WHERE ts>=? GROUP BY mac HAVING SUM(kind!='connect')>0 "
            "ORDER BY SUM(kind IN ('move_ap','move_band')) DESC, SUM(kind='disconnect') DESC LIMIT 10",
            (since,)).fetchall()
    current = {d["mac"]: d["name"] for d in ((builder.STATE["data"] or {}).get("devices") or [])}

    def name_of(mac, stored):  # the current name takes precedence over the one stored at the time of the event
        return current[mac] if current.get(mac) not in (None, "?") else stored

    return jsonify(hours=hours, totals=totals,
                   events=[dict(ts=r[0], mac=r[1], name=name_of(r[1], r[2]), kind=r[3], src=r[4], dst=r[5]) for r in rows],
                   summary=[dict(mac=r[0], name=name_of(r[0], r[1]), move_ap=r[2], move_band=r[3], disconnect=r[4])
                            for r in summary])


@app.post("/api/refresh")
def api_refresh():
    """It forces a cycle and responds as soon as new data is ready."""
    with COND:
        seq = META["seq"]
        WAKE.set()
        COND.wait_for(lambda: META["seq"] > seq, timeout=25)
    return jsonify(builder.STATE)


@app.get("/api/history")
def api_history():
    mac = request.args.get("mac", "")
    mac = mac if mac == UPLINK_ID else norm_mac(mac)
    try:
        hours = min(CFG["retention_days"] * 24, max(1, int(request.args.get("hours", "24"))))
    except ValueError:
        hours = 24
    bucket = max(CFG["poll"], hours * 3600 // 500)  # at most ~500 points, averaged
    with dbx() as db:
        rows = db.execute(
            "SELECT CAST(ts/? AS INTEGER)*? AS t, ROUND(AVG(rssi),1) FROM samples "
            "WHERE mac=? AND ts>=? AND rssi IS NOT NULL GROUP BY 1 ORDER BY 1",
            (bucket, bucket, mac, time.time() - hours * 3600)).fetchall()
    return jsonify(hours=hours, bucket=bucket, points=[[t, v] for t, v in rows])


@app.patch("/api/names/<mac>")
def api_name(mac):
    mac = norm_mac(mac)
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        return jsonify(error="Invalid MAC"), 400
    name = str((request.get_json(silent=True) or {}).get("name", "")).strip()[:80]
    with NAMES_LOCK:
        try:
            names = read_names(strict=True)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"names.json unreadable: {exc}"), 500
        if name:
            names[mac] = name
        else:
            names.pop(mac, None)
        write_names(names)
    WAKE.set()
    return jsonify(ok=True, name=name)


@app.patch("/api/meta/<mac>")
def api_meta(mac):
    mac = norm_mac(mac)
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        return jsonify(error="Invalid MAC"), 400
    body = request.get_json(silent=True) or {}
    kind = str(body.get("type") or "").strip()
    room = " ".join(str(body.get("room") or "").split())[:40]
    if kind and kind not in TYPES:
        return jsonify(error="Invalid type"), 400
    kuma = body.get("kuma")
    if kuma is not None:  # {"enabled": true|false|null, "check": "ping"|"alexa"|"shelly"|""}; null/"" = automatic
        if not isinstance(kuma, dict) or kuma.get("enabled") not in (True, False, None) \
                or (kuma.get("check") or "") not in ("", *KUMA_CHECKS):
            return jsonify(error="Invalid kuma settings"), 400
        kuma = {k: v for k, v in (("enabled", kuma.get("enabled")), ("check", kuma.get("check") or None)) if v is not None}
    with META_LOCK:
        try:
            meta = read_meta(strict=True)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"meta.json unreadable: {exc}"), 500
        if kuma is None:  # field not sent: keep what is stored
            kuma = (meta.get(mac) or {}).get("kuma") if isinstance(meta.get(mac), dict) else None
        entry = {k: v for k, v in (("type", kind), ("room", room), ("kuma", kuma)) if v}
        if entry:
            meta[mac] = entry
        else:
            meta.pop(mac, None)
        write_meta(meta)
    WAKE.set()
    return jsonify(ok=True, **entry)


@app.post("/api/meta/apply-suggestions")
def api_apply_suggestions():
    """Commits suggested types for all not-yet-classified devices."""
    devices = (builder.STATE["data"] or {}).get("devices", [])
    with META_LOCK:
        try:
            meta = read_meta(strict=True)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"meta.json unreadable: {exc}"), 500
        applied = 0
        for d in devices:
            entry = dict(meta.get(d["mac"]) or {})
            if d.get("kind_auto") and d.get("kind") and not entry.get("type"):  # never overwrite a manually saved choice
                entry["type"] = d["kind"]
                meta[d["mac"]] = entry
                applied += 1
        if applied:
            write_meta(meta)
    WAKE.set()
    return jsonify(ok=True, applied=applied)


if not os.getenv("DASH_NO_WORKER"):
    start_worker()

if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8080")), threaded=True)
