"""Master §34; INV-20, INV-21: export is a resumable copy that never modifies the library."""
import asyncio
import json
import zipfile
from pathlib import Path

import pytest

from oneshelf.export.service import ExportBlocked, ExportContract, ExportError, ExportService


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
    plan = service.plan(ExportContract(work_id=work["work_id"], language="en", source_id="mangadex",
                                       unit_ids=units, destination=str(destination)))
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
    plan = service.plan(ExportContract(work_id=work["work_id"], language="en", source_id="mangadex",
                                       unit_ids=[good["unit_id"], broken["unit_id"]], destination=str(destination)))
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
    plan = service.plan(ExportContract(work_id=work["work_id"], language="en", source_id="mangadex",
                                       unit_ids=[work["unit_id"], second["unit_id"]], destination=str(destination)))
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
    plan = service.plan(ExportContract(work_id=work["work_id"], language="en", source_id="mangadex",
                                       unit_ids=[work["unit_id"], missing["unit_id"]], destination=str(destination)))
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
