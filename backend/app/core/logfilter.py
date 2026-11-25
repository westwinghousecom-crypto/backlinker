"""Keep OAuth codes and state out of access logs.

uvicorn logs every request line, including the query string. Google's redirect to /api/v1/google/callback carries a
one-time authorization ``code`` and the sealed ``state``; neither should sit in log files.
"""
import logging
import re

_SENSITIVE = re.compile(r"([?&](?:code|state|access_token|refresh_token|client_secret|secret)=)[^&\s\"']*", re.I)


def redact(text: str) -> str:
    return _SENSITIVE.sub(r"\1[redacted]", text)


class RedactQueryFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        return True


def install() -> None:
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        logging.getLogger(name).addFilter(RedactQueryFilter())
