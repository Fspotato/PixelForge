"""API Key 生成與驗證工具。"""

import hashlib
import secrets

KEY_PREFIX = "ask_"
KEY_LENGTH = 40
PREFIX_DISPLAY_LENGTH = 8


class KeyGenerator:
    """API Key 生成器，負責金鑰的產生、雜湊與驗證。"""

    @staticmethod
    def generate() -> tuple[str, str, str]:
        """生成 API Key。

        Returns:
            tuple: (full_key, key_prefix, key_hash)
                - full_key: 完整金鑰（僅在建立時回傳一次）
                - key_prefix: 前 8 字元，用於辨識
                - key_hash: SHA-256 雜湊值，用於儲存與比對
        """
        random_part = secrets.token_urlsafe(KEY_LENGTH)
        full_key = f"{KEY_PREFIX}{random_part}"
        key_prefix = full_key[:PREFIX_DISPLAY_LENGTH]
        key_hash = KeyGenerator.hash_key(full_key)
        return full_key, key_prefix, key_hash

    @staticmethod
    def hash_key(key: str) -> str:
        """計算金鑰的 SHA-256 雜湊值。"""
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def verify(incoming_key: str, stored_hash: str) -> bool:
        """驗證傳入的金鑰是否與儲存的雜湊值匹配。"""
        return KeyGenerator.hash_key(incoming_key) == stored_hash
