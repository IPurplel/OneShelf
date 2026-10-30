"""Reviewed Noor Book public Read flow (native exception, plugin API 1.3).

Scrapling parses source markup. Lazy image addresses follow the verified source
read.min.js contract; every group must also contain matching source-issued URLs.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re
from urllib.parse import unquote, urljoin, urlsplit

from scrapling.parser import Selector

from oneshelf.plugins.results import WorkDetails, ResourceDescriptor
from oneshelf.plugins.runtime import CapabilityError

ORIGIN = 'https://www.noor-book.com'
MAX_PAGES = 1000
MAX_GROUPS = 20
_HASH = re.compile(r'[a-f0-9]{16,64}\Z')
_TOKEN = re.compile(r'[A-Za-z0-9_-]{16,256}\Z')


def _invalid(message):
    return CapabilityError('parser_failure', message)


def book_url(key: str) -> str:
    if not isinstance(key, str) or len(key) > 2000:
        raise _invalid('Invalid Noor book address')
    parts = urlsplit(key)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        raise _invalid('Noor listing key must be a book path')
    path = unquote(parts.path)
    # Same-titled books get a numeric suffix: "/كتاب-الغريب-pdf-1613751028".
    if not re.fullmatch(r'/(?:en/ebook-|كتاب-)[^/\\?#%\x00-\x20]+-pdf(?:-[0-9]{1,12})?', path):
        raise _invalid('Unsupported Noor book path')
    return ORIGIN + path


def _page(url: str) -> Selector:
    return Selector(url, huge_tree=False)


@dataclass(frozen=True)
class Book:
    details: WorkDetails
    book_hash: str
    pages: int
    readable: bool

    @property
    def unit_key(self):
        return self.book_hash + ':0'


def parse_book(body: bytes, url: str) -> Book:
    doc = _page(body.decode('utf-8', errors='replace'))
    hashes = re.findall(r'\bvar\s+book_hash\s*=\s*[\'"]([a-f0-9]{16,64})[\'"]\s*;',
                        '\n'.join(doc.css('script::text').getall()))
    if len(set(hashes)) != 1:
        raise _invalid('Noor book identity missing or ambiguous')
    metadata = []
    for text in doc.css('script[type="application/ld+json"]::text').getall():
        try:
            value = json.loads(text)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and value.get('@type') == 'Book':
            metadata.append(value)
    if len(metadata) != 1:
        raise _invalid('Noor book metadata missing or ambiguous')
    data = metadata[0]
    title = data.get('name')
    if not isinstance(title, str) or not title.strip():
        raise _invalid('Noor book title missing')
    try:
        count = int(data['numberOfPages'])
    except (ValueError, TypeError, KeyError):
        raise _invalid('Noor page total missing') from None
    if count < 1:
        raise _invalid('Invalid Noor page total')
    author = data.get('author')
    creator = author.get('name') if isinstance(author, dict) else None
    language = data.get('inLanguage')
    if not isinstance(language, str) or not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*', language):
        language = None
    cover = data.get('image')
    cover = urljoin(ORIGIN, cover) if isinstance(cover, str) else None
    if cover and (urlsplit(cover).scheme != 'https' or urlsplit(cover).netloc != 'www.noor-book.com'):
        cover = None
    description = data.get('description')
    details = WorkDetails(title=title.strip(), creator=creator if isinstance(creator, str) else None,
                          description=description if isinstance(description, str) else None,
                          cover_url=cover, content_type='book', language=language)
    return Book(details, hashes[0], count, bool(doc.css('a.read-btn')))


def page_groups(markup: str, *, expected_total: int) -> list[tuple[int, int]]:
    if not 1 <= expected_total <= MAX_PAGES:
        raise CapabilityError('unsupported', 'Noor book exceeds the supported page limit')
    groups = []
    for item in _page(markup).css('.pages_from_to'):
        if item.attrib.get('file_num') != '1':
            continue  # alternate scans are not concatenated to the first scan
        try:
            start, end = int(item.attrib['start']), int(item.attrib['end'])
        except (KeyError, ValueError):
            raise _invalid('Invalid Noor reader group') from None
        previous = groups[-1][1] if groups else 0
        if start != previous + 1 or end < start or end > MAX_PAGES or end - start >= 100:
            raise _invalid('Noor reader groups are not contiguous')
        groups.append((start, end))
    if not groups or len(groups) > MAX_GROUPS or groups[-1][1] != expected_total:
        raise _invalid('Noor reader groups do not cover the complete book')
    return groups


def image_url(book_hash: str, token: str, number: int) -> str:
    if not _HASH.fullmatch(book_hash) or not _TOKEN.fullmatch(token) or not 1 <= number <= MAX_PAGES:
        raise _invalid('Invalid Noor page identity')
    return f'{ORIGIN}/book/read_book_image/0/{book_hash}/{number}/{token}.svg'


def group_resources(markup: str, start: int, end: int, book_hash: str, token: str) -> list[ResourceDescriptor]:
    nodes = _page(markup).css('.page_img')
    try:
        numbers = [int(item.attrib['page_number']) for item in nodes]
    except (KeyError, ValueError):
        raise _invalid('Noor reader page number missing') from None
    if numbers != list(range(start, end + 1)):
        raise _invalid('Noor reader group is incomplete or reordered')
    resources = []
    witnessed = False
    for number, node in zip(numbers, nodes, strict=True):
        expected = image_url(book_hash, token, number)
        for src in node.css('img::attr(src)').getall():
            if urljoin(ORIGIN, src) != expected:
                raise _invalid('Noor reader image belongs to a different book, scan or session')
            witnessed = True
        resources.append(ResourceDescriptor(expected, number - 1, str(number)))
    if not witnessed:
        raise _invalid('Noor group contains no verifiable source image address')
    return resources

# Native orchestration is Core code, never read from a package or generated by a source.
import asyncio
from urllib.parse import quote, urlencode

from oneshelf.net.governor import Priority
from oneshelf.net.http import FetchFailed, ResponseTooLarge, TooManyRedirects
from oneshelf.net.policy import DisallowedTarget, BlockedDestination
from oneshelf.plugins.results import Evidence, ListResult, Listing, UnitDescriptor
from oneshelf.plugins.runtime import AuthRequired, PublicReaderExpired, RateLimited, RecipeRequest, parse_retry_after


def check_response(response):
    if response.status == 429:
        raise RateLimited(parse_retry_after(response.headers.get('Retry-After')))
    if response.status == 401:
        raise AuthRequired()
    if response.status == 403:
        raise CapabilityError('blocked', 'Noor requires verification before this book can be read')
    if response.status == 404:
        raise CapabilityError('not_found', 'Noor book is unavailable')
    if response.status != 200:
        raise CapabilityError('unexpected_response', 'Noor returned an unexpected response')


MAX_SEARCH_RESULTS = 60


def search_url(query) -> str:
    if not isinstance(query, str) or not query.strip() or len(query) > 200:
        raise _invalid('Invalid Noor search query')
    return f'{ORIGIN}/?{urlencode({"search_for": query.strip()}, quote_via=quote)}'


def parse_search(body: bytes) -> list[Listing]:
    """Noor's own search page (its schema.org SearchAction target). A result that links to a review page
    instead of a book page was withdrawn for copyright ("غير متاح"): it has nothing to open and is skipped."""
    doc = _page(body.decode('utf-8', errors='replace'))
    listings, seen = [], set()
    for item in doc.css('div.book-restult')[:MAX_SEARCH_RESULTS]:
        href = item.css('a.img-a::attr(href)').get()
        title = ' '.join((item.css("h3[itemprop='name']::text").get() or '').split())
        if not href or not title:
            continue
        try:
            url = book_url(unquote(urlsplit(urljoin(ORIGIN, href)).path))
        except CapabilityError:
            continue
        # Percent-encoded, as a copied book address is, so a book found here and the same book opened by its
        # URL are one listing, not two.
        key = quote(urlsplit(url).path)
        if key in seen:
            continue
        seen.add(key)
        url = ORIGIN + key
        creator = ' '.join((item.css("[itemprop='author'] [itemprop='name']::text").get() or '').split()) or None
        cover = item.css("img[itemprop='image']::attr(src)").get()
        cover = urljoin(ORIGIN, cover) if cover else None
        if cover and (urlsplit(cover).scheme != 'https' or urlsplit(cover).netloc != 'www.noor-book.com'):
            cover = None
        listings.append(Listing(listing_key=key, title=title, url=url, cover_url=cover, creator=creator,
                                # "/en/" is the site's interface language, not the book's.
                                content_type='book', language='ar'))
    return listings


async def run_static(capability, inputs, fetcher):
    """Same typed search/metadata/catalog path for live transport and offline packaged fixtures."""
    if capability == 'search':
        url = search_url(inputs.get('query'))
        response = await fetcher.fetch(RecipeRequest(capability, 'GET', url, {}, None, 'http', 'none'))
        check_response(response)
        return ListResult('search', parse_search(response.body), True,
                          Evidence(pages=1, stop_reason='single_response'))
    if capability not in ('work', 'catalog'):
        raise CapabilityError('unsupported', 'Unsupported static Noor capability')
    url = book_url(inputs.get('listing_key', ''))
    request = RecipeRequest(capability, 'GET', url, {}, None, 'http', 'none')
    response = await fetcher.fetch(request)
    check_response(response)
    book = parse_book(response.body, url)
    if capability == 'work':
        return book.details
    if not book.readable:
        raise CapabilityError('preview_only', 'No public Read flow is available for this Noor book')
    if book.pages > MAX_PAGES:
        raise CapabilityError('unsupported', 'Noor book exceeds the supported page limit')
    return ListResult('catalog', [UnitDescriptor(book.unit_key, 0, book.details.title,
                      unit_type='one_shot', url=url)], True,
                      Evidence(pages=1, stop_reason='single_response', total_expected=1))


class NoorBookProvider:
    def __init__(self, client, browser, governor, policy, priority=Priority.INTERACTIVE, *, resolver_backend=None):
        self.client, self.browser, self.governor = client, browser, governor
        self.policy, self.priority, self.resolver_backend = policy, priority, resolver_backend

    async def request(self, url, **kwargs):
        async with self.governor.acquire('oneshelf.noorbook', self.priority, kind='http'):
            response = await self.client.fetch(url, **kwargs)
        if response.status == 429:
            delay = parse_retry_after(response.headers.get('Retry-After'))
            self.governor.set_retry_after('oneshelf.noorbook', delay if delay is not None else 60)
        return response

    async def fetch(self, request):
        return await self.request(request.url)

    async def resource(self, url, *, capability, max_bytes=None, headers=None):
        self.client.check_url(url)
        path = urlsplit(url).path
        if capability == 'reader':
            if not re.fullmatch(r'/book/read_book_image/0/[a-f0-9]{16,64}/[1-9][0-9]{0,3}/[A-Za-z0-9_-]{16,256}\.svg', path):
                raise _invalid('Invalid Noor reader resource')
        elif capability != 'work':
            raise CapabilityError('unsupported', 'Unsupported Noor resource capability')
        response = await self.request(url, max_bytes=max_bytes, headers=headers)
        if capability == 'reader' and response.status == 200:
            lead = response.body.removeprefix(b'\xef\xbb\xbf').lstrip()
            if lead.startswith(b'<') and not lead.startswith((b'<svg', b'<?xml')):
                if len(response.body) < 4096:
                    doc = _page(response.body.decode('utf-8', errors='replace'))
                    notice = doc.css('h3.loading_read')
                    if len(notice) == 1 and ' '.join(notice[0].get_all_text().split()) == 'أنتهى وقت الجلسة قم بإعادة تحميل الصفحة':
                        # The site returns HTML200 for expired image URLs. Let Core renew its
                        # descriptor list once; this is not a stored login/session requirement.
                        raise PublicReaderExpired()
                raise CapabilityError('unexpected_response', 'Noor returned HTML instead of a reader page')
        return response

    async def run(self, capability, inputs):
        try:
            if capability in ('search', 'work', 'catalog'):
                return await run_static(capability, inputs, self)
            if capability != 'reader':
                raise CapabilityError('unsupported', 'Unsupported Noor capability')
            async with asyncio.timeout(300):
                return await self._reader(inputs)
        except (FetchFailed, ResponseTooLarge, TooManyRedirects):
            raise CapabilityError('transport', 'Noor connection failed or exceeded its limits') from None
        except (DisallowedTarget, BlockedDestination):
            raise CapabilityError('blocked', 'Noor request was refused by source network policy') from None
        except TimeoutError:
            raise CapabilityError('timeout', 'Noor reader exceeded its time limit') from None

    async def _reader(self, inputs):
        if self.browser is None:
            raise CapabilityError('unsupported', 'Noor reading requires the Core browser')
        raw_url = inputs.get('url') or ''
        parts = urlsplit(raw_url)
        if parts.scheme != 'https' or parts.netloc != 'www.noor-book.com' or parts.query or parts.fragment:
            raise _invalid('Invalid Noor reader URL')
        url = book_url(parts.path)
        async with self.governor.acquire('oneshelf.noorbook', self.priority, kind='browser'):
            async with self.browser.context(self.policy, resolver_backend=self.resolver_backend) as handle:
                routes = set()
                async def dispatch(route):
                    task = asyncio.current_task()
                    routes.add(task)
                    try:
                        await self._route(route)
                    finally:
                        routes.discard(task)
                await handle.context.route('**/*', dispatch)
                page = await handle.context.new_page()
                try:
                    response = await page.goto(url, wait_until='load', timeout=60_000)
                    if response is None:
                        raise _invalid('Noor page did not respond')
                    # Only the metadata response status is needed here; source tokens stay in context.
                    from types import SimpleNamespace
                    check_response(SimpleNamespace(status=response.status, headers=response.headers))
                    book = parse_book((await page.content()).encode(), url)
                    if book.unit_key != inputs.get('unit_key'):
                        raise _invalid('Noor reader book identity changed')
                    if not book.readable:
                        raise CapabilityError('preview_only', 'No public Read flow is available for this Noor book')
                    async with page.expect_response(lambda r: urlsplit(r.url).path.endswith('/book/read_book'),
                                                     timeout=30_000) as opened:
                        await page.locator('a.read-btn').first.click(timeout=10_000)
                    modal = await opened.value
                    check_response(SimpleNamespace(status=modal.status, headers=modal.headers))
                    groups = page_groups(await modal.text(), expected_total=book.pages)
                    tokens = await page.evaluate('({book_hash, csrf_token, crypto_token, ls:localStorage.getItem("ls")})')
                    if tokens.get('book_hash') != book.book_hash:
                        raise _invalid('Noor browser identity changed')
                    token = tokens.get('csrf_token')
                    if not isinstance(token, str) or not _TOKEN.fullmatch(token):
                        raise _invalid('Noor reader token missing')
                    for key in ('crypto_token', 'ls'):
                        if not isinstance(tokens.get(key), str) or not 1 <= len(tokens[key]) <= 4096:
                            raise _invalid('Noor reader state missing')
                    endpoint = '/en/book/read_modal_load_pages_from_to' if parts.path.startswith('/en/') else '/book/read_modal_load_pages_from_to'
                    resources = []
                    for start, end in groups:
                        form = {'book_hash': book.book_hash, 'csrf_token': token, '_': tokens['crypto_token'],
                                'ls': tokens['ls'], 'start': str(start), 'end': str(end), 'file_num': '1'}
                        async with asyncio.timeout(30):
                            result = await page.evaluate('''async ({endpoint,form}) => {
                                const r = await fetch(endpoint, {method:'POST',
                                  headers:{'Content-Type':'application/x-www-form-urlencoded; charset=UTF-8',
                                           'X-Requested-With':'XMLHttpRequest'}, body:new URLSearchParams(form)});
                                return {status:r.status, headers:Object.fromEntries(r.headers), body:await r.text()};
                            }''', {'endpoint': endpoint, 'form': form})
                        check_response(SimpleNamespace(status=result['status'], headers=result['headers']))
                        resources.extend(group_resources(result['body'], start, end, book.book_hash, token))
                    return ListResult('reader', resources, True,
                                      Evidence(pages=len(groups), stop_reason='total_count', total_expected=book.pages))
                except CapabilityError:
                    raise
                except Exception:
                    # Playwright errors often embed the signed source URL. Do not return/log them.
                    raise CapabilityError('transport', 'Noor browser Read flow failed') from None
                finally:
                    # A route can be queued behind Retry-After or another source lease. Waiting
                    # for it here would keep the single browser lease after the reader is cancelled.
                    await handle.context.unroute_all(behavior='ignoreErrors')
                    pending = list(routes)
                    for task in pending:
                        task.cancel()
                    if pending:
                        await asyncio.wait(pending, timeout=5)

    async def _route(self, route):
        request = route.request
        try:
            self.client.check_url(request.url)
        except (DisallowedTarget, BlockedDestination):
            await route.abort('blockedbyclient')
            return
        if request.resource_type in ('image', 'media', 'font'):
            await route.abort('blockedbyclient')
            return  # ReaderService fetches selected page resources after descriptor validation.
        try:
            response = await self.request(request.url, method=request.method,
                                          headers=await request.all_headers(), data=request.post_data_buffer,
                                          follow_redirects=False)
            headers = {k: v for k, v in response.headers.items()
                       if k.lower() not in ('content-length', 'content-encoding', 'transfer-encoding',
                                            'connection', 'set-cookie')}
            cookies = response.headers.getall('Set-Cookie', [])
            if cookies:
                headers['set-cookie'] = '\n'.join(cookies)
            await route.fulfill(status=response.status, headers=headers, body=response.body)
        except (FetchFailed, ResponseTooLarge, TooManyRedirects, DisallowedTarget, BlockedDestination):
            await route.abort('failed')
