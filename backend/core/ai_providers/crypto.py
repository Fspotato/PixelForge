"""API Key 加解密工具 — 使用 Fernet 對稱加密保護 AI 供應商 API key。"""

from __future__ import annotations

import base64
import hashlib

from django.conf import settings


def _get_fernet():
    """取得 Fernet 加密實例（使用 Django SECRET_KEY 衍生金鑰）。"""
    from cryptography.fernet import Fernet

    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_api_key(plain_key: str) -> str:
    """加密 API key。"""
    return _get_fernet().encrypt(plain_key.encode()).decode()


def decrypt_api_key(encrypted_key: str) -> str:
    """解密 API key。"""
    return _get_fernet().decrypt(encrypted_key.encode()).decode()
