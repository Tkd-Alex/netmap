import json

import builder
import config
import database
import sources

from conftest import OPAL_OUTPUT, opal, tracker

H = {"X-Requested-With": "dashboard"}


# ───────────── Opal parsing
def test_parse_opal_clients_neighbors_and_local_macs(A):
    parsed = sources.parse_opal(OPAL_OUTPUT)
    assert parsed["clients"]["aa:bb:cc:00:00:01"]["tx"] == 65.0
    assert parsed["clients"]["aa:bb:cc:00:00:01"]["ip"] == "192.168.1.50"
    assert parsed["clients"]["aa:bb:cc:00:00:02"]["rssi"] == -78
    assert parsed["neigh_state"]["aa:bb:cc:00:00:09"] == "STALE"
    assert "94:00:00:00:00:07" in parsed["local_macs"] and "00:00:00:00:00:00" not in parsed["local_macs"]


def test_wired_clients_from_brctl_and_from_bridge_fdb(A):
    assert sources.parse_opal(OPAL_OUTPUT)["wired"] == ["aa:bb:cc:00:00:04"]  # `brctl showmacs` format + ports
    fdb = OPAL_OUTPUT.split("##FDB")[0] + "##FDB\naa:bb:cc:00:00:04 dev eth0.1 master br-lan\n33:33:00:00:00:01 dev eth0.1 self permanent\n"
    assert sources.parse_opal(fdb)["wired"] == ["aa:bb:cc:00:00:04"]  # `bridge fdb show` format


# ───────────── suggested types
def test_suggest_kind(A):
    cases = {"ShellyPlus1 0A1B2C3D4E5F": "luce_presa", "RLC-510A Kitchen": "camera", "Pixel phone": "smartphone",
             "Office PC": "pc", "Philips AC1000": "iot", "Philips Hue lamp": "luce_presa", "string-device": None}
    for name, expected in cases.items():
        assert config.suggest_kind("10:00:00:00:00:01", name) == expected, name
    assert config.suggest_kind("bc:24:11:00:00:01", "qualsiasi") == "server"  # OUI Proxmox


# ───────────── Opal alias ↔ main router
def test_alias_promotes_device_seen_behind_opal(A):
    real, alias = "aa:bb:cc:00:00:09", "94:00:00:00:00:07"
    router = dict(fw="x", devices=[tracker(real, "Purificatore", "192.0.2.220", active=False),
                                   tracker(alias, "Purificatore", "192.0.2.220")])
    data = builder.build(router, sources.parse_opal(OPAL_OUTPUT), {})
    by_mac = {d["mac"]: d for d in data["devices"]}
    assert by_mac[real]["connected"] and by_mac[real]["group"] == "opal_wired" and by_mac[real]["via"]["en"] == "behind the Opal"
    assert alias not in by_mac and not any(a["kind"] == "conflict" for a in data["alerts"] if "kind" in a)


def test_opal_association_beats_alias_and_inactive_alias_is_ignored(A):
    real, alias = "aa:bb:cc:00:00:09", "94:00:00:00:00:07"
    parsed = sources.parse_opal(OPAL_OUTPUT)
    parsed["clients"][real] = dict(rssi=-70, idle_ms=0, ip="192.0.2.220", tx=None, rx=None)
    router = dict(fw="x", devices=[tracker(real, "P", "192.0.2.220", active=False), tracker(alias, "P", "192.0.2.220")])
    device = {d["mac"]: d for d in builder.build(router, parsed, {})["devices"]}[real]
    assert device["group"] == "opal" and device["rssi"] == -70
    parsed = sources.parse_opal(OPAL_OUTPUT)
    router["devices"][1] = tracker(alias, "P", "192.0.2.220", active=False)
    assert not {d["mac"]: d for d in builder.build(router, parsed, {})["devices"]}[real]["connected"]


# ───────────── uplink
def test_uplink_unknown_when_driver_echoes_own_mac_and_router_view_is_used(A):
    parsed = sources.parse_opal(OPAL_OUTPUT.replace("Access Point: 6E:00:00:00:00:08", "Access Point: 6E:00:00:00:00:08"))
    data = builder.build(dict(fw="x", devices=[]), parsed, {})
    assert data["opal"]["uplink"] == "unknown" and not any(a.get("kind") == "uplink" for a in data["alerts"])
    on_extender = tracker("6e:00:00:00:00:08", "Opal", ap="Ext", conn="HOST_5G")
    data = builder.build(dict(fw="x", devices=[on_extender]), parsed, {})
    assert data["opal"]["uplink"] == "Ext" or any("Ext" in a["text"]["en"] for a in data["alerts"])
    assert any(a["kind"] == "uplink" and "Main" in a["text"]["en"] for a in data["alerts"])


