# Netmap — Project Guide

> This document describes the current Netmap architecture and gives coding assistants (Claude, ChatGPT, and similar tools) project-specific working rules. Keep it updated when architecture, configuration, API, or deployment changes.

## 1. Purpose

Netmap is a self-hosted dashboard for discovering and monitoring devices on a home network. It combines information from a TP-Link Archer AX55 exposed through Home Assistant and, optionally, a GL.iNet/OpenWrt access point (currently an Opal) queried over SSH.

The UI provides a network topology, a searchable/sortable device inventory, quick-copy IP/MAC controls, per-device signal history, AP/band/connectivity event history, device labels and type/room metadata, source diagnostics, and a health endpoint suitable for Uptime Kuma. The frontend supports Italian and English plus dark and light themes.

Netmap is a home-network inventory and monitoring dashboard, not a general-purpose network scanner.

## 2. Stack and architecture

- **Backend:** Python, Flask, Requests, SQLite.
- **Production HTTP server:** Waitress. Flask's built-in server is suitable for development.
- **Router source:** Home Assistant HTTP API (`HA_URL`, `HA_TOKEN`).
- **Optional AP source:** SSH via Paramiko to GL.iNet/OpenWrt.
- **Frontend:** server-rendered HTML template plus `static/css/netmap.css` and `static/js/netmap.js` (vanilla JavaScript); no frontend build step is required.
- **Persistence:** SQLite for signal samples, events, and first/last-seen state; JSON files for labels and device metadata.
- **Runtime model:** one application process with a background polling thread. The worker and in-memory state are process-local, so do not run multiple worker-enabled application processes for the same instance without redesigning this model.

The default poll interval is 30 seconds, with a minimum of 10 seconds. The worker collects source data, normalizes it into a common device model, updates first/last-seen information, stores useful samples/events, prunes expired history, and publishes the latest state to the API.

### Data sources and reconciliation

1. **Home Assistant / Archer AX55** provides the primary router/device view and related connection, band, and extender information.
2. **GL.iNet Opal / OpenWrt** is optional and enabled when `OPAL_HOST` is non-empty. Netmap uses SSH and keeps a persistent session to avoid reconnecting every poll. Interface names, bridge, and wired LAN details are configurable.
3. Devices behind a repeater/AP may appear on the main router under the repeater's MAC rather than their own MAC. Source-aware reconciliation is therefore important.
4. SQLite stores time-series samples and events. RSSI history exists only when a signal value is available; wired devices normally do not have RSSI.

### Identity and status rules

- A normalized MAC address is the stable device identity. IP addresses can change and must not be used as the primary identity.
- User labels are overrides. Type and room metadata are stored separately.
- Automatically inferred device types are suggestions; never overwrite an explicit user selection.
- A missing observation is not automatically proof of a disconnect if a source is unhealthy or stale. Distinguish device state from source health.
- Do not infer a radio disconnect from a single missing sample unless the current implementation explicitly requires it; wireless driver observations can be intermittent.

## 3. Files and persistence

Typical project files:

- `app.py` — Flask application, request guard, API routes, static asset version, and worker start-up.
- `config.py` — environment configuration, constants (`GROUP`, `LABEL`, `BAND`, `TYPES`), type suggestions, bilingual `L()`/`msg()`, and logging setup.
- `sources.py` — Home Assistant HTTP client and the persistent Opal SSH session with its output parsing.
- `database.py` — names/meta JSON storage, SQLite helpers (schema, history, seen, pruning, stats), offline alerts, and `HEALTH`.
- `builder.py` — device map building, event detection, data collection, the shared `STATE`, and the polling worker.
- `kuma.py` — optional Uptime Kuma sync over Kuma's Socket.IO API (persistent logged-in session, monitor/tag reconciliation, cached heartbeat status).
- `templates/index.html` — HTML template; `static/css/netmap.css` and `static/js/netmap.js` hold the styles and script.
- `names.json` — user-defined labels keyed by normalized MAC.
- `meta.json` — user-defined device type and room metadata keyed by normalized MAC.
- SQLite database — signal samples, events, and seen records.
- `.env` — optional local environment configuration; never commit secrets.
- `CLAUDE.md` — this guide.

The project has been deployed on Debian 12 in an LXC, with application files under `/opt/netmap` and persistent database data under `/var/lib/netmap`. Verify the actual service unit and environment before assuming these paths on another host. `NAMES_FILE`, `META_FILE`, and `DB_PATH` can override defaults.

## 4. Configuration reference

Configuration is read from environment variables. `config.py` attempts to load `.env` from the application folder; already-exported environment variables take precedence.

