"""Netmap: live map of a home network. TP-Link router (via Home Assistant) + GL.iNet/OpenWrt AP (via SSH).

Run with a SINGLE process (polling lives in a thread):
    waitress-serve --listen=0.0.0.0:8080 --threads=4 app:app
"""
import copy
import hmac
import json
import logging
import logging.handlers
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import requests
from flask import Flask, Response, jsonify, render_template, request

ROOT = Path(__file__).resolve().parent


def norm_mac(mac):
    value = re.sub(r"[^0-9a-fA-F]", "", mac or "").lower()
    return ":".join(value[i:i + 2] for i in range(0, 12, 2)) if len(value) == 12 else (mac or "").lower()


def load_dotenv():
    # No dependencies; already-exported variables take precedence.
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


def _list(name, default=""):
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


def _iface(value):
    if not re.fullmatch(r"[\w.-]+", value):
        raise ValueError(f"Invalid interface name: {value!r}")
    return value


CFG = dict(
    opal_host=os.getenv("OPAL_HOST", ""),  # empty = Opal/OpenWrt disabled (primary router only)
    opal_port=int(os.getenv("OPAL_PORT", "22")),
    opal_user=os.getenv("OPAL_USER", "root"),
    opal_pass=os.getenv("OPAL_PASSWORD", os.getenv("OPAL_PASS", "")) or None,
    opal_key=os.getenv("OPAL_KEY") or None,
    known_hosts=os.getenv("OPAL_KNOWN_HOSTS") or None,  # when set, host key is verified (RejectPolicy)
    ap_if=_iface(os.getenv("OPAL_AP_IF", os.getenv("OPAL_IFACE", "wlan0"))),
    sta_if=_iface(os.getenv("OPAL_STA_IF", "wlan-sta0")),
    extenders=_list("EXTENDER_NAMES"),  # names (may be partial) of OneMesh extenders reported by the AX55
    bridge=_iface(os.getenv("OPAL_BRIDGE", "br-lan")),
    uplink_expected=os.getenv("UPLINK_EXPECTED_AP", ""),  # part of expected AP name (e.g. "AX55"); empty = no warning
    # Opal physical LAN ports (e.g. "eth0.1"): MACs seen there by the bridge become "Opal · wired".
    lan_ifs=[_iface(x) for x in _list("OPAL_LAN_IF")],
    wired_macs=[norm_mac(x) for x in _list("OPAL_WIRED_MACS")],  # manual alternative/addition
    ax_macs=[norm_mac(x) for x in _list("AX55_MAC")],
    re_macs=[norm_mac(x) for x in _list("RE700X_MAC")],
    poll=max(10, int(os.getenv("POLL_SECONDS", "30"))),
    names=os.getenv("NAMES_FILE", str(ROOT / "names.json")),
    meta=os.getenv("META_FILE", str(ROOT / "meta.json")),  # type and room per device
    db=os.getenv("DB_PATH", str(ROOT / "network.db")),
    retention_days=max(1, int(os.getenv("RETENTION_DAYS", "14"))),
    rssi_good=int(os.getenv("RSSI_GOOD", "-60")),
    rssi_warn=int(os.getenv("RSSI_WARN", "-75")),
    uplink_warn=int(os.getenv("UPLINK_WARN", "-70")),
    new_hours=int(os.getenv("NEW_DEVICE_HOURS", "48")),
    offline_types=_list("OFFLINE_ALERT_TYPES", "camera,rete"),  # types to alert on when they stay offline (empty = never)
    offline_minutes=int(os.getenv("OFFLINE_ALERT_MINUTES", "10")),
    ha_url=os.getenv("HA_URL", "").rstrip("/"),
    ha_token=os.getenv("HA_TOKEN", ""),
    ha_verify=os.getenv("HA_VERIFY_SSL", "true").lower() not in ("0", "false", "no", "off"),
    auth_user=os.getenv("DASH_USER", ""),
    auth_pass=os.getenv("DASH_PASSWORD", ""),
)

GROUP = {"WIRED": "wired", "HOST_5G": "w5", "HOST_6G": "w5", "HOST_2G": "w2",
         "IOT_2G": "iot", "IOT_5G": "iot", "IOT_6G": "iot",
         "GUEST_2G": "guest", "GUEST_5G": "guest", "GUEST_6G": "guest"}
LABEL = {"wired": "AX55 · cavo", "w5": "AX55 · 5 GHz", "w2": "AX55 · 2.4 GHz", "iot": "AX55 · IoT",
         "guest": "AX55 · ospiti", "opal": "Opal · 2.4 GHz", "opal_wired": "Opal · cavo",
         "unknown": "non determinato"}
BAND = {"wired": "RJ45", "opal_wired": "RJ45", "w5": "5 GHz", "w2": "2.4 GHz", "iot": "2.4 GHz",
        "guest": "2.4 GHz", "opal": "2.4 GHz"}
TYPES = {"pc": "PC / laptop", "server": "Server / VM / LXC", "smartphone": "Smartphone / tablet",
         "tv": "TV / audio / media", "camera": "Telecamera / campanello", "luce_presa": "IoT · luci / prese / relè",
         "iot": "IoT · altro", "rete": "Rete (router / AP)", "altro": "Altro"}
