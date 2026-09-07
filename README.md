# Manga Downloader

A self-hosted manga downloader with a browser-based GUI, built to run headless
in an LXC container. Paste a series URL, pick chapters, get one lossless CBZ per
chapter on your NAS.

It targets **platforms, not domains**, so one adapter covers every site built on
that platform — including Arabic scanlation sites — and keeps working when any
of them changes hostname.

| Adapter | Platform | Coverage |
| --- | --- | --- |
| `mangathemesia` | MangaThemesia / "TS" WordPress theme | Hundreds of sites; the most common theme among Arabic and Indonesian scanlation groups |
| `madara` | Madara WordPress theme | Hundreds of sites. Verified: `manga-starz.net` (391 chapters), `3asq.online` (مانجا العاشق) |
| `comix` | comix.to | Astro app; chapter list and reader read from the rendered page |
| `blogger` | Blogger / Blogspot comic blogs | Issue lists injected by the theme's own script |
| `webtoons` | webtoons.com | Free episodes. Page URLs live in `data-url`, not `src`; the image host needs the chapter as `Referer` |
| `royalroad` | royalroad.com | Web fiction, packaged as EPUB. Chapter list read from the inline `window.chapters` array |
| `scribblehub` | scribblehub.com | Web fiction, packaged as EPUB. Table of contents paged serially — the site rate-limits |
| `sunovels` | sunovels.com | Arabic web novels, packaged as EPUB. Chapter listing pages are **zero-based** |
| `ao3` | archiveofourown.org | Uses the archive's *own* EPUB/MOBI/PDF/AZW3 downloads rather than scraping chapters |
| `books` | direct-file book sites | …now including Hindawi/Safahat (`hindawi.org` → `safahat.org`) |
| `generic` | anything else | Heuristic fallback: the largest run of sequentially-named images |

Prose sources are written as **one EPUB per chapter**, mirroring the one-CBZ-per-chapter
model: the queue's unit of work, resume and progress is a chapter, and Unicode,
Arabic text and right-to-left reading direction are preserved.

Adapters are chosen by **fingerprinting the DOM**, not by hostname, so a new
site on a known platform needs no code at all — paste its URL and it works.
Sites are identified from the page itself, so a theme that carries markers of
two platforms resolves to the more specific one.

```
┌─ Manga Downloader ─────────────────────── ⚙ ─┐
│ URL: https://example.net/manga/series/  [Fetch]│
├────────────────────────────────────────────────┤
│ Example Series                  madara adapter │
│ 364 chapters found                             │
│ [Select all] [None] [Not downloaded] [1]→[364] │
├────────────────────────────────────────────────┤
│ Ch 12  ████████████████░░░  18/22 pages        │
│ Ch 13  ░░░░░░░░░░░░░░░░░░░  queued             │
│ Ch 11  ██████████████████   done               │
└────────────────────────────────────────────────┘
```

## Features

- **Web GUI** — works headless; open it from any device on your LAN.
- **Bulk or selective** — all chapters, a numeric range, or individual ticks.
- **Lossless CBZ** — images stored byte-for-byte, no re-encoding, with
  `ComicInfo.xml` for Komga, Kavita, YACReader and Mihon/Tachiyomi.
- **Best quality** — strips CDN resize parameters and unwraps image proxies
  (weserv, Jetpack Photon, statically, Next.js) to reach the originals.
- **Clears Cloudflare** — a patched browser solves the JS challenge and hands
  its session to a fast parallel HTTP downloader, escalating to a real Chrome
  and a headful display on its own. Interactive Turnstile still needs a pasted
  cookie; see the measurements below.
- **Resumable** — kill it mid-run; it skips finished chapters and cleans up
  partial files on the next start.
- **Polite** — per-host rate limiting, jitter, and exponential backoff.

## Install

Both paths are supported. Pick based on how your LXC is configured.

### Docker (recommended)

The official Playwright image already contains Chromium and its system
libraries, which removes the biggest source of install pain.

**Requires nesting on the container:**

```bash
# On the Proxmox host:
pct set <ctid> -features nesting=1
pct reboot <ctid>
```

Then inside the container:

```bash
git clone <this-repo> manga-downloader && cd manga-downloader
# Edit the left side of the /data/manga volume to point at your storage
docker compose -f deploy/docker-compose.yml up -d --build
```

### Native systemd

Works in an **unprivileged LXC with no nesting** and uses less RAM. The script
installs Chromium's system dependencies for you.

