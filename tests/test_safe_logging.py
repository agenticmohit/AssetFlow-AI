import logging

from assetflow.core.logging import AccessLogRedactionFilter, redact_url_tokens


def test_sensitive_url_tokens_are_redacted():
    raw = "/review/t/super-secret-token?token=media-secret&invite=invite-secret"
    safe = redact_url_tokens(raw)

    assert "super-secret-token" not in safe
    assert "media-secret" not in safe
    assert "invite-secret" not in safe
    assert safe == "/review/t/[redacted]?token=[redacted]&invite=[redacted]"


def test_uvicorn_access_log_arguments_are_redacted():
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1", "GET", "/review/t/client-token", "1.1", 200),
        None,
    )

    assert AccessLogRedactionFilter().filter(record) is True
    assert "client-token" not in record.getMessage()
    assert "[redacted]" in record.getMessage()
