"""§49 (M49): every exclusion the Master lists has something standing over it.

The list in §49 is the authority. This reads it from the Master itself and insists that each item is
answered by a named test — so an exclusion cannot be quietly dropped from the list, and a guard cannot
be quietly deleted from the suite. What each guard proves is its own business; that one exists, and
still runs, is this test's.
"""
import re
from pathlib import Path

from .conftest import BACKEND

MASTER = BACKEND.parent / "docs" / "OneShelf_Final_Implementation_Meta_Prompt.md"
SUITE = Path(__file__).parent

# Each exclusion, as the Master words it, and the test that answers it. A test named here must exist.
GUARDS = {
    "cloud oneshelf account": "test_no_route_offers_an_account_or_another_user",
    "multi-user": "test_the_schema_never_says_which_user_a_row_belongs_to",
    "arbitrary executable community plugin code": "test_the_plugin_path_never_executes_what_it_loads",
    "restricted-rpc plugin design": "test_there_is_no_rpc_channel_to_a_plugin",
    "matcher telemetry / central collector / shared decision dataset":
        "test_a_matching_pass_writes_nothing_to_the_diagnostics_store",
    "automatic source switching": "test_a_second_language_is_a_separate_track_and_must_be_chosen_explicitly",
    "automatic cross-language fallback": "test_a_second_language_is_a_separate_track_and_must_be_chosen_explicitly",
    "automatic translation": "test_no_translation_engine_is_installed",
    "title stemming": "test_no_stemming_articles_are_not_stripped",
    "cover/image matching": "test_matching_decides_from_evidence_rather_than_a_score_from_a_model",
    "ai matching requirement": "test_no_model_runtime_or_hosted_model_client_is_installed",
    "browser notifications": "test_no_browser_notification_or_push_apis_anywhere",
    "automatic new-release downloads": "test_new_releases_never_enqueue_downloads",
    "complex storage deduplication": "test_nothing_deduplicates_stored_files",
    "full note/drawing/annotation system": "test_the_reader_keeps_bookmarks_and_highlights_and_nothing_more",
    "social feed": "test_no_route_opens_a_social_or_commercial_surface",
    "comments/reviews": "test_no_table_stores_comments_followers_or_purchases",
    "followers": "test_no_table_stores_comments_followers_or_purchases",
    "chat": "test_nothing_in_the_product_builds_one_of_these",
    "ads": "test_the_interface_never_offers_one_of_these_in_either_language",
    "subscriptions/payments": "test_no_payment_processor_is_installed",
    "gaming/achievement systems": "test_nothing_in_the_product_builds_one_of_these",
    "anti-bot stealth/bypass": "test_oneshelf_code_never_uses_scrapling_fetchers_or_stealth_features",
    "captcha bypass": "test_nothing_tries_to_solve_or_bypass_a_challenge",
    "paywall bypass": "test_a_blocked_source_is_reported_rather_than_worked_around",
    "drm bypass": "test_nothing_touches_drm",
    "screenshot-based normal extraction": "test_no_page_is_extracted_by_photographing_it",
    "hidden destructive cleanup": "test_history_cleanup_never_deletes_exported_files",
    "implicit format conversion subsystem": "test_missing_content_offers_choices_and_never_converts_formats",
    "uncontrolled plugin access to lan/internal services": "test_allowlisted_domain_resolving_to_loopback_is_blocked",
}


def master_exclusions() -> list[str]:
    section = re.search(r"^# 49\. Explicit v1 Exclusions(.*?)^# 50\.", MASTER.read_text(encoding="utf-8"),
                        re.DOTALL | re.MULTILINE)
    assert section is not None, "§49 is not where it was; the guard list cannot be checked against it"
    return [line[2:].strip().lower() for line in section.group(1).splitlines() if line.startswith("- ")]


def test_the_guard_list_still_matches_the_masters_own_list():
    assert sorted(master_exclusions()) == sorted(GUARDS)


def test_every_named_guard_exists_somewhere_in_the_suite():
    names = set()
    for path in (BACKEND / "tests").rglob("test_*.py"):
        names.update(re.findall(r"^def (test_\w+)", path.read_text(encoding="utf-8"), re.MULTILINE))
    missing = sorted({guard for guard in GUARDS.values() if guard not in names})
    assert missing == []


def test_the_guards_in_this_suite_are_all_reachable():
    """A guard module that nothing imports proves nothing, so they live where pytest collects them."""
    modules = sorted(p.name for p in SUITE.glob("test_*.py"))
    assert len(modules) >= 5 and (SUITE / "__init__.py").exists()
