"""Data sources: Home Assistant (AX55) over HTTP and the GL.iNet Opal (OpenWrt) over SSH."""
import ipaddress
import json
import re
import threading
import time

import requests

from config import CFG, L, log, msg, norm_mac


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
        log.info(L("Opal: nuova sessione SSH verso %s@%s:%s", "Opal: new SSH session to %s@%s:%s"),
                 CFG["opal_user"], CFG["opal_host"], CFG["opal_port"])
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


NEIGH_RANK = {"REACHABLE": 0, "DELAY": 1, "PROBE": 1, "PERMANENT": 2, "NOARP": 2, "STALE": 3}  # lower = fresher


def _networks(text):
    """IPv4 networks the Opal itself has an address in (from `ip -4 addr show`), loopback excluded."""
    nets = set()
    for m in re.finditer(r"\binet (\d+\.\d+\.\d+\.\d+/\d+)", text or ""):
        try:
            net = ipaddress.ip_interface(m.group(1)).network
        except ValueError:
            continue
        if not net.is_loopback:
            nets.add(net)
    return nets


def _pick_neighbors(entries, nets):
    """(ip, mac, state) ARP entries → ({mac: ip}, {mac: state}), netmap's policy for both transports.

    One IP per MAC: the freshest entry wins (a STALE entry left over from an old lease must not hide the
    current one), FAILED/INCOMPLETE entries are ignored, and so are addresses outside the Opal's own networks
    (e.g. a device's setup-mode address), which no monitor could reach. On a tie the lowest IP wins, so the
    result does not depend on the table order (the kernel lists it in hash order, netstatus sorted by IP)."""
    best = {}
    for ip, mac, state in entries:
        if not mac or state in ("FAILED", "INCOMPLETE"):
            continue
        try:
            address = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if nets and not any(address in net for net in nets):
            continue
        mac, key = norm_mac(mac), (NEIGH_RANK.get(state, 4), int(address))
        if mac not in best or key < best[mac][0]:
            best[mac] = (key, ip, state)
    return ({mac: ip for mac, (_rank, ip, _state) in best.items()},
            {mac: state for mac, (_rank, _ip, state) in best.items()})


