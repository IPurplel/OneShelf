# OneShelf

Download manga, comics, books, and web novels from your browser.

## Start

You need **Docker with Compose v2** running and a **Bash terminal**.
On Windows, use WSL2 with Docker Desktop's WSL integration enabled.

1. Click **Code → Download ZIP** on this page and extract the folder.
2. Open a terminal in the extracted OneShelf folder.
3. Run:

```bash
bash startup.sh
```

The first startup needs internet and can take several minutes.
When ready, open **[http://localhost:8080](http://localhost:8080)**. You can close the terminal.

## Download

1. Search for a title or paste a series URL.
2. Choose chapters and press **Download**. Follow progress in **Queue**.
3. Open **Library → Download .zip** to save files to your device.

## Use your phone or another computer

Connect to the same network and open the **LAN address printed at startup**.
For example: `http://192.168.1.42:8080`.

Your downloads and settings stay saved on the computer running OneShelf after restarts.
OneShelf has no login—keep it on a trusted network and do not expose it to the internet.

[Need help?](docs/troubleshooting.md) · [MIT License](LICENSE)
