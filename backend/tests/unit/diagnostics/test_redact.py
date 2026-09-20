"""Master §43 / §48: diagnostics never store cookies, tokens, auth headers or passwords."""
import logging

from oneshelf.diagnostics.redact import RedactingFilter, redact_headers, redact_text, redact_url


def test_sensitive_headers_are_redacted():
    out = redact_headers({"Cookie": "sid=abc", "Set-Cookie": "sid=abc; Path=/", "Authorization": "Bearer xyz",
                          "Proxy-Authorization": "Basic q", "X-Api-Key": "k", "X-Auth-Token": "t", "Accept": "text/html"})
    assert out["Accept"] == "text/html"
    assert all(v == "[redacted]" for k, v in out.items() if k != "Accept")


def test_sensitive_query_parameters_are_redacted():
    url = "https://cdn.books.example/p.jpg?token=abc&sig=def&Expires=1&page=2&access_key=zz&X-Amz-Signature=q"
    out = redact_url(url)
    assert "abc" not in out and "def" not in out and "zz" not in out and "=q" not in out
    assert "page=2" in out and "Expires=1" in out


def test_free_text_patterns_are_redacted():
    text = 'Authorization: Bearer eyJhbGciOi.abc.def cookie="sid=SECRET123; theme=dark" password=hunter2 url=https://x.example/?token=tok1'
    out = redact_text(text)
    for secret in ("eyJhbGciOi", "SECRET123", "hunter2", "tok1"):
        assert secret not in out


def test_logging_filter_redacts_messages_and_args(caplog):
    logger = logging.getLogger("oneshelf.test.redaction")
    logger.addFilter(RedactingFilter())
    with caplog.at_level(logging.INFO, logger="oneshelf.test.redaction"):
        logger.info("fetch %s with %s", "https://b.example/x?session=S3CR3T", {"Cookie": "sid=C00KIE"})
    assert "S3CR3T" not in caplog.text and "C00KIE" not in caplog.text


def test_redaction_does_not_break_a_message_that_has_arguments(caplog):
    """Redacting the template removed its placeholders, so the record raised and was lost (I-18)."""
    logger = logging.getLogger("oneshelf.test.formatting")
    logger.addFilter(RedactingFilter())
    try:
        with caplog.at_level(logging.WARNING):
            logger.warning("fetch failed for %s with cookie=%s", "https://example.org/x", "session=secret")
    finally:
        logger.filters.clear()

    message = caplog.records[-1].getMessage()          # would raise before the fix
    assert "secret" not in message
    assert "example.org" in message
