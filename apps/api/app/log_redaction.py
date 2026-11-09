"""Keep credentials out of logs.

The WebSocket JWT has to ride in the query string (browsers can't set headers on a WebSocket,
ADR 0005), and uvicorn logs the full path: `"WebSocket /ws/live?token=eyJ..." [accepted]`.
Anyone with log access could replay that token until it expires. This filter rewrites the record
before any handler formats it.
"""

import logging
import re

_TOKEN = re.compile(r"([?&]token=)[^&\s\"']+")


def redact(text: str) -> str:
    return _TOKEN.sub(r"\1[redacted]", text)


class RedactTokens(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = redact(message)
        if redacted != message:
            record.msg, record.args = redacted, None
        return True  # never drop the record, only rewrite it


def install() -> None:
    """Attach to uvicorn's loggers (WebSocket lines go to uvicorn.error, HTTP to uvicorn.access)."""
    for name in ("uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(RedactTokens())
