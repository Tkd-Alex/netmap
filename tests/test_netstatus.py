"""Opal over HTTP (netstatus JSON, schema 2) vs SSH (parse_opal) on the same data.

Fixtures: tests/fixtures/netstatus.json is a real netstatus document, anonymized (MACs → 02:00:00:00:…,
192.168.1.x → 192.0.2.x, SSIDs, hostname, time), plus one wired client on eth0.1 and one client known only
to hostapd, which the real snapshot did not have. tests/fixtures/opal_ssh.txt is the same data written in
the formats of the commands fetch_opal_ssh() runs (iwinfo, ubus, ip, bridge), neighbours in non-IP order.
"""
import copy
import json
from pathlib import Path

import pytest

import app as netmap
import builder
import config
import sources

FIX = Path(__file__).resolve().parent / "fixtures"
DOC = json.loads((FIX / "netstatus.json").read_text(encoding="utf-8"))
SSH = (FIX / "opal_ssh.txt").read_text(encoding="utf-8")
NOW = DOC["time"] + 10


def doc(**changes):
    d = copy.deepcopy(DOC)
    d.update(changes)
    return d


# ───────────── conversion
def test_http_conversion_matches_parse_opal_on_the_same_data(A):
    ssh, http = sources.parse_opal(SSH), sources.opal_from_netstatus(DOC)
    for key in ("clients", "hostapd_clients", "hostapd_ok", "local_macs", "neigh", "neigh_state", "wired", "own_mac"):
        assert http[key] == ssh[key], key
    # Fields netstatus does not carry (AP signal/quality are meaningless in AP mode, uplink tx power) are None;
    # MACs are lower case; the uplink BSSID is the real one from wpa_cli, not the Opal's own MAC echoed by iwinfo.
    for part, missing in (("ap", {"signal", "quality"}), ("sta", {"txpower", "bssid"})):
        assert set(http[part]) == set(ssh[part])
        for field in set(ssh[part]) - missing - {"bssid"}:
            assert http[part][field] == ssh[part][field], (part, field)
    assert http["ap"]["signal"] is http["ap"]["quality"] is http["sta"]["txpower"] is None
    assert http["ap"]["bssid"] == ssh["ap"]["bssid"].lower()
    assert ssh["sta"]["bssid"].lower() == ssh["own_mac"] and http["sta"]["bssid"] == DOC["uplink"]["bssid"]
    assert "checks" in http and "checks" not in ssh


def test_conversion_content(A):
    parsed = sources.opal_from_netstatus(DOC)
    assert parsed["wired"] == ["02:00:00:00:0f:01"]                      # bridge_fdb, local=false, on OPAL_LAN_IF
    assert "02:00:00:00:0f:02" in parsed["hostapd_clients"] and "02:00:00:00:0f:02" not in parsed["clients"]
    assert set(parsed["clients"]) <= set(parsed["hostapd_clients"]) and parsed["hostapd_ok"] is True
    assert all(not ip.startswith("169.254.") for ip in parsed["neigh"].values())  # outside lan.addresses
    assert parsed["neigh"]["02:00:00:00:00:12"] == "192.0.2.51"          # two STALE entries: lowest IP, any order
    assert parsed["own_mac"] == DOC["uplink"]["mac"] and parsed["own_mac"] in parsed["local_macs"]
    assert parsed["checks"] == dict(ok=True, total=15, failed=[])


def test_wired_needs_opal_lan_if_and_wired_macs_are_added(A, monkeypatch):
    monkeypatch.setitem(config.CFG, "lan_ifs", [])
    monkeypatch.setitem(config.CFG, "wired_macs", ["02:00:00:00:0f:09"])
    assert sources.opal_from_netstatus(DOC)["wired"] == sources.parse_opal(SSH)["wired"] == ["02:00:00:00:0f:09"]


def test_neighbor_choice_does_not_depend_on_order(A):
    d = doc()
    d["lan"]["neighbors"].reverse()
    assert sources.opal_from_netstatus(d)["neigh"] == sources.opal_from_netstatus(DOC)["neigh"]


