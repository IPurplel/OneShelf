"""Master §34; INV-20, INV-21: export is a resumable copy that never modifies the library."""
import asyncio
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from oneshelf.export.service import ExportBlocked, ExportContract, ExportError, ExportService
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 30))


@pytest.fixture
def exports(library, tmp_path):
    (tmp_path / "usb").mkdir()
    return ExportService(library.conn), tmp_path / "usb"


def contract(library, title, destination, **kwargs):
    work = library.works[title]
    track = library.conn.execute("SELECT * FROM source_tracks WHERE id = ?", (work["track_id"],)).fetchone()
    return ExportContract(work_id=work["work_id"], language=track["language"], source_id=track["source_id"],
                          unit_ids=[work["unit_id"]], destination=str(destination), **kwargs)


def library_state(conn):
    return {table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in ("works", "source_tracks", "reading_units", "assets", "shelf_entries", "reading_state")}


@pytest.mark.parametrize("output", ["folder", "zip"])
def test_i69_colliding_unit_titles_keep_every_exported_file(library, exports, output):
    service, destination = exports
    work = library.add_work("Collisions", content=b"first")
    unit_ids = [work["unit_id"]]
    library.conn.execute("UPDATE reading_units SET display_title = 'Same' WHERE id = ?", (unit_ids[0],))
    for order, (title, payload) in enumerate((("Same", b"second"), ("A/B", b"third"),
                                               ("A:B", b"fourth")), start=2):
        unit_id, asset_id = new_id(), new_id()
        relative = f"collisions/{order}.cbz"
        path = library.root_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        library.conn.execute(
            "INSERT INTO reading_units (id, track_id, source_unit_key, display_title, unit_type, source_order,"
            " first_seen_at) VALUES (?,?,?,?, 'chapter', ?, ?)",
            (unit_id, work["track_id"], f"unit-{order}", title, order, utcnow_iso()))
        library.conn.execute(
            "INSERT INTO assets (id, reading_unit_id, format, storage_root_id, relative_path, size_bytes, sha256,"
            " integrity, created_at, updated_at) VALUES (?,?,?,?,?,?,?, 'ok', ?, ?)",
            (asset_id, unit_id, "cbz", library.root.id, relative, len(payload), hashlib.sha256(payload).hexdigest(),
             utcnow_iso(), utcnow_iso()))
        unit_ids.append(unit_id)
    selected = ExportContract(work["work_id"], "en", "mangadex", unit_ids, str(destination),
                              output=output, conflict="replace")
    plan = service.plan(selected)
    names = [Path(file.target_path).name for file in plan.files]
    assert len(names) == len(set(names)) == 4
    assert [file.target_path for file in service.plan(selected).files] == [file.target_path for file in plan.files]
    report = run(service.run(service.start(plan)))
    assert (report.state, report.copied, report.failed) == ("completed", 4, 0)
    if output == "folder":
        actual = {path.read_bytes() for path in destination.rglob("*.cbz")}
    else:
        with zipfile.ZipFile(next(destination.glob("*.zip"))) as archive:
            members = [name for name in archive.namelist() if name.endswith(".cbz")]
            assert len(members) == len(set(members)) == 4
            actual = {archive.read(name) for name in members}
    assert actual == {b"first", b"second", b"third", b"fourth"}
    skip = ExportContract(work["work_id"], "en", "mangadex", unit_ids, str(destination),
                          output=output, conflict="skip_identical")
    skipped = run(service.run(service.start(service.plan(skip))))
    assert (skipped.state, skipped.skipped, skipped.failed) == ("completed", 4, 0)


def test_export_copies_originals_without_touching_the_library(library, exports):
    service, destination = exports
    library.add_work("Solo Leveling", content=b"original chapter bytes")
    before = library_state(library.conn)
    plan = service.plan(contract(library, "Solo Leveling", destination))
    assert plan.files and plan.missing_units == []
    report = run(service.run(service.start(plan)))
    assert report.state == "completed" and report.copied == 1 and report.failed == 0
    copied = next(p for p in destination.rglob("*") if p.suffix == ".cbz")
    assert copied.read_bytes() == b"original chapter bytes"          # byte-identical original (§34.2)
    assert library_state(library.conn) == before                     # INV-20
    metadata = json.loads((copied.parent / "oneshelf-export.json").read_text())
    assert metadata["title"] == "Solo Leveling" and metadata["language"] == "en" and metadata["source"] == "mangadex"
    assert "/" not in metadata.get("library_path", "") and "sha256" in metadata["units"][0]["files"][0]


