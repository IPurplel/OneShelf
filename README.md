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
* Nothing else. No database to set up, no web server to configure, no account to create.

Podman on Fedora is a first-class path and is what OneShelf is verified against; Docker is equally
supported. If both are present, `./install.sh` uses Podman — set `ONESHELF_RUNTIME=docker` in `.env`
to choose otherwise.

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
absolute path and run `./install.sh` again.

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

If your checkout has local changes, or your branch has diverged from upstream, `./update.sh` stops and
tells you rather than guessing — nothing is changed in that case. To go back to a previous version:

```sh
git log --oneline -5        # find the commit you were on
git checkout <commit>
./install.sh
```

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
sentence in full. It never touches anything outside OneShelf's own directories.

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
which you set up in Settings → Remote Access.

## Advanced: running Compose yourself

The scripts are a convenience, not a requirement. The Compose file is `deploy/compose.yaml` and is
perfectly ordinary:

```sh
# Podman
podman compose -f deploy/compose.yaml build
podman compose -f deploy/compose.yaml up -d
podman compose -f deploy/compose.yaml logs -f
podman compose -f deploy/compose.yaml down          # keeps volumes

# Docker
docker compose -f deploy/compose.yaml build
docker compose -f deploy/compose.yaml up -d
docker compose -f deploy/compose.yaml logs -f
docker compose -f deploy/compose.yaml down
```

`podman-compose` and `docker-compose` (v1) work too; `./install.sh` detects whichever you have.

Configuration lives in `.env` beside the Compose file — copy `.env.example` if you are not using
`install.sh`. Every value is documented there. The container runs as an unprivileged user (uid 10001)
and exposes a healthcheck on `/api/ready`.

### Troubleshooting

* **`podman` or `docker` is installed but nothing happens.** Its service may not be running:
  `systemctl --user start podman.socket`, or `sudo systemctl start docker`.
* **OneShelf cannot write to its directories.** `install.sh` corrects ownership of its own
  directories through the runtime. If you moved them somewhere the container user cannot reach, point
  `ONESHELF_*_PATH` at a directory you own.
* **Something else is on port 8420.** Change `ONESHELF_PORT` in `.env` and run `./install.sh` again.
* **Look at the log.** `podman compose -f deploy/compose.yaml logs --tail=50`

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
