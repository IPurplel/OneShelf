"""Markup responses include real-world XML feeds (arXiv, OPDS), which begin with a declaration."""
import pytest

from oneshelf.plugins.runtime import parse_document

ATOM = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>A Paper</title><id>http://arxiv.org/abs/2201.00978v1</id></entry>
</feed>"""


def test_a_feed_with_an_xml_declaration_is_parsed():
    document = parse_document(ATOM, url="http://export.arxiv.org/api/query")
    entries = document.css("entry")
    assert len(entries) == 1
    assert str(entries[0].css("title::text")[0]) == "A Paper"


def test_ordinary_html_still_parses():
    document = parse_document("<html><body><p class='x'>hi</p></body></html>", url="http://example.test/")
    assert str(document.css("p.x::text")[0]) == "hi"


def test_an_empty_body_does_not_explode():
    assert parse_document("", url="http://example.test/") is not None
