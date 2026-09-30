"""UX regressions in Chromium. Run with a Vite server: --url http://127.0.0.1:5173."""
import argparse
import json
import traceback
from pathlib import Path
from playwright.sync_api import expect, sync_playwright
from layout_browser import fixture, results


def modal_keyboard(page, url, out):
    page.goto(url + '/settings')
    page.locator('.bottomnav button').click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_focused()
    for key in ['Tab'] * 10 + ['Shift+Tab'] * 10:
        page.keyboard.press(key)
        assert page.evaluate("!!document.activeElement.closest('[role=dialog],dialog')"), 'Focus escaped modal'
    page.locator('main').evaluate('e => e.focus()')
    assert page.evaluate("!!document.activeElement.closest('[role=dialog],dialog')"), 'Background accepts focus'
    page.screenshot(path=str(out / 'more.png'))
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(page.locator('.bottomnav button')).to_be_focused()


def removal_keyboard(page, url, out):
    page.route(url + '/api/shelf/w0/removal-summary', lambda r: r.fulfill(json=dict(
        work_id='w0', files=12, bytes=1000000, has_progress=True, is_followed=True)))
    page.goto(url + '/works/w0')
    opener = page.get_by_role('button', name='Remove from shelf', exact=True)
    opener.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_focused()
    page.keyboard.press('Shift+Tab')
    expect(dialog.get_by_role('button', name='Keep the files')).to_be_focused()
    page.screenshot(path=str(out / 'removal.png'))
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()


def confirm_keyboard(page, url, out):
    page.goto(url + '/downloads')
    opener = page.get_by_role('button', name='Clear history', exact=True)
    opener.click()
    dialog = page.get_by_role('dialog')
    expect(dialog).to_be_focused()
    page.keyboard.press('Tab')
    expect(dialog.get_by_role('button', name='Cancel')).to_be_focused()
    page.keyboard.press('Shift+Tab')
    expect(dialog.get_by_role('button', name='Clear history', exact=True)).to_be_focused()
    page.screenshot(path=str(out / 'confirm.png'))
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)
    expect(opener).to_be_focused()


def reader_focus(page, url, out):
    page.goto(url + '/read/u0?work=w0&track=t0')
    page.get_by_role('button', name='Reader settings', exact=True).click()
    dialog = page.get_by_role('dialog')
    radio = dialog.get_by_role('radio', name='Single page', exact=True)
    radio.click()
    expect(radio).to_be_checked()
    expect(radio).to_be_focused()
    for _ in range(20):
        page.keyboard.press('Tab')
        assert page.evaluate("!!document.activeElement.closest('[role=dialog],dialog')"), 'Reader focus escaped'
    page.screenshot(path=str(out / 'reader-settings.png'))
    page.keyboard.press('Escape')
    expect(dialog).to_have_count(0)


def import_current_file(page, url, out):
    review = dict(upload_id='A', format='pdf', suggested_title='First book', language='en',
                  page_count=4, warnings=[], suggestions=[])
    def upload(route):
        if 'bad.pdf' in route.request.url:
            return route.fulfill(status=422, json={'error': {'message': 'Invalid PDF'}})
        return route.fulfill(json=review)
    page.route(url + '/api/import/uploads?*', upload)
    page.goto(url + '/settings/storage')
    choose = page.locator('input[type=file]')
    choose.set_input_files(dict(name='first.pdf', mimeType='application/pdf', buffer=b'fixture'))
    expect(page.get_by_role('button', name='Import', exact=True)).to_be_enabled()
    choose.set_input_files(dict(name='bad.pdf', mimeType='application/pdf', buffer=b'broken'))
    expect(page.get_by_role('alert')).to_have_text('Invalid PDF')
    expect(page.locator('.import__review')).to_have_count(0)
    choose.scroll_into_view_if_needed()
    page.screenshot(path=str(out / 'import-rejected.png'))


