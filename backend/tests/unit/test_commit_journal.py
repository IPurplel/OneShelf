"""Master §17, §24.3, INV-16, INV-17: staged artifacts commit idempotently and survive crashes."""
import json
import os
from pathlib import Path

import pytest

from oneshelf.storage.commit import FAULT_POINTS, CommitEngine, CommitError, CommitRequest, Crash
from oneshelf.storage.roots import register_root
from oneshelf.storage.staging import StagingError, new_staging_area

NOW = "2026-09-17T00:00:00+00:00"


def registrar(conn, payload):
    """Test registrar: idempotent registration of one row keyed by the pre-assigned id."""
    conn.execute("CREATE TABLE IF NOT EXISTS registered (id TEXT PRIMARY KEY, relpath TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO registered (id, relpath) VALUES (?, ?)", (payload["id"], payload["relpath"]))


@pytest.fixture
def root(db, tmp_path):
    (tmp_path / "lib").mkdir()
    return register_root(db, "Library", tmp_path / "lib")


def stage(root, data=b"%PDF-1.7 fake but staged"):
    area, area_rel = new_staging_area(root, purpose="test", owner_id="owner")
    (area / "artifact.pdf").write_bytes(data)
    return f"{area_rel}/artifact.pdf"


def request(root, staging_rel, final_rel="Books/Book [aaaaaaaaaaaa]/und/local/Book [bbbbbbbbbbbb].pdf"):
    return CommitRequest(root_id=root.id, staging_relpath=staging_rel, final_relpath=final_rel,
                         registration={"kind": "test", "payload": {"id": "asset-1", "relpath": final_rel}})


def engine(db, fault=None):
    return CommitEngine(db, registrars={"test": registrar}, fault=fault)


def registered(db):
    try:
        return [tuple(r) for r in db.execute("SELECT id, relpath FROM registered")]
    except Exception:
        return []


def journal_states(db):
    return [r[0] for r in db.execute("SELECT state FROM commit_journal")]


def test_staging_area_lives_in_root_on_same_filesystem(root):
    area, rel = new_staging_area(root, purpose="import", owner_id="imp1")
    assert rel.startswith(".oneshelf/staging/")
    assert os.stat(area).st_dev == os.stat(root.path).st_dev
    meta = json.loads((area / "staging.json").read_text())
    assert meta["purpose"] == "import" and meta["owner_id"] == "imp1"


def test_staging_refuses_unavailable_root(db, root, tmp_path):
    (tmp_path / "lib" / ".oneshelf" / "root.json").unlink()
    with pytest.raises(StagingError):
        new_staging_area(root, purpose="import", owner_id="x")


def test_successful_commit(db, root):
    rel = stage(root)
    req = request(root, rel)
    engine(db).commit(req)
    final = os.path.join(root.path, req.final_relpath)
    assert Path(final).read_bytes() == b"%PDF-1.7 fake but staged"
    assert not os.path.exists(os.path.join(root.path, rel))
    assert registered(db) == [("asset-1", req.final_relpath)]
    assert journal_states(db) == ["done"]


def test_commit_never_overwrites_existing_final_file(db, root):
    req = request(root, stage(root))
    final = os.path.join(root.path, req.final_relpath)
    os.makedirs(os.path.dirname(final))
    Path(final).write_bytes(b"precious existing file")
    with pytest.raises(CommitError):
        engine(db).commit(req)
    assert Path(final).read_bytes() == b"precious existing file"
    assert registered(db) == []


def test_commit_rejects_staging_outside_staging_dir(db, root):
    os.makedirs(os.path.join(root.path, "Books"))
    Path(os.path.join(root.path, "Books", "x.pdf")).write_bytes(b"x")
    with pytest.raises(CommitError):
        engine(db).commit(request(root, "Books/x.pdf"))


@pytest.mark.parametrize("point", FAULT_POINTS)
def test_crash_at_every_boundary_recovers_idempotently(db, root, point):
    rel = stage(root)
    req = request(root, rel)

    def fault(name):
        if name == point:
            raise Crash(name)

    with pytest.raises(Crash):
        engine(db, fault).commit(req)

    first = engine(db).recover()
    second = engine(db).recover()
    assert second.changed == 0  # repeatable reconciliation

    final = os.path.join(root.path, req.final_relpath)
    assert registered(db) == [("asset-1", req.final_relpath)]
    assert Path(final).read_bytes() == b"%PDF-1.7 fake but staged"
    assert journal_states(db) == ["done"]
    assert first.changed >= 1


