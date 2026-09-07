"""Adapter for the Madara WordPress theme.

Madara powers a very large share of manga aggregator sites, including the one
this project was built against. Targeting the theme rather than a single domain
means the same code keeps working when a site changes hostname, and works on
hundreds of other installs unchanged.

The theme has been through several major versions with incompatible chapter-list
plumbing, so chapter resolution walks a three-tier fallback:

1. ``POST {series_url}ajax/chapters/``            (Madara >= 1.6)
2. ``POST /wp-admin/admin-ajax.php`` with
   ``action=manga_get_chapters&manga=<post_id>``  (older builds)
3. Parse ``li.wp-manga-chapter`` straight out of the series HTML
   (sites with AJAX chapter loading disabled)

Page extraction handles both the plain ``div.reading-content`` markup and the
"chapter protector" variant that AES-encrypts the image list into a script tag.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from hashlib import md5
from urllib.parse import quote_plus, urlparse, urlunparse

from ..models import Chapter, Page, SearchResult, Series
from .base import Adapter, AdapterError, extract_number as _extract_number, first_attr

log = logging.getLogger(__name__)

# Attribute order matters: lazy-load attributes hold the real URL while `src`
# often holds a placeholder or low-res thumbnail.
IMAGE_ATTRS = ("data-src", "data-lazy-src", "data-original", "data-url", "srcset", "src")

_POST_ID_RE = re.compile(r"manga_id\s*[:=]\s*['\"]?(\d+)", re.I)
_PROTECTOR_RE = re.compile(
    r"chapter_data\s*=\s*'([^']+)'", re.I
)
_PROTECTOR_PASS_RE = re.compile(
    r"wpmangaprotectornonce\s*=\s*'([^']+)'", re.I
)


class MadaraAdapter(Adapter):
    id = "madara"
    name = "Madara (WordPress)"
    priority = 100
    content_type = "manga"

    # -------------------------------------------------------- identification

    @classmethod
    def matches(cls, url: str, html: str | None = None) -> bool:
        if html:
            fingerprints = (
                "wp-manga",
                "reading-content",
                "manga-chapters-holder",
                "wp-manga-chapter",
            )
            if any(marker in html for marker in fingerprints):
                return True
            # Only trust the URL shape if the DOM gave us nothing to go on.
            return False
        return "/manga/" in urlparse(url).path

    # ---------------------------------------------------------------- search

    search_path = "/?s={query}&post_type=wp-manga"

    async def search(self, site: str, query: str, limit: int = 12) -> list[SearchResult]:
        url = site.rstrip("/") + self.search_path.format(query=quote_plus(query))
        tree = self.parse(await self.get_html(url))

        results: list[SearchResult] = []
        seen: set[str] = set()
        for row in tree.css("div.c-tabs-item__content") or tree.css("div.page-item-detail"):
            link = row.css_first("div.post-title h3 a") or row.css_first("h3 a") \
                or row.css_first("a")
            href = self.absolute(url, first_attr(link, "href"))
            title = self.text(link)
            if not href or not title:
                continue
            # These themes repeat a series across a carousel and the result
            # list, so the same hit arrives twice from one page.
            if href.rstrip("/") in seen:
                continue
            seen.add(href.rstrip("/"))
            cover = first_attr(row.css_first("img"), *IMAGE_ATTRS)
            results.append(SearchResult(
                title=title, url=href, source=self.id,
                site=urlparse(href).netloc,
                cover_url=self.absolute(url, cover),
            ))
            if len(results) >= limit:
                break
        return results

    # ---------------------------------------------------------------- series

    async def fetch_series(self, url: str) -> Series:
        url = _normalise_series_url(url)
        html = await self.get_html(url)
        tree = self.parse(html)

        # URL shape alone cannot cover every install, so confirm what actually
        # loaded. Without this, a reader page yields a "series" whose title is
        # whatever heading happens to be present and whose chapter list is
        # navigation markup — which is how a chapter URL produced a one-chapter
        # series pointing at the site index.
        if not _looks_like_series(tree):
            recovered = _series_link_from_page(tree, url)
            if recovered and recovered.rstrip("/") != url.rstrip("/"):
                log.info("%s is not a series page; following it to %s",
                         url, recovered)
                url = recovered
                html = await self.get_html(url)
                tree = self.parse(html)

        if not _looks_like_series(tree):
            raise AdapterError(
                f"{url} does not look like a series page. Open the manga's own "
                "page on the site and paste that URL."
            )

        title = (
            self.text(tree.css_first("div.post-title h1"))
            or self.text(tree.css_first("div.post-title h3"))
            or self.text(tree.css_first("h1.entry-title"))
            or self.text(tree.css_first("meta[property='og:title']"))
            or _title_from_url(url)
        )
        # Madara templates leave the "HOT"/"NEW" badge inside the title node.
        title = re.sub(r"^\s*(HOT|NEW)\s+", "", title).strip()

        cover = first_attr(
            tree.css_first("div.summary_image img"), *IMAGE_ATTRS
        ) or first_attr(tree.css_first("meta[property='og:image']"), "content")

        author = None
        for block in tree.css("div.post-content_item"):
            heading = self.text(block.css_first("div.summary-heading")).lower()
            if "author" in heading or "المؤلف" in heading:
                author = self.text(block.css_first("div.summary-content")) or None
                break

        description = (
            self.text(tree.css_first("div.description-summary div.summary__content"))
            or self.text(tree.css_first("div.summary__content"))
            or None
        )

        series = Series(
            url=url,
            title=title,
            source=self.id,
            cover_url=self.absolute(url, cover),
            author=author,
            description=description,
            site_id=_extract_post_id(html, tree),
        )
        # Cached so fetch_chapters() need not re-fetch the page it just parsed.
        self._last_html = (url, html)
        return series

    # -------------------------------------------------------------- chapters

    async def fetch_chapters(self, series: Series) -> list[Chapter]:
        errors: list[str] = []

        for strategy in (
            self._chapters_via_ajax_path,
            self._chapters_via_admin_ajax,
            self._chapters_via_inline_html,
        ):
            try:
                chapters = await strategy(series)
            except Exception as exc:
                errors.append(f"{strategy.__name__}: {exc}")
                log.debug("Chapter strategy %s failed", strategy.__name__, exc_info=True)
                continue
            if chapters:
                log.info("Resolved %d chapters via %s", len(chapters), strategy.__name__)
                return chapters
            errors.append(f"{strategy.__name__}: no chapters found")

        raise AdapterError(
            "Could not read the chapter list. Tried: " + "; ".join(errors)
        )

    async def _chapters_via_ajax_path(self, series: Series) -> list[Chapter]:
        """Madara >= 1.6: POST to ``<series-url>ajax/chapters/``."""
        endpoint = series.url.rstrip("/") + "/ajax/chapters/"
        html = await self.sessions.post_form(endpoint, {}, referer=series.url)
        return self._parse_chapter_nodes(html, series.url)

    async def _chapters_via_admin_ajax(self, series: Series) -> list[Chapter]:
        """Older Madara: ``admin-ajax.php`` with the numeric post id."""
        post_id = series.site_id
        if not post_id:
            html = await self._series_html(series.url)
            post_id = _extract_post_id(html, self.parse(html))
        if not post_id:
            raise AdapterError("no manga post id on the page")

        parsed = urlparse(series.url)
        endpoint = f"{parsed.scheme}://{parsed.netloc}/wp-admin/admin-ajax.php"
        html = await self.sessions.post_form(
            endpoint,
            {"action": "manga_get_chapters", "manga": str(post_id)},
            referer=series.url,
        )
        return self._parse_chapter_nodes(html, series.url)

    async def _chapters_via_inline_html(self, series: Series) -> list[Chapter]:
        """Last resort: the list is already in the series page markup."""
        html = await self._series_html(series.url)
        return self._parse_chapter_nodes(html, series.url)

    async def _series_html(self, url: str) -> str:
        cached = getattr(self, "_last_html", None)
        if cached and cached[0] == url:
            return cached[1]
        html = await self.get_html(url)
        self._last_html = (url, html)
        return html

    def _parse_chapter_nodes(self, html: str, base_url: str) -> list[Chapter]:
        tree = self.parse(html)
        nodes = tree.css("li.wp-manga-chapter") or tree.css("div.wp-manga-chapter")
        if not nodes:
            # Some skins drop the wrapper class and expose bare links.
            nodes = [n for n in tree.css("li") if n.css_first("a")]

        seen: set[str] = set()
        collected: list[tuple[str, str, str | None]] = []

        for node in nodes:
            link = node.css_first("a")
            href = self.absolute(base_url, first_attr(link, "href"))
            if not href or href in seen:
                continue
            # Guard against picking up navigation links in the fallback path.
            if "/manga/" not in urlparse(href).path:
                continue
            # A "chapter" that is the series itself, or an ancestor of it such
            # as the site index, is never real — that link is breadcrumb or nav
            # markup. Checked as an ancestor rather than requiring links to sit
            # under the series path, because some installs serve chapters from
            # a different prefix (/read/<slug>/<n>/) and a stricter rule would
            # reject those legitimately.
            if _is_ancestor_or_same(href, base_url):
                continue
            seen.add(href)

            title = self.text(link) or href.rstrip("/").rsplit("/", 1)[-1]
            date = (
                self.text(node.css_first("span.chapter-release-date"))
                or self.text(node.css_first("i"))
                or None
            )
            collected.append((href, title, date))

        # Madara lists newest first; reverse so index 0 is chapter 1.
        collected.reverse()

        chapters = [
            Chapter(url=href, title=title, number=_extract_number(title, href),
                    index=i + 1, date=date)
            for i, (href, title, date) in enumerate(collected)
        ]
        # Re-sort by parsed number where available; some sites interleave
        # specials and extras out of order in the markup.
        chapters.sort(key=lambda c: c.sort_key)
        for position, chapter in enumerate(chapters, start=1):
            chapter.index = position
        return chapters

    # ----------------------------------------------------------------- pages

    async def fetch_pages(self, chapter: Chapter) -> list[Page]:
        html = await self.get_html(chapter.url, referer=chapter.url)
        tree = self.parse(html)

        urls = self._images_from_dom(tree, chapter.url)
        if not urls:
            urls = self._images_from_protector(html, chapter.url)
        if not urls:
            raise AdapterError(
                f"No reader images on {chapter.url} — this is either a "
                "placeholder chapter (some series list one with no pages) or "
                "the URL is not a chapter page."
            )

        return [
            Page(index=i + 1, url=url, referer=chapter.url)
            for i, url in enumerate(urls)
        ]

    def _images_from_dom(self, tree, base_url: str) -> list[str]:
        container = (
            tree.css_first("div.reading-content")
            or tree.css_first("div.read-container")
            or tree.css_first("div.entry-content")
        )
        if container is None:
            return []

        nodes = container.css("img.wp-manga-chapter-img") or container.css("img")
        urls: list[str] = []
        for node in nodes:
            raw = first_attr(node, *IMAGE_ATTRS)
            absolute = self.absolute(base_url, raw)
            if absolute and absolute not in urls and not _is_decorative(absolute):
                urls.append(absolute)
        return urls

    def _images_from_protector(self, html: str, base_url: str) -> list[str]:
        """Decode the "chapter protector" payload some installs use.

        The image list is AES-encrypted and base64-wrapped in an inline script.
        The scheme is OpenSSL's ``Salted__`` EVP key derivation with a nonce
        that is present in the same page, so this is obfuscation rather than
        real protection.
        """
        payload = _PROTECTOR_RE.search(html)
        password = _PROTECTOR_PASS_RE.search(html)
        if not payload or not password:
            return []

        try:
            from Crypto.Cipher import AES  # type: ignore import-not-found
            from Crypto.Util.Padding import unpad
        except ImportError:  # pragma: no cover - optional dependency
            log.warning("pycryptodome not installed; cannot read protected chapter")
            return []

        try:
            outer = json.loads(base64.b64decode(payload.group(1)).decode("utf-8"))
            ciphertext = base64.b64decode(outer["ct"])
            salt = bytes.fromhex(outer["s"])
            iv = bytes.fromhex(outer["iv"])
            key = _evp_bytes_to_key(password.group(1).encode(), salt, 32)

            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
            images = json.loads(json.loads(decrypted.decode("utf-8")))
        except Exception:
            log.debug("Failed to decode protected chapter payload", exc_info=True)
            return []

        urls = []
        for item in images:
            absolute = self.absolute(base_url, str(item).strip())
            if absolute:
                urls.append(absolute)
        return urls


def _evp_bytes_to_key(password: bytes, salt: bytes, key_length: int) -> bytes:
    """OpenSSL EVP_BytesToKey (MD5) — what CryptoJS uses by default."""
    derived = b""
    block = b""
    while len(derived) < key_length:
        block = md5(block + password + salt).digest()
        derived += block
    return derived[:key_length]


#: Madara publishes series under a configurable post-type slug. These are the
#: ones seen in the wild. An unrecognised base is left alone rather than
#: guessed at — `fetch_series` verifies the page shape afterwards and can still
#: recover from there.
SERIES_BASES = frozenset({
    "manga", "series", "comic", "comics", "webtoon", "webtoons",
    "manhwa", "manhua", "novel", "read", "title",
})


def _normalise_series_url(url: str) -> str:
    """Reduce any URL inside a series to the series URL itself.

    Madara lays series out as ``/<base>/<slug>/`` and chapters as
    ``/<base>/<slug>/<chapter>/``. Someone pasting the chapter they happen to be
    reading means "this manga", so trim back to the series.

    This previously only stripped the query string, despite its docstring
    promising exactly this behaviour. A chapter URL therefore sailed through as
    a series URL, where the title selectors miss and
    ``<chapter-url>/ajax/chapters/`` answers with navigation markup that parses
    as a single bogus chapter pointing at the site index.
    """
    url = url.strip().split("?")[0].split("#")[0]
    parsed = urlparse(url)
    segments = [segment for segment in parsed.path.split("/") if segment]

    for position, segment in enumerate(segments):
        if segment.lower() not in SERIES_BASES:
            continue
        if position + 1 >= len(segments):
            raise AdapterError(
                f"{url} is a listing page, not a series. Open the manga you "
                "want on the site and paste the URL of its own page."
            )
        path = "/" + "/".join(segments[: position + 2]) + "/"
        return urlunparse((parsed.scheme, parsed.netloc, path, "", "", ""))

    return url if url.endswith("/") else url + "/"


#: Present on a series page and absent from a reader page — verified against
#: saved markup from a live site, not assumed.
SERIES_MARKERS = (
    "div.post-title",
    "div.summary_image",
    "div.listing-chapters_wrap",
    "li.wp-manga-chapter",
    "div.description-summary",
    "#manga-chapters-holder",
    # The theme's series wrapper. Measured on live markup: present once on a
    # series page, absent from a reader page — so it discriminates, and it is
    # the most likely marker to survive on a stripped-down install.
    "div.wp-manga",
)


def _is_ancestor_or_same(href: str, series_url: str) -> bool:
    """True when ``href`` is the series itself or sits above it in the path."""
    series_path = urlparse(series_url).path.rstrip("/")
    link_path = urlparse(href).path.rstrip("/")
    return series_path == link_path or series_path.startswith(link_path + "/")


def _looks_like_series(tree) -> bool:
    return any(tree.css_first(marker) is not None for marker in SERIES_MARKERS)


def _series_link_from_page(tree, url: str) -> str | None:
    """Recover the series URL from a page that turned out to be a chapter.

    The breadcrumb on a Madara reader page links back to the series, which
    works even on installs whose post-type slug we do not recognise. Falls back
    to the canonical URL, trimmed the same way.
    """
    current = urlparse(url).path.rstrip("/")
    best: str | None = None

    for node in tree.css("div.c-breadcrumb a, .breadcrumb a, ol.breadcrumb a"):
        href = first_attr(node, "href")
        if not href:
            continue
        path = urlparse(href).path.rstrip("/")
        # Must be a genuine ancestor, and deeper than the site root or a
        # listing page — otherwise "Home" would win.
        if len([s for s in path.split("/") if s]) < 2:
            continue
        if not current.startswith(path + "/"):
            continue
        if best is None or len(path) > len(urlparse(best).path.rstrip("/")):
            best = href

    if best:
        return best

    canonical = first_attr(tree.css_first("link[rel=canonical]"), "href")
    if canonical:
        try:
            return _normalise_series_url(canonical)
        except AdapterError:
            return None
    return None


def _title_from_url(url: str) -> str:
    slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").replace("_", " ").title() or "Unknown Series"


def _extract_post_id(html: str, tree) -> str | None:
    holder = tree.css_first("#manga-chapters-holder")
    if holder and holder.attributes.get("data-id"):
        return holder.attributes["data-id"].strip()

    button = tree.css_first(".wp-manga-action-button[data-post]")
    if button and button.attributes.get("data-post"):
        return button.attributes["data-post"].strip()

    for node in tree.css("input#manga-id, input[name='manga_id']"):
        value = node.attributes.get("value")
        if value and value.strip().isdigit():
            return value.strip()

    match = _POST_ID_RE.search(html)
    return match.group(1) if match else None




_DECORATIVE = ("data:image", "/wp-content/themes/", "logo", "spinner", "loading.gif")


def _is_decorative(url: str) -> bool:
    lowered = url.lower()
    return any(marker in lowered for marker in _DECORATIVE)
