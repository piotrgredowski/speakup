import logging

from speakup.app_logging import make_formatter


def _make_record(*, message: str, extra: dict) -> logging.LogRecord:
    logger = logging.getLogger("speakup.test")
    return logger.makeRecord(
        name=logger.name,
        level=logging.INFO,
        fn=__file__,
        lno=1,
        msg=message,
        args=(),
        exc_info=None,
        extra=extra,
    )


def test_make_formatter_text_places_request_id_first():
    formatter = make_formatter({"format": "text", "include_timestamps": False, "include_module": True}, colors=False)

    output = formatter.format(_make_record(message="hello", extra={"request_id": "req-123", "foo": "bar"}))

    assert output.startswith("request_id=req-123")
    assert "level=info" in output
    assert "logger=speakup.test" in output
    assert "event=hello" in output
    assert "foo=bar" in output


def test_make_formatter_json_places_request_id_first():
    formatter = make_formatter({"format": "json", "include_timestamps": False, "include_module": True}, colors=False)

    output = formatter.format(_make_record(message="hello", extra={"request_id": "req-123", "foo": "bar"}))

    assert output.startswith('{"request_id":')
    assert '"level": "info"' in output
    assert '"logger": "speakup.test"' in output
    assert '"event": "hello"' in output
    assert '"foo": "bar"' in output


def test_make_formatter_text_adds_ansi_colors_when_enabled():
    formatter = make_formatter({"format": "text", "include_timestamps": False, "include_module": True}, colors=True)

    output = formatter.format(_make_record(message="hello", extra={"request_id": "req-123"}))

    assert "\x1b[" in output
    assert "request_id=req-123" in output
    assert "level=info" in output
    assert output.endswith("\x1b[0m")
