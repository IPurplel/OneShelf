"""Application wiring: startup recovery on boot and the C1 remote-access boundary (K4)."""
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.db.connection import open_database


@pytest.fixture
def config(tmp_path):
    return AppConfig.from_env({
        "ONESHELF_DATA_DIR": str(tmp_path / "data"),
        "ONESHELF_TRUSTED_NETWORKS": "192.168.1.0/24",
        "ONESHELF_TRUSTED_PROXIES": "10.0.0.2/32",
        "ONESHELF_ALLOWED_HOSTS": "testserver",
        "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"),
    })


def client(config, host):
    return TestClient(create_app(config), client=(host, 50000))


def test_startup_migrates_and_serves_health_to_loopback(config):
    with client(config, "127.0.0.1") as c:
        r = c.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok" and body["schema_version"] >= 1 and body["access"] == "loopback"
    assert Path(config.data_dir, "oneshelf.db").exists()


def test_lan_client_is_allowed(config):
    with client(config, "192.168.1.44") as c:
        assert c.get("/api/health").json()["access"] == "lan"


@pytest.mark.parametrize("path", ["/api/health", "/api/events", "/anything"])
def test_remote_client_is_denied_until_remote_auth_exists(config, path):
    with client(config, "203.0.113.50") as c:
        r = c.get(path)
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "REMOTE_AUTH_REQUIRED"


def test_forged_forwarded_for_cannot_bypass(config):
    with client(config, "203.0.113.50") as c:
        assert c.get("/api/health", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 401


def test_remote_client_via_trusted_proxy_is_denied(config):
    with client(config, "10.0.0.2") as c:
        assert c.get("/api/health", headers={"X-Forwarded-For": "198.51.100.4"}).status_code == 401


def test_startup_runs_recovery(config):
    Path(config.data_dir).mkdir(parents=True)
    with client(config, "127.0.0.1") as c:
        c.get("/api/health")
    with open_database(Path(config.data_dir) / "oneshelf.db") as conn:
        conn.execute("INSERT INTO imports (id, original_filename, mode, state, created_at, updated_at)"
                     " VALUES ('i1', 'x.pdf', 'copy', 'validating', '2026-01-01', '2026-01-01')")
    with client(config, "127.0.0.1") as c:
        assert c.get("/api/health").status_code == 200
    with open_database(Path(config.data_dir) / "oneshelf.db") as conn:
        assert conn.execute("SELECT state FROM imports WHERE id = 'i1'").fetchone()[0] == "failed"


def test_newer_database_schema_refuses_to_start(config):
    Path(config.data_dir).mkdir(parents=True)
    with client(config, "127.0.0.1") as c:
        c.get("/api/health")
    with open_database(Path(config.data_dir) / "oneshelf.db") as conn:
        conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (9999, 'future', 'x')")
    with pytest.raises(Exception, match="newer"):
        with client(config, "127.0.0.1"):
            pass


def test_server_does_not_trust_forwarded_headers_itself():
    from oneshelf.api.app import server_options

    assert server_options()["proxy_headers"] is False


def test_readiness_reports_what_startup_actually_did(config):
    """Deployments need a readiness probe that means something (Meta Prompt C9)."""
    with client(config, "127.0.0.1") as c:
        ready = c.get("/api/ready")
    assert ready.status_code == 200
    body = ready.json()
    assert body["ready"] is True
    assert body["schema_version"] >= 12 and body["migrations_pending"] == 0
    assert body["recovery"]["order"] and body["recovery"]["commits"] is not None   # recovery ran first
    assert "storage_roots" in body and "database" in body
