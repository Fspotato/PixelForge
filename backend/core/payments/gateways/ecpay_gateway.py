"""ECPay 綠界金流閘道實作。"""

from __future__ import annotations

import hashlib
import urllib.parse
from datetime import datetime
from decimal import Decimal

from django.conf import settings

from core._logger import get_logger

from ..base_gateway import (
    BaseGateway,
    CheckoutRequest,
    CheckoutResult,
    HealthStatus,
    WebhookPayload,
)
from ..exceptions import WebhookVerificationError
from ..registry import GatewayRegistry

logger = get_logger(__name__)


@GatewayRegistry.register
class ECPayGateway(BaseGateway):
    """綠界 ECPay 金流閘道。"""

    gateway_name = "ecpay"
    display_name = "綠界科技"
    supported_currencies = ["TWD"]
    is_placeholder = True  # 佔位符，尚未開放使用

    ECPAY_API_URL = "https://payment.ecpay.com.tw/Cashier/AioCheckOut/V5"
    ECPAY_TEST_API_URL = "https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5"

    def __init__(self, **kwargs) -> None:
        self.merchant_id = ""
        self.hash_key = ""
        self.hash_iv = ""
        self.is_sandbox = True
        self._ensure_config()

    def _load_config(self) -> dict:
        """從 Django settings 載入 ECPay 配置。"""
        return {
            "merchant_id": getattr(settings, "ECPAY_MERCHANT_ID", "2000132"),
            "hash_key": getattr(settings, "ECPAY_HASH_KEY", "5294y06JbISpM5x9"),
            "hash_iv": getattr(settings, "ECPAY_HASH_IV", "v77hoKGq4kWxNNIS"),
            "is_sandbox": getattr(settings, "ECPAY_SANDBOX", True),
        }

    def _apply_config(self, config: dict) -> None:
        """套用 ECPay 配置。"""
        self.merchant_id = config.get("merchant_id", "")
        self.hash_key = config.get("hash_key", "")
        self.hash_iv = config.get("hash_iv", "")
        self.is_sandbox = config.get("is_sandbox", True)

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """建立 ECPay 結帳表單參數。"""
        self._ensure_config()

        params = {
            "MerchantID": self.merchant_id,
            "MerchantTradeNo": request.transaction_id[:20],
            "MerchantTradeDate": datetime.now().strftime("%Y/%m/%d %H:%M:%S"),
            "PaymentType": "aio",
            "TotalAmount": str(int(request.amount)),
            "TradeDesc": urllib.parse.quote(request.description),
            "ItemName": request.description,
            "ReturnURL": request.notify_url,
            "ClientBackURL": request.return_url,
            "ChoosePayment": "ALL",
            "EncryptType": "1",
        }

        params["CheckMacValue"] = self._generate_check_mac(params)

        # 產生自動提交表單 HTML
        api_url = self.ECPAY_TEST_API_URL if self.is_sandbox else self.ECPAY_API_URL
        form_inputs = "".join(
            f'<input type="hidden" name="{k}" value="{v}">' for k, v in params.items()
        )
        checkout_html = (
            f'<form id="ecpay-form" method="POST" action="{api_url}">'
            f"{form_inputs}"
            f'<button type="submit">前往付款</button>'
            f"</form>"
            f'<script>document.getElementById("ecpay-form").submit();</script>'
        )

        return CheckoutResult(
            gateway_name=self.gateway_name,
            checkout_html=checkout_html,
            gateway_order_id=params["MerchantTradeNo"],
        )

    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        """驗證 ECPay Webhook CheckMacValue。"""
        self._ensure_config()

        params = dict(urllib.parse.parse_qsl(body.decode("utf-8")))

        received_mac = params.pop("CheckMacValue", "")
        expected_mac = self._generate_check_mac(params)

        if received_mac.upper() != expected_mac.upper():
            raise WebhookVerificationError("ECPay CheckMacValue 不符")

        is_success = params.get("RtnCode") == "1"

        return WebhookPayload(
            gateway_name=self.gateway_name,
            transaction_id=params.get("MerchantTradeNo", ""),
            gateway_order_id=params.get("TradeNo", ""),
            is_success=is_success,
            amount=Decimal(params.get("TradeAmt", "0")),
            raw_data=params,
        )

    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        """ECPay 退款需透過後台或另行串接，此處尚未實作。"""
        raise NotImplementedError("ECPay 退款功能尚未實作")

    def health_check(self) -> HealthStatus:
        """ECPay 閘道目前為佔位符，不可用。"""
        return HealthStatus(
            is_healthy=False,
            message="綠界科技閘道尚未開放，僅作為佔位符使用",
        )

    def _generate_check_mac(self, params: dict) -> str:
        """產生 ECPay SHA256 CheckMacValue。

        步驟：
        1. 依參數名稱排序（不分大小寫）
        2. 組成 key=value& 字串
        3. 前後加上 HashKey / HashIV
        4. URL encode（小寫）
        5. 轉小寫後做 SHA256
        6. 轉大寫
        """
        # 排序：不分大小寫
        sorted_params = sorted(params.items(), key=lambda x: x[0].lower())
        raw = "&".join(f"{k}={v}" for k, v in sorted_params)
        raw = f"HashKey={self.hash_key}&{raw}&HashIV={self.hash_iv}"

        # URL encode 並套用 ECPay 特殊替換規則
        encoded = urllib.parse.quote_plus(raw).lower()

        # ECPay 特殊字元替換
        encoding_replacements = {
            "%2d": "-",
            "%5f": "_",
            "%2e": ".",
            "%21": "!",
            "%2a": "*",
            "%28": "(",
            "%29": ")",
        }
        for old, new in encoding_replacements.items():
            encoded = encoded.replace(old, new)

        # SHA256 後轉大寫
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest().upper()
