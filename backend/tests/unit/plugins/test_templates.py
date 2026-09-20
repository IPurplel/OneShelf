"""Composed resource URLs (Master §9, §41.1): real APIs return a base, a hash and bare filenames."""
import pytest

from oneshelf.plugins.package import PackageError
from oneshelf.plugins.schema import Extract, FieldSpec
from oneshelf.plugins.runtime import render_template, resolve_values
from oneshelf.plugins.templates import TemplateError, render

DOCUMENT = {"baseUrl": "https://uploads.example", "chapter": {"hash": "abc", "data": ["1.png", "2.png"]}}


def test_document_values_are_resolved_once_per_page():
    extract = Extract(values={"base": FieldSpec(json="$.baseUrl"), "hash": FieldSpec(json="$.chapter.hash")},
                      items=FieldSpec(json="$.chapter.data[*]"),
                      fields={"url": FieldSpec(template="{base}/data/{hash}/{item}", required=True)})
    values = resolve_values(DOCUMENT, extract)
    assert values == {"base": "https://uploads.example", "hash": "abc"}
    assert render_template("{base}/data/{hash}/{item}", values, item="1.png") == \
        "https://uploads.example/data/abc/1.png"


def test_a_template_may_only_use_known_names():
    with pytest.raises(PackageError):
        from oneshelf.plugins.package import validate_templates
        validate_templates(Extract(values={"base": FieldSpec(json="$.baseUrl")},
                                   items=FieldSpec(json="$.chapter.data[*]"),
                                   fields={"url": FieldSpec(template="{base}/{unknown}/{item}")}),
                           capability="reader", inputs=["unit_key"])


def test_a_field_cannot_be_both_a_selector_and_a_template():
    with pytest.raises(ValueError):
        FieldSpec(css="img::attr(src)", template="{base}/{item}")


def test_missing_values_leave_the_field_empty_rather_than_inventing_text():
    values = {"base": "https://uploads.example"}
    assert render_template("{base}/data/{hash}/{item}", values, item="1.png") is None


def test_a_recipe_may_ask_for_the_tracks_language_but_not_arbitrary_inputs():
    """§4: a Language Track's language is core context a multi-language source needs (MangaDex)."""
    from oneshelf.plugins.templates import TemplateError, validate_url_template

    validate_url_template("{base_url}/feed?lang={language}", {"language"})
    with pytest.raises(TemplateError):
        validate_url_template("{base_url}/feed?lang={language}", set())        # declared inputs still rule
    with pytest.raises(TemplateError):
        validate_url_template("{base_url}/feed?x={session_token}", {"session_token"})


def test_a_recipe_may_follow_a_url_its_own_catalog_produced():
    """§8: direct URLs. The egress policy still decides what may be fetched (INV-15)."""
    from oneshelf.plugins.templates import TemplateError, validate_url_template

    validate_url_template("{url}", {"url"})
    with pytest.raises(TemplateError):
        validate_url_template("{url}/pages", {"url"})        # no building on top of a supplied URL
    with pytest.raises(TemplateError):
        validate_url_template("{url}", set())


# A recipe sometimes has to request a URL the source itself gave us — a viewer page whose address the
# catalog captured, say. Percent-encoding the whole thing turns it into a path segment, so there is an
# explicit encoder for it, and it refuses anything that is not plainly an http(s) URL.

def test_an_absolute_url_can_be_requested_as_it_was_given():
    url = "https://www.webtoons.com/en/fantasy/tower-of-god/season-1-ep-2/viewer?title_no=95&episode_no=3"
    assert render("{url:absolute}", {"url": url}, base_url="https://www.webtoons.com") == url


@pytest.mark.parametrize("value", [
    "javascript:alert(1)",
    "file:///etc/passwd",
    "data:text/html,<script>",
    "https://user:pass@example.test/x",          # credentials never travel in a recipe's URL
    "https://example.test/x\nHost: elsewhere",   # no header splitting
    "//example.test/x",                          # scheme-relative is not an absolute URL
    "not a url",
])
def test_the_absolute_encoder_refuses_anything_that_is_not_a_plain_http_url(value):
    with pytest.raises(TemplateError):
        render("{u:absolute}", {"u": value}, base_url="https://example.test")
