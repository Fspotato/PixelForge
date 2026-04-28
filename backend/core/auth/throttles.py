"""頻率限制 — 防止暴力破解與濫用。"""

from rest_framework.throttling import AnonRateThrottle


class LoginRateThrottle(AnonRateThrottle):
    """登入嘗試頻率限制：防暴力破解。"""

    rate = "5/min"


class RegisterRateThrottle(AnonRateThrottle):
    """註冊頻率限制。"""

    rate = "3/min"


class PasswordResetRateThrottle(AnonRateThrottle):
    """密碼重設頻率限制。"""

    rate = "3/hour"
