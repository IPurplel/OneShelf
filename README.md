# OneShelf

A personal reading library that lives on your own machine.

OneShelf keeps manga, comics, books and papers in one place: it finds them at the sources you choose,
downloads what you ask for, remembers where you stopped reading, and tells you when something new
arrives. There is no account, no cloud, and nothing phones home. Your library is a directory on your
own disk, and you can pick it up and move it whenever you like.

## Quick start

```sh
git clone https://github.com/IPurplel/OneShelf.git
cd OneShelf
./install.sh
```

Then open **<http://127.0.0.1:8420>**.

Release verification is still awaiting the Fedora-host container gate. Script and application tests
pass independently; see [the host verification commands](docs/c9/verification.md#3a-the-final-release-gate--what-the-fedora-host-must-run).

The first run builds the image, which takes a few minutes. After that, starting takes seconds.

```sh
./update.sh       # update to the latest version, keeping your library
./uninstall.sh    # stop OneShelf, keeping your library
```

### What you need first

* **A container runtime.** Either Podman or Docker. OneShelf will not install one for you, and will
  say exactly what to do if neither is there.
  * Fedora / RHEL: `sudo dnf install podman podman-compose`
  * Debian / Ubuntu: `sudo apt install podman podman-compose`
  * Or [Docker Engine](https://docs.docker.com/engine/install/) with the Compose plugin.
* **About 3 GB of disk** for the image, plus whatever your library grows to.
* **Linux, Bash, Git, coreutils and curl or wget.** No database or separate web server to configure.

Podman on Fedora is a first-class path; Docker Engine on Linux is also supported. The real container
gate is pending. If both are present, the scripts prefer Podman. To choose Docker, run
`ONESHELF_RUNTIME=docker ./install.sh` (use the same prefix for update and uninstall).
The Linux deployment uses host networking so the application sees the real client IP; it binds only
to loopback by default. It shares the host network namespace. Docker Desktop is not a verified path.

## Where your library lives

Everything persistent is kept outside the container, in five directories:

| Directory | What is in it |
|---|---|
| `deploy/volumes/data` | the library database, the search index, staging and diagnostics |
| `deploy/volumes/content` | your downloaded and imported files |
| `deploy/volumes/plugins` | the source adapters you have installed |
| `deploy/volumes/keys` | the key for your saved source logins — **back this up separately** |
| `deploy/volumes/backups` | OneShelf's own `.osbackup` archives |

They survive restarts, rebuilds, updates, and removing the container entirely. To keep your library
somewhere else — a bigger disk, a different mount — set the matching `ONESHELF_*_PATH` in `.env` to an
absolute path **dedicated to OneShelf**. The installer may change ownership of those five directories
and label them for SELinux; do not select shared directories. Paths may not overlap or contain
symlinks. A nonempty custom directory must already contain the `.oneshelf-managed` marker from
a previous install; otherwise the installer stops before relabelling or changing ownership. When
migrating existing OneShelf-only storage manually, review its contents, back it up, and create that
empty marker yourself to explicitly designate it for OneShelf. Changing a path does not move existing content: copy it while stopped, then change `.env`
and run `./install.sh` again. The existing copy is yours to retain.

Configuration is a literal `KEY=value` file at the repository root. Quotes and inline comments are
supported; multiline values, variable interpolation and escapes are rejected by the scripts. Exported
`ONESHELF_*` deployment values override `.env` consistently for Compose and readiness probes.

### Backups

OneShelf takes a **Library Backup** of its own every seven days into `deploy/volumes/backups`: your
works, shelf, reading progress, follows and settings, without the files themselves. A **Full Backup**
adds the content of works you choose, and is manual. Keep those archives on a different disk from the
library if you can — OneShelf warns you when they are on the same one.

Two things are deliberately **not** in any backup: the session key in `keys/`, and your saved source
logins. Copy the `keys/` directory somewhere safe yourself, the way you would a password.

## Updating

```sh
./update.sh
```

It pulls the latest version, rebuilds, and restarts. Your library, your settings and your `.env` are
left alone, and database migrations run the same way they do on any normal start.

Automatic Git updates require `main` and `origin/main`, a clean tracked tree, no unfinished Git
operation, and no local commits ahead of or diverged from the remote. A checkout without an upstream,
or an archive without Git metadata, rebuilds locally with an explicit notice. Untracked files are
preserved; Git refuses an update if they would be overwritten.

Back up before updating. Migrations run on startup and are forward-only: a failed health check does
not mean the database is unchanged. Do not simply check out an older commit against a newer database.
Preserve the volumes and follow [upgrade/recovery instructions](docs/operations.md#7-upgrades), using
a compatible backup or pre-migration snapshot if a downgrade is necessary.

## Uninstalling

```sh
./uninstall.sh
```

stops and removes the containers and **keeps every byte of your library**. Run `./install.sh` again
whenever you want it back.

If you genuinely want the data gone as well:

```sh
./uninstall.sh --delete-data
```

It lists exactly which directories it will delete, and only proceeds if you type the confirmation
sentence in full. Automatic deletion is limited to the five default `deploy/volumes/` directories.
Custom paths, symlinked paths and overlapping paths are refused; review and remove custom storage
manually. A failure to remove a directory is reported as failure, never as success.

## Reaching OneShelf from other devices

By default OneShelf listens on this machine only. To use it from a phone or tablet on your own
network, edit `.env`:

```sh
ONESHELF_BIND=0.0.0.0
ONESHELF_TRUSTED_NETWORKS=192.168.1.0/24    # the subnet you actually trust
ONESHELF_ALLOWED_HOSTS=localhost,my-machine.local
```

then `./install.sh` again. Trust is decided by the real network connection, never by a header a
client can set. Anything arriving from outside those networks has to authenticate with a passkey,
which you set up in Settings → Remote Access. If a reverse proxy runs on this same host, configure
its address in `ONESHELF_TRUSTED_PROXIES` **before exposing it publicly**; otherwise the application
sees its trusted loopback connection instead of the remote visitor. See [access configuration](docs/operations.md#4-access).

## Advanced: running Compose yourself

The scripts are a convenience, not a requirement. The Compose file is `deploy/compose.yaml` and is
ordinary. After the first `./install.sh` has prepared configuration, directories and ownership,
use these commands from the repository root:

```sh
# Podman
podman compose --env-file .env -f deploy/compose.yaml build
podman compose --env-file .env -f deploy/compose.yaml up -d
podman compose --env-file .env -f deploy/compose.yaml logs -f
podman compose --env-file .env -f deploy/compose.yaml down          # keeps volumes

# Docker
docker compose --env-file .env -f deploy/compose.yaml build
docker compose --env-file .env -f deploy/compose.yaml up -d
docker compose --env-file .env -f deploy/compose.yaml logs -f
docker compose --env-file .env -f deploy/compose.yaml down
```

Standalone `podman-compose` and `docker-compose` providers implementing the current Compose
specification are detected too. Legacy Docker Compose v1 is not a supported target.

Configuration lives in `.env` at the repository root, not in `deploy/`. Always pass `--env-file .env`
when invoking Compose manually. Relative bind paths are resolved relative to `deploy/`. Every value is documented there. The container runs as an unprivileged user (uid 10001)
and exposes a healthcheck on `/api/ready`.

### Legacy deployment storage

Pre-release images stored plugins and backups inside the data directory, despite exposing separate
mounts. The scripts stop before new mounts could hide those files. If that check fails, inspect the
runtime error first. For an actual legacy install: stop it with `./uninstall.sh`, back up all five
host directories, and copy the contents of `<data-path>/plugins` and `<data-path>/backups` into the
configured plugin and backup host directories **only when those destinations are empty**. Use
`podman unshare` for rootless-owned files. Never merge or overwrite populated destinations. Rename
the original subdirectories to `plugins.pre-release` and `backups.pre-release` to retain them, then
rerun `./install.sh`. These are file-location changes; database migrations still run only on startup.
If unsure which copies are authoritative, keep both and stop before moving anything.

### Troubleshooting

* **`podman` or `docker` is installed but nothing happens.** Its service may not be running:
  `systemctl --user start podman.socket`, or `sudo systemctl start docker`.
* **OneShelf cannot write to its directories.** `install.sh` corrects ownership of its own
  directories through the runtime. If you moved them somewhere the container user cannot reach, point
  `ONESHELF_*_PATH` at a directory you own.
* **Something else is on port 8420.** Change `ONESHELF_PORT` in `.env` and run `./install.sh` again.
* **Look at the log.** `podman compose --env-file .env -f deploy/compose.yaml logs --tail=50`

## What OneShelf will not do

It does not bypass paywalls, DRM, CAPTCHAs or anti-bot systems; it does not solve challenges or
pretend to be a browser it is not. Where a source's `robots.txt` disallows something, OneShelf simply
does not do it, and the missing capability is recorded rather than worked around. There is no
telemetry of any kind, no account, and no cloud service behind it.

## Sources

Eight sources ship and are verified against the live sites: MangaDex, WEBTOON, Tapas, 3asq
(Al-Aasheq), Safahat (Hindawi), Project Gutenberg, arXiv and Standard Ebooks. Each is a declarative
package — data, not code — and you can see exactly what each one asks for before installing it. What
each can and cannot do is recorded in
[docs/c9/source-capability-ledger.md](docs/c9/source-capability-ledger.md).

## Documentation

| | |
|---|---|
| [docs/operations.md](docs/operations.md) | deployment, storage, backup, restore, upgrade |
| [docs/api.md](docs/api.md) | the HTTP API |
| [docs/plugins.md](docs/plugins.md) | how source packages work, and how to write one |
| [docs/development.md](docs/development.md) | running from source, tests, environment variables |

## Licence

No licence has been chosen yet. Until one is added, the default applies: the code is published for you
to read, and no rights to use, modify or redistribute it are granted. If you intend others to use
OneShelf, add a `LICENSE` file — that choice is yours to make, not one this repository should assume.
