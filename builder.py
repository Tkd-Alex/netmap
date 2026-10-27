"""Device map building, event detection, data collection and the polling worker."""
import copy
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from config import BAND, CFG, GROUP, L, LABEL, log, msg, norm_mac, setup_logging, suggest_kind, TYPES
from sources import fetch_home_assistant, fetch_opal
from database import CONFIG_ERRORS, dbx, HEALTH, init_db, prune, read_meta, read_names, save_history, track_seen


STARTED = time.time()
STATE = {"ts": None, "errors": {}, "data": None, "health": None}  # replaced in its entirety at each cycle (no read locks)
META = {"seq": 0}
COND = threading.Condition()
WAKE = threading.Event()
ALIAS_LOGGED = set()
LAST = {}  # latest valid result for source: {"router": (ts, data), "opal": (ts, data)}
OPAL_MISSING_SINCE = {}  # Opal MACs temporarily absent from radio sources
_started = False


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


def build(router, opal, names, meta=None, previous=None, now=None, allow_opal_grace=True):
    now = time.time() if now is None else now
    previous_devices = {d["mac"]: d for d in (previous or {}).get("devices", [])}
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
        wifi_clients = dict(opal.get("hostapd_clients", {}))
        wifi_clients.update(opal.get("clients", {}))  # iwinfo adds RSSI/traffic when available
        for mac, client in wifi_clients.items():
            item = row(mac)
            item.update(group="opal", rssi=client.get("rssi"), connected=True, ssid=essid, ap_name="GL.iNet Opal",
                        connection="Wi-Fi 2.4 GHz", ip=item["ip"] or client.get("ip"),
                        tx=client.get("tx") if client.get("tx") is not None else item["tx"],
                        rx=client.get("rx") if client.get("rx") is not None else item["rx"])
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
                            ap_name="GL.iNet Opal", connection=msg("dietro l'Opal", "behind the Opal"),
                            via=msg("dietro l'Opal", "behind the Opal"),
                            ip=item["ip"] or entry["ip"], name=item["name"] or entry["name"])
            aliases.append(dict(real=real, via=mac, ip=entry["ip"], name=item["name"] or entry["name"],
                                promoted=promoted))
    # Avoid false disconnects when the driver omits an Opal client for some polls.
    # The hostapd view is the primary source; grace covers short gaps in either view.
    current_opal = {mac for mac, item in table.items() if item.get("connected") and item.get("group") == "opal"}
    for mac, old in previous_devices.items():
        if old.get("group") != "opal" or not old.get("connected"):
            OPAL_MISSING_SINCE.pop(mac, None)
            continue
        if mac in current_opal:
            OPAL_MISSING_SINCE.pop(mac, None)
            continue
        if not allow_opal_grace or not opal or CFG["opal_missing_grace"] <= 0:
            OPAL_MISSING_SINCE.pop(mac, None)
            continue
        missing_since = OPAL_MISSING_SINCE.setdefault(mac, now)
        if now - missing_since < CFG["opal_missing_grace"]:
            item = row(mac)
            # Keep the previous row without inventing new radio data.
            for key in ("ip", "name", "group", "rssi", "tx", "rx", "connected", "ssid", "ap_name",
                        "connection", "alias", "via"):
                if key in old:
                    item[key] = old[key]
            item["connected"] = True
        else:
            OPAL_MISSING_SINCE.pop(mac, None)

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
            alerts.append(dict(level="bad", kind="conflict", text=msg(f"Conflitto IP {ip}: {', '.join(owners)}",
                                                                      f"IP conflict {ip}: {', '.join(owners)}")))
    weak = {}
    for d in live:
        if d["rssi"] is not None and d["rssi"] <= CFG["rssi_warn"]:
            weak.setdefault((d["room"], d["node"]), []).append(d)
    for (room, where), items in weak.items():
        if room and len(items) >= 2:  # multiple weak devices in the same room: single warning, likely a coverage issue
            detail = ", ".join(f"{d['name']} ({d['rssi']} dBm)" for d in items)
            alerts.append(dict(level="warn", kind="weak", room=room,
                               text=msg(f"Segnale debole in {room} su {where}: {detail}",
                                        f"Weak signal in {room} on {where}: {detail}")))
        else:
            for d in items:
                place = f" · {d['room']}" if d["room"] else ""
                alerts.append(dict(level="warn", kind="weak", mac=d["mac"], room=d["room"],
                                   text=msg(f"{d['name']}{place} ha segnale debole su {where} ({d['rssi']} dBm)",
                                            f"{d['name']}{place} has a weak signal on {where} ({d['rssi']} dBm)")))

    opal_out = None
    if opal:
        sta = opal["sta"]
        bssid = (sta.get("bssid") or "").lower()
        via = ((opal_view or {}).get("ap_name") or "").strip() if opal_view and opal_view["connected"] else ""
        uplink = "unknown"
        if via:  # most reliable source: what the AX55/OneMesh reports for the Opal wlan-sta0 MAC
            uplink = via
            if CFG["uplink_expected"] and CFG["uplink_expected"].lower() not in via.lower():
                alerts.append(dict(level="warn", kind="uplink", text=msg(
                    f"L'Opal risulta agganciato a «{via}» invece di «{CFG['uplink_expected']}»",
                    f"The Opal is attached to «{via}» instead of «{CFG['uplink_expected']}»")))
        elif bssid and bssid != own:  # if BSSID matches the Opal MAC the driver doesn't really report it
            mid = bssid[3:14]
            uplink = ("AX55" if any(m[3:14] == mid for m in CFG["ax_macs"]) else
                      "RE700X" if any(m[3:14] == mid for m in CFG["re_macs"]) else "other AP")
            if uplink in ("RE700X", "other AP"):
                alerts.append(dict(level="warn", kind="uplink", text=msg(
                    f"L'Opal è agganciato a {bssid} ({uplink}), non al router principale",
                    f"The Opal is attached to {bssid} ({uplink}), not to the main router")))
        if sta.get("signal") is not None and sta["signal"] <= CFG["uplink_warn"]:
            alerts.append(dict(level="warn", kind="uplink", text=msg(f"Uplink dell'Opal debole ({sta['signal']} dBm)",
                                                                     f"Opal uplink is weak ({sta['signal']} dBm)")))
        snr = sta["signal"] - sta["noise"] if sta.get("signal") is not None and sta.get("noise") is not None else None
        opal_out = dict(ap=opal["ap"], sta=sta, uplink=uplink, own_mac=own, snr=snr)
    return dict(router=dict(fw=router.get("fw")), opal=opal_out, devices=devices, alerts=alerts,
                thresholds=dict(good=CFG["rssi_good"], warn=CFG["rssi_warn"]), aliases=aliases, types=TYPES)


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
            log.warning(L("%s: ERRORE · %s (tentativo n. %d)", "%s: ERROR · %s (attempt #%d)"),
                        health["label"], message, health["fails"])
        log.debug(L("Dettaglio errore %s", "Error details %s"), health["label"], exc_info=True)
        if key in LAST and now - LAST[key][0] < 600:  # keep the last valid data point for up to 10 minutes
            stale[key] = int(now - LAST[key][0])
            return LAST[key][1]
        return None
    if health["fails"]:
        log.info(L("%s: ripristinato dopo %d errori consecutivi", "%s: recovered after %d consecutive errors"),
                 health["label"], health["fails"])
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
        return ", ".join(names[:8]) + (L(f" (+{len(names) - 8} altri)", f" (+{len(names) - 8} more)") if len(names) > 8 else "")

    joined, left = [e for e in events if e[3] == "connect"], [e for e in events if e[3] == "disconnect"]
    if joined or left:
        log.info(L("Dispositivi · connessi: %s · disconnessi: %s", "Devices · connected: %s · disconnected: %s"),
                 fmt(joined) or "—", fmt(left) or "—")
    for e in events:
        if e[3] in ("move_ap", "move_band"):
            log.info(L("%s: %s da «%s» a «%s»", "%s: %s from «%s» to «%s»"),
                     L("Cambio AP", "AP change") if e[3] == "move_ap" else L("Cambio banda/rete", "Band/network change"),
                     e[2] or e[1], e[4], e[5])
    old, new = (prev.get("opal") or {}).get("sta", {}), (data.get("opal") or {}).get("sta", {})
    old_up, new_up = (prev.get("opal") or {}).get("uplink"), (data.get("opal") or {}).get("uplink")
    if old_up and new_up and old_up != new_up:
        log.warning(L("Uplink Opal cambiato: %s → %s", "Opal uplink changed: %s → %s"), old_up, new_up)
    elif old.get("bssid") and new.get("bssid") and old["bssid"] != new["bssid"]:
        log.warning(L("BSSID dell'uplink Opal cambiato: %s → %s", "Opal uplink BSSID changed: %s → %s"),
                    old["bssid"], new["bssid"])