def test_destination_preflight_rejects_missing_or_unwritable_targets(library, exports, tmp_path):
    service, destination = exports
    library.add_work("Solo Leveling")
    with pytest.raises(ExportError, match="destination"):
        service.plan(contract(library, "Solo Leveling", tmp_path / "nope"))
    readonly = tmp_path / "readonly"
    readonly.mkdir()
    readonly.chmod(0o500)
    try:
        with pytest.raises(ExportError, match="writable"):
            service.plan(contract(library, "Solo Leveling", readonly))
    finally:
        readonly.chmod(0o700)


@pytest.mark.parametrize("policy,expected", [("skip_identical", "identical"), ("replace", "new"), ("keep_both", "both")])
def test_conflict_policies(library, exports, policy, expected):
    service, destination = exports
    library.add_work("Solo Leveling", content=b"new content")
    plan = service.plan(contract(library, "Solo Leveling", destination))
    target = Path(plan.files[0].target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"new content" if expected == "identical" else b"older different content")

    plan = service.plan(contract(library, "Solo Leveling", destination, conflict=policy))
    report = run(service.run(service.start(plan)))
    files = sorted(p.name for p in target.parent.glob("*.cbz"))
    if expected == "identical":
        assert report.skipped == 1 and files == [target.name]
    elif expected == "new":
        assert report.copied == 1 and target.read_bytes() == b"new content"
    else:
        assert len(files) == 2 and report.copied == 1


def test_export_resumes_after_an_interruption(library, exports):
    service, destination = exports
    for index in range(3):
        library.add_work(f"Work {index}", content=f"chapter {index}".encode())
    units = [library.works[f"Work {i}"]["unit_id"] for i in range(3)]
    work = library.works["Work 0"]
    plan = service.plan_selection([contract(library, f"Work {i}", destination) for i in range(3)])
    job_id = service.start(plan)

    copied = {"n": 0}

    def fault(point):
        if point == "file_copied":
            copied["n"] += 1
            if copied["n"] == 2:
                raise KeyboardInterrupt("interrupted")

    service.fault = fault
    with pytest.raises(KeyboardInterrupt):
        run(service.run(job_id))
    service.fault = lambda _point: None
    report = run(service.run(job_id))
    assert report.copied == 1 and report.state == "completed"        # only the remaining file was copied
    assert len(list(destination.rglob("*.cbz"))) == 3


def test_one_failed_file_does_not_fail_the_export_and_can_be_retried(library, exports):
    service, destination = exports
    good = library.add_work("Good", content=b"good chapter")
    broken = library.add_work("Broken", content=b"broken chapter")
    work = library.works["Good"]
    plan = service.plan_selection([contract(library, "Good", destination), contract(library, "Broken", destination)])
    (library.root_path / broken["relative"]).unlink()
    job_id = service.start(plan)
    report = run(service.run(job_id))
    assert report.state == "completed_with_issues" and report.copied == 1 and report.failed == 1

    (library.root_path / broken["relative"]).write_bytes(b"broken chapter")
    assert service.retry_failed(job_id) == 1
    report = run(service.run(job_id))
    assert report.state == "completed" and report.copied == 1


def test_zip_output_stores_already_compressed_files(library, exports):
    service, destination = exports
    library.add_work("Solo Leveling", content=b"chapter bytes")
    plan = service.plan(contract(library, "Solo Leveling", destination, output="zip"))
    run(service.run(service.start(plan)))
    archives = list(destination.glob("*.zip"))
    assert len(archives) == 1
    with zipfile.ZipFile(archives[0]) as z:
        names = z.namelist()
        assert any(n.endswith(".cbz") for n in names) and "oneshelf-export.json" in names
        assert all(info.compress_type == zipfile.ZIP_STORED for info in z.infolist() if info.filename.endswith(".cbz"))