```bash
git clone <this-repo> manga-downloader && cd manga-downloader
sudo ./deploy/install.sh
```

Override defaults with environment variables:

```bash
sudo APP_DIR=/opt/mangadl DATA_DIR=/mnt/nas/manga PORT=9090 ./deploy/install.sh
```

Then open `http://<container-ip>:8080`.

## Proxmox / LXC notes

**Container sizing** — 2 vCPU, 2 GB RAM, ~3 GB disk beyond the base image.
Chromium is the memory driver; below ~1.5 GB it gets OOM-killed mid-challenge.

**Unprivileged vs privileged** — the native path runs fine unprivileged. Docker
needs `nesting=1`. Neither path needs a privileged container.

**Shared memory** — Chromium maps large buffers and dies on a container's tiny
default `/dev/shm`. Compose sets `shm_size: 1gb`, and the app additionally
passes `--disable-dev-shm-usage` unconditionally, so both paths are covered.

**Mounting NAS storage** — bind-mount from the host rather than mounting inside
an unprivileged container:

```bash
pct set <ctid> -mp0 /mnt/pve/nas/manga,mp=/data/manga
```

For CIFS/SMB, mount on the host and bind-mount in; unprivileged containers
cannot mount CIFS themselves. Check **Settings → Browser session → Output
writable** in the UI if writes fail — that is almost always a UID mapping
problem on the mount, not the app.

**Firewall** — allow TCP 8080 from your LAN. Do not expose this to the internet;
there is no authentication. If you need remote access, put it behind your
existing reverse proxy or VPN.

## Usage

1. **Add** — paste the series URL and press Fetch. The first request can take up
   to a minute while the browser clears the bot check; later requests reuse the
   session and are fast.
2. Select **all**, a **range**, **not downloaded** (for catching up), or tick
   chapters individually. Press Download.
3. **Queue** — live per-chapter progress. Pause, resume, cancel, or retry the
   failed ones.
4. **Library** — what you have, how many chapters, disk usage.

Output layout, which Komga and Kavita both pick up automatically:

```
/data/manga/
└── Example Series/
    ├── Example Series - c001.cbz
    ├── Example Series - c002.cbz
    └── Example Series - c010.5.cbz
```

## Cloudflare: what is automatic and what is not

The app escalates on its own, cheapest first, and each step is configurable:

| Step | Setting | What it does |
| --- | --- | --- |
| Patched driver | `stealth: true` | Uses `patchright`, a Playwright build with the CDP automation leaks removed. Stock Playwright is detectable through the protocol, not the DOM, so patching `navigator` properties does not help. |
| Real browser | `browser_channel: auto` | Drives installed Chrome or Edge instead of Playwright's bundled Chromium, which is an unsigned developer build with a distinct fingerprint. |
| Wait it out | `challenge_timeout` | The plain JS challenge clears by itself. |
| Click Turnstile | `challenge_click: true` | Locates the widget by its iframe bounding box and clicks with real mouse movement — the checkbox sits in a closed shadow root inside a cross-origin frame, where no selector reaches it. |
| Go headful | `headless: auto` | Relaunches under a virtual display (Xvfb) and retries. Headless takes different rendering and input paths, and those are readable from JavaScript. |
| Retry clean | `challenge_attempts: 3` | Clears the host's cookies between attempts, so each retry is a fresh challenge rather than a replay of the failed one. |

**Honest limitation.** The plain JS challenge clears automatically. **Interactive
Turnstile does not.** This was measured, not assumed — against two neutral
Cloudflare test sites, with no proxy in the path:

| Configuration | Result |
| --- | --- |
| patchright + bundled Chromium, headless | fails |
| patchright + Chromium 149 (current), headless | fails |
| patchright + real Edge, headless | fails |
| patchright + real Edge, **headful** | fails |

Turnstile validates that input events originate from the OS, and events
synthesised over the automation protocol do not. No amount of browser realism
above that layer changes it. Anything claiming otherwise is either paying a
solving service or about to break.

### Attach to your own browser (recommended when Turnstile appears)

Rather than trying to look human to the challenge, use the browser in which a
human already satisfied it. Nothing has to win a detection arms race.

Start your browser with remote debugging, clear the check by hand once, and
leave the window open:

```powershell
# Windows - close other Chrome windows first, or the flag is ignored
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\cdp-profile"
```

```bash
# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/cdp
```

Then set it — in **Settings → Attach to my browser**, or in the config:

