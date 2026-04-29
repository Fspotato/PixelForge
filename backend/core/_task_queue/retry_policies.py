"""可配置的重試策略。"""


class RetryPolicy:
    """提供多種重試延遲計算策略。"""

    @staticmethod
    def exponential_backoff(retries: int, base_delay: int = 60, max_delay: int = 3600) -> int:
        """指數退避：delay = base_delay * 2^retries，不超過 max_delay。"""
        delay = base_delay * (2**retries)
        return min(delay, max_delay)

    @staticmethod
    def fixed_delay(delay: int = 60) -> int:
        """固定延遲：每次重試等待相同時間。"""
        return delay

    @staticmethod
    def linear_backoff(retries: int, base_delay: int = 60) -> int:
        """線性退避：delay = base_delay * (retries + 1)。"""
        return base_delay * (retries + 1)
