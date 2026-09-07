# 📚 OneShelf

> Your manga, comics, books, and web novels in one place.

Search or paste a link, choose chapters, and download them from your browser.
OneShelf runs on your own computer or server with Docker.

## ✨ Features

| Feature | What you can do |
| --- | --- |
| 🔎 **Search or paste a link** | Find titles across supported sources or open a series directly. |
| ☑️ **Choose your chapters** | Download everything, a range, or just the chapters you are missing. |
| 📥 **Manage downloads** | Follow live progress, pause, resume, and retry failed downloads. |
| 📖 **Keep your library** | Save comics as CBZ, web novels as EPUB, and supported books in their original format. |
| 🌍 **Arabic and RTL** | Preserve Arabic text and right-to-left reading information. |
| 📱 **Use any device** | Open the interface from your phone or another computer on the same network. |

## 🚀 Quick Start

**You need:** Docker with Compose v2 running, a Bash terminal, and internet access.
On Windows, use WSL2 with Docker Desktop's WSL integration enabled.
The container targets Linux amd64; other architectures need Docker emulation.

1. Click **Code → Download ZIP** on this page and extract the folder.
2. Open a terminal inside the extracted OneShelf folder.
3. Run this command:

```bash
bash startup.sh
```

The first build can take several minutes. The script checks that OneShelf is ready
and prints its addresses. No Python installation or manual configuration is needed.

Open **[http://localhost:8080](http://localhost:8080)**. You can close the terminal
after startup; OneShelf keeps running in the background.

## 🌐 Open it on your phone or another computer

Connect to the same network and open the **LAN address printed at startup**,
for example `http://192.168.1.42:8080`. Keep the computer running OneShelf turned on.

If needed, find the host computer's Wi-Fi or Ethernet IP in its network settings.
OneShelf has no login: use a trusted network and do not expose it to the internet.

## 📖 Your first download

1. **Find a title** — search or paste a series URL.
2. **Choose chapters** — select everything, a range, or individual chapters, then press **Download**.
3. **Follow progress** — open **Queue** to pause, resume, or retry.
4. **Save a copy** — open **Library → Download .zip** to download a series to the device you are using.

Supported sources include MangaDex, Webtoons, Royal Road, Scribble Hub, AO3,
Gutenberg, and sites using the Madara or MangaThemesia themes. Support varies by
source; some sites may ask for a browser session or block automated downloads.

## 💾 Your files and settings

Downloads and settings stay on the host computer and survive restarts and updates.
Use **Settings** to adjust browser and download options. Keep the output folder
at `/data/manga`, and do not delete OneShelf's Docker storage unless you want to erase it.

## 🔄 Updates and maintenance

To update, download the latest source files or pull changes with Git, then run
**`bash startup.sh`** again. Your saved data stays in place.

| Task | Command |
| --- | --- |
| Stop OneShelf | `docker stop oneshelf` |
| Start it again | `bash startup.sh` |
| View logs | `docker logs -f oneshelf` |

## ❓ Need help?

Check the [troubleshooting guide](docs/troubleshooting.md) for startup errors,
LAN connections, browser checks, backups, and moving an older installation.

## 📄 License

[MIT](LICENSE). Download only content you have permission to save, and support official releases.