```yaml
browser_cdp: http://127.0.0.1:9222
```

The app now drives that browser: its cookies, its exit IP, and its TLS
fingerprint. `headless`, `browser_channel` and `virtual_display` no longer
apply, and the app never closes the window — it is yours, with your tabs in it.

This also fixes the fingerprint problem described below. When a plain HTTP
request is rejected, the image is refetched through the browser's own
connection automatically, so downloads complete where a replayed cookie fails.

The trade-off is that a machine must be running that browser. For an LXC,
either attach to a browser on your desktop over the LAN
(`--remote-debugging-address=0.0.0.0`, LAN only — the debugging port is
unauthenticated and grants full control of the browser), or keep a headful
Chrome inside the container under Xvfb.

### The escape hatch

**Settings → Browser session:**

1. Open the site in your own browser and let it through the check.
2. DevTools → Application → Cookies → copy `cf_clearance`.
3. DevTools → Console → `navigator.userAgent` → copy it.
4. Paste both into Settings and press Install session.

The cookie is bound to **the IP and the User-Agent** that solved it, so this
only works if the container shares your public IP. That binding is also why the
browser runs inside the app rather than as a separate service.

On some sites clearance is additionally bound to the **TLS fingerprint** of the
client that earned it. Where that is enforced, a cookie replayed from Python
still gets a 403 no matter how correct the cookie and UA are, because the
handshake does not look like a browser's. Verify with `/api/connectivity`
before assuming the cookie was pasted wrong.

## When the site is unreachable (network-level blocking)

Distinct from a bot check, and far more common than people expect: many ISPs
block sites by reading the hostname out of the plaintext TLS ClientHello and
resetting the connection. No HTTP response is ever produced, so no amount of
browser realism helps.

Diagnose it — this reports *how* the connection failed, not just that it did:

```bash
curl -s -X POST localhost:8080/api/connectivity \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.net/manga/series/"}'
```

| `kind` | Meaning |
| --- | --- |
| `ok` | Reachable, no interference |
| `challenge` | Reachable; a bot check is in the way. Normal — the browser handles it. |
| `connection_reset` | Killed before any HTTP response. Network-level filtering. Use a proxy. |
| `connect_error` | Could not connect at all. Check DNS and routing. |
| `proxy_error` | Your proxy refused or is unreachable. |

To confirm it is hostname-based filtering rather than the site, compare a TLS
handshake to the *same IP* under two different hostnames — if only the target
name resets, the network is reading the ClientHello.

### Option 1: the built-in bypass (no external service)

Filters of this kind are *passive* — they inspect packets in flight rather than
proxying them, and most never reassemble a TCP stream. Splitting the ClientHello
across two segments therefore leaves them nothing to match:

```yaml
desync_enabled: true
```

This starts a local SOCKS5 proxy that applies the split and routes both the
browser and the downloader through it. Nothing else to install, no bandwidth
limit, full speed.

What matters is *where* the split falls. Measured against a live filter:

| Split point | Result |
| --- | --- |
| No split (control) | reset |
| First 1 byte | **connects** |
| First 5 bytes (record header) | **connects** |
| Inside the hostname | reset |
| Just before the hostname | reset |

Counterintuitively, splitting *inside* the hostname still fails. The filter
parses a TLS record header before deciding whether to track a flow, so the
winning move is a first segment too small to parse — hence the default
`desync_split: 1`.

### Option 2: an external proxy

If the filtering is more capable than simple packet inspection, route out of the
network entirely. This also uses the `proxy` setting, which covers the browser
and downloader together (they must share an exit IP, or the clearance cookie is
void):

```yaml
proxy: socks5://127.0.0.1:1080
```

The cheapest option needing no subscription is an SSH tunnel to any machine
outside the filtered network — a free-tier cloud VM works:

```bash
ssh -D 1080 -N you@your-vps
```

With SOCKS5 the hostname is resolved at the proxy, so neither the DNS lookup nor
the TLS handshake is visible to the filtering.

Verify either option with `/api/connectivity` — it should flip from
`connection_reset` to `ok` or `challenge`.

### Borrowing a cookie from your own browser

Cloudflare's interactive Turnstile is not reliably solvable by automated
browsers, and this project makes no attempt to win that arms race. When you hit
one, solve it yourself once:

1. Point your own browser at the built-in bypass — `socks5://127.0.0.1:8081`
   (Firefox: Settings → Network Settings → Manual proxy, SOCKS v5).
