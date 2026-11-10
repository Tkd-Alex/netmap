import copy
import json

import pytest

import builder
import config
import database
import kuma

from conftest import tracker

H = {"X-Requested-With": "dashboard"}
FOREIGN = dict(id=16, name="ShellyPlus2PM (192.168.1.118)", type="json-query", hostname="192.168.1.118", active=True,
               description="Import statico\nMAC: aa:bb:cc:00:00:02\n", tags=[dict(tag_id=4, name="Cucina", value="")])


class FakeKuma:
    """In-memory stand-in for the Kuma Socket.IO API, with the same event names and reply shapes."""

    def __init__(self):
        self.monitors = {16: copy.deepcopy(FOREIGN)}
        self.tags = {4: "Cucina"}
        self.calls = []
        self.beats = {}
        self.alive = True
        self.deleted = set()
        self.since = 0.0

    @property
    def listing(self):
        return self.monitors

    def connect(self):
        self.alive = True

    def close(self):
        self.alive = False

    def call(self, event, *args):
        self.calls.append((event, args))
        if event == "getTags":
            return dict(ok=True, tags=[dict(id=i, name=n, color="#000") for i, n in self.tags.items()])
        if event == "addTag":
            tid = max(self.tags) + 1
            self.tags[tid] = args[0]["name"]
            return dict(ok=True, tag=dict(id=tid, name=args[0]["name"]))
        if event == "add":
            mid = max(self.monitors) + 1
            self.monitors[mid] = dict(copy.deepcopy(args[0]), id=mid, active=True, tags=[])
            return dict(ok=True, monitorID=mid)
        if event == "getMonitor":
            return dict(ok=True, monitor=copy.deepcopy(self.monitors[args[0]]))
        if event == "editMonitor":
            mon = args[0]
            self.monitors[mon["id"]] = dict(copy.deepcopy(mon), tags=self.monitors[mon["id"]]["tags"])
            return dict(ok=True, monitorID=mon["id"])
        if event == "addMonitorTag":
            tid, mid, value = args
            self.monitors[mid]["tags"].append(dict(tag_id=tid, name=self.tags[tid], value=value))
            return dict(ok=True)
        if event == "deleteMonitorTag":
            tid, mid, value = args
            self.monitors[mid]["tags"] = [t for t in self.monitors[mid]["tags"] if t["tag_id"] != tid]
            return dict(ok=True)
        if event in ("pauseMonitor", "resumeMonitor"):
            self.monitors[args[0]]["active"] = event == "resumeMonitor"
            return dict(ok=True)
        raise AssertionError(event)

    def mine(self):
        return {kuma.owner(m): m for m in self.monitors.values() if kuma.owner(m)}

    def writes(self):
        return [c for c in self.calls if c[0] not in ("getTags", "getMonitor")]


@pytest.fixture()
def K(A, monkeypatch):
    fake = FakeKuma()
    monkeypatch.setattr(kuma, "SESSION", fake)
    monkeypatch.setitem(config.CFG, "kuma_url", "http://kuma.invalid:3001")
    kuma.DONE.clear()
    kuma.ENABLED.clear()
    database.HEALTH["kuma"].update(ok=None, fails=0, last_error=None)
    return fake


DEVICES = [tracker("aa:bb:cc:00:00:01", "echo-dot-kitchen", "192.168.1.126", conn="IOT_2G"),
           tracker("aa:bb:cc:00:00:02", "ShellyPlus2PM-30C9", "192.168.1.118", conn="IOT_2G"),
           tracker("aa:bb:cc:00:00:03", "RLC-510A garden", "192.168.1.60", conn="WIRED"),
           tracker("aa:bb:cc:00:00:04", "Pixel phone", "192.168.1.70", conn="HOST_5G")]


def run(cycle, devices=DEVICES):
    data = cycle(devices)
    kuma.sync(data)
    return data


def test_suggest_check():
    assert config.suggest_check("amazon-0472aac153daa0ca") == "alexa"
    assert config.suggest_check("Kitchen", "echo-dot") == "alexa"
    assert config.suggest_check("shellyplus1-fce8") == "shelly"
    assert config.suggest_check("Pixel phone") == "ping"


