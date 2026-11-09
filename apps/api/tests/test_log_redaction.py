import logging

import pytest

from app.log_redaction import RedactTokens, redact


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/ws/live?token=eyJ.abc.def", "/ws/live?token=[redacted]"),
        ("/ws/live?token=eyJ.abc&tag_id=2", "/ws/live?token=[redacted]&tag_id=2"),
        ("/ws/live?tag_id=2&token=eyJ.abc", "/ws/live?tag_id=2&token=[redacted]"),
        (
            '"WebSocket /ws/live?token=eyJ.a" [accepted]',
            '"WebSocket /ws/live?token=[redacted]" [accepted]',
        ),
        ("/assets?limit=10", "/assets?limit=10"),
    ],
)
def test_redact(raw: str, expected: str) -> None:
    assert redact(raw) == expected


def test_filter_rewrites_formatted_args_and_keeps_the_record() -> None:
    # uvicorn logs with %-style args, so the token is in record.args, not record.msg.
    record = logging.LogRecord(
        "uvicorn.error",
        logging.INFO,
        __file__,
        1,
        '%s - "WebSocket %s" [accepted]',
        ("1.2.3.4:5", "/ws/live?token=secret.jwt"),
        None,
    )
    assert RedactTokens().filter(record) is True
    assert record.getMessage() == '1.2.3.4:5 - "WebSocket /ws/live?token=[redacted]" [accepted]'
