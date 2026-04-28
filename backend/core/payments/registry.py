"""金流閘道註冊中心 — 提供閘道註冊、查找與快取管理。"""

from __future__ import annotations

from core._logger import get_logger

from .base_gateway import BaseGateway

logger = get_logger(__name__)


class GatewayRegistry:
    """金流閘道註冊中心。

    使用 @GatewayRegistry.register 裝飾器註冊閘道類別，
    使用 GatewayRegistry.get_gateway(name) 取得閘道實例。
    """

    _gateways: dict[str, type[BaseGateway]] = {}
    _instances: dict[str, BaseGateway] = {}

    @classmethod
    def register(cls, gateway_class: type[BaseGateway]) -> type[BaseGateway]:
        """註冊金流閘道類別。"""
        name = gateway_class.gateway_name
        cls._gateways[name] = gateway_class
        logger.info(f"Payment Gateway 已註冊: {name}")
        return gateway_class

    @classmethod
    def get_gateway(cls, name: str, **kwargs) -> BaseGateway:
        """取得金流閘道實例（帶快取）。"""
        if name not in cls._gateways:
            from .exceptions import GatewayNotFoundError

            raise GatewayNotFoundError(name)
        if name not in cls._instances:
            cls._instances[name] = cls._gateways[name](**kwargs)
        return cls._instances[name]

    @classmethod
    def list_gateways(cls) -> list[str]:
        """列出所有已註冊的閘道名稱。"""
        return list(cls._gateways.keys())

    @classmethod
    def clear_cache(cls) -> None:
        """清除閘道實例快取。"""
        cls._instances = {}

    @classmethod
    def get_healthy_gateways(cls, currency: str | None = None) -> list[str]:
        """取得所有健康且支援指定幣別的閘道。"""
        healthy = []
        for name in cls._gateways:
            gw = cls.get_gateway(name)
            if currency and currency not in gw.supported_currencies:
                continue
            health = gw.health_check()
            if health.is_healthy:
                healthy.append(name)
        return healthy

    @classmethod
    def get_gateway_with_fallback(
        cls,
        preferred: str,
        currency: str = "USD",
    ) -> BaseGateway:
        """取得閘道，若偏好閘道不健康則自動切換。"""
        gw = cls.get_gateway(preferred)
        health = gw.health_check()
        if health.is_healthy:
            return gw
        logger.warning(f"閘道 {preferred} 不健康（{health.message}），嘗試 Fallback")
        for fallback_name in cls.get_healthy_gateways(currency=currency):
            if fallback_name != preferred:
                logger.info(f"Fallback 到閘道：{fallback_name}")
                return cls.get_gateway(fallback_name)
        logger.error("所有閘道均不健康，使用偏好閘道")
        return gw
