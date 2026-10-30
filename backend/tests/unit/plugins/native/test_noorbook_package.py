import asyncio
import copy
import pytest
from oneshelf.plugins.package import PackageError, load_package
from oneshelf.plugins.runtime import run_packaged_tests
from tests.fixtures.osp import build_osp
from tests.unit.plugins.native.test_noorbook import work_html

MANIFEST = {'schema':'oneshelf.osp/1','id':'oneshelf.noorbook','name':'Noor Book','version':'1.0.0',
            'api':'1.3','native_profile':'noorbook','capabilities':['work','catalog','reader'],
            'network':{'domains':['www.noor-book.com']}, 'browser':{'capabilities':['reader']}}
SOURCE = {'base_url':'https://www.noor-book.com','rate_limit':{'concurrency':2,'requests_per_minute':120}}
TESTS = {'cases':[{'capability':'work','inputs':{'listing_key':'/en/ebook-test-pdf'},
                  'fixtures':[{'url':'https://www.noor-book.com/en/ebook-test-pdf','file':'fixtures/book.html'}],
                  'expect':{'first':{'title':'White Nights','language':'ar'}}},
                 {'capability':'catalog','inputs':{'listing_key':'/en/ebook-test-pdf'},
                  'fixtures':[{'url':'https://www.noor-book.com/en/ebook-test-pdf','file':'fixtures/book.html'}],
                  'expect':{'min_items':1,'complete':True,'first':{'unit_key':'a'*32+':0'}}}]}


def package(tmp_path, manifest=None, source=None, recipes=None):
    return load_package(build_osp(tmp_path/'native.osp', manifest=manifest or MANIFEST,
        source=source or SOURCE, recipes=recipes or {}, tests=TESTS,
        extra_files={'tests/fixtures/book.html':work_html()}))


def test_reviewed_profile_has_visible_permissions_and_runs_real_offline_parser(tmp_path):
    pkg=package(tmp_path)
    assert {'native:noorbook','browser:reader','network:resolver:dns.google'} <= pkg.permissions
    assert pkg.recipes == {}
    report=asyncio.run(run_packaged_tests(pkg))
    assert report.passed, report.failures
    assert report.cases==2


@pytest.mark.parametrize('update', [
    {'id':'example.fake'}, {'api':'1.2'}, {'network':{'domains':['attacker.test']}},
    {'network':{'domains':['www.noor-book.com','attacker.test']}},
    {'network':{'domains':['www.noor-book.com'],'allow_http':True}},
    {'network':{'domains':['www.noor-book.com'],'cdn_domains':['attacker.test']}},
    {'capabilities':['work','catalog','reader','downloads']}, {'browser':{'capabilities':[]}},
    {'auth':{'login_url':'https://www.noor-book.com/login','session_domains':['www.noor-book.com']}},
])
def test_native_profile_cannot_widen_reviewed_contract(tmp_path, update):
    with pytest.raises(PackageError): package(tmp_path,{**MANIFEST,**update})


def test_browser_child_requests_have_a_source_slot(tmp_path):
    with pytest.raises(PackageError):
        package(tmp_path,source={**SOURCE,'rate_limit':{'concurrency':1}})


def test_no_silent_native_dispatch_by_id(tmp_path):
    manifest=copy.deepcopy(MANIFEST)
    del manifest['native_profile']
    with pytest.raises(PackageError,match='recipe'): package(tmp_path,manifest)
