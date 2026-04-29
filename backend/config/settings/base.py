from datetime import timedelta
from pathlib import Path

import environ

from core._logger.config import build_logging_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_DIR = BASE_DIR / "env"
DJANGO_ENV = environ.Env().str("DJANGO_ENV", default="dev")


def _resolve_env_file() -> Path:
    explicit_env_file = environ.Env().str("DJANGO_ENV_FILE", default="")
    if explicit_env_file:
        return Path(explicit_env_file)
    return ENV_DIR / f".env.{DJANGO_ENV}"


env = environ.Env()
ENV_FILE = _resolve_env_file()
if ENV_FILE.exists():
    environ.Env.read_env(ENV_FILE)


SECRET_KEY = env(
    "DJANGO_SECRET_KEY",
    default="unsafe-default-secret-key",
)

DEBUG = env.bool("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["127.0.0.1"])

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["http://127.0.0.1:8002"],
)

CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://127.0.0.1:8002",
        "http://127.0.0.1:8001",
    ],
)


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # 第三方套件
    "corsheaders",
    "drf_spectacular",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_celery_beat",
    # 內部核心模組
    "core._task_queue",
    # 外部核心模組
    "core.accounts",
    "core.auth",
    "core.ai_providers",
    "core.catalog",
    "core.payments",
    "core.subscriptions",
    "core.audit_log",
    "core.notifications",
    "core.rbac",
    "core.api_keys",
    "core.file_storage",
    # PixelForge 業務模組
    "modules._forge_shared",
    "modules.style_presets",
    "modules.generation_jobs",
    "modules.asset_library",
    "modules.image_processing",
    "modules.admin_operations",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "core._logger.middleware.RequestLoggingMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


DATABASES = {
    "default": env.db(
        "DATABASE_URL",
        default="postgresql://postgres:postgres@127.0.0.1:5432/ai_service_framework",
    )
}


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"

AUTHENTICATION_BACKENDS = [
    "core.auth.backends.EmailBackend",
    "django.contrib.auth.backends.ModelBackend",
]


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        # 只使用 JWT 認證；不加 SessionAuthentication，
        # 避免 Django admin session cookie 在同一個 127.0.0.1 下讓 API 被意外授權
        "core.auth.authentication.CookieJWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "core._common.pagination.StandardPagination",
    "EXCEPTION_HANDLER": "core._common.exception_handler.global_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "anon": "100/day",
        "user": "1000/day",
        "login": "5/min",
        "register": "3/min",
        "password_reset": "3/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}


SPECTACULAR_SETTINGS = {
    "TITLE": "AI Service Framework API",
    "DESCRIPTION": "AI 服務框架 — 統一的 AI 供應商接入、認證、金流處理平台",
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "SCHEMA_PATH_PREFIX": "/api/v1/",
    "COMPONENT_SPLIT_REQUEST": True,
    "TAGS": [
        {"name": "auth", "description": "認證相關端點"},
        {"name": "accounts", "description": "帳號管理端點"},
        {"name": "ai-providers", "description": "AI 供應商端點"},
        {"name": "payments", "description": "金流端點"},
        {"name": "system", "description": "系統端點"},
    ],
}


SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
}

JWT_AUTH_COOKIE = env("JWT_AUTH_COOKIE", default="ai_service_framework_access")
JWT_REFRESH_COOKIE = env("JWT_REFRESH_COOKIE", default="ai_service_framework_refresh")
JWT_COOKIE_SECURE = env.bool("JWT_COOKIE_SECURE", default=not DEBUG)
JWT_COOKIE_SAMESITE = env("JWT_COOKIE_SAMESITE", default="Lax")
JWT_COOKIE_PATH = env("JWT_COOKIE_PATH", default="/api/")
JWT_COOKIE_DOMAIN = env("JWT_COOKIE_DOMAIN", default="")
CORS_ALLOW_CREDENTIALS = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin-allow-popups"


REDIS_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://127.0.0.1:6379/1")
CELERY_RESULT_BACKEND = env(
    "CELERY_RESULT_BACKEND",
    default="redis://127.0.0.1:6379/2",
)
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# Celery 可靠性設定
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_TASK_SOFT_TIME_LIMIT = 300
CELERY_TASK_TIME_LIMIT = 360

# 任務佇列路由 — 依優先級分流
CELERY_TASK_QUEUES = {
    "default": {"exchange": "default", "routing_key": "default"},
    "high_priority": {"exchange": "high_priority", "routing_key": "high_priority"},
    "low_priority": {"exchange": "low_priority", "routing_key": "low_priority"},
}
CELERY_TASK_DEFAULT_QUEUE = "default"

# Email 設定
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = env("EMAIL_HOST", default="127.0.0.1")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@example.com")
# 前端網址，用於產生驗證信連結
FRONTEND_URL = env("FRONTEND_URL", default="http://127.0.0.1:8002")
LOGGER_ENABLE_MIDDLEWARE_LOGS = env.bool("LOGGER_ENABLE_MIDDLEWARE_LOGS", default=True)

# Google OAuth 設定
GOOGLE_CLIENT_ID = env("GOOGLE_CLIENT_ID", default="")
GOOGLE_SECRET_KEY = env("GOOGLE_SECRET_KEY", default="")
# OAuth callback 基底 URL（設定後 redirect_uri 以此為準；留空則自動偵測）
# 範例：http://127.0.0.1:8001（需在各 OAuth 供應商後台登記相同的 callback URI）
SOCIAL_AUTH_CALLBACK_BASE_URL = env("SOCIAL_AUTH_CALLBACK_BASE_URL", default="")


LOGGING = build_logging_config(
    base_dir=BASE_DIR,
    environment=DJANGO_ENV,
    debug=DEBUG,
)

# ============================================================
# Stripe 金流設定
# ============================================================
STRIPE_PUBLISHABLE_KEY = env("STRIPE_PUBLISHABLE_KEY", default="")
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", default="")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", default="")
