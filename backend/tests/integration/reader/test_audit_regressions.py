"""Regression coverage for cancellation, read-ahead, and bilingual follows."""
import asyncio
import pytest
from tests.fixtures.builders import make_cbz, png_bytes
from tests.fixtures.library import library
from tests.integration.reader.test_reading import reading

def test_reader_exit_preserves_manually_queued_downloads(reading):
    async def scenario():
        async with reading() as (env,reader,cache):
            binding=await env.add_work('irregular','The Irregular Chronicle')
            current,manual=env.unit_id('irr-1'),env.unit_id('irr-2')
            batch=env.engine.enqueue([manual],label='manual selection')
            await reader.record_engagement(current,fraction=.2,interacted=True)
            canceled=await reader.leaving_work(binding.work_id)
            state=env.job_rows(batch)[0]['state']
            print({'auto_download_enabled':False,'canceled':canceled,'manual_job_state':state})
            assert state=='QUEUED'
    asyncio.run(scenario())


@pytest.mark.parametrize("delete_partial", [False, True])
@pytest.mark.parametrize("phase", ["catalog", "resource"])
def test_cancel_active_download_stays_canceled(reading, delete_partial, phase):
    async def scenario():
        async with reading() as (env,reader,cache):
            await env.add_work('irregular','The Irregular Chronicle')
            unit=env.unit_id('irr-1'); batch=env.engine.enqueue([unit])
            job=env.job_rows(batch)[0]['id']
            entered=asyncio.Event(); release=asyncio.Event()
            method = "run" if phase == "catalog" else "fetch_resource"
            original=getattr(env.service, method)
            async def delayed(*args,**kwargs):
                result=await original(*args,**kwargs)
                if not entered.is_set():
                    entered.set(); await release.wait()
                return result
            setattr(env.service, method, delayed)
            task=asyncio.create_task(env.engine.run_once())
            await asyncio.wait_for(entered.wait(),10)
            env.engine.cancel_job(job,delete_partial=delete_partial)
            canceled_state=env.engine.job(job)['state']
            release.set(); await task
            final_state=env.engine.job(job)['state']
            print({'after_cancel':canceled_state,'after_worker_finished':final_state,'assets':len(env.assets())})
            assert final_state=='CANCELED'
            assert env.assets() == []
            assert env.files() == []
    asyncio.run(scenario())


def test_read_ahead_mode_from_public_settings_is_honored(reading):
    from oneshelf.api.library import set_download_settings, DownloadSettingsBody
    from types import SimpleNamespace
    async def scenario():
        async with reading() as (env,reader,cache):
            await env.add_work('irregular','The Irregular Chronicle')
            request=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(settings=reader.settings))))
            settings=await set_download_settings(request,DownloadSettingsBody(auto_download={'enabled':True,'mode':'read_ahead','read_ahead':3}))
            queued=await reader.record_engagement(env.unit_id('irr-1'),fraction=.2,interacted=True)
            print({'settings_mode':settings['auto_download']['mode'],'queued_units':len(queued)})
            assert len(queued)==4
    asyncio.run(scenario())


def test_following_a_second_language_keeps_both_baselines(library,tmp_path):
    from oneshelf.follow.service import FollowService
    from oneshelf.catalog.trust import CatalogTrust
    en=library.add_work('Bilingual',source='example',language='en',content=None)
    ja=library.add_work('Bilingual Japanese',source='example',language='ja',content=None)
    library.conn.execute('UPDATE source_tracks SET work_id=? WHERE id=?',(en['work_id'],ja['track_id']))
    service=FollowService(library.conn,CatalogTrust(library.conn))
    first=service.follow(en['work_id'],language='en',source_id='example',track_id=en['track_id'])
    second=service.follow(en['work_id'],language='ja',source_id='example',track_id=ja['track_id'])
    rows=[dict(r) for r in library.conn.execute('SELECT f.id,f.language,f.track_id,b.track_id AS baseline_track FROM follows f LEFT JOIN follow_baselines b ON b.follow_id=f.id ORDER BY f.language')]
    print({'returned_same_follow_id':first.id==second.id,'rows':rows})
    assert all(row['track_id']==row['baseline_track'] for row in rows)


