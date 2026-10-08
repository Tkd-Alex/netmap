"""Flask dashboard combining Home Assistant router trackers with Opal associations."""
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
import requests


ROOT = Path(__file__).resolve().parent


def load_dotenv():
    # Keep deployment dependency-free; never overwrite explicitly exported vars.
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


try:
    load_dotenv()
except OSError:
    pass

CFG = dict(
    opal_host=os.getenv("OPAL_HOST", "192.0.2.2"),
    opal_port=int(os.getenv("OPAL_PORT", "22")),
    opal_user=os.getenv("OPAL_USER", "root"),
    opal_pass=os.getenv("OPAL_PASSWORD", os.getenv("OPAL_PASS", "")) or None,
    opal_key=os.getenv("OPAL_KEY") or None,
    ap_if=os.getenv("OPAL_AP_IF", os.getenv("OPAL_IFACE", "wlan0")),
    sta_if=os.getenv("OPAL_STA_IF", "wlan-sta0"),
    poll=max(10, int(os.getenv("POLL_SECONDS", "30"))),
    names=os.getenv("NAMES_FILE", str(ROOT / "names.json")),
)

# Known names, used when HA/Opal provide only the MAC or a generic hostname.
# Custom labels saved in names.json take precedence over this map.
KNOWN_NAMES = {
    "02:00:00:00:00:01": "Living room TV",
    "02:00:00:00:00:02": "Office PC",
    "02:00:00:00:00:03": "Smart plug",
}

GROUP = {"WIRED": "wired", "HOST_5G": "w5", "HOST_6G": "w5", "HOST_2G": "w2",
         "IOT_2G": "iot", "IOT_5G": "iot", "IOT_6G": "iot",
         "GUEST_2G": "guest", "GUEST_5G": "guest", "GUEST_6G": "guest"}
LABEL = {"wired": "AX55 · cavo", "w5": "AX55 · 5 GHz", "w2": "AX55 · 2.4 GHz",
         "iot": "AX55 · IoT", "guest": "AX55 · ospiti", "opal": "Opal · 2.4 GHz",
         "unknown": "non connesso"}


def norm_mac(mac):
    value = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    return ":".join(value[i:i + 2] for i in range(0, 12, 2)) if len(value) == 12 else (mac or "").lower()

DB = os.getenv("DB_PATH", str(ROOT / "network.db"))
HA_URL = os.getenv("HA_URL", "").rstrip("/")
HA_TOKEN = os.getenv("HA_TOKEN", "")
HA_VERIFY_SSL = os.getenv("HA_VERIFY_SSL", "true").lower() not in ("0", "false", "no", "off")
app = Flask(__name__)
STATE = {"ts": None, "errors": {}, "data": None}
LOCK = threading.Lock()
WAKE = threading.Event()
_started = False


def _g(pattern, value, cast=str):
    match = re.search(pattern, value or "")
    return cast(match.group(1)) if match else None


def _iw_info(value):
    return dict(essid=_g(r'ESSID: "(.*?)"', value), bssid=_g(r"Access Point: ([0-9A-Fa-f:]{17})", value),
                channel=_g(r"Channel: (\d+)", value, int), txpower=_g(r"Tx-Power: (\d+) dBm", value, int),
                signal=_g(r"Signal: (-?\d+) dBm", value, int), noise=_g(r"Noise: (-?\d+) dBm", value, int),
                quality=_g(r"Link Quality: (\d+/\d+)", value))