def test_missing_content_offers_choices_and_never_converts_formats(library, exports):
    service, destination = exports
    work = library.add_work("Solo Leveling", content=b"chapter bytes")
    second = library.add_work("Solo Leveling Vol 2", content=None)    # no local file
    plan = service.plan_selection([contract(library, "Solo Leveling", destination),
                                   contract(library, "Solo Leveling Vol 2", destination)])
    assert plan.missing_units == [second["unit_id"]]
    assert plan.choices == ["export_downloaded_only", "download_missing_then_export", "cancel"]

    report = run(service.run(service.start(plan, missing_policy="export_downloaded_only")))
    assert report.copied == 1 and report.state == "completed"

    pdf_plan = service.plan(contract(library, "Solo Leveling", destination, formats=["pdf"]))
    assert pdf_plan.files == [] and pdf_plan.missing_units == [work["unit_id"]]   # no implicit conversion (§34.4)


def test_download_missing_requires_an_explicit_permanent_download_notice(library, exports):
    service, destination = exports
    work = library.add_work("Solo Leveling", content=b"chapter bytes")
    missing = library.add_work("Missing Chapter", content=None)
    plan = service.plan_selection([contract(library, "Solo Leveling", destination),
                                   contract(library, "Missing Chapter", destination)])
    with pytest.raises(ExportBlocked, match="permanently"):
        service.start(plan, missing_policy="download_missing_then_export")
    assert service.disclosure(plan)["message"].startswith("This will also permanently download")
    job_id = service.start(plan, missing_policy="download_missing_then_export", acknowledge_permanent_download=True)
    assert service.job(job_id)["missing_policy"] == "download_missing_then_export"


def test_history_cleanup_never_deletes_exported_files(library, exports, clock):
    from datetime import timedelta

    service, destination = exports
    service.clock = lambda: clock["now"]
    library.add_work("Solo Leveling", content=b"chapter bytes")
    plan = service.plan(contract(library, "Solo Leveling", destination))
    run(service.run(service.start(plan)))
    exported = list(destination.rglob("*.cbz"))
    clock["now"] += timedelta(days=40)
    removed = service.cleanup_history()
    assert removed == 1 and all(p.exists() for p in exported)
    assert library.conn.execute("SELECT count(*) FROM export_jobs").fetchone()[0] == 0


def test_local_only_content_exports_without_any_plugin(library, exports):
    service, destination = exports
    work = library.add_work("Imported Book", source="local", content=b"local bytes")
    plan = service.plan(ExportContract(work_id=work["work_id"], language="en", source_id="local",
                                       unit_ids=[work["unit_id"]], destination=str(destination)))
    report = run(service.run(service.start(plan)))
    assert report.copied == 1 and library.conn.execute("SELECT count(*) FROM plugins").fetchone()[0] == 0


def test_selected_works_export_as_one_job_without_mixing_them(library, exports):
    """§34.1 'Selected Works': one export job, one folder per work and language, nothing mixed."""
    service, destination = exports
    library.add_work("Solo Leveling", content=b"solo bytes")
    library.add_work("Omniscient Reader", content=b"orv bytes")
    plan = service.plan_selection([contract(library, "Solo Leveling", destination),
                                   contract(library, "Omniscient Reader", destination)])
    job_id = service.start(plan)
    report = run(service.run(job_id))

    assert report.state == "completed" and report.copied == 2
    folders = sorted(p.name for p in destination.iterdir() if p.is_dir())
    assert folders == ["Omniscient Reader (en)", "Solo Leveling (en)"]
    for folder, expected in (("Solo Leveling (en)", b"solo bytes"), ("Omniscient Reader (en)", b"orv bytes")):
        exported = list((destination / folder).glob("*.cbz"))
        assert len(exported) == 1 and exported[0].read_bytes() == expected
        metadata = json.loads((destination / folder / "oneshelf-export.json").read_text())
        assert metadata["title"] == folder.removesuffix(" (en)") and len(metadata["units"]) == 1
    assert service.job(job_id)["state"] == "completed"


