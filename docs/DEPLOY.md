# Going to production

**English** · [Italiano](DEPLOY.it.md)

Two ways, both with a **single process** (`waitress`) and the data kept outside the code:

- **A. Proxmox LXC** with systemd (lightweight, recommended if you already run Proxmox).
- **B. Docker / Compose** (on any Docker host).

> The scripts and files in this guide were written and syntax-checked, but the Proxmox and Docker steps were not run in the environment where they were produced: if something does not work, open an issue with the output of the command.

## What is in the repository and what you add yourself

| In the repository | You add (not, and must not be, in the repository) |
|---|---|
| Code (`app.py`, `config.py`, `sources.py`, `database.py`, `builder.py`, `templates/`, `static/`), `requirements.txt` | `.env` with token and addresses: start from `.env.example` |
| `Dockerfile`, `docker-compose.yml`, `deploy/` (systemd, LXC script) | **Your** `names.json` and `meta.json` in the data folder (optional: without them the router's names are used) |
| Documentation, tests, `names.example.json`, `meta.example.json` | SSH key (or password) for the secondary AP |

The `network.db` database is created on its own at first start.

## 0. Preparation (common)

**Home Assistant token.** User profile → Security → *Long-lived access tokens*. Test it:

```bash
curl -s -H "Authorization: Bearer <TOKEN>" http://<HA>:8123/api/      # {"message":"API running."}
```

**Dedicated SSH key for the secondary AP** (optional, recommended). On your PC:

```bash
ssh-keygen -t ed25519 -f netmap_opal -N "" -C netmap
cat netmap_opal.pub | ssh root@<OPAL> 'cat >> /etc/dropbear/authorized_keys && chmod 600 /etc/dropbear/authorized_keys'
ssh -i netmap_opal root@<OPAL> iwinfo                                    # must work without a password
```

On the secondary AP, to recognise wired devices: `opkg update && opkg install ip-bridge` (on recent versions with `apk`: `apk add ip-bridge`). Then look up the LAN port name: `ls /sys/class/net/br-lan/brif` (for example `eth0.1`) and use it in `OPAL_LAN_IF`.

**Host key** (for `OPAL_KNOWN_HOSTS`): `ssh-keyscan <OPAL> > known_hosts` and check the fingerprint with `ssh-keygen -lf known_hosts`.

**Network.** Give the Netmap host a fixed IP or a DHCP reservation.

---

## A. Proxmox LXC

### 1. Create the container

Web UI: *Create CT* → **Debian 12** template, *Unprivileged* on, 1 vCPU, 512 MB RAM, 4 GB disk, network on `vmbr0` (the same LAN as router and AP), *Start at boot*. From the shell, as an example (adapt ID, storage and template name):

```bash
pct create 120 local:vztmpl/debian-12-standard_*_amd64.tar.zst \
  --hostname netmap --unprivileged 1 --cores 1 --memory 512 --swap 256 \
  --rootfs local-lvm:4 --net0 name=eth0,bridge=vmbr0,ip=dhcp --onboot 1
pct start 120 && pct enter 120
```

### 2. Install

Inside the container:

```bash
apt-get update && apt-get install -y git
ln -sf /usr/share/zoneinfo/Europe/Rome /etc/localtime        # correct times in the logs
git clone https://github.com/<user>/netmap /opt/netmap
cd /opt/netmap && bash deploy/install-lxc.sh
```

The script creates the `netmap` user, a virtualenv, the `/var/lib/netmap` data folder, a `.env` to fill in and the systemd service (with `ProtectSystem=strict`: the service can only write to `/var/lib/netmap`).

### 3. Configure

```bash
nano /opt/netmap/.env                       # HA_URL, HA_TOKEN, OPAL_*, OPAL_LAN_IF…
install -d -o root -g netmap -m 750 /etc/netmap
install -o root -g netmap -m 640 netmap_opal /etc/netmap/opal_ed25519      # key copied into the CT
echo "OPAL_KEY=/etc/netmap/opal_ed25519" >> /opt/netmap/.env
systemctl restart netmap
```

To reuse your names, types and rooms: copy `names.json` and `meta.json` to `/var/lib/netmap/` and run `chown netmap:netmap /var/lib/netmap/*.json`.

The page is available in English and Italian (selector in the header). To get Italian **logs** add `NETMAP_LANG=it` to `.env`.

### 4. Check

```bash
systemctl status netmap
journalctl -u netmap -f                     # look for the line «Cycle 1 · HA ok … · Opal ok …»
curl -s localhost:8080/api/health           # {"status":"ok",…}
```

Open `http://<container-IP>:8080`.

### Update, back up, remove

```bash
cd /opt/netmap && git pull && venv/bin/pip install -r requirements.txt && systemctl restart netmap
```

- **Backup:** `/var/lib/netmap` (database, `names.json`, `meta.json`) and `/opt/netmap/.env`; a Proxmox backup of the container includes them.
- **Remove:** `systemctl disable --now netmap && rm /etc/systemd/system/netmap.service`, then delete `/opt/netmap` and `/var/lib/netmap`.

---

## B. Docker / Compose

> On Proxmox, run Docker in a **VM** (or on an existing Docker host). Inside an LXC you need *nesting* and `keyctl` enabled, and it is a less recommended setup.

### 1. Prepare the folders

```bash
git clone https://github.com/<user>/netmap && cd netmap
cp .env.example .env && nano .env                       # HA_URL, HA_TOKEN, OPAL_HOST, OPAL_LAN_IF…
mkdir -p data secrets
cp names.json meta.json data/ 2>/dev/null || true       # your data, if you already have it
cp /path/to/netmap_opal secrets/opal_ed25519
sudo chown -R 10001:10001 data secrets                  # the user inside the container has UID 10001
sudo chmod 400 secrets/opal_ed25519
```

If you use a password instead of a key: set `OPAL_PASSWORD` in `.env` and remove the `OPAL_KEY` line and the key volume from `docker-compose.yml`.

### 2. Start

```bash
docker compose up -d --build
docker compose logs -f                                  # «Cycle 1 · HA ok … · Opal ok …»
docker inspect --format '{{.State.Health.Status}}' netmap     # healthy
```

Open `http://<host>:8080`. The container only makes **outbound** connections to Home Assistant and the AP, so the default `bridge` network is enough.

### Update and back up

```bash
git pull && docker compose up -d --build
```

- **Backup:** the `./data` folder and the `.env` file.
- **Time zone:** `TZ` is already `Europe/Rome` in the Compose file; change it if needed.
- **Logs in Italian:** add `NETMAP_LANG=it` to `.env`.

---

## Behind a reverse proxy (HTTPS)

Netmap does not do TLS. With Nginx Proxy Manager: *Add Proxy Host* → domain, **Forward** `http://<Netmap-IP>:8080`, SSL tab with a certificate and *Force SSL*. No websockets are needed. If you set `DASH_USER`/`DASH_PASSWORD`, Basic auth is protected by TLS. To keep the dashboard off the Internet use an *Access List* or reach it only from the local network/VPN.

## Monitoring

`GET /api/health` answers **200** when every source is healthy and the last cycle is recent, **503** otherwise. In Uptime Kuma: an *HTTP(s)* monitor, URL `http://<host>:8080/api/health`, accepted status `200-299` (with Basic auth, enter the credentials in the monitor).

## If something does not work

| Symptom in the log or the Diagnostics panel | Likely cause |
|---|---|
| `Home Assistant · AX55: ERROR · … 401` | Wrong or expired token |
| `… ConnectionError` / `Max retries` towards Home Assistant | Wrong `HA_URL`, or the host cannot reach port 8123 |
| `Set HA_URL and HA_TOKEN in the .env file…` | `.env` not read: check its path and permissions (`EnvironmentFile`, `env_file`) |
| `Opal (SSH): ERROR · AuthenticationException` | Key not installed on Dropbear, or wrong password |
| `Incompatible ssh peer (no acceptable host key)` | paramiko 5 does not support the `ssh-rsa` (SHA-1) host key of an older Dropbear. Install `paramiko>=3.4,<5` (already pinned in `requirements.txt`), or give the AP an ed25519 host key: `dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key && /etc/init.d/dropbear restart` |
| `… not found in known_hosts` | With `OPAL_KNOWN_HOSTS` the AP's host key is not in the file |
| `Opal ok 5 s` and slow | Look at `slow: …` in the cycle line; `LOG_LEVEL=DEBUG` shows the time per command |
| `… wired` always 0 | `OPAL_LAN_IF` missing or wrong: `ls /sys/class/net/br-lan/brif`; or use `OPAL_WIRED_MACS` |
| `Database: ERROR · unable to open database file` | The data folder is not writable by the service user (`/var/lib/netmap`, `./data`) |
| Wrong times in the logs | Container time zone (`/etc/localtime`, `TZ`) |
| Doubled cycles or jumping data | More than one process/worker running: there must be exactly one |
| A device shows offline but answers ping | See the README: aliases, source priority and the Diagnostics panel |
