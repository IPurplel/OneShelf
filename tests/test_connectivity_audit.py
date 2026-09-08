"""The audit must retain a result for every host despite endpoint failures."""
import json

import httpx

from scratchpad import audit_connectivity as audit


async def test_endpoint_failure_does_not_erase_other_hosts(tmp_path):
    urls = ['https://good.test', 'https://slow.test', 'https://invalid.test']

    def endpoint(request):
        url = json.loads(request.content)['url']
        if url == urls[1]:
            raise httpx.ReadTimeout('endpoint timeout', request=request)
        if url == urls[2]:
            return httpx.Response(200, text='not JSON')
        return httpx.Response(200, json={'url': url, 'reachable': True, 'kind': 'ok', 'status': 200})

    async with httpx.AsyncClient(transport=httpx.MockTransport(endpoint), base_url='http://local.test') as client:
        results = [await audit.probe_site(client, url) for url in urls]
    assert results[0]['kind'] == 'ok'
    assert results[1]['kind'] == 'audit_error'
    assert results[2]['kind'] == 'audit_error'
    assert [r['url'] for r in results] == urls

    first, second = tmp_path / 'run1', tmp_path / 'run2'
    first.mkdir()
    second.mkdir()
    audit.save_report(first, {'results': results})
    audit.save_report(second, {'results': []})
    assert json.loads((first / 'connectivity.json').read_text())['results'] == results