| Variable | Purpose | Default / notes |
|---|---|---|
| `HA_URL` | Home Assistant base URL | Empty until configured |
| `HA_TOKEN` | Home Assistant long-lived access token | Secret; required for HA access |
| `HA_VERIFY_SSL` | Verify HA TLS certificates | `true` |
| `OPAL_HOST` | Opal/OpenWrt host or IP | Empty disables Opal integration |
| `OPAL_PORT` | SSH port | `22` |
| `OPAL_USER` | SSH username | `root` |
| `OPAL_PASSWORD` / `OPAL_PASS` | SSH password | Optional; prefer key-based auth where practical |
| `OPAL_KEY` | SSH private-key path | Optional |
| `OPAL_KNOWN_HOSTS` | Known-hosts file for strict host-key checking | If set, unknown keys are rejected; otherwise current code uses automatic host-key acceptance |
| `OPAL_AP_IF` | Opal AP interface | Falls back to `OPAL_IFACE`, then `wlan0` |
| `OPAL_IFACE` | Legacy/fallback AP interface | `wlan0` |
| `OPAL_STA_IF` | Station/uplink interface | `wlan-sta0` |
| `OPAL_BRIDGE` | LAN bridge interface | `br-lan` |
| `OPAL_LAN_IF` | Comma-separated physical LAN interfaces | Empty |
| `OPAL_WIRED_MACS` | Comma-separated manually defined wired-client MACs | Empty |
| `AX55_MAC` | Comma-separated AX55 MAC addresses | Empty |
| `RE700X_MAC` | Comma-separated extender MAC addresses | Empty |
| `EXTENDER_NAMES` | Comma-separated extender name fragments | Empty |
| `UPLINK_EXPECTED_AP` | Expected AP name fragment for uplink warnings | Empty disables this check |
| `POLL_SECONDS` | Polling interval | `30`, minimum `10` |
| `OPAL_MISSING_GRACE_SECONDS` | How long an Opal client missing from the radio views stays connected | `120`; `0` disables the grace period |
| `NAMES_FILE` | Labels JSON path | `names.json` in the application folder by default |
| `META_FILE` | Type/room JSON path | `meta.json` in the application folder by default |
| `DB_PATH` | SQLite path | `network.db` in the application folder by default |
| `RETENTION_DAYS` | Sample/event retention | `14`, minimum `1` |
| `RSSI_GOOD` | Good RSSI threshold | `-60` dBm |
| `RSSI_WARN` | Warning RSSI threshold | `-75` dBm |
| `UPLINK_WARN` | Weak-uplink warning threshold | `-70` dBm |
| `NEW_DEVICE_HOURS` | New-device alert window | `48` |
| `OFFLINE_ALERT_TYPES` | Comma-separated types eligible for offline alerts | `camera,rete`; empty disables |
| `OFFLINE_ALERT_MINUTES` | Offline duration before alerting | `10` |
| `NETMAP_LANG` | Backend/log language (`it` or `en`) | `en`; UI language is selected independently |
| `DASH_USER` | Optional HTTP Basic Auth username | Empty disables auth |
| `DASH_PASSWORD` | Optional HTTP Basic Auth password | Empty by default |
| `LOG_LEVEL` | Python logging level | `INFO` |
| `LOG_FILE` | Optional rotating log file path | Empty means console only |
| `DASH_NO_WORKER` | Disable polling worker | Unset enables worker |
| `KUMA_URL` | Uptime Kuma base URL | Empty disables the Kuma sync |
| `KUMA_USERNAME` / `KUMA_PASSWORD` | Kuma login (Kuma API keys only read `/metrics`, so the sync logs in as the Kuma user) | Secret; 2FA must be off for that login |
| `KUMA_DEFAULT_TYPES` | Types monitored unless switched off per device | `camera,rete,luce_presa` |
| `KUMA_INTERVAL` | Check interval for created monitors (s) | `60`, minimum `20` |
| `KUMA_ALEXA_PORT` | TCP port checked on Alexa/Echo devices | `1080` |
| `KUMA_SHELLY_EXPECTED` | Shelly JSON-query threshold (`$number(wifi.rssi) > value`) | `-70` |
| `HOST` / `PORT` | Built-in Flask server bind | `0.0.0.0` / `8080` |

Never put real tokens, passwords, private keys, or other secrets in documentation, tests, commits, or logs.

## 5. HTTP API

The frontend uses same-origin endpoints. Keep the API contract stable unless a coordinated frontend/backend change is intended.

