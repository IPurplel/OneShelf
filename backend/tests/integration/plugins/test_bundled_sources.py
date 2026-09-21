"""The official adapters install themselves on a fresh library — once (release requirement, 2026-09-21).

Every test here goes through the real PluginManager with real packages built from
`plugins/official/`. The ones about updates, permissions and failures use edited copies of a real
package, because what matters is how the normal pipeline treats them, not a mock of it.
"""
import asyncio
import shutil
from pathlib import Path

import pytest

from oneshelf.plugins.bundled import BOOTSTRAP_VERSION, bootstrap_version, sync_bundled
from oneshelf.plugins.manager import PluginManager

OFFICIAL = Path(__file__).resolve().parents[3] / "plugins" / "official"
EIGHT = ["oneshelf.3asq", "oneshelf.arxiv", "oneshelf.gutenberg", "oneshelf.hindawi", "oneshelf.mangadex",
         "oneshelf.standard-ebooks", "oneshelf.tapas", "oneshelf.webtoon"]


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, 120))


@pytest.fixture
def manager(db, tmp_path):
    return PluginManager(db, store_dir=tmp_path / "store")


def bundle(tmp_path, *names, name="bundled"):
    """A bundled directory holding copies of some real official packages."""
    directory = tmp_path / name
    directory.mkdir(exist_ok=True)
    for plugin in names:
        shutil.copytree(OFFICIAL / plugin, directory / plugin, dirs_exist_ok=True)
    return directory


def edit_manifest(directory, plugin, *, version=None, extra_domain=None):
    path = directory / plugin / "manifest.yaml"
    text = path.read_text(encoding="utf-8")
    if version:
        text = text.replace("version: 1.0.0", f"version: {version}", 1)
    if extra_domain:
        text = text.replace("  domains: [", f"  domains: [{extra_domain}, ", 1)
    path.write_text(text, encoding="utf-8")


def plugin_rows(db):
    return {r["id"]: (r["state"], r["active_version"], r["trust_label"], r["channel"])
            for r in db.execute("SELECT * FROM plugins")}


def by_id(outcomes):
    return {o.plugin_id: o for o in outcomes}


# -- 1. a fresh library -------------------------------------------------------------------------

def test_a_fresh_library_gets_all_eight_official_sources_active(db, manager):
    outcomes = run(sync_bundled(db, manager, OFFICIAL))
    assert sorted(o.plugin_id for o in outcomes if o.result == "installed") == EIGHT, \
        [(o.plugin_id, o.result, o.detail) for o in outcomes]
    rows = plugin_rows(db)
    assert sorted(rows) == EIGHT
    assert all(state == "active" and trust == "official" and channel == "bundled"
               for state, _, trust, channel in rows.values())
    assert bootstrap_version(db) == BOOTSTRAP_VERSION


def test_they_went_through_the_normal_pipeline_packaged_tests_included(db, manager):
    run(sync_bundled(db, manager, OFFICIAL))
    for plugin in EIGHT:
        [version] = manager.versions(plugin)
        assert version.status == "active"
        assert version.approved_permissions == version.permissions      # first install: declared set
        manager.load_active(plugin)                                      # stored, hashed, loadable
    reports = [r[0] for r in db.execute("SELECT test_report_json FROM plugin_versions")]
    assert all('"passed": true' in r for r in reports)


# -- 2, 3, 7. restarting --------------------------------------------------------------------------

def test_restarting_changes_nothing_and_duplicates_nothing(db, manager):
    run(sync_bundled(db, manager, OFFICIAL))
    before = [tuple(r) for r in db.execute("SELECT plugin_id, version, sha256, installed_at FROM plugin_versions"
                                           " ORDER BY plugin_id")]
    for _ in range(3):
        outcomes = run(sync_bundled(db, manager, OFFICIAL))
        assert {o.result for o in outcomes} == {"unchanged"}
    after = [tuple(r) for r in db.execute("SELECT plugin_id, version, sha256, installed_at FROM plugin_versions"
                                          " ORDER BY plugin_id")]
    assert after == before                                # same rows, same install times: nothing redone
    assert db.execute("SELECT count(*) FROM plugins").fetchone()[0] == 8


def test_the_build_is_deterministic_so_a_rebuilt_image_is_the_same_package(db, manager, tmp_path):
    run(sync_bundled(db, manager, OFFICIAL))
    rebuilt = bundle(tmp_path, *EIGHT, name="rebuilt-image")          # the same sources, copied fresh
    assert {o.result for o in run(sync_bundled(db, manager, rebuilt))} == {"unchanged"}


# -- 4, 5. the person's choices stand ---------------------------------------------------------------

