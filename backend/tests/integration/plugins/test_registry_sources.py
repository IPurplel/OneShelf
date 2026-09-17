"""Registry sources over HTTP(S) through the policy client, and registry wiring in the app (ledger A1)."""
import asyncio
import base64
import hashlib
import json
import socket

import pytest
from aiohttp import web
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from starlette.testclient import TestClient

from oneshelf.api.app import AppConfig, create_app
from oneshelf.net.http import HttpClient
from oneshelf.net.policy import EgressPolicy
from oneshelf.plugins.registry import HttpRegistry, RegistryError, registry_from_config
from testsource.build import build_package


class Hosts:
    def __init__(self, port):
        self.port = port

    async def resolve(self, host, port=0, family=socket.AF_INET):
        return [{"hostname": host, "host": "127.0.0.1", "port": self.port, "family": socket.AF_INET, "proto": 0, "flags": 0}]

    async def close(self):
        pass


def test_http_registry_reads_index_and_packages_through_policy_client(tmp_path):
    package = build_package(tmp_path / "ts.osp").read_bytes()
    index = {"schema": "oneshelf.registry/1", "plugins": [{"id": "oneshelf.test-source", "name": "TS", "version": "1.0.0",
             "url": "packages/ts.osp", "sha256": hashlib.sha256(package).hexdigest(), "trust_label": "community"}]}

    async def scenario():
        async def index_handler(request):
            return web.json_response(index)

        async def package_handler(request):
            return web.Response(body=package)

        app = web.Application()
        app.add_routes([web.get("/index.json", index_handler), web.get("/packages/ts.osp", package_handler)])
        runner = web.AppRunner(app, access_log=None)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        policy = EgressPolicy(domains=("registry.example",), allow_http=True, dev_loopback_exception=True)
        async with HttpClient(policy, resolver_backend=Hosts(port)) as client:
            registry = HttpRegistry("http://registry.example/index.json", client)
            entries = await registry.entries()
            data = await registry.fetch(entries[0])
        blocked_policy = EgressPolicy(domains=("registry.example",), allow_http=True)  # no loopback exception
        async with HttpClient(blocked_policy, resolver_backend=Hosts(port)) as client:
            with pytest.raises(Exception):
                await HttpRegistry("http://registry.example/index.json", client).entries()
        await runner.cleanup()
        return entries, data

    entries, data = asyncio.run(scenario())
    assert entries[0].id == "oneshelf.test-source" and data == package


def test_registry_configuration_parsing(tmp_path):
    assert registry_from_config(None) is None
    local = registry_from_config((tmp_path / "mirror").as_uri())
    assert local.location.startswith("file://")
    with pytest.raises(RegistryError):
        registry_from_config("ftp://registry.example/index.json")
    with pytest.raises(RegistryError):
        registry_from_config("https://user:pw@registry.example/index.json")


def make_mirror(tmp_path, *, label="community", signer=None):
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    data = build_package(mirror / "ts.osp").read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    entry = {"id": "oneshelf.test-source", "name": "OneShelf Test Source", "version": "1.0.0", "file": "ts.osp",
             "sha256": sha, "trust_label": label}
    if signer:
        entry["signature"] = {"key_id": "official-1", "value": base64.b64encode(signer.sign(sha.encode())).decode()}
    (mirror / "index.json").write_text(json.dumps({"schema": "oneshelf.registry/1", "plugins": [entry]}))
    return mirror


def api(tmp_path, **env):
    config = AppConfig.from_env({"ONESHELF_DATA_DIR": str(tmp_path / "data"), "ONESHELF_ALLOWED_HOSTS": "testserver",
                                 "ONESHELF_SESSION_KEY_FILE": str(tmp_path / "keys" / "session.key"), **env})
    return TestClient(create_app(config), client=("127.0.0.1", 50000))


def test_registry_api_lists_and_installs_with_signature_trust(tmp_path):
    key = Ed25519PrivateKey.generate()
    public = base64.b64encode(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    mirror = make_mirror(tmp_path, label="official", signer=key)
    with api(tmp_path, ONESHELF_REGISTRY_URL=mirror.as_uri(), ONESHELF_REGISTRY_TRUSTED_KEYS=f"official-1:{public}") as client:
        listing = client.get("/api/registry").json()
        assert listing["configured"] is True and listing["plugins"][0]["id"] == "oneshelf.test-source"
        from oneshelf.plugins.package import load_package
        permissions = sorted(load_package(mirror / "ts.osp").permissions)
        result = client.post("/api/registry/install", json={"plugin_id": "oneshelf.test-source",
                                                            "approved_permissions": permissions})
        assert result.status_code == 200 and result.json()["state"] == "active"
        source = client.get("/api/sources").json()["sources"][0]
        assert source["channel"] == "registry" and source["trust_label"] == "official"


def test_registry_api_when_not_configured(tmp_path):
    with api(tmp_path) as client:
        assert client.get("/api/registry").json() == {"configured": False, "plugins": []}
        r = client.post("/api/registry/install", json={"plugin_id": "x.y", "approved_permissions": []})
        assert r.status_code == 409 and r.json()["error"]["code"] == "REGISTRY_NOT_CONFIGURED"
