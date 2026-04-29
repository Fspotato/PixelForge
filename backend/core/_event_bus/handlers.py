import importlib

from celery import shared_task

from .envelope import EventEnvelope


@shared_task(name="_event_bus.dispatch_async_event")
def dispatch_async_event(handler_path: str, envelope_dict: dict):
    """在 Celery worker 中執行非同步事件 handler"""
    module_path, func_name = handler_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    handler = getattr(module, func_name)
    envelope = EventEnvelope(**envelope_dict)
    handler(envelope)
