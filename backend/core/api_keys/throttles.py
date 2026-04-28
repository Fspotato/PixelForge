"""API Key 專屬速率限制。"""

import time

from django.core.cache import cache
from rest_framework.throttling import BaseThrottle

DEFAULT_RATE_LIMIT = 60  # 預設每分鐘 60 次請求
THROTTLE_WINDOW = 60  # 時間窗口（秒）


class APIKeyRateThrottle(BaseThrottle):
    """Per-API-Key 速率限制。

    使用 Django cache 追蹤每個 API Key 的請求計數。
    預設 60 req/min，可由 api_key.rate_limit 覆寫。
    """

    cache_format = "api_key_throttle:{key_id}"

    def allow_request(self, request, view):
        """判斷請求是否在速率限制內。"""
        api_key = getattr(request, "auth", None)
        if api_key is None or not hasattr(api_key, "rate_limit"):
            return True

        self.key = self.cache_format.format(key_id=api_key.id)
        self.rate = api_key.rate_limit or DEFAULT_RATE_LIMIT
        self.now = time.time()

        # 從快取取得請求歷史
        self.history = cache.get(self.key, [])

        # 清除過期的請求記錄
        cutoff = self.now - THROTTLE_WINDOW
        self.history = [t for t in self.history if t > cutoff]

        if len(self.history) >= self.rate:
            return False

        self.history.append(self.now)
        cache.set(self.key, self.history, THROTTLE_WINDOW)
        return True

    def wait(self):
        """計算需要等待的秒數。"""
        if not self.history:
            return 0

        oldest = self.history[0]
        remaining = THROTTLE_WINDOW - (self.now - oldest)
        return max(0, remaining)