OUI_KIND = {"bc:24:11": "server"}  # Proxmox virtual MACs (VM and LXC)
KIND_HINTS = [  # in priority order; words <4 chars only if an exact "chunk" of the name
    ("camera", "cam camera telecamera reolink rlc doorbell campanello citofono ring spioncino webcam"),
    ("rete", "archer ax55 re700 opal router extender repeater mesh accesspoint"),
    ("server", "proxmox pve lxc vm nas server homeassistant assistant raspberrypi raspberry"),
    ("luce_presa", "shelly plug presa luce luci lampada lamp bulb tasmota sonoff hue relay dimmer tapo kasa wled"),
    ("smartphone", "iphone ipad pixel galaxy smartphone phone tablet android oneplus redmi poco"),
    ("pc", "pc laptop notebook desktop macbook imac workstation thinkpad"),
    ("tv", "tv chromecast firetv roku appletv echo alexa amazon sonos soundbar speaker bravia webos tizen"),
    ("iot", "philips broadlink sensor sensore thermostat termostato purifier purificatore conditioner "
            "climatizzatore robot roomba aspirapolvere stampante printer esp zigbee"),
]


def suggest_kind(mac, *texts):
    """Likely type from MAC (known OUI) or from words in the name. Only a suggestion: the last word is yours."""
    if mac[:8] in OUI_KIND:
        return OUI_KIND[mac[:8]]
    tokens = re.findall(r"[a-z0-9]+", " ".join(t for t in texts if t).lower())
    for kind, words in KIND_HINTS:
        for word in words.split():
            if any(t == word if len(word) < 4 else t.startswith(word) for t in tokens):
                return kind
    return None


UPLINK_ID = "opal:uplink"  # pseudo-MAC by which the uplink signal is historicized

# ───────────────────────────── Log and diagnostics ─────────────────────────────

log = logging.getLogger("netmap")


def setup_logging():
    """INFO: a summary per cycle + events. DEBUG: includes tracebacks. LOG_FILE enables a file with rotation."""
    if log.handlers:
        return
    level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers = [logging.StreamHandler()]
    if os.getenv("LOG_FILE"):
        handlers.append(logging.handlers.RotatingFileHandler(os.getenv("LOG_FILE"), maxBytes=1_000_000,
                                                             backupCount=3, encoding="utf-8"))
    log.setLevel(level)
    log.propagate = False
    for handler in handlers:
        handler.setFormatter(fmt)
        log.addHandler(handler)
    logging.getLogger("paramiko").setLevel(logging.WARNING)
    if level > logging.DEBUG:
        logging.getLogger("werkzeug").setLevel(logging.WARNING)  # no line for each HTTP request


# Health status of each source, shown in the "Diagnostics" panel and at /api/health.
HEALTH = {key: dict(label=label, ok=None, last_ok=None, last_try=None, duration=None, fails=0,
                    last_error=None, detail="")
          for key, label in (("router", "Home Assistant · AX55"), ("opal", "Opal (SSH)"), ("db", "Database"))}
STARTED = time.time()

app = Flask(__name__)
STATE = {"ts": None, "errors": {}, "data": None, "health": None}  # replaced in its entirety at each cycle (no read locks)
META = {"seq": 0}
COND = threading.Condition()
WAKE = threading.Event()
ALIAS_LOGGED = set()
OFFLINE_ALERTED = set()
LAST = {}  # latest valid result for source: {"router": (ts, data), "opal": (ts, data)}
NAMES_LOCK = threading.Lock()
META_LOCK = threading.Lock()
_started = False


# ───────────────────────────── Opal (SSH) ─────────────────────────────

def _g(pattern, value, cast=str):
    match = re.search(pattern, value or "")
    return cast(match.group(1)) if match else None


def _iw_info(value):
    return dict(essid=_g(r'ESSID: "(.*?)"', value), bssid=_g(r"Access Point: ([0-9A-Fa-f:]{17})", value),
                channel=_g(r"Channel: (\d+)", value, int), txpower=_g(r"Tx-Power: (\d+) dBm", value, int),
                signal=_g(r"Signal: (-?\d+) dBm", value, int), noise=_g(r"Noise: (-?\d+) dBm", value, int),
                quality=_g(r"Link Quality: (\d+/\d+)", value))


class OpalLink:
    """Persistent SSH connection: avoids a handshake (expensive for the Opal's CPU) on each cycle."""

    def __init__(self):
        self.client = None
        self.new_session = False
        self.lock = threading.Lock()

    def _connect(self):
        import paramiko
        client = paramiko.SSHClient()
        if CFG["known_hosts"]:
            client.load_host_keys(CFG["known_hosts"])
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(CFG["opal_host"], port=CFG["opal_port"], username=CFG["opal_user"],
                       password=CFG["opal_pass"], key_filename=CFG["opal_key"], timeout=8, banner_timeout=8,
                       auth_timeout=8, allow_agent=True, look_for_keys=True,
                       disabled_algorithms=dict(pubkeys=["rsa-sha2-256", "rsa-sha2-512"]))
        client.get_transport().set_keepalive(20)
        self.new_session = True
        log.info("Opal: new SSH session to %s@%s:%s", CFG["opal_user"], CFG["opal_host"], CFG["opal_port"])
        return client

    def close(self):
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        self.client = None

    def run_sections(self, sections):
        """It executes each command separately within the persistent session and measures its duration."""
        with self.lock:
            self.new_session = False
            for attempt in (1, 2):
                try:
                    transport = self.client.get_transport() if self.client else None
                    if not (transport and transport.is_active()):
                        self.close()
                        self.client = self._connect()
                    outputs, timings = {}, {}
                    for name, command in sections:
                        t0 = time.perf_counter()
                        _, stdout, _ = self.client.exec_command(command, timeout=15)
                        outputs[name] = stdout.read().decode(errors="replace")
                        timings[name] = time.perf_counter() - t0
                    return outputs, timings
                except Exception:
                    self.close()
                    if attempt == 2:
                        raise


