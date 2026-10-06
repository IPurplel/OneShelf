"""Text reading units end to end against the Test Source run as a text source (plugin API 1.2).

Download Missing stores the source's own text as a validated `text` container — sanitised, never an
EPUB (Master §27, §34.4; INV-16, INV-17) — and the reader serves it locally or online.
"""
import asyncio
import zipfile
from types import SimpleNamespace

import pytest

from oneshelf.api.library import reader_context, reader_text
from oneshelf.integrity.validators import validate
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.package import load_package
from oneshelf.reader.service import ReaderService
from oneshelf.text.container import TEXT_MIMETYPE, open_text_container
from testsource.build import build_package
from tests.integration.downloads.conftest import run


@pytest.fixture
def plugins(db, tmp_path):
    manager = PluginManager(db, store_dir=tmp_path / "app" / "plugins")
    path = build_package(tmp_path / "ts-text.osp", text=True)
    asyncio.run(manager.install_file(path, approved_permissions=load_package(path).permissions))
    return manager


def reader_for(env):
    return ReaderService(env.db, env.service, cache=None)


def request_for(reader):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(services=SimpleNamespace(reader=reader))))


def test_a_text_unit_downloads_into_a_validated_text_container(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("novel", "A Quiet Novel", content_type="novel")
            batch = env.engine.enqueue([env.unit_id("nov-1"), env.unit_id("nov-2")])
            report = await env.engine.run_until_idle()
            return report, env.job_rows(batch), env.assets(), env.files()

    report, jobs, assets, files = run(scenario())
    assert report.completed == 2 and {j["state"] for j in jobs} == {"COMPLETED"}
    assert {a["format"] for a in assets} == {"text"} and {a["integrity"] for a in assets} == {"ok"}
    assert all(f.suffix == ".ostext" and f.parts[-5] == "Books" for f in files)
    result = validate(files[0])
    assert result.ok and result.format == "text" and result.page_count == assets[0]["page_count"]
    with zipfile.ZipFile(files[0]) as z:
        assert z.read("mimetype") == TEXT_MIMETYPE and not any(n.endswith((".opf", ".xhtml")) for n in z.namelist())
    unit = open_text_container(files[0])
    markup = "".join(s.html for s in unit.sections)
    assert "The lamp was still burning" in markup and unit.sections[0].title == "Chapter 1"
    for hostile in ("<script", "onclick", "javascript:", "<iframe", "document.cookie"):
        assert hostile not in markup
    assert 'href="http://testsource.example/work/novel"' in markup     # relative links resolved at the source


def test_text_with_nothing_left_after_sanitising_is_never_stored(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("novel", "A Quiet Novel", content_type="novel")
            batch = env.engine.enqueue([env.unit_id("nov-empty")])
            report = await env.engine.run_until_idle()
            return report, env.job_rows(batch)[0], env.assets(), env.files()

    report, job, assets, files = run(scenario())
    assert report.failed == 1 and job["state"] == "FAILED"
    assert assets == [] and files == []


def test_a_crash_after_sections_recovers_without_duplicates(environment):
    class Crash(BaseException):
        pass

    def fault(point):
        if point == "after_text_sections":
            raise Crash(point)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("novel", "A Quiet Novel", content_type="novel")
            batch = env.engine.enqueue([env.unit_id("nov-3")])
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            env.engine.fault = lambda _point: None
            recovered = await env.engine.recover()
            report = await env.engine.run_until_idle()
            return recovered, report, env.job_rows(batch)[0], env.assets(), env.files()

    recovered, report, job, assets, files = run(scenario())
    assert recovered == 1 and report.completed == 1 and job["state"] == "COMPLETED"
    assert len(assets) == 1 and len(files) == 1


def test_the_reader_serves_text_online_then_from_the_download(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("novel", "A Quiet Novel", content_type="novel")
            reader = reader_for(env)
            unit_id = env.unit_id("nov-1")
            before = await reader_context(request_for(reader), unit_id)
            online = await reader_text(request_for(reader), unit_id)
            env.engine.enqueue([unit_id])
            await env.engine.run_until_idle()
            after = await reader_context(request_for(reader), unit_id)
            local = await reader_text(request_for(reader), unit_id)
            return before, online, after, local

    before, online, after, local = run(scenario())
    assert before["kind"] == "text" and before["formats"] == []
    assert after["kind"] == "text" and after["formats"] == ["text"]
    import json
    online_body, local_body = json.loads(online.body), json.loads(local.body)
    assert online_body["origin"] == "online" and local_body["origin"] == "local"
    assert online_body["sections"] == local_body["sections"]
    assert online_body["direction"] == "ltr" and online_body["language"] == "en"
    assert online.headers["content-security-policy"] == "sandbox; default-src 'none'"
    assert online.headers["x-content-type-options"] == "nosniff"


def test_arabic_text_runs_right_to_left_whatever_the_interface_language(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("riwaya", "رواية هادئة", content_type="novel", language="ar")
            return await reader_text(request_for(reader_for(env)), env.unit_id("rw-1"))

    import json
    body = json.loads(run(scenario()).body)
    assert body["direction"] == "rtl" and body["language"] == "ar"
    assert "كان المصباح ما يزال مضاءً" in body["sections"][0]["html"]


def test_image_pages_are_refused_for_a_text_unit(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("novel", "A Quiet Novel", content_type="novel")
            with pytest.raises(ValueError, match="is text"):
                await reader_for(env).pages(env.unit_id("nov-1"))

    run(scenario())
