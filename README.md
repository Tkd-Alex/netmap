# Netmap

A live map of your home network: which devices are connected, **to which access point** (main router, mesh extender, secondary AP), with what signal, since when, and how they move from one AP to another. Every device can have a **type** (with an icon) and a **room**. It runs as a single Python process with a local SQLite history, and the web page is available in **English and Italian**.

It was built for one specific setup, but it is adaptable:

```
Internet ─ TP-Link router (AX55) ──  Home Assistant ─┐ (device_tracker)
               │  5 GHz Wi-Fi uplink                 │
               ▼                                     ▼
       GL.iNet Opal (OpenWrt)  ── SSH ──────────►  Netmap ──► http://host:8080
        ├─ LAN: camera
        └─ 2.4 GHz Wi-Fi: IoT devices
```

> The labels in the interface say "AX55" and "Opal" because that is the author's setup. The secondary access point is **optional**: without `OPAL_HOST` Netmap works with the main router only.

## Features

- **Map grouped by connection, room or type**, with colour-coded signal (RSSI) and one icon per category.
- **Table** with filtering, sorting, renaming and editing of type and room.
- **Signal history** (1 h / 6 h / 24 h / 7 d) for every device and for the secondary AP's uplink.
- **Roaming**: records moves between APs or bands, connections and disconnections, with a ranking of the most unstable devices. Events also show up as vertical lines in the signal chart.
- **Alerts**: IP conflict, weak signal (grouped by room), weak uplink or uplink attached to the wrong AP, **new device**, cameras/network gear **offline**.
- **Source priority**: for what sits behind the secondary AP, the AP itself wins (associated and wired clients), then what the main router reports. Devices that the router sees under the AP's MAC ("aliases") are handled too.
- **Diagnostics**: a panel with the state, duration and detail of each source, readable logs and `/api/health` for monitors.
- **Failure tolerant**: if a source stops answering it shows the last valid reading (up to 10 minutes) and does **not** invent events.
- **Two languages**: Italian and English, with a selector in the header. The choice is remembered; the first time it follows the browser language.

## Requirements

- Python 3.11+ (or Docker).
- **Home Assistant** with the router's `device_tracker` entities (state `home` = connected). Netmap reads these attributes: `mac`/`mac_address`, `ip`/`ip_address`, `friendly_name`/`host_name`/`hostname`, `connection`, `band`, `ap_name`, `signal`, `tx_rate`, `rx_rate` (kbps), `ssid`, `source_type`. The author uses them with a TP-Link Archer AX55: with another integration you may need to adapt `fetch_home_assistant` and `HA_TEMPLATE` in `app.py`.
- (Optional) an **OpenWrt/GL.iNet** access point with SSH. It uses `iwinfo`, `ip neigh` and, for wired devices, `bridge` (the `ip-bridge` package) or `brctl`. Developed on a GL.iNet Opal (GL-SFT1200).
- **paramiko < 5**: version 5 dropped the SHA-1 `ssh-rsa` host key that older Dropbear servers still use (`requirements.txt` already pins it).

## Quick start (development)

```bash
git clone https://github.com/<user>/netmap && cd netmap
python3 -m venv venv && . venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # fill in HA_URL, HA_TOKEN and, if needed, OPAL_*
cp names.example.json names.json && cp meta.example.json meta.json   # optional
python app.py                   # http://localhost:8080
pytest                          # tests
```

For everyday use see **[docs/DEPLOY.md](docs/DEPLOY.md)** (Proxmox LXC, Docker, reverse proxy, monitoring).

## Configuration

