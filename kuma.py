"""Uptime Kuma sync: one monitor per opted-in device, keyed by MAC (Socket.IO API, tested on Kuma 2.5).

A monitor is Netmap's only if it has the "netmap" tag AND its description is "MAC(<MAC>)" (upper case).
Netmap never edits, pauses or deletes any other monitor, and never deletes a monitor at all: opted-out
or vanished devices are paused. Removing the "netmap" tag by hand releases a monitor from Netmap.
On managed monitors Netmap owns the name, address, check settings and tags.
"""
import re
import threading
import time

from config import CFG, L, log, msg
from database import HEALTH

MARK = re.compile(r"^MAC\(([0-9A-F]{2}(?::[0-9A-F]{2}){5})\)$", re.M)
PREVIOUS = re.compile(r"^MAC=([0-9A-F]{2}(?::[0-9A-F]{2}){5})$", re.M)  # second format (with tag): rewritten too
LEGACY = re.compile(r"^netmap:([0-9a-f]{2}(?::[0-9a-f]{2}){5})$", re.M)  # first format: adopted, then rewritten
TAG = "netmap"
TYPE_TAG = {"pc": "PC", "server": "Server", "smartphone": "Smartphone", "tv": "Media", "camera": "Camera",
            "luce_presa": "Lights-Plugs", "iot": "IoT", "rete": "Network", "altro": "Other"}
CONN_TAG = {"wired": "Wired", "w5": "5G", "w2": "2.4G", "iot": "IoT-2.4G", "guest": "Guest",
            "opal": "Opal-2.4G", "opal_wired": "Opal-Wired"}
COLOR = {"netmap": "#059669", "room": "#DB2777", "type": "#7C3AED", "conn": "#fd7e14"}
STATUS = {0: "down", 1: "up", 2: "pending", 3: "maintenance"}
RECHECK = 600   # seconds: a monitor whose desired state did not change is re-read from Kuma at most this often
TIMEOUT = 15


class Session:
    """Persistent, logged-in Socket.IO connection. Pushed data (monitor list, heartbeats) is cached."""

    def __init__(self):
        self.sio = None
        self.listing = {}     # monitor id → monitor, as last pushed by Kuma
        self.beats = {}       # monitor id → latest heartbeat status
        self.listed = threading.Event()

    @property
    def alive(self):
        return self.sio is not None and self.sio.connected

    def connect(self):
        import socketio  # imported lazily: Netmap runs without the dependency when Kuma is disabled
        self.close()
        sio = socketio.Client(reconnection=False)
        sio.on("monitorList", self._on_list)
        sio.on("updateMonitorIntoList", self._on_update)
        sio.on("deleteMonitorFromList", self._on_delete)
        sio.on("heartbeat", self._on_beat)
        sio.on("heartbeatList", self._on_beat_list)
        self.listed.clear()
        sio.connect(CFG["kuma_url"], transports=["websocket"], wait_timeout=10)
        self.sio = sio
        res = sio.call("login", {"username": CFG["kuma_user"], "password": CFG["kuma_pass"], "token": ""},
                       timeout=TIMEOUT) or {}
        if not res.get("ok"):
            self.close()
            raise RuntimeError(f"login failed: {res.get('msg') or res}")
        if not self.listed.wait(TIMEOUT):
            self.close()
            raise RuntimeError("no monitor list received after login")

    def close(self):
        if self.sio is not None:
            try:
                self.sio.disconnect()
            except Exception:
                pass
        self.sio = None

    def call(self, event, *args):
        res = self.sio.call(event, args[0] if len(args) == 1 else args, timeout=TIMEOUT)
        if isinstance(res, dict) and res.get("ok") is False:
            raise RuntimeError(f"{event}: {res.get('msg')}")
        return res

    # pushed events (python-socketio runs each handler in its own thread: keep them tiny)
    def _on_list(self, data):
        self.listing = {int(k): v for k, v in (data or {}).items()}
        self.listed.set()

    def _on_update(self, data):
        listing = dict(self.listing)
        listing.update({int(k): v for k, v in (data or {}).items()})
        self.listing = listing

    def _on_delete(self, monitor_id):
        listing = dict(self.listing)
        listing.pop(int(monitor_id), None)
        self.listing = listing

    def _on_beat(self, beat):
        if isinstance(beat, dict) and beat.get("monitorID") is not None:
            self.beats[int(beat["monitorID"])] = beat.get("status")

    def _on_beat_list(self, monitor_id, beats, *_):
        if beats:
            latest = max(beats, key=lambda b: str(b.get("time") or ""))
            self.beats[int(monitor_id)] = latest.get("status")


SESSION = Session()
DONE = {}       # mac → (signature, monitor id, ts) of the last successful sync for that device
ENABLED = {}    # mac → opt-in seen in the previous sync (a change to "on" resumes a paused monitor)
_LOCK = threading.Lock()


