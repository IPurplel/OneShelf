# ADR 0003 — Preserve peer addresses and use the actual storage paths

Status: accepted for Linux release implementation; Fedora runtime verification pending.

The access boundary depends on the real peer IP. Rootless bridge port forwarders may replace it
with their gateway IP. Trusting that gateway would trust unrelated remote clients too. Compose uses
Linux host networking, with the application itself binding `ONESHELF_BIND`/`ONESHELF_PORT` (loopback
by default). Network namespace isolation is reduced; application outbound policy remains unchanged.
A same-host reverse proxy must be configured as a trusted proxy before public exposure, so forwarded
remote clients do not inherit loopback trust. Docker Desktop is not a verified deployment target.

References: [Podman rootless networking](https://github.com/podman-container-tools/podman/blob/main/rootless.md)
and [Docker host networking](https://docs.docker.com/engine/network/drivers/host/).

Mount plugins and backups at `/data/plugins` and `/data/backups`, the paths the application actually
uses, retaining separate host disks and existing in-container paths. An install/update preflight mounts
only the data directory and refuses nonempty legacy subdirectories before they could be concealed.
The image independently checks a read-only `/legacy-data` view before launching the app, so even
a pre-release updater that continues its old script after pulling cannot bypass the check.
Neither check moves or deletes data. README describes manual stopped migration preserving originals.

All five bind mounts and ownership helpers use shared SELinux labels (`:z`) because helpers and the
application access the same directories. Helpers use distinct numbered targets, including when host
paths share a basename. Ownership repair runs before startup and a failure stops installation.
See [Podman volume labels](https://docs.podman.io/en/latest/markdown/podman-run.1.html).

The build ignore file belongs at the repository root, matching the Dockerfile's build context;
`deploy/.dockerignore` did not exclude local data from that context. The container healthcheck now
uses the configured listener and requires readiness JSON, including on nondefault ports.