# ───────────── roaming and events
def test_events_roaming_and_guard_on_failing_sources(A, cycle, monkeypatch):
    monkeypatch.setitem(config.CFG, "opal_missing_grace", 0)  # leaving the Opal is immediate (grace: see below)
    phone = "10:00:00:00:00:01"
    cycle([tracker(phone, "Telefono", conn="HOST_5G")])
    cycle([tracker(phone, "Telefono", conn="HOST_2G")])                                    # band change
    cycle([], clients=[phone])                                                              # AX55 → Opal
    cycle([tracker(phone, "Telefono", conn="HOST_5G", ap="Ext")])                           # Opal → extender
    cycle([tracker(phone, "Telefono", conn="HOST_5G", ap="Ext")], router_ok=False)          # failing source (stale data)
    cycle([], router_ok=False, opal_ok=False)                                               # everything failing: no false events
    cycle([tracker(phone, "Telefono", conn="HOST_5G", ap="Ext")])                           # recovery
    with database.dbx() as db:
        rows = db.execute("SELECT kind, src, dst FROM events ORDER BY ts, rowid").fetchall()
    assert [r[0] for r in rows] == ["move_band", "move_ap", "move_ap"]
    assert rows[1][1:] == ("AX55 · 2.4 GHz", "Opal · 2.4 GHz") and rows[2][2] == "Ext · 5 GHz"


def test_events_api_summary(A, cycle, monkeypatch):
    monkeypatch.setitem(config.CFG, "opal_missing_grace", 0)  # leaving the Opal is immediate (grace: see below)
    phone = "10:00:00:00:00:01"
    cycle([tracker(phone, "Telefono")])
    cycle([tracker(phone, "Telefono", active=False)], clients=[phone])    # router says offline, Opal associates it
    cycle([tracker(phone, "Telefono", active=False)])
    data = A.app.test_client().get("/api/events?hours=24").get_json()
    assert data["totals"] == {"move_ap": 1, "disconnect": 1}
    assert data["summary"][0]["name"] == "Telefono" and data["summary"][0]["move_ap"] == 1


def test_opal_grace_period_bridges_short_radio_gaps(A, cycle):
    phone = "10:00:00:00:00:01"
    cycle([], clients=[phone])
    device = {d["mac"]: d for d in cycle([])["devices"]}[phone]          # the driver omits the client for one poll
    assert device["connected"] and device["group"] == "opal"
    builder.OPAL_MISSING_SINCE[phone] -= config.CFG["opal_missing_grace"]          # ...until the grace period is over
    assert phone not in {d["mac"] for d in cycle([])["devices"] if d["connected"]}
    with database.dbx() as db:
        assert [r[0] for r in db.execute("SELECT kind FROM events ORDER BY ts, rowid")] == ["disconnect"]


# ───────────── alerts with room and type
def test_weak_signal_alerts_are_grouped_by_room(A):
    meta = {"10:00:00:00:00:01": {"room": "Cucina"}, "10:00:00:00:00:02": {"room": "Cucina"},
            "10:00:00:00:00:03": {"room": "Camera"}}
    devices = [tracker(f"10:00:00:00:00:0{i}", f"Dev{i}", signal=-80) for i in (1, 2, 3)]
    alerts = [a["text"]["en"] for a in builder.build(dict(fw="x", devices=devices), None, {}, meta)["alerts"]]
    assert any(t.startswith("Weak signal in Cucina") and "Dev1" in t and "Dev2" in t for t in alerts)
    assert any("Dev3 · Camera has a weak signal" in t for t in alerts)


