"""Call the real connectivity endpoint on an isolated ephemeral HTTP server.

Reports are retained per run under .state/connectivity/run-*/connectivity.json.
Capture stdout for a separate transcript; no earlier report is overwritten.
"""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scratchpad.verify_dl import create_run_settings
from app import main
from app.config import settings, CONFIG_FILE
from app.adapters import select
import httpx
import uvicorn


def save_report(run_dir, output):
    path = run_dir / 'connectivity.json'
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    return path


async def probe_site(client, url):
    """An endpoint/transport failure is an audit result, not a site verdict."""
    try:
        response = await client.post('/api/connectivity', json={'url': url})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or 'kind' not in result:
            raise ValueError('Unexpected connectivity response')
    except Exception as exc:
        result = {'url': url, 'reachable': False, 'kind': 'audit_error',
                  'detail': f'{type(exc).__name__}: {exc}'}
    result.update(adapter_guess=select(url).id, checked=datetime.now(timezone.utc).isoformat())
    return result


async def supplement(url, isolated, user_agent):
    # The endpoint does not expose redirects or HTML. A labelled second GET
    # captures those with the same route and UA; it does not replace its verdict.
    options = {'timeout': 20, 'follow_redirects': True}
    if isolated.proxy_config is not None:
        options['proxy'] = isolated.proxy_config.for_httpx()
    try:
        async with httpx.AsyncClient(**options) as probe:
            page = await probe.get(url, headers={'User-Agent': user_agent})
            return {
                'final_url': str(page.url), 'status': page.status_code,
                'redirects': [{'url': str(h.url), 'status': h.status_code,
                               'location': h.headers.get('location')} for h in page.history],
                'adapter_fingerprint': select(str(page.url), page.text).id,
            }
    except Exception as exc:
        return {'error': f'{type(exc).__name__}: {exc}'}


async def audit():
    isolated, run_dir = create_run_settings(settings, ROOT / '.state' / 'connectivity')
    isolated.headless = 'true'
    isolated.assisted_solve = False
    original_settings = main.settings
    main.settings = isolated
    sock = socket.socket()
    task = None
    output = {'checked': datetime.now(timezone.utc).isoformat(), 'run_dir': str(run_dir),
              'config_file': str(CONFIG_FILE.resolve()),
              'desync_enabled': isolated.desync_enabled, 'desync_browser': isolated.desync_browser,
              'configured_urls': list(isolated.search_sites), 'results': []}
    try:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(main.app, log_level='warning'))
        task = asyncio.create_task(server.serve(sockets=[sock]))
        async with asyncio.timeout(30):
            while not server.started:
                if task.done():
                    await task
                    raise RuntimeError('Server did not start')
                await asyncio.sleep(0.05)
        semaphore = asyncio.Semaphore(4)
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{port}', timeout=35, trust_env=False) as client:
            async def one(url):
                async with semaphore:
                    result = await probe_site(client, url)
                    output['results'].append(result)
                    save_report(run_dir, output)
                    if result.get('reachable'):
                        result['supplemental'] = await supplement(url, isolated, main.state['sessions'].user_agent)
                    save_report(run_dir, output)
                    print(json.dumps(result, ensure_ascii=False), flush=True)
            async with asyncio.TaskGroup() as group:
                for url in isolated.search_sites:
                    group.create_task(one(url))
        order = {url: index for index, url in enumerate(isolated.search_sites)}
        output['results'].sort(key=lambda item: order[item['url']])
    except Exception as exc:
        output['error'] = f'{type(exc).__name__}: {exc}'
    finally:
        path = save_report(run_dir, output)
        print(f'Evidence: {path}', flush=True)
        try:
            if task is not None:
                server.should_exit = True
                await task
        finally:
            sock.close()
            main.settings = original_settings
    return 1 if output.get('error') or any(r['kind'] == 'audit_error' for r in output['results']) else 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(audit()))