def test_fresh_arp_entry_beats_stale_one(A):
    d = doc()
    d["lan"]["neighbors"].append(dict(ip="192.0.2.99", mac="02:00:00:00:00:12", dev="br-lan", state="REACHABLE", router=False))
    parsed = sources.opal_from_netstatus(d)
    assert parsed["neigh"]["02:00:00:00:00:12"] == "192.0.2.99" and parsed["neigh_state"]["02:00:00:00:00:12"] == "REACHABLE"


def test_hostapd_wrapped_in_clients_is_read_by_parse_opal(A):
    # `ubus call hostapd.<if> get_clients` answers {"freq": …, "clients": {…}}: the clients must not be lost
    assert "02:00:00:00:0f:02" in sources.parse_opal(SSH)["hostapd_clients"]


# ───────────── freshness
@pytest.mark.parametrize("change, match", [
    (dict(schema=1), "schema"),
    (dict(error="boom", ok=False), "boom"),
    (dict(time=DOC["time"] - 91), "old|vecchi"),
    (dict(time=DOC["time"] + 500), "old|vecchi"),
    (dict(time=None), "time"),
])
def test_unusable_documents_are_rejected(A, change, match):
    with pytest.raises(RuntimeError, match=match):
        sources.check_netstatus(doc(**change), now=DOC["time"])


def test_fresh_document_is_accepted(A):
    assert sources.check_netstatus(DOC, now=DOC["time"] + 89) == 89


# ───────────── transport selection
class Answer:
    def __init__(self, body):
        self.content = json.dumps(body).encode()
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def ssh_result():
    parsed = sources.parse_opal(SSH)
    parsed["meta"] = dict(detail=config.msg("ssh", "ssh"))
    return parsed


@pytest.fixture()
def transports(A, monkeypatch):
    calls = []
    state = {"body": doc(time=None)}

    def get(url, **_kw):
        calls.append(("http", url))
        if isinstance(state["body"], Exception):
            raise state["body"]
        return Answer(state["body"])

    def ssh():
        calls.append(("ssh", None))
        return ssh_result()

    monkeypatch.setattr(sources.OPAL_HTTP, "get", get)
    monkeypatch.setattr(sources, "fetch_opal_ssh", ssh)
    monkeypatch.setitem(sources._auto, "retry_at", 0.0)
    monkeypatch.setitem(sources._auto, "reason", None)
    monkeypatch.setattr(sources.time, "time", lambda: NOW)
    return calls, state


def test_auto_prefers_http_and_falls_back_to_ssh(transports, monkeypatch):
    calls, state = transports
    monkeypatch.setitem(config.CFG, "opal_source", "auto")
    state["body"] = DOC
    parsed = sources.fetch_opal()
    assert calls == [("http", config.CFG["opal_url"])] and "checks" in parsed
    assert "HTTP" in parsed["meta"]["detail"]["en"] and "data 10 s old" in parsed["meta"]["detail"]["en"]
    assert "collected in" in parsed["meta"]["detail"]["en"] and "raccolti in" in parsed["meta"]["detail"]["it"]

    state["body"] = doc(time=DOC["time"] - 1000)                   # stale → SSH, and HTTP is not retried at once
    calls.clear()
    parsed = sources.fetch_opal()
    assert calls == [("http", config.CFG["opal_url"]), ("ssh", None)]
    assert "HTTP unavailable" in parsed["meta"]["detail"]["en"] and "HTTP non disponibile" in parsed["meta"]["detail"]["it"]
    calls.clear()
    sources.fetch_opal()
    assert calls == [("ssh", None)]

    state["body"] = DOC                                              # retry window over: back to HTTP
    sources._auto["retry_at"] = 0.0
    calls.clear()
    assert "checks" in sources.fetch_opal() and calls == [("http", config.CFG["opal_url"])]


