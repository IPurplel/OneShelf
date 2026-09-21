"""Container liveness follows readiness at the actual configured listener."""
import json
import os
import sys
from urllib.request import ProxyHandler, build_opener


def main():
    host = os.environ.get("ONESHELF_HOST", "127.0.0.1")
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    if ":" in host:
        host = f"[{host}]"
    url = f"http://{host}:{os.environ.get('ONESHELF_PORT', '8420')}/api/ready"
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
            ready = json.load(response).get("ready") is True
    except (OSError, ValueError):
        ready = False
    return 0 if ready else 1


if __name__ == "__main__":
    sys.exit(main())
