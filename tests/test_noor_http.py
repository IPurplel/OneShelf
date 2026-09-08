"""Noor anonymous reader, captured live 2026-09-08; no invented site markup."""
import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.adapters.books import BooksAdapter

FIXTURES = Path(__file__).parent / 'fixtures/noor'
URL = 'https://www.noor-book.com/en/ebook-الليالي-البيضاء-دوستويفسكي-pdf'


class AnonymousSessions:
    def __init__(self, *, setup_status=200):
        self.setup_status = setup_status
        self.requests = []

    def direct_http_client(self, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.respond), follow_redirects=True)

    def respond(self, request):
        self.requests.append(request)
        if request.method == 'GET':
            return httpx.Response(200, text=(FIXTURES / 'book.html').read_text(),
                                  headers={'Set-Cookie': 'anonymous_session=reader; Path=/'})
        assert 'anonymous_session=reader' in request.headers.get('cookie', '')
        data = parse_qs(request.content.decode())
        assert data['book_hash'] and data['csrf_token'] and data['_']
        if request.url.path.endswith('/Verification/check_user'):
            return httpx.Response(self.setup_status, text=(FIXTURES / 'anonymous.json').read_text())
        assert request.url.path.endswith('/book/read_book')
        assert data['ls'] == [json.loads((FIXTURES / 'anonymous.json').read_text())['ls']]
        return httpx.Response(200, text=(FIXTURES / 'reader.html').read_text())

    async def fetch_html_after_click(self, *args, **kwargs):
        raise RuntimeError('browser route cannot connect')


async def test_anonymous_reader_uses_http_session_and_enumerates_all_pages():
    sessions = AnonymousSessions()
    adapter = BooksAdapter(sessions)
    series = await adapter.fetch_series(URL)
    chapters = await adapter.fetch_chapters(series)
    assert len(chapters) == 1
    assert adapter.packaging_for(chapters[0]) == 'pdf'
    pages = await adapter.fetch_pages(chapters[0])
    assert len(pages) == 111
    assert [page.index for page in pages] == list(range(1, 112))
    assert len(sessions.requests) == 3
    assert all('get_download_links' not in str(r.url) for r in sessions.requests)


async def test_403_is_reported_as_http_failure_when_browser_also_fails():
    adapter = BooksAdapter(AnonymousSessions(setup_status=403))
    with pytest.raises(Exception, match='403'):
        await adapter.fetch_series(URL)


@pytest.mark.parametrize('query,fixture_name,has_hits', [
    ('White Nights', 'search.html', True),
    ('zzqvoneshelfnonexistent987654321', 'negative.html', False),
])
async def test_noor_search_uses_http_and_rejects_unanswerable_query(query, fixture_name, has_hits):
    class SearchSessions:
        async def fetch_text_direct(self, url, **kwargs):
            return (FIXTURES / fixture_name).read_text()

        async def fetch_html(self, *args, **kwargs):
            raise AssertionError('Noor static search started a browser')

    results = await BooksAdapter(SearchSessions()).search('https://www.noor-book.com', query)
    assert bool(results) is has_hits
