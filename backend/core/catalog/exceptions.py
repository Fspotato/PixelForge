"""商品目錄模組自訂例外。"""

from rest_framework import status

from core._common.exceptions import ServiceError


class CatalogItemNotFoundError(ServiceError):
    """找不到指定商品。"""

    def __init__(self, identifier: str = ""):
        detail = f"（{identifier}）" if identifier else ""
        super().__init__(
            code="CATALOG_ITEM_NOT_FOUND",
            message=f"找不到指定的商品{detail}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class PricingTierNotFoundError(ServiceError):
    """找不到指定定價層級。"""

    def __init__(self, identifier: str = ""):
        detail = f"（{identifier}）" if identifier else ""
        super().__init__(
            code="PRICING_TIER_NOT_FOUND",
            message=f"找不到指定的定價層級{detail}",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class GatewayMappingNotFoundError(ServiceError):
    """找不到指定閘道映射。"""

    def __init__(self, identifier: str = ""):
        detail = f"（{identifier}）" if identifier else ""
        super().__init__(
            code="GATEWAY_MAPPING_NOT_FOUND",
            message=f"找不到指定的閘道映射{detail}",
            status_code=status.HTTP_404_NOT_FOUND,
        )
