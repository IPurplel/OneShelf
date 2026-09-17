"""Host allowlist (DNS-rebinding defence) and same-origin checks for state-changing requests (ledger D-C3-13)."""
import pytest
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from oneshelf.api.guard import RequestGuardMiddleware


async def ok(request):
    return JSONResponse({"ok": True})


def client(allowed=("oneshelf.home.example",)):
    app = Starlette(routes=[Route("/api/x", ok, methods=["GET", "POST", "DELETE"])])
    app.add_middleware(RequestGuardMiddleware, allowed_hosts=allowed)
    return TestClient(app, client=("127.0.0.1", 5000))


@pytest.mark.parametrize("host", ["localhost:8420", "127.0.0.1:8420", "192.168.1.20:8420", "[::1]:8420",
                                  "oneshelf.home.example", "ONESHELF.home.example:443"])
def test_allowed_hosts(host):
    assert client().get("/api/x", headers={"Host": host}).status_code == 200


@pytest.mark.parametrize("host", ["evil.example", "attacker.example:8420", "oneshelf.home.example.evil.example", ""])
def test_rebinding_hosts_are_rejected(host):
    r = client().get("/api/x", headers={"Host": host})
    assert r.status_code == 421 and r.json()["error"]["code"] == "HOST_NOT_ALLOWED"


def test_cross_origin_state_change_is_rejected():
    c = client()
    r = c.post("/api/x", headers={"Host": "192.168.1.20:8420", "Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "CROSS_ORIGIN_REQUEST"
    assert c.delete("/api/x", headers={"Host": "192.168.1.20:8420", "Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert c.post("/api/x", headers={"Host": "192.168.1.20:8420", "Origin": "null"}).status_code == 403


def test_same_origin_and_non_browser_state_changes_are_allowed():
    c = client()
    assert c.post("/api/x", headers={"Host": "192.168.1.20:8420", "Origin": "http://192.168.1.20:8420"}).status_code == 200
    assert c.post("/api/x", headers={"Host": "192.168.1.20:8420"}).status_code == 200  # e.g. curl, no Origin
    assert c.get("/api/x", headers={"Host": "192.168.1.20:8420", "Origin": "http://evil.example"}).status_code == 200
