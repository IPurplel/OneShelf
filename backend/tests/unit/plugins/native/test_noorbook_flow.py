import asyncio
from urllib.parse import urlsplit, parse_qs
from multidict import CIMultiDict
import pytest

from oneshelf.net.browser import BrowserManager
from oneshelf.net.governor import TrafficGovernor, Priority
from oneshelf.net.http import HttpResponse
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.native.noorbook import NoorBookProvider, image_url
from oneshelf.plugins.runtime import AuthRequired, CapabilityError
from tests.unit.plugins.native.test_noorbook import work_html, group_html, HASH, TOKEN, URL


class Source:
    def __init__(self, *, broken=False, readable=True):
        self.broken, self.readable = broken, readable

    def check_url(self, url):
        EgressPolicy(domains=('www.noor-book.com',)).check_url(url)

    async def fetch(self, url, *, method='GET', data=None, **kwargs):
        path = urlsplit(url).path
        if path.startswith('/en/ebook-'):
            html = work_html(readable=self.readable).decode()
            html += f'''<script>
var csrf_token='{TOKEN}', crypto_token='test'; localStorage.setItem('ls','test');
document.querySelector('.read-btn')?.addEventListener('click',async()=>{{
const r=await fetch('/en/book/read_book',{{method:'POST'}});
document.querySelector('#modal').innerHTML=await r.text();}});
</script><div id="modal"></div>'''
        elif path == '/en/book/read_book':
            html = '<a class="pages_from_to" start="1" end="100" file_num="1"></a><a class="pages_from_to" start="101" end="111" file_num="1"></a>'
        elif path == '/en/book/read_modal_load_pages_from_to':
            fields = parse_qs(data.decode())
            assert fields['book_hash'] == [HASH] and fields['csrf_token'] == [TOKEN]
            start, end = int(fields['start'][0]), int(fields['end'][0])
            html = group_html(start, end - (1 if self.broken and start == 101 else 0))
        else:
            return HttpResponse(url,404,CIMultiDict(),b'')
        return HttpResponse(url,200,CIMultiDict({'Content-Type':'text/html'}),html.encode())


def provider(client, browser=None):
    governor=TrafficGovernor()
    governor.configure_source('oneshelf.noorbook',concurrency=2,requests_per_minute=600)
    return NoorBookProvider(client,browser,governor,EgressPolicy(domains=('www.noor-book.com',)),Priority.READER)


def test_native_catalog_is_one_stable_unit_and_preview_is_explicit():
    async def scenario():
        result=await provider(Source()).run('catalog',{'listing_key':'/en/ebook-test-pdf'})
        assert result.complete and len(result.units)==1
        assert result.units[0].unit_key == HASH + ':0' and result.units[0].url == URL
        with pytest.raises(CapabilityError,match='public Read'):
            await provider(Source(readable=False)).run('catalog',{'listing_key':'/en/ebook-test-pdf'})
    asyncio.run(scenario())


@pytest.mark.browser
@pytest.mark.parametrize('broken', [False, True])
def test_real_browser_read_flow_refuses_partial_second_group(broken):
    async def scenario():
        async with BrowserManager() as browser:
            source=provider(Source(broken=broken),browser)
            if broken:
                with pytest.raises(CapabilityError,match='incomplete'):
                    await source.run('reader',{'unit_key':HASH+':0','url':URL})
            else:
                result=await source.run('reader',{'unit_key':HASH+':0','url':URL})
                assert result.complete and len(result.resources)==111
                assert result.resources[-1].page_label=='111'
                assert result.evidence.total_expected==111 and result.evidence.pages==2
    asyncio.run(scenario())


@pytest.mark.browser
def test_cancelling_reader_cancels_pending_source_routes_and_releases_browser():
    async def scenario():
        started,release=asyncio.Event(),asyncio.Event()
        class SlowSource(Source):
            async def fetch(self,url,**kwargs):
                if url.endswith('/stall.js'):
                    started.set()
                    await release.wait()
                    return HttpResponse(url,200,CIMultiDict(),b'')
                response=await super().fetch(url,**kwargs)
                if '/en/ebook-' in url:
                    response.body += b'<script src="/stall.js"></script>'
                return response
        async with BrowserManager() as browser:
            source=provider(SlowSource(),browser)
            task=asyncio.create_task(source.run('reader',{'unit_key':HASH+':0','url':URL}))
            await asyncio.wait_for(started.wait(),10)
            task.cancel()
            done,_=await asyncio.wait({task},timeout=2)
            released_promptly=task in done
            release.set()
            await asyncio.gather(task,return_exceptions=True)
            assert released_promptly, 'cancelled reader retained a pending source route'
            async with asyncio.timeout(1):
                async with source.governor.acquire('another.source',Priority.READER,kind='browser'):
                    pass
    asyncio.run(scenario())


@pytest.mark.parametrize('body,expected', [
    ('<h3 class="text-center loading_read">أنتهى وقت الجلسة قم بإعادة تحميل الصفحة</h3>'.encode(), 'expired'),
    (b'<h3 class="loading_read">Different error</h3>', 'unexpected'),
    (b'<html><body>Challenge</body></html>', 'unexpected'),
    (b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"/>', 'image'),
    (b'\x89PNG\r\n\x1a\n', 'image'),
])
def test_native_resource_distinguishes_expired_session_from_images_and_other_html(body, expected):
    class ResourceSource(Source):
        async def fetch(self, url, **kwargs):
            return HttpResponse(url, 200, CIMultiDict(), body)
    async def scenario():
        source=provider(ResourceSource())
        if expected == 'image':
            assert (await source.resource(image_url(HASH,TOKEN,1), capability='reader')).body == body
        else:
            with pytest.raises(CapabilityError) as raised:
                await source.resource(image_url(HASH,TOKEN,1), capability='reader')
            if expected == 'expired':
                assert not isinstance(raised.value, AuthRequired)
                assert raised.value.category == 'expired_link'
    asyncio.run(scenario())
