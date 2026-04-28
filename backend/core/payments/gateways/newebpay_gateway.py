"""藍新 NewebPay 金流閘道實作。"""

from __future__ import annotations

import hashlib
import json
from binascii import hexlify, unhexlify
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

# AES 加解密使用標準庫 + PyCryptodome 為可選依賴
try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad, unpad

    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False


@GatewayRegistry.register
class NewebPayGateway(BaseGateway):
    """藍新 NewebPay 金流閘道。"""

    gateway_name = "newebpay"
    display_name = "藍新金流"
    supported_currencies = ["TWD"]
    is_placeholder = True  # 佔位符，尚未開放使用

    NEWEBPAY_API_URL = "https://core.newebpay.com/MPG/mpg_gateway"
    NEWEBPAY_TEST_API_URL = "https://ccore.newebpay.com/MPG/mpg_gateway"

    def __init__(self, **kwargs) -> None:
        self.merchant_id = ""
        self.hash_key = ""
        self.hash_iv = ""
        self.is_sandbox = True
        self._ensure_config()

    def _load_config(self) -> dict:
        """從 Django settings 載入 NewebPay 配置。"""
        return {
            "merchant_id": getattr(settings, "NEWEBPAY_MERCHANT_ID", ""),
            "hash_key": getattr(settings, "NEWEBPAY_HASH_KEY", ""),
            "hash_iv": getattr(settings, "NEWEBPAY_HASH_IV", ""),
            "is_sandbox": getattr(settings, "NEWEBPAY_SANDBOX", True),
        }

    def _apply_config(self, config: dict) -> None:
        """套用 NewebPay 配置。"""
        self.merchant_id = config.get("merchant_id", "")
        self.hash_key = config.get("hash_key", "")
        self.hash_iv = config.get("hash_iv", "")
        self.is_sandbox = config.get("is_sandbox", True)

    def create_checkout(self, request: CheckoutRequest) -> CheckoutResult:
        """建立 NewebPay MPG 結帳表單。"""
        self._ensure_config()

        trade_info = {
            "MerchantID": self.merchant_id,
            "RespondType": "JSON",
            "TimeStamp": str(int(__import__("time").time())),
            "Version": "2.0",
            "MerchantOrderNo": request.transaction_id[:20],
            "Amt": str(int(request.amount)),
            "ItemDesc": request.description,
            "ReturnURL": request.return_url,
            "NotifyURL": request.notify_url,
        }

        trade_info_str = "&".join(f"{k}={v}" for k, v in trade_info.items())
        encrypted = self._aes_encrypt(trade_info_str)
        trade_sha = self._sha256_hash(encrypted)

        api_url = self.NEWEBPAY_TEST_API_URL if self.is_sandbox else self.NEWEBPAY_API_URL

        form_html = (
            f'<form id="newebpay-form" method="POST" action="{api_url}">'
            f'<input type="hidden" name="MerchantID" value="{self.merchant_id}">'
            f'<input type="hidden" name="TradeInfo" value="{encrypted}">'
            f'<input type="hidden" name="TradeSha" value="{trade_sha}">'
            f'<input type="hidden" name="Version" value="2.0">'
            f'<button type="submit">前往付款</button>'
            f"</form>"
            f'<script>document.getElementById("newebpay-form").submit();</script>'
        )

        return CheckoutResult(
            gateway_name=self.gateway_name,
            checkout_html=form_html,
            gateway_order_id=trade_info["MerchantOrderNo"],
        )

    def verify_webhook(self, headers: dict, body: bytes) -> WebhookPayload:
        """驗證 NewebPay Webhook 並解密 TradeInfo。"""
        self._ensure_config()

        params = dict(item.split("=", 1) for item in body.decode("utf-8").split("&") if "=" in item)

        trade_info_encrypted = params.get("TradeInfo", "")
        received_sha = params.get("TradeSha", "")
        expected_sha = self._sha256_hash(trade_info_encrypted)

        if received_sha.upper() != expected_sha.upper():
            raise WebhookVerificationError("NewebPay TradeSha 不符")

        decrypted = self._aes_decrypt(trade_info_encrypted)
        try:
            data = json.loads(decrypted)
        except (json.JSONDecodeError, ValueError) as exc:
            raise WebhookVerificationError("NewebPay TradeInfo 解密後格式錯誤") from exc

        result = data.get("Result", {})
        is_success = data.get("Status") == "SUCCESS"

        return WebhookPayload(
            gateway_name=self.gateway_name,
            transaction_id=result.get("MerchantOrderNo", ""),
            gateway_order_id=result.get("TradeNo", ""),
            is_success=is_success,
            amount=Decimal(str(result.get("Amt", 0))),
            raw_data=data,
        )

    def refund(self, gateway_order_id: str, amount: Decimal) -> bool:
        """NewebPay 退款需透過後台或另行串接，此處尚未實作。"""
        raise NotImplementedError("NewebPay 退款功能尚未實作")

    def health_check(self) -> HealthStatus:
        """藍新金流閘道目前為佔位符，不可用。"""
        return HealthStatus(
            is_healthy=False,
            message="藍新金流閘道尚未開放，僅作為佔位符使用",
        )

    def _aes_encrypt(self, plaintext: str) -> str:
        """AES-256-CBC 加密（PKCS7 填充）。"""
        if not HAS_CRYPTO:
            logger.warning("PyCryptodome 未安裝，無法執行 AES 加密")
            return ""
        key = self.hash_key.encode("utf-8")
        iv = self.hash_iv.encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        padded = pad(plaintext.encode("utf-8"), AES.block_size)
        encrypted = cipher.encrypt(padded)
        return hexlify(encrypted).decode("utf-8")

    def _aes_decrypt(self, ciphertext: str) -> str:
        """AES-256-CBC 解密。"""
        if not HAS_CRYPTO:
            logger.warning("PyCryptodome 未安裝，無法執行 AES 解密")
            return ""
        key = self.hash_key.encode("utf-8")
        iv = self.hash_iv.encode("utf-8")
        cipher = AES.new(key, AES.MODE_CBC, iv)
        decrypted = cipher.decrypt(unhexlify(ciphertext))
        return unpad(decrypted, AES.block_size).decode("utf-8")

    def _sha256_hash(self, encrypted_data: str) -> str:
        """產生 SHA256 雜湊值用於 TradeSha 驗證。"""
        raw = f"HashKey={self.hash_key}&{encrypted_data}&HashIV={self.hash_iv}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