def owner(monitor):
    """Lower-case MAC of the device a monitor belongs to, or None if it is not Netmap's."""
    text = monitor.get("description") or ""
    legacy = LEGACY.search(text)
    if legacy:
        return legacy.group(1)
    found = MARK.search(text) or PREVIOUS.search(text)
    if found and any(t.get("name") == TAG for t in monitor.get("tags") or []):
        return found.group(1).lower()
    return None


def managed(listing):
    """mac → monitor for every monitor Netmap owns (lowest id wins if a MAC appears twice)."""
    out = {}
    for mid in sorted(listing):
        mac = owner(listing[mid])
        if mac:
            out.setdefault(mac, listing[mid])
    return out


def desired(d, current=None):
    """Monitor fields Netmap wants for a device. Without an IP the last known address is kept."""
    ip = d.get("ip") or (current or {}).get("hostname")
    check = d["kuma"]["check"]
    fields = dict(name=f"{d['name']} ({ip})" if ip else d["name"], hostname=ip,
                  description=f"MAC({d['mac'].upper()})")
    if check == "alexa":
        fields.update(type="port", port=CFG["kuma_alexa_port"])
    elif check == "shelly":
        fields.update(type="json-query", url=f"http://{ip}/rpc/Shelly.GetStatus", jsonPath="$number(wifi.rssi)",
                      jsonPathOperator=">", expectedValue=str(CFG["kuma_shelly_expected"]))
    else:
        fields.update(type="ping")
    return fields


def desired_tags(d, current=None):
    tags = {TAG: COLOR["netmap"]}
    if d.get("room"):
        tags[d["room"]] = COLOR["room"]
    if d.get("kind") and not d.get("kind_auto") and d["kind"] in TYPE_TAG:
        tags[TYPE_TAG[d["kind"]]] = COLOR["type"]
    if d.get("connected") and d.get("group") in CONN_TAG:
        tags[CONN_TAG[d["group"]]] = COLOR["conn"]
    else:  # offline: keep the last known connection tag instead of dropping it
        for t in (current or {}).get("tags") or []:
            if t.get("name") in CONN_TAG.values():
                tags[t["name"]] = COLOR["conn"]
    return tags


def new_monitor(fields):
    interval = CFG["kuma_interval"]
    monitor = dict(interval=interval, retryInterval=interval, maxretries=2, resendInterval=0,
                   timeout=int(interval * 0.8), method="GET", accepted_statuscodes=["200-299"],
                   notificationIDList={}, conditions=[], kafkaProducerBrokers=[],
                   kafkaProducerSaslOptions={"mechanism": "None"}, rabbitmqNodes=[], ignoreTls=False,
                   upsideDown=False, maxredirects=10, packetSize=56, ping_count=1, ping_numeric=True,
                   ping_per_request_timeout=2, httpBodyEncoding="json", jsonPathOperator="==", parent=None,
                   url="https://", port=None)
    monitor.update(fields)
    return monitor


class Sync:
    def __init__(self, session):
        self.s = session
        self.tag_ids = None
        self.changes = []

    def tag_id(self, name, color):
        if self.tag_ids is None:
            self.tag_ids = {t["name"]: t["id"] for t in (self.s.call("getTags") or {}).get("tags", [])}
        if name not in self.tag_ids:
            tag = self.s.call("addTag", {"name": name, "color": color})["tag"]
            self.tag_ids[name] = tag["id"]
        return self.tag_ids[name]

    def fetch(self, monitor_id):
        return self.s.call("getMonitor", monitor_id)["monitor"]

    def device(self, d, monitor, now):
        mac, cfg = d["mac"], d["kuma"]
        was = ENABLED.get(mac)
        ENABLED[mac] = cfg["enabled"]
        if not cfg["enabled"]:
            if monitor and monitor.get("active"):
                self.s.call("pauseMonitor", monitor["id"])
                self.changes.append(f"pause {d['name']}")
            return
        if monitor is None:
            if not d.get("ip"):
                return  # nothing to point the monitor at yet
            fields = desired(d)
            res = self.s.call("add", new_monitor(fields))
            monitor = dict(id=int(res["monitorID"]), tags=[], active=True, **fields)
            self.changes.append(f"add {fields['name']}")
            log.info(L("Uptime Kuma: creato il monitor %s (%s)", "Uptime Kuma: created monitor %s (%s)"),
                     fields["name"], fields["type"])
        sig = repr((sorted(desired(d, monitor).items()), sorted(desired_tags(d, monitor))))
        last = DONE.get(mac)
        if last and last[0] == sig and last[1] == monitor["id"] and now - last[2] < RECHECK and was is not False:
            return
        current = self.fetch(monitor["id"])  # authoritative copy (the pushed list may lag behind our writes)
        fields = desired(d, current)
        diff = {k: v for k, v in fields.items() if current.get(k) != v}
        if diff:
            if "hostname" in diff and current.get("hostname"):
                log.info(L("Uptime Kuma: %s · indirizzo %s → %s", "Uptime Kuma: %s · address %s → %s"),
                         d["name"], current["hostname"], fields["hostname"])
            self.s.call("editMonitor", dict(current, **fields))
            self.changes.append(f"edit {fields['name']}: {', '.join(sorted(diff))}")
        self.sync_tags(current, desired_tags(d, current))
        if was is False and not current.get("active"):
            self.s.call("resumeMonitor", current["id"])  # resumed only when the user switched it back on
            self.changes.append(f"resume {d['name']}")
        DONE[mac] = (sig, current["id"], now)

    def sync_tags(self, monitor, want):
        have = {t["name"]: t for t in monitor.get("tags") or []}
        for name, color in want.items():
            if name not in have:
                self.s.call("addMonitorTag", self.tag_id(name, color), monitor["id"], "")
                self.changes.append(f"tag +{name} {monitor['name']}")
        for name, t in have.items():
            if name not in want:
                self.s.call("deleteMonitorTag", t["tag_id"], monitor["id"], t.get("value") or "")
                self.changes.append(f"tag -{name} {monitor['name']}")


