"""測試環境設定。"""

# ruff: noqa: F403,F405

from .base import *

DJANGO_ENV = "test"

DEBUG = False

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test.sqlite3",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True


# 測試環境不使用真實 Stripe API，避免網路請求阻塞測試
STRIPE_SECRET_KEY = ""
STRIPE_WEBHOOK_SECRET = ""

LOGGING = build_logging_config(
    base_dir=BASE_DIR,
    environment=DJANGO_ENV,
    debug=DEBUG,
)
