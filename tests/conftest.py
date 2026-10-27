import os
import sys
from pathlib import Path

os.environ.update(DASH_NO_WORKER="1", OPAL_HOST="192.0.2.2", OPAL_LAN_IF="eth0.1", UPLINK_EXPECTED_AP="Main",
                  EXTENDER_NAMES="Ext", AX55_MAC="02:00:00:00:00:01")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import app as netmap  # noqa: E402
import builder  # noqa: E402
import config  # noqa: E402
import database  # noqa: E402


@pytest.fixture()
def A(tmp_path, monkeypatch):
    """The module with data, names and meta in a temporary folder, and a clean state."""
    monkeypatch.setitem(config.CFG, "db", str(tmp_path / "n.db"))
    monkeypatch.setitem(config.CFG, "names", str(tmp_path / "names.json"))
    monkeypatch.setitem(config.CFG, "meta", str(tmp_path / "meta.json"))
    monkeypatch.setattr(builder, "STATE", {"ts": None, "errors": {}, "data": None, "health": None})
    for container in (builder.LAST, builder.ALIAS_LOGGED, database.OFFLINE_ALERTED, database._GOOD, database.CONFIG_ERRORS,
                      builder.OPAL_MISSING_SINCE):
        container.clear()
    database.init_db()
    return netmap


OPAL_OUTPUT = """##AP
wlan0     ESSID: "IoT"
          Access Point: 94:00:00:00:00:07
          Channel: 6 (2.437 GHz)
##ASSOC
AA:BB:CC:00:00:01  -61 dBm / -95 dBm (SNR 34)  120 ms ago
        RX: 72.2 MBit/s, MCS 7
        TX: 65.0 MBit/s, MCS 7
AA:BB:CC:00:00:02  -78 dBm / -95 dBm (SNR 17)  40 ms ago
##STA
wlan-sta0 ESSID: "Home"
          Access Point: 6E:00:00:00:00:08
          Signal: -67 dBm  Noise: unknown
##MAC
6e:00:00:00:00:08
##NEIGH
192.168.1.50 dev br-lan lladdr aa:bb:cc:00:00:01 REACHABLE
192.0.2.220 dev br-lan lladdr aa:bb:cc:00:00:09 STALE
192.168.1.239 dev br-lan lladdr aa:bb:cc:00:00:04 REACHABLE

##LOCAL
94:00:00:00:00:07
6e:00:00:00:00:08
00:00:00:00:00:00
##FDB
port no	mac addr		is local?	ageing timer
  1	aa:bb:cc:00:00:04	no		   0.50
  2	aa:bb:cc:00:00:01	no		   3.10
##PORTS
0x1 eth0.1
0x2 wlan0
"""


def tracker(mac, name, ip="", active=True, conn="HOST_2G", ap="", signal=-55):
    return dict(mac=mac, ip=ip, name=name, conn=conn, connection_label="", ap_name=ap,
                signal=signal if active else None, active=active, tx=None, rx=None, ssid="Home")


def opal(clients=(), wired=(), neigh=None):
    return dict(ap=dict(essid="IoT", channel=6), sta=dict(essid="Home", bssid="6e:00:00:00:00:08", signal=-60, noise=None),
                clients={m: dict(rssi=-50, idle_ms=0, ip=None, tx=None, rx=None) for m in clients}, neigh=neigh or {},
                neigh_state={}, wired=list(wired), own_mac="6e:00:00:00:00:08", local_macs=["94:00:00:00:00:07"])


@pytest.fixture()
def cycle(A, monkeypatch):
    """cycle(router_devices, opal_clients, ...) runs a complete collection cycle using simulated sources."""
    def run(devices, clients=(), router_ok=True, opal_ok=True, wired=(), neigh=None):
        def boom(message):
            def raiser():
                raise RuntimeError(message)
            return raiser
        monkeypatch.setattr(builder, "fetch_home_assistant", (lambda: dict(fw="x", devices=devices)) if router_ok else boom("HA down"))
        monkeypatch.setattr(builder, "fetch_opal", (lambda: opal(clients, wired, neigh)) if opal_ok else boom("SSH down"))
        builder.collect()
        return builder.STATE["data"]
    return run
