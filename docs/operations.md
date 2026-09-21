# Running OneShelf

Deployment, startup, storage, backup, restore and upgrade — what the software actually does, not a wish list.
Authority: Master §2.1, §13, §18, §24–25, §33–34, §42; Meta Prompt §C9.

## 1. What you need

- A container runtime (Docker or Podman), or Python 3.12+ for a direct run.
- Disk for the library itself. OneShelf keeps a reserve free on every storage location (5%, capped at 5 GB) and
  pauses background writes rather than filling the disk (§24.5).
- Nothing else. There is no cloud account, no external service and no telemetry.

## 2. Mounts, and why they are separate

| Mount | Holds | Notes |
|---|---|---|
| `/data` | `oneshelf.db` (authoritative), `cache.db` (rebuildable), `secrets.db` (encrypted source sessions), staging, snapshots, diagnostics | Back this up. Losing `cache.db` costs nothing. |
| `/data/plugins` | installed `.osp` packages, including the eight official sources installed on first run | Rebuildable by reinstalling, but keeping it avoids re-approving permissions. Recreating the container does **not** reinstall a source you removed. |
| `/keys` | `session.key`, the key for `secrets.db` | **Its own volume.** It is deliberately excluded from every backup (§33.3), so store it where you store passwords. Lose it and source logins must be redone; nothing else is affected. |
| `/content` | a storage location for downloaded and imported files | Add more locations in Settings → Storage; OneShelf never writes outside a registered location. |
| `/data/backups` | `.osbackup` archives | Prefer a different physical disk: OneShelf warns when backups sit on the same device as the library (§33.9). |

## 3. Start it

```sh
./install.sh
# Later manual operations, from the repository root:
# docker compose --env-file .env -f deploy/compose.yaml up -d --build
curl -fsS http://127.0.0.1:8420/api/ready
```

`/api/ready` returns `ready: true` only once migrations are applied and startup recovery has finished, which is
what the container healthcheck uses. `/api/health` is the lighter liveness check.

Direct run, without a container:

```sh
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements.lock && .venv/bin/pip install --no-deps -e .
ONESHELF_DATA_DIR=./var .venv/bin/python -m oneshelf.api.app
```

### Configuration

| Variable | Default | Meaning |
|---|---|---|
| `ONESHELF_DATA_DIR` | `.oneshelf-dev` | Application data directory. |
| `ONESHELF_SESSION_KEY_FILE` | `<data>/keys/session.key` | Key for the encrypted source-session store; mount separately. |
| `ONESHELF_TRUSTED_NETWORKS` | empty | CIDRs treated as your LAN. Empty means loopback only. First Run and Settings can add more without a restart. |
| `ONESHELF_TRUSTED_PROXIES` | empty | CIDRs whose `X-Forwarded-For` is believed. Anything else is ignored entirely. |
| `ONESHELF_ALLOWED_HOSTS` | `localhost` plus IP literals | Host header allowlist (DNS-rebinding defence). The canonical hostname you set for remote access is accepted automatically. |
| `ONESHELF_HOST`, `ONESHELF_PORT` | `127.0.0.1`, `8420` | Bind address. |
| `ONESHELF_REGISTRY_URL` | the Source Registry, `https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json` (Compose and `.env.example`) | Read only when Sources → Source Registry is opened. `ONESHELF_REGISTRY_URL=` (set, empty) switches it off. The old default `https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json` is read as the new one at container start, without editing `.env`. `https://` or a local `file://` mirror. |
| `ONESHELF_FIRST_PARTY_REGISTRY_URL` | `https://raw.githubusercontent.com/IPurplel/OneShelf-Adapters/registry/index.json` (Compose and `.env.example`) | The Registry whose Official and Verified Community tiers are trusted without a signature — only while `ONESHELF_REGISTRY_URL` is exactly this URL. Empty: no Registry is trusted by its tiers. |
| `ONESHELF_REGISTRY_TRUSTED_KEYS` | empty | Optional **public** Ed25519 keys (`key-id:base64,…`). A valid signature from one of them makes an Official/Verified Community claim count from any Registry, shown as *Signed*. List two while rotating. A private key never goes in configuration. |
| `ONESHELF_DEV_TEST_SOURCE`, `ONESHELF_DEV_TEST_SOURCE_ADDRESS` | off | Development only: enables the bundled Test Source and its loopback exception. Never set these in a real deployment. |

## 4. Access