def test_creates_monitors_by_check_type_and_leaves_foreign_ones_alone(K, cycle):
    run(cycle)
    mine = K.mine()
    assert set(mine) == {"aa:bb:cc:00:00:01", "aa:bb:cc:00:00:02", "aa:bb:cc:00:00:03"}  # phone: not opted in
    alexa, shelly, cam = mine["aa:bb:cc:00:00:01"], mine["aa:bb:cc:00:00:02"], mine["aa:bb:cc:00:00:03"]
    assert (alexa["type"], alexa["hostname"], alexa["port"]) == ("port", "192.168.1.126", 1080)
    assert shelly["type"] == "json-query" and shelly["url"] == "http://192.168.1.118/rpc/Shelly.GetStatus"
    assert (shelly["jsonPath"], shelly["jsonPathOperator"], shelly["expectedValue"]) == ("$number(wifi.rssi)", ">", "-70")
    assert cam["type"] == "ping" and cam["name"] == "RLC-510A garden (192.168.1.60)"
    assert {t["name"] for t in cam["tags"]} == {"netmap", "Wired"}  # type suggested only → no type tag yet
    assert cam["description"] == "MAC(AA:BB:CC:00:00:03)"
    assert K.monitors[16] == FOREIGN  # same MAC as the Shelly, but not Netmap's: untouched
    assert all(args[0] != 16 and (not args or not isinstance(args[0], dict) or args[0].get("id") != 16)
               for _e, args in K.writes())
    assert database.HEALTH["kuma"]["ok"] is True


def test_second_cycle_without_changes_writes_nothing(K, cycle):
    run(cycle)
    before = len(K.writes())
    run(cycle)
    assert len(K.writes()) == before


def test_ip_change_updates_monitor_and_logs_event(K, cycle):
    run(cycle)
    moved = [dict(d) for d in DEVICES]
    moved[1]["ip"] = "192.168.1.200"
    run(cycle, moved)
    shelly = K.mine()["aa:bb:cc:00:00:02"]
    assert shelly["hostname"] == "192.168.1.200" and shelly["url"] == "http://192.168.1.200/rpc/Shelly.GetStatus"
    assert shelly["name"].endswith("(192.168.1.200)") and len(K.mine()) == 3
    with database.dbx() as db:
        assert db.execute("SELECT src, dst FROM events WHERE kind='ip'").fetchall() == [("192.168.1.118", "192.168.1.200")]


def test_tags_follow_room_and_type(K, cycle, A):
    run(cycle)
    client = A.app.test_client()
    client.patch("/api/meta/aa:bb:cc:00:00:03", headers=H, json={"type": "camera", "room": "Giardino"})
    run(cycle)
    assert {t["name"] for t in K.mine()["aa:bb:cc:00:00:03"]["tags"]} == {"netmap", "Wired", "Camera", "Giardino"}
    client.patch("/api/meta/aa:bb:cc:00:00:03", headers=H, json={"type": "camera", "room": "Cucina"})
    run(cycle)
    tags = K.mine()["aa:bb:cc:00:00:03"]["tags"]
    assert {t["name"] for t in tags} == {"netmap", "Wired", "Camera", "Cucina"}
    assert [t["tag_id"] for t in tags if t["name"] == "Cucina"] == [4]  # existing Kuma tag reused


def test_opt_out_pauses_and_opt_in_resumes(K, cycle, A):
    run(cycle)
    client = A.app.test_client()
    client.patch("/api/meta/aa:bb:cc:00:00:01", headers=H, json={"kuma": {"enabled": False}})
    run(cycle)
    assert K.mine()["aa:bb:cc:00:00:01"]["active"] is False
    client.patch("/api/meta/aa:bb:cc:00:00:01", headers=H, json={"kuma": {"enabled": True}})
    run(cycle)
    assert K.mine()["aa:bb:cc:00:00:01"]["active"] is True
    assert not any(e == "delete" or e == "deleteMonitor" for e, _a in K.calls)


def test_manual_pause_in_kuma_is_respected(K, cycle):
    run(cycle)
    K.mine()["aa:bb:cc:00:00:03"]["active"] = False  # paused by hand in Kuma
    kuma.DONE.clear()  # force a full re-read
    run(cycle)
    assert K.mine()["aa:bb:cc:00:00:03"]["active"] is False


def test_check_override_and_opt_in_from_meta(K, cycle, A):
    client = A.app.test_client()
    client.patch("/api/meta/aa:bb:cc:00:00:04", headers=H, json={"kuma": {"enabled": True, "check": "shelly"}})
    run(cycle)
    assert K.mine()["aa:bb:cc:00:00:04"]["type"] == "json-query"


def test_stale_data_never_touches_kuma(K, cycle):
    data = cycle(DEVICES, opal_ok=False)
    assert not data["clean"]
    kuma.sync(data)
    assert K.calls == []


def test_kuma_failure_is_reported_in_health(K, cycle, A):
    def boom(*_a):
        raise RuntimeError("socket closed")
    K.call = boom
    run(cycle)
    assert database.HEALTH["kuma"]["ok"] is False and "socket closed" in database.HEALTH["kuma"]["last_error"]
    cycle(DEVICES)
    assert A.app.test_client().get("/api/health").json["failing"] == ["kuma"]


