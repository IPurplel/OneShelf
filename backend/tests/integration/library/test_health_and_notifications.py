"""Master §21 (capability health) and §30/§35/§44 (notifications, Needs Attention)."""
from datetime import UTC, datetime, timedelta

import pytest

from oneshelf.downloads.contract import Settings

from oneshelf.domain.clock import utcnow_iso
from oneshelf.domain.ids import new_id
from oneshelf.health.service import HealthService
from oneshelf.notifications.service import NotificationService
from oneshelf.sources.health import record_signal

NOW = utcnow_iso()


@pytest.fixture
def health(db):
    return HealthService(db)


def signals(db, source, capability, outcomes, *, version="1.0.0"):
    for outcome, category in outcomes:
        record_signal(db, source, capability, outcome, category, version)


# -- §21 capability health ---------------------------------------------------------------------------

def test_a_single_failure_does_not_degrade_a_source(db, health):
    signals(db, "mangadex", "search", [("success", None), ("failure", "timeout")])
    assert health.evaluate("mangadex")["search"].state == "healthy"


def test_repeated_failures_degrade_then_become_unavailable(db, health):
    signals(db, "mangadex", "search", [("failure", "timeout")] * 3)
    assert health.evaluate("mangadex")["search"].state == "degraded"
    signals(db, "mangadex", "search", [("failure", "timeout")] * 3)
    assert health.evaluate("mangadex")["search"].state == "unavailable"


def test_recovery_requires_repeated_success_to_avoid_flapping(db, health):
    signals(db, "mangadex", "catalog", [("failure", "parser_failure")] * 3)
    assert health.evaluate("mangadex")["catalog"].state == "degraded"
    signals(db, "mangadex", "catalog", [("success", None)])
    assert health.evaluate("mangadex")["catalog"].state == "degraded"   # one success is not recovery
    signals(db, "mangadex", "catalog", [("success", None)])
    assert health.evaluate("mangadex")["catalog"].state == "healthy"


def test_rate_limit_and_auth_are_their_own_states(db, health):
    signals(db, "mangadex", "reader", [("failure", "rate_limit")] * 3)
    assert health.evaluate("mangadex")["reader"].state == "rate_limited"
    signals(db, "3asq", "catalog", [("failure", "auth_failure")])
    assert health.evaluate("3asq")["catalog"].state == "reconnect_required"


def test_missing_content_never_degrades_a_source(db, health):
    signals(db, "mangadex", "reader", [("content_missing", "not_found")] * 6)
    assert health.evaluate("mangadex")["reader"].state == "healthy"


def test_parser_failures_are_diagnosed_with_the_plugin_version(db, health):
    signals(db, "mangadex", "catalog", [("failure", "parser_failure")] * 3, version="2.3.1")
    capability = health.evaluate("mangadex")["catalog"]
    assert capability.category == "parser_failure" and capability.plugin_version == "2.3.1"
    assert capability.hint == "plugin_update_may_be_needed"


def test_overall_state_is_the_worst_capability_and_persists(db, health):
    signals(db, "mangadex", "search", [("success", None)] * 2)
    signals(db, "mangadex", "catalog", [("failure", "parser_failure")] * 3)
    assert health.overall("mangadex") == "degraded"
    stored = db.execute("SELECT capability, state FROM source_health_state WHERE source_id = 'mangadex'").fetchall()
    assert {r["capability"]: r["state"] for r in stored} == {"search": "healthy", "catalog": "degraded"}


def test_health_never_rewrites_methods_sources_or_languages(db, health):
    signals(db, "mangadex", "catalog", [("failure", "parser_failure")] * 6)
    health.evaluate("mangadex")
    assert db.execute("SELECT count(*) FROM settings").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM download_jobs").fetchone()[0] == 0


def test_active_checks_are_explicit_low_priority_and_never_use_the_browser(db, health):
    calls = []

    class Runner:
        async def run(self, plugin_id, capability, inputs, *, priority):
            calls.append((plugin_id, capability, priority))
            return None

    import asyncio

    from oneshelf.net.governor import Priority

    asyncio.run(health.active_check("mangadex", "health", Runner(), browser_capabilities={"reader"}))
    assert calls == [("mangadex", "health", Priority.HEALTH)]
    with pytest.raises(ValueError):
        asyncio.run(health.active_check("mangadex", "reader", Runner(), browser_capabilities={"reader"}))
    assert len(calls) == 1   # browser probes are never started for health


# -- §30 notifications -------------------------------------------------------------------------------

@pytest.fixture
def notifications(db):
    return NotificationService(db)


def test_repeated_problems_update_one_notification(db, notifications):
    for work in range(20):
        notifications.reconnect_required("3asq", detail=f"work-{work}")
    active = notifications.active()
    assert len(active) == 1 and active[0].count == 20
    assert active[0].dedupe_key == "source-auth:3asq"


def test_low_storage_is_deduplicated_per_root(db, notifications):
    notifications.low_storage("root-a", free_bytes=1000)
    notifications.low_storage("root-a", free_bytes=900)
    notifications.low_storage("root-b", free_bytes=500)
    assert {n.dedupe_key for n in notifications.active()} == {"storage-low:root-a", "storage-low:root-b"}