- **Local**: loopback is trusted, no authentication.
- **LAN**: list your subnets in `ONESHELF_TRUSTED_NETWORKS` (or finish First Run with Access Mode = LAN). A genuine
  LAN device is fully trusted, including administrative actions such as resetting remote passkeys.
- **Remote**: put OneShelf behind HTTPS on a stable hostname, set that hostname in First Run, and register a
  passkey from a LAN device. Remote clients then need a passkey session. Record the Recovery Code it shows once.
- Behind a reverse proxy, add the proxy's address to `ONESHELF_TRUSTED_PROXIES`. An unlisted proxy
  contributes its own peer address, which is trusted if it is loopback or an allowed LAN address.
  Configure a same-host or LAN proxy **before** exposing it publicly; a listed proxy requires the
  forwarded client identity and never lends its own LAN trust to remote visitors.
- If every client appears to arrive from one address, OneShelf says so in Settings: that means a router or proxy is
  forwarding, and your trusted networks are wider than you think.

## 5. Backups

- A **Library Backup** runs every seven days and catches up after downtime. It holds library state — works, shelf,
  progress, follows, mappings, settings, plugin requirements — and no downloaded reading files.
- A **Full Backup** is manual and adds the content of the works you select.
- Sessions, cookies, tokens, the recovery verifier, the master key, browser profiles, staging and rebuildable caches
  are excluded by construction, not by filtering.
- The last four **verified** archives are kept. A new archive is verified before any old one is rotated out, so a
  failed verification never costs you a good backup.
- An archive is **not encrypted** by OneShelf, and none is required: it carries no session, token or key, because
  those are excluded by construction above (§33.10). If the disk holding `/data/backups` needs to be encrypted — an
  off-site copy, a shared NAS — encrypt it where you already encrypt things: a LUKS volume, an encrypted dataset,
  or your own tool over the `.osbackup` file. OneShelf reads whatever it is given back, so nothing in it prevents
  that, and nothing in it pretends to have done it for you.

```sh
curl -X POST http://127.0.0.1:8420/api/backups -d '{"kind":"library"}' -H 'Content-Type: application/json'
curl http://127.0.0.1:8420/api/backups           # list, due, same-disk warning
```

## 6. Restore

1. **Preflight** (`POST /api/restore/preflight`) checks the archive, its checksums, schema compatibility, space,
   and which plugins it expects. An older archive is migrated forward in a staging copy; the file itself is never
   modified. An archive from a newer OneShelf is refused rather than half-read.
2. **Merge** adds records you no longer have, keeps your current manual decisions, never moves reading progress
   backwards, and only repairs files that are missing or corrupt.
3. **Replace Current Library** takes a Safety Snapshot first, then replaces.
4. Missing plugins never block a restore; they are listed so you can reinstall or skip. New plugin permissions are
   reported for approval, never granted by a restore.

## 7. Upgrades

- Pull the new image and recreate the container. Migrations are numbered and forward-only; they run inside a
  transaction after a consistent snapshot is taken, and the snapshot stays in `/data/snapshots` for recovery.
- A database newer than the running build is refused with a clear message rather than opened.
- Downgrading is not supported. Restore a backup taken with the older version instead.

## 8. When something goes wrong

- A storage location that is offline shows as **Storage Location Unavailable**. Files are never mass-marked missing
  and nothing is cleaned up; reconnect the disk and OneShelf reconciles.
- Interrupted downloads resume; unverified artefacts are never registered as library content.
- Diagnostics live under `/data/diagnostics`, rotate after 7 days or 100 MB, and are redacted at write time.
- If a source changes its markup, use the generator's **Repair Existing Adapter** flow: it diagnoses the live site,
  proposes a selector diff, validates the replacement, and only then lets you activate it.

## 9. The Source Registry

Published from [OneShelf-Adapters](https://github.com/IPurplel/OneShelf-Adapters). Installed sources never depend on it: if it cannot be reached,
Sources says so and everything else carries on; `/api/ready` does not consult it. To run without it, set
`ONESHELF_REGISTRY_URL=` in `.env`. To mirror it offline, copy the `registry` branch of OneShelf-Adapters
somewhere and point `ONESHELF_REGISTRY_URL` at `file:///that/directory`. It is read when the Sources screen
opens (cached 5 minutes, failures 60 seconds) — never polled in the background. Its Official and Verified
Community entries are trusted as such because it is the configured first-party Registry (`plugins.md` §7);
a mirror keeps that trust only if `ONESHELF_FIRST_PARTY_REGISTRY_URL` names the mirror too.
