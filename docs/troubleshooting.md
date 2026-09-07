# OneShelf troubleshooting

Deployment always starts with `bash startup.sh` from the repository folder.
The commands below inspect or maintain that deployment.

## Startup and LAN access

- Docker must be running and accessible to your user. On Linux, an access error
  can mean your user lacks Docker permissions. On Windows, enable Docker
  Desktop's WSL integration for the distribution running the script.
- The image targets Linux amd64. Other architectures require Docker emulation;
  native ARM support has not been validated.
- Build errors are printed directly. Fix the reported network, package download,
  or disk-space problem and rerun the script.
- Read container logs with `docker logs --tail 60 oneshelf`. If the script times
  out while the app is still starting, inspect the logs before retrying.
- If localhost works but a phone cannot connect, check that both devices share
  the same LAN, use the host's Wi-Fi/Ethernet IP, and allow TCP 8080 through the
  host's private-network firewall. Guest Wi-Fi may isolate devices.
- Several network interfaces can produce several printed addresses. Docker,
  VPN, or WSL addresses might not be reachable from another device. Use the
  physical host's network settings to find the correct address.
- Do not change the container's listening port in Settings: this deployment
  publishes port 8080 and explicitly sets the application to listen there.

## Storage permissions and backups

New Docker volumes inherit the image directories' ownership. OneShelf runs as
the image's non-root `pwuser`, and startup checks actual writes to both volumes.
If an existing or restored volume is unwritable, inspect its ownership and
restore write access for that user. Do not solve this by deleting the volume.

Inspect storage with:

```bash
docker inspect oneshelf --format '{{json .Mounts}}'
```

Keep the download folder at `/data/manga`. A different path inside the container
may not be persistent. Settings live in `/config/config.yaml`; the queue database
and browser profile also live under `/config`.

Back up **both** `oneshelf_downloads` and `oneshelf_config` using your Docker
volume backup tools. Stop OneShelf before copying the database and browser
profile so the backup is consistent. Removing a container does not erase these
named volumes, but deleting volumes or resetting Docker storage does.

## Existing installation

The startup script checks both the name `oneshelf` and containers labeled as
belonging to the OneShelf Compose project. It refuses to replace containers
that use a different deployment or storage. This
prevents an older library from appearing to disappear behind empty new volumes.

Inspect the old container's mounts with the command above and back up its data.
Also inspect its Compose project label:

```bash
docker inspect oneshelf --format '{{index .Config.Labels "com.docker.compose.project"}}'
```

If the old project is different from `oneshelf` (or has no Compose label), stop
and rename the old container in Docker so the name `oneshelf` is available.
Keep that container and its old folders until you verify the new installation.

If the project label is already `oneshelf`, renaming is insufficient: Compose
still finds the container by its labels. After verifying a complete backup,
explicitly remove that old container in Docker **without deleting its volumes**
before starting the new deployment. The startup script never does this for you.
Keep the backups and old storage until the new library has been verified.

Older layouts included `manga/` and `config/` beside the terminal directory,
`deploy/manga/` and `deploy/config/` for Compose, or `downloads/` and `.state/`
for the desktop launcher. Desktop settings may also be in `config.yaml`.
The script neither deletes nor automatically migrates these files.

To retain the library, copy the old downloads into `oneshelf_downloads` and
the old database and browser profile into `oneshelf_config` using a Docker volume
management tool, with OneShelf stopped. Review old settings before copying them:
desktop paths and visible-browser settings may not work in a container. Keep
the mounted paths above and use `headless: auto`. Restore ownership for
`pwuser`, then rerun `bash startup.sh` and check the Library and Settings.

## Browser checks and sessions

The image includes Chromium, Chrome, and a virtual display. Ordinary JavaScript
checks may clear automatically. Interactive checks can still require a human;
the virtual display is not a remote desktop you can click from the web UI.

In **Settings → Browser session**, you can install a site's `cf_clearance`
cookie and the User-Agent from the browser where you completed its check.
Cookies may expire and may be tied to the public IP, User-Agent, or browser
connection that earned them. A copied cookie is therefore not guaranteed to work.

For sites that require the original browser connection, **Settings → Attach to
my browser** accepts a Chrome/Edge debugging endpoint. Start a separate browser
profile with remote debugging, visit the site, complete the check, and keep
that browser open. See [Chrome's remote debugging documentation](https://developer.chrome.com/docs/devtools/remote-debugging).

An address beginning with `127.0.0.1` inside OneShelf refers to the container,
not your desktop. The endpoint must be reachable from inside the container.
A browser debugging port grants control of that browser: keep it restricted to
trusted connections and never expose it publicly.

If you see “Target page, context or browser has been closed,” reopen the attached
browser. For OneShelf's managed browser, retry the request and inspect the logs.

## Unreachable sources and proxies

Use the app's connectivity information or the diagnostic endpoint:

```bash
curl -s -X POST http://localhost:8080/api/connectivity \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.net/manga/series/"}'
```

| Result | Meaning |
| --- | --- |
| `ok` | The source is reachable |
| `challenge` | A browser check is in the way |
| `connection_reset` | The connection was reset before an HTTP response |
| `connect_error` | Connection failed; check DNS and routing |
| `proxy_error` | The configured proxy is unavailable or rejected the connection |

A connection reset does not by itself prove ISP filtering. Some networks block
sites; others fail because of routing or a source-side restriction. Browser
cookies cannot repair a failed network connection.

OneShelf supports a `proxy` setting and a built-in `desync_enabled` option for
some forms of hostname filtering. Neither is guaranteed to bypass every network
restriction. Configure these through Settings; the browser and downloader must
use the same public exit IP for IP-bound sessions. A proxy on your desktop must
also be reachable from the container—container localhost is not host localhost.
