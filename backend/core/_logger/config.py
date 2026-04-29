"""全局 logger 設定。"""

from __future__ import annotations

import logging.config
from copy import deepcopy
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


def _resolve_environment(environment: str | None = None) -> str:
    if environment:
        return environment

    if hasattr(settings, "DJANGO_ENV") and settings.DJANGO_ENV:
        return settings.DJANGO_ENV

    if hasattr(settings, "ENV_FILE"):
        return settings.ENV_FILE.stem.removeprefix(".env.") or "dev"
    return "dev"


def _use_json_formatter(environment: str | None = None, debug: bool | None = None) -> bool:
    environment = _resolve_environment(environment)
    if environment in {"prod", "stage"}:
        return True
    if debug is not None:
        return not debug
    return not getattr(settings, "DEBUG", False)


def _resolve_log_directory(base_dir: Path | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir) / "logs"
    return Path(settings.BASE_DIR) / "logs"


def _resolve_log_filename_prefix(environment: str | None = None) -> str:
    return _resolve_environment(environment)


def build_logging_config(
    *,
    base_dir: Path | None = None,
    environment: str | None = None,
    debug: bool | None = None,
) -> dict[str, object]:
    resolved_environment = _resolve_environment(environment)
    formatter_name = "json" if _use_json_formatter(resolved_environment, debug) else "colored"
    file_formatter_name = "json" if _use_json_formatter(resolved_environment, debug) else "plain"

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "app_logger": {"()": "core._logger.filters.AppLoggerFilter"},
            "context": {"()": "core._logger.filters.ContextFilter"},
            "sensitive": {"()": "core._logger.filters.SensitiveDataFilter"},
            "system_logger": {"()": "core._logger.filters.SystemLoggerFilter"},
        },
        "formatters": {
            "json": {"()": "core._logger.formatters.JSONFormatter"},
            "colored": {"()": "core._logger.formatters.ColoredConsoleFormatter"},
            "plain": {"()": "core._logger.formatters.PlainTextFormatter"},
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": formatter_name,
                "filters": ["context", "sensitive"],
                "stream": "ext://sys.stdout",
            },
            "logger_file": {
                "class": "core._logger.handlers.DailyFileHandler",
                "formatter": file_formatter_name,
                "filters": ["context", "sensitive", "app_logger"],
                "directory": str(_resolve_log_directory(base_dir)),
                "filename_prefix": f"{_resolve_log_filename_prefix(resolved_environment)}-logger",
                "encoding": "utf-8",
            },
            "system_file": {
                "class": "core._logger.handlers.DailyFileHandler",
                "formatter": file_formatter_name,
                "filters": ["context", "sensitive", "system_logger"],
                "directory": str(_resolve_log_directory(base_dir)),
                "filename_prefix": _resolve_log_filename_prefix(resolved_environment),
                "encoding": "utf-8",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console", "logger_file", "system_file"],
        },
        "loggers": {
            "django": {
                "level": "INFO",
                "handlers": ["console", "logger_file", "system_file"],
                "propagate": False,
            },
            "core": {
                "level": "INFO",
                "handlers": ["console", "logger_file", "system_file"],
                "propagate": False,
            },
        },
        "environment": resolved_environment,
    }


try:
    LOGGING_CONFIG = build_logging_config()
except (ImproperlyConfigured, AttributeError):
    LOGGING_CONFIG = {}


def configure_logging() -> None:
    """套用 logger 設定。"""

    config = deepcopy(build_logging_config())
    config.pop("environment", None)
    logging.config.dictConfig(config)


__all__ = ["LOGGING_CONFIG", "build_logging_config", "configure_logging"]