def parse_opal(output):
    parts = dict(re.findall(r"##(\w+)\n(.*?)(?=\n##\w+\n|\Z)", output, re.S))
    entries = []
    for m in re.finditer(r"^(\d+\.\d+\.\d+\.\d+)\s+dev\s+\S+\s+lladdr\s+([0-9a-fA-F:]{17})(.*)$",
                         parts.get("NEIGH", ""), re.M):
        found = re.search(r"\b(REACHABLE|STALE|DELAY|PROBE|FAILED|PERMANENT|INCOMPLETE|NOARP)\b", m.group(3))
        entries.append((m.group(1), m.group(2), found.group(1) if found else None))
    neighbors, neigh_state = _pick_neighbors(entries, _networks(parts.get("ADDR")))
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
    hostapd_clients = {}
    hostapd_ok = False
    try:
        raw_clients = json.loads(parts.get("HOSTAPD", ""))
        if isinstance(raw_clients, dict):
            hostapd_ok = True
            # `ubus call hostapd.<if> get_clients` answers {"freq": …, "clients": {mac: {…}}}
            if isinstance(raw_clients.get("clients"), dict):
                raw_clients = raw_clients["clients"]
            for raw_mac, details in raw_clients.items():
                if not isinstance(details, dict) or details.get("assoc") is not True or details.get("authorized") is not True:
                    continue
                mac = norm_mac(raw_mac)
                if mac and mac != "00:00:00:00:00:00":
                    hostapd_clients[mac] = dict(rssi=None, idle_ms=None, ip=neighbors.get(mac), tx=None, rx=None)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    ap_info, own = _iw_info(parts.get("AP")), norm_mac(parts.get("MAC", "").strip())
    local = {norm_mac(m) for m in re.findall(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", parts.get("LOCAL", ""))}
    local |= {own, norm_mac(ap_info.get("bssid") or "")}
    local -= {"00:00:00:00:00:00", ""}
    return dict(ap=ap_info, sta=_iw_info(parts.get("STA")), clients=clients, hostapd_clients=hostapd_clients,
                hostapd_ok=hostapd_ok, local_macs=sorted(local), neigh=neighbors, neigh_state=neigh_state,
                wired=sorted(wired), own_mac=own)


def fetch_opal():
    ap, sta = CFG["ap_if"], CFG["sta_if"]
    sections = [("AP", f"iwinfo {ap} info"), ("ASSOC", f"iwinfo {ap} assoclist"),
                ("HOSTAPD", f"ubus call hostapd.{ap} get_clients 2>/dev/null"),
                ("STA", f"iwinfo {sta} info"), ("MAC", f"cat /sys/class/net/{sta}/address"),
                ("NEIGH", "ip neigh show; echo; echo '##ADDR'; ip -4 addr show 2>/dev/null; echo; echo '##LOCAL'; "
                          "cat /sys/class/net/*/address 2>/dev/null")]
    if CFG["lan_ifs"]:
        br = CFG["bridge"]
        sections += [("FDB", f"bridge fdb show 2>/dev/null || brctl showmacs {br} 2>/dev/null"),
                     ("PORTS", f'for p in /sys/class/net/{br}/brif/*; do echo "$(cat $p/port_no) ${{p##*/}}"; done 2>/dev/null')]
    outputs, timings = OPAL.run_sections(sections)
    output = "".join(f"##{name}\n{outputs[name].rstrip()}\n" for name, _ in sections)
    parsed = parse_opal(output)
    log.debug(L("Opal · tempi per comando: %s", "Opal · time per command: %s"), ", ".join(f"{n} {t:.2f} s" for n, t in timings.items()))
    ranked = sorted(timings.items(), key=lambda kv: -kv[1])
    slow = [f"{n} {t:.2f} s" for n, t in (ranked[:2] if sum(timings.values()) >= 2 else
                                           [kv for kv in ranked if kv[1] >= 1])]
    n_wifi, n_wired = len(set(parsed["clients"]) | set(parsed["hostapd_clients"])), len(parsed["wired"])
    session = ("nuova", "new") if OPAL.new_session else ("riusata", "reused")
    parsed["meta"] = dict(detail=msg(
        f"{n_wifi} client Wi-Fi, {n_wired} cavo · SSH {session[0]} · {len(output)} B"
        + (f" · lenti: {', '.join(slow)}" if slow else ""),
        f"{n_wifi} Wi-Fi clients, {n_wired} wired · SSH {session[1]} · {len(output)} B"
        + (f" · slow: {', '.join(slow)}" if slow else "")))
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
            log.warning(L("Home Assistant: template non utilizzabile (%s), uso /api/states",
                          "Home Assistant: template unusable (%s), falling back to /api/states"), exc)
    r = HA.get(f"{CFG['ha_url']}/api/states", headers=headers, timeout=12, verify=CFG["ha_verify"])
    r.raise_for_status()
    states = r.json()
    return ([e for e in states if e.get("entity_id", "").startswith("device_tracker.")], "/api/states",
            len(r.content), len(states))


def fetch_home_assistant():
    if not CFG["ha_url"] or not CFG["ha_token"]:
        raise RuntimeError("Set HA_URL and HA_TOKEN in the .env file to read the router from Home Assistant.")
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
    if not devices:  # e.g. the router integration lost its session (AX55 web UI login): not "everyone left"
        raise RuntimeError(L(f"Home Assistant: {len(entities)} tracker ricevuti ma nessuno valido "
                             "(integrazione del router non disponibile?)",
                             f"Home Assistant: {len(entities)} trackers received but none valid "
                             "(router integration unavailable?)"))
    kb = f"{size / 1024:.0f}"
    detail = (msg(f"{len(entities)} tracker ricevuti, {len(devices)} validi · template · {kb} KB",
                  f"{len(entities)} trackers received, {len(devices)} valid · template · {kb} KB")
              if total is None else
              msg(f"{len(entities)} tracker su {total} entità scaricate · {kb} KB (template non disponibile)",
                  f"{len(entities)} trackers out of {total} entities downloaded · {kb} KB (template unavailable)"))
    return dict(fw=msg("TP-Link AX55 · dati da Home Assistant", "TP-Link AX55 · data from Home Assistant"),
                devices=devices, meta=dict(detail=detail))
