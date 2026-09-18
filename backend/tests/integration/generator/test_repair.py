"""Master §12.3: Repair Existing Adapter — diff, validate, then atomic activation or rollback."""
import asyncio

import pytest

from oneshelf.generator.discovery import discover
from oneshelf.generator.draft import build_draft, write_package
from oneshelf.generator.repair import RepairError, diagnose, repair
from oneshelf.plugins.package import load_package
from testsource.server import HOST, TestSourceServer


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 90))


async def generate(tmp_path, server, name="generated.osp"):
    site = await discover(f"http://{HOST}/gen/search?q=a", dev_hosts=server.hosts(), allow_http=True)
    return load_package(write_package(build_draft(site, name="Generated Test Source"), tmp_path / name))


async def set_markup(server, version: int):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.post(f"http://127.0.0.1:{server.port}/__control",
                                json={"markup_version": version}) as response:
            assert response.status == 200


def test_a_healthy_adapter_reports_nothing_to_repair(tmp_path):
    async def go():
        async with TestSourceServer() as server:
            package = await generate(tmp_path, server)
            return await diagnose(package, dev_hosts=server.hosts(), allow_http=True)
    report = run(go())
    assert report.broken == [] and report.healthy


def test_changed_selectors_are_detected_diffed_and_validated_before_replacing(tmp_path):
    async def go():
        async with TestSourceServer() as server:
            package = await generate(tmp_path, server)
            await set_markup(server, 2)                       # the site redesigns its chapter list and reader
            before = await diagnose(package, dev_hosts=server.hosts(), allow_http=True)
            outcome = await repair(package, dev_hosts=server.hosts(), allow_http=True,
                                   destination=tmp_path / "repaired.osp")
            after = await diagnose(load_package(outcome.path), dev_hosts=server.hosts(), allow_http=True)
            return before, outcome, after
    before, outcome, after = run(go())

    assert before.broken == ["catalog"]                        # the chapter list no longer matches
    assert "reader" not in before.checked                      # without a unit there is nothing honest to probe
    assert outcome.validated is True and outcome.path.exists()
    assert outcome.version == "0.1.1"                          # a repair is a new version, never an edit in place
    changes = {change.capability for change in outcome.changes}
    assert changes == {"catalog", "reader"}
    assert any("li.chapter" in change.before and "li.ch-row" in change.after for change in outcome.changes)
    assert after.broken == []                                  # the repaired adapter works against the new markup


def test_a_repair_that_cannot_be_validated_is_refused(tmp_path):
    """If discovery cannot map the site any more, nothing is produced to activate."""
    async def go():
        async with TestSourceServer() as server:
            package = await generate(tmp_path, server)
            return await repair(package, dev_hosts=server.hosts(), allow_http=True,
                                destination=tmp_path / "nope.osp", start_url=f"http://{HOST}/js-search?q=a")
    with pytest.raises(RepairError):
        run(go())
    assert not (tmp_path / "nope.osp").exists()
