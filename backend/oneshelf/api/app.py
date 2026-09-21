"""Application factory: migrations and startup recovery on boot, access boundary around everything."""
from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from http.cookies import SimpleCookie
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from oneshelf.api.access import AccessConfig
from oneshelf.api.sources import error as api_error
from oneshelf.api.guard import RequestGuardMiddleware
from oneshelf.api.middleware import AccessBoundaryMiddleware
from oneshelf.api.auth import PUBLIC_REMOTE_PATHS, router as auth_router
from oneshelf.api.discovery import router as discovery_router
from oneshelf.api.firstrun import router as firstrun_router
from oneshelf.api.generator import router as generator_router
from oneshelf.api.library import router as library_router
from oneshelf.api.shelf import router as shelf_router
from oneshelf.api.storage import router as storage_router
from oneshelf.api.works import router as works_router
from oneshelf.auth.policy import AccessPolicy
from oneshelf.auth.service import RemoteAuth
from oneshelf.auth.sessions import COOKIE_NAME
from oneshelf.backup.runner import BackupRunner
from oneshelf.backup.service import BackupService
from oneshelf.export.service import ExportService
from oneshelf.restore.service import RestoreService
from oneshelf.storage.migration import StorageMigration
from oneshelf.storage.roots import check_availability, list_roots
from oneshelf.follow.runner import FollowRunner
from oneshelf.generator.service import GeneratorService
from oneshelf.follow.service import FollowService
from oneshelf.health.service import HealthService
from oneshelf.library.shelf import ShelfService
from oneshelf.notifications.service import NotificationService
from oneshelf.diagnostics.store import DiagnosticsHandler, DiagnosticsStore, open_store
from oneshelf.downloads.contract import Settings
from oneshelf.downloads.engine import DownloadEngine
from oneshelf.downloads.runner import DownloadRunner
from oneshelf.reader.cache import ReaderCache
from oneshelf.reader.service import ReaderService
from oneshelf.api.sources import router as sources_router
from oneshelf.catalog.trust import CatalogTrust
from oneshelf.discovery.home import HomeService
from oneshelf.search.cache import DiscoveryCache
from oneshelf.search.service import SearchService
from oneshelf.search.url_resolve import UrlResolver
from oneshelf.net.governor import TrafficGovernor
from oneshelf.net.lazy_browser import LazyBrowser
from oneshelf.plugins.bundled import sync_bundled
from oneshelf.plugins.manager import PluginManager
from oneshelf.plugins.registry import parse_trusted_keys, registry_from_config
from oneshelf.sessions.login import LoginController
from oneshelf.sessions.manager import SessionManager
from oneshelf.sessions.store import SecretsStore, load_or_create_key
from oneshelf.sources.service import SourceService
from oneshelf.db.connection import open_database
from oneshelf.db.migrate import current_version, migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.events.bus import EventBus, sse_stream
from oneshelf.services.startup import run_startup_recovery

DEFAULT_DATA_DIR = ".oneshelf-dev"


@dataclass
class Services:
    conn: object
    plugins: PluginManager
    sessions: SessionManager
    governor: TrafficGovernor
    source_service: SourceService
    logins: LoginController
    registry: object | None = None
    cache: DiscoveryCache | None = None
    search: SearchService | None = None
    home: HomeService | None = None
    url_resolver: UrlResolver | None = None
    catalog: CatalogTrust | None = None
    downloads: DownloadEngine | None = None
    reader: ReaderService | None = None
    reader_cache: ReaderCache | None = None
    shelf: ShelfService | None = None
    follows: FollowService | None = None
    follow_runner: FollowRunner | None = None
    notifications: NotificationService | None = None
    health: HealthService | None = None
    migrations: StorageMigration | None = None
    backups: BackupService | None = None
    restore: RestoreService | None = None
    exports: ExportService | None = None
    remote_auth: RemoteAuth | None = None
    access_policy: AccessPolicy | None = None
    generator: GeneratorService | None = None
    settings: Settings | None = None
    diagnostics: DiagnosticsStore | None = None