| Method and path | Purpose |
|---|---|
| `GET /` | Render `templates/index.html`, passing the polling interval |
| `GET /api/data` | Current state (`ts`, `errors`, `data`, `health`); `?since=<timestamp>` may return `{"unchanged": true}` when state has not changed |
| `GET /api/health` | Health check for Uptime Kuma/other monitors; returns HTTP 200 when healthy and 503 when starting/degraded |
| `GET /api/events?hours=24[&mac=...]` | AP/band/connectivity events; range bounded by retention, at most 300 event rows returned |
| `POST /api/refresh` | Wake the worker and wait briefly for a new poll cycle |
| `GET /api/history?mac=<MAC>&hours=24` | Aggregated RSSI history for a device or special `opal:uplink` pseudo-ID |
| `PATCH /api/names/<mac>` | Set or clear a device label |
| `PATCH /api/meta/<mac>` | Set or clear device type, room and optional `kuma: {enabled, check}` (omitted `kuma` keeps the stored value; `null`/`""` = automatic) |
| `POST /api/meta/apply-suggestions` | Persist suggested types only where an explicit type has not already been stored |

Write requests are guarded by the custom `X-Requested-With: dashboard` header; frontend write requests must continue to send it. Optional HTTP Basic Auth applies to requests when enabled.

`/api/health` reports the health of Netmap's own data sources (including Uptime Kuma when enabled) and polling, not the online status of every individual device. `/api/events` currently limits event rows to 300, so exporting that response does **not** guarantee a complete global historical export. `/api/history` returns aggregated RSSI points, not packet-level or every-poll data.

## 6. SQLite schema

The application initializes these tables and indexes:

- `samples(ts, mac, ip, name, ap, band, ssid, rssi, tx, rx)` — time-series observations; indexed by `(mac, ts)` and `ts`.
- `events(ts, mac, name, kind, src, dst)` — connection, AP-movement, band/network, and IP-change (`kind='ip'`, `src`/`dst` = old/new IP) events; indexed by `ts` and `(mac, ts)`.
- `seen(mac PRIMARY KEY, first_seen, last_seen)` — first/last-seen tracking.

SQLite uses WAL mode. Reuse the existing database helpers/context manager, parameterize SQL queries, and account for concurrent reads and writes. Avoid schema changes that discard history; document and test migrations and backup/recovery steps.

### Uptime Kuma sync

- Enabled when `KUMA_URL` is set. `kuma.sync()` runs in the worker after each `collect()`, only when the cycle's data is `clean`, in its own try/except; failures appear as `HEALTH["kuma"]`.
- Ownership: a monitor is Netmap's only if it has the `netmap` tag and its description is `MAC(<MAC>)` (upper case); removing the tag by hand releases it. Earlier formats (`netmap:<mac>` line; `MAC=<MAC>` with the tag) are adopted once and rewritten. Netmap never edits, pauses or deletes any other monitor and never deletes monitors at all. Opted-out devices and devices no source reports any more are paused; a paused monitor is resumed only when the user switches the device back on (a manual pause in Kuma is respected).
- On managed monitors Netmap owns the name (`<label> (<ip>)`), address, check settings and **all tags**: `netmap`, room, confirmed type (`kuma.TYPE_TAG`) and connection (`kuma.CONN_TAG`; kept while offline). Existing Kuma tags with the same name are reused.
- Check type: `meta.json` `kuma.check` override, else `config.suggest_check()` (shelly → JSON query on `/rpc/Shelly.GetStatus`; echo/alexa/amazon → TCP port; otherwise ping). Opt-in: `kuma.enabled` override, else type in `KUMA_DEFAULT_TYPES` or a non-ping check.
- Each device carries `kuma: {enabled, enabled_set, check, check_set, check_auto, monitor, status}` in `/api/data`; `data.kuma.enabled` tells the page whether the sync is on.
- Tested against Uptime Kuma 2.5.x. Kuma's Socket.IO API is not a stable public API: re-check `kuma.new_monitor()` fields after Kuma upgrades.

## 7. Frontend conventions

The UI lives in `templates/index.html`, `static/css/netmap.css`, and `static/js/netmap.js` (vanilla JavaScript, `'use strict'`). The poll interval reaches the script through `<meta name="poll-interval">`, and CSS/JS URLs carry a `?v=` hash of `static/` so browsers reload them after a deploy. It supports bilingual strings through the `T` translation dictionary and browser/local-storage language selection, dark/light themes persisted in local storage, topology grouping by connection/room/type, a sortable/searchable inventory, copy buttons, history charts, event tables, source diagnostics, and device-edit dialogs.

### UI rules

- Preserve existing behavior and both languages during visual changes.
- Add all new UI text to the bilingual translation dictionary; do not hard-code a single-language label into generated markup.
- Escape dynamic values before injecting HTML. Follow existing `esc()` patterns for device names, room names, SSIDs, and API-provided text.
- Copy controls inside clickable cards/rows must not trigger the card/row history action.
- Preserve keyboard access, visible focus states, and keyboard activation for interactive elements.
- Use theme CSS variables instead of hard-coded colors that only work in dark or light mode.
- Keep device cards left-aligned within groups; do not center a lone card in an otherwise empty row.
- Let long device names wrap to two lines without hiding RSSI/status information.
- Keep IP and MAC rows vertically separated enough to scan easily.
- Give the refresh icon fixed dimensions so it cannot shrink when the label changes.
- Test both desktop and mobile widths after layout changes.