def test_sequential_units_default_to_cbz_while_books_keep_their_original(library, exports):
    """§34.4: CBZ is the default for sequential content and books export as they are — never converted."""
    service, destination = exports
    manga = library.add_work("Solo Leveling", content=b"cbz bytes")
    library.add_asset(manga["unit_id"], fmt="pdf", content=b"%PDF-1.7 fallback")
    book = library.add_work("The Prophet", content=b"%PDF-1.7 book", content_type="novel", fmt="pdf")

    plan = service.plan_selection([contract(library, "Solo Leveling", destination),
                                   contract(library, "The Prophet", destination)])
    assert sorted(Path(f.target_path).suffix for f in plan.files) == [".cbz", ".pdf"]

    both = service.plan(contract(library, "Solo Leveling", destination, formats=["cbz", "pdf"]))
    assert len(both.files) == 2       # an explicit format choice still exports exactly what was asked for


def test_export_rejects_units_belonging_to_another_work(library, exports):
    service, destination = exports
    first = library.add_work('First')
    other = library.add_work('Other')
    with pytest.raises(ExportError, match='belong'):
        service.plan(ExportContract(first['work_id'], 'en', 'mangadex', [other['unit_id']], str(destination)))


def test_zip_keep_both_preserves_existing_folder_and_archive(library, exports):
    service, destination = exports
    library.add_work('Book', content=b'selected')
    folder = destination / 'Book (en)'
    folder.mkdir()
    (folder / 'personal.txt').write_bytes(b'personal')
    old = destination / 'Book (en).zip'
    old.write_bytes(b'old archive')
    report = run(service.run(service.start(service.plan(contract(library, 'Book', destination,
                                                                 output='zip', conflict='keep_both')))))
    assert report.state == 'completed'
    assert old.read_bytes() == b'old archive'
    assert (folder / 'personal.txt').read_bytes() == b'personal'
    fresh = next(p for p in destination.glob('*.zip') if p != old)
    with zipfile.ZipFile(fresh) as z:
        assert 'personal.txt' not in z.namelist()
        assert len([n for n in z.namelist() if n.endswith('.cbz')]) == 1


def test_zip_same_title_works_have_separate_archives(library, exports):
    service, destination = exports
    library.add_work('First', content=b'first')
    library.add_work('Second', content=b'second')
    contracts = [contract(library, name, destination, output='zip') for name in ['First', 'Second']]
    library.conn.execute("UPDATE works SET display_title = 'Same'")
    report = run(service.run(service.start(service.plan_selection(contracts))))
    assert report.state == 'completed'
    archives = list(destination.glob('*.zip'))
    assert len(archives) == 2
    contents = []
    for path in archives:
        with zipfile.ZipFile(path) as z:
            contents.extend(z.read(n) for n in z.namelist() if n.endswith('.cbz'))
    assert sorted(contents) == [b'first', b'second']


def test_keep_both_records_actual_filename_in_job_and_metadata(library, exports):
    service, destination = exports
    library.add_work('Book')
    plan = service.plan(contract(library, 'Book', destination, conflict='keep_both'))
    original = Path(plan.files[0].target_path)
    original.parent.mkdir()
    original.write_bytes(b'previous')
    job_id = service.start(plan)
    run(service.run(job_id))
    actual = Path(library.conn.execute('SELECT target_path FROM export_items WHERE job_id = ?', (job_id,)).fetchone()[0])
    assert actual != original and actual.read_bytes() == b'chapter one'
    metadata = json.loads((actual.parent / 'oneshelf-export.json').read_text())
    assert metadata['units'][0]['files'][0]['name'] == actual.name


def test_download_missing_cannot_report_empty_success(library, exports):
    service, destination = exports
    library.add_work('Missing', content=None)
    job_id = service.start(service.plan(contract(library, 'Missing', destination)),
                           missing_policy='download_missing_then_export', acknowledge_permanent_download=True)
    report = run(service.run(job_id))
    assert report.state == 'completed_with_issues' and report.failed == 1 and report.errors


