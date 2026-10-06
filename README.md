# Wi-Fi Network Mapper

Local dashboard to visualize the topology of an AX55 + GL.iNet Opal network. Home Assistant provides the AX55 device trackers; SSH/`iwinfo` on the Opal provides Wi-Fi associations, RSSI, and rates detected directly by the access point. Results are merged by MAC and RSSI history is stored in SQLite.

The program does not log into the AX55 and does not use its password. It reads the states already published by the Home Assistant integration through its local API.

## Configuration

In the `.env` file set:

```dotenv
HA_URL=http://HOME_ASSISTANT_IP:8123
HA_TOKEN=YOUR_HA_LONG_LIVED_TOKEN
HA_VERIFY_SSL=true
OPAL_HOST=192.0.2.2
OPAL_USER=root
OPAL_PASSWORD=YOUR_OPAL_SSH_PASSWORD
```

Create the token in Home Assistant from the user profile and keep it only in the local `.env`; do not share it. If Home Assistant uses HTTPS with a self-signed certificate, set `HA_VERIFY_SSL=false`.

The TP-Link integration must have device tracking enabled. The attributes read are `mac`/`mac_address`, `ip`/`ip_address`, `friendly_name`/`host_name`, `connection`, `band`, `signal`, `tx_rate`, `rx_rate`, and `ap_name`. HA rates are converted from kbit/s to Mbps.

## Local run

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open `http://localhost:8080`.

## Docker

```sh
docker compose up -d --build
```

The dashboard is available on port 8080. SQLite and custom labels are stored under `./data`.

## Opal and labels

The Opal SSH user must be able to read `iwinfo`, `ip neigh`, and `/sys/class/net`. Interfaces are configurable with `OPAL_IFACE`, `OPAL_STA_IF`, and `OPAL_PORT`; for an SSH key use `OPAL_KEY`. Custom labels can be edited from the table and are saved in `names.json`.