def sync(data, now=None):
    """Reconcile Kuma with the current cycle. Runs only on clean data: stale sources never rewrite addresses."""
    if not CFG["kuma_url"]:
        return
    if not data or not data.get("clean") or not data.get("devices"):
        return
    now = time.time() if now is None else now
    health = HEALTH["kuma"]
    health["last_try"] = now
    t0 = time.perf_counter()
    with _LOCK:
        try:
            if not SESSION.alive:
                SESSION.connect()
            job, by_mac = Sync(SESSION), managed(SESSION.listing)
            for mac, (_sig, mid, _ts) in DONE.items():  # our writes (new monitor, its tag) may not be pushed yet
                if mac not in by_mac:
                    by_mac[mac] = SESSION.listing.get(mid) or dict(id=mid, active=True, tags=[])
            seen = set()
            for d in data["devices"]:
                seen.add(d["mac"])
                job.device(d, by_mac.get(d["mac"]), now)
            for mac, monitor in by_mac.items():  # device no longer known to any source
                if mac not in seen and monitor.get("active"):
                    SESSION.call("pauseMonitor", monitor["id"])
                    job.changes.append(f"pause {monitor.get('name')} (device gone)")
        except Exception as exc:
            SESSION.close()
            message = f"{type(exc).__name__}: {exc}"
            health.update(ok=False, duration=round(time.perf_counter() - t0, 2), last_error=message,
                          fails=health["fails"] + 1)
            if health["fails"] == 1 or health["fails"] % 20 == 0:
                log.warning(L("Uptime Kuma: ERRORE · %s (tentativo n. %d)", "Uptime Kuma: ERROR · %s (attempt #%d)"),
                            message, health["fails"])
            log.debug("Uptime Kuma", exc_info=True)
            return
    if health["fails"]:
        log.info(L("Uptime Kuma: ripristinato dopo %d errori", "Uptime Kuma: recovered after %d errors"), health["fails"])
    for change in job.changes:
        log.debug("Uptime Kuma: %s", change)
    if job.changes:
        log.info(L("Uptime Kuma: %d modifiche", "Uptime Kuma: %d changes"), len(job.changes))
    mine = managed(SESSION.listing)
    up = sum(SESSION.beats.get(m["id"]) == 1 for m in mine.values() if m.get("active"))
    health.update(ok=True, last_ok=now, duration=round(time.perf_counter() - t0, 2), fails=0, last_error=None,
                  detail=msg(f"{len(mine)} monitor Netmap · {up} up", f"{len(mine)} Netmap monitors · {up} up"))


def annotate(data):
    """Adds the last known Kuma state to each device (cached data only, no network calls)."""
    if not CFG["kuma_url"]:
        HEALTH["kuma"].update(ok=None, detail=msg("disattivato (KUMA_URL non impostato)", "disabled (KUMA_URL not set)"))
        data["kuma"] = dict(enabled=False)
        return
    data["kuma"] = dict(enabled=True, url=CFG["kuma_url"])
    mine = managed(SESSION.listing)
    for d in data["devices"]:
        m = mine.get(d["mac"])
        if m:
            status = STATUS.get(SESSION.beats.get(m["id"])) if m.get("active") else "paused"
            d["kuma"].update(monitor=m["id"], status=status)
        else:
            d["kuma"].update(monitor=None, status=None)