def test_auto_reports_both_errors_when_both_fail(transports, monkeypatch):
    calls, state = transports
    monkeypatch.setitem(config.CFG, "opal_source", "auto")
    state["body"] = ConnectionError("no route")
    monkeypatch.setattr(sources, "fetch_opal_ssh", lambda: (_ for _ in ()).throw(OSError("ssh down")))
    with pytest.raises(RuntimeError, match="HTTP: ConnectionError: no route · SSH: OSError: ssh down"):
        sources.fetch_opal()


def test_forced_transports_never_fall_back(transports, monkeypatch):
    calls, state = transports
    state["body"] = doc(error="crash")
    monkeypatch.setitem(config.CFG, "opal_source", "http")
    with pytest.raises(RuntimeError, match="crash"):
        sources.fetch_opal()
    assert calls == [("http", config.CFG["opal_url"])]
    calls.clear()
    monkeypatch.setitem(config.CFG, "opal_source", "ssh")
    sources.fetch_opal()
    assert calls == [("ssh", None)]


def test_url_is_derived_from_opal_host():
    assert config.CFG["opal_url"] == "http://192.0.2.2/netstatus.json"  # OPAL_HOST from conftest


# ───────────── checks → alerts, health
def drifted():
    d = doc(ok=False, failed=["ps_on", "ap_txpower"])
    for c in d["checks"]:
        if c["id"] == "ps_on":
            c.update(ok=False, actual="Y")
        if c["id"] == "ap_txpower":
            c.update(ok=False, actual=20)
    return d


def test_failed_checks_become_alerts_and_health_field(A, monkeypatch, caplog):
    parsed = sources.opal_from_netstatus(DOC)
    monkeypatch.setattr(builder, "fetch_home_assistant", lambda: dict(fw="x", devices=[]))
    monkeypatch.setattr(builder, "fetch_opal", lambda: parsed)
    builder.collect()
    assert not [a for a in builder.STATE["data"]["alerts"] if a["kind"] == "opal_check"]
    assert netmap.app.test_client().get("/api/health").get_json()["opal_checks_failed"] == []

    parsed = sources.opal_from_netstatus(drifted())
    builder.log.propagate = True
    try:
        with caplog.at_level("WARNING", logger="netmap"):
            builder.collect()
    finally:
        builder.log.propagate = False
    alerts = {a["check"]: a for a in builder.STATE["data"]["alerts"] if a["kind"] == "opal_check"}
    assert alerts["ps_on"]["level"] == "bad" and alerts["ap_txpower"]["level"] == "warn"
    assert "expected N, got Y" in alerts["ps_on"]["text"]["en"] and "atteso N, trovato Y" in alerts["ps_on"]["text"]["it"]
    assert "check ps_on FAILED" in caplog.text
    body = netmap.app.test_client().get("/api/health").get_json()
    assert body["opal_checks_failed"] == ["ps_on", "ap_txpower"]


def test_ssh_source_has_no_checks(A, monkeypatch):
    monkeypatch.setattr(builder, "fetch_home_assistant", lambda: dict(fw="x", devices=[]))
    monkeypatch.setattr(builder, "fetch_opal", lambda: sources.parse_opal(SSH))
    builder.collect()
    assert builder.STATE["data"]["opal"]["checks"] is None
    assert "opal_checks_failed" not in netmap.app.test_client().get("/api/health").get_json()


def test_real_uplink_bssid_without_router_macs_raises_no_alert(A, monkeypatch):
    monkeypatch.setitem(config.CFG, "ax_macs", [])
    data = builder.build(dict(fw="x", devices=[]), sources.opal_from_netstatus(DOC), {})
    assert data["opal"]["uplink"] == "unknown" and not any(a["kind"] == "uplink" for a in data["alerts"])
    monkeypatch.setitem(config.CFG, "ax_macs", [DOC["uplink"]["bssid"]])
    data = builder.build(dict(fw="x", devices=[]), sources.opal_from_netstatus(DOC), {})
    assert data["opal"]["uplink"] == "AX55"