def _source_summary(key, name):
    h = HEALTH[key]
    if h["ok"] is None:
        return f"{name} " + L("disattivato", "disabled")
    if h["ok"]:
        return f"{name} ok {h['duration']:.2f} s" + (f" ({h['detail']})" if h["detail"] else "")
    return f"{name} " + L("ERRORE", "ERROR") + (L(f" dopo {h['duration']:.1f} s", f" after {h['duration']:.1f} s")
                                                 if h["duration"] is not None else "")


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
            HEALTH["opal"].update(ok=None, detail=msg("disattivato (OPAL_HOST non impostato)",
                                                      "disabled (OPAL_HOST not set)"))
    now = round(time.time(), 3)
    opal_fresh = opal is not None and "opal" not in stale
    data = build(router or dict(fw=None, devices=[]), opal, read_names(), read_meta(),
                 previous=STATE.get("data"), now=now, allow_opal_grace=opal_fresh)
    errors.update(CONFIG_ERRORS)
    data["stale"] = stale
    data["clean"] = router is not None and (opal is not None or not opal_on) and not stale  # fresh sources
    for a in data["aliases"]:
        key = (a["real"], a["via"], a["promoted"])
        if key not in ALIAS_LOGGED:
            ALIAS_LOGGED.add(key)
            log.info(L("Alias AX55↔Opal: %s (%s) è visto dall'AX55 con il MAC dell'Opal %s%s",
                       "AX55↔Opal alias: %s (%s) is seen by the AX55 with the Opal's MAC %s%s"),
                     a["name"] or a["real"], a["ip"], a["via"],
                     L(" → considerato ONLINE dietro l'Opal", " → treated as ONLINE behind the Opal") if a["promoted"] else "")
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
                log.warning(L("Database: ERRORE · %s", "Database: ERROR · %s"), message)
    if "database" not in errors:
        db.update(ok=True, last_ok=now, fails=0, last_error=None)
    log_changes(STATE["data"], data, events)
    live = sum(d["connected"] for d in data["devices"])
    with COND:
        META["seq"] += 1
        STATE = dict(ts=now, errors=errors, data=data,
                     health=dict(cycle=META["seq"], poll=CFG["poll"], started=STARTED, sources=copy.deepcopy(HEALTH)))
        COND.notify_all()
    log.info(L("Ciclo %d · %s · %s · %d/%d connessi · +%d campioni · %.2f s totali",
               "Cycle %d · %s · %s · %d/%d connected · +%d samples · %.2f s total"), META["seq"],
             _source_summary("router", "HA"), _source_summary("opal", "Opal"), live, len(data["devices"]),
             saved, time.perf_counter() - started)


