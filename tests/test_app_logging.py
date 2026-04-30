import logging

from speakup.app_logging import make_formatter, redact_payload


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
    assert "hello" in output
    assert "req-123" in output
    assert "info" in output


def test_make_formatter_color_target_ignores_json_format():
    formatter = make_formatter(
        {"format": "json", "include_timestamps": False, "include_module": True},
        target="color",
    )

    output = formatter.format(_make_record(message="hello", extra={"request_id": "req-123"}))

    assert "\x1b[" in output
    assert "hello" in output
    assert "req-123" in output
    assert not output.lstrip().startswith("{")


def test_redact_payload_masks_sensitive_keys_and_token_values():
    payload = {
        "message": "Bearer abcdefghijklmnop",
        "api_key": "secret",
        "nested": [{"token": "value"}, {"ok": "safe"}],
    }

    redacted = redact_payload(payload)

    assert redacted["message"] == "***"
    assert redacted["api_key"] == "***"
    assert redacted["nested"][0]["token"] == "***"
    assert redacted["nested"][1]["ok"] == "safe"
