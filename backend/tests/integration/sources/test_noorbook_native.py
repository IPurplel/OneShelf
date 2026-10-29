"""Native capabilities enter the ordinary URL/open/reader path, including disable and health."""
import pytest
from starlette.testclient import TestClient
from multidict import CIMultiDict

from oneshelf.api.app import AppConfig, create_app
from oneshelf.net.ech import EchClient
from oneshelf.plugins.native.noorbook import NoorBookProvider, image_url
from oneshelf.plugins.results import ListResult, ResourceDescriptor, Evidence
from tests.unit.plugins.native.test_noorbook import HASH
from oneshelf.net.http import HttpResponse
from tests.fixtures.builders import png_bytes
from tests.unit.plugins.native.test_noorbook_package import package, SOURCE
from tests.unit.plugins.native.test_noorbook_flow import Source


@pytest.mark.parametrize("renew_success", [True, False])
def test_noor_url_open_catalog_cover_and_disabled_lifecycle(tmp_path, monkeypatch, renew_success):
    pkg=package(tmp_path,source={**SOURCE,'url_patterns':[
        {'pattern':r'^https://www\.noor-book\.com(/en/ebook-[^/?#]+-pdf)$','capability':'work'}]})
    fake=Source()
    async def fetch(self,url,**kwargs):
        if '/book/read_book_image/' in url:
            if url.endswith('/'+'1'*32+'.svg'):
                return HttpResponse(url,200,CIMultiDict(),'<h3 class="loading_read">أنتهى وقت الجلسة قم بإعادة تحميل الصفحة</h3>'.encode())
            return HttpResponse(url,200,CIMultiDict(),png_bytes())
        if url.endswith('/cover.jpg'):
            return HttpResponse(url,200,CIMultiDict({'Content-Type':'image/png'}),png_bytes())
        return await fake.fetch(url,**kwargs)
    monkeypatch.setattr(EchClient,'fetch',fetch)
    config=AppConfig.from_env({'ONESHELF_DATA_DIR':str(tmp_path/'data'),'ONESHELF_ALLOWED_HOSTS':'testserver',
                              'ONESHELF_SESSION_KEY_FILE':str(tmp_path/'keys'/'session.key')})
    with TestClient(create_app(config),client=('127.0.0.1',50000)) as client:
        upload=client.post('/api/sources/uploads',content=(tmp_path/'native.osp').read_bytes(),
                           headers={'Content-Type':'application/octet-stream'}).json()
        installed=client.post('/api/sources/install',json={'upload_id':upload['upload_id'],
                               'approved_permissions':upload['permissions']})
        assert installed.status_code==200 and installed.json()['state']=='active'
        preview=client.post('/api/resolve-url',json={'url':'https://www.noor-book.com/en/ebook-test-pdf'})
        assert preview.status_code==200, preview.text
        assert preview.json()['result']['title']=='White Nights'
        opened=client.post('/api/listings/open',json={'source_id':pkg.id,'listing_key':'/en/ebook-test-pdf',
                            'title':'White Nights','url':'https://www.noor-book.com/en/ebook-test-pdf','language':'ar'})
        assert opened.status_code==200, opened.text
        assert opened.json()['catalog']=='refreshed',opened.json()
        s=client.app.state.services
        assert s.source_service.reads_online(pkg.id)
        assert not s.source_service.supports_download(pkg.id)
        work=client.get('/api/works/'+opened.json()['work_id']).json()
        assert work['tracks'][0]['can_download'] is False
        unit_id=work['units'][0]['id']
        refused=client.post('/api/downloads',json={'unit_ids':[unit_id]})
        assert refused.status_code==422 and 'online reading' in refused.text
        s.settings.set('global',None,'reader.auto_download.enabled',True)
        engagement=client.post(f'/api/reader/units/{unit_id}/engagement',json={'fraction':1,'interacted':True})
        assert engagement.status_code==200,engagement.text
        assert s.conn.execute('SELECT count(*) FROM download_batches').fetchone()[0]==0
        assert s.conn.execute('SELECT count(*) FROM reading_units').fetchone()[0]==1
        assert s.conn.execute('SELECT count(*) FROM download_jobs').fetchone()[0]==0
        cover=client.get('/api/covers',params={'source':pkg.id,'url':'https://www.noor-book.com/cover.jpg'})
        assert cover.status_code==200 and cover.content.startswith(b'\x89PNG')
        original_run=NoorBookProvider.run
        generations=[]
        async def changing_descriptors(self,capability,inputs):
            if capability != 'reader':
                return await original_run(self,capability,inputs)
            generations.append(True)
            token=str(len(generations) if renew_success else 1)*32
            return ListResult('reader',[ResourceDescriptor(image_url(HASH,token,1),index=0,page_label='1')],True,
                              Evidence(pages=1,stop_reason='total_count',total_expected=1))
        monkeypatch.setattr(NoorBookProvider,'run',changing_descriptors)
        assert client.get(f'/api/reader/units/{unit_id}/pages').status_code==200
        renewed=client.get(f'/api/reader/units/{unit_id}/pages/1')
        if not renew_success:
            assert renewed.status_code == 503, renewed.text
            assert renewed.json()['error']['code'] == 'SOURCE_TEMPORARILY_UNAVAILABLE'
            assert 1 <= int(renewed.headers['Retry-After']) <= 120
            assert 'account' not in renewed.text
            assert client.get(f'/api/reader/units/{unit_id}/pages/1').status_code == 503
            assert len(generations) == 2
            return
        assert renewed.status_code==200 and renewed.content.startswith(b'\x89PNG'),renewed.text
        assert len(generations)==2
        assert client.get(f'/api/reader/units/{unit_id}/pages/1').content==renewed.content
        assert len(generations)==2
        health=client.get(f'/api/sources/{pkg.id}/health').json()['signals']
        assert any(signal['capability']=='work' for signal in health)
        client.post(f'/api/sources/{pkg.id}/disable')
        assert not s.source_service.reads_online(pkg.id)
