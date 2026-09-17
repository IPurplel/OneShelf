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
from oneshelf.api.middleware import AccessBoundaryMiddleware
from oneshelf.db.connection import open_database
from oneshelf.db.migrate import current_version, migrate
from oneshelf.db.schema import MIGRATIONS
from oneshelf.events.bus import EventBus, sse_stream
from oneshelf.services.startup import run_startup_recovery

DEFAULT_DATA_DIR = ".oneshelf-dev"


@dataclass(frozen=True)
class AppConfig:
    data_dir: str
    access: AccessConfig

    @property
    def db_path(self) -> Path:
        return Path(self.data_dir) / "oneshelf.db"

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> AppConfig:
        return cls(
            data_dir=env.get("ONESHELF_DATA_DIR", DEFAULT_DATA_DIR),
            access=AccessConfig.from_strings(
                trusted_networks=env.get("ONESHELF_TRUSTED_NETWORKS", ""),
                trusted_proxies=env.get("ONESHELF_TRUSTED_PROXIES", ""),
            ),
        )


def create_app(config: AppConfig) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Path(config.data_dir).mkdir(parents=True, exist_ok=True)
        migrate(config.db_path, MIGRATIONS, snapshot_dir=Path(config.data_dir) / "snapshots")
        with open_database(config.db_path) as conn:
            app.state.startup_report = run_startup_recovery(conn)
        yield

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

    app.add_middleware(AccessBoundaryMiddleware, config=config.access)
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
