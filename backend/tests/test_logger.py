"""_logger 模組單元測試。"""

from __future__ import annotations

import json
import logging
from datetime import date
from unittest.mock import MagicMock

import pytest
from django.http import HttpResponse
from django.test import RequestFactory

from core._logger import get_logger
from core._logger.config import build_logging_config
from core._logger.filters import (
    AppLoggerFilter,
    ContextFilter,
    SensitiveDataFilter,
    SystemLoggerFilter,
    clear_context,
    set_context,
)
from core._logger.formatters import JSONFormatter
from core._logger.handlers import DailyFileHandler
from core._logger.middleware import RequestLoggingMiddleware


@pytest.fixture(autouse=True)
def clear_logger_context():
    clear_context()
    yield
    clear_context()


def test_context_filter_injects_context_fields():
    set_context(request_id="req-123", user_id="user-456", environment="test")
    record = logging.LogRecord(
        name="tests.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="context",
        args=(),
        exc_info=None,
    )

    ContextFilter().filter(record)

    assert record.request_id == "req-123"
    assert record.user_id == "user-456"
    assert record.environment == "test"
    assert record.module_name == "tests.logger"


def test_sensitive_data_filter_masks_message_and_extra_fields():
    record = logging.LogRecord(
        name="tests.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=20,
        msg="password=hunter2 token=abcd-1234",
        args=(),
        exc_info=None,
    )
    record.payload = {
        "password": "hunter2",
        "nested": {"api_key": "secret-value"},
        "token": "abcd-1234",
    }

    SensitiveDataFilter().filter(record)

    assert record.msg == "password=*** token=***"
    assert record.payload == {
        "password": "***",
        "nested": {"api_key": "***"},
        "token": "***",
    }


def test_json_formatter_outputs_structured_log():
    set_context(request_id="req-789", user_id="user-789", environment="test")
    record = logging.LogRecord(
        name="tests.logger",
        level=logging.WARNING,
        pathname=__file__,
        lineno=30,
        msg="quota warning",
        args=(),
        exc_info=None,
    )
    record.status_code = 429

    ContextFilter().filter(record)
    payload = json.loads(JSONFormatter().format(record))

    assert payload["level"] == "WARNING"
    assert payload["logger"] == "tests.logger"
    assert payload["message"] == "quota warning"
    assert payload["request_id"] == "req-789"
    assert payload["user_id"] == "user-789"
    assert payload["environment"] == "test"
    assert payload["status_code"] == 429
    assert "timestamp" in payload


def test_request_logging_middleware_generates_request_id(monkeypatch, settings):
    settings.LOGGER_ENABLE_MIDDLEWARE_LOGS = True
    captured_logs: list[tuple[str, dict[str, object] | None]] = []
    logger_mock = MagicMock()
    logger_mock.info.side_effect = lambda message, extra=None: captured_logs.append(
        (message, extra)
    )
    monkeypatch.setattr("core._logger.middleware.logger", logger_mock)
    monkeypatch.setattr("core._logger.middleware.uuid.uuid4", lambda: "req-generated")

    request = RequestFactory().get("/health/")
    middleware = RequestLoggingMiddleware(lambda _: HttpResponse(status=204))

    response = middleware(request)

    assert request._request_id == "req-generated"
    assert response.status_code == 204
    assert response["X-Request-ID"] == "req-generated"
    assert captured_logs == [
        (
            "request.started",
            {"method": "GET", "path": "/health/"},
        ),
        (
            "request.completed",
            {
                "method": "GET",
                "path": "/health/",
                "status_code": 204,
                "duration_ms": pytest.approx(0, abs=50),
            },
        ),
    ]


def test_request_logging_middleware_can_disable_request_logs(monkeypatch, settings):
    captured_logs: list[tuple[str, dict[str, object] | None]] = []
    logger_mock = MagicMock()
    logger_mock.info.side_effect = lambda message, extra=None: captured_logs.append(
        (message, extra)
    )
    logger_mock.exception = MagicMock()
    monkeypatch.setattr("core._logger.middleware.logger", logger_mock)
    monkeypatch.setattr("core._logger.middleware.uuid.uuid4", lambda: "req-generated")
    settings.LOGGER_ENABLE_MIDDLEWARE_LOGS = False

    request = RequestFactory().get("/health/")
    middleware = RequestLoggingMiddleware(lambda _: HttpResponse(status=204))

    response = middleware(request)

    assert request._request_id == "req-generated"
    assert response.status_code == 204
    assert response["X-Request-ID"] == "req-generated"
    assert captured_logs == []
    logger_mock.exception.assert_not_called()


def test_daily_file_handler_writes_date_based_log_file(tmp_path):
    handler = DailyFileHandler(directory=str(tmp_path), filename_prefix="dev")
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler._today = lambda: date(2026, 3, 20)

    record = logging.LogRecord(
        name="tests.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=99,
        msg="daily file log",
        args=(),
        exc_info=None,
    )
    handler.emit(record)
    handler.close()

    log_file = tmp_path / "dev-2026-03-20.log"
    assert log_file.exists() is True
    assert log_file.read_text(encoding="utf-8").strip() == "daily file log"


def test_build_logging_config_uses_explicit_environment_for_filename_prefix(tmp_path):
    config = build_logging_config(base_dir=tmp_path, environment="stage", debug=False)

    logger_file_handler = config["handlers"]["logger_file"]
    system_file_handler = config["handlers"]["system_file"]

    assert logger_file_handler["filename_prefix"] == "stage-logger"
    assert system_file_handler["filename_prefix"] == "stage"
    assert logger_file_handler["directory"] == str(tmp_path / "logs")
    assert system_file_handler["directory"] == str(tmp_path / "logs")


def test_build_logging_config_defaults_to_settings_django_env(settings, tmp_path):
    settings.DJANGO_ENV = "prod"
    settings.BASE_DIR = tmp_path
    settings.DEBUG = False

    config = build_logging_config()

    assert config["handlers"]["logger_file"]["filename_prefix"] == "prod-logger"
    assert config["handlers"]["system_file"]["filename_prefix"] == "prod"


def test_get_logger_marks_records_as_app_logger():
    logger = get_logger("tests.logger")

    message, kwargs = logger.process("hello", {})

    assert message == "hello"
    assert kwargs["extra"]["is_app_logger"] is True


def test_app_and_system_logger_filters_route_records():
    app_record = logging.LogRecord(
        name="tests.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=140,
        msg="app",
        args=(),
        exc_info=None,
    )
    app_record.is_app_logger = True
    system_record = logging.LogRecord(
        name="django.server",
        level=logging.INFO,
        pathname=__file__,
        lineno=150,
        msg="system",
        args=(),
        exc_info=None,
    )

    assert AppLoggerFilter().filter(app_record) is True
    assert AppLoggerFilter().filter(system_record) is False
    assert SystemLoggerFilter().filter(app_record) is False
    assert SystemLoggerFilter().filter(system_record) is True