def fetch_opal():
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(CFG["opal_host"], port=CFG["opal_port"], username=CFG["opal_user"], password=CFG["opal_pass"],
                   key_filename=CFG["opal_key"], timeout=8, allow_agent=True, look_for_keys=True,
                   disabled_algorithms=dict(pubkeys=["rsa-sha2-256", "rsa-sha2-512"]))
    ap, sta = CFG["ap_if"], CFG["sta_if"]
    command = (f"echo '##AP'; iwinfo {ap} info; echo '##ASSOC'; iwinfo {ap} assoclist; "
               f"echo '##STA'; iwinfo {sta} info; echo '##MAC'; cat /sys/class/net/{sta}/address; "
               "echo '##NEIGH'; ip neigh show")
    _, stdout, _ = client.exec_command(command, timeout=15)
    output = stdout.read().decode(errors="replace")
    client.close()
    parts = dict(re.findall(r"##(\w+)\n(.*?)(?=\n##\w+\n|\Z)", output, re.S))
    clients, neighbors = {}, {}
    assoc_rx = r"^([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+(-?\d+) dBm(?: / (-?\d+) dBm)?(?:.*?(\d+) ms ago)?"
    for neighbor in re.finditer(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+([0-9a-fA-F:]{17})", parts.get("NEIGH", ""), re.M):
        neighbors[norm_mac(neighbor.group(2))] = neighbor.group(1)
    matches = list(re.finditer(assoc_rx, parts.get("ASSOC", ""), re.M))
    assoc_text = parts.get("ASSOC", "")
    for index, match in enumerate(matches):
        mac = norm_mac(match.group(1))
        block = assoc_text[match.start():matches[index + 1].start() if index + 1 < len(matches) else len(assoc_text)]
        clients[mac] = dict(rssi=int(match.group(2)), idle_ms=int(match.group(4)) if match.group(4) else None,
                            ip=neighbors.get(mac), tx=_g(r"TX:\s*([\d.]+) MBit/s", block, float),
                            rx=_g(r"RX:\s*([\d.]+) MBit/s", block, float))
    return dict(ap=_iw_info(parts.get("AP")), sta=_iw_info(parts.get("STA")), clients=clients,
                own_mac=norm_mac(parts.get("MAC", "").strip()))


def load_names():
    names = dict(KNOWN_NAMES)
    try:
        with open(CFG["names"], encoding="utf-8") as file:
            names.update({norm_mac(key): value for key, value in json.load(file).items()})
    except Exception:
        pass
    return names


def build(router, opal, names):
    table = {}
    def row(mac):
        return table.setdefault(mac, dict(mac=mac, name=None, ip=None, group="unknown", rssi=None,
                                          src=None, tx=None, rx=None, reserved=False, connected=False))
    for lease in router["leases"]:
        item = row(lease["mac"]); item["ip"] = lease["ip"]; item["name"] = lease["name"]
    for reservation in router["reservations"]:
        item = row(reservation["mac"]); item["ip"] = item["ip"] or reservation["ip"]
        item["name"] = item["name"] or reservation["name"]; item["reserved"] = True
    for device in router["devices"]:
        item = row(device["mac"]); item["ip"] = device["ip"] or item["ip"]
        item["name"] = device["name"] or item["name"]
        if device.get("active") is not False:
            item["group"] = GROUP.get(device["conn"], "unknown"); item["rssi"] = device["signal"]
            item["src"] = "AX55" if device["signal"] is not None else None
            item["tx"], item["rx"] = device["tx"], device["rx"]
            item["connected"] = True
    own = None
    if opal:
        own = opal["own_mac"]
        for mac, client in opal["clients"].items():
            row(mac).update(group="opal", rssi=client["rssi"], src="Opal", connected=True)
        table.pop(own, None)
    for mac, item in table.items():
        source_name = item["name"]
        item["labeled"] = bool(names.get(mac) or (source_name and norm_mac(source_name) != mac))
        item["name"] = names.get(mac) or source_name or "?"; item["ap"] = LABEL[item["group"]]
    alerts, by_ip = [], {}
    for item in table.values():
        if item["ip"]:
            by_ip.setdefault(item["ip"], []).append(item["name"])
    for ip, device_names in by_ip.items():
        if len(device_names) > 1:
            alerts.append(dict(level="bad", text=f"IP conflict {ip}: {', '.join(device_names)}"))
    for item in table.values():
        if item["rssi"] is not None and item["rssi"] <= -75:
            ap_name = "Opal" if item["group"] == "opal" else "AX55"
            alerts.append(dict(level="warn", text=f"{item['name']} has a weak signal on {ap_name} ({item['rssi']} dBm)"))
    opal_out = None
    if opal:
        lan = (router.get("status") or {}).get("lan_mac"); bssid = (opal["sta"].get("bssid") or "").lower()
        uplink = "unknown"
        if bssid and lan:
            uplink = "AX55" if bssid[:14] == lan[:14] else "other AP (RE700X?)"
        if uplink.startswith("other"):
            alerts.append(dict(level="warn", text=f"The Opal is attached to {bssid}, not to the AX55"))
        signal = opal["sta"].get("signal")
        if signal is not None and signal <= -70:
            alerts.append(dict(level="warn", text=f"Opal uplink signal weak ({signal} dBm)"))
        opal_out = dict(ap=opal["ap"], sta=opal["sta"], uplink=uplink, own_mac=own)
    devices = sorted(table.values(), key=lambda item: (item["ap"], item["name"].lower()))
    return dict(router=dict(fw=router.get("fw"), status=router.get("status")), opal=opal_out,
                devices=devices, alerts=alerts)


def save_history(data):
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS samples(
            ts REAL, mac TEXT, ip TEXT, name TEXT, ap TEXT, band TEXT, ssid TEXT,
            rssi REAL, tx REAL, rx REAL)""")
        now = time.time()
        db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?)", [
            (now, d["mac"], d.get("ip"), d.get("name"), d.get("ap"),
             d.get("band"), d.get("ssid"), d.get("rssi"), d.get("tx"), d.get("rx"))
            for d in data["devices"]
        ])
        db.commit()


def _ha_connection(connection, band):
    c = str(connection or "").upper()
    b = re.sub(r"[^A-Z0-9]", "", str(band or "").upper())
    if any(word in c for word in ("WIRED", "ETHERNET", "RJ45", "CABLE")):
        return "WIRED"
    suffix = "6G" if "6" in b else "5G" if "5" in b else "2G" if "2" in b else ""
    category = "IOT" if "IOT" in c else "GUEST" if "GUEST" in c else "HOST"
    if suffix:
        return f"{category}_{suffix}"
    return "WIRED" if "LAN" in c else "UNKNOWN"


def _ha_rate_mbps(value):
    """Convert TP-Link integration rates from kbit/s to Mbit/s."""
    try:
        return round(float(value) / 1000, 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def fetch_home_assistant():
    if not HA_URL or not HA_TOKEN:
        raise RuntimeError("Configure HA_URL and HA_TOKEN in the .env file to read the AX55 from Home Assistant.")
    response = requests.get(
        f"{HA_URL}/api/states",
        headers={"Authorization": f"Bearer {HA_TOKEN}", "Accept": "application/json"},
        timeout=12,
        verify=HA_VERIFY_SSL,
    )
    response.raise_for_status()
    states = response.json()
    devices = []
    for entity in states:
        if not entity.get("entity_id", "").startswith("device_tracker."):
            continue
        attrs = entity.get("attributes") or {}
        if (attrs.get("source_type") or entity.get("source_type")) not in (None, "router"):
            continue
        mac = attrs.get("mac") or attrs.get("mac_address")
        if not mac:
            continue
        mac = norm_mac(mac)
        if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
            continue
        connection, band = attrs.get("connection"), attrs.get("band")
        devices.append({
            "mac": mac,
            "ip": attrs.get("ip") or attrs.get("ip_address") or "",
            "name": attrs.get("friendly_name") or attrs.get("host_name") or attrs.get("hostname") or mac,
            "conn": _ha_connection(connection, band),
            "connection_label": connection or "",
            "band_label": band or "",
            "ap_name": str(attrs.get("ap_name") or "").lstrip("* "),
            "signal": attrs.get("signal"),
            "active": entity.get("state") == "home",
            "tx": _ha_rate_mbps(attrs.get("tx_rate")),
            "rx": _ha_rate_mbps(attrs.get("rx_rate")),
            "ssid": attrs.get("ssid") or "",
            "rate_unit": "Mbps",
        })
    return {
        "fw": "TP-Link AX55 · data from Home Assistant",
        "status": {"clients": sum(d["active"] for d in devices)},
        "devices": devices,
        "leases": [],
        "reservations": [],
    }


def collect():
    errors, router, opal = {}, None, None
    try:
        router = fetch_home_assistant()
    except Exception as exc:
        errors["Home Assistant · AX55"] = f"{type(exc).__name__}: {exc}"
    try:
        opal = fetch_opal()
    except Exception as exc:
        errors["Opal"] = f"{type(exc).__name__}: {exc}"

    router = router or {"devices": [], "leases": [], "reservations": [], "status": {}}
    data = build(router, opal, load_names())
    by_mac = {d["mac"]: d for d in router.get("devices", [])}
    opal_clients = (opal or {}).get("clients", {})
    opal_ap = (opal or {}).get("ap", {})
    for d in data["devices"]:
        raw = by_mac.get(d["mac"], {})
        conn = raw.get("connection_label") or raw.get("conn", "")
        d["band"] = ("RJ45" if d["group"] == "wired" else
                     "5 GHz" if d["group"] == "w5" else
                     "2.4 GHz" if d["group"] in ("w2", "iot", "guest", "opal") else "—")
        d["ssid"] = opal_ap.get("essid", "") if d["group"] == "opal" else raw.get("ssid", "") or ""
        assoc = opal_clients.get(d["mac"], {})
        d["ip"] = d.get("ip") or assoc.get("ip")
        d["tx"] = assoc.get("tx") if assoc.get("tx") is not None else raw.get("tx")
        d["rx"] = assoc.get("rx") if assoc.get("rx") is not None else raw.get("rx")
        d["rssi"] = (opal_clients[d["mac"]].get("rssi") if d["mac"] in opal_clients
                      else raw.get("signal", d.get("rssi")))
        d["connection"] = conn or ("Wi-Fi" if d["group"] in ("opal", "w2", "w5", "iot", "guest") else d["band"])
        d["ap_name"] = "GL.iNet Opal" if d["group"] == "opal" else raw.get("ap_name", "")
        d["rate_unit"] = "Mbps" if any(assoc.get(k) is not None for k in ("tx", "rx")) else raw.get("rate_unit", "HA")
    try:
        save_history(data)
    except Exception as exc:
        errors["database"] = f"{type(exc).__name__}: {exc}"
    with LOCK:
        STATE.update(ts=time.time(), errors=errors, data=data)


def poll_loop():
    while True:
        try:
            collect()
        except Exception as exc:
            with LOCK:
                STATE["errors"] = {"collector": f"{type(exc).__name__}: {exc}"}
        WAKE.wait(CFG["poll"])
        WAKE.clear()


def start_worker():
    global _started
    if not _started:
        _started = True
        threading.Thread(target=poll_loop, daemon=True, name="network-poller").start()


@app.before_request
def ensure_worker():
    start_worker()


@app.get("/")
def index():
    return render_template("index.html", poll=CFG["poll"])


@app.get("/api/data")
def api_data():
    with LOCK:
        return jsonify(STATE)


@app.post("/api/refresh")
def api_refresh():
    WAKE.set()
    return jsonify(ok=True)


@app.get("/api/history")
def api_history():
    mac = norm_mac(request.args.get("mac", ""))
    try:
        hours = min(168, max(1, int(request.args.get("hours", "24"))))
    except ValueError:
        hours = 24
    with sqlite3.connect(DB) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute("SELECT ts,rssi,ap,band FROM samples WHERE mac=? AND ts>=? ORDER BY ts",
                          (mac, time.time() - hours * 3600)).fetchall()
    return jsonify([dict(row) for row in rows])


@app.patch("/api/names/<mac>")
def api_name(mac):
    mac = norm_mac(mac)
    if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
        return jsonify(error="Invalid MAC"), 400
    body = request.get_json(silent=True) or {}
    name = str(body.get("name", "")).strip()[:80]
    names = load_names()
    if name:
        names[mac] = name
    else:
        names.pop(mac, None)
    Path(CFG["names"]).write_text(json.dumps(names, indent=2, ensure_ascii=False), encoding="utf-8")
    WAKE.set()
    return jsonify(ok=True, name=name)


if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8080")), threaded=True)
