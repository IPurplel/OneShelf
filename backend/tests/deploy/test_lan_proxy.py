"""The bundled local-network proxy (compose service lan-proxy, profile "lan").

It serves OneShelf to the LAN on port 80 while OneShelf itself keeps listening on this machine only. The
one thing it must never do is make every visitor look like this machine: it connects from its own loopback
address, only that address may name the real visitor, and it overwrites X-Forwarded-For rather than
passing on whatever a client sent.
"""
import importlib.util
import re

from oneshelf.api.access import AccessConfig, classify

from .test_image_contains_bundled_sources import REPO
from .test_install_scripts import bin_dir, checkout, run, working_runtime  # noqa: F401  (fixtures)
from .test_registry_defaults import compose, env_example

TEMPLATE = REPO / "deploy" / "nginx" / "oneshelf.conf.template"


def container_start():
    spec = importlib.util.spec_from_file_location("container_start", REPO / "deploy" / "container_start.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def lan_proxy_service() -> str:
    text = compose()
    return text[text.index("  lan-proxy:"):]


def test_the_proxy_is_a_pinned_nginx_on_the_host_network_behind_a_profile():
    service = lan_proxy_service()
    assert re.search(r"image: docker\.io/library/nginx:\d+\.\d+\.\d+-alpine\n", service)
    assert 'profiles: ["lan"]' in service and "network_mode: host" in service
    assert 'ONESHELF_LAN_PORT: "${ONESHELF_LAN_PORT:-80}"' in service
    assert "./nginx/oneshelf.conf.template:/etc/nginx/templates/default.conf.template:ro" in service


def test_oneshelf_is_told_which_address_the_proxy_speaks_from():
    assert 'ONESHELF_LAN_PROXY_ADDRESS: "127.0.0.2"' in compose()
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "proxy_bind 127.0.0.2;" in template
    assert "server 127.0.0.1:${ONESHELF_PORT};" in template and "listen ${ONESHELF_LAN_PORT}" in template


def test_the_proxy_names_the_real_visitor_and_never_relays_a_forged_one():
    template = TEMPLATE.read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in template
    assert "$proxy_add_x_forwarded_for" not in template


def test_event_streams_and_uploads_pass_through_unbuffered():
    template = TEMPLATE.read_text(encoding="utf-8")
    for directive in ("proxy_buffering off;", "proxy_request_buffering off;", "client_max_body_size 0;",
                      "proxy_read_timeout 1h;"):
        assert directive in template
    assert "text/event-stream" not in template          # never compressed, so never held back by gzip


def test_container_start_adds_the_proxy_to_the_owner_s_trusted_proxies():
    trust = container_start().trust_lan_proxy
    environ = {"ONESHELF_LAN_PROXY_ADDRESS": "127.0.0.2", "ONESHELF_TRUSTED_PROXIES": "10.0.0.5/32"}
    trust(environ)
    assert environ["ONESHELF_TRUSTED_PROXIES"] == "10.0.0.5/32,127.0.0.2/32"
    trust(environ)                                        # starting again adds nothing twice
    assert environ["ONESHELF_TRUSTED_PROXIES"] == "10.0.0.5/32,127.0.0.2/32"
    empty = {"ONESHELF_LAN_PROXY_ADDRESS": "127.0.0.2"}
    trust(empty)
    assert empty["ONESHELF_TRUSTED_PROXIES"] == "127.0.0.2/32"
    untouched = {"ONESHELF_TRUSTED_PROXIES": "10.0.0.5/32"}
    trust(untouched)
    assert untouched == {"ONESHELF_TRUSTED_PROXIES": "10.0.0.5/32"}


def test_visitors_through_the_proxy_get_their_own_trust_and_no_more():
    config = AccessConfig.from_strings(trusted_networks="192.168.8.0/24", trusted_proxies="127.0.0.2/32")
    lan = classify("127.0.0.2", {"x-forwarded-for": "192.168.8.50"}, config)
    assert (lan.kind, lan.client_ip) == ("lan", "192.168.8.50")
    assert classify("127.0.0.2", {"x-forwarded-for": "203.0.113.9"}, config).kind == "remote"
    assert classify("127.0.0.2", {}, config).kind == "remote"            # the proxy alone is nobody
    assert classify("127.0.0.2", {"x-forwarded-for": "127.0.0.1"}, config).kind == "loopback"   # the server's own browser
    assert classify("127.0.0.1", {}, config).kind == "loopback"           # healthcheck and local tools, unchanged


def test_env_example_turns_the_proxy_on_at_port_80():
    lines = env_example().splitlines()
    assert "ONESHELF_LAN_PROXY=on" in lines and "ONESHELF_LAN_PORT=80" in lines


def test_install_starts_the_proxy_with_the_lan_profile(checkout, bin_dir):  # noqa: F811
    log = checkout / "runtime.log"
    working_runtime(bin_dir, "docker", log=log)
    run("install.sh", checkout, bin_dir, env={"ONESHELF_LAN_PORT": "18080"})
    assert re.search(r"compose .*--profile lan .*up -d", log.read_text())


def test_switching_the_proxy_off_leaves_it_out(checkout, bin_dir):  # noqa: F811
    log = checkout / "runtime.log"
    working_runtime(bin_dir, "docker", log=log)
    run("install.sh", checkout, bin_dir, env={"ONESHELF_LAN_PROXY": "off"})
    calls = log.read_text()
    assert re.search(r"compose .* up -d", calls) and "--profile lan" not in calls


def test_a_bad_proxy_setting_is_refused_before_anything_starts(checkout, bin_dir):  # noqa: F811
    working_runtime(bin_dir, "docker")
    result = run("install.sh", checkout, bin_dir, env={"ONESHELF_LAN_PROXY": "yes"})
    assert result.returncode != 0 and "ONESHELF_LAN_PROXY must be on or off" in result.stderr
    result = run("install.sh", checkout, bin_dir, env={"ONESHELF_LAN_PORT": "8420"})
    assert result.returncode != 0 and "must differ from ONESHELF_PORT" in result.stderr