@dataclass(frozen=True)
class AppConfig:
    data_dir: str
    access: AccessConfig
    allowed_hosts: tuple[str, ...] = ()
    session_key_file: str | None = None
    dev_test_source: bool = False
    dev_test_source_address: str | None = None
    registry_url: str | None = None
    registry_trusted_keys: str | None = None
    # The built interface, served from this same origin (§2.1). Empty in a source checkout that has
    # not run a frontend build; the API then serves itself and nothing else.
    web_root: str | None = None
    # The official adapters shipped with this build, installed once on a fresh library. Unset in
    # development and tests, which start with an empty library unless a directory is given.
    bundled_plugins_dir: str | None = None

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "oneshelf.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AppConfig:
        data_dir = env.get("ONESHELF_DATA_DIR", DEFAULT_DATA_DIR)
        web_root = env.get("ONESHELF_WEB_ROOT", "") or None
        return cls(
            web_root=web_root,
            bundled_plugins_dir=env.get("ONESHELF_BUNDLED_PLUGINS_DIR", "") or None,
            data_dir=data_dir,
            access=AccessConfig.from_strings(
                trusted_networks=env.get("ONESHELF_TRUSTED_NETWORKS", ""),
                trusted_proxies=env.get("ONESHELF_TRUSTED_PROXIES", ""),
            ),
            allowed_hosts=tuple(h.strip() for h in env.get("ONESHELF_ALLOWED_HOSTS", "").split(",") if h.strip()),
            session_key_file=env.get("ONESHELF_SESSION_KEY_FILE") or str(Path(data_dir) / "keys" / "session.key"),
            dev_test_source=env.get("ONESHELF_DEV_TEST_SOURCE", "").lower() in ("1", "true", "yes"),
            dev_test_source_address=env.get("ONESHELF_DEV_TEST_SOURCE_ADDRESS"),
            registry_url=env.get("ONESHELF_REGISTRY_URL") or None,
            registry_trusted_keys=env.get("ONESHELF_REGISTRY_TRUSTED_KEYS") or None,
        )

    def dev_hosts(self) -> dict[str, tuple[str, int]]:
        if not (self.dev_test_source and self.dev_test_source_address):
            return {}
        host, _, port = self.dev_test_source_address.rpartition(":")
        return {name: (host, int(port)) for name in ("testsource.example", "cdn.testsource.example")}


def _services_of(scope) -> Services | None:
    return getattr(scope.get("app").state, "services", None) if scope.get("app") is not None else None


def _effective_access_config(scope) -> AccessConfig | None:
    """Trusted networks configured in First Run or Settings apply without a restart."""
    services = _services_of(scope)
    return services.access_policy.current() if services and services.access_policy else None


def _observe_client(scope) -> None:
    services = _services_of(scope)
    access = scope["state"]["access"]
    if services and services.access_policy and access.kind != "loopback":
        services.access_policy.note_client(access.client_ip)   # ledger A2: notice a single gateway address


def _configured_hostname(scope) -> str | None:
    """The canonical hostname set in First Run or Settings is a valid Host without extra configuration."""
    services = _services_of(scope)
    return services.remote_auth.canonical_hostname if services and services.remote_auth else None


def _remote_session_authenticator(scope) -> bool:
    """A remote client is admitted only with a valid session cookie; sign-in itself stays reachable."""
    services = _services_of(scope)
    if services is None or services.remote_auth is None:
        return False
    if scope["type"] == "http" and scope.get("path") in PUBLIC_REMOTE_PATHS:
        return True
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    token = SimpleCookie(headers.get("cookie", "")).get(COOKIE_NAME)
    session = services.remote_auth.sessions.validate(token.value if token else None)
    if session is None:
        return False
    scope["state"]["remote_session"] = session
    return True


def _bundled_summary(outcomes) -> dict:
    return {
        "installed": sorted(o.plugin_id for o in outcomes if o.result in ("installed", "updated", "unchanged")),
        "failed": sorted(o.plugin_id for o in outcomes if o.result == "failed"),
        "pending_review": sorted(o.plugin_id for o in outcomes if o.result == "pending_review"),
    }


