import logging
import re

TOKEN_PATTERNS = (
    (re.compile(r"(/review/t/)[^/?\s]+"), r"\1[redacted]"),
    (re.compile(r"([?&](?:invite|token)=)[^&\s]+"), r"\1[redacted]"),
)


def redact_url_tokens(value: str) -> str:
    for pattern, replacement in TOKEN_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


class AccessLogRedactionFilter(logging.Filter):
    """Remove bearer-style URL tokens before a record reaches log handlers."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(
                redact_url_tokens(value) if isinstance(value, str) else value
                for value in record.args
            )
        if isinstance(record.msg, str):
            record.msg = redact_url_tokens(record.msg)
        return True


def configure_safe_access_logging() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AccessLogRedactionFilter) for item in access_logger.filters):
        access_logger.addFilter(AccessLogRedactionFilter())