## 8. Development and validation

Create/use a virtual environment and install dependencies from the repository's dependency file if one exists. Do not invent dependency versions.

Development run:

```bash
python app.py
```

Production-like single-process run:

```bash
waitress-serve --listen=0.0.0.0:8080 --threads=4 app:app
```

Basic Python syntax check:

```bash
python -m py_compile app.py config.py sources.py database.py builder.py kuma.py
node --check static/js/netmap.js
pytest -q
```

Where tools are available, validate embedded JavaScript, HTML, and CSS. Browser smoke tests should cover:

- Initial load, polling, manual refresh, and error states.
- Italian/English switching and dark/light persistence.
- Search, filters, sorting, and filter reset.
- Copy IP/MAC without triggering row/card actions.
- Rename, type, and room editing.
- History chart, event list, and source diagnostics.
- Desktop and mobile layout.

A syntax check is not an end-to-end test. State exactly which checks were run. Never claim browser or live-router testing unless it actually happened.

### Safe deployment

1. Back up the current template and every file being changed.
2. Keep SQLite and JSON metadata out of disposable build/artifact directories.
3. Run syntax/validation checks before replacing production files.
4. Deploy only files relevant to the change.
5. Restart/reload the service only when necessary.
6. Check the systemd journal and `GET /api/health` after deployment.
7. Confirm that source data is fresh.

## 9. Security and reliability

- Keep Home Assistant tokens and Opal SSH credentials out of source control.
- Prefer SSH key authentication and strict known-host verification where practical. If `OPAL_KNOWN_HOSTS` is unset, current code accepts an unknown host key automatically; do not assume strict host verification is active.
- Do not expose the dashboard publicly without a deliberate authentication and network-security design.
- Basic Auth and the custom write-request header are safeguards, not substitutes for TLS, network controls, or a complete threat model.
- Do not treat stale source data as fresh, or a source failure as proof that all clients disconnected.
- The Uptime Kuma sync may only mutate monitors it owns (`netmap` tag + `MAC(<MAC>)` description); never touch other monitors and never delete monitors.
- Avoid destructive database/metadata operations without explicit approval.

## 10. Working rules for AI coding assistants

1. **Inspect before editing.** Read the current files and verify actual implementation before proposing changes.
2. **Use the latest user-provided files.** Older conversation attachments may be stale; do not silently revert to them.
3. **Keep changes scoped.** Prefer targeted patches over rewriting whole modules or the template.
   `builder.STATE` is rebound every cycle: read it through the module (`builder.STATE`), never via `from builder import STATE`.
4. **Preserve contracts.** Do not break API routes, database layout, language switching, themes, or user metadata unintentionally.
5. **State backend impact.** Clearly distinguish frontend-only, backend-only, and cross-layer changes.
6. **Do not fabricate tests.** Separate syntax checks, unit tests, browser tests, and live-environment tests in reports.
7. **Ask before destructive changes.** Never delete history, reset metadata, or change router/network configuration without explicit approval.
8. **Prefer evidence to assumptions.** Inspect logs/data or ask for evidence when router output or API behavior is unclear.
9. **Keep project documentation in English** unless explicitly asked otherwise. The product UI itself remains bilingual.
10. **Use placeholders in examples.** Never include actual secrets.

## 11. Known limitations and future work

These are design considerations, not claims that the features are already implemented:

- Current/filtered inventory CSV export can be implemented in the browser. A complete global event export needs a backend endpoint or pagination because `/api/events` returns at most 300 event rows.
- A single CSV containing RSSI history for all devices needs a dedicated aggregate endpoint; the existing history route is per MAC.
- Source-health UI should distinguish disabled, waiting, failed, stale, and healthy sources using existing health data accurately.
- Uptime Kuma: no status page/notification management yet; the sync pauses but never deletes monitors.

## Quick reference

- **Stable device identity:** normalized MAC address.
- **Polling:** one in-process worker; default 30 seconds, minimum 10 seconds.
- **Primary source:** Home Assistant / TP-Link Archer AX55.
- **Optional source:** GL.iNet/OpenWrt Opal over SSH.
- **History:** SQLite.
- **User labels:** `names.json`.
- **Device type/room:** `meta.json`.
- **Monitoring endpoint:** `GET /api/health`.
- **Production principle:** one worker-enabled process; Waitress may use multiple request threads.
