# Deploying to a Proxmox LXC

Two paths, both starting from a fresh unprivileged Debian 12 container.

| Path | Needs `nesting=1` | Rootfs | Pick it when |
| --- | --- | --- | --- |
| **[Docker](#docker-path)** | yes | 12 GB | You already run Docker, or want Chromium and its libraries to arrive pre-built |
| **[Native systemd](#native-systemd-path)** | no | 8 GB | The container is unprivileged with no nesting, or you want the smaller footprint |

Replace these as you go:

| Placeholder | Meaning | Example |
| --- | --- | --- |
| `<PVE>` | Proxmox host IP or name | `192.168.1.10` |
| `<CTID>` | Container ID you pick | `200` |
| `<STORAGE>` | Proxmox storage for the rootfs | `local-lvm` |

---

# Docker path

## D1. Create the container (on the Proxmox host)

Docker needs nested user namespaces, so this path — unlike the native one —
does require `nesting=1`.

```bash
pveam update
pveam available --section system | grep debian-12
pveam download local debian-12-standard_12.7-1_amd64.tar.zst

pct create <CTID> local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname manga-dl \
  --cores 2 \
  --memory 2048 \
  --swap 512 \
  --rootfs <STORAGE>:12 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --features nesting=1 \
  --onboot 1

pct start <CTID>
```

**12 GB, not 8.** The image carries Chromium *and* a real Chrome on top of a
Python runtime, which is heavier than the native path's venv. Output belongs on
a separate mount either way — see D5.

## D2. Install Docker in the container

```bash
pct exec <CTID> -- bash -c 'apt-get update && apt-get install -y ca-certificates curl'
pct exec <CTID> -- bash -c 'install -m 0755 -d /etc/apt/keyrings && \
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc && \
  chmod a+r /etc/apt/keyrings/docker.asc'
pct exec <CTID> -- bash -c 'echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list'
pct exec <CTID> -- bash -c 'apt-get update && apt-get install -y \
  docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin'
pct exec <CTID> -- docker version
```

If `docker version` fails to reach the daemon, `nesting=1` is missing — go back
to D1.

## D3. Ship the code

From this project directory. The excludes matter enormously: unfiltered, the
project is **3.5 GB** (a downloaded library, a browser profile and several
virtualenvs), none of which the image uses.

```bash
tar --exclude='./.venv*' --exclude='./downloads' --exclude='./.state' \
    --exclude='./__pycache__' --exclude='./.pytest_cache' --exclude='./.git' \
    -czf /tmp/manga-dl.tgz .

scp /tmp/manga-dl.tgz root@<PVE>:/tmp/
```

<details>
<summary>On Windows (PowerShell)</summary>

```powershell
cd "E:\projects\manga downloader"
tar --exclude=".venv*" --exclude="downloads" --exclude=".state" `
    --exclude="__pycache__" --exclude=".pytest_cache" `
    -czf "$env:TEMP\manga-dl.tgz" .
scp "$env:TEMP\manga-dl.tgz" root@<PVE>:/tmp/
```
</details>

Then, on the Proxmox host:

```bash
pct push <CTID> /tmp/manga-dl.tgz /tmp/manga-dl.tgz
pct exec <CTID> -- mkdir -p /opt/src
pct exec <CTID> -- tar -xzf /tmp/manga-dl.tgz -C /opt/src
```

## D4. Build and start

```bash
pct exec <CTID> -- bash -c 'cd /opt/src && docker compose -f deploy/docker-compose.yml up -d --build'
```

The build takes several minutes, most of it installing Chrome and the Python
dependencies. Watch the first line of output: the **transferred build context
should be a couple of megabytes**. If it reports gigabytes, `.dockerignore` did
not come across in the tarball — check that `/opt/src/.dockerignore` exists.

**Chrome is not optional here.** The app prefers a real Chrome and falls back to
the Chromium baked into the base image, which is version 131 — and 131 never
clears a Cloudflare challenge. Without Chrome, every Cloudflare-fronted source
fails while the app otherwise looks healthy. The build installs it by default;
`INSTALL_CHROME: "0"` in `deploy/docker-compose.yml` turns it off if you have a
reason to.

## D5. Point the output at real storage

`docker-compose.yml` bind-mounts the host path `/data/manga` into the container.
Inside an LXC that path is the *container's* filesystem, so give it real storage
from the Proxmox host:

```bash
pct stop <CTID>
pct set <CTID> -mp0 /mnt/pve/nas/manga,mp=/data/manga
pct start <CTID>
```

For an unprivileged container the host directory must be writable by the mapped
UID. Docker runs the app as `pwuser` (UID 1000), which maps to host UID 101000:

```bash
# on the Proxmox host
chown -R 101000:101000 /mnt/pve/nas/manga
```

The database and the persistent Chromium profile live in the named volume
`manga-config`, which is what lets a solved Cloudflare clearance survive a
restart. Leave it alone unless you want to reset the browser session.

## D6. Verify

```bash
# the app answers, and can write where it was told to
pct exec <CTID> -- curl -s localhost:8080/api/health
```

Three things to look for, in order of what they catch:

1. `"output_writable": true` — if false, it is UID mapping on the mount (D5),
   not the application.
2. `session.channel` reads **`chrome`**, not `chromium`. This is the check that
   the Cloudflare fix in D4 actually took. The UI shows the same thing under
   **Settings → Engine**.
3. `browser_running: false` is correct here — Chromium starts lazily on the
   first fetch, not at boot.

Then open `http://<container-ip>:8080` and download **one** chapter before
queuing anything large. A Royal Road URL is the cleanest first test: it needs no
browser at all, so it proves the pipeline independently of any bot check. Follow
it with a Cloudflare-fronted source to confirm point 2 for real.

## Docker housekeeping

```bash
cd /opt/src
docker compose -f deploy/docker-compose.yml logs -f      # follow logs
docker compose -f deploy/docker-compose.yml restart      # restart
docker compose -f deploy/docker-compose.yml down         # stop and remove
```

To update: repeat D3, then re-run D4. The named volume keeps your settings,
database and browser profile.

---

# Native systemd path

Ships the code and installs the service directly. No Docker, no nesting.

---

## 1. Create the container (on the Proxmox host)

SSH into the Proxmox host as root.

```bash
# Check what storage you actually have - local-lvm is common but not universal
pvesm status

# Refresh the template list and see what Debian 12 build is current
pveam update
pveam available --section system | grep debian-12
```

Download whatever version that last command listed (the version suffix changes
over time — use the exact name it printed):

```bash
pveam download local debian-12-standard_12.7-1_amd64.tar.zst
```

Create and start the container:

```bash
pct create <CTID> local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname manga-dl \
  --cores 2 \
  --memory 2048 \
  --swap 512 \
  --rootfs <STORAGE>:8 \
  --net0 name=eth0,bridge=vmbr0,ip=dhcp \
  --unprivileged 1 \
  --onboot 1

pct start <CTID>
```

**Why these numbers.** Chromium is the memory driver — below about 1.5 GB it
gets OOM-killed part-way through a Cloudflare challenge, which looks like a
mysterious timeout. 8 GB rootfs holds the system, the venv and Chromium
(~1.5 GB) with room spare; your CBZ files should go on a separate mount
(step 5), not the rootfs.

**No `nesting=1` needed.** Chromium's sandbox wants nested user namespaces,
but the app passes `--no-sandbox` unconditionally for exactly this case. Only
the Docker path needs nesting.

Find the container's IP — you'll need it at the end:

```bash
pct exec <CTID> -- hostname -I
```

---

## 2. Package and ship the code

From this project directory:

```bash
tar --exclude='./.venv*' --exclude='./downloads' --exclude='./.state' \
    --exclude='./__pycache__' --exclude='./.pytest_cache' --exclude='./.git' \
    -czf /tmp/manga-dl.tgz .

scp /tmp/manga-dl.tgz root@<PVE>:/tmp/
```

<details>
<summary>On Windows (PowerShell)</summary>

Windows 10+ has `tar` and `scp` built in, so nothing to install.

```powershell
cd "E:\projects\manga downloader"
tar --exclude=".venv*" --exclude="downloads" --exclude=".state" `
    --exclude="__pycache__" --exclude=".pytest_cache" `
    -czf "$env:TEMP\manga-dl.tgz" .
scp "$env:TEMP\manga-dl.tgz" root@<PVE>:/tmp/
```
</details>

The excludes matter, and `.venv*` covers more than one thing: a Windows `.venv`
(~250 MB of binaries useless on Linux), a `.venv-linux` if the project was built
on Linux (~380 MB), and any `.venv.backup-*`. `downloads/` and `.state/` are a
CBZ library and a browser profile — gigabytes, and both belong on the container
side, not in the tarball. Filtered, the archive is well under a megabyte.

---

## 3. Push it into the container (on the Proxmox host)

`pct push` copies from the host into the container, so the container needs no
SSH server of its own.

```bash
pct push <CTID> /tmp/manga-dl.tgz /tmp/manga-dl.tgz

pct exec <CTID> -- mkdir -p /opt/src
pct exec <CTID> -- tar -xzf /tmp/manga-dl.tgz -C /opt/src
```

---

## 4. Install

```bash
pct exec <CTID> -- bash -c "chmod +x /opt/src/deploy/install.sh && /opt/src/deploy/install.sh"
```

`chmod +x` is needed because a tar built on Windows does not carry the Unix
executable bit.

This takes a few minutes — most of it is `playwright install --with-deps
chromium` pulling Chromium and its system libraries. The script prints the URL
when it finishes.

To install somewhere other than the defaults:

```bash
pct exec <CTID> -- bash -c "DATA_DIR=/mnt/manga PORT=9090 /opt/src/deploy/install.sh"
```

Defaults: user `mangadl`, app in `/opt/manga-downloader`, config in
`/etc/manga-downloader`, output in `/data/manga`, port 8080.

---

## 5. Point the output at real storage (optional but recommended)

By default CBZ files land on the container's 8 GB rootfs, which will fill up.
Bind-mount your NAS or a host directory instead — do this from the **host**,
because an unprivileged container cannot mount NFS or CIFS itself.

```bash
pct stop <CTID>
pct set <CTID> -mp0 /mnt/pve/nas/manga,mp=/data/manga
pct start <CTID>
```

For an unprivileged container, the host directory must be writable by the
container's mapped UID. The container's `mangadl` user maps to host UID
`100000 + <uid>`. The simplest fix on the host:

```bash
chown -R 101000:101000 /mnt/pve/nas/manga
```

Then confirm in the UI under **Settings → Browser session → Output writable**.
If that says no, it is a UID mapping problem on the mount, not the application.

---

## 6. Verify

```bash
# Service is up
pct exec <CTID> -- systemctl status manga-downloader --no-pager

# API responds and reports a writable output directory
pct exec <CTID> -- curl -s localhost:8080/api/health
```

A healthy response looks like:

```json
{"status":"ok","version":"1.0.0","output_writable":true,
 "session":{"browser_running":false,...},
 "adapters":[{"id":"madara",...},{"id":"generic",...}]}
```

`browser_running: false` is correct at this point — Chromium starts lazily on
the first fetch, not at boot.

Now open `http://<container-ip>:8080` from your laptop.

**First run:** fetch the series, download a **single** chapter first, and check
that the page count matches the site's reader and that the CBZ opens
right-to-left. Then queue the rest.

---

## 7. If the site is blocked on your network

Check this **before** assuming the app is broken. Some networks filter sites by
reading the hostname out of the TLS handshake and resetting the connection, which
looks like a vague timeout in the UI:

```bash
pct exec <CTID> -- curl -s -X POST localhost:8080/api/connectivity \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.net/manga/series/"}'
```

If `kind` comes back `connection_reset`, the container's network path is
filtered — not the application, and not the site blocking you. The container
shares the host's uplink, so it inherits whatever your workstation experiences.

**Try the built-in bypass first** — it needs no external service. In
`/etc/manga-downloader/config.yaml`:

```yaml
desync_enabled: true
```

It starts a local SOCKS5 proxy that splits the TLS handshake so the filter
cannot read the hostname, and routes the browser and downloader through it.

If that is not enough, give the app a different exit path instead:

```yaml
proxy: socks5://127.0.0.1:1080
```

then restart:

```bash
pct exec <CTID> -- systemctl restart manga-downloader
```

The cheapest option that needs no subscription is an SSH tunnel from inside the
container to any machine outside the filtered network:

```bash
pct exec <CTID> -- apt-get install -y autossh
# then run autossh -D 1080 -N user@your-vps under its own systemd unit
```

This routes both the browser and the image downloader together, which is
required — a Cloudflare clearance cookie is bound to the IP that earned it, so a
split path fails every request. Re-run the connectivity check to confirm it
flips to `ok` or `challenge`.

## Updating later

Repeat steps 2 and 3, then re-run the installer. It preserves your existing
`/etc/manga-downloader/config.yaml`, so settings survive:

```bash
pct exec <CTID> -- systemctl stop manga-downloader
pct exec <CTID> -- bash -c "chmod +x /opt/src/deploy/install.sh && /opt/src/deploy/install.sh"
```

---

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `install.sh: bad interpreter` | CRLF line endings. `pct exec <CTID> -- sed -i 's/\r$//' /opt/src/deploy/install.sh` |
| `Permission denied` running installer | Missing `chmod +x` (see step 4) |
| `Python 3.11+ required` | Not Debian 12. Use the Debian 12 or Ubuntu 24.04 template. |
| Service starts then dies | Usually RAM. `pct set <CTID> -memory 2048` and check `journalctl -u manga-downloader -n 60`. |
| Can't reach the web UI | Container firewall or wrong IP. Confirm with `pct exec <CTID> -- ss -tlnp \| grep 8080`. |
| Preview times out | Cloudflare challenge not clearing. Check **Settings → Engine**: it should read `patchright (patched) · chrome · headless (auto)`. Interactive Turnstile needs the manual-cookie fallback in the main README. |
| Never escalates to headful | `xvfb` missing. `pct exec <CTID> -- apt-get install -y xvfb`, then restart the service. |
| Engine says `chromium` not `chrome` | Chrome was skipped or failed to install. Re-run the installer, or `apt-get install -y google-chrome-stable`. Bundled Chromium works but clears fewer challenges. |
| Chromium fails to launch | `pct exec <CTID> -- /opt/manga-downloader/venv/bin/playwright install --with-deps chromium` |

Logs:

```bash
pct exec <CTID> -- journalctl -u manga-downloader -f
```

### Docker path

| Symptom | Cause and fix |
| --- | --- |
| `docker version` cannot reach the daemon | `nesting=1` is missing. `pct set <CTID> -features nesting=1` and reboot the container. |
| Build sends gigabytes of context, or fills the rootfs | `.dockerignore` is not in `/opt/src`. It is a dotfile — confirm your `tar` included it (`tar tzf /tmp/manga-dl.tgz \| grep dockerignore`). |
| **Settings → Engine** says `chromium`, not `chrome` | Chrome did not install. Look for the `WARNING: Chrome install failed` line in the build output, then rebuild with `docker compose -f deploy/docker-compose.yml build --no-cache`. Cloudflare sources will keep failing until this reads `chrome`. |
| Every Cloudflare site fails but the app looks healthy | Same cause as the row above. Check `session.channel` in `/api/health` before suspecting the adapters. |
| Chromium dies immediately | `/dev/shm` too small. Compose sets `shm_size: 1gb`; confirm it survived any edits. |
| `output_writable: false` | UID mapping on the bind mount. Docker runs as UID 1000, which maps to host UID 101000 — see D5. |
| Downloads vanish after `docker compose down` | Output was landing inside the container. Bind `/data/manga` to real storage (D5). |

Note there is **no authentication** on the web UI. Keep it on your LAN; put it
behind your existing reverse proxy or VPN if you need remote access.
