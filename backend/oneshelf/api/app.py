"""Application factory: migrations and startup recovery on boot, access boundary around everything."""
from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from oneshelf.api.access import AccessConfig
from oneshelf.api.guard import RequestGuardMiddleware
from oneshelf.api.middleware import AccessBoundaryMiddleware
from oneshelf.api.discovery import router as discovery_router
from oneshelf.api.library import router as library_router
from oneshelf.api.shelf import router as shelf_router
from oneshelf.follow.runner import FollowRunner
from oneshelf.follow.service import FollowService
from oneshelf.health.service import HealthService
from oneshelf.library.shelf import ShelfService
from oneshelf.notifications.service import NotificationService
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

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "oneshelf.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AppConfig:
        data_dir = env.get("ONESHELF_DATA_DIR", DEFAULT_DATA_DIR)
        return cls(
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
        engine = DownloadEngine(conn, source_service, plugins, governor, settings=settings, events=app.state.bus)
        reader_cache = ReaderCache(Path(config.data_dir) / "reader-cache", Path(config.data_dir) / "cache.db")
        reader = ReaderService(conn, source_service, reader_cache, engine, settings=settings, events=app.state.bus)
        catalog = CatalogTrust(conn)
        notifications = NotificationService(conn, events=app.state.bus)
        shelf = ShelfService(conn, events=app.state.bus)
        follows = FollowService(conn, catalog, events=app.state.bus)
        follow_runner = FollowRunner(conn, follows, source_service, plugins, catalog, notifications)
        engine.notifications = notifications
        app.state.services = Services(
            conn, plugins, sessions, governor, source_service, logins, registry, cache,
            SearchService(conn, source_service, cache), HomeService(conn, source_service, cache),
            UrlResolver(conn, plugins, source_service), catalog, engine, reader, reader_cache,
            shelf, follows, follow_runner, notifications, HealthService(conn, events=app.state.bus))
        runner = DownloadRunner(engine)
        await runner.start()
        await follow_runner.start()
        try:
            yield
        finally:
            for login in list(logins._active.values()):
                await login.cancel()
            await runner.stop()
            await follow_runner.stop()
            await source_service.aclose()
            await browser.aclose()
            cache.close()
            reader_cache.close()
            store.close()
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
    app.add_middleware(AccessBoundaryMiddleware, config=config.access)
    app.add_middleware(RequestGuardMiddleware, allowed_hosts=config.allowed_hosts)
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
