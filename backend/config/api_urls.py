from celery.result import AsyncResult
from django.http import HttpRequest, JsonResponse
from django.middleware.csrf import get_token
from django.urls import include, path
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie

from config.celery import app as celery_app
from core._task_queue.tasks import ping_task


def ping(_request: HttpRequest) -> JsonResponse:
    return JsonResponse({"status": "ok"})


@ensure_csrf_cookie
def csrf_token(request: HttpRequest) -> JsonResponse:
    """提供前端測試介面初始化 CSRF token。"""
    return JsonResponse({"csrf_token": get_token(request)})


def health_check(_request: HttpRequest) -> JsonResponse:
    """系統健康檢查端點"""
    checks: dict = {}

    # DB 檢查
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = {"status": "ok"}
    except Exception as e:
        checks["database"] = {"status": "error", "detail": str(e)}

    # Redis 檢查
    try:
        import redis
        from django.conf import settings

        r = redis.from_url(settings.REDIS_URL)
        r.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}

    # Celery 檢查
    try:
        inspect = celery_app.control.inspect(timeout=2.0)
        ping_result = inspect.ping()
        if ping_result:
            checks["celery"] = {"status": "ok", "workers": len(ping_result)}
        else:
            checks["celery"] = {"status": "warning", "detail": "沒有可用的 worker"}
    except Exception as e:
        checks["celery"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(c["status"] == "ok" for c in checks.values()) else "degraded"

    return JsonResponse({
        "status": overall,
        "version": "0.1.0",
        "checks": checks,
    })


@csrf_exempt
def trigger_ping_task(_request: HttpRequest) -> JsonResponse:
    task = ping_task.delay()
    return JsonResponse({"task_id": task.id, "state": task.state}, status=202)


def get_task_status(_request: HttpRequest, task_id: str) -> JsonResponse:
    task_result = AsyncResult(task_id, app=celery_app)
    return JsonResponse(
        {
            "task_id": task_result.id,
            "state": task_result.state,
            "result": task_result.result if task_result.successful() else None,
        }
    )


urlpatterns = [
    # 系統端點
    path("system/csrf/", csrf_token, name="system-csrf"),
    path("system/health/", health_check, name="system-health"),
    path("system/ping/", ping, name="system-ping"),
    path("system/tasks/ping/", trigger_ping_task, name="system-task-ping"),
    path("system/tasks/<str:task_id>/", get_task_status, name="system-task-status"),
    # 模組端點
    path("auth/", include("core.auth.urls")),
    path("accounts/", include("core.accounts.urls")),
    path("ai-providers/", include("core.ai_providers.urls")),
    path("catalog/", include("core.catalog.urls")),
    path("payments/", include("core.payments.urls")),
    path("subscriptions/", include("core.subscriptions.urls")),
    path("audit-log/", include("core.audit_log.urls")),
    path("notifications/", include("core.notifications.urls")),
    path("rbac/", include("core.rbac.urls")),
    path("api-keys/", include("core.api_keys.urls")),
    path("files/", include("core.file_storage.urls")),
]
