"""Real Chromium layout regressions. Run with backend/.venv/bin/python; see verification doc."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import expect, sync_playwright

WIDTHS = (390, 768, 899, 900, 1440, 1920, 2560)
COVER = '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="214"><rect width="150" height="214" fill="#49654b"/><text x="18" y="70" fill="#f6eedf" font-size="18">OneShelf</text></svg>'


def items(count):
    return [dict(work_id=f'w{i}', title=(f'Book {i} — A long title from the reading room' if i % 3 else f'كتاب {i} في المكتبة العربية'),
                 cover_url='/api/covers/broken' if i % 4 == 0 else '/api/covers/good', fraction=.42,
                 content_type='manga', added_at='2026-09-25', is_favorite=False, is_pinned=False,
                 completed_at=None, releases_since_completion=0) for i in range(count)]


def results(count):
    return [{**item, 'work_id': item['work_id'] if i % 2 == 0 else None, 'soft': False,
             'availability': {'und': 2}, 'provenance': [dict(source_id=s, listing_key=f'k{i}', language='und',
               title=item['title'], url=f'https://example.test/{i}', cover_url=item['cover_url']) for s in ('alpha', 'beta')]}
            for i, item in enumerate(items(count))]


def fixture(route, count):
    path = urlparse(route.request.url).path
    if path == '/api/events':
        return route.fulfill(content_type='text/event-stream', body='event: hello\ndata: {}\n\n')
    if path.startswith('/api/covers/'):
        return route.fulfill(status=404 if path.endswith('broken') else 200, content_type='image/svg+xml', body='' if path.endswith('broken') else COVER)
    if path.startswith('/api/works/'):
        return route.fulfill(json=dict(
            work=dict(id='w0', title='Reader smoke test', original_title=None, creator=None, description=None,
                      content_type='manga', content_type_source='source', aliases=[]),
            shelf=dict(on_shelf=True, favorite=False, pinned=False, completed=False),
            follow=dict(following=False, preferred_source_id=None, track_id=None, language=None, last_successful_at=None),
            tracks=[dict(id='t0', source_id='local', language='en', kind='local', availability='available', unit_count=1)],
            selected_track_id='t0', continue_unit_id='u0',
            units=[dict(id='u0', title='Chapter One', number='1', unit_type='chapter', volume=None, order=1,
                        release_date=None, availability='available', url=None, downloaded=True, formats=['cbz'],
                        read_state='unread', fraction=0, read_at=None, integrity='ok', is_new=False)]))
    if path == '/api/reader/units/u0/context':
        return route.fulfill(json=dict(work_id='w0', track_id='t0', formats=['cbz']))
    if path == '/api/reader/units/u0/pages':
        return route.fulfill(json=dict(reading_unit_id='u0', pages=[dict(index=1, label='1', url=None)]))
    if path == '/api/reader/units/u0/pages/1':
        return route.fulfill(content_type='image/svg+xml', body=COVER)
    if path.endswith('/progress'):
        return route.fulfill(json=dict(read_state='unread', fraction=0, locator=None, revision=0))
    if path == '/api/reader/settings':
        return route.fulfill(json=dict(auto_mark_read_threshold=.97, smart_controls_hide_after_ms=3000,
                                       remember_per_work=True, preload_next=7, preload_previous=4))
    if path.endswith('/leave') or path.endswith('/engagement'):
        return route.fulfill(json={})
    data = {
        '/api/home': dict(hero={**items(1)[0], 'reason': 'continue_reading', 'cover_url': '/api/covers/good', 'description': 'A quiet corner for your next story.'} if count else None, continue_reading=items(count), trending=results(count), latest=results(count), recently_added=items(count)),
        '/api/shelf': dict(view='all', entries=items(count)),
        '/api/notifications': dict(notifications=[], needs_attention=0),
        '/api/follows': dict(follows=[dict(work_id='w0', track_id='t0', source_id='alpha', language='en',
            state='new_releases', last_attempted_at='2026-09-25T00:00:00Z',
            last_successful_at='2026-09-25T00:00:00Z', unseen_releases=3)]),
        '/api/downloads': dict(batches=[dict(batch_id='b0', state='active', completed=3, failed=1,
            pending=5, canceled=0, skipped=2, counts={})]),
        '/api/sources': dict(sources=[dict(id='alpha', name='Reading Room Library', state='active',
            version='1.0.0', trust_label='official', channel='bundled', capabilities=['search', 'work', 'catalog', 'reader'],
            auth_available=False, session_state='none')]),
        '/api/registry': dict(plugins=[], configured=False),
        '/api/storage': dict(roots=[dict(id='r0', name='Library', path='/library', is_default=True,
            available=True, reason=None, total=500e9, free=120e9, reserve=5e9, state='ok')], missing=0),
    }.get(path)
    if path == '/api/listings/open':
        return route.fulfill(status=503, json={'error': {'code': 'OFFLINE', 'message': 'Source temporarily unavailable'}})
    if path == '/api/search':
        update = dict(stage='complete', results=results(count), source_status={}, sources_total=0, sources_done=0, sources_failed=0)
        return route.fulfill(content_type='text/event-stream', body=f'event: complete\ndata: {json.dumps(update)}\n\n')
    return route.fulfill(status=200 if data is not None else 404, json=data or {})


def geometry(page):
    return page.evaluate('''() => {
      const rect = e => e.getBoundingClientRect();
      const main = document.querySelector('.layout__main'), screen = main.querySelector('.screen');
      const css = getComputedStyle(main);
      return {
        overflow: document.documentElement.scrollWidth - innerWidth,
        available: main.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight),
        width: rect(screen).width, rtl: document.dir === 'rtl',
        shelves: [...document.querySelectorAll('.shelf__case')].map(s => ({
          plank: rect(s.querySelector('.shelf__plank')).top,
          cards: [...s.querySelectorAll('.workcard')].map(c => ({
            cover: rect(c.querySelector('.workcard__cover')).toJSON(),
            caption: rect(c.querySelector('.workcard__caption')).toJSON()
          }))
        }))
      };
    }''')


def check_layout(page):
    page.mouse.move(0, 0)
    page.wait_for_function("[...document.querySelectorAll('.workcard__cover')].every(e => getComputedStyle(e).transform === 'none' || getComputedStyle(e).transform === 'matrix(1, 0, 0, 1, 0, 0)')")
    g = geometry(page)
    assert g['overflow'] <= 1, f"document overflow {g['overflow']}px"
    assert abs(g['width'] - g['available']) <= 1, f"screen {g['width']} vs available {g['available']}"
    for shelf in g['shelves']:
        for card in shelf['cards']:
            cover, caption = card['cover'], card['caption']
            assert abs(cover['bottom'] - shelf['plank']) <= 1, f"cover/plank: {cover['bottom']} vs {shelf['plank']}"
            assert caption['top'] >= shelf['plank'], 'caption above plank'
            assert 95 <= cover['width'] <= 155, f"unreadable/stretched cover {cover['width']}"
            assert cover['height'] >= 145, f"clipped cover {cover['height']}"
            edge = 'right' if g['rtl'] else 'left'
            assert abs(cover[edge] - caption[edge]) <= 1, 'caption in another column'
    for card in page.locator('.search__results .workcard').all():
        cover = card.locator('.workcard__cover').bounding_box()
        caption = card.locator('.workcard__caption').bounding_box()
        assert cover and caption
        assert 145 <= cover['width'] <= 230 and cover['height'] >= 200, 'unreadable Search cover'
        assert caption['y'] >= cover['y'] + cover['height'] - 1, 'Search caption overlaps cover'
        assert abs(caption['x'] - cover['x']) <= 1, 'Search caption in another column'
    return g


def run(args):
    failures = []
    checks = 0
    out = Path(args.screenshots)
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for language in args.languages:
            page = browser.new_page(viewport={'width': 390, 'height': 1000}, reduced_motion='reduce')
            page.add_init_script(f"localStorage.setItem('oneshelf.language', '{language}')")
            state = {'count': 17}
            page.route(f'{args.url}/api/**', lambda route: fixture(route, state['count']))
            for width in args.widths:
                page.set_viewport_size({'width': width, 'height': 1000})
                for path in ('/', '/shelf', '/search', '/following', '/downloads', '/sources', '/settings', '/settings/storage'):
                    state['count'] = 17
                    page.goto(args.url + path)
                    page.wait_for_load_state('networkidle')
                    if path == '/search':
                        page.locator('input[type=search]').fill('book')
                        page.locator('input[type=search]').press('Enter')
                        page.locator('.workcard').first.wait_for()
                    if path in ('/', '/shelf') and width in (390, 1440, 2560):
                        page.screenshot(path=str(out / f'{language}-{width}-{path.strip("/") or "home"}.png'), full_page=True)
                    try:
                        check_layout(page)
                        if path == '/':
                            row = page.locator('.shelf__row').first
                            moved = row.evaluate('''e => { e.scrollLeft = document.dir === 'rtl' ? -10000 : 10000;
                                return { scroll: Math.abs(e.scrollLeft), needed: e.scrollWidth > e.clientWidth }; }''')
                            assert not moved['needed'] or moved['scroll'] > 0, 'shelf does not scroll locally'
                            opener = page.locator('.shelf--recessed button.workcard').first
                            opener.focus()
                            opener.press('Enter')
                            page.get_by_role('dialog').wait_for()
                            check_layout(page)
                            page.keyboard.press('Escape')
                            assert page.get_by_role('dialog').count() == 0
                            expect(opener).to_be_focused()
                            opener.press('Enter')
                            page.locator('.choice__option').first.click()
                            page.get_by_role('alert').wait_for()
                            assert opener.locator('[role=alert]').count() == 1
                            check_layout(page)
                            assert page.locator('.workcard__blank').count() > 0
                        if path == '/search':
                            opener = page.locator('.search__results button.workcard').first
                            opener.focus()
                            opener.press('Enter')
                            page.locator('.choice__option').first.click()
                            page.get_by_role('alert').wait_for()
                            assert opener.locator('[role=alert]').count() == 1
                            check_layout(page)
                        if path == '/shelf':
                            for control in page.locator('.toolbar input, .toolbar select, .toolbar button').all():
                                box = control.bounding_box()
                                assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                            rows = page.locator('.shelf__row')
                            first = rows.first.locator('.workcard__cover').first.bounding_box()
                            last = rows.last.locator('.workcard__cover').first.bounding_box()
                            assert abs(first['width'] - last['width']) <= 1, 'incomplete row stretches'
                            page.locator('.toolbar__end button').last.click()
                            check_layout(page)
                            page.locator('.toolbar__end button').first.click()
                        if path == '/settings' and width < 900:
                            more = page.locator('.bottomnav button')
                            more.click()
                            drawer = page.get_by_role('dialog')
                            expect(drawer).to_be_focused()
                            box = drawer.bounding_box()
                            assert box and box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                            page.keyboard.press('Escape')
                            expect(more).to_be_focused()
                            more.click()
                            drawer.locator('a[href="/downloads"]').click()
                            expect(page.get_by_role('dialog')).to_have_count(0)
                            assert urlparse(page.url).path == '/downloads'
                        checks += 1
                    except AssertionError as exc:
                        failures.append(f'{language} {width} {path}: {exc}')
                # Empty, single and incomplete rows, each at every width and locale.
                for count in (0, 1, 7):
                    state['count'] = count
                    page.goto(args.url + '/shelf')
                    page.wait_for_load_state('networkidle')
                    try:
                        check_layout(page)
                        assert page.locator('.workcard').count() == count
                        checks += 1
                    except AssertionError as exc:
                        failures.append(f'{language} {width} shelf count={count}: {exc}')
            # Resize the mounted shelf, then its container alone (not just the viewport).
            state['count'] = 17
            page.set_viewport_size({'width': 2560, 'height': 1000})
            page.goto(args.url + '/shelf')
            page.wait_for_load_state('networkidle')
            expect(page.locator('.shelf__row').first.locator('.workcard')).to_have_count(12)
            page.set_viewport_size({'width': 390, 'height': 1000})
            expect(page.locator('.shelf__row').first.locator('.workcard')).to_have_count(2)
            check_layout(page)
            page.set_viewport_size({'width': 2560, 'height': 1000})
            page.locator('.shelfview').evaluate("e => e.style.width = '500px'")
            expect(page.locator('.shelf__row').first.locator('.workcard')).to_have_count(3)
            # Empty Home remains usable, and its Import link lands on Storage after reload/history.
            state['count'] = 0
            page.goto(args.url)
            page.locator('.empty').wait_for()
            check_layout(page)
            page.locator('.empty a[href="/settings/storage"]').click()
            expect(page.locator('[role=tab][aria-selected=true]')).to_have_text('Storage' if language == 'en' else 'التخزين')
            page.reload()
            expect(page.locator('[role=tab][aria-selected=true]')).to_have_text('Storage' if language == 'en' else 'التخزين')
            page.locator('[role=tab]').first.click()
            page.go_back()
            expect(page.locator('[role=tab][aria-selected=true]')).to_have_text('Storage' if language == 'en' else 'التخزين')
            page.go_forward()
            expect(page.locator('[role=tab][aria-selected=true]')).to_have_text('General' if language == 'en' else 'عام')
            # Enter and leave the real page reader in both shell modes and locales.
            for reader_width in (390, 1440):
                page.set_viewport_size({'width': reader_width, 'height': 1000})
                page.goto(args.url + '/works/w0')
                page.locator('.work__actions a[href^="/read/"]').click()
                page.locator('[data-testid=reader-stage]').wait_for()
                expect(page.locator('[data-testid=reader-stage] img').first).to_be_visible()
                # Work entry carries context and returns to that Work.
                page.locator('.reader__bar--top a[href="/works/w0?track=t0"]').click()
                page.locator('.work__header').wait_for()
                # Reader routes with work context return to that Work.
                page.goto(args.url + '/read/u0?work=w0')
                page.locator('[data-testid=reader-stage]').wait_for()
                page.locator('.reader__bar--top a[href="/works/w0?track=t0"]').click()
                page.locator('.work__header').wait_for()
            print(f'{language}: viewport matrix, resize, settings history and Reader smoke complete', flush=True)
            page.close()
        browser.close()
    print(f'{checks} layout cases passed; {len(failures)} failed')
    for failure in failures:
        print(failure)
    return bool(failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='http://127.0.0.1:5173')
    parser.add_argument('--widths', nargs='+', type=int, default=WIDTHS)
    parser.add_argument('--languages', nargs='+', choices=('en', 'ar'), default=('en', 'ar'))
    parser.add_argument('--screenshots', default='/tmp/oneshelf-ui-layout')
    raise SystemExit(run(parser.parse_args()))
