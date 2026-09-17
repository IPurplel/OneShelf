"""Master §16–§17, §14, §39; INV-16, INV-17, INV-23: durable downloads, recovery, contracts."""
import zipfile
from pathlib import Path

import pytest

from tests.integration.downloads.conftest import TS, cbz_pages, run


def test_sequential_download_produces_verified_cbz_assets(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1"), env.unit_id("irr-2")])
            report = await env.engine.run_until_idle()
            return env, batch, report, env.job_rows(batch), env.assets(), env.files()

    env, batch, report, jobs, assets, files = run(scenario())
    assert report.completed == 2 and report.failed == 0
    assert {j["state"] for j in jobs} == {"COMPLETED"}
    assert len(assets) == 2 and {a["integrity"] for a in assets} == {"ok"}
    assert {a["page_count"] for a in assets} == {3} and {a["format"] for a in assets} == {"cbz"}
    assert len(files) == 2 and all(f.suffix == ".cbz" for f in files)
    assert len(cbz_pages(files[0])) == 3
    with zipfile.ZipFile(files[0]) as z:
        assert "ComicInfo.xml" in z.namelist()
    assert env.engine.batch(batch)["state"] == "completed"


def test_direct_method_downloads_the_original_file(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            batch = env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            await env.engine.run_until_idle()
            return env.assets(), env.files()

    assets, files = run(scenario())
    assert len(assets) == 1 and assets[0]["format"] == "pdf" and assets[0]["integrity"] == "ok"
    assert files[0].suffix == ".pdf"
    from oneshelf.integrity.validators import validate
    assert validate(files[0]).page_count == 1  # version 1 of the source file, byte-for-byte


@pytest.mark.parametrize("unit_key", ["bad-html", "bad-corrupt"])
def test_invalid_media_never_becomes_downloaded_content(environment, unit_key):
    async def scenario():
        async with environment() as env:
            await env.add_work("broken", "Broken Media")
            batch = env.engine.enqueue([env.unit_id(unit_key)])
            report = await env.engine.run_until_idle()
            return env, report, env.job_rows(batch)

    env, report, jobs = run(scenario())
    assert report.failed == 1 and jobs[0]["state"] == "FAILED"
    assert jobs[0]["error_category"] == "media_invalid"
    assert env.assets() == [] and env.files() == []


def test_rate_limited_media_waits_then_completes(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("broken", "Broken Media")
            await env.control(rate_limit_remaining=1, retry_after=1)
            batch = env.engine.enqueue([env.unit_id("bad-limited")])
            await env.engine.run_once()
            waiting = env.job_rows(batch)[0]
            report = await env.engine.run_until_idle(max_seconds=20)
            return waiting, report, env.job_rows(batch)[0], env.assets()

    waiting, report, final, assets = run(scenario())
    assert waiting["state"] == "WAITING_FOR_RATE_LIMIT" and waiting["next_attempt_at"] is not None
    assert final["state"] == "COMPLETED" and report.completed == 1 and len(assets) == 1


def test_auth_failure_waits_for_session_and_resumes_after_connect(environment):
    async def scenario():
        async with environment() as env:
            await env.connect_session()
            await env.add_work("private", "Members Only")
            env.sessions.disconnect(TS)
            batch = env.engine.enqueue([env.unit_id("priv-1")])
            await env.engine.run_once()
            waiting = env.job_rows(batch)[0]
            await env.connect_session()
            report = await env.engine.run_until_idle()
            return waiting, report, env.job_rows(batch)[0]

    waiting, report, final = run(scenario())
    assert waiting["state"] == "WAITING_FOR_SESSION"
    assert final["state"] == "COMPLETED" and report.completed == 1


def test_partial_batch_success_and_retry_all_failed(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            await env.add_work("broken", "Broken Media")
            batch = env.engine.enqueue([env.unit_id("irr-1"), env.unit_id("bad-corrupt"), env.unit_id("irr-2")])
            await env.engine.run_until_idle()
            state = env.engine.batch(batch)
            requeued = env.engine.retry_all_failed(batch)
            queued = [j["state"] for j in env.job_rows(batch)]
            await env.engine.run_until_idle()
            return env, state, requeued, queued, env.engine.batch(batch)

    env, state, requeued, queued, final = run(scenario())
    assert state["state"] == "completed_with_issues" and state["completed"] == 2 and state["failed"] == 1
    assert requeued == 1 and sorted(queued) == ["COMPLETED", "COMPLETED", "QUEUED"]
    assert final["completed"] == 2 and final["failed"] == 1
    assert len(env.assets()) == 2  # successful units survived the failure of another


def test_crash_during_download_recovers_without_duplicates(environment):
    class Crash(BaseException):
        pass

    def fault(point):
        if point == "after_pages_downloaded":
            raise Crash(point)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            interrupted = env.job_rows(batch)[0]["state"]
            env.engine.fault = lambda _point: None
            recovered = await env.engine.recover()
            report = await env.engine.run_until_idle()
            return interrupted, recovered, report, env.job_rows(batch)[0], env.assets(), env.files()

    interrupted, recovered, report, final, assets, files = run(scenario())
    assert interrupted == "DOWNLOADING" and recovered == 1
    assert final["state"] == "COMPLETED" and report.completed == 1
    assert len(assets) == 1 and len(files) == 1


def test_resume_skips_pages_that_are_already_valid(environment):
    class Crash(BaseException):
        pass

    state = {"pages": 0}

    def fault(point):
        if point == "page_downloaded":
            state["pages"] += 1
            if state["pages"] == 2:
                raise Crash(point)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.engine.enqueue([env.unit_id("irr-1")])
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            first_pass = len(env.requests_for("/img/irr-1/1.png"))
            env.engine.fault = lambda _point: None
            await env.engine.recover()
            await env.engine.run_until_idle()
            return first_pass, len(env.requests_for("/img/irr-1/1.png")), env.files()

    first_pass, after_resume, files = run(scenario())
    assert first_pass == 1 and after_resume == 1  # page 1 was not fetched again
    assert len(files) == 1 and len(cbz_pages(files[0])) == 3


def test_changed_validator_restarts_the_file_instead_of_splicing(environment):
    class Crash(BaseException):
        pass

    def fault(point):
        if point == "file_partially_downloaded":
            raise Crash(point)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("manual", "The Manual", content_type="book")
            env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            await env.control(file_version=2)
            env.engine.fault = lambda _point: None
            await env.engine.recover()
            await env.engine.run_until_idle()
            return env.files()

    files = run(scenario())
    from oneshelf.integrity.validators import validate
    result = validate(files[0])
    # a clean restart under the new validator: the file parses and is entirely version 2 (two pages)
    assert result.ok and result.page_count == 2


def test_cancel_removes_the_job_and_its_partial_by_default(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1"), env.unit_id("irr-2")])
            job_id = env.job_rows(batch)[0]["id"]
            env.engine.cancel_job(job_id)
            await env.engine.run_until_idle()
            staging = list((Path(env.root.path) / ".oneshelf" / "staging").iterdir())
            return env.job_rows(batch), staging, env.assets()

    jobs, staging, assets = run(scenario())
    assert [j["state"] for j in jobs] == ["CANCELED", "COMPLETED"]
    assert staging == [] and len(assets) == 1


def test_pause_resume_and_reorder(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            units = [env.unit_id("irr-1"), env.unit_id("irr-2"), env.unit_id("irr-3")]
            batch = env.engine.enqueue(units)
            env.engine.pause(batch)
            paused_report = await env.engine.run_until_idle()
            order = [j["id"] for j in env.job_rows(batch)]
            env.engine.reorder(batch, [order[2], order[0], order[1]])
            reordered = [j["reading_unit_id"] for j in env.job_rows(batch)]
            env.engine.resume(batch)
            report = await env.engine.run_until_idle()
            return paused_report, units, reordered, report

    paused_report, units, reordered, report = run(scenario())
    assert paused_report.completed == 0
    assert reordered == [units[2], units[0], units[1]]
    assert report.completed == 3


def test_history_records_methods_and_clearing_keeps_content_and_progress(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            env.db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, updated_at)"
                           " VALUES (?, 'partial', 0.5, '2026-09-17T00:00:00+00:00')", (unit,))
            history = env.db.execute("SELECT * FROM download_history").fetchall()
            removed = env.engine.clear_history()
            return history, removed, env.assets(), env.files(), env.db.execute(
                "SELECT count(*) FROM reading_state").fetchone()[0]

    history, removed, assets, files, progress = run(scenario())
    assert len(history) == 1 and history[0]["outcome"] == "completed"
    assert history[0]["initial_method"] == history[0]["final_method"] == "html_api"
    assert removed == 1 and len(assets) == 1 and len(files) == 1 and progress == 1


def test_running_again_after_completion_does_nothing(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.engine.enqueue([env.unit_id("irr-1")])
            await env.engine.run_until_idle()
            before = len(env.server.scenario.request_log)
            report = await env.engine.run_until_idle()
            return report, before, len(env.server.scenario.request_log), env.assets()

    report, before, after, assets = run(scenario())
    assert report.completed == 0 and before == after and len(assets) == 1


def test_enqueueing_a_unit_that_is_already_downloaded_is_skipped(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            second = env.engine.enqueue([unit])
            report = await env.engine.run_until_idle()
            return env.engine.batch(second), report, env.assets()

    batch, report, assets = run(scenario())
    assert batch["skipped"] == 1 and report.completed == 0 and len(assets) == 1
