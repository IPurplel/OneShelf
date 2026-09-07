"""Application settings.

Layered configuration, lowest precedence first:

1. Defaults declared on ``Settings``
2. ``config.yaml`` (path from ``MD_CONFIG_FILE``, default ``./config.yaml``)
3. Environment variables prefixed ``MD_`` (e.g. ``MD_OUTPUT_DIR``)

A handful of settings are also editable at runtime from the Settings view in the
web UI; those are persisted back to the YAML file so they survive a restart.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml
from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

CONFIG_FILE = Path(os.environ.get("MD_CONFIG_FILE", "config.yaml"))

# Settings the UI is allowed to change. Everything else is deploy-time only,
# so a compromised browser session cannot repoint the data directory.
RUNTIME_EDITABLE = {
    "output_dir",
    "chapter_concurrency",
    "image_concurrency",
    "requests_per_second",
    "max_retries",
    "prefer_original_quality",
    "language",
    "proxy",
    "desync_enabled",
    "browser_cdp",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MD_",
        extra="ignore",
        validate_assignment=True,
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        """Rank the environment above ``config.yaml``.

        ``load_settings`` hands the YAML over as constructor keyword arguments,
        and pydantic-settings ranks those *highest* by default — the opposite of
        what this file, ``config.example.yaml`` and the README all promise, and
        the opposite of what deployment needs. Every shipped deployment sets
        ``MD_OUTPUT_DIR``/``MD_CONFIG_DIR``/``MD_PORT`` in the environment
        (Dockerfile, docker-compose, the systemd unit) while pointing
        ``MD_CONFIG_FILE`` at a copy of ``config.example.yaml`` — which sets all
        three itself. With the default ordering the YAML silently won, so the
        container wrote to whatever path the file named and ignored the mount
        it was actually given. Env first, YAML behind it.
        """
        return (env_settings, dotenv_settings, init_settings, file_secret_settings)

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8080

    # --- storage ---
    output_dir: Path = Path("/data/manga")
    config_dir: Path = Path("/config")

    # --- browser / Cloudflare ---
    headless: str = "auto"
    """``auto`` (default), ``true`` or ``false``.

    ``auto`` starts headless — cheap, and enough for the non-interactive
    challenge — and escalates to a headful browser under a virtual display if a
    challenge refuses to clear. Headless Chromium takes different code paths for
    rendering and input, and those differences are readable from JavaScript, so
    an interactive Turnstile that stalls headless often passes headful.

    A YAML boolean is accepted and normalised, so an existing ``headless: true``
    keeps meaning what it did.
    """
    stealth: bool = True
    """Prefer the ``patchright`` driver when it is installed.

    Stock Playwright is detectable through the automation protocol itself, not
    through anything the DOM exposes; patchright is a drop-in build with those
    leaks patched. Set false to pin stock Playwright when debugging.
    """
    virtual_display: bool = True
    """Allow starting Xvfb so a headful browser can run in a container."""
    browser_channel: str = "auto"
    """Which browser to drive: ``auto``, ``chrome``, ``msedge`` or ``chromium``.

    ``auto`` prefers a real installed browser and falls back to Playwright's
    bundled Chromium. That bundle is a developer build — unsigned, missing the
    proprietary codecs a shipped browser has — and a challenge can tell.
    """
    challenge_attempts: int = 3
    """Solve attempts before giving up on a host.

    Each retry clears that host's cookies first, so it is a genuinely fresh
    challenge rather than a replay of the one that just failed.
    """
    challenge_click: bool = True
    """Click the Turnstile checkbox when a challenge presents one."""

    assisted_solve: bool = True
    """When automation stalls and a browser window is visible, wait for you.

    Interactive Turnstile cannot be solved by automation — it validates that
    input came from the operating system. Rather than fail, the app shows the
    challenge in a real window and waits: one click from you, and the session
    it earns is used for the whole download. Ignored when nothing is visible,
    since there would be no window to click in.
    """
    assisted_timeout: float = 300.0
    """How long to wait for you, once automation has had its turn."""

    browser_cdp: str | None = None
    """Attach to a browser you are already running, e.g. ``http://127.0.0.1:9222``.

    The reliable answer to an interactive Turnstile. Start your own browser with
    ``--remote-debugging-port=9222``, clear the check by hand once, and the app
    drives that tab instead of launching its own. Nothing has to defeat the bot
    check, because a person already passed it.

    When set, ``headless``, ``browser_channel`` and ``virtual_display`` are
    ignored — the browser is already running and is not ours to configure.
    """

    search_sites: list[str] = [
        # Arabic
        "https://3asq.online",
        "https://manga-starz.net",
        "https://arabtoons.net",
        "https://azoramoon.com",
        # Books — searched alongside comics, and answering an Arabic query
        # better than any of the manga sites do.
        "https://8ghrb.com",
        "https://www.noor-book.com",
        # Kitaboka is a masked alias; use its active Norkitab backend.
        "https://kitaboka.com",
        # arabic-book.net is deliberately absent: it downloads fine by URL, but
        # its search page renders a "latest posts" widget in the same <article>
        # markup as results, so a query it cannot answer comes back looking
        # answered. Paste-by-URL only until that can be told apart.
        "https://www.planetebook.com",
        "https://bettergutenberg.org",
        "https://www.gutenberg.org",
        # Added by the 2026-09-07 source survey. Each was verified reachable
        # from this machine, matched by an adapter, and — the part that is not
        # optional — checked to return *nothing* for a query it cannot answer,
        # which is what keeps a site out of every unrelated search.
        #
        # sunovels.com is deliberately absent even though its adapter works:
        # its /library ignores every search parameter and returns the same
        # twenty-four catalogue cards, so it can never answer a query. It is
        # paste-by-URL only, like arabic-book.net above.
        "https://www.royalroad.com",
        "https://archiveofourown.org",
        "https://www.webtoons.com",
        "https://azorafly.com",
        # Global
        "https://mangadex.org",
        "https://mangaread.org",
        "https://manhuaplus.com",
        "https://rizzfables.com",
    ]
    """Sites the search box queries, in order.

    Every site here was probed from this machine and confirmed to be reachable,
    matched by an adapter, and returning search results with covers. Sites are
    not added on reputation: of twenty candidates, six were unreachable or dead
    domains and seven more served pages no adapter could read.

    Each is searched through its own search page, so results are always current
    and reflect exactly what that site hosts. Add any site the app supports —
    the adapter is chosen by fingerprinting the page, so nothing else needs to
    change. Sites that fail or time out are skipped, never fatal.
    """
    search_timeout: float = 20.0
    """Seconds any single site gets before it is dropped from the results."""

    browser_data_dir: Path | None = None
    """Persistent Chromium profile. Defaults to ``config_dir/browser``.

    Keeping this on disk is what lets a solved Cloudflare clearance survive a
    container restart instead of forcing a fresh challenge every boot.
    """
    challenge_timeout: float = 60.0
    """Seconds to wait for a Cloudflare interstitial to clear."""
    navigation_timeout: float = 45.0
    wait_timeout: float = 10.0
    """Seconds to wait for JS-injected content to appear.

    Deliberately far shorter than ``navigation_timeout``. The wait is
    non-fatal, so spending the navigation budget on a selector that is never
    coming is pure invisible delay — it cost 45 seconds a page before this
    existed. A selector absent after 10s is absent; the adapter's own parse
    error says far more than more waiting would.
    """

    # --- network ---
    desync_enabled: bool = False
    """Route traffic through a built-in proxy that fragments the TLS handshake.

    Defeats networks that block by reading the hostname out of the plaintext
    ClientHello and injecting a reset. Needs no external service. Ignored when
    ``proxy`` is set, since that is an explicit routing choice by the operator.
    """
    desync_split: int = 1
    """Bytes in the first TCP segment. Small is what works: the filter must be
    unable to parse a TLS record header from the opening segment."""
    desync_delay: float = 0.05
    """Seconds between the two segments."""
    desync_browser: bool = False
    """Route the *browser* through the built-in bypass too.

    Off by default, and that default is load-bearing. Modern Chromium encrypts
    the TLS ClientHello (ECH) and resolves over DoH, so it usually walks past
    hostname filtering with no help — while a fragmented handshake is an
    anomaly Cloudflare re-challenges on, producing a verify loop no amount of
    clicking escapes. The plain HTTP downloader has neither protection and does
    need the bypass, so by default the two take different routes.

    Both still leave from your own IP, so clearance stays valid across them.
    Turn this on only if the browser itself cannot reach the site.
    """
    desync_port: int = 8081
    """Port for the built-in bypass proxy. 0 picks a free one at random.

    A fixed port matters: you can point your own browser at this proxy to reach
    a filtered site, solve any bot check there, and paste the resulting cookie
    into Settings. Traffic still leaves via your own IP, so the cookie stays
    valid for the app.
    """

    proxy: str | None = None
    """Route all traffic through a proxy, e.g. ``socks5://127.0.0.1:1080``.

    Applies to the browser and the image downloader alike — they must share an
    exit IP or the harvested clearance cookie is rejected. Needed when the local
    network filters the target host; SOCKS5 also moves DNS resolution and the
    TLS hostname beyond the filtering point.
    """

    # --- download engine ---
    chapter_concurrency: int = 2
    image_concurrency: int = 6
    requests_per_second: float = 4.0
    """Per-host cap. Deliberately modest: getting the IP banned costs far more
    time than the throughput ever saves."""
    max_retries: int = 3
    request_timeout: float = 60.0

    # --- output ---
    prefer_original_quality: bool = True
    """Strip CDN resize parameters and unwrap image proxies to reach originals."""
    language: str = "en"
    """ComicInfo LanguageISO, and the translation MangaDex is asked for.

    English is the default because it is the least surprising for a general
    audience; set `language: ar` for the Arabic sources. Change it in Settings."""
    right_to_left: bool = False
    """Fallback page direction, used only when an adapter does not declare one.

    Adapters that know their own direction win here — see queue.py, where
    `adapter.right_to_left` overrides this whenever it is not None. The Arabic
    sources (vcomics, sunovels) set it themselves, so they stay right-to-left
    regardless of this value."""

    @field_validator("output_dir", "config_dir", mode="after")
    @classmethod
    def _expand(cls, value: Path) -> Path:
        return Path(os.path.expandvars(str(value))).expanduser()

    @field_validator("browser_cdp", mode="before")
    @classmethod
    def _validate_cdp(cls, value):
        """Normalise the CDP endpoint; blank means "not attached"."""
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if not text.startswith(("http://", "https://", "ws://", "wss://")):
            # A bare "127.0.0.1:9222" is the natural thing to type.
            text = f"http://{text}"
        return text.rstrip("/")

    @field_validator("headless", mode="before")
    @classmethod
    def _normalise_headless(cls, value):
        """Accept ``auto``, a YAML boolean, or the usual truthy/falsey strings.

        Environment variables arrive as strings and YAML gives a real bool, so
        both have to land on the same three values.
        """
        if isinstance(value, bool):
            return "true" if value else "false"
        text = str(value).strip().lower()
        if text == "auto":
            return "auto"
        if text in {"1", "true", "yes", "on"}:
            return "true"
        if text in {"0", "false", "no", "off"}:
            return "false"
        raise ValueError(
            f"headless must be 'auto', true or false (got {value!r})"
        )

    @property
    def headless_is_auto(self) -> bool:
        return self.headless == "auto"

    @property
    def start_headless(self) -> bool:
        """Whether the *first* browser launch should be headless."""
        return self.headless != "false"

    @field_validator("proxy", mode="before")
    @classmethod
    def _validate_proxy(cls, value):
        """Normalise and reject malformed proxy URLs at assignment time.

        The UI sends an empty string to mean "no proxy"; treat that as unset
        rather than storing a value that would fail on every request.
        """
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None

        from .proxy import parse_proxy  # local import to avoid a cycle

        parse_proxy(text)  # raises ProxyError (a ValueError) if malformed
        return text

    _runtime_proxy: str | None = PrivateAttr(default=None)
    """Set at startup to the built-in desync proxy's address.

    Deliberately private so it is never written back to config.yaml — it is a
    per-run detail (the port is chosen at bind time), not a stored preference.
    """

    @property
    def effective_proxy(self) -> str | None:
        """The proxy the HTTP downloader uses.

        An explicit ``proxy`` wins: if the operator named a route, honour it
        rather than silently substituting the local bypass.
        """
        return self.proxy or self._runtime_proxy

    @property
    def browser_proxy(self) -> str | None:
        """The proxy the browser uses — not always the same one.

        An explicit ``proxy`` applies to both, because the operator chose it and
        because a split exit IP would void the clearance cookie. The built-in
        bypass is different: it exists to compensate for a plain client's
        missing ECH, and applying it to a browser that does not need it causes
        a Cloudflare verify loop. It stays local either way, so both paths keep
        the same exit IP and clearance carries over.
        """
        if self.proxy:
            return self.proxy
        return self._runtime_proxy if self.desync_browser else None

    @property
    def proxy_config(self):
        """Parsed proxy for the HTTP downloader, or ``None``."""
        from .proxy import parse_proxy

        return parse_proxy(self.effective_proxy)

    @property
    def browser_proxy_config(self):
        """Parsed proxy for the browser, or ``None``."""
        from .proxy import parse_proxy

        return parse_proxy(self.browser_proxy)

    @property
    def browser_profile_dir(self) -> Path:
        return self.browser_data_dir or (self.config_dir / "browser")

    @property
    def db_path(self) -> Path:
        return self.config_dir / "manga.db"

    def ensure_dirs(self) -> None:
        for path in (self.output_dir, self.config_dir, self.browser_profile_dir):
            path.mkdir(parents=True, exist_ok=True)

    def apply_runtime_update(self, values: dict[str, Any]) -> dict[str, Any]:
        """Apply UI-editable settings and persist them to ``config.yaml``."""
        applied: dict[str, Any] = {}
        for key, value in values.items():
            if key not in RUNTIME_EDITABLE:
                continue
            setattr(self, key, value)  # validate_assignment enforces types here
            applied[key] = getattr(self, key)

        if applied:
            with _write_lock:
                stored = _load_yaml(CONFIG_FILE)
                stored.update({k: str(v) if isinstance(v, Path) else v for k, v in applied.items()})
                CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                with CONFIG_FILE.open("w", encoding="utf-8") as fh:
                    yaml.safe_dump(stored, fh, sort_keys=True, allow_unicode=True)
        return applied


_write_lock = threading.Lock()


def load_settings() -> Settings:
    """Build settings from YAML + environment.

    Env wins over YAML because ``BaseSettings`` treats explicitly passed values
    as the lowest-priority source.
    """
    return Settings(**_load_yaml(CONFIG_FILE))


settings = load_settings()