def search_history_and_failure(page, url, out):
    state = {'mode': 'complete', 'requests': 0}
    def search(route):
        state['requests'] += 1
        if state['mode'] == 'fail':
            return route.fulfill(status=503, json={'error': {'message': 'Unavailable'}})
        stage = state['mode']
        update = dict(stage=stage, results=results(7), source_status={}, sources_total=1,
                      sources_done=1 if stage == 'complete' else 0, sources_failed=0)
        route.fulfill(content_type='text/event-stream', body=f'event: {stage}\ndata: {json.dumps(update)}\n\n')
    page.route(url + '/api/search?*', search)
    page.goto(url + '/search')
    box = page.get_by_role('searchbox')
    box.fill('book'); box.press('Enter')
    expect(page.locator('.workcard')).to_have_count(7)
    assert '?q=book' in page.url
    page.locator('.workcard').first.click()
    expect(page.locator('.work__header')).to_be_visible()
    page.go_back()
    expect(box).to_have_value('book')
    expect(page.locator('.workcard')).to_have_count(7)
    page.go_forward()
    expect(page.locator('.work__header')).to_be_visible()
    page.go_back(); page.reload()
    expect(box).to_have_value('book')
    expect(page.locator('.workcard')).to_have_count(7)
    before = state['requests']
    with page.expect_response(lambda response: '/api/search?' in response.url):
        box.press('Enter')
    expect(page.locator('.workcard')).to_have_count(7)
    assert state['requests'] > before
    state['mode'] = 'fail'
    box.press('Enter')
    expect(page.get_by_role('alert')).to_be_visible()
    state['mode'] = 'local'
    page.get_by_role('button', name='Try again', exact=True).click()
    expect(page.locator('.workcard')).to_have_count(7)
    expect(page.get_by_role('alert')).to_be_visible()
    page.screenshot(path=str(out / 'search-interrupted.png'))
    state['mode'] = 'complete'
    page.get_by_role('button', name='Try again', exact=True).click()
    expect(page.get_by_role('alert')).to_have_count(0)
    expect(page.locator('.workcard')).to_have_count(7)


def settings_recovery(page, url, out):
    download = dict(auto_download=dict(enabled=False, mode='current', read_ahead=5, threshold=.12),
                    keep_partial_on_cancel=False, extraction=dict(method=None, mode='preferred_ask', fallback_order=[]))
    state = {'failed': True}
    page.route(url + '/api/downloads/settings', lambda r: r.fulfill(status=503, json={'error': {'message': 'Unavailable'}})
               if state['failed'] else r.fulfill(json=download))
    page.goto(url + '/settings/downloads')
    expect(page.get_by_role('alert')).to_have_text('Unavailable')
    state['failed'] = False
    page.get_by_role('button', name='Try again', exact=True).click()
    expect(page.get_by_role('checkbox', name='Download while reading', exact=False)).to_be_visible()
    settings = dict(auto_mark_read_threshold=.97, smart_controls_hide_after_ms=3000,
                    remember_per_work=True, preload_next=7, preload_previous=4)
    writes = []
    state['failed'] = True
    def reader(route):
        if route.request.method == 'POST':
            writes.append(route.request.post_data_json)
            if state['failed']:
                return route.fulfill(status=503, json={'error': {'message': 'Disk unavailable'}})
            settings.update(route.request.post_data_json)
        route.fulfill(json=settings)
    page.route(url + '/api/reader/settings', reader)
    page.goto(url + '/settings/reader')
    page.locator('.panel__advanced button').click()
    threshold = page.get_by_role('spinbutton', name='Count a unit as read at (%)')
    threshold.fill('101'); threshold.press('Tab')
    expect(threshold).to_have_attribute('aria-invalid', 'true')
    assert writes == []
    threshold.fill('90'); threshold.press('Tab')
    expect(page.get_by_role('alert')).to_contain_text('Not saved. Disk unavailable')
    expect(threshold).to_have_value('90')
    threshold.scroll_into_view_if_needed()
    page.screenshot(path=str(out / 'settings-unsaved.png'))
    state['failed'] = False
    page.get_by_role('button', name='Try again', exact=True).click()
    expect(page.get_by_role('alert')).to_have_count(0)
    expect(threshold).to_have_value('90')
    assert settings['auto_mark_read_threshold'] == .9


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    parser.add_argument('--screenshots', default='/tmp/oneshelf-ux-verification')
    args = parser.parse_args()
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for check in [modal_keyboard, removal_keyboard, confirm_keyboard, reader_focus, import_current_file, search_history_and_failure, settings_recovery]:
            page = browser.new_page(viewport={'width':390, 'height':844}, reduced_motion='reduce')
            page.set_default_timeout(7000)
            page.route(args.url + '/api/**', lambda r: fixture(r, 7))
            try:
                check(page, args.url, out)
                print('PASS', check.__name__, flush=True)
            except Exception as error:
                failures.append(f'{check.__name__}: {error}\n{traceback.format_exc()}')
            finally:
                page.close()
        browser.close()
    for failure in failures:
        print('FAIL', failure)
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
