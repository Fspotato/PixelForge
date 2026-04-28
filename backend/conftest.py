"""Pytest 全域設定 — 自動清除跨測試的單例快取，避免狀態污染。"""

import pytest


@pytest.fixture(autouse=True)
def clear_gateway_registry_cache():
    """每個測試前後清除 GatewayRegistry 的閘道實例快取，防止跨測試狀態污染。"""
    from core.payments.registry import GatewayRegistry

    GatewayRegistry.clear_cache()
    yield
    GatewayRegistry.clear_cache()
