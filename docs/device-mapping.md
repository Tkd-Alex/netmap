# Device mapping — home lab reference

**Last updated:** October 23, 2026
**Goal:** Reliably identify network devices, their Wi-Fi access point, and RSSI signal, combining Home Assistant and GL.iNet Opal data.

## 1. Project goal

A local dashboard showing, for each device:

| Field | Description |
|---|---|
| Device name | Custom label or hostname |
| MAC address | Normalized (colon-separated, lowercase) |
| IP address | From router DHCP leases or ARP table |
| Access point | AX55 (5 GHz, 2.4 GHz, IoT, guest, wired), Opal (2.4 GHz, wired), or extender |
| SSID | Wi-Fi network name |
| RSSI | Signal strength in dBm |
| TX / RX rate | Link speed in Mbps |
| Connection status | Online / offline |
| First seen / last seen | Timestamp of first and most recent appearance |

## 2. Data sources

### 2.1 Home Assistant (TP-Link Archer AX55 via integration)

- REST API at `HA_URL:8123/api/`
- Reads `device_tracker` entities with attributes: `mac`, `ip`, `friendly_name`, `connection`, `band`, `ap_name`, `signal`, `tx_rate`, `rx_rate`, `ssid`
- Rate conversion: HA provides kbps → divide by 1000 for Mbps
- Template mode: Jinja2 template sent to `/api/template` to fetch only device_tracker attributes (falls back to `/api/states` if unsupported)

### 2.2 GL.iNet Opal (OpenWrt, SSH)

- `iwinfo wlan0 info` + `iwinfo wlan0 assoclist` → AP info + client associations with RSSI and TX/RX rates
- `ubus call hostapd.wlan0 get_clients` → alternative presence view (avoids false disconnects)
- `ip neigh show` → ARP table with neighbor state (REACHABLE, STALE, DELAY, PROBE, FAILED)
- `bridge fdb show` / `brctl showmacs` → wired MACs on bridge ports
- `/sys/class/net/*/address` → local MAC addresses (for alias detection)

### 2.3 Merge strategy

1. Opal assoclist/wired data takes priority over AX55 data for clients behind the Opal
2. Alias detection: devices seen by AX55 with the Opal's MAC are considered online behind the Opal
3. hostapd presence is the primary source; iwinfo provides RSSI/traffic
4. Grace period (OPAL_MISSING_GRACE_SECONDS, default 120s) prevents false disconnects

## 3. Known device categories

| Type | Description | Key phrase matches |
|---|---|---|
| PC / laptop | Desktops, laptops | proxmox, pc, laptop, macbook, thinkpad |
| Server / VM / LXC | Virtualized or containerized | server, vm, lxc, container, docker, home assistant |
| Smartphone / tablet | Mobile devices | pixel, iphone, samsung, tablet, ipad, phone |
| TV / audio / media | Entertainment devices | tv, chromecast, google home, echo, fire, roku, apple tv |
| Camera / doorbell | Security cameras | camera, cam, reolink, rlc, doorbell, ring, spioncino |
| IoT · lights / plugs / relays | Smart home controllers | shelly, sonoff, plug, relay, light, lamp, switch |
| IoT · other | Other smart devices | sensor, thermostat, purificatore, sensor |
| Network (router / AP) | Network infrastructure | archer, ax55, opal, router, extender, repeater, mesh, access point |
| Other | Unclassified | — |

Device types are auto-suggested from MAC OUI (e.g. Proxmox virtual MACs starting with `bc:24:11`) and keyword matching against the device name. Users can override suggestions via the UI; manual choices are never overwritten.

## 4. Alerts

- **IP conflict**: Two connected devices sharing the same IP
- **Weak signal**: RSSI ≤ RSSI_WARN; grouped by room when ≥ 2 devices share the same room and node
- **Uplink signal**: Opal uplink RSSI ≤ UPLINK_WARN, or Opal connected to wrong AP
- **New device**: MAC never seen before, within NEW_DEVICE_HOURS, without a name in names.json
- **Offline**: Cameras and network devices (configurable) offline for > OFFLINE_ALERT_MINUTES

## 5. File structure

| Purpose | File | Notes |
|---|---|---|
| Device labels | names.json | Maps MAC → human-readable name |
| Type and room | meta.json | Maps MAC → {type, room} |
| Signal history, events | network.db | SQLite, one DB per poll cycle, retention-days |
| Configuration | .env | Secrets (never committed) |

