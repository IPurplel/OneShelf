# 📚 OneShelf

> Self-hosted manga, comic, book, and web novel downloader. Find a title, choose your chapters, build your library.

Supports **MangaDex**, **Webtoons**, **Royal Road**, **Gutenberg**, and more — runs on your own machine with Docker.

<sub>Source availability varies. Some sites require a browser session or a human check — see [Browser Checks](#-browser-checks).</sub>

---

## ✨ Features

| | |
|---|---|
| 🔎 **Search Across Sources** | Search by title and choose which sources to include · or paste a series URL directly |
| 📚 **Manga & Comics** | One CBZ per chapter · original image bytes preserved without re-encoding · chapter numbers keep files in reading order |
| 📖 **Books & Web Novels** | Web novel chapters packaged as EPUB · supported book sources provide their original EPUB, PDF, or other available files |
| ☑️ **Pick Your Chapters** | Download all chapters, a numeric range, individual selections, or only chapters you have not downloaded |
| 🏷️ **Reader Metadata** | CBZ archives include `ComicInfo.xml` with available series and chapter information for compatible comic readers |
| 🖼️ **Original Quality** | Tries to retrieve original images by removing supported resize parameters and unwrapping image proxies |
| 📥 **Live Queue** | Follow download progress · pause, resume, cancel, and retry jobs from the browser |
| 🔁 **Resumable Downloads** | Completed chapters are kept · interrupted jobs can resume without downloading finished chapters again |
| 🗂️ **Library Management** | Browse and filter saved series · sort by title, date, size, or chapter count · download a series as ZIP |
| 🌍 **Arabic & RTL** | Unicode filenames and Arabic text · right-to-left reading metadata for supported sources |
| 🌈 **Themes** | Switch between light, dark, and your system's appearance |
| 🍪 **Browser Sessions** | Keep browser profiles between restarts · install session cookies or attach an existing browser when a source needs extra help |
| 📱 **LAN Access** | Use the web interface from your phone, tablet, or another computer on the same network |
| 💾 **Persistent Storage** | Downloads, settings, queue data, and browser sessions stay in Docker volumes across restarts and updates |

---

## 🚀 Quick Start

### Requirements

- **Docker with Docker Compose v2**, installed and running.
- A **Bash terminal** and an internet connection.
- On Windows, use **WSL2** with Docker Desktop's WSL integration enabled.

The container targets **Linux amd64**. Other architectures require Docker emulation; native ARM support has not been validated.

### 1. Get OneShelf

```bash
git clone https://github.com/IPurplel/OneShelf.git
cd OneShelf
```

### 2. Start

```bash
bash startup.sh
```

The script builds OneShelf, starts it in the background, and checks that it is ready. The first build can take several minutes; later runs reuse Docker's build cache. No Python installation or configuration file setup is needed.

Open **[http://localhost:8080](http://localhost:8080)** 🎉

You can close the terminal after startup. Run the same command whenever you need to start OneShelf again.

---

## 🌐 Access From Other Devices

Connect your phone or another computer to the **same network**, then open the LAN address printed by the startup script:

```text
http://192.168.1.42:8080
```

Use your host computer's address, not the example above. If several addresses appear, choose its Wi-Fi or Ethernet IP. Keep the host computer running while you use OneShelf.

**OneShelf has no authentication.** Keep it on a trusted LAN and do not forward port 8080 to the public internet. If a device cannot connect, check the host's private-network firewall and whether your Wi-Fi isolates devices.

---

## 📥 Downloading

1. **Find a title** — search across sources or paste a series URL.
2. **Choose chapters** — select all, a range, or individual chapters, then press **Download**.
3. **Follow the queue** — watch progress, pause, resume, or retry failed jobs.
4. **Open your library** — browse saved series and use **Download .zip** to save a copy to the device you are using.

Files are stored on the computer running OneShelf. Opening the interface on a phone does not move the library to that phone; downloading a ZIP gives it a separate copy.

---

## ⚙️ Configuration

The defaults work out of the box. Open **Settings** in the web interface to change common options; saved changes are stored in `/config/config.yaml`.

| Setting | Default | Description |
|---|---|---|
| `language` | `en` | Language metadata and the translation requested from MangaDex; use `ar` for Arabic |
| `chapter_concurrency` | `2` | Chapters processed in parallel |
| `image_concurrency` | `6` | Images fetched in parallel within a chapter |
| `requests_per_second` | `4` | Request rate limit per source host |
| `max_retries` | `3` | Retry limit for failed fetches |
| `prefer_original_quality` | `true` | Try to retrieve original images instead of resized copies |
| `proxy` | Unset | Optional proxy for browser and download requests |
| `browser_cdp` | Unset | Attach to an existing browser's debugging endpoint |

The deployment fixes the web port at **8080** and the download folder at **`/data/manga`**. Keep that output path so files stay in persistent storage.

See the [configuration reference](config.example.yaml) for advanced options and the [troubleshooting guide](docs/troubleshooting.md) for browser and network setup.

---

## 🌍 Supported Sources

Every source below has been verified by downloading a real file from it and
opening that file — not by checking that search returns results. The evidence
for each, with the file, its size and its page or chapter count, is in
[SOURCES.md](SOURCES.md).

| Source | Content | Output |
|---|---|---|
| MangaDex | Manga translations | CBZ |
| 3asq · MangaRead · Manhua Plus · ArabToons | Manga on the Madara platform | CBZ |
| AzoraMoon / AzoraFly | Manga and manhwa | CBZ |
| Comix.to | Manga, manhwa and manhua | CBZ |
| Webtoons | Free episodes | CBZ |
| Arcomixverse (Blogger / Blogspot) | Scanned comic issues | CBZ |
| Royal Road | Web novels | EPUB per chapter |
| Sunovels · KolNovel · Cenele · Rewayat Club · RiwayatArab | Arabic web novels | EPUB per chapter |
| WuxiaBox | English web novels | EPUB per chapter |
| Archive of Our Own | Public works | Site-provided EPUB, MOBI, PDF, AZW3 |
| Project Gutenberg | Public-domain books | Site-provided EPUB, AZW3 or PDF |
| Arabic Collections Online (NYU) | Open-access Arabic books | PDF |
| Noor Book | Arabic books, bound from the free reader | PDF |
| Kitaboka | Arabic books | Site-provided PDF |
| 8ghrb · Planet eBook · Better Gutenberg | Books | Site-provided files |

Adapters recognize a site by the shape of its pages rather than its hostname,
so a site sharing a platform with one of the above may well work when you paste
its URL — but only the sources listed here have actually been verified, and a
site can change its markup at any time.

**Not supported, and why.** Sources that need an account, a subscription or a
purchase to reach readable content are excluded on principle rather than worked
around. A few others are believed correct but could not be proven from the
machine this was developed on — an ISP-level filter or a bot check this
container cannot clear — and those are listed in
[SOURCES.md](SOURCES.md#not-verified) rather than advertised here.

---

## 🍪 Browser Checks

The Docker image includes **Chromium**, **Chrome**, and a virtual display. OneShelf can handle some browser checks automatically, but interactive checks may still require a person.

Use **Settings → Browser session** to install cookies from a browser where you completed a check, or **Attach to my browser** to reuse an existing browser session. Copied cookies may expire or depend on the original public IP and browser, so they do not work on every source.

See [browser-session instructions](docs/troubleshooting.md#browser-checks-and-sessions) for details. The browser runs on the OneShelf host; the virtual display is not an interactive desktop inside the web interface.

---

## 📁 File Naming

Each series gets its own folder. Comic chapters use the series title and a padded chapter number:

```text
Example Series/
  Example Series - c001.cbz
  Example Series - c002.cbz
  Example Series - c010.5.cbz
```

Web novels use the same pattern with `.epub`, one file per chapter. Direct book downloads use the source filename or a title-based filename, depending on the adapter.

---

## 🐳 Docker Details

OneShelf runs in **one container**, named `oneshelf`, serving the web interface and API on port **8080**. The startup script builds the code in your downloaded repository.

Data is stored in named Docker volumes:

| Volume | Path inside OneShelf | Contents |
|---|---|---|
| `oneshelf_downloads` | `/data/manga` | Downloaded books and chapters |
| `oneshelf_config` | `/config` | Settings, queue database, and browser profiles |

These volumes survive container recreation. Do not delete them or reset Docker's storage unless you intend to erase the data. See [backups and storage](docs/troubleshooting.md#storage-permissions-and-backups) for more information.

### Updates and maintenance

Get the latest repository changes, then run **`bash startup.sh`** again to rebuild and start the updated version. Existing Docker volume data stays in place.

| Task | Command |
|---|---|
| Update the cloned source | `git pull` |
| Start or rebuild OneShelf | `bash startup.sh` |
| Stop OneShelf | `docker stop oneshelf` |
| Follow logs | `docker logs -f oneshelf` |

Upgrading from an older deployment? Read [Existing installation](docs/troubleshooting.md#existing-installation) first. Old host folders are preserved but are not automatically imported into the new volumes.

---

## 🔌 API

The interface uses the same API available to scripts and integrations. Open **[API documentation](http://localhost:8080/docs)** on the host while OneShelf is running for request and response details.

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Application status and download-folder write access |
| `GET` | `/api/sources` | Available source information |
| `GET` | `/api/search` | Search for titles |
| `POST` | `/api/preview` | Read series details and its chapter list |
| `POST` | `/api/download` | Queue a series and selected chapters |
| `GET` | `/api/jobs` | List download jobs |
| `GET` | `/api/library` | List saved series |
| `GET` | `/api/library/archive` | Download a series as ZIP |
| `GET` / `PUT` | `/api/settings` | Read or update settings |

Live progress is available over WebSocket at `/ws`.

---

## 🛠️ Development

See the [development guide](docs/development.md) for the code layout, test commands, and adding source adapters. The frontend is served directly by the application and needs no build step.

---

## 📦 Built With

- **FastAPI & Uvicorn** — web interface and API server
- **Playwright & Patchright** — browser-assisted page retrieval
- **HTTPX** — HTTP downloads
- **SQLite** — persistent queue and library records
- **Selectolax & Pillow** — HTML parsing and image handling

---

## 📄 License

[MIT](LICENSE). Download only content you have permission to save, and support official releases.