def test_crash_after_journal_with_lost_staging_aborts_without_registration(db, root):
    rel = stage(root)
    req = request(root, rel)

    def fault(name):
        if name == "after_journal":
            raise Crash(name)

    with pytest.raises(Crash):
        engine(db, fault).commit(req)
    os.remove(os.path.join(root.path, rel))
    engine(db).recover()
    assert registered(db) == []
    assert journal_states(db) == ["aborted"]


def test_moved_but_corrupted_final_is_never_registered(db, root):
    req = request(root, stage(root))

    def fault(name):
        if name == "after_move":
            raise Crash(name)

    with pytest.raises(Crash):
        engine(db, fault).commit(req)
    with open(os.path.join(root.path, req.final_relpath), "ab") as f:
        f.write(b"torn write")
    report = engine(db).recover()
    assert registered(db) == []
    assert journal_states(db) == ["aborted"]
    assert report.aborted == 1


def test_recovery_skips_unavailable_roots_without_changes(db, root, tmp_path):
    req = request(root, stage(root))

    def fault(name):
        if name == "after_move":
            raise Crash(name)

    with pytest.raises(Crash):
        engine(db, fault).commit(req)
    marker = tmp_path / "lib" / ".oneshelf" / "root.json"
    saved = marker.read_text()
    marker.unlink()  # root goes offline
    report = engine(db).recover()
    assert report.skipped_unavailable == 1
    assert journal_states(db) == ["moved"]
    assert registered(db) == []
    marker.write_text(saved)  # root returns
    engine(db).recover()
    assert journal_states(db) == ["done"]
    assert registered(db) == [("asset-1", req.final_relpath)]


def test_crash_between_link_and_unlink_recovers(db, root):
    """Both staged and final copies exist with a pending journal: recovery keeps one verified copy."""
    import shutil as _shutil

    rel = stage(root)
    req = request(root, rel)

    def fault(name):
        if name == "after_journal":
            raise Crash(name)

    with pytest.raises(Crash):
        engine(db, fault).commit(req)
    final = Path(root.path) / req.final_relpath
    final.parent.mkdir(parents=True)
    _shutil.copyfile(Path(root.path) / rel, final)  # the link happened; the unlink did not
    engine(db).recover()
    assert not (Path(root.path) / rel).exists()
    assert registered(db) == [("asset-1", req.final_relpath)]
    assert journal_states(db) == ["done"]


def test_failing_registrar_leaves_verified_journal_that_recovers_later(db, root):
    req = request(root, stage(root))
    calls = {"n": 0}

    def flaky(conn, payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("database busy")
        registrar(conn, payload)

    with pytest.raises(RuntimeError):
        CommitEngine(db, registrars={"test": flaky}).commit(req)
    assert journal_states(db) == ["verified"]
    assert registered(db) == []
    CommitEngine(db, registrars={"test": flaky}).recover()
    assert journal_states(db) == ["done"]
    assert registered(db) == [("asset-1", req.final_relpath)]


def test_persistently_failing_registration_does_not_abort_recovery_of_others(db, root):
    good = request(root, stage(root), final_rel="Books/good [cccccccccccc].pdf")
    bad_req = CommitRequest(root_id=root.id, staging_relpath=stage(root, b"%PDF-1.7 other"),
                            final_relpath="Books/bad [dddddddddddd].pdf",
                            registration={"kind": "broken", "payload": {}})

    def broken(conn, payload):
        raise RuntimeError("schema mismatch")

    engine_all = CommitEngine(db, registrars={"test": registrar, "broken": broken})
    with pytest.raises(RuntimeError):
        engine_all.commit(bad_req)

    def fault(name):
        if name == "after_verify":
            raise Crash(name)

    with pytest.raises(Crash):
        CommitEngine(db, registrars={"test": registrar, "broken": broken}, fault=fault).commit(good)

    report = engine_all.recover()  # must not raise
    assert len(report.errors) == 1 and "schema mismatch" in report.errors[0]
    assert registered(db) == [("asset-1", good.final_relpath)]
    states = dict(db.execute("SELECT final_relpath, state FROM commit_journal").fetchall())
    assert states == {good.final_relpath: "done", bad_req.final_relpath: "verified"}
