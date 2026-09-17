"""Master §14: Extraction Contracts, method precedence, Smart Retry and fallback rules."""
import pytest

from oneshelf.downloads.contract import (
    METHODS,
    ExtractionContract,
    FallbackDecision,
    Settings,
    may_fall_back,
    next_method,
    resolve_method,
)

CONTRACT = ExtractionContract(source_id="mangadex", language="en", reading_unit_id="u1", output_format="cbz",
                              method="html_api", mode="preferred_ask")


def test_contract_round_trips_through_json():
    restored = ExtractionContract.from_json(CONTRACT.to_json())
    assert restored == CONTRACT


def test_method_precedence(db):
    settings = Settings(db)
    assert resolve_method(settings, "mangadex", plugin_recommendation="reader_media").method == "reader_media"
    settings.set("global", None, "extraction.method", "html_api")
    assert resolve_method(settings, "mangadex", plugin_recommendation="reader_media").method == "html_api"
    settings.set("source", "mangadex", "extraction.method", "browser")
    assert resolve_method(settings, "mangadex", plugin_recommendation="reader_media").method == "browser"
    resolved = resolve_method(settings, "mangadex", plugin_recommendation="reader_media", one_time="direct")
    assert resolved.method == "direct" and resolved.origin == "one_time"
    assert resolve_method(settings, "other.source", plugin_recommendation="reader_media").method == "html_api"


def test_mode_precedence_and_default(db):
    settings = Settings(db)
    assert resolve_method(settings, "mangadex", plugin_recommendation="direct").mode == "preferred_ask"
    settings.set("global", None, "extraction.mode", "strict")
    assert resolve_method(settings, "mangadex", plugin_recommendation="direct").mode == "strict"
    settings.set("source", "mangadex", "extraction.mode", "automatic")
    settings.set("source", "mangadex", "extraction.fallback_order", ["reader_media", "browser"])
    resolved = resolve_method(settings, "mangadex", plugin_recommendation="direct")
    assert resolved.mode == "automatic" and resolved.fallback_order == ("reader_media", "browser")


def test_invalid_settings_are_rejected(db):
    settings = Settings(db)
    with pytest.raises(ValueError):
        settings.set("source", "mangadex", "extraction.method", "screenshots")
    with pytest.raises(ValueError):
        settings.set("source", "mangadex", "extraction.mode", "whatever")
    with pytest.raises(ValueError):
        settings.set("nowhere", None, "extraction.method", "direct")


@pytest.mark.parametrize("category,allowed", [
    ("parser_failure", True), ("selector_missing", True), ("media_invalid", True), ("not_found", True),
    ("auth_failure", False),        # waits for reconnect instead
    ("rate_limit", False),          # waits out the limit
    ("captcha_required", False),    # action required, never a method change
    ("source_outage", False),
    ("server_error", False),
    ("blocked", False),
])
def test_fallback_is_only_for_method_specific_failures(category, allowed):
    assert may_fall_back(category) is allowed


def test_smart_retry_stays_within_the_method_before_any_fallback():
    decision = next_method(CONTRACT, attempts=1, retry_budget=3, category="parser_failure")
    assert decision == FallbackDecision("retry", "html_api", None)
    decision = next_method(CONTRACT, attempts=3, retry_budget=3, category="parser_failure")
    assert decision.action == "ask" and decision.method is None


def test_strict_mode_never_falls_back():
    strict = ExtractionContract(**{**CONTRACT.__dict__, "mode": "strict"})
    assert next_method(strict, attempts=3, retry_budget=3, category="parser_failure").action == "fail"


def test_automatic_mode_follows_the_user_order_and_stops_at_the_end():
    automatic = ExtractionContract(**{**CONTRACT.__dict__, "mode": "automatic",
                                      "fallback_order": ("reader_media", "browser")})
    first = next_method(automatic, attempts=3, retry_budget=3, category="parser_failure")
    assert first == FallbackDecision("fallback", "reader_media", "parser_failure")
    after_first = ExtractionContract(**{**automatic.__dict__, "method": "reader_media",
                                        "attempted_methods": ("html_api", "reader_media")})
    second = next_method(after_first, attempts=3, retry_budget=3, category="parser_failure")
    assert second == FallbackDecision("fallback", "browser", "parser_failure")
    exhausted = ExtractionContract(**{**automatic.__dict__, "method": "browser",
                                      "attempted_methods": ("html_api", "reader_media", "browser")})
    assert next_method(exhausted, attempts=3, retry_budget=3, category="parser_failure").action == "fail"


def test_auth_and_rate_limit_produce_waiting_decisions_not_fallback():
    assert next_method(CONTRACT, attempts=3, retry_budget=3, category="auth_failure").action == "wait_for_session"
    assert next_method(CONTRACT, attempts=3, retry_budget=3, category="rate_limit").action == "wait_for_rate_limit"


def test_contract_never_changes_source_language_or_output_on_fallback():
    automatic = ExtractionContract(**{**CONTRACT.__dict__, "mode": "automatic", "fallback_order": ("browser",)})
    decision = next_method(automatic, attempts=3, retry_budget=3, category="media_invalid")
    switched = automatic.with_method(decision.method)
    assert switched.method == "browser"
    assert (switched.source_id, switched.language, switched.reading_unit_id, switched.output_format) == \
           (automatic.source_id, automatic.language, automatic.reading_unit_id, automatic.output_format)
    assert switched.attempted_methods == ("html_api", "browser")


def test_all_master_methods_are_modelled():
    assert METHODS == ("direct", "html_api", "reader_media", "browser")