def test_new_device_and_offline_alerts(A, cycle, monkeypatch):
    cam, mystery = "10:00:00:00:00:0a", "10:00:00:00:00:0b"
    base = [tracker("10:00:00:00:00:01", "Telefono")]
    cycle(base)                                                                  # baseline: nothing "new"
    monkeypatch.setitem(config.CFG, "offline_types", ["camera"])
    data = cycle(base + [tracker(cam, "Telecamera cucina", "192.168.1.9"), tracker(mystery, "gadget", "192.168.1.10")])
    new = {a["mac"]: a for a in data["alerts"] if a.get("kind") == "new"}
    assert new[cam]["level"] == "info" and "probably Camera / doorbell" in new[cam]["text"]["en"]
    assert "probabile Telecamera" in new[cam]["text"]["it"]
    assert new[mystery]["level"] == "warn" and "unknown type" in new[mystery]["text"]["en"]
    with database.dbx() as db:                                                          # the camera was last seen 15 minutes ago
        db.execute("UPDATE seen SET last_seen = last_seen - 900 WHERE mac = ?", (cam,))
    data = cycle(base + [tracker(cam, "Telecamera cucina", "192.168.1.9", active=False)])
    offline = [a for a in data["alerts"] if a.get("kind") == "offline"]
    assert len(offline) == 1 and "offline for 15 min" in offline[0]["text"]["en"]
    assert "offline da 15 min" in offline[0]["text"]["it"]
    data = cycle(base + [tracker(cam, "Telecamera cucina", "192.168.1.9", active=False)], router_ok=False)
    assert not any(a.get("kind") == "offline" for a in data["alerts"])           # failing source: no false alerts


# ───────────── type/room (API)
def test_meta_api(A, cycle):
    cycle([tracker("10:00:00:00:00:01", "Philips AC1000"), tracker("10:00:00:00:00:02", "Pixel 9", conn="HOST_5G")])
    client, mac = A.app.test_client(), "10:00:00:00:00:01"
    assert client.patch(f"/api/meta/{mac}", json={"type": "iot"}).status_code == 400            # without the anti-CSRF header
    assert client.patch(f"/api/meta/{mac}", json={"type": "mostro"}, headers=H).status_code == 400
    ok = client.patch(f"/api/meta/{mac}", json={"type": "iot", "room": "  Stanza   da letto "}, headers=H)
    assert ok.get_json() == {"ok": True, "type": "iot", "room": "Stanza da letto"}
    assert client.post("/api/meta/apply-suggestions", headers=H).get_json()["applied"] == 1  # only the Pixel
    meta = json.load(open(config.CFG["meta"]))
    assert meta["10:00:00:00:00:02"] == {"type": "smartphone"} and meta[mac]["room"] == "Stanza da letto"
    assert client.patch(f"/api/meta/{mac}", json={"type": "", "room": ""}, headers=H).get_json() == {"ok": True}
    assert mac not in json.load(open(config.CFG["meta"]))


def test_names_api_and_override(A, cycle):
    client = A.app.test_client()
    assert client.patch("/api/names/zz", json={"name": "x"}, headers=H).status_code == 400
    client.patch("/api/names/10-00-00-00-00-01", json={"name": "Lampada"}, headers=H)
    data = cycle([tracker("10:00:00:00:00:01", "hostname-originale")])
    assert data["devices"][0]["name"] == "Lampada" and data["devices"][0]["labeled"]


# ───────────── health, stale data, optional Opal
def test_stale_data_kept_and_health_endpoint(A, cycle):
    cycle([tracker("10:00:00:00:00:01", "Telefono")])
    data = cycle([], router_ok=False)
    assert "router" in data["stale"] and len(data["devices"]) == 1                 # last good data
    assert "Home Assistant · AX55" in builder.STATE["errors"]
    client = A.app.test_client()
    bad = client.get("/api/health")
    assert bad.status_code == 503 and bad.get_json()["status"] == "degraded" and bad.get_json()["failing"] == ["router"]
    cycle([tracker("10:00:00:00:00:01", "Telefono")])
    good = client.get("/api/health")
    assert good.status_code == 200 and set(good.get_json()) == {"status", "failing", "last_cycle_age_s", "cycles"}


def test_opal_is_optional(A, cycle, monkeypatch):
    monkeypatch.setitem(config.CFG, "opal_host", "")
    monkeypatch.setattr(builder, "fetch_opal", lambda: (_ for _ in ()).throw(AssertionError("must not be called")))
    monkeypatch.setattr(builder, "fetch_home_assistant", lambda: dict(fw="x", devices=[tracker("10:00:00:00:00:01", "Telefono")]))
    builder.collect()
    assert builder.STATE["data"]["clean"] and builder.STATE["data"]["opal"] is None and not builder.STATE["errors"]
    assert builder.STATE["health"]["sources"]["opal"]["ok"] is None


