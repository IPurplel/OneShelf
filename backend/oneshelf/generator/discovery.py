"""Generator discovery pipeline (Master §12.2).

    URL → static discovery → site mapping → capabilities → optional browser escalation
        → XHR/DOM/media → confidence

Every fetch goes through the Core HTTP client under an egress policy scoped to the site, so discovery
obeys the same SSRF rules as everything else (§11), and Scrapling/lxml is used only to read what came
back. Capability states are Confirmed, Probable, Unknown or Unsupported — never an optimistic guess.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from oneshelf.generator import structure
from oneshelf.generator.structure import FieldGuess
from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy
from oneshelf.sources.fetcher import DevHostsResolver

CONFIRMED, PROBABLE, UNKNOWN, UNSUPPORTED = "confirmed", "probable", "unknown", "unsupported"
SEARCH_PARAMS = ("q", "query", "s", "search", "keyword", "term")
PAGE_PARAMS = ("page", "p", "offset", "start")
MAX_SAMPLES = 2
# Placeholder values used when re-running a recipe's search URL during repair.
USABLE_START = {"query": "a", "page": "1"}


class DiscoveryError(RuntimeError):
    pass


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    body: bytes

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def is_html(self) -> bool:
        return "html" in self.content_type

    @property
    def is_json(self) -> bool:
        return "json" in self.content_type


@dataclass
class SearchMap:
    url_template: str | None = None
    item_selector: str | None = None
    fields: dict[str, FieldGuess] = field(default_factory=dict)
    page_param: str | None = None


@dataclass
class WorkMap:
    url_template: str | None = None
    id_pattern: str | None = None
    fields: dict[str, FieldGuess] = field(default_factory=dict)


@dataclass
class CatalogMap:
    item_selector: str | None = None
    fields: dict[str, FieldGuess] = field(default_factory=dict)
    unit_pattern: str | None = None


@dataclass
class ReaderMap:
    url_template: str | None = None
    image_selector: str | None = None
    sample_images: list[str] = field(default_factory=list)


@dataclass
class SiteMap:
    start_url: str
    base_url: str
    domains: list[str] = field(default_factory=list)
    cdn_domains: list[str] = field(default_factory=list)
    rejected_domains: list[str] = field(default_factory=list)
    search: SearchMap = field(default_factory=SearchMap)
    work: WorkMap = field(default_factory=WorkMap)
    catalog: CatalogMap = field(default_factory=CatalogMap)
    reader: ReaderMap = field(default_factory=ReaderMap)
    capabilities: dict[str, str] = field(default_factory=dict)
    samples: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    fetches: list[dict] = field(default_factory=list)      # Recipe Inspector evidence
    bodies: dict[str, bytes] = field(default_factory=dict)  # captured pages, reused as offline test fixtures

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    if not parts.scheme or not parts.netloc:
        raise DiscoveryError("give the full address of a page on the source, including https://")
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def _registrable(host: str) -> str:
    return host.split("@")[-1].split(":")[0].lower()


def _template_from_query(url: str) -> tuple[str | None, str | None]:
    """Turn '…/search?q=solo&page=2' into '…/search?q={query}' plus the page parameter it used."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    search_key = next((k for k in query if k.lower() in SEARCH_PARAMS), None)
    if search_key is None:
        return None, None
    page_key = next((k for k in query if k.lower() in PAGE_PARAMS), None)
    rebuilt = {k: ("{query}" if k == search_key else v) for k, v in query.items() if k != page_key}
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(rebuilt, safe="{}"), "")), page_key


def _search_form(tree, base_url: str) -> str | None:
    for form in tree.xpath("//form"):
        inputs = form.xpath(".//input[@name]")
        names = [i.get("name") for i in inputs if i.get("name")]
        candidate = next((n for n in names if n.lower() in SEARCH_PARAMS), None)
        if candidate is None and not any((i.get("type") or "").lower() == "search" for i in inputs):
            continue
        if candidate is None and not names:
            continue
        candidate = candidate or names[0]
        action = urljoin(base_url, form.get("action") or "")
        return f"{action}?{candidate}={{query}}"
    return None


def _pattern_from_url(url: str, *, group_name: str) -> str:
    """A conservative URL pattern for the id segment of a work or unit URL."""
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return ""
    prefix = "/".join(segments[:-1])
    escaped = re.escape(f"{parts.scheme}://{parts.netloc}/{prefix}")
    return rf"^{escaped}/(?P<{group_name}>[^/?#]+)/?$"


def _template_from_url(url: str, placeholder: str) -> str:
    parts = urlsplit(url)
    segments = [s for s in parts.path.split("/") if s]
    if not segments:
        return url
    segments[-1] = placeholder
    return urlunsplit((parts.scheme, parts.netloc, "/" + "/".join(segments), "", ""))