Everything is set through environment variables or the `.env` file (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `HA_URL`, `HA_TOKEN` | – | Home Assistant and its long-lived access token. `HA_VERIFY_SSL=false` for self-signed certificates |
| `OPAL_HOST` | empty | Secondary AP over SSH; **empty = disabled** |
| `OPAL_PORT`, `OPAL_USER` | `22`, `root` | |
| `OPAL_PASSWORD` / `OPAL_KEY` | – | Password or private key (recommended) |
| `OPAL_KNOWN_HOSTS` | – | If set the host key is verified, otherwise it is accepted on first contact |
| `OPAL_AP_IF`, `OPAL_STA_IF` | `wlan0`, `wlan-sta0` | Access point interface and the client interface used for the uplink |
| `OPAL_LAN_IF`, `OPAL_BRIDGE` | – , `br-lan` | Physical LAN port (e.g. `eth0.1`): MACs seen there are "wired". List the ports with `ls /sys/class/net/br-lan/brif` |
| `OPAL_WIRED_MACS` | – | Wired MACs listed by hand (alternative to `OPAL_LAN_IF`) |
| `UPLINK_EXPECTED_AP` | – | Part of the name of the AP the secondary AP must be attached to; alert if different |
| `EXTENDER_NAMES` | – | Mesh extenders (partial name) to tell them apart in roaming |
| `AX55_MAC`, `RE700X_MAC` | – | Used only if the router does not say which AP the secondary AP is attached to |
| `POLL_SECONDS` | `30` | Cycle period, **including** the collection time (minimum 10) |
| `RETENTION_DAYS` | `14` | How long samples and events are kept |
| `RSSI_GOOD`, `RSSI_WARN`, `UPLINK_WARN` | `-60`, `-75`, `-70` | Thresholds in dBm |
| `NEW_DEVICE_HOURS` | `48` | How long a never-seen MAC counts as "new" |
| `OFFLINE_ALERT_TYPES`, `OFFLINE_ALERT_MINUTES` | `camera,rete`, `10` | Types to alert on when they stay offline (empty = never). Type keys: `pc`, `server`, `smartphone`, `tv`, `camera`, `luce_presa`, `iot`, `rete`, `altro` |
| `DB_PATH`, `NAMES_FILE`, `META_FILE` | next to `app.py` | In production use a dedicated data folder |
| `DASH_USER`, `DASH_PASSWORD` | – | Optional HTTP Basic auth |
| `NETMAP_LANG` | `en` | Language of the **logs**: `en` or `it`. The page language is chosen in the browser |
| `LOG_LEVEL`, `LOG_FILE` | `INFO`, – | `DEBUG` adds tracebacks and the time of every SSH command |

## Type, room and icons

Each device can have a name (`names.json`), a type and a room (`meta.json`), editable from the page (pencil in the table, or the "Edit" button under the chart).

Types: PC/laptop, Server/VM/LXC, Smartphone/tablet, TV/audio/media, Camera/doorbell, IoT lights/plugs/relays, IoT other, Network, Other. Change them in `TYPES` in `app.py` (the icons live in `ICON` in `templates/index.html`).

For unclassified devices Netmap **suggests** a type from the name or the MAC (dimmed icon and `(?)`); the "Apply suggestions" button confirms them in bulk without overwriting choices you already made. The suggestions are keywords in `KIND_HINTS`: add your own.

## Where the data is stored (and what happens when you rename)

| What | Where | Notes |
|---|---|---|
| **Names** (labels) | `names.json` | Source of truth. If a name is missing, the one the router reports is used |
| **Type and room** | `meta.json` | Source of truth |
| Signal samples, roaming events, "last seen" | `network.db` (SQLite) | Measurements only, tied to the **MAC**, never to the name |

So there is **no migration**: the JSON files are not "loaded" into the database. Names, types and rooms are read from the files on **every cycle** and applied to the incoming data.

- **Rename from the page:** the server rewrites the file atomically and starts a cycle right away; the page updates instantly. History and events follow the MAC, so they show the new name immediately, past events included.
- **Edit the file by hand:** it applies from the next cycle, no restart needed. MACs may use upper case, colons or dashes. JSON has no comments, and after the first save from the page the keys are sorted.
- **Invalid JSON** (e.g. a trailing comma): Netmap keeps using the last valid version, shows the error in the page and in the log, and **refuses to rewrite** the file until you fix it, so nothing gets lost.
- **Clear name, type and room:** the entry disappears and the device goes back to the router's name.
- **Backup:** `names.json`, `meta.json` and `network.db` (the database only holds history: losing it does not remove your labels).

## Alerts

| Alert | When |
|---|---|
| IP conflict | Two connected devices share the same IP |
| Weak signal | RSSI ≤ `RSSI_WARN`; with two or more in the same room and AP, a single alert "Weak signal in Kitchen…" |
| Uplink | Signal ≤ `UPLINK_WARN`, or the secondary AP attached to an AP other than `UPLINK_EXPECTED_AP` |
| New device | A never-seen MAC, within `NEW_DEVICE_HOURS`, with no name in `names.json`; yellow if the type is unknown. On first start everything already present counts as known |
| Offline | Cameras and network gear (configurable) offline for more than `OFFLINE_ALERT_MINUTES`. Not raised while a source is failing |

Alerts that refer to a device are clickable and open its history.

## Reading the logs

```
Start · every 30 s · HA http://… · Opal root@…:22 (AP wlan0, uplink wlan-sta0, LAN ports eth0.1) · DB … (14 d) · auth off · log INFO
Cycle 12 · HA ok 0.04 s (77 trackers received, 74 valid · template · 26 KB) · Opal ok 1.2 s (6 Wi-Fi clients, 1 wired · SSH reused · 5890 B) · 32/73 connected · +19 samples · 1.3 s total
AP change: Phone from «AX55 · 5 GHz» to «Opal · 2.4 GHz»
AX55↔Opal alias: Purifier (192.0.2.220) is seen by the AX55 with the Opal's MAC 94:… → treated as ONLINE behind the Opal
Offline: Kitchen camera · Kitchen for 12 min (Camera / doorbell)
Home Assistant · AX55: ERROR · ConnectionError… (attempt #1)
```

If an SSH command takes longer than 1 s, `slow: …` appears in the cycle line. For details use `LOG_LEVEL=DEBUG`. Set `NETMAP_LANG=it` for Italian logs.

## API

Requests that change data need the header `X-Requested-With: dashboard` (CSRF protection). Texts meant for display (`alerts[].text`, `types`, source `detail`) are `{"it": …, "en": …}` objects and the page picks one; group labels use neutral tokens (`wired`, `guest`, `undetermined`).

| Method and path | Description |
|---|---|
| `GET /api/data[?since=ts]` | Full state (answers `{"unchanged":true}` if nothing changed) |
| `POST /api/refresh` | Forces a cycle and answers with the new data |
| `GET /api/health` | 200 if everything is fine, 503 otherwise: `{"status": "ok"\|"degraded"\|"starting", "failing": […], "last_cycle_age_s": n, "cycles": n}` (for Uptime Kuma & co.) |
| `GET /api/history?mac=…&hours=24` | Signal series (`mac=opal:uplink` for the uplink) |
| `GET /api/events?hours=24[&mac=…]` | AP/band changes, connections, disconnections |
| `PATCH /api/names/<mac>` | `{"name": "…"}` (empty removes it) |
| `PATCH /api/meta/<mac>` | `{"type": "camera", "room": "Kitchen"}` |
| `POST /api/meta/apply-suggestions` | Confirms the suggested types |

## Security

- Netmap **does not do TLS**: use it on your LAN or behind a reverse proxy with HTTPS. With `DASH_USER`/`DASH_PASSWORD` set, Basic auth travels in clear text without HTTPS.
- Use a **dedicated SSH key** for the secondary AP and `OPAL_KNOWN_HOSTS` to verify the host. The Home Assistant token can belong to a dedicated user.
- The `.env` file holds secrets: permissions `640` or stricter, never in the repository.

## Known limitations

- The labels "AX55", "Opal" and the group names are hard-coded.
- Event precision is that of the refresh cycle plus the time the routers take to report a client as gone.
- "Behind the Opal" does not distinguish Wi-Fi from wired for devices seen only as aliases.
- A single process: do not start several workers (they would duplicate the polling).

## Before publishing on GitHub

`.gitignore` excludes `.env`, `names.json`, `meta.json`, databases, logs and keys: they hold the MACs, IPs and names of your home. Before the first push:

```bash
git status --short                                      # no personal file among those to be added
git grep -nIiE "([0-9a-f]{2}:){5}[0-9a-f]{2}" -- . ':!tests' ':!*.example.json' ':!.env.example'
git grep -nIi "token\|password" -- . ':!*.md' ':!.env.example' ':!app.py' ':!deploy'
```

If a token ends up in the history, **revoke it** in Home Assistant: rewriting the history is not enough.

## License

Pick a license before publishing (for example MIT) and add the `LICENSE` file.
