"""Testai logging_config.py - JsonFormatter ir setup_logging elgsenai."""

import json
import logging

from logging_config import JsonFormatter, _resolve_format, get_logger, setup_logging


def _make_record(message="test message", level=logging.INFO, **extra):
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_produces_valid_json():
    formatter = JsonFormatter()
    record = _make_record("Skelbimas rastas")

    output = formatter.format(record)
    parsed = json.loads(output)  # nemestų išimties, jei ne validus JSON

    assert parsed["message"] == "Skelbimas rastas"
    assert parsed["level"] == "INFO"
    assert parsed["logger"] == "test.logger"
    assert "timestamp" in parsed


def test_json_formatter_includes_extra_fields():
    formatter = JsonFormatter()
    record = _make_record("Scrape sėkmingas", source="ExampleJobBoard1", jobs_found=5)

    parsed = json.loads(formatter.format(record))

    assert parsed["source"] == "ExampleJobBoard1"
    assert parsed["jobs_found"] == 5


def test_json_formatter_handles_error_level():
    formatter = JsonFormatter()
    record = _make_record("Klaida", level=logging.ERROR)

    parsed = json.loads(formatter.format(record))

    assert parsed["level"] == "ERROR"


def test_resolve_format_explicit_true():
    assert _resolve_format(True) is True


def test_resolve_format_explicit_false():
    assert _resolve_format(False) is False


def test_resolve_format_from_env_json(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    assert _resolve_format(None) is True


def test_resolve_format_from_env_console(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "console")
    assert _resolve_format(None) is False


def test_resolve_format_defaults_to_console_when_unset(monkeypatch):
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    assert _resolve_format(None) is False


def test_setup_logging_json_mode_produces_parseable_output(capsys, monkeypatch):
    setup_logging(json_format=True)
    logger = get_logger("test.setup")
    logger.info("test žinutė", extra={"custom_field": "value"})

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]
    parsed = json.loads(line)  # turi būti parsinamas kaip JSON

    assert parsed["message"] == "test žinutė"
    assert parsed["custom_field"] == "value"


def test_setup_logging_console_mode_is_human_readable(capsys):
    setup_logging(json_format=False)
    logger = get_logger("test.setup2")
    logger.info("paprasta žinutė")

    captured = capsys.readouterr()
    line = captured.out.strip().splitlines()[-1]

    # Console formatas NĖRA validus JSON (tai žmogui skaitomas tekstas)
    assert "paprasta žinutė" in line
    assert "INFO" in line
