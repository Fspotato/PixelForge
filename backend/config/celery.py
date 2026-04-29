import logging
import os

from celery import Celery
from celery.signals import worker_process_init

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE",
    os.getenv("DJANGO_SETTINGS_MODULE", "config.settings.dev"),
)

app = Celery("config")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# core._event_bus 不在 INSTALLED_APPS 中，需手動載入其 task 模組
app.autodiscover_tasks(["core._event_bus"], related_name="handlers")


@worker_process_init.connect
def reset_file_handlers_after_fork(**kwargs):
    """Fork 後重置 DailyFileHandler，讓子程序重新嘗試開啟日誌檔案。"""
    from core._logger.handlers import DailyFileHandler

    for handler in logging.root.handlers:
        if isinstance(handler, DailyFileHandler):
            handler.after_fork()
    for logger in logging.Logger.manager.loggerDict.values():
        if not isinstance(logger, logging.Logger):
            continue
        for handler in logger.handlers:
            if isinstance(handler, DailyFileHandler):
                handler.after_fork()