def test_meta_patch_keeps_and_validates_kuma(K, A):
    client = A.app.test_client()
    mac = "aa:bb:cc:00:00:09"
    assert client.patch(f"/api/meta/{mac}", headers=H, json={"kuma": {"check": "nope"}}).status_code == 400
    client.patch(f"/api/meta/{mac}", headers=H, json={"type": "iot", "kuma": {"enabled": True, "check": "alexa"}})
    client.patch(f"/api/meta/{mac}", headers=H, json={"type": "iot", "room": "Studio"})  # old client: no kuma field
    stored = json.load(open(config.CFG["meta"]))[mac]
    assert stored == {"type": "iot", "room": "Studio", "kuma": {"enabled": True, "check": "alexa"}}
    client.patch(f"/api/meta/{mac}", headers=H, json={"type": "iot", "kuma": {"enabled": None, "check": ""}})
    assert "kuma" not in json.load(open(config.CFG["meta"]))[mac]


def test_annotate_reports_status(K, cycle):
    run(cycle)
    mid = K.mine()["aa:bb:cc:00:00:01"]["id"]
    K.beats[mid] = 0
    data = cycle(DEVICES)
    dev = {d["mac"]: d for d in data["devices"]}
    assert dev["aa:bb:cc:00:00:01"]["kuma"]["status"] == "down"
    assert dev["aa:bb:cc:00:00:04"]["kuma"]["monitor"] is None and data["kuma"]["enabled"] is True


def test_disabled_kuma_is_inert(A, cycle, monkeypatch):
    monkeypatch.setitem(config.CFG, "kuma_url", "")
    data = cycle(DEVICES)
    assert data["kuma"] == {"enabled": False} and database.HEALTH["kuma"]["ok"] is None
    kuma.sync(data)  # no session, no error


def test_description_without_netmap_tag_is_not_ours(K, cycle):
    K.monitors[20] = dict(id=20, name="hand made", type="ping", hostname="192.168.1.60", active=True,
                          description="MAC(AA:BB:CC:00:00:03)", tags=[])
    run(cycle)
    assert K.monitors[20]["name"] == "hand made" and K.monitors[20]["tags"] == []
    assert K.mine()["aa:bb:cc:00:00:03"]["id"] != 20


def test_legacy_description_is_adopted_and_rewritten(K, cycle):
    K.monitors[20] = dict(id=20, name="old", type="ping", hostname="192.168.1.60", active=True,
                          description="netmap:aa:bb:cc:00:00:03\nManaged by Netmap", tags=[])
    run(cycle)
    mon = K.monitors[20]
    assert mon["description"] == "MAC(AA:BB:CC:00:00:03)" and "netmap" in {t["name"] for t in mon["tags"]}
    assert sum(kuma.owner(m) == "aa:bb:cc:00:00:03" for m in K.monitors.values()) == 1


def test_untagged_listing_after_create_does_not_duplicate(K, cycle):
    run(cycle)
    for m in K.monitors.values():  # pushed list lags behind: tags not visible yet
        if m["id"] != 16:
            K.monitors[m["id"]] = dict(m, tags=[])
    kuma.DONE.update({mac: (sig, mid, 0) for mac, (sig, mid, _t) in kuma.DONE.items()})  # force a re-read
    before = len(K.monitors)
    run(cycle)
    assert len(K.monitors) == before


def test_previous_mac_equals_description_is_rewritten(K, cycle):
    K.monitors[20] = dict(id=20, name="old", type="ping", hostname="192.168.1.60", active=True,
                          description="MAC=AA:BB:CC:00:00:03", tags=[dict(tag_id=9, name="netmap", value="")])
    K.tags[9] = "netmap"
    run(cycle)
    assert K.monitors[20]["description"] == "MAC(AA:BB:CC:00:00:03)"
    assert sum(kuma.owner(m) == "aa:bb:cc:00:00:03" for m in K.monitors.values()) == 1


def test_monitor_deleted_in_kuma_is_forgotten_and_recreated(K, cycle):
    run(cycle)
    mac = "aa:bb:cc:00:00:03"
    old = K.mine()[mac]["id"]
    del K.monitors[old]          # deleted by hand in Kuma, Netmap told by the deleteMonitorFromList event
    K.deleted = {old}
    adds = sum(c[0] == "add" for c in K.calls)
    run(cycle)
    assert database.HEALTH["kuma"]["ok"] is True
    assert mac in K.mine() and sum(c[0] == "add" for c in K.calls) == adds + 1


def test_monitor_deleted_while_disconnected_is_forgotten(K, cycle, A):
    run(cycle)
    mac = "aa:bb:cc:00:00:03"
    A.app.test_client().patch(f"/api/meta/{mac}", json=dict(type="camera", kuma=dict(enabled=False)), headers=H)
    del K.monitors[K.mine()[mac]["id"]]
    K.since = 10 ** 12           # fresh login after the deletion: its monitor list is complete
    run(cycle)
    assert database.HEALTH["kuma"]["ok"] is True
    assert mac not in K.mine() and mac not in kuma.DONE
    assert not [c for c in K.calls if c[0] == "pauseMonitor"]
