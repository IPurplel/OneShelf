# OneShelf

Download manga, comics, books, and web novels on your own computer. OneShelf
runs locally on Windows, macOS, or Linux, with a browser interface for finding
titles, choosing chapters, and managing your downloads. Your library stays on
your disk.

## Quick start — one command to set up and run

### 1. Get Python and OneShelf

Install **Python 3.12** from [python.org](https://www.python.org/downloads/)
or your operating system's package manager. The launcher requires Python 3.11
or newer; Python 3.12 is the version used for the setup checks.

Download this repository with **Code → Download ZIP**, then extract it to a
writable folder. If you use Git, you can clone it instead:

```bash
git clone https://github.com/IPurplel/OneShelf.git
```

This repository is private, so downloading or cloning requires access through
your GitHub account.

### 2. Run one command

Open a terminal **inside the extracted or cloned OneShelf folder**, where
`run.py` is located. Use the command for your operating system:

| Windows — PowerShell or Command Prompt | macOS — Terminal | Linux — Terminal |
| --- | --- | --- |
| `py -3.12 run.py` | `python3.12 run.py` | `python3.12 run.py` |

If your Python 3.12 installation is called `python` or `python3`, use that name
instead. For example, `python3 run.py`. Check its version with `python3 --version`
(or `python --version`).

The same command handles first-time setup and every later launch. On the first
run it creates an isolated Python environment, installs the application's
packages and Chromium, writes local settings if none exist, and starts OneShelf.
Allow a few minutes and an internet connection for this initial setup. Later
launches reuse the installed packages; changes to `requirements.txt` trigger
setup again automatically.

On **Ubuntu/Debian**, Python's `venv` support must be installed (usually the
matching `python3-venv` or `python3.12-venv` package). The launcher also installs
Chromium's system libraries and may ask for your **sudo password** on first
setup. On other Linux distributions, install the required browser system
libraries through your package manager first; the launcher does not manage
those distributions' system packages. See
[Playwright's browser dependency guide](https://playwright.dev/python/docs/browsers#install-system-dependencies).

### 3. Open OneShelf

Open **[http://127.0.0.1:8080](http://127.0.0.1:8080)** in your browser.
Keep the terminal open while using the app. Press **Ctrl+C** in that terminal
to stop it; run the same command to start it again.

Fresh desktop installs listen only on your computer. If you already have a
`config.yaml`, the launcher keeps it unchanged, including its address, port,
and download location. Use the address shown in the terminal in that case.

### Where your files go

By default, the launcher creates these alongside `run.py`:

| Location | Contents |
| --- | --- |
| `downloads/` | Your downloaded manga, books, and novels |
| `.state/` | Queue database and the app's browser profile |
| `config.yaml` | Your saved settings |
| `.venv-oneshelf/` | The app's private Python environment |

Change the download folder in **Settings**. Your choice survives restarts.
You do not need to activate a virtual environment or install Docker to use
the desktop launcher.

## Supported sources

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
┌─ OneShelf ─────────────────────────────── ⚙ ─┐
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

- **Web GUI** — open it in your usual browser, with warm light and dark themes.
- **Bulk or selective** — all chapters, a numeric range, or individual ticks.
- **Lossless CBZ** — images stored byte-for-byte, no re-encoding, with
  `ComicInfo.xml` for Komga, Kavita, YACReader and Mihon/Tachiyomi.
- **Best quality** — strips CDN resize parameters and unwraps image proxies
  (weserv, Jetpack Photon, statically, Next.js) to reach the originals.
- **Browser-assisted downloads** — uses installed Chrome/Edge when available,
  with bundled Chromium as a fallback. If a site asks for a human check,
  complete it in the browser window OneShelf opens.
- **Resumable** — kill it mid-run; it skips finished chapters and cleans up
  partial files on the next start.
- **Polite** — per-host rate limiting, jitter, and exponential backoff.

## Usage

1. **Add** — paste the series URL and press Fetch. The first request can take up
   to a minute while the browser clears the bot check; later requests reuse the
   session and are fast.
2. Select **all**, a **range**, **not downloaded** (for catching up), or tick
   chapters individually. Press Download.
3. **Queue** — live per-chapter progress. Pause, resume, cancel, or retry the
   failed ones.
4. **Library** — what you have, how many chapters, disk usage.

Default desktop output layout, also suitable for Komga and Kavita:

```
downloads/
└── Example Series/
    ├── Example Series - c001.cbz
    ├── Example Series - c002.cbz
    └── Example Series - c010.5.cbz
```

## Cloudflare: what is automatic and what is not

The desktop launcher uses a visible browser so you can complete checks directly.
Leave that window open while downloads run. For headless/server setups, the
app can escalate through the following steps:

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

### Attach to your own browser (if a check keeps repeating)

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

The desktop launcher creates `config.yaml` in the OneShelf folder. Common
settings are editable live in **Settings** and are saved to that file. For
advanced options, consult [config.example.yaml](config.example.yaml) and add
only the settings you need; its storage paths are server defaults.

`MD_` environment variables take precedence over the file. Set `MD_CONFIG_FILE`
to use a different configuration file. The launcher preserves both existing
configuration files and environment overrides.

| Setting | Default | Notes |
| --- | --- | --- |
| `browser_cdp` | unset | Attach to a browser you already cleared by hand |
| `headless` | `false` on desktop | A visible browser lets you complete checks; server default is `auto` |
| `stealth` | `true` | Prefer the patched `patchright` driver |
| `browser_channel` | `auto` | Drive real Chrome/Edge when installed |
| `challenge_attempts` | `3` | Solve attempts, cookies cleared between each |
| `desync_enabled` | `false` | Built-in bypass for hostname-based filtering |
| `proxy` | unset | Route browser + downloader through a proxy |
| `output_dir` | `downloads/` on desktop | Where your files land; server default is `/data/manga` |
| `chapter_concurrency` | `2` | Chapters downloaded in parallel |
| `image_concurrency` | `6` | Images in parallel per chapter |
| `requests_per_second` | `4.0` | Per-host cap |
| `prefer_original_quality` | `true` | Strip CDN downscaling |
| `language` | `ar` | ComicInfo `LanguageISO` |
| `right_to_left` | `true` | Correct for manga; false for Western comics |

Defaults are deliberately modest. Getting the IP banned costs far more time than
the extra throughput saves.

## Development

Run the desktop launcher once, then stop it. Use its environment to install
development dependencies and run the offline tests:

| Platform | Install test tools | Run tests |
| --- | --- | --- |
| Windows | `.venv-oneshelf\Scripts\python.exe -m pip install -r requirements-dev.txt` | `.venv-oneshelf\Scripts\python.exe -m pytest` |
| macOS | `.venv-oneshelf/bin/python -m pip install -r requirements-dev.txt` | `.venv-oneshelf/bin/python -m pytest` |
| Linux | `.venv-oneshelf/bin/python -m pip install -r requirements-dev.txt` | `.venv-oneshelf/bin/python -m pytest` |

The test suite needs no network: adapter tests replay saved Madara markup, and
the end-to-end queue test runs the real pipeline against a local HTTP server.

### Layout

| Path | Role |
| --- | --- |
| `run.py` | Desktop setup and startup on Windows, macOS, and Linux |
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
| `py`, `python3.12`, or `python3` is not found | Install Python 3.12 and reopen your terminal. Use the command name supplied by your Python installation. |
| `can't open file ... run.py` | Open a terminal in the extracted OneShelf folder, or pass the full quoted path to `run.py`. |
| Setup fails or a download is interrupted | Fix the network or permissions error shown in the terminal, then run the same startup command. Incomplete package/browser setup is retried. |
| `ensurepip` or `venv` is missing on Linux | Install the matching `python3-venv` / `python3.12-venv` package using your distribution's package manager, then rerun. |
| Port 8080 is already in use | Stop the other OneShelf instance, or set a different `port` in `config.yaml` and reopen that address. |
| A browser window appears and stays open | Expected. The app keeps one window open on purpose — closing every page would leave the browser with no windows, and it would quit. The window says so. It is also where a bot check appears for you to complete. |
| `Target page, context or browser has been closed` | The browser died (closed, crashed, auto-updated). The app relaunches it on the next request; you should see "The browser went away" then "Launching Chromium" in the log. If you are using `browser_cdp`, it will *not* relaunch by design — reopen your own browser instead. |
| Preview times out | Challenge not clearing. Check `/api/health`; use the manual cookie fallback. |
| Chromium won't start | On Linux, check the terminal for missing system libraries. For Docker, also verify `shm_size: 1gb`. |
| Everything 403s mid-run | Clearance expired. The queue re-solves automatically; repeated failures mean the IP is blocked. |
| Files don't appear | Check the download folder in Settings and whether your user can write to it. Existing configuration may point somewhere other than `downloads/`. |
| Pages out of order | Open an issue with the chapter URL — page ordering comes from DOM order. |
| Wrong reading direction | Set `right_to_left` and re-download, or fix `ComicInfo.xml` in place. |

Desktop logs appear in the terminal where you launched OneShelf.

## Updating

Stop OneShelf with **Ctrl+C**. If you cloned the repository, run `git pull`
inside its folder, then use your usual startup command. Changed Python
requirements are installed automatically. Your config, downloads, and browser
state are kept.

If you downloaded a ZIP, replace the source files with the new version while
keeping `config.yaml`, `downloads/`, and `.state/`. Keep the same folder location
so the saved paths remain valid.

## Advanced: Docker, servers, and Proxmox/LXC

For an always-on server or NAS, use the deployment files in `deploy/`.
These are optional and are not needed for the desktop workflow above.

**Docker:** edit the storage mapping in
[deploy/docker-compose.yml](deploy/docker-compose.yml) for your server, then run:

```bash
docker compose -f deploy/docker-compose.yml up -d --build
```

**Debian/Ubuntu systemd:** from the cloned repository, run
`sudo ./deploy/install.sh`. This installs a system service; do not use it as
the desktop launcher. The service and image retain their existing
`manga-downloader` names.

See the [Proxmox/LXC deployment guide](deploy/DEPLOY-LXC.md) for container
nesting, storage mounts, service configuration, and troubleshooting. Server
logs are available with `docker compose -f deploy/docker-compose.yml logs -f`
or `journalctl -u manga-downloader -f`.

Server deployments can listen on the LAN. OneShelf has no authentication, so
keep access to a trusted network or VPN rather than exposing its port publicly.

## Legal

This is a general-purpose downloader, in the same category as gallery-dl or
HakuNeko. It ships with no site list and no content.

Aggregator sites are generally not authorised to distribute the works they host.
Downloading from them may infringe copyright where you live, regardless of the
tool used. You are responsible for what you point this at. Support the official
releases where they exist.