2. Load the site and clear the check by hand.
3. Copy `cf_clearance` and `navigator.userAgent` from DevTools.
4. Paste both into **Settings → Browser session**.

Because the bypass is local, traffic still leaves via your own IP, so the cookie
stays valid for the app. Clearance typically lasts hours to days; downloads run
unattended in between.

## Configuration

Copy `config.example.yaml` to your config directory and edit, or use `MD_`
environment variables (`MD_IMAGE_CONCURRENCY=8`), which take precedence. The
common knobs are editable live in the Settings view.

| Setting | Default | Notes |
| --- | --- | --- |
| `browser_cdp` | unset | Attach to a browser you already cleared by hand |
| `headless` | `auto` | `auto` escalates to headful on a stuck challenge |
| `stealth` | `true` | Prefer the patched `patchright` driver |
| `browser_channel` | `auto` | Drive real Chrome/Edge when installed |
| `challenge_attempts` | `3` | Solve attempts, cookies cleared between each |
| `desync_enabled` | `false` | Built-in bypass for hostname-based filtering |
| `proxy` | unset | Route browser + downloader through a proxy |
| `output_dir` | `/data/manga` | Where CBZ files land |
| `chapter_concurrency` | `2` | Chapters downloaded in parallel |
| `image_concurrency` | `6` | Images in parallel per chapter |
| `requests_per_second` | `4.0` | Per-host cap |
| `prefer_original_quality` | `true` | Strip CDN downscaling |
| `language` | `ar` | ComicInfo `LanguageISO` |
| `right_to_left` | `true` | Correct for manga; false for Western comics |

Defaults are deliberately modest. Getting the IP banned costs far more time than
the extra throughput saves.

## Development

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
playwright install chromium

pytest                                           # 72 tests, fully offline
uvicorn app.main:app --reload --port 8080
```

The test suite needs no network: adapter tests replay saved Madara markup, and
the end-to-end queue test runs the real pipeline against a local HTTP server.

### Layout

| Path | Role |
| --- | --- |
| `app/session.py` | Chromium, Cloudflare solving, cookie harvesting |
| `app/fetcher.py` | HTTP pool, retries, backoff, quality upgrading |
| `app/adapters/madara.py` | Madara chapter/page extraction |
| `app/adapters/generic.py` | Heuristic fallback for unknown sites |
| `app/packager.py` | CBZ writing, ComicInfo, atomic replace |
| `app/queue.py` | Worker pool, resume logic, progress events |
| `web/` | UI — three static files, no build step |

### Adding a site adapter

Subclass `Adapter` in `app/adapters/`, implement `matches`, `fetch_series`,
`fetch_chapters`, `fetch_pages`, and register it in `registry.ADAPTERS`.
Prefer fingerprinting the DOM in `matches()` over matching the hostname.

Use `first_attr(node, "data-src", "src")` for image URLs rather than reading
attributes directly — it strips the whitespace padding these themes emit and
picks the widest `srcset` entry. Forgetting that is the most common reason
scrapers of these sites silently break.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| A browser window appears and stays open | Expected. The app keeps one window open on purpose — closing every page would leave the browser with no windows, and it would quit. The window says so. It is also where a bot check appears for you to complete. |
| `Target page, context or browser has been closed` | The browser died (closed, crashed, auto-updated). The app relaunches it on the next request; you should see "The browser went away" then "Launching Chromium" in the log. If you are using `browser_cdp`, it will *not* relaunch by design — reopen your own browser instead. |
| Preview times out | Challenge not clearing. Check `/api/health`; use the manual cookie fallback. |
| Chromium won't start | Missing `/dev/shm` size or nesting. Verify `shm_size: 1gb` (Docker) or use the native path. |
| Everything 403s mid-run | Clearance expired. The queue re-solves automatically; repeated failures mean the IP is blocked. |
| Files don't appear | Mount permissions. Check **Output writable** in Settings. |
| Pages out of order | Open an issue with the chapter URL — page ordering comes from DOM order. |
| Wrong reading direction | Set `right_to_left` and re-download, or fix `ComicInfo.xml` in place. |

Logs: `docker compose logs -f` or `journalctl -u manga-downloader -f`.

## Legal

This is a general-purpose downloader, in the same category as gallery-dl or
HakuNeko. It ships with no site list and no content.

Aggregator sites are generally not authorised to distribute the works they host.
Downloading from them may infringe copyright where you live, regardless of the
tool used. You are responsible for what you point this at. Support the official
releases where they exist.
