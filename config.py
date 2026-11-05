"""Netmap configuration (environment variables), constants, type suggestions and bilingual messages."""
import logging
import os
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parent

# LOG language (NETMAP_LANG=it|en, default en). The PAGE language is chosen by the browser.
LOG_LANG = "it" if os.getenv("NETMAP_LANG", "en").lower().startswith("it") else "en"


def L(it, en):
    """Log text in the language chosen via NETMAP_LANG."""
    return it if LOG_LANG == "it" else en


class Msg(dict):
    """Bilingual message: in the API it's {"it": …, "en": …} (the page chooses), in logs str(msg) is used."""

    def __str__(self):
        return self[LOG_LANG]


def msg(it, en):
    return Msg(it=it, en=en)



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
        value = value.strip()
        if value[:1] in ("'", '"') and value[1:].find(value[0]) >= 0:
            value = value[1:1 + value[1:].find(value[0])]  # quoted: keep "#" literally
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].strip()  # drop inline " # comment"
        os.environ.setdefault(key.strip(), value)


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
    opal_missing_grace=max(0, int(os.getenv("OPAL_MISSING_GRACE_SECONDS", "120"))),
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
LABEL = {"wired": "AX55 · wired", "w5": "AX55 · 5 GHz", "w2": "AX55 · 2.4 GHz", "iot": "AX55 · IoT",
         "guest": "AX55 · guest", "opal": "Opal · 2.4 GHz", "opal_wired": "Opal · wired",
         "unknown": "undetermined"}  # neutral tokens: the page translates them
BAND = {"wired": "RJ45", "opal_wired": "RJ45", "w5": "5 GHz", "w2": "2.4 GHz", "iot": "2.4 GHz",
        "guest": "2.4 GHz", "opal": "2.4 GHz"}
TYPES = {"pc": msg("PC / laptop", "PC / laptop"), "server": msg("Server / VM / LXC", "Server / VM / LXC"),
         "smartphone": msg("Smartphone / tablet", "Smartphone / tablet"), "tv": msg("TV / audio / media", "TV / audio / media"),
         "camera": msg("Telecamera / campanello", "Camera / doorbell"),
         "luce_presa": msg("IoT · luci / prese / relè", "IoT · lights / plugs / relays"),
         "iot": msg("IoT · altro", "IoT · other"), "rete": msg("Rete (router / AP)", "Network (router / AP)"),
         "altro": msg("Altro", "Other")}
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
