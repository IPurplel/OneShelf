"""Run the OneShelf Test Source for manual development: python -m testsource [port]."""
import sys

from aiohttp import web

from testsource.server import create_app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8421
    print(f"OneShelf Test Source on 127.0.0.1:{port} (use ONESHELF_DEV_TEST_SOURCE=1 "
          f"ONESHELF_DEV_TEST_SOURCE_ADDRESS=127.0.0.1:{port})")
    web.run_app(create_app(), host="127.0.0.1", port=port, access_log=None)
