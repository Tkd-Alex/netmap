"""Persistence: names/meta JSON files, SQLite history, first/last seen, offline alerts, health."""
import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from config import CFG, L, log, LOG_LANG, msg, norm_mac, TYPES, UPLINK_ID


# Health status of each source, shown in the "Diagnostics" panel and at /api/health.
HEALTH = {key: dict(label=label, ok=None, last_ok=None, last_try=None, duration=None, fails=0,
                    last_error=None, detail="")
          for key, label in (("router", "Home Assistant · AX55"), ("opal", "Opal (SSH)"), ("db", "Database"))}
OFFLINE_ALERTED = set()


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
            log.warning(L("%s non leggibile (%s): uso l'ultima versione valida", "%s unreadable (%s): using the last valid version"),
                        name, message)
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
                    where = d["ip"] or d["mac"]
                    guess = (f"probabile {TYPES[d['kind']]['it']}", f"probably {TYPES[d['kind']]['en']}") if d["kind"] \
                        else ("tipo sconosciuto", "unknown type")
                    data["alerts"].append(dict(level="info" if d["kind"] else "warn", kind="new", mac=d["mac"],
                                               text=msg(f"Nuovo dispositivo sulla rete: {d['name']} ({where}) · {guess[0]}",
                                                        f"New device on the network: {d['name']} ({where}) · {guess[1]}")))
            d["last_seen"] = last
        db.executemany("INSERT INTO seen VALUES(?,?,?) ON CONFLICT(mac) DO UPDATE SET last_seen=excluded.last_seen",
                       upserts)
    offline_alerts(data, now)


def _duration(minutes, lang="en"):
    day = "g" if lang == "it" else "d"
    return f"{minutes} min" if minutes < 120 else f"{minutes // 60} h" if minutes < 2880 else f"{minutes // 1440} {day}"


def offline_alerts(data, now):
    """Notifies you if a device of a "critical" type (default: cameras and network) remains offline."""
    current = set()
    if data.get("clean") and CFG["offline_types"]:  # with a faulty source, they would all appear to be offline
        for d in data["devices"]:
            if d["connected"] or d["kind"] not in CFG["offline_types"] or not d.get("last_seen"):
                continue
            minutes = int((now - d["last_seen"]) / 60)
            # if minutes >= CFG["offline_minutes"]:
            if CFG["offline_minutes"] <= minutes <= 2 * 1440:
                place = f" · {d['room']}" if d["room"] else ""
                current.add(d["mac"])
                data["alerts"].append(dict(level="bad" if d["kind"] == "rete" else "warn", kind="offline",
                                           mac=d["mac"], room=d["room"],
                                           text=msg(f"{d['name']}{place} è offline da {_duration(minutes, 'it')} "
                                                    f"({TYPES[d['kind']]['it']})",
                                                    f"{d['name']}{place} has been offline for {_duration(minutes)} "
                                                    f"({TYPES[d['kind']]['en']})")))
                if d["mac"] not in OFFLINE_ALERTED:
                    log.warning(L("Offline: %s%s da %s (%s)", "Offline: %s%s for %s (%s)"), d["name"], place,
                                _duration(minutes, LOG_LANG), TYPES[d["kind"]])
    OFFLINE_ALERTED.intersection_update(current)
    OFFLINE_ALERTED.update(current)


def db_stats():
    with dbx() as db:
        rows = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
    size = sum(os.path.getsize(p) for p in (CFG["db"], CFG["db"] + "-wal") if os.path.exists(p))
    mb = f"{size / 1e6:.1f}"
    HEALTH["db"]["detail"] = msg(f"{rows:,} campioni · {mb} MB".replace(",", "."), f"{rows:,} samples · {mb} MB")
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
    log.info(L("Pulizia DB: eliminati %d campioni più vecchi di %d giorni · restano %d campioni, %.1f MB",
               "DB cleanup: deleted %d samples older than %d days · %d samples left, %.1f MB"),
             deleted, CFG["retention_days"], rows, size / 1e6)
