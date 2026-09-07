"""The UI shell: cache-busting so a shipped change actually reaches a browser."""

from __future__ import annotations

import os
import time

from app.main import WEB_DIR, asset_token, index_html


def test_assets_are_versioned():
    """A bare /app.js can sit in a browser cache indefinitely.

    StaticFiles sends an ETag but no Cache-Control, so browsers fall back to
    heuristic freshness and may not revalidate at all — a shipped UI change
    then simply never arrives and looks like a broken feature.
    """
    html = index_html()

    assert 'src="/app.js?v=' in html
    assert 'href="/style.css?v=' in html
    # The unversioned forms must be gone, or the old URL is still reachable.
    assert 'src="/app.js"' not in html
    assert 'href="/style.css"' not in html


def test_token_is_stable_while_nothing_changes():
    assert asset_token() == asset_token()


def test_token_changes_when_the_ui_changes():
    script = WEB_DIR / "app.js"
    before = asset_token()
    original = script.stat()
    try:
        future = time.time() + 5
        os.utime(script, (future, future))
        assert asset_token() != before
    finally:
        os.utime(script, (original.st_atime, original.st_mtime))

    assert asset_token() == before


def test_token_survives_an_unreadable_asset(monkeypatch):
    # A packaging quirk must not 500 the whole page.
    from app import main

    monkeypatch.setattr(main, "WEB_DIR", WEB_DIR / "does-not-exist")
    assert main.asset_token()
