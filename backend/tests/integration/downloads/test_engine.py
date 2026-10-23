"""Master §16–§17, §14, §39; INV-16, INV-17, INV-23: durable downloads, recovery, contracts."""
import asyncio
import json
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.downloads.conftest import TS, cbz_pages, run
from testsource.server import png
from oneshelf.search.mapping import MappingService


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


def test_queued_download_does_not_fetch_after_edition_is_unlinked(environment):
    async def scenario():
        async with environment() as env:
            binding = await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            before = len(env.server.scenario.request_log)
            MappingService(env.db).unlink(binding.listing_id)
            report = await env.engine.run_once()
            return report, env.job_rows(batch)[0], env.assets(), env.files(), len(env.server.scenario.request_log) - before

    report, job, assets, files, new_requests = run(scenario())
    assert report.failed == 1 and job["state"] == "FAILED"
    assert job["error_category"] == "source_unlinked"
    assert assets == [] and files == [] and new_requests == 0


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


def test_i81_resume_refetches_a_page_whose_source_url_changed(environment):
    class Crash(BaseException):
        pass

    def fault(point):
        if point == "page_downloaded":
            raise Crash(point)

    changed_page = png(shade=180)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.engine.enqueue([env.unit_id("irr-1")])
            with pytest.raises(Crash):
                await env.engine.run_until_idle()

            original_resources = env.engine._resources
            original_fetch = env.service.fetch_resource_to
            changed_url = "http://cdn.testsource.example/img/irr-1/1.png?revision=2"
            fetched = []

            async def changed_resources(contract, context):
                resources = await original_resources(contract, context)
                resources[0] = replace(resources[0], url=changed_url)
                return resources

            async def changed_fetch(source_id, url, path, **kwargs):
                if url == changed_url:
                    fetched.append(url)
                    Path(path).write_bytes(changed_page)
                    return SimpleNamespace(status=200, headers={}, total=len(changed_page))
                return await original_fetch(source_id, url, path, **kwargs)

            env.engine._resources = changed_resources
            env.service.fetch_resource_to = changed_fetch
            env.engine.fault = lambda _point: None
            await env.engine.recover()
            report = await env.engine.run_until_idle()
            with zipfile.ZipFile(env.files()[0]) as archive:
                saved_page = archive.read("0001.png")
            return report, fetched, saved_page

    report, fetched, saved_page = run(scenario())
    assert report.completed == 1
    assert fetched == ["http://cdn.testsource.example/img/irr-1/1.png?revision=2"]
    assert saved_page == changed_page


def test_i81_resume_discards_stale_manifest_pages_when_source_page_count_shrinks(environment):
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
            assert len(env.engine._manifest(env.job_rows(batch)[0])["pages"]) == 3

            original_resources = env.engine._resources

            async def shorter_resources(contract, context):
                return (await original_resources(contract, context))[:2]

            env.engine._resources = shorter_resources
            env.engine.fault = lambda _point: None
            await env.engine.recover()
            report = await env.engine.run_until_idle()
            return report, env.job_rows(batch)[0], env.assets(), env.files()

    report, job, assets, files = run(scenario())
    assert report.completed == 1 and job["state"] == "COMPLETED"
    assert assets[0]["page_count"] == 2
    assert len(cbz_pages(files[0])) == 2


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


def test_the_queue_survives_a_restart_and_a_new_engine_finishes_it(environment):
    """§53 queue persistence: the queue lives in SQLite, so a fresh process picks it up (§17, INV-16)."""
    class Crash(BaseException):
        pass

    async def interrupted():
        async with environment(fault=lambda point: (_ for _ in ()).throw(Crash(point))
                               if point == "after_pages_downloaded" else None) as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            return batch, env.job_rows(batch)[0]["state"]

    async def after_restart(batch):
        # A new SourceService, governor and DownloadEngine: nothing is carried over in memory.
        async with environment() as env:
            recovered = await env.engine.recover()
            report = await env.engine.run_until_idle()
            return recovered, report, env.job_rows(batch)[0], env.assets(), env.files()

    batch, state = run(interrupted())
    assert state == "DOWNLOADING"

    recovered, report, final, assets, files = run(after_restart(batch))
    assert recovered == 1 and report.completed == 1
    assert final["state"] == "COMPLETED"
    assert len(assets) == 1 and len(files) == 1