def poll_loop():
    global STATE
    try:
        init_db()
    except Exception as exc:
        STATE = dict(STATE, errors={"database": f"{type(exc).__name__}: {exc}"})
        log.error(L("Database non inizializzabile: %s", "Cannot initialize the database: %s"), exc)
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
            log.exception(L("Errore imprevisto nel ciclo di raccolta", "Unexpected error in the collection cycle"))
        WAKE.wait(max(1.0, CFG["poll"] - (time.monotonic() - cycle_start)))  # fixed cadence, not poll + duration
        WAKE.clear()


def start_worker():
    global _started
    if not _started:
        _started = True
        setup_logging()
        lan = ",".join(CFG["lan_ifs"]) or "—"
        opal = (f"Opal {CFG['opal_user']}@{CFG['opal_host']}:{CFG['opal_port']} "
                + L(f"(AP {CFG['ap_if']}, uplink {CFG['sta_if']}, porte LAN {lan})",
                    f"(AP {CFG['ap_if']}, uplink {CFG['sta_if']}, LAN ports {lan})")) if CFG["opal_host"] \
            else L("Opal disattivato", "Opal disabled")
        log.info(L("Avvio · ogni %d s · HA %s · %s · DB %s (%d g) · auth %s · log %s",
                   "Start · every %d s · HA %s · %s · DB %s (%d d) · auth %s · log %s"), CFG["poll"],
                 CFG["ha_url"] or L("NON CONFIGURATO", "NOT CONFIGURED"), opal, CFG["db"], CFG["retention_days"],
                 L("attiva", "on") if CFG["auth_user"] else L("disattiva", "off"), logging.getLevelName(log.level))
        threading.Thread(target=poll_loop, daemon=True, name="network-poller").start()
