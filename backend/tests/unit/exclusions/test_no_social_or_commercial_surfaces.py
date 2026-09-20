"""§49 EX-16 to EX-22: no feed, comments, followers, chat, ads, payments or achievements.

OneShelf is a private library, not a place where anyone is watched, sold to, or scored. Following a
*work* is not following a person: there is no other person here, so none of these surfaces can exist
without something below failing first.
"""
import importlib.util
import re

from .conftest import BACKEND, code_lines, frontend_sources, python_sources

SOCIAL_ROUTE = re.compile(r"/(feed|timeline|comments?|reviews?|ratings?|followers|friends|chat|messages?|"
                          r"ads?|sponsored|checkout|payments?|billing|plans?|achievements?|badges?|streaks?|"
                          r"leaderboards?|points?)(/|$)")
SOCIAL_IDENTIFIER = re.compile(r"\b(post_comment|add_comment|comment_thread|follower_count|followers|"
                               r"send_message|chat_room|ad_slot|ad_unit|impression|checkout_session|"
                               r"subscription_plan|achievement|badge_earned|leaderboard|streak_count|"
                               r"xp_points)\b", re.IGNORECASE)
COMMERCIAL_PACKAGES = ["stripe", "paypalrestsdk", "braintree", "razorpay", "adyen"]


def test_no_route_opens_a_social_or_commercial_surface(routes):
    assert [path for path in routes if SOCIAL_ROUTE.search(path)] == []


def test_no_table_stores_comments_followers_or_purchases(schema):
    tables = re.findall(r"CREATE TABLE (?:IF NOT EXISTS )?(\w+)", schema)
    assert [t for t in tables if SOCIAL_ROUTE.search(f"/{t}/") or SOCIAL_IDENTIFIER.search(t)] == []
    # "follows" is following a work; a followers table would be following a person.
    assert "follows" in tables and "followers" not in tables


def test_nothing_in_the_product_builds_one_of_these():
    offenders = [f"{path.name}:{number}: {line.strip()}"
                 for path, number, line in code_lines(python_sources() + frontend_sources())
                 if SOCIAL_IDENTIFIER.search(line)]
    assert offenders == []


def test_no_payment_processor_is_installed():
    assert [n for n in COMMERCIAL_PACKAGES if importlib.util.find_spec(n) is not None] == []


def test_the_interface_never_offers_one_of_these_in_either_language():
    """A surface reaches a person through its words, so the strings are guarded too (§1, §2.3)."""
    strings = (BACKEND.parent / "frontend" / "src" / "i18n" / "strings.ts").read_text(encoding="utf-8")
    # "Review" here is a person reviewing a plugin or an export before it happens — a safety step, and
    # the opposite of a product review. What is excluded is rating, selling and broadcasting.
    forbidden = re.compile(r'"[^"]*(\bcomment\b|write a review|leave a review|user review|star rating|'
                           r'your rating|rate this|\bfollower|\bfriends\b|\bchat\b|advertisement|sponsored|'
                           r'checkout|subscribe|upgrade to|achievement|\bbadge|leaderboard|\bstreak)[^"]*"',
                           re.IGNORECASE)
    assert [m.group(0) for m in forbidden.finditer(strings)] == []
