#!/usr/bin/env bash
# Installs Netmap in a Debian/Ubuntu container (e.g. a Proxmox LXC). Run as root from the project folder:
#   git clone <repo> /opt/netmap && cd /opt/netmap && bash deploy/install-lxc.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR=/var/lib/netmap

[ "$(id -u)" -eq 0 ] || { echo "Run as root."; exit 1; }
[ -f "$APP_DIR/app.py" ] || { echo "app.py not found in $APP_DIR"; exit 1; }

apt-get update
apt-get install -y --no-install-recommends python3 python3-venv python3-pip

id netmap >/dev/null 2>&1 || useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin netmap
mkdir -p "$DATA_DIR"
chown netmap:netmap "$DATA_DIR"

python3 -m venv "$APP_DIR/venv"
"$APP_DIR/venv/bin/pip" install --upgrade pip
"$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  # data in a dedicated folder, outside the code
  {
    echo "DB_PATH=$DATA_DIR/network.db"
    echo "NAMES_FILE=$DATA_DIR/names.json"
    echo "META_FILE=$DATA_DIR/meta.json"
  } >> "$APP_DIR/.env"
  echo ">> Created $APP_DIR/.env: fill it in (HA_URL, HA_TOKEN, OPAL_*)."
fi
chown root:netmap "$APP_DIR/.env"
chmod 640 "$APP_DIR/.env"

# example files as a starting point (never overwrites yours)
[ -f "$DATA_DIR/names.json" ] || install -o netmap -g netmap -m 640 "$APP_DIR/names.example.json" "$DATA_DIR/names.json"
[ -f "$DATA_DIR/meta.json" ]  || install -o netmap -g netmap -m 640 "$APP_DIR/meta.example.json"  "$DATA_DIR/meta.json"

# the service reads the code, never writes it
chown -R root:netmap "$APP_DIR"
chmod -R g+rX "$APP_DIR"

install -m 644 "$APP_DIR/deploy/netmap.service" /etc/systemd/system/netmap.service
systemctl daemon-reload
systemctl enable --now netmap

echo
echo ">> Installed. Status:  systemctl status netmap"
echo ">>            Logs:    journalctl -u netmap -f"
echo ">> After editing .env:  systemctl restart netmap"