def test_auth_and_csrf(A, monkeypatch):
    monkeypatch.setitem(config.CFG, "auth_user", "u")
    monkeypatch.setitem(config.CFG, "auth_pass", "p")
    client = A.app.test_client()
    assert client.get("/api/data").status_code == 401
    import base64
    ok = {"Authorization": "Basic " + base64.b64encode(b"u:p").decode()}
    assert client.get("/api/data", headers=ok).status_code == 200
    assert client.post("/api/refresh", headers=ok).status_code == 400              # X-Requested-With missing


# ───────────── labels: the JSON is the source of truth
def test_rename_is_applied_to_past_events(A, cycle):
    phone = "10:00:00:00:00:01"
    cycle([tracker(phone, "Telefono")])
    cycle([tracker(phone, "Telefono", active=False)])                    # disconnect event with the name it had at the time
    client = A.app.test_client()
    client.patch(f"/api/names/{phone}", json={"name": "Telefono di Anna"}, headers=H)
    cycle([tracker(phone, "Telefono", active=False)])
    data = client.get("/api/events?hours=24").get_json()
    assert data["events"][0]["name"] == "Telefono di Anna" and data["summary"][0]["name"] == "Telefono di Anna"


def test_invalid_json_keeps_last_good_labels_and_is_reported(A, cycle):
    mac = "10:00:00:00:00:01"
    with open(config.CFG["names"], "w", encoding="utf-8") as f:
        f.write('{"10-00-00-00-00-01": "Lampada"}')                      # the format with hyphens is also fine
    assert cycle([tracker(mac, "host")])["devices"][0]["name"] == "Lampada"
    with open(config.CFG["names"], "w", encoding="utf-8") as f:
        f.write('{"10:00:00:00:00:01": "Lampada",}')                     # trailing comma
    data = cycle([tracker(mac, "host")])
    assert data["devices"][0]["name"] == "Lampada" and "names.json" in builder.STATE["errors"]
    assert A.app.test_client().patch(f"/api/names/{mac}", json={"name": "x"}, headers=H).status_code == 500
    with open(config.CFG["names"], "w", encoding="utf-8") as f:
        f.write('{"10:00:00:00:00:01": "Lampada nuova"}')
    assert cycle([tracker(mac, "host")])["devices"][0]["name"] == "Lampada nuova" and "names.json" not in builder.STATE["errors"]


# ───────────── two languages
def test_every_message_for_the_page_exists_in_both_languages(A, cycle):
    meta = {"10:00:00:00:00:01": {"room": "Kitchen"}, "10:00:00:00:00:02": {"room": "Kitchen"}}
    config.CFG["offline_types"] = ["camera"]
    devices = [tracker("10:00:00:00:00:01", "A", ip="192.168.1.5", signal=-80), tracker("10:00:00:00:00:02", "B", ip="192.168.1.5", signal=-80)]
    data = builder.build(dict(fw="x", devices=devices), opal(), {}, meta)
    assert data["alerts"] and all(set(a["text"]) == {"it", "en"} for a in data["alerts"])
    assert all(set(v) == {"it", "en"} for v in data["types"].values())
    cycle([tracker("10:00:00:00:00:01", "A")])
    database.prune()                                                         # refreshes the database detail
    assert set(database.HEALTH["db"]["detail"]) == {"it", "en"} and "samples" in database.HEALTH["db"]["detail"]["en"]


def test_disabled_opal_detail_is_bilingual(A, cycle, monkeypatch):
    monkeypatch.setitem(config.CFG, "opal_host", "")
    monkeypatch.setattr(builder, "fetch_home_assistant", lambda: dict(fw="x", devices=[]))
    builder.collect()
    detail = builder.STATE["health"]["sources"]["opal"]["detail"]
    assert detail["en"].startswith("disabled") and detail["it"].startswith("disattivato")


def test_log_language_defaults_to_english_and_labels_are_neutral(A):
    assert config.LOG_LANG == "en" and str(config.msg("ciao", "hello")) == "hello" and config.L("ciao", "hello") == "hello"
    assert set(config.LABEL.values()) >= {"AX55 · wired", "Opal · wired", "undetermined"}   # neutral tokens, translated by the page
    assert json.loads(json.dumps(config.msg("ciao", "hello"))) == {"it": "ciao", "en": "hello"}