def test_repair_downloads_a_broken_copy_again_through_the_normal_pipeline(environment):
    """§16.5, §26.21: repair is the same contract, method and validated commit as any download."""
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            first = env.files()

            # Asking again changes nothing: a sound copy is left alone.
            again = env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            skipped_only = env.engine.batch(again)["skipped"] == 1

            # The copy goes bad the way copies do.
            for path in first:
                path.unlink()
            env.db.execute("UPDATE assets SET integrity = 'missing_local_file'")
            assert env.files() == [], f"precondition: the copy is gone, but found {env.files()}"

            batch = env.engine.enqueue([unit], repair=True)
            report = await env.engine.run_until_idle()
            return skipped_only, env.engine.batch(batch), report, env.files(), env.assets()

    skipped_only, batch, report, files, assets = run(scenario())
    assert skipped_only, "a sound copy should not be downloaded again"
    assert batch["skipped"] == 0 and report.completed == 1
    assert len(files) == 1 and len(assets) == 1
    assert {a["integrity"] for a in assets} == {"ok"}


# -- I-95 (BE-005), I-106 (BE-016): no job is ever stranded in an active state -------------------------------

from oneshelf.downloads import engine as engine_module
from oneshelf.downloads.engine import ACTIVE_STATES, NoStorageLocation
from oneshelf.integrity.validators import ValidationResult
from oneshelf.notifications.service import NotificationService


def _notifications(db):
    return [dict(r) for r in db.execute("SELECT dedupe_key, payload_json FROM notifications ORDER BY created_at")]


