"""Real 3asq markup, captured via desync 2026-09-08."""
from pathlib import Path

from app.adapters.madara import MadaraAdapter
from app.adapters.registry import resolve
from .conftest import FakeSessionManager

FIXTURES = Path(__file__).parent / 'fixtures/asq'
URL = 'https://3asq.online/manga/hunter-x-hunter/'
CHAPTER = URL + '01/'


class StaticSessions(FakeSessionManager):
    async def fetch_html(self, *args, **kwargs):
        raise AssertionError('static Madara page opened the blocked browser')

    async def post_form_direct(self, url, data, **kwargs):
        return self.posts[url]


def sessions():
    return StaticSessions(pages={URL: (FIXTURES / 'series.html').read_text(),
                                 CHAPTER: (FIXTURES / 'reader.html').read_text()},
                          posts={URL+'ajax/chapters/': (FIXTURES / 'chapters.html').read_text()})


async def test_static_madara_preview_and_reader_need_no_browser():
    adapter = MadaraAdapter(sessions())
    series = await adapter.fetch_series(URL)
    chapters = await adapter.fetch_chapters(series)
    assert len(chapters) == 93
    assert chapters[0].url == CHAPTER
    assert len(await adapter.fetch_pages(chapters[0])) == 33


async def test_registry_fingerprints_static_madara_over_http():
    manager = sessions()
    adapter = await resolve(URL, manager)
    assert isinstance(adapter, MadaraAdapter)
    assert manager.direct == [URL]


async def test_redirected_series_uses_its_canonical_host_for_ajax():
    original = 'https://3asq.org/manga/hunter-x-hunter/'
    manager = sessions()
    manager.pages[original] = manager.pages[URL]
    adapter = MadaraAdapter(manager)
    series = await adapter.fetch_series(original)
    assert series.url == URL
    assert len(await adapter.fetch_chapters(series)) == 93


async def test_empty_direct_ajax_retries_same_endpoint_in_browser():
    manager = FakeSessionManager(pages={URL: (FIXTURES / 'series.html').read_text()},
                                 posts={URL+'ajax/chapters/': (FIXTURES / 'chapters.html').read_text()})

    async def empty(*args, **kwargs):
        return '0'

    manager.post_form_direct = empty
    adapter = MadaraAdapter(manager)
    chapters = await adapter.fetch_chapters(await adapter.fetch_series(URL))
    assert len(chapters) == 93
    assert manager.posted == [(URL+'ajax/chapters/', {})]