def test_new_releases_are_grouped_per_work_with_safe_numbering(db, notifications):
    work = new_id()
    numeric = notifications.new_releases(work, "Solo Leveling", [{"number": "209"}, {"number": "210"}, {"number": "211"}])
    assert numeric.summary == "3 new releases · Ch. 209–211"
    mixed = notifications.new_releases(work, "Solo Leveling",
                                       [{"number": "209"}, {"number": None, "title": "Special"},
                                        {"number": None, "title": "Extra Story"}])
    assert mixed.summary == "3 new releases · Chapter 209, Special, Extra Story"
    assert len(notifications.active()) == 1   # one notification per Work


def test_seen_state_is_independent_from_reading_state(db, notifications):
    work = new_id()
    notifications.new_releases(work, "Solo Leveling", [{"number": "1"}])
    notifications.mark_all_seen()
    assert all(n.seen for n in notifications.active())
    assert db.execute("SELECT count(*) FROM reading_state").fetchone()[0] == 0   # INV-22


def test_clear_seen_keeps_unseen_and_underlying_state(db, notifications):
    notifications.download_failed("unit-1", "Chapter 1", category="media_invalid")
    notifications.mark_all_seen()
    notifications.reconnect_required("3asq")
    removed = notifications.clear_seen()
    keys = {n.dedupe_key for n in notifications.active()}
    assert removed == 1 and keys == {"source-auth:3asq"}


def test_resolved_notifications_linger_then_disappear(db):
    clock = {"now": datetime(2026, 9, 17, 12, 0, tzinfo=UTC)}
    service = NotificationService(db, clock=lambda: clock["now"])
    service.reconnect_required("3asq")
    service.resolve("source-auth:3asq")
    assert [n.state for n in service.active()] == ["resolved"]
    clock["now"] += timedelta(hours=2)
    assert service.active() == []


def test_needs_attention_lists_only_unresolved_actionable_problems(db, notifications):
    work = new_id()
    notifications.new_releases(work, "Solo Leveling", [{"number": "1"}])      # informational inbox item
    notifications.plugin_update_available("mangadex", "2.0.0")
    notifications.reconnect_required("3asq")
    notifications.low_storage("root-a", free_bytes=10)
    notifications.download_failed("unit-1", "Chapter 1", category="media_invalid")
    notifications.catalog_suspicious("mangadex", "Solo Leveling")
    attention = notifications.needs_attention()
    assert {n.dedupe_key for n in attention} == {"source-auth:3asq", "storage-low:root-a", "download-failed:unit-1",
                                                 "catalog-suspicious:mangadex"}
    assert all(len(n.actions) <= 2 for n in notifications.active())
    notifications.resolve("source-auth:3asq")
    assert "source-auth:3asq" not in {n.dedupe_key for n in notifications.needs_attention()}


def test_retention_is_bounded_by_age_and_count(db):
    clock = {"now": datetime(2026, 1, 1, tzinfo=UTC)}
    service = NotificationService(db, clock=lambda: clock["now"])
    for index in range(520):
        service.notify("informational", dedupe_key=f"plugin-update:{index}", title=f"Update {index}",
                       summary="update available")
    service.cleanup()
    assert len(service.all()) == 500
    clock["now"] += timedelta(days=40)
    service.notify("informational", dedupe_key="plugin-update:new", title="Fresh", summary="update available")
    service.cleanup()
    assert [n.dedupe_key for n in service.all()] == ["plugin-update:new"]


def test_background_noise_is_never_notified(db, notifications):
    assert notifications.should_notify("retry_succeeded") is False
    assert notifications.should_notify("health_probe") is False
    assert notifications.should_notify("cache_cleanup") is False
    assert notifications.should_notify("page_repaired") is False
    assert notifications.should_notify("download_failed") is True


def test_domain_changes_reach_every_connected_client(db):
    """Master §36: one internal event channel, multiple clients (no cloud service)."""
    import asyncio

    from oneshelf.catalog.trust import CatalogTrust
    from oneshelf.events.bus import EventBus
    from oneshelf.follow.service import FollowService
    from oneshelf.library.shelf import ShelfService

    async def scenario():
        bus = EventBus()
        first, second = bus.subscribe(), bus.subscribe()
        work_id = new_id()
        db.execute("INSERT INTO works (id, display_title, created_at, updated_at) VALUES (?,?,?,?)",
                   (work_id, "Solo Leveling", NOW, NOW))
        track_id = new_id()
        db.execute("INSERT INTO source_tracks (id, work_id, source_id, language, kind, created_at)"
                   " VALUES (?,?,?,?,?,?)", (track_id, work_id, "mangadex", "en", "source", NOW))
        ShelfService(db, events=bus).add(work_id)
        FollowService(db, CatalogTrust(db), events=bus).follow(work_id, language="en", source_id="mangadex",
                                                               track_id=track_id)
        NotificationService(db, events=bus).reconnect_required("mangadex")
        received = []
        for subscriber in (first, second):
            events = []
            while not subscriber.queue.empty():
                events.append((await subscriber.get()).type)
            received.append(events)
        return received

    first_events, second_events = asyncio.run(scenario())
    assert first_events == second_events == ["shelf.changed", "follow.changed", "notifications.changed"]


def test_source_recovered_is_silent_unless_it_is_turned_on(db, notifications):
    """§30.10: a source coming back is good news, not an interruption — optional, and off by default."""
    assert notifications.source_recovered("mangadex") is None
    assert db.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0

    Settings(db).set("global", None, "notifications.source_recovered", True)
    made = notifications.source_recovered("mangadex")
    assert made is not None and made.dedupe_key == "source-recovered:mangadex"
    assert db.execute("SELECT count(*) FROM notifications").fetchone()[0] == 1