def test_export_includes_content_downloaded_after_the_job_was_created(library, exports):
    service, destination = exports
    work = library.add_work('Missing', content=None)
    job_id = service.start(service.plan(contract(library, 'Missing', destination)),
                           missing_policy='download_missing_then_export', acknowledge_permanent_download=True)
    library.add_asset(work['unit_id'], fmt='cbz', content=b'new download')
    report = run(service.run(job_id))
    assert report.state == 'completed' and report.copied == 1
    assert next(destination.rglob('*.cbz')).read_bytes() == b'new download'


def test_invalid_existing_zip_is_a_reported_conflict(library, exports):
    service, destination = exports
    library.add_work('Book')
    archive = destination / 'Book (en).zip'
    archive.write_bytes(b'personal file')
    job_id = service.start(service.plan(contract(library, 'Book', destination, output='zip')))
    report = run(service.run(job_id))
    assert report.state == 'completed_with_issues' and report.errors
    assert service.job(job_id)['state'] == 'completed_with_issues'
    assert archive.read_bytes() == b'personal file'


def test_zip_retry_publishes_only_when_all_selected_files_are_ready(library, exports):
    service, destination = exports
    work = library.add_work('Book', content=b'comic')
    asset_id = library.add_asset(work['unit_id'], fmt='pdf', content=b'paper')
    relative = library.conn.execute('SELECT relative_path FROM assets WHERE id = ?', (asset_id,)).fetchone()[0]
    missing = library.root_path / relative
    plan = service.plan(contract(library, 'Book', destination, output='zip', formats=['cbz', 'pdf']))
    missing.unlink()
    job_id = service.start(plan)
    assert run(service.run(job_id)).state == 'completed_with_issues'
    assert list(destination.glob('*.zip')) == []
    missing.write_bytes(b'paper')
    service.retry_failed(job_id)
    assert run(service.run(job_id)).state == 'completed'
    with zipfile.ZipFile(next(destination.glob('*.zip'))) as archive:
        assert sorted(archive.read(name) for name in archive.namelist() if name != 'oneshelf-export.json') == [b'comic', b'paper']


def test_zip_waits_for_missing_units_before_publishing(library, exports):
    service, destination = exports
    first = library.add_work('Book', content=b'first')
    second = library.add_work('Second chapter', content=None)
    library.conn.execute('UPDATE reading_units SET track_id=?, source_order=2 WHERE id=?',
                         (first['track_id'], second['unit_id']))
    selection = ExportContract(first['work_id'], 'en', 'mangadex',
                               [first['unit_id'], second['unit_id']], str(destination), output='zip')
    job_id = service.start(service.plan(selection), missing_policy='download_missing_then_export',
                           acknowledge_permanent_download=True)
    assert run(service.run(job_id)).state == 'completed_with_issues'
    assert list(destination.glob('*.zip')) == []
    library.add_asset(second['unit_id'], fmt='cbz', content=b'second')
    service.retry_failed(job_id)
    assert run(service.run(job_id)).state == 'completed'
    with zipfile.ZipFile(next(destination.glob('*.zip'))) as archive:
        assert sorted(archive.read(name) for name in archive.namelist() if name.endswith('.cbz')) == [b'first', b'second']


@pytest.mark.parametrize('output', ['folder', 'zip'])
def test_export_rejects_destination_symlink(library, exports, output):
    service, destination = exports
    library.add_work('Book')
    outside = destination.parent / 'outside'
    outside.mkdir()
    sentinel = outside / 'Book-1.cbz'
    sentinel.write_bytes(b'private')
    if output == 'folder':
        (destination / 'Book (en)').symlink_to(outside, target_is_directory=True)
    else:
        (destination / 'Book (en).zip').symlink_to(sentinel)
    report = run(service.run(service.start(service.plan(contract(library, 'Book', destination,
                                                                 output=output, conflict='replace')))))
    assert report.state == 'completed_with_issues'
    assert sentinel.read_bytes() == b'private'
