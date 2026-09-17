"""Master §42 approved defaults live in exactly one registry (Meta Prompt D2)."""
from datetime import timedelta

import pytest

from oneshelf.settings.defaults import DEFAULTS


def test_backup_defaults():
    assert DEFAULTS.backup.library_interval == timedelta(days=7)
    assert DEFAULTS.backup.full_backup_automatic is False
    assert DEFAULTS.backup.retain_verified == 4


def test_cache_defaults():
    assert DEFAULTS.discovery_cache.ttl == timedelta(days=7)
    assert DEFAULTS.discovery_cache.cap_bytes == 250 * 1024**2
    assert DEFAULTS.reader_cache.ttl == timedelta(days=7)
    assert DEFAULTS.reader_cache.cap_bytes == 5 * 1024**3


def test_reading_defaults():
    assert DEFAULTS.auto_download.enabled is False  # INV-08
    assert DEFAULTS.auto_download.engagement_threshold == pytest.approx(0.12)
    assert DEFAULTS.auto_download.read_ahead_units == 5
    assert DEFAULTS.reader.auto_mark_read_threshold == pytest.approx(0.97)
    assert DEFAULTS.reader.smart_controls_hide_after == timedelta(seconds=3)
    assert DEFAULTS.reader.remember_per_work is True
    assert DEFAULTS.reader.preload_next == 7
    assert DEFAULTS.reader.preload_previous == 4


def test_download_and_follow_defaults():
    assert DEFAULTS.downloads.http_concurrency == 4
    assert DEFAULTS.downloads.browser_concurrency == 1
    assert DEFAULTS.downloads.max_retries == 3
    assert DEFAULTS.downloads.fallback_mode == "preferred_ask"
    assert DEFAULTS.follow.check_interval == timedelta(hours=12)
    assert DEFAULTS.follow.jitter > timedelta(0)


def test_retention_defaults():
    assert DEFAULTS.notifications.resolved_visible_for == timedelta(hours=1)
    assert DEFAULTS.notifications.history_max_age == timedelta(days=30)
    assert DEFAULTS.notifications.history_max_entries == 500
    assert DEFAULTS.export.activity_max_age == timedelta(days=30)
    assert DEFAULTS.export.activity_max_jobs == 100
    assert DEFAULTS.export.default_output == "folder"
    assert DEFAULTS.diagnostics.max_age == timedelta(days=7)
    assert DEFAULTS.diagnostics.max_bytes == 100 * 1024**2
    assert DEFAULTS.importing.default_mode == "copy"


def test_storage_and_staging_defaults():
    assert DEFAULTS.storage.reserve_fraction == pytest.approx(0.05)
    assert DEFAULTS.storage.reserve_cap_bytes == 5 * 1024**3
    assert DEFAULTS.storage.warning_multiplier == 2
    assert DEFAULTS.staging.success_leftover_ttl == timedelta(hours=24)
    assert DEFAULTS.staging.resumable_partial_ttl == timedelta(days=7)


def test_catalog_and_auth_defaults():
    assert DEFAULTS.catalog.suspicious_loss_fraction == pytest.approx(0.5)
    assert DEFAULTS.catalog.suspicious_min_units_lost == 5
    assert DEFAULTS.auth.local_auth_enabled is False
    assert DEFAULTS.auth.lan_auth_enabled is False
    assert DEFAULTS.auth.remote_session_lifetime == timedelta(days=30)


def test_defaults_are_immutable():
    with pytest.raises(Exception):
        DEFAULTS.downloads.http_concurrency = 99  # type: ignore[misc]
