"""Generator sessions (Master §12.2–12.3).

The workflow is deliberately made of separate, explicit steps: discover and preview, run the packaged
tests, Generate a `.osp`, and only then — as its own action elsewhere — install it. A submission bundle
is written to disk for the developer to send; OneShelf never publishes anything (ledger A1).
"""
from __future__ import annotations

import json
import sqlite3
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from oneshelf.db.connection import transaction
from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.generator.discovery import DiscoveryError, discover
from oneshelf.generator.draft import Draft, build_draft, write_package
from oneshelf.generator.repair import Diagnosis, RepairError, RepairOutcome, diagnose, repair
from oneshelf.plugins.package import load_package
from oneshelf.plugins.runtime import run_packaged_tests


class GeneratorError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftRecord:
    id: str
    start_url: str
    name: str
    state: str
    package_path: str | None
    bundle_path: str | None
    created_at: str
    updated_at: str


def _serialize(draft: Draft) -> dict:
    payload = {k: v for k, v in asdict(draft).items() if k != "site"}
    payload["permissions"] = draft.permissions
    payload["rejected_domains"] = list(draft.site.rejected_domains) if draft.site else []
    payload["fixtures"] = {k: v.decode("utf-8", errors="replace") for k, v in draft.fixtures.items()}
    payload["fetches"] = draft.site.fetches if draft.site else []
    return payload


class GeneratorService:
    def __init__(self, conn: sqlite3.Connection, *, work_dir: Path, dev_hosts: dict | None = None,
                 dev_test_source: bool = False) -> None:
        self.conn = conn
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.dev_hosts = dev_hosts or {}
        self.dev_test_source = dev_test_source

    # -- drafts -------------------------------------------------------------------------------------

    def _dev(self) -> dict | None:
        """Dev hosts exist only when this instance explicitly enables the Test Source."""
        return self.dev_hosts if (self.dev_test_source and self.dev_hosts) else None

    async def start(self, url: str, *, name: str) -> tuple[str, Draft]:
        try:
            site = await discover(url, dev_hosts=self._dev(), allow_http=bool(self._dev()))
        except DiscoveryError as exc:
            raise GeneratorError(str(exc)) from exc
        draft = build_draft(site, name=name)
        draft_id, now = new_id(), utcnow_iso()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO generator_drafts (id, start_url, name, state, draft_json, created_at, updated_at)"
                " VALUES (?,?,?,'discovered',?,?,?)",
                (draft_id, url, name, json.dumps(_serialize(draft)), now, now))
        return draft_id, draft

    def _row(self, draft_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM generator_drafts WHERE id = ?", (draft_id,)).fetchone()
        if row is None:
            raise GeneratorError("unknown draft")
        return row

    def preview(self, draft_id: str) -> dict:
        row = self._row(draft_id)
        payload = json.loads(row["draft_json"])
        payload.update({"id": row["id"], "state": row["state"], "start_url": row["start_url"],
                        "package_path": row["package_path"], "bundle_path": row["bundle_path"]})
        return payload

    def list_drafts(self) -> list[DraftRecord]:
        rows = self.conn.execute("SELECT * FROM generator_drafts ORDER BY created_at DESC").fetchall()
        return [DraftRecord(r["id"], r["start_url"], r["name"], r["state"], r["package_path"], r["bundle_path"],
                            r["created_at"], r["updated_at"]) for r in rows]

    def _draft(self, draft_id: str) -> Draft:
        payload = json.loads(self._row(draft_id)["draft_json"])
        return Draft(manifest=payload["manifest"], source=payload["source"], recipes=payload["recipes"],
                     tests=payload["tests"], fixtures={k: v.encode() for k, v in payload["fixtures"].items()},
                     confidence=payload["confidence"], unsupported=payload["unsupported"],
                     notes=payload["notes"])

    def _package_for(self, draft_id: str) -> Path:
        draft = self._draft(draft_id)
        return Path(write_package(draft, self.work_dir / f"{draft_id}.osp"))

    async def run_tests(self, draft_id: str) -> dict:
        """The packaged tests, run offline against the pages discovery captured."""
        package = load_package(self._package_for(draft_id))
        report = await run_packaged_tests(package)
        return {"passed": report.passed, "cases": len(package.tests.cases), "failures": list(report.failures)}

    def generate(self, draft_id: str) -> dict:
        path = self._package_for(draft_id)
        load_package(path)                      # a draft is only "generated" once it validates
        with transaction(self.conn):
            self.conn.execute("UPDATE generator_drafts SET state = 'generated', package_path = ?, updated_at = ?"
                              " WHERE id = ?", (str(path), utcnow_iso(), draft_id))
        return {"path": str(path), "installed": False}

    def submission_bundle(self, draft_id: str) -> dict:
        """A bundle the developer can send somewhere themselves. Nothing leaves this machine here."""
        row = self._row(draft_id)
        package_path = Path(row["package_path"]) if row["package_path"] else self._package_for(draft_id)
        draft = self._draft(draft_id)
        bundle = self.work_dir / f"{draft_id}-submission.zip"
        network = draft.manifest["network"]
        metadata = {"plugin_id": draft.manifest["id"], "name": draft.manifest["name"],
                    "version": draft.manifest["version"], "start_url": row["start_url"],
                    "capabilities": draft.manifest["capabilities"], "confidence": draft.confidence,
                    "unsupported": draft.unsupported, "notes": draft.notes,
                    "permissions": draft.permissions,
                    "prepared_at": utcnow_iso(), "published": False}
        with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("submission.json", json.dumps(metadata, indent=1, ensure_ascii=False))
            archive.write(package_path, package_path.name)
        with transaction(self.conn):
            self.conn.execute("UPDATE generator_drafts SET bundle_path = ?, updated_at = ? WHERE id = ?",
                              (str(bundle), utcnow_iso(), draft_id))
        return {"path": str(bundle), "published": False, "metadata": metadata}

    # -- repair -------------------------------------------------------------------------------------

    async def diagnose(self, package) -> Diagnosis:
        return await diagnose(package, dev_hosts=self._dev(), allow_http=bool(self._dev()))

    async def repair(self, package) -> RepairOutcome:
        destination = self.work_dir / f"{package.id}-{utcnow_iso().replace(':', '')}.osp"
        try:
            return await repair(package, destination=destination, dev_hosts=self._dev(),
                                allow_http=bool(self._dev()))
        except (RepairError, DiscoveryError) as exc:
            raise GeneratorError(str(exc)) from exc