def test_a_source_the_person_disabled_stays_disabled_across_restarts(db, manager):
    run(sync_bundled(db, manager, OFFICIAL))
    manager.disable("oneshelf.tapas")
    run(sync_bundled(db, manager, OFFICIAL))
    run(sync_bundled(db, manager, OFFICIAL))
    assert plugin_rows(db)["oneshelf.tapas"][0] == "disabled"


def test_a_disabled_source_is_not_updated_either_because_updating_would_re_enable_it(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.tapas")
    run(sync_bundled(db, manager, source))
    manager.disable("oneshelf.tapas")
    edit_manifest(source, "oneshelf.tapas", version="1.1.0")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "left_alone"
    assert plugin_rows(db)["oneshelf.tapas"][:2] == ("disabled", "1.0.0")


def test_a_source_the_person_removed_is_never_reinstalled(db, manager):
    run(sync_bundled(db, manager, OFFICIAL))
    manager.uninstall("oneshelf.webtoon")
    for _ in range(2):
        outcomes = by_id(run(sync_bundled(db, manager, OFFICIAL)))
        assert outcomes["oneshelf.webtoon"].result == "left_alone"
    assert plugin_rows(db)["oneshelf.webtoon"][:2] == ("uninstalled", None)
    assert manager.versions("oneshelf.webtoon")[0].status == "retired"


def test_a_source_the_person_reinstalled_by_hand_is_theirs_and_is_not_updated_for_them(db, manager, tmp_path):
    from plugins.build import build_package

    source = bundle(tmp_path, "oneshelf.gutenberg")
    run(sync_bundled(db, manager, source))
    manager.uninstall("oneshelf.gutenberg")
    package = build_package(source / "oneshelf.gutenberg", tmp_path / "manual.osp")
    run(manager.install_file(package, approved_permissions=frozenset({"network:domain:gutendex.com",
                                                                     "network:cdn:www.gutenberg.org"})))
    edit_manifest(source, "oneshelf.gutenberg", version="1.1.0")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "left_alone"
    assert plugin_rows(db)["oneshelf.gutenberg"][1:] == ("1.0.0", "local", "upload")


# -- 6, 8. updates -----------------------------------------------------------------------------------

def test_a_newer_bundled_version_updates_through_the_normal_path_keeping_rollback(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.arxiv")
    run(sync_bundled(db, manager, source))
    edit_manifest(source, "oneshelf.arxiv", version="1.1.0")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "updated" and outcome.version == "1.1.0"
    assert plugin_rows(db)["oneshelf.arxiv"] == ("active", "1.1.0", "official", "bundled")
    assert {v.version: v.status for v in manager.versions("oneshelf.arxiv")} == {"1.0.0": "previous",
                                                                                  "1.1.0": "active"}
    manager.rollback("oneshelf.arxiv")                                  # rollback still works
    assert plugin_rows(db)["oneshelf.arxiv"][1] == "1.0.0"


def test_a_rolled_back_source_is_not_rolled_forward_again_on_restart(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.arxiv")
    run(sync_bundled(db, manager, source))
    edit_manifest(source, "oneshelf.arxiv", version="1.1.0")
    run(sync_bundled(db, manager, source))
    manager.rollback("oneshelf.arxiv")
    run(sync_bundled(db, manager, source))
    assert plugin_rows(db)["oneshelf.arxiv"][1] == "1.0.0"


def test_an_update_leaves_the_library_that_depends_on_the_source_untouched(db, manager, tmp_path):
    from oneshelf.domain.ids import new_id

    source = bundle(tmp_path, "oneshelf.mangadex")
    run(sync_bundled(db, manager, source))
    now = "2026-01-01T00:00:00+00:00"
    work, track, listing, unit = new_id(), new_id(), new_id(), new_id()
    db.execute("INSERT INTO works (id, display_title, content_type, created_at, updated_at) VALUES (?,?,?,?,?)",
               (work, "A Work", "manga", now, now))
    db.execute("INSERT INTO source_listings (id, source_id, source_listing_key, raw_title, work_id, created_at)"
               " VALUES (?,?,?,?,?,?)", (listing, "oneshelf.mangadex", "abc", "A Work", work, now))
    db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, listing_id, created_at)"
               " VALUES (?,?,?,?,?,?,?)", (track, work, "oneshelf.mangadex", "en", "source", listing, now))
    db.execute("INSERT INTO reading_units (id, track_id, source_unit_key, unit_type, source_order, first_seen_at)"
               " VALUES (?,?,?,?,?,?)", (unit, track, "u1", "chapter", 1.0, now))
    db.execute("INSERT INTO shelf_entries (work_id, added_at) VALUES (?, ?)", (work, now))
    db.execute("INSERT INTO follows (id, work_id, language, preferred_source_id, track_id, created_at)"
               " VALUES (?,?,?,?,?,?)", (new_id(), work, "en", "oneshelf.mangadex", track, now))
    db.execute("INSERT INTO reading_state (reading_unit_id, read_state, fraction, revision, updated_at)"
               " VALUES (?,?,?,?,?)", (unit, "partial", 0.5, 3, now))

    def snapshot():
        return {table: [tuple(r) for r in db.execute(f"SELECT * FROM {table} ORDER BY 1")]
                for table in ("works", "source_listings", "source_tracks", "reading_units", "shelf_entries",
                              "follows", "reading_state")}

    before = snapshot()
    edit_manifest(source, "oneshelf.mangadex", version="1.1.0")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "updated"
    assert snapshot() == before


# -- 9. permissions are never widened silently ---------------------------------------------------------

def test_a_newer_version_asking_for_more_goes_to_review_and_the_old_one_keeps_working(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.hindawi")
    run(sync_bundled(db, manager, source))
    edit_manifest(source, "oneshelf.hindawi", version="1.1.0", extra_domain="www.hindawi.org")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "pending_review"
    assert "network:domain:www.hindawi.org" in outcome.detail
    assert plugin_rows(db)["oneshelf.hindawi"][:2] == ("active", "1.0.0")      # still the approved one
    statuses = {v.version: v for v in manager.versions("oneshelf.hindawi")}
    assert statuses["1.1.0"].status == "pending_review"
    assert statuses["1.1.0"].approved_permissions == frozenset()            # nothing approved for it
    # and a restart does not approve it either
    [again] = run(sync_bundled(db, manager, source))
    assert again.result == "pending_review"
    assert plugin_rows(db)["oneshelf.hindawi"][1] == "1.0.0"


# -- 10. a broken adapter is contained ------------------------------------------------------------------

def test_a_broken_adapter_is_never_active_and_does_not_stop_the_others(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.gutenberg", "oneshelf.arxiv")
    (source / "oneshelf.arxiv" / "recipes" / "search.yaml").write_text("capability: search\nnot: valid\n",
                                                                       encoding="utf-8")
    outcomes = by_id(run(sync_bundled(db, manager, source)))
    assert outcomes["oneshelf.gutenberg"].result == "installed"
    assert outcomes["oneshelf.arxiv"].result == "failed" and outcomes["oneshelf.arxiv"].detail
    assert "oneshelf.arxiv" not in plugin_rows(db)                        # nothing half-installed
    assert not list((tmp_path / "store").glob("oneshelf.arxiv/*.osp"))
    assert not list((tmp_path / "store" / ".staging").glob("*")) if (tmp_path / "store" / ".staging").exists() else True
    status = db.execute("SELECT status, detail FROM bundled_plugins WHERE plugin_id = 'oneshelf.arxiv'").fetchone()
    assert status["status"] == "failed" and status["detail"]


def test_an_adapter_whose_own_tests_fail_is_refused_and_says_why(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.gutenberg")
    tests = source / "oneshelf.gutenberg" / "tests" / "tests.yaml"
    tests.write_text(tests.read_text(encoding="utf-8").replace("min_items: 1", "min_items: 999", 1),
                     encoding="utf-8")
    [outcome] = run(sync_bundled(db, manager, source))
    assert outcome.result == "failed" and "packaged tests failed" in outcome.detail
    assert plugin_rows(db) == {}


def test_a_failed_first_install_is_retried_when_the_package_changes_and_not_before(db, manager, tmp_path):
    source = bundle(tmp_path, "oneshelf.gutenberg")
    tests = source / "oneshelf.gutenberg" / "tests" / "tests.yaml"
    good = tests.read_text(encoding="utf-8")
    tests.write_text(good.replace("min_items: 1", "min_items: 999", 1), encoding="utf-8")
    run(sync_bundled(db, manager, source))
    [same] = run(sync_bundled(db, manager, source))
    assert same.result == "failed" and "not retried" in same.detail          # same package: not re-run
    tests.write_text(good, encoding="utf-8")                                 # a fixed image
    [fixed] = run(sync_bundled(db, manager, source))
    assert fixed.result == "installed"
    assert plugin_rows(db)["oneshelf.gutenberg"][0] == "active"


def test_a_failure_is_raised_as_needs_attention_and_cleared_when_it_is_fixed(db, manager, tmp_path):
    from oneshelf.notifications.service import NotificationService

    notifications = NotificationService(db)
    source = bundle(tmp_path, "oneshelf.gutenberg")
    tests = source / "oneshelf.gutenberg" / "tests" / "tests.yaml"
    good = tests.read_text(encoding="utf-8")
    tests.write_text(good.replace("min_items: 1", "min_items: 999", 1), encoding="utf-8")
    run(sync_bundled(db, manager, source, notifications=notifications))
    assert [n.dedupe_key for n in notifications.needs_attention()] == ["source-bootstrap:oneshelf.gutenberg"]
    tests.write_text(good, encoding="utf-8")
    run(sync_bundled(db, manager, source, notifications=notifications))
    assert notifications.needs_attention() == []


def deflated_build(source_dir, destination):
    """The same files packed the way an older builder packed them: different container bytes."""
    import zipfile
    source_dir, destination = Path(source_dir), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(p for p in source_dir.rglob("*") if p.is_file()):
            archive.write(path, path.relative_to(source_dir).as_posix())
    return destination


def test_repackaging_under_the_same_version_is_neither_an_update_nor_a_failure(db, manager, tmp_path, monkeypatch):
    """A Core update that packs the same adapter differently must not raise eight failures in Needs Attention."""
    import oneshelf.plugins.bundled as bundled
    from oneshelf.notifications.service import NotificationService

    notifications = NotificationService(db)
    source = bundle(tmp_path, "oneshelf.gutenberg")
    monkeypatch.setattr(bundled, "build_package", deflated_build)
    run(sync_bundled(db, manager, source, notifications=notifications))
    installed_sha = db.execute("SELECT sha256 FROM plugin_versions WHERE plugin_id = 'oneshelf.gutenberg'").fetchone()[0]
    monkeypatch.undo()
    outcome = by_id(run(sync_bundled(db, manager, source, notifications=notifications)))["oneshelf.gutenberg"]
    assert outcome.result == "unchanged"
    assert notifications.needs_attention() == []
    assert plugin_rows(db)["oneshelf.gutenberg"] == ("active", "1.0.0", "official", "bundled")
    rows = db.execute("SELECT sha256, status FROM plugin_versions WHERE plugin_id = 'oneshelf.gutenberg'").fetchall()
    assert [tuple(r) for r in rows] == [(installed_sha, "active")]


# -- existing libraries -------------------------------------------------------------------------------

def test_a_library_that_already_manages_its_sources_is_not_second_guessed(db, manager, tmp_path):
    """A pre-existing library with an official source installed by hand: no bootstrap, only a record."""
    from plugins.build import build_package

    package = build_package(OFFICIAL / "oneshelf.gutenberg", tmp_path / "g.osp")
    run(manager.install_file(package, approved_permissions=frozenset({"network:domain:gutendex.com",
                                                                     "network:cdn:www.gutenberg.org"})))
    outcomes = run(sync_bundled(db, manager, OFFICIAL))
    assert {o.result for o in outcomes} == {"skipped"}
    assert sorted(plugin_rows(db)) == ["oneshelf.gutenberg"]
    assert bootstrap_version(db) == BOOTSTRAP_VERSION                    # decided once, never again
    assert {o.result for o in run(sync_bundled(db, manager, OFFICIAL))} <= {"skipped", "left_alone"}


def test_an_existing_library_where_a_source_was_removed_is_not_bootstrapped(db, manager, tmp_path):
    from plugins.build import build_package

    package = build_package(OFFICIAL / "oneshelf.tapas", tmp_path / "t.osp")
    run(manager.install_file(package, approved_permissions=frozenset({"network:domain:tapas.io",
                                                                     "network:cdn:*.tapas.io"})))
    manager.uninstall("oneshelf.tapas")
    run(sync_bundled(db, manager, OFFICIAL))
    assert plugin_rows(db) == {"oneshelf.tapas": ("uninstalled", None, "local", "upload")}


def test_without_a_bundled_directory_nothing_happens(db, manager, tmp_path):
    assert run(sync_bundled(db, manager, tmp_path / "does-not-exist")) == []
    assert bootstrap_version(db) == 0


def test_a_bootstrap_interrupted_part_way_resumes_instead_of_giving_up(db, manager, tmp_path):
    """If the process dies before the marker is written, the sources it already added are its own work,
    not evidence that the person manages their sources — so the next start finishes the job."""
    run(sync_bundled(db, manager, bundle(tmp_path, "oneshelf.arxiv", "oneshelf.tapas", name="partial")))
    db.execute("DELETE FROM app_meta")                                  # the crash: no marker was written
    outcomes = by_id(run(sync_bundled(db, manager, OFFICIAL)))
    assert sorted(plugin_rows(db)) == EIGHT
    assert all(o.result in ("installed", "unchanged") for o in outcomes.values())
    assert bootstrap_version(db) == BOOTSTRAP_VERSION