def test_explicit_reader_format_and_context(library, tmp_path):
    from types import SimpleNamespace
    from oneshelf.api.library import reader_file, reader_context
    from oneshelf.reader.service import ReaderService
    from tests.fixtures.builders import make_epub, make_pdf

    pdf = make_pdf(tmp_path / 'book.pdf').read_bytes()
    epub = make_epub(tmp_path / 'book.epub').read_bytes()
    work = library.add_work('Book', source='local', content_type='book', fmt='pdf', content=pdf)
    alternate = library.add_asset(work['unit_id'], fmt='epub', content=epub)
    library.conn.execute("UPDATE assets SET created_at='2000-01-01' WHERE id=?", (work['asset_id'],))
    library.conn.execute("UPDATE assets SET created_at='2000-01-02' WHERE id=?", (alternate,))
    reader = ReaderService(library.conn, None, None)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(reader=reader))))
    context = asyncio.run(reader_context(request, work['unit_id']))
    assert context == {'work_id': work['work_id'], 'track_id': work['track_id'], 'formats': ['epub', 'pdf'], 'kind': 'images'}
    assert asyncio.run(reader_context(request, 'missing')).status_code == 404
    assert asyncio.run(reader_file(request, work['unit_id'], format='epub')).body == epub
    assert asyncio.run(reader_file(request, work['unit_id'], format='pdf')).body == pdf
    assert asyncio.run(reader_file(request, work['unit_id'], format='cbz')).status_code == 404
    assert asyncio.run(reader_file(request, work['unit_id'])).body == pdf


def test_page_reader_selects_cbz_when_an_older_pdf_exists(library, tmp_path):
    from oneshelf.reader.service import ReaderService

    work = library.add_work('Mixed formats', source='local', fmt='pdf', content=b'pdf file')
    cbz = make_cbz(tmp_path / 'pages.cbz').read_bytes()
    library.add_asset(work['unit_id'], fmt='cbz', content=cbz)
    library.conn.execute("UPDATE assets SET created_at='2000-01-01' WHERE id=?", (work['asset_id'],))
    reader = ReaderService(library.conn, None, None)

    pages = asyncio.run(reader.pages(work['unit_id']))
    first = asyncio.run(reader.page(work['unit_id'], 1))
    assert len(pages) == 3
    assert first.origin == 'local' and first.data == png_bytes()


def test_local_pdf_has_no_image_pages(library):
    from oneshelf.reader.service import ReaderService

    work = library.add_work('PDF only', source='local', fmt='pdf', content=b'pdf file')
    reader = ReaderService(library.conn, None, None)
    with pytest.raises(FileNotFoundError, match='page'):
        asyncio.run(reader.pages(work['unit_id']))
    with pytest.raises(FileNotFoundError, match='page'):
        asyncio.run(reader.page(work['unit_id'], 1))


def test_follow_language_operations_and_scheduling_are_independent(library):
    from oneshelf.follow.service import FollowService
    from oneshelf.follow.runner import FollowRunner
    from oneshelf.catalog.trust import CatalogTrust
    en = library.add_work('English', source='example', language='en', content=None)
    ja = library.add_work('Japanese', source='example', language='ja', content=None)
    conn = library.conn
    conn.execute('UPDATE source_tracks SET work_id=? WHERE id=?', (en['work_id'], ja['track_id']))
    service = FollowService(conn, CatalogTrust(conn))
    first = service.follow(en['work_id'], language='en', source_id='example', track_id=en['track_id'])
    second = service.follow(en['work_id'], language='ja', source_id='example', track_id=ja['track_id'])
    assert first.id != second.id
    assert service.status(en['work_id'], language='ja').track_id == ja['track_id']
    assert service.status(en['work_id']).language == 'en'  # legacy calls resolve deterministically
    conn.execute('UPDATE follows SET next_check_at=NULL')
    runner = FollowRunner(conn, service, None, None, service.catalog)
    outcomes = asyncio.run(runner.check_all())
    assert len(outcomes) == 2
    rows = conn.execute('SELECT last_attempted_at, last_error_category FROM follows').fetchall()
    assert all(row['last_attempted_at'] and row['last_error_category'] == 'no_listing' for row in rows)
    token = service.unfollow(en['work_id'], language='ja')
    assert service.status(en['work_id'], language='ja') is None
    assert service.status(en['work_id'], language='en').track_id == en['track_id']
    assert service.undo_unfollow(token).id == second.id
    with pytest.raises(ValueError):
        service.follow(en['work_id'], language='en', source_id='example', track_id=ja['track_id'])