def _mount_web_interface(app: FastAPI, web_root: str | None) -> None:
    """Serve the built SPA from this origin, under every boundary the API already has.

    It is mounted after the routers, so `/api/...` is always answered by the API — a missing API route
    stays a JSON 404 instead of quietly becoming the interface. Client-side routes fall back to
    `index.html`, which is what lets the SPA own its own routing, and `StaticFiles` refuses anything
    that resolves outside the directory it was given.
    """
    if not web_root:
        return
    root = Path(web_root)
    if not (root / "index.html").is_file():
        return

    index = root / "index.html"
    app.mount("/assets", StaticFiles(directory=root / "assets", check_dir=False), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def interface(path: str) -> Response:
        if path == "api" or path.startswith("api/"):
            # The API answers for itself. A route that does not exist is a 404 in JSON, never the
            # interface loading as though nothing were wrong.
            return api_error(404, "NOT_FOUND", f"No such endpoint: /{path}")
        candidate = (root / path).resolve() if path else index
        if path and candidate.is_file() and candidate.is_relative_to(root.resolve()):
            return FileResponse(candidate)
        # Anything else is a screen the SPA draws for itself.
        return FileResponse(index, media_type="text/html", headers={"Cache-Control": "no-store"})


def create_app(config: AppConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        migrate(config.db_path, MIGRATIONS, snapshot_dir=Path(config.data_dir) / "snapshots")
        conn = open_database(config.db_path)
        app.state.startup_report = run_startup_recovery(conn)
        plugins = PluginManager(conn, store_dir=Path(config.data_dir) / "plugins",
                                trusted_keys=parse_trusted_keys(config.registry_trusted_keys))
        registry = registry_from_config(config.registry_url)
        plugins.reconcile_store()
        store = SecretsStore(Path(config.data_dir) / "secrets.db", load_or_create_key(config.session_key_file))
        sessions = SessionManager(conn, store, events=app.state.bus)
        governor = TrafficGovernor()
        browser = LazyBrowser()
        source_service = SourceService(conn, plugins, governor, sessions, dev_test_source=config.dev_test_source,
                                       dev_hosts=config.dev_hosts(), browser=browser)
        logins = LoginController(source_service, browser, sessions, governor)
        cache = DiscoveryCache(Path(config.data_dir) / "cache.db")
        settings = Settings(conn)
        # §43: local, redacted and bounded — opened once and rotated at startup.
        diagnostics = open_store(config.data_dir)
        diagnostics.rotate()
        # What the application already says about itself becomes its local diagnostic record (§43).
        diagnostics_handler = DiagnosticsHandler(diagnostics)
        logging.getLogger("oneshelf").addHandler(diagnostics_handler)
        engine = DownloadEngine(conn, source_service, plugins, governor, settings=settings, events=app.state.bus)
        reader_cache = ReaderCache(Path(config.data_dir) / "reader-cache", Path(config.data_dir) / "cache.db")
        reader = ReaderService(conn, source_service, reader_cache, engine, settings=settings, events=app.state.bus)
        catalog = CatalogTrust(conn)
        backups = BackupService(conn, config.db_path, backup_dir=Path(config.data_dir) / "backups")
        notifications = NotificationService(conn, events=app.state.bus)
        # The official adapters, installed through the normal plugin pipeline on a fresh library and kept
        # current afterwards — never re-adding one the owner removed, never approving new permissions.
        app.state.bundled_outcomes = await sync_bundled(conn, plugins, config.bundled_plugins_dir,
                                                        notifications=notifications)
        shelf = ShelfService(conn, events=app.state.bus)
        follows = FollowService(conn, catalog, events=app.state.bus)
        follow_runner = FollowRunner(conn, follows, source_service, plugins, catalog, notifications)
        engine.notifications = notifications
        app.state.services = Services(
            conn, plugins, sessions, governor, source_service, logins, registry, cache,
            SearchService(conn, source_service, cache), HomeService(conn, source_service, cache),
            UrlResolver(conn, plugins, source_service), catalog, engine, reader, reader_cache,
            shelf, follows, follow_runner, notifications, HealthService(conn, events=app.state.bus),
            StorageMigration(conn), backups, RestoreService(conn, config.db_path, backups=backups),
            ExportService(conn, downloads=engine), RemoteAuth(conn),
            AccessPolicy(conn, base=config.access),
            GeneratorService(conn, work_dir=Path(config.data_dir) / "generator", dev_hosts=config.dev_hosts(),
                             dev_test_source=config.dev_test_source),
            settings,
            diagnostics)
        runner = DownloadRunner(engine)
        await runner.start()
        await follow_runner.start()
        backup_runner = BackupRunner(backups, notifications=notifications)
        await backup_runner.start()
        try:
            yield
        finally:
            for login in list(logins._active.values()):
                await login.cancel()
            await runner.stop()
            await follow_runner.stop()
            await backup_runner.stop()
            await source_service.aclose()
            await browser.aclose()
            cache.close()
            reader_cache.close()
            store.close()
            logging.getLogger("oneshelf").removeHandler(diagnostics_handler)
            conn.close()

    app = FastAPI(title="OneShelf", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config
    app.state.bus = EventBus()

    @app.get("/api/health")
    def health(request: Request) -> dict:
        return {
            "status": "ok",
            "schema_version": current_version(config.db_path),
            "access": request.scope["state"]["access"].kind,
        }

    @app.get("/api/ready")
    def ready(request: Request) -> dict:
        """Readiness means migrations are applied and startup recovery has finished (Meta Prompt C9)."""
        report = getattr(app.state, "startup_report", None)
        services = getattr(app.state, "services", None)
        version = current_version(config.db_path)
        pending = max(0, max(m.version for m in MIGRATIONS) - version)
        roots = []
        if services is not None:
            roots = [{"id": r.id, "name": r.name, "available": check_availability(r).available}
                     for r in list_roots(services.conn)]
        return {
            "ready": services is not None and pending == 0,
            "schema_version": version,
            "migrations_pending": pending,
            "database": str(config.db_path),
            "recovery": {"order": list(getattr(report, "order", [])),
                         "commits": asdict(report.commits) if report is not None else None,
                         "scan": asdict(report.scan) if report is not None else None,
                         "downloads_recovered": getattr(report, "downloads_recovered", 0),
                         "jobs_failed": getattr(report, "jobs_failed", 0),
                         "staging_removed": getattr(report, "staging_removed", 0)},
            "storage_roots": roots,
            # Reported, never gating: one failed adapter must not make a local library unavailable (§3.3).
            "bundled_sources": _bundled_summary(getattr(app.state, "bundled_outcomes", [])),
        }

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        return StreamingResponse(
            sse_stream(app.state.bus, request.is_disconnected),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    app.include_router(sources_router)
    app.include_router(discovery_router)
    app.include_router(library_router)
    app.include_router(shelf_router)
    app.include_router(storage_router)
    app.include_router(works_router)
    app.include_router(auth_router)
    app.include_router(firstrun_router)
    app.include_router(generator_router)
    _mount_web_interface(app, config.web_root)
    app.add_middleware(AccessBoundaryMiddleware, config=config.access,
                       remote_authenticator=_remote_session_authenticator,
                       config_provider=_effective_access_config, observer=_observe_client)
    app.add_middleware(RequestGuardMiddleware, allowed_hosts=config.allowed_hosts,
                       extra_hosts=_configured_hostname)
    return app


def server_options() -> dict:
    """uvicorn must not rewrite the peer address from forwarded headers; OneShelf decides trust itself."""
    return {"proxy_headers": False, "forwarded_allow_ips": ""}


def main() -> None:  # pragma: no cover - thin process entry point
    import uvicorn

    config = AppConfig.from_env(os.environ)
    uvicorn.run(
        create_app(config),
        host=os.environ.get("ONESHELF_HOST", "127.0.0.1"),
        port=int(os.environ.get("ONESHELF_PORT", "8420")),
        **server_options(),
    )


if __name__ == "__main__":  # pragma: no cover - container entry point
    main()
