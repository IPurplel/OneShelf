"""Real reader regressions against an isolated API and production build, with no remote sources.

Run after npm run build: backend/.venv/bin/python frontend/tests/reader_browser.py
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
from playwright.sync_api import expect, sync_playwright
from oneshelf.db.connection import open_database
from oneshelf.db.migrate import migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.storage.roots import register_root
from tests.fixtures.builders import make_cbz, make_epub, make_pdf, make_text_unit, png_bytes
from tests.fixtures.library import Library


def seed(base):
    data = base / 'data'
    data.mkdir()
    storage = base / 'library'
    storage.mkdir()
    migrate(data / 'oneshelf.db', MIGRATIONS, snapshot_dir=data / 'snapshots')
    conn = open_database(data / 'oneshelf.db')
    lib = Library(conn, base, register_root(conn, 'Reader test', storage))
    epub = make_epub(base / 'book.epub').read_bytes()
    pdf = make_pdf(base / 'paper.pdf').read_bytes()
    records = {
        'epub': lib.add_work('EPUB book', source='local', content_type='book', fmt='epub', content=epub),
        'pdf': lib.add_work('PDF paper', source='local', content_type='paper', fmt='pdf', content=pdf),
        'mixed': lib.add_work('Both formats', source='local', content_type='book', fmt='pdf', content=pdf),
        # A downloaded Arabic text unit (plugin API 1.2): it must run right to left in an English interface.
        'text': lib.add_work('Arabic novel', source='local', content_type='novel', language='ar', fmt='text',
                             relative='Books/Arabic novel/ar/local/one.ostext',
                             content=make_text_unit(base / 'novel.ostext', title='الفصل الأول', language='ar',
                                                    direction='rtl', sections=[
                                                        '<h2>الفصل الأول</h2><p>كان المصباح ما يزال مضاءً.</p>',
                                                        '<h2>الفصل الثاني</h2><p>عادت إلى الغرفة.</p>']).read_bytes()),
        'comic': lib.add_work('Comic', source='local', content=make_cbz(base / 'comic.cbz',
            pages=[(f'{i:03}.png', png_bytes(600, 900)) for i in range(12)]).read_bytes()),
    }
    alt = lib.add_asset(records['mixed']['unit_id'], fmt='epub', content=epub)
    conn.execute("UPDATE assets SET created_at='2000-01-01' WHERE id=?", (records['mixed']['asset_id'],))
    conn.execute("UPDATE assets SET created_at='2000-01-02' WHERE id=?", (alt,))
    conn.close()
    return records


def verify(base, url, records):
    def api(path, body=None):
        request = urllib.request.Request(url + path, data=None if body is None else json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={'width': 1440, 'height': 900})
        errors, requests = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.on('request', lambda request: requests.append(request.url))
        for kind in ('epub', 'pdf', 'mixed'):
            record = records[kind]
            page.goto(url + '/works/' + record['work_id'])
            page.locator('.work__actions a[href^="/read/"]').click()
            expect(page.get_by_role('toolbar', name='Reading controls')).to_be_visible()
            if kind == 'pdf':
                expect(page.locator('canvas').first).to_be_visible()
            else:
                page.wait_for_function("document.querySelector('iframe')?.srcdoc.includes('<body>')")
            expect(page.get_by_role('alert')).to_have_count(0)
            assert 'work=' + record['work_id'] in page.url
            assert 'track=' + record['track_id'] in page.url
            print(f'PASS Work entry: {kind}', flush=True)
        record = records['epub']
        page.goto(url + '/read/' + record['unit_id'])
        page.wait_for_function("document.querySelector('iframe')?.srcdoc.includes('<body>')")
        print('PASS legacy unit-only EPUB entry', flush=True)
        page.goto(url + '/read/' + record['unit_id'] + '?work=nonexistent')
        expect(page.get_by_role('alert')).to_be_visible()
        expect(page.get_by_role('button', name='Try again')).to_be_visible()
        print('PASS missing work shows recoverable error', flush=True)
        text = records['text']
        page.goto(url + '/works/' + text['work_id'])
        page.locator('.work__actions a[href^="/read/"]').click()
        page.wait_for_function("document.querySelector('iframe')?.srcdoc.includes('كان المصباح')")
        frame = page.locator('iframe.book__frame')
        assert frame.get_attribute('sandbox') == ''
        srcdoc = frame.get_attribute('srcdoc')
        assert 'dir="rtl"' in srcdoc and "default-src 'none'" in srcdoc and '<script' not in srcdoc
        assert page.evaluate('document.documentElement.dir') != 'rtl'      # the interface stays English
        expect(page.get_by_role('status')).to_have_text('1 of 2')
        page.get_by_role('button', name='Next').click()
        page.wait_for_function("document.querySelector('iframe')?.srcdoc.includes('عادت إلى الغرفة')")
        page.get_by_role('button', name='Bookmark this place').click()
        page.wait_for_timeout(1600)                                         # progress writes are debounced
        marks = api('/api/reader/units/' + text['unit_id'] + '/marks')
        assert [b['locator'] for b in marks['bookmarks']] == [{'chapter': 1}], marks
        assert api('/api/reader/units/' + text['unit_id'] + '/progress')['locator'] == {'chapter': 1}
        page.reload()
        expect(page.get_by_role('status')).to_have_text('2 of 2')
        print('PASS downloaded Arabic text unit reads RTL in the sandbox, bookmarks and resumes', flush=True)
        comic = records['comic']
        assert api('/api/downloads/settings')['auto_download']['enabled'] is False
        api('/api/downloads/settings', {'auto_download': {'enabled': True, 'mode': 'read_ahead', 'read_ahead': 3}})
        page.goto(url + '/read/' + comic['unit_id'])
        stage = page.locator('[data-testid=reader-stage]')
        expect(stage).to_be_visible()
        page.wait_for_function("document.querySelector('.reader__stage img')?.naturalHeight > 0")
        requests.clear()
        stage.hover()
        with page.expect_response(lambda response: '/engagement' in response.url):
            page.mouse.wheel(0, 4000)
        page.wait_for_timeout(1600)
        assert api('/api/reader/units/' + comic['unit_id'] + '/progress')['fraction'] > 0
        page.mouse.move(100, 100)
        with page.expect_response(lambda response: '/leave' in response.url):
            page.locator('.reader__bar--top a').click()
        expect(page.locator('.work__header')).to_be_visible()
        assert any('/engagement' in path for path in requests)
        assert any('/leave' in path for path in requests)
        print('PASS genuine scrolling saves progress and sends engagement/leave', flush=True)
        assert errors == [], errors
        browser.close()


def main():
    assert (ROOT / 'frontend/dist/index.html').is_file(), 'Run npm run build in frontend first'
    with tempfile.TemporaryDirectory(prefix='oneshelf-reader-verified-') as temporary:
        base = Path(temporary)
        records = seed(base)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'ONESHELF_DATA_DIR': str(base / 'data'),
               'ONESHELF_WEB_ROOT': str(ROOT / 'frontend/dist'), 'ONESHELF_PORT': str(port),
               'ONESHELF_HOST': '127.0.0.1', 'ONESHELF_SESSION_KEY_FILE': str(base / 'session.key'),
               'ONESHELF_BUNDLED_PLUGINS_DIR': '', 'ONESHELF_REGISTRY_URL': '',
               'ONESHELF_FIRST_PARTY_REGISTRY_URL': '', 'ONESHELF_DEV_TEST_SOURCE': ''}
        with (base / 'server.log').open('w+') as log:
            server = subprocess.Popen([sys.executable, '-m', 'oneshelf'], cwd=ROOT / 'backend', env=env,
                                      stdout=log, stderr=subprocess.STDOUT)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(url + '/api/reader/settings'):
                            break
                    except (urllib.error.URLError, ConnectionError):
                        assert server.poll() is None, 'API process exited'
                        time.sleep(.1)
                else:
                    raise AssertionError('API failed to start')
                verify(base, url, records)
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                server.terminate()
                server.wait(timeout=15)


if __name__ == '__main__':
    main()
