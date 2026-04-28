"""帳號模組事件處理器 — 訂閱 Event Bus 並執行對應的帳號業務邏輯。"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.utils import timezone

from core._event_bus import subscribe
from core._logger import get_logger

from .models import EmailVerification

logger = get_logger(__name__)
User = get_user_model()


@subscribe("auth.user.registered", is_async=True)
def on_user_registered(event) -> None:
    """使用者註冊後建立驗證 token 並發送驗證信。"""
    user_id = event.payload.get("user_id")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error("找不到使用者，無法發送驗證信", extra={"user_id": user_id})
        return

    # 作廢該使用者所有未使用的驗證 token
    EmailVerification.objects.filter(user=user, verified_at__isnull=True).delete()

    # 建立新的驗證 token（有效期 24 小時）
    token = secrets.token_urlsafe(32)
    expires_at = timezone.now() + timedelta(hours=24)
    EmailVerification.objects.create(
        user=user,
        token=token,
        expires_at=expires_at,
    )

    # 組合驗證連結
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"

    # 發送驗證信
    try:
        send_mail(
            subject="請驗證您的 Email",
            message=(
                f"您好，\n\n"
                f"感謝您的註冊！請點擊以下連結驗證您的 Email 地址：\n\n"
                f"{verify_url}\n\n"
                f"此連結將於 24 小時後失效。\n\n"
                f"若您未申請此帳號，請忽略此信件。"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        logger.info("驗證信已發送", extra={"user_id": user_id, "email": user.email})
    except Exception:
        logger.exception("驗證信發送失敗", extra={"user_id": user_id, "email": user.email})


@subscribe("auth.password_reset.requested", is_async=True)
def on_password_reset_requested(event) -> None:
    """使用者請求密碼重設後發送重設信。"""
    user_id = event.payload.get("user_id")
    email = event.payload.get("email")
    token = event.payload.get("token")

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.error("找不到使用者，無法發送密碼重設信", extra={"user_id": user_id})
        return

    if not isinstance(token, str) or not token:
        logger.error("缺少有效的密碼重設 token", extra={"user_id": user_id})
        return

    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"

    try:
        send_mail(
            subject="重設您的密碼",
            message=(
                f"您好，\n\n"
                f"我們收到了您的密碼重設請求。請點擊以下連結設定新密碼：\n\n"
                f"{reset_url}\n\n"
                f"此連結將於 1 小時後失效。\n\n"
                f"若您未提出此請求，請忽略此信件。"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email or user.email],
            fail_silently=False,
        )
        logger.info("密碼重設信已發送", extra={"user_id": user_id, "email": email or user.email})
    except Exception:
        logger.exception(
            "密碼重設信發送失敗",
            extra={"user_id": user_id, "email": email or user.email},
        )