class Discovery:
    def __init__(self, start_url: str, *, dev_hosts: dict | None = None, allow_http: bool = False,
                 max_fetches: int = 24) -> None:
        self.start_url = start_url
        self.dev_hosts = dev_hosts
        self.allow_http = allow_http
        self.max_fetches = max_fetches
        self.site = SiteMap(start_url=start_url, base_url=_origin(start_url))
        self.host = _registrable(urlsplit(start_url).netloc)
        self.site.domains = [self.host]
        self._client: HttpClient | None = None
        self._referenced: list[str] = []

    # -- fetching -----------------------------------------------------------------------------------

    def _policy(self, extra: list[str]) -> EgressPolicy:
        # The loopback exception exists only for development against the OneShelf Test Source, which is
        # the only caller that passes dev hosts (see api/generator.py).
        return EgressPolicy(domains=(self.host,), cdn_domains=tuple(dict.fromkeys(extra)),
                            allow_http=self.allow_http, dev_loopback_exception=bool(self.dev_hosts))

    async def _open(self, extra: list[str] | None = None) -> HttpClient:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
        resolver = DevHostsResolver(self.dev_hosts) if self.dev_hosts else None
        self._client = await HttpClient(self._policy(extra or []), resolver_backend=resolver).__aenter__()
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def fetch(self, url: str) -> Fetched | None:
        if len(self.site.fetches) >= self.max_fetches:
            self.site.note("Stopped early: the discovery fetch budget was reached.")
            return None
        response = await self._client.fetch(url)
        fetched = Fetched(url=response.url, status=response.status,
                          content_type=(response.headers.get("content-type") or "").lower(), body=response.body)
        self.site.fetches.append({"url": fetched.url, "status": fetched.status, "content_type": fetched.content_type,
                                  "bytes": len(fetched.body)})
        if fetched.is_html and len(fetched.body) <= 512 * 1024:
            self.site.bodies[fetched.url] = fetched.body
        return fetched if fetched.status == 200 else None

    def _parse(self, page: Fetched):
        tree = structure.parse(page.text)
        for attribute in ("src", "href"):
            for value in tree.xpath(f"//script/@{attribute}|//img/@{attribute}|//iframe/@{attribute}"):
                self._referenced.append(urljoin(page.url, value))
        return tree

    # -- pipeline -----------------------------------------------------------------------------------

    async def run(self) -> SiteMap:
        await self._open()
        try:
            start = await self.fetch(self.start_url)
            if start is None:
                raise DiscoveryError("the start page could not be fetched")
            if not start.is_html:
                raise DiscoveryError("start from a normal page of the site; this address returned "
                                     f"{start.content_type or 'no content type'}")
            tree = self._parse(start)
            await self._map_search(start, tree)
            await self._map_work_and_units(start, tree)
            await self._classify_domains()
            return self.site
        finally:
            await self.close()

    async def _map_search(self, page: Fetched, tree) -> None:
        template, page_param = _template_from_query(page.url)
        blocks = structure.repeated_blocks(tree)
        if template is None:
            template = _search_form(tree, self.site.base_url)
            if template is not None:
                self.site.note("The search route came from a form on the page; run a test query before trusting it.")
        if template is None:
            self.site.capabilities["search"] = UNKNOWN
            return
        self.site.search.url_template = template
        self.site.search.page_param = page_param
        if not blocks:
            if structure.looks_javascript_driven(tree):
                self.site.capabilities["search"] = UNSUPPORTED
                self.site.note("This page builds its results with JavaScript; a browser capability or the "
                               "underlying API is required before search can be supported.")
            else:
                self.site.capabilities["search"] = UNKNOWN
                self.site.note("No repeated result blocks were found on the search page.")
            return
        best = blocks[0]
        self.site.search.item_selector = best.selector
        self.site.search.fields = structure.item_fields(best.elements, base_url=page.url)
        self.site.samples.setdefault("search", []).append(page.url)
        self.site.capabilities["search"] = CONFIRMED if best.count >= 2 else PROBABLE

    async def _map_work_and_units(self, page: Fetched, tree) -> None:
        candidates = self._work_candidates(page, tree)
        if not candidates:
            self.site.capabilities.setdefault("work", UNKNOWN)
            return
        pages: list[tuple[Fetched, object]] = []
        for url in candidates[:MAX_SAMPLES]:
            fetched = await self.fetch(url)
            if fetched is None or not fetched.is_html:
                continue
            pages.append((fetched, self._parse(fetched)))
            self.site.samples.setdefault("work", []).append(fetched.url)
        if not pages:
            self.site.capabilities["work"] = UNKNOWN
            return
        first, first_tree = pages[0]
        self.site.work.fields = structure.page_fields(first_tree, base_url=first.url)
        self.site.work.url_template = _template_from_url(first.url, "{work_id}")
        self.site.work.id_pattern = _pattern_from_url(first.url, group_name="work_id")
        titles = [structure.page_fields(t, base_url=f.url).get("title") for f, t in pages]
        sane = all(g is not None and g.sample for g in titles)
        self.site.capabilities["work"] = (CONFIRMED if sane and len(pages) >= MAX_SAMPLES
                                          else PROBABLE if sane else UNKNOWN)
        await self._map_units(first, first_tree)

    def _work_candidates(self, page: Fetched, tree) -> list[str]:
        if self.site.search.item_selector:
            urls = []
            for block in structure.repeated_blocks(tree):
                if block.selector != self.site.search.item_selector:
                    continue
                for element in block.elements:
                    link = element.xpath(".//a[@href]")
                    if link:
                        urls.append(urljoin(page.url, link[0].get("href")))
            return [u for u in dict.fromkeys(urls) if _registrable(urlsplit(u).netloc) == self.host]
        return [page.url]        # the developer pasted a work page

    async def _map_units(self, page: Fetched, tree) -> None:
        block = structure.chapter_blocks(tree, base_url=page.url)
        if block is None:
            self.site.capabilities["catalog"] = UNKNOWN
            self.site.note("No reading units were found on the work page; they may come from an API "
                           "(open the Recipe Inspector) or need a browser.")
            return
        self.site.catalog.item_selector = block.selector
        self.site.catalog.fields = structure.item_fields(block.elements, base_url=page.url, unit_key=True)
        first_unit = self.site.catalog.fields.get("url")
        self.site.capabilities["catalog"] = CONFIRMED if block.count >= 2 else PROBABLE
        if first_unit is None or not first_unit.sample:
            self.site.capabilities["reader"] = UNKNOWN
            return
        self.site.catalog.unit_pattern = _pattern_from_url(first_unit.sample, group_name="unit_key")
        await self._map_reader(first_unit.sample)

    async def _map_reader(self, unit_url: str) -> None:
        fetched = await self.fetch(unit_url)
        if fetched is None or not fetched.is_html:
            self.site.capabilities["reader"] = UNKNOWN
            return
        tree = self._parse(fetched)
        selector, images = structure.image_group(tree, base_url=fetched.url)
        self.site.samples.setdefault("reader", []).append(fetched.url)
        if selector is None:
            if structure.looks_javascript_driven(tree):
                self.site.capabilities["reader"] = UNSUPPORTED
                self.site.note("The reader page needs JavaScript; look for the underlying media request "
                               "instead of rendering screenshots.")
            else:
                self.site.capabilities["reader"] = UNKNOWN
            return
        self.site.reader.image_selector = selector
        self.site.reader.sample_images = images
        self.site.reader.url_template = _template_from_url(fetched.url, "{unit_key}")
        self.site.capabilities["reader"] = CONFIRMED if len(images) >= 2 else PROBABLE

    # -- domains ------------------------------------------------------------------------------------

    async def _classify_domains(self) -> None:
        """Only hosts that actually served content the adapter needs become permissions (§12.3)."""
        needed = list(self.site.reader.sample_images)
        for guess in (*self.site.search.fields.values(), *self.site.work.fields.values()):
            if guess.sample and guess.sample.startswith("http") and "src" in (guess.css or ""):
                needed.append(guess.sample)
            if guess.sample and guess.sample.startswith("http") and "content" in (guess.css or ""):
                needed.append(guess.sample)
        candidates = [h for h in structure.asset_hosts(needed) if h != self.host]
        if candidates:
            await self._open(candidates)
        verified = []
        for host in candidates:
            sample = next(u for u in needed if _registrable(urlsplit(u).netloc) == host)
            fetched = await self.fetch(sample)
            if fetched is not None and len(fetched.body) > 0:
                verified.append(host)
            else:
                self.site.note(f"{host} was referenced but did not serve usable content; it is not requested "
                               "as a permission.")
        self.site.cdn_domains = verified
        referenced = structure.asset_hosts(self._referenced + [f["url"] for f in self.site.fetches])
        self.site.rejected_domains = [h for h in referenced if h != self.host and h not in verified]


async def discover(url: str, *, dev_hosts: dict | None = None, allow_http: bool = False) -> SiteMap:
    return await Discovery(url, dev_hosts=dev_hosts, allow_http=allow_http).run()