def test_i95_a_download_without_any_storage_location_is_refused_at_enqueue(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.db.execute("DELETE FROM storage_roots")
            with pytest.raises(NoStorageLocation):
                env.engine.enqueue([env.unit_id("irr-1")])
            return env.db.execute("SELECT count(*) FROM download_jobs").fetchone()[0]

    assert run(scenario()) == 0


def test_i95_an_unexpected_error_fails_the_job_instead_of_stranding_it(environment, monkeypatch):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.engine.notifications = NotificationService(env.db)

            async def broken(*_args, **_kwargs):
                raise RuntimeError("an error nobody planned for")

            monkeypatch.setattr(env.engine, "_resources", broken)
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            report = await env.engine.run_until_idle(max_seconds=40)
            history = env.db.execute("SELECT outcome, error_category FROM download_history").fetchall()
            return report, env.job_rows(batch)[0], [tuple(h) for h in history], _notifications(env.db)

    report, job, history, notes = run(scenario(), timeout=90)
    assert job["state"] == "FAILED" and job["error_category"] == "internal_error"
    assert report.failed == 1 and history == [("failed", "internal_error")]
    assert len(notes) == 1 and notes[0]["dedupe_key"].startswith("download-failed")


def test_i95_an_oversized_resource_fails_at_once(environment, monkeypatch):
    monkeypatch.setattr(engine_module, "MAX_RESOURCE_BYTES", 100)

    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            await env.engine.run_until_idle(max_seconds=20)
            return env.job_rows(batch)[0]

    job = run(scenario())
    assert job["state"] == "FAILED" and job["error_category"] == "too_large" and job["attempts"] == 1


def test_i95_a_redirect_loop_is_a_transport_failure(environment, monkeypatch):
    from oneshelf.net.http import TooManyRedirects

    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")

            async def looping(*_args, **_kwargs):
                raise TooManyRedirects("more than 5 redirects")

            monkeypatch.setattr(env.service, "fetch_resource_to", looping)
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            await env.engine.run_until_idle(max_seconds=40)
            return env.job_rows(batch)[0]

    job = run(scenario(), timeout=90)
    assert job["state"] == "FAILED" and job["error_category"] == "transport"


def test_i95_a_job_interrupted_again_and_again_is_failed_by_recovery(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            job_id = env.job_rows(batch)[0]["id"]
            # A worker died mid-download (process killed) more often than the retry budget allows.
            env.db.execute("UPDATE download_jobs SET state = 'DOWNLOADING', attempts = ? WHERE id = ?",
                           (env.engine.retry_budget + 1, job_id))
            await env.engine.recover()
            return env.engine.job(job_id)

    job = run(scenario())
    assert job["state"] == "FAILED" and job["error_category"] == "interrupted"
    assert job["state"] not in ACTIVE_STATES


def test_i106_a_batch_whose_jobs_were_all_canceled_is_canceled(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            batch = env.engine.enqueue([env.unit_id("irr-1"), env.unit_id("irr-2")])
            env.engine.cancel_batch(batch)
            return env.engine.batch(batch)

    assert run(scenario())["state"] == "canceled"


def test_i106_an_unavailable_storage_location_is_not_reported_as_low_storage(environment, tmp_path):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            env.engine.notifications = NotificationService(env.db)
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            Path(env.root.path).rename(tmp_path / "unplugged")            # the disk went away
            await env.engine.run_until_idle(max_seconds=40)
            return env.job_rows(batch)[0], _notifications(env.db), env.root.id

    job, notes, root_id = run(scenario(), timeout=90)
    assert job["state"] == "FAILED" and job["error_category"] == "storage_unavailable"
    assert [n["dedupe_key"] for n in notes] == [f"storage-unavailable:{root_id}"]
    assert "0 bytes remain" not in notes[0]["payload_json"]


# -- I-93 (BE-003): what is downloaded follows what the source delivers, not the Work's label --------------------

@pytest.mark.parametrize("content_type", ["unknown", "other", "manga"])
def test_i93_image_reader_units_package_as_cbz_whatever_the_work_is_labelled(environment, content_type):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle", content_type=content_type)
            batch = env.engine.enqueue([env.unit_id("irr-1")])
            report = await env.engine.run_until_idle()
            job = env.job_rows(batch)[0]
            return report, json.loads(job["extraction_contract_json"])["output_format"], env.assets(), env.files()

    report, output, assets, files = run(scenario())
    assert output == "cbz" and report.completed == 1
    assert [a["format"] for a in assets] == ["cbz"] and len(cbz_pages(files[0])) == 3


def test_i93_a_book_from_a_source_with_both_recipes_still_downloads_its_file(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            batch = env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            await env.engine.run_until_idle()
            return json.loads(env.job_rows(batch)[0]["extraction_contract_json"])["output_format"], env.assets()

    output, assets = run(scenario())
    assert output == "file" and [a["format"] for a in assets] == ["pdf"]


# -- I-97 (BE-007): resume asks only for bytes that exist, and Retry starts a bad file over -------------------

def _recording(env, calls):
    original = env.service.fetch_resource_to

    async def recording(source_id, url, path, **kwargs):
        calls.append(kwargs.get("resume_from", 0))
        return await original(source_id, url, path, **kwargs)
    env.service.fetch_resource_to = recording


def test_i97_a_complete_file_that_failed_later_is_fetched_whole_again(environment, monkeypatch):
    real_validate = engine_module.validate
    failures = {"left": 1}

    def flaky(path):
        if failures["left"]:
            failures["left"] -= 1
            return ValidationResult(ok=False, format=None, reason="transient")
        return real_validate(path)

    monkeypatch.setattr(engine_module, "validate", flaky)

    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            calls = []
            _recording(env, calls)
            batch = env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            await env.engine.run_until_idle(max_seconds=40)
            return env.job_rows(batch)[0], calls, env.assets()

    job, calls, assets = run(scenario(), timeout=90)
    assert job["state"] == "COMPLETED" and [a["format"] for a in assets] == ["pdf"]
    assert calls == [0, 0]                       # never a Range request for bytes past the end


def test_i97_manual_retry_starts_a_failed_file_over(environment, monkeypatch):
    monkeypatch.setattr(engine_module, "validate",
                        lambda path: ValidationResult(ok=False, format=None, reason="bad"))

    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            batch = env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            await env.engine.run_until_idle(max_seconds=60)
            job = env.job_rows(batch)[0]
            env.db.execute("UPDATE download_jobs SET manifest_json = ? WHERE id = ?",
                           (json.dumps({"file": {"validator": '"v1"', "expected": 10**6, "bytes": 5}}), job["id"]))
            env.engine.retry_job(job["id"])
            return job["state"], json.loads(env.engine.job(job["id"])["manifest_json"] or "{}")

    state, manifest = run(scenario(), timeout=120)
    assert state == "FAILED" and "file" not in manifest


# -- I-98 (BE-008), I-99 (BE-009): a new copy replaces a broken one only once it is verified -----------------

from oneshelf.storage.scanner import reconcile


def _break_and_scan(env, how):
    asset = env.assets()[0]
    path = Path(env.root.path) / asset["relative_path"]
    if how == "missing":
        path.unlink()
    else:
        data = bytearray(path.read_bytes())
        data[-10] ^= 0xFF
        path.write_bytes(bytes(data))
    reconcile(env.db, verify_checksums=True)
    return asset, path


@pytest.mark.parametrize("repair", [False, True])
def test_i98_downloading_again_a_unit_whose_file_went_missing_completes(environment, repair):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            old, path = _break_and_scan(env, "missing")
            batch = env.engine.enqueue([unit], repair=repair)
            await env.engine.run_until_idle()
            journal = [r[0] for r in env.db.execute("SELECT state FROM commit_journal")]
            return old, env.job_rows(batch)[0], env.assets(), env.files(), journal, path

    old, job, assets, files, journal, path = run(scenario())
    assert job["state"] == "COMPLETED"
    assert len(assets) == 1 and assets[0]["id"] == old["id"] and assets[0]["integrity"] == "ok"
    assert files == [path] and set(journal) == {"done"}


def test_i99_repair_keeps_the_broken_copy_while_the_source_cannot_supply_a_new_one(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            old, path = _break_and_scan(env, "corrupt")
            broken_bytes = path.read_bytes()

            original = env.service.fetch_resource_to

            async def offline(*_args, **_kwargs):
                from oneshelf.net.http import FetchFailed
                raise FetchFailed("source offline")

            env.service.fetch_resource_to = offline
            batch = env.engine.enqueue([unit], repair=True)
            during = (len(env.assets()), path.read_bytes() == broken_bytes)
            await env.engine.run_until_idle(max_seconds=40)
            after_failure = (env.job_rows(batch)[0]["state"], env.assets()[0]["integrity"],
                             path.read_bytes() == broken_bytes)

            env.service.fetch_resource_to = original                 # the source is back
            retry = env.engine.enqueue([unit], repair=True)
            await env.engine.run_until_idle()
            return during, after_failure, env.job_rows(retry)[0]["state"], env.assets(), env.files(), path, broken_bytes

    during, after_failure, retried, assets, files, path, broken = run(scenario(), timeout=120)
    assert during == (1, True)                                       # nothing deleted at enqueue
    assert after_failure == ("FAILED", "corrupt", True)              # still there after the repair failed
    assert retried == "COMPLETED" and len(assets) == 1 and assets[0]["integrity"] == "ok"
    assert files == [path] and path.read_bytes() != broken           # replaced, with nothing left beside it


def test_i99_a_repair_of_a_sound_copy_is_not_needed_and_is_skipped(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            batch = env.engine.enqueue([unit], repair=True)
            return env.engine.batch(batch)

    assert run(scenario())["skipped"] == 1


@pytest.mark.parametrize("point", ["after_journal", "after_retire", "after_move", "after_verify", "after_register"])
def test_i99_a_crash_at_any_step_of_a_replacement_recovers_to_exactly_one_good_copy(environment, point):
    class Crash(BaseException):
        pass

    armed = {"on": False}

    def fault(name):
        if armed["on"] and name == point:
            armed["on"] = False
            raise Crash(name)

    async def scenario():
        async with environment(fault=fault) as env:
            await env.add_work("irregular", "The Irregular Chronicle")
            unit = env.unit_id("irr-1")
            env.engine.enqueue([unit])
            await env.engine.run_until_idle()
            old, path = _break_and_scan(env, "corrupt")
            env.engine.enqueue([unit], repair=True)
            armed["on"] = True
            with pytest.raises(Crash):
                await env.engine.run_until_idle()
            await env.engine.recover()                              # the restart
            await env.engine.run_until_idle()
            await env.engine.recover()                              # and again: recovery is idempotent
            leftovers = [p for p in Path(env.root.path).rglob("*") if p.is_file() and "replaced" in p.name]
            journal = {r[0] for r in env.db.execute("SELECT state FROM commit_journal")}
            return env.assets(), env.files(), path, leftovers, journal

    assets, files, path, leftovers, journal = run(scenario(), timeout=120)
    assert len(assets) == 1 and assets[0]["integrity"] == "ok"
    assert files == [path] and leftovers == [] and journal <= {"done", "aborted"}
    from oneshelf.storage.hashing import sha256_file
    assert sha256_file(path)[0] == assets[0]["sha256"]


# -- I-96 (BE-006): the engine's heavy steps never stall the event loop ------------------------------------

def test_i96_validation_hashing_and_commit_run_off_the_event_loop(environment, monkeypatch):
    """Each heavy step is made as slow as it is for a several-hundred-MB file; the loop must keep ticking."""
    import time as _time

    from oneshelf.storage import commit as commit_module

    def slow(function):
        def wrapper(*args, **kwargs):
            _time.sleep(0.4)
            return function(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(engine_module, "validate", slow(engine_module.validate))
    monkeypatch.setattr(engine_module, "sha256_file", slow(engine_module.sha256_file))
    monkeypatch.setattr(commit_module, "sha256_file", slow(commit_module.sha256_file))

    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            batch = env.engine.enqueue([env.unit_id("manual-1")], one_time_method="direct")
            lags, running = [], True

            async def heartbeat():
                loop = asyncio.get_running_loop()
                while running:
                    started = loop.time()
                    await asyncio.sleep(0.02)
                    lags.append(loop.time() - started - 0.02)

            beat = asyncio.create_task(heartbeat())
            await env.engine.run_until_idle(max_seconds=60)
            running = False
            await beat
            return env.job_rows(batch)[0]["state"], max(lags)

    state, worst = run(scenario(), timeout=120)
    assert state == "COMPLETED"
    assert worst < 0.25, f"the event loop stalled for {worst:.2f}s"


# -- I-103 (BE-013): a unit offered in several formats can be downloaded in the ones chosen ---------------

def test_i103_two_chosen_formats_become_two_files_of_one_unit(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("editions", "A Book in Two Editions", content_type="book")
            unit = env.unit_id("ed-1")
            batch = env.engine.enqueue([unit], formats=["pdf", "epub"])
            report = await env.engine.run_until_idle()
            works = env.db.execute("SELECT count(*) FROM works").fetchone()[0]
            return report, env.engine.batch(batch), sorted(a["format"] for a in env.assets()), env.files(), works

    report, batch, formats, files, works = run(scenario())
    assert report.completed == 2 and batch["state"] == "completed"
    assert formats == ["epub", "pdf"] and sorted(f.suffix for f in files) == [".epub", ".pdf"] and works == 1


def test_i103_without_a_choice_the_preferred_format_is_taken(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("editions", "A Book in Two Editions", content_type="book")
            env.engine.enqueue([env.unit_id("ed-1")], one_time_method="direct")
            await env.engine.run_until_idle()
            return [a["format"] for a in env.assets()]

    assert run(scenario()) == ["epub"]          # EPUB before PDF, although the source lists the PDF first


def test_i103_a_format_the_source_does_not_offer_fails_without_retrying(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("manual", "The Manual", content_type="book")
            batch = env.engine.enqueue([env.unit_id("manual-1")], formats=["epub"])
            await env.engine.run_until_idle()
            return env.job_rows(batch)[0], env.assets()

    job, assets = run(scenario())
    assert job["state"] == "FAILED" and job["error_category"] == "format_unavailable" and job["attempts"] == 1
    assert assets == []


def test_i103_a_format_already_downloaded_is_skipped_and_another_is_not(environment):
    async def scenario():
        async with environment() as env:
            await env.add_work("editions", "A Book in Two Editions", content_type="book")
            unit = env.unit_id("ed-1")
            env.engine.enqueue([unit], formats=["pdf"])
            await env.engine.run_until_idle()
            again = env.engine.batch(env.engine.enqueue([unit], formats=["pdf", "epub"]))
            await env.engine.run_until_idle()
            return again, sorted(a["format"] for a in env.assets())

    again, formats = run(scenario())
    assert again["skipped"] == 1 and formats == ["epub", "pdf"]


# -- I-108 (BE-018): a file whose declared size would cross the reserve is refused before it is fetched ------

def test_i108_preflight_uses_the_declared_size_before_fetching(environment, monkeypatch):
    from collections import namedtuple
    usage = namedtuple("usage", "total used free")
    gib = 1024 ** 3
    # 100 GiB disk: the reserve is 5 GiB; 5 GiB + 10 MiB free leaves room for small files only.
    monkeypatch.setattr(engine_module.shutil, "disk_usage",
                        lambda _path: usage(100 * gib, 95 * gib - 10 * 1024**2, 5 * gib + 10 * 1024**2))

    async def scenario():
        async with environment() as env:
            await env.add_work("editions", "A Book in Two Editions", content_type="book")
            fetched = []
            original = env.service.fetch_resource_to

            async def counting(source_id, url, path, **kwargs):
                fetched.append(url)
                return await original(source_id, url, path, **kwargs)

            env.service.fetch_resource_to = counting
            big = env.engine.enqueue([env.unit_id("ed-1")], formats=["epub"])     # declares 50 MB
            small = env.engine.enqueue([env.unit_id("ed-1")], formats=["pdf"])    # declares nothing, is tiny
            await env.engine.run_until_idle(max_seconds=40)
            return env.job_rows(big)[0], env.job_rows(small)[0], fetched

    big, small, fetched = run(scenario(), timeout=90)
    assert big["state"] == "FAILED" and big["error_category"] == "storage_full"
    assert small["state"] == "COMPLETED"
    assert not any(url.endswith(".epub") for url in fetched)            # refused before a byte was fetched
