# ADR 0002 — Bind mounts for the library, with ownership corrected through the runtime

**Date:** 2026-09-21 · **Status:** Accepted

## The situation

The container runs as an unprivileged user (uid 10001). OneShelf's five persistent areas — data,
content, plugins, keys, backups — must be writable by it, must survive `down`/`up` and recreation, and
must be somewhere a person can find, copy and back up.

## The decision

Keep **bind mounts** to directories the person can see (`deploy/volumes/...` by default, or any
absolute path via `.env`), and where the container user cannot write, correct the ownership of *those
directories only* by running a short one-shot container as root inside the runtime.

## Why not named volumes

Named volumes get their ownership right automatically, which is simpler. But this is a library
application: the whole point is that the files are the person's own. "Your books are in
`deploy/volumes/content`" is something someone can act on — copy it, move it to a bigger disk, put it
on a NAS. `podman volume inspect` is not.

## Why not `chown` on the host

Because it would need `sudo`, and an installer that asks for root to fix permissions is an installer
that can damage a machine. Running `chown` inside the runtime needs no host privilege at all: under
rootless Podman it maps to the user's own subuid range, and under Docker it is the daemon doing what
it already does for named volumes.

## What it commits us to

* `install.sh` probes whether the container user can write, and only acts when it cannot — so a repeat
  install does nothing.
* Only the five OneShelf directories are ever touched. `uninstall.sh --delete-data` refuses to remove
  `/`, `$HOME` and other obvious mistakes, and removes nothing else.
* Permissions are never loosened to make installation work: ownership is corrected, not widened.