OPAL = OpalLink()
ASSOC_RX = re.compile(r"^([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s+(-?\d+) dBm(?: / (-?\d+) dBm)?(?:.*?(\d+) ms ago)?", re.M)


def parse_opal(output):
    parts = dict(re.findall(r"##(\w+)\n(.*?)(?=\n##\w+\n|\Z)", output, re.S))
    neighbors, neigh_state = {}, {}
    for m in re.finditer(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+([0-9a-fA-F:]{17})(.*)$",
                         parts.get("NEIGH", ""), re.M):
        mac = norm_mac(m.group(2))
        neighbors[mac] = m.group(1)
        state = re.search(r"\b(REACHABLE|STALE|DELAY|PROBE|FAILED|PERMANENT|INCOMPLETE|NOARP)\b", m.group(3))
        neigh_state[mac] = state.group(1) if state else None
    assoc_text = parts.get("ASSOC", "")
    matches = list(ASSOC_RX.finditer(assoc_text))
    clients = {}
    for index, match in enumerate(matches):
        mac = norm_mac(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(assoc_text)
        block = assoc_text[match.start():end]
        clients[mac] = dict(rssi=int(match.group(2)), idle_ms=int(match.group(4)) if match.group(4) else None,
                            ip=neighbors.get(mac), tx=_g(r"TX:\s*([\d.]+) MBit/s", block, float),
                            rx=_g(r"RX:\s*([\d.]+) MBit/s", block, float))
    wired = set(CFG["wired_macs"])
    if CFG["lan_ifs"]:
        fdb = parts.get("FDB", "")
        for m in re.finditer(r"^([0-9a-fA-F:]{17}) dev (\S+)(.*)$", fdb, re.M):  # `bridge fdb show` format
            if m.group(2) in CFG["lan_ifs"] and "permanent" not in m.group(3) and "self" not in m.group(3):
                wired.add(norm_mac(m.group(1)))
        ports = {int(m.group(1), 0): m.group(2) for m in re.finditer(r"^(0x[0-9a-fA-F]+|\d+) (\S+)$",
                                                                    parts.get("PORTS", ""), re.M)}
        for m in re.finditer(r"^\s*(\d+)\s+([0-9a-fA-F:]{17})\s+(yes|no)\b", fdb, re.M):  # `brctl showmacs`
            if m.group(3) == "no" and ports.get(int(m.group(1))) in CFG["lan_ifs"]:
                wired.add(norm_mac(m.group(2)))
    ap_info, own = _iw_info(parts.get("AP")), norm_mac(parts.get("MAC", "").strip())
    local = {norm_mac(m) for m in re.findall(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", parts.get("LOCAL", ""))}
    local |= {own, norm_mac(ap_info.get("bssid") or "")}
    local -= {"00:00:00:00:00:00", ""}
    return dict(ap=ap_info, sta=_iw_info(parts.get("STA")), clients=clients, local_macs=sorted(local),
                neigh=neighbors, neigh_state=neigh_state, wired=sorted(wired), own_mac=own)


def fetch_opal():
    ap, sta = CFG["ap_if"], CFG["sta_if"]
    sections = [("AP", f"iwinfo {ap} info"), ("ASSOC", f"iwinfo {ap} assoclist"), ("STA", f"iwinfo {sta} info"),
                ("MAC", f"cat /sys/class/net/{sta}/address"), ("NEIGH", "ip neigh show; echo; echo '##LOCAL'; cat /sys/class/net/*/address 2>/dev/null")]
    if CFG["lan_ifs"]:
        br = CFG["bridge"]
        sections += [("FDB", f"bridge fdb show 2>/dev/null || brctl showmacs {br} 2>/dev/null"),
                     ("PORTS", f'for p in /sys/class/net/{br}/brif/*; do echo "$(cat $p/port_no) ${{p##*/}}"; done 2>/dev/null')]
    outputs, timings = OPAL.run_sections(sections)
    output = "".join(f"##{name}\n{outputs[name].rstrip()}\n" for name, _ in sections)
    parsed = parse_opal(output)
    log.debug("Opal · time per command: %s", ", ".join(f"{n} {t:.2f} s" for n, t in timings.items()))
    ranked = sorted(timings.items(), key=lambda kv: -kv[1])
    slow = [f"{n} {t:.2f} s" for n, t in (ranked[:2] if sum(timings.values()) >= 2 else
                                           [kv for kv in ranked if kv[1] >= 1])]
    parsed["meta"] = dict(detail=f"{len(parsed['clients'])} Wi-Fi clients, {len(parsed['wired'])} wired · "
                                 f"SSH {'new' if OPAL.new_session else 'reused'} · {len(output)} B"
                                 + (f" · slow: {', '.join(slow)}" if slow else ""))
    return parsed


# ──────────────────────── Home Assistant (AX55) ────────────────────────

HA = requests.Session()
_template_ok = True
# Ask HA for device_tracker entities only (and only useful attributes) instead of downloading all entities.
HA_TEMPLATE = (
    "{% set ns = namespace(r=[]) %}{% for s in states.device_tracker %}{% set a = s.attributes %}"
    "{% set ns.r = ns.r + [dict(state=s.state, attributes=dict(mac=a.get('mac'), mac_address=a.get('mac_address'),"
    " ip=a.get('ip'), ip_address=a.get('ip_address'), friendly_name=a.get('friendly_name'),"
    " host_name=a.get('host_name'), hostname=a.get('hostname'), connection=a.get('connection'),"
    " band=a.get('band'), ap_name=a.get('ap_name'), signal=a.get('signal'), tx_rate=a.get('tx_rate'),"
    " rx_rate=a.get('rx_rate'), ssid=a.get('ssid'), source_type=a.get('source_type')))] %}"
    "{% endfor %}{{ ns.r | tojson }}")


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
    try:
        return round(float(value) / 1000, 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def _ha_trackers():
    global _template_ok
    headers = {"Authorization": f"Bearer {CFG['ha_token']}", "Accept": "application/json"}
    if _template_ok:
        try:
            r = HA.post(f"{CFG['ha_url']}/api/template", json={"template": HA_TEMPLATE}, headers=headers,
                        timeout=12, verify=CFG["ha_verify"])
            r.raise_for_status()
            return json.loads(r.text), "template", len(r.content), None
        except (ValueError, requests.HTTPError) as exc:
            _template_ok = False  # template not supported/valid: falling back to /api/states
            log.warning("Home Assistant: template unusable (%s), falling back to /api/states", exc)
    r = HA.get(f"{CFG['ha_url']}/api/states", headers=headers, timeout=12, verify=CFG["ha_verify"])
    r.raise_for_status()
    states = r.json()
    return ([e for e in states if e.get("entity_id", "").startswith("device_tracker.")], "/api/states",
            len(r.content), len(states))


def fetch_home_assistant():
    if not CFG["ha_url"] or not CFG["ha_token"]:
        raise RuntimeError("Configure HA_URL and HA_TOKEN in the .env file to read the AX55 from Home Assistant.")
    devices = []
    entities, mode, size, total = _ha_trackers()
    for entity in entities:
        attrs = entity.get("attributes") or {}
        if (attrs.get("source_type") or entity.get("source_type")) not in (None, "router"):
            continue
        mac = norm_mac(attrs.get("mac") or attrs.get("mac_address") or "")
        if not re.fullmatch(r"[0-9a-f]{2}(?::[0-9a-f]{2}){5}", mac):
            continue
        connection, band = attrs.get("connection"), attrs.get("band")
        devices.append(dict(
            mac=mac, ip=attrs.get("ip") or attrs.get("ip_address") or "",
            name=attrs.get("friendly_name") or attrs.get("host_name") or attrs.get("hostname") or mac,
            conn=_ha_connection(connection, band), connection_label=connection or "",
            ap_name=str(attrs.get("ap_name") or "").lstrip("* "), signal=attrs.get("signal"),
            active=entity.get("state") == "home", tx=_ha_rate_mbps(attrs.get("tx_rate")),
            rx=_ha_rate_mbps(attrs.get("rx_rate")), ssid=attrs.get("ssid") or ""))
    detail = (f"{len(entities)} trackers received, {len(devices)} valid · template · {size / 1024:.0f} KB"
              if total is None else
              f"{len(entities)} trackers out of {total} entities downloaded · {size / 1024:.0f} KB (template not available)")
    return dict(fw="TP-Link AX55 · data from Home Assistant", devices=devices, meta=dict(detail=detail))


# ───────────────────────────── Names / labels ───────────────────────────

_GOOD = {}           # the last valid content of each JSON file
CONFIG_ERRORS = {}   # file → error, shown on the page


def _read_map(path, strict=False):
    name = Path(path).name
    try:
        with open(path, encoding="utf-8") as file:
            raw = json.load(file)
        if not isinstance(raw, dict):
            raise ValueError("must be a JSON object {mac: …}")
        data = {norm_mac(k): v for k, v in raw.items()}
    except FileNotFoundError:
        _GOOD.pop(path, None)
        CONFIG_ERRORS.pop(name, None)
        return {}
    except (OSError, ValueError) as exc:
        if strict:
            raise  # Whoever rewrites the file must never start from broken content.
        message = f"{type(exc).__name__}: {exc}"
        if CONFIG_ERRORS.get(name) != message:
            log.warning("%s is unreadable (%s): using the last valid version", name, message)
        CONFIG_ERRORS[name] = message
        return dict(_GOOD.get(path, {}))
    CONFIG_ERRORS.pop(name, None)
    _GOOD[path] = data
    return dict(data)


def _write_map(path, data):
    target = Path(path)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, target)  # atomic write


def read_names(strict=False):
    return _read_map(CFG["names"], strict)


def write_names(names):
    _write_map(CFG["names"], names)


def read_meta(strict=False):
    return _read_map(CFG["meta"], strict)


def write_meta(meta):
    _write_map(CFG["meta"], meta)


# ───────────────────────────── Map building ─────────────────────────────

def node_of(d):
    """Network node the device is attached to: Opal, an OneMesh extender, or the AX55."""
    if d["group"] in ("opal", "opal_wired"):
        return "Opal"
    name = (d["ap_name"] or "").lower()
    for hint in CFG["extenders"]:
        if hint.lower() in name:
            return hint
    return "AX55"


def build(router, opal, names, meta=None):
    table = {}

    def row(mac):
        return table.setdefault(mac, dict(mac=mac, name=None, ip=None, group="unknown", rssi=None, tx=None,
                                          rx=None, connected=False, ap_name="", ssid="", connection="", arp=None, alias=False, via=""))

    for dev in router["devices"]:
        item = row(dev["mac"])
        item.update(ip=dev["ip"] or None, name=dev["name"])
        if dev["active"]:
            item.update(group=GROUP.get(dev["conn"], "unknown"), rssi=dev["signal"], tx=dev["tx"], rx=dev["rx"],
                        connected=True, ssid=dev["ssid"], ap_name=dev["ap_name"], connection=dev["connection_label"])
    own, opal_view, aliases = None, None, []
    if opal:
        own, essid = opal["own_mac"], opal["ap"].get("essid") or ""
        for mac, client in opal["clients"].items():
            item = row(mac)
            item.update(group="opal", rssi=client["rssi"], connected=True, ssid=essid, ap_name="GL.iNet Opal",
                        connection="Wi-Fi 2.4 GHz", ip=item["ip"] or client["ip"],
                        tx=client["tx"] if client["tx"] is not None else item["tx"],
                        rx=client["rx"] if client["rx"] is not None else item["rx"])
        for mac in opal["wired"]:
            if mac in opal["clients"] or mac == own:
                continue
            item = row(mac)
            item.update(group="opal_wired", rssi=None, tx=None, rx=None, connected=True, ssid="",
                        ap_name="GL.iNet Opal", connection="RJ45", ip=item["ip"] or opal["neigh"].get(mac))
        opal_view = table.pop(own, None)  # the Opal itself is not a client (but the router knows which AP it's attached to)
        # Alias: behind the Opal the AX55 may see devices with the Opal's MAC (station without 4addr).
        # Priority: Opal assoclist/wired > alias seen through AX55 > AX55 state (may show "absent").
        by_ip = {}
        for mac, ip in opal["neigh"].items():
            if mac not in opal.get("local_macs", ()):
                by_ip.setdefault(ip, mac)
        for mac in [m for m in table if m in opal.get("local_macs", ())]:
            entry = table.pop(mac)
            real = by_ip.get(entry["ip"] or "")
            if not real:
                continue
            item = row(real)
            item["alias"] = True
            promoted = not item["connected"] and entry["connected"]
            if promoted:
                item.update(group="opal_wired", connected=True, rssi=None, tx=None, rx=None, ssid="",
                            ap_name="GL.iNet Opal", connection="behind the Opal", via="behind the Opal",
                            ip=item["ip"] or entry["ip"], name=item["name"] or entry["name"])
            aliases.append(dict(real=real, via=mac, ip=entry["ip"], name=item["name"] or entry["name"],
                                promoted=promoted))
    for mac, item in table.items():
        source = item["name"]
        item["named"] = bool(names.get(mac))  # name chosen by the user (names.json)
        item["labeled"] = bool(item["named"] or (source and norm_mac(source) != mac))
        item["name"] = names.get(mac) or source or "?"
        item["ap"], item["band"] = LABEL[item["group"]], BAND.get(item["group"], "—")
        item["node"] = node_of(item)
        item["arp"] = (opal or {}).get("neigh_state", {}).get(mac)  # ARP state seen by the Opal(REACHABLE, STALE…)
        info = (meta or {}).get(mac)
        info = info if isinstance(info, dict) else {}
        explicit = info.get("type") if info.get("type") in TYPES else None
        suggested = None if explicit else suggest_kind(mac, item["name"], source)
        item["kind"], item["kind_auto"] = explicit or suggested, bool(suggested)
        item["room"] = str(info.get("room") or "")

    devices = sorted(table.values(), key=lambda d: (not d["connected"], d["ap"], d["name"].lower()))
    live = [d for d in devices if d["connected"]]
    alerts, by_ip = [], {}
    for d in live:
        if d["ip"]:
            by_ip.setdefault(d["ip"], []).append(d["name"])
    for ip, owners in by_ip.items():
        if len(owners) > 1:
            alerts.append(dict(level="bad", kind="conflict", text=f"IP conflict {ip}: {', '.join(owners)}"))
    weak = {}
    for d in live:
        if d["rssi"] is not None and d["rssi"] <= CFG["rssi_warn"]:
            weak.setdefault((d["room"], d["node"]), []).append(d)
    for (room, where), items in weak.items():
        if room and len(items) >= 2:  # multiple weak devices in the same room: single warning, likely a coverage issue
            detail = ", ".join(f"{d['name']} ({d['rssi']} dBm)" for d in items)
            alerts.append(dict(level="warn", kind="weak", room=room, text=f"Weak signal in {room} on {where}: {detail}"))
        else:
            for d in items:
                place = f" · {d['room']}" if d["room"] else ""
                alerts.append(dict(level="warn", kind="weak", mac=d["mac"], room=d["room"],
                                   text=f"{d['name']}{place} has a weak signal on {where} ({d['rssi']} dBm)"))

    opal_out = None
    if opal:
        sta = opal["sta"]
        bssid = (sta.get("bssid") or "").lower()
        via = ((opal_view or {}).get("ap_name") or "").strip() if opal_view and opal_view["connected"] else ""
        uplink = "unknown"
        if via:  # most reliable source: what the AX55/OneMesh reports for the Opal wlan-sta0 MAC
            uplink = via
            if CFG["uplink_expected"] and CFG["uplink_expected"].lower() not in via.lower():
                alerts.append(dict(level="warn", kind="uplink", text=f"The Opal is connected to «{via}» instead of "
                                                                    f"«{CFG['uplink_expected']}»"))
        elif bssid and bssid != own:  # if BSSID matches the Opal MAC the driver doesn't really report it
            mid = bssid[3:14]
            uplink = ("AX55" if any(m[3:14] == mid for m in CFG["ax_macs"]) else
                      "RE700X" if any(m[3:14] == mid for m in CFG["re_macs"]) else "other AP")
            if uplink in ("RE700X", "other AP"):
                alerts.append(dict(level="warn", kind="uplink",
                                   text=f"The Opal is connected to {bssid} ({uplink}), not the primary router"))
        if sta.get("signal") is not None and sta["signal"] <= CFG["uplink_warn"]:
            alerts.append(dict(level="warn", kind="uplink", text=f"Opal uplink signal weak ({sta['signal']} dBm)"))
        snr = sta["signal"] - sta["noise"] if sta.get("signal") is not None and sta.get("noise") is not None else None
        opal_out = dict(ap=opal["ap"], sta=sta, uplink=uplink, own_mac=own, snr=snr)
    return dict(router=dict(fw=router.get("fw")), opal=opal_out, devices=devices, alerts=alerts,
                thresholds=dict(good=CFG["rssi_good"], warn=CFG["rssi_warn"]), aliases=aliases, types=TYPES)


# ───────────────────────────── History (SQLite) ─────────────────────────────

@contextmanager
def dbx():
    db = sqlite3.connect(CFG["db"], timeout=10)
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    Path(CFG["db"]).parent.mkdir(parents=True, exist_ok=True)
    with dbx() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS samples(
            ts REAL, mac TEXT, ip TEXT, name TEXT, ap TEXT, band TEXT, ssid TEXT, rssi REAL, tx REAL, rx REAL)""")
        db.execute("CREATE INDEX IF NOT EXISTS ix_samples_mac_ts ON samples(mac, ts)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_samples_ts ON samples(ts)")
        db.execute("CREATE TABLE IF NOT EXISTS events(ts REAL, mac TEXT, name TEXT, kind TEXT, src TEXT, dst TEXT)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts)")
        db.execute("CREATE INDEX IF NOT EXISTS ix_events_mac_ts ON events(mac, ts)")
        db.execute("CREATE TABLE IF NOT EXISTS seen(mac TEXT PRIMARY KEY, first_seen REAL, last_seen REAL)")


def save_history(data, now):
    """Save only useful samples: connected devices with RSSI + Opal uplink signal."""
    rows = [(now, d["mac"], None, None, d["ap"], d["band"], None, d["rssi"], d["tx"], d["rx"])
            for d in data["devices"] if d["connected"] and d["rssi"] is not None]
    sta = (data["opal"] or {}).get("sta") or {}
    if sta.get("signal") is not None:
        rows.append((now, UPLINK_ID, None, None, "Uplink Opal", "5 GHz", sta.get("essid"), sta["signal"], None, None))
    with dbx() as db:
        db.executemany("INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def track_seen(data, now):
    """Adds last_seen to devices and a warning for MAC addresses never seen before."""
    with dbx() as db:
        known = {m: (f, l) for m, f, l in db.execute("SELECT mac, first_seen, last_seen FROM seen")}
        baseline = not known  # first run: everything already present is not "new"
        upserts = []
        for d in data["devices"]:
            first, last = known.get(d["mac"], (None, None))
            if d["connected"]:
                if first is None:
                    first = 0 if baseline else now
                last = now
                upserts.append((d["mac"], first, last))
                if first and now - first < CFG["new_hours"] * 3600 and not d["named"]:
                    guess = f"probably {TYPES[d['kind']]}" if d["kind"] else "unknown type"
                    data["alerts"].append(dict(level="info" if d["kind"] else "warn", kind="new", mac=d["mac"],
                                               text=f"New device on the network: {d['name']} "
                                                    f"({d['ip'] or d['mac']}) · {guess}"))
            d["last_seen"] = last
        db.executemany("INSERT INTO seen VALUES(?,?,?) ON CONFLICT(mac) DO UPDATE SET last_seen=excluded.last_seen",
                       upserts)
    offline_alerts(data, now)


def _duration(minutes):
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h" if minutes < 2880 else f"{minutes // 1440} d"


def offline_alerts(data, now):
    """Notifies you if a device of a "critical" type (default: cameras and network) remains offline."""
    current = set()
    if data.get("clean") and CFG["offline_types"]:  # with a faulty source, they would all appear to be offline
        for d in data["devices"]:
            if d["connected"] or d["kind"] not in CFG["offline_types"] or not d.get("last_seen"):
                continue
            minutes = int((now - d["last_seen"]) / 60)
            if minutes >= CFG["offline_minutes"]:
                place = f" · {d['room']}" if d["room"] else ""
                current.add(d["mac"])
                data["alerts"].append(dict(level="bad" if d["kind"] == "rete" else "warn", kind="offline",
                                           mac=d["mac"], room=d["room"],
                                           text=f"{d['name']}{place} has been offline for {_duration(minutes)} "
                                                f"({TYPES[d['kind']]})"))
                if d["mac"] not in OFFLINE_ALERTED:
                    log.warning("Offline: %s%s for %s (%s)", d["name"], place, _duration(minutes), TYPES[d["kind"]])
    OFFLINE_ALERTED.intersection_update(current)
    OFFLINE_ALERTED.update(current)


def db_stats():
    with dbx() as db:
        rows = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    size = sum(os.path.getsize(p) for p in (CFG["db"], CFG["db"] + "-wal") if os.path.exists(p))
    HEALTH["db"]["detail"] = f"{rows:,} samples · {size / 1e6:.1f} MB".replace(",", ".")
    return rows, size


def prune():
    with dbx() as db:
        limit = time.time() - CFG["retention_days"] * 86400
        deleted = db.execute("DELETE FROM samples WHERE ts < ?", (limit,)).rowcount
        db.execute("DELETE FROM events WHERE ts < ?", (limit,))
    if deleted > 100_000:  # after a major cleanup, it frees up disk space
        con = sqlite3.connect(CFG["db"], timeout=60)
        try:
            con.execute("VACUUM")
        finally:
            con.close()
    rows, size = db_stats()
    log.info("DB cleanup: deleted %d samples older than %d days · %d samples remaining, %.1f MB",
             deleted, CFG["retention_days"], rows, size / 1e6)


# ───────────────────────────── Data collection ─────────────────────────────

def _timed(fn):
    t0 = time.perf_counter()
    try:
        return fn(), time.perf_counter() - t0
    except Exception as exc:
        exc.elapsed = time.perf_counter() - t0
        raise


def _take(future, key, errors, stale):
    health, now = HEALTH[key], time.time()
    health["last_try"] = now
    try:
        value, elapsed = future.result()
    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        health.update(ok=False, duration=getattr(exc, "elapsed", None), last_error=message, fails=health["fails"] + 1)
        errors[health["label"]] = message
        if health["fails"] == 1 or health["fails"] % 20 == 0:  # no flood of duplicate log lines
            log.warning("%s: ERROR · %s (attempt #%d)", health["label"], message, health["fails"])
        log.debug("Error details %s", health["label"], exc_info=True)
        if key in LAST and now - LAST[key][0] < 600:  # keep last good data for up to 10 minutes
            stale[key] = int(now - LAST[key][0])
            return LAST[key][1]
        return None
    if health["fails"]:
        log.info("%s: recovered after %d consecutive errors", health["label"], health["fails"])
    health.update(ok=True, last_ok=now, duration=round(elapsed, 2), fails=0, last_error=None,
                  detail=(value.get("meta") or {}).get("detail", ""))
    LAST[key] = (now, value)
    return value


def _where(d):
    return f"{d['node']} · {d['ap'].split(' · ', 1)[-1]}"  # e.g. "AX55 · 5 GHz", "Opal · 2.4 GHz", "RE700X · 5 GHz"


def detect_events(prev, data, now):
    """Compare two consecutive cycles. Only if both sources were healthy: otherwise they'd be false events."""
    if not (prev and prev.get("clean") and data.get("clean")):
        return []
    before = {d["mac"]: d for d in prev["devices"] if d["connected"]}
    after = {d["mac"]: d for d in data["devices"] if d["connected"]}
    events = []
    for mac, d in after.items():
        old = before.get(mac)
        if old is None:
            events.append((now, mac, d["name"], "connect", None, _where(d)))
        elif old["node"] != d["node"]:
            events.append((now, mac, d["name"], "move_ap", _where(old), _where(d)))
        elif old["group"] != d["group"]:
            events.append((now, mac, d["name"], "move_band", _where(old), _where(d)))
    for mac, old in before.items():
        if mac not in after:
            events.append((now, mac, old["name"], "disconnect", _where(old), None))
    return events


def save_events(events):
    with dbx() as db:
        db.executemany("INSERT INTO events VALUES(?,?,?,?,?,?)", events)


def log_changes(prev, data, events):
    """Records events: connections/disconnections, moves between access points, and uplink changes."""
    if not (prev and prev.get("clean") and data.get("clean")):
        return

    def fmt(items):
        names = [e[2] or e[1] for e in items]
        return ", ".join(names[:8]) + (f" (+{len(names) - 8} others)" if len(names) > 8 else "")

    joined, left = [e for e in events if e[3] == "connect"], [e for e in events if e[3] == "disconnect"]
    if joined or left:
        log.info("Devices · connected: %s · disconnected: %s", fmt(joined) or "—", fmt(left) or "—")
    for e in events:
        if e[3] in ("move_ap", "move_band"):
            log.info("%s: %s from «%s» to «%s»", "AP change" if e[3] == "move_ap" else "Band/network change",
                     e[2] or e[1], e[4], e[5])
    old, new = (prev.get("opal") or {}).get("sta", {}), (data.get("opal") or {}).get("sta", {})
    old_up, new_up = (prev.get("opal") or {}).get("uplink"), (data.get("opal") or {}).get("uplink")
    if old_up and new_up and old_up != new_up:
        log.warning("Opal uplink changed: %s → %s", old_up, new_up)
    elif old.get("bssid") and new.get("bssid") and old["bssid"] != new["bssid"]:
        log.warning("Opal uplink BSSID changed: %s → %s", old["bssid"], new["bssid"])


def _source_summary(key, name):
    h = HEALTH[key]
    if h["ok"] is None:
        return f"{name} disabled"
    if h["ok"]:
        return f"{name} ok {h['duration']:.2f} s" + (f" ({h['detail']})" if h["detail"] else "")
    return f"{name} ERROR" + (f" after {h['duration']:.1f} s" if h["duration"] is not None else "")


def collect():
    global STATE
    started = time.perf_counter()
    errors, stale = {}, {}
    with ThreadPoolExecutor(2) as pool:
        opal_on = bool(CFG["opal_host"])
        f_router = pool.submit(_timed, fetch_home_assistant)
        f_opal = pool.submit(_timed, fetch_opal) if opal_on else None
        router = _take(f_router, "router", errors, stale)
        opal = _take(f_opal, "opal", errors, stale) if f_opal else None
        if not opal_on:
            HEALTH["opal"].update(ok=None, detail="disabled (OPAL_HOST not set)")
    now = round(time.time(), 3)
    data = build(router or dict(fw=None, devices=[]), opal, read_names(), read_meta())
    errors.update(CONFIG_ERRORS)
    data["stale"] = stale
    data["clean"] = router is not None and (opal is not None or not opal_on) and not stale  # fresh sources
    for a in data["aliases"]:
        key = (a["real"], a["via"], a["promoted"])
        if key not in ALIAS_LOGGED:
            ALIAS_LOGGED.add(key)
            log.info("Alias AX55↔Opal: %s (%s) seen through AX55 with the Opal MAC %s%s", a["name"] or a["real"],
                     a["ip"], a["via"], " → treated as ONLINE behind the Opal" if a["promoted"] else "")
    events = detect_events(STATE["data"], data, now)
    saved, db = 0, HEALTH["db"]
    db["last_try"] = now
    for step in (track_seen, save_history, *([lambda _d, _n: save_events(events)] if events else [])):
        try:
            result = step(data, now)
            saved = result if step is save_history else saved
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}"
            errors["database"] = message
            db.update(ok=False, last_error=message, fails=db["fails"] + 1)
            if db["fails"] == 1 or db["fails"] % 20 == 0:
                log.warning("Database: ERROR · %s", message)
    if "database" not in errors:
        db.update(ok=True, last_ok=now, fails=0, last_error=None)
    log_changes(STATE["data"], data, events)
    live = sum(d["connected"] for d in data["devices"])
    with COND:
        META["seq"] += 1
        STATE = dict(ts=now, errors=errors, data=data,
                     health=dict(cycle=META["seq"], poll=CFG["poll"], started=STARTED, sources=copy.deepcopy(HEALTH)))
        COND.notify_all()
    log.info("Cycle %d · %s · %s · %d/%d connected · +%d samples · %.2f s total", META["seq"],
             _source_summary("router", "HA"), _source_summary("opal", "Opal"), live, len(data["devices"]),
             saved, time.perf_counter() - started)


def poll_loop():
    global STATE
    try:
        init_db()
    except Exception as exc:
        STATE = dict(STATE, errors={"database": f"{type(exc).__name__}: {exc}"})
        log.error("Database cannot be initialized: %s", exc)
    last_prune = 0
    while True:
        cycle_start = time.monotonic()
        try:
            collect()
            if time.time() - last_prune > 3600:
                prune()
                last_prune = time.time()
        except Exception as exc:
            STATE = dict(STATE, errors={"collector": f"{type(exc).__name__}: {exc}"})
            log.exception("Unexpected error during the collection cycle")
        WAKE.wait(max(1.0, CFG["poll"] - (time.monotonic() - cycle_start)))  # fixed cadence, not poll + duration
        WAKE.clear()


def start_worker():
    global _started
    if not _started:
        _started = True
        setup_logging()
        opal = (f"Opal {CFG['opal_user']}@{CFG['opal_host']}:{CFG['opal_port']} (AP {CFG['ap_if']}, uplink "
                f"{CFG['sta_if']}, LAN ports {','.join(CFG['lan_ifs']) or '—'})") if CFG["opal_host"] else "Opal disabled"
        log.info("Start · every %d s · HA %s · %s · DB %s (%d d) · auth %s · log %s", CFG["poll"],
                 CFG["ha_url"] or "NOT CONFIGURED", opal, CFG["db"], CFG["retention_days"],
                 "on" if CFG["auth_user"] else "off", logging.getLevelName(log.level))
        threading.Thread(target=poll_loop, daemon=True, name="network-poller").start()


# ───────────────────────────── HTTP ─────────────────────────────

@app.before_request
def guard():
    if CFG["auth_user"]:
        auth = request.authorization
        ok = auth and hmac.compare_digest((auth.username or "").encode(), CFG["auth_user"].encode()) \
            and hmac.compare_digest((auth.password or "").encode(), CFG["auth_pass"].encode())
        if not ok:
            return Response("Authentication required", 401, {"WWW-Authenticate": 'Basic realm="Network map"'})
    # Custom header prevents third-party pages from writing/updating the dashboard (CSRF).
    if request.method in ("POST", "PATCH", "PUT", "DELETE") and request.headers.get("X-Requested-With") != "dashboard":
        return jsonify(error="Invalid request"), 400


@app.get("/")
def index():
    return render_template("index.html", poll=CFG["poll"])


@app.get("/api/data")
def api_data():
    since = request.args.get("since", type=float)
    state = STATE
    if since is not None and state["ts"] == since:
        return jsonify(unchanged=True)
    return jsonify(state)


@app.get("/api/health")
def api_health():
    """200 if everything is fine, 503 otherwise: designed for Uptime Kuma or other monitoring tools."""
    state, now = STATE, time.time()
    if not state["ts"]:
        return jsonify(status="starting"), 503
    failing = [k for k, h in state["health"]["sources"].items() if h["ok"] is False]
    age = int(now - state["ts"])
    ok = not failing and age <= CFG["poll"] * 3
    return jsonify(status="ok" if ok else "degraded", failing=failing, last_cycle_age_s=age,
                   cycles=state["health"]["cycle"]), (200 if ok else 503)


@app.get("/api/events")
def api_events():
    """AP/band changes, connections, and disconnections. ?mac= filters a device, ?hours= sets the time range."""
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
    current = {d["mac"]: d["name"] for d in ((STATE["data"] or {}).get("devices") or [])}

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
    return jsonify(STATE)


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
            return jsonify(error=f"names.json is unreadable: {exc}"), 500
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
    with META_LOCK:
        try:
            meta = read_meta(strict=True)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"meta.json is unreadable: {exc}"), 500
        entry = {k: v for k, v in (("type", kind), ("room", room)) if v}
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
    devices = (STATE["data"] or {}).get("devices", [])
    with META_LOCK:
        try:
            meta = read_meta(strict=True)
        except (OSError, ValueError) as exc:
            return jsonify(error=f"meta.json is unreadable: {exc}"), 500
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
