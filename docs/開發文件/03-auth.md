# PixelForge 平台 — 認證模組設計 (`auth`)

> 🌐 **外部模組**：暴露 REST API，處理所有認證相關流程。

## 1. 設計目標

- **API-first 無狀態認證**：不依賴 Django session，完全以 JWT (access + refresh token) 驅動
- **社交登入可插拔**：Google、GitHub 等 OAuth provider 透過 adapter 接入
- **Token 生命週期完整管理**：簽發、刷新、撤銷、黑名單
- **與 accounts 模組解耦**：auth 只負責「你是誰」，accounts 負責「你的資料」
- **安全性優先**：防 replay、防 token 洩漏、signed state callback

---

## 2. 架構流程圖

### 2.1 JWT 認證流程

```
Client (SPA / Mobile)                     Backend (auth 模組)
       │                                        │
       │  POST /api/v1/auth/login/               │
       │  { email, password }                    │
       │ ──────────────────────────────────────→  │
       │                                        │
       │                          ┌──────────────┤
       │                          │ 驗證帳密      │
       │                          │ 查詢 User     │
       │                          │ 簽發 JWT     │
       │                          └──────────────┤
       │                                        │
       │  200 { access_token, refresh_token }    │
       │ ←──────────────────────────────────────  │
       │                                        │
       │  GET /api/v1/accounts/me/               │
       │  Authorization: Bearer {access_token}   │
       │ ──────────────────────────────────────→  │
       │                                        │
       │  200 { user data }                      │
       │ ←──────────────────────────────────────  │
       │                                        │
       │  ---- access_token 過期 ----             │
       │                                        │
       │  POST /api/v1/auth/refresh/             │
       │  { refresh_token }                      │
       │ ──────────────────────────────────────→  │
       │                                        │
       │  200 { new_access_token }               │
       │ ←──────────────────────────────────────  │
```

### 2.2 社交登入流程（以 Google 為例）

```
Client                    Backend                     Google
  │                          │                           │
  │ GET /auth/social/        │                           │
  │   google/start/          │                           │
  │ ───────────────────────→ │                           │
  │                          │                           │
  │                          │ 生成 signed state         │
  │                          │ (含 user context +        │
  │                          │  redirect_url)            │
  │                          │                           │
  │  302 Redirect            │                           │
  │  → Google OAuth URL      │                           │
  │ ←─────────────────────── │                           │
  │                          │                           │
  │ ─────────────────────────────────────────────────→   │
  │  使用者授權                                           │
  │ ←─────────────────────────────────────────────────   │
  │  302 + auth code                                     │
  │                          │                           │
  │ GET /auth/social/        │                           │
  │   google/callback/       │                           │
  │   ?code=xxx&state=yyy    │                           │
  │ ───────────────────────→ │                           │
  │                          │ 驗證 signed state          │
  │                          │ Exchange code → token      │
  │                          ├──────────────────────────→ │
  │                          │      token + userinfo      │
  │                          │ ←──────────────────────── │
  │                          │                           │
  │                          │ 查找/建立 User             │
  │                          │ 簽發 JWT                  │
  │                          │                           │
  │  302 → redirect_url      │                           │
  │  ?access_token=xxx       │                           │
  │  &refresh_token=yyy      │                           │
  │ ←─────────────────────── │                           │
```

---

## 3. API 端點設計

| Method | Path | 說明 |
|--------|------|------|
| `POST` | `/api/v1/auth/login/` | 帳號密碼登入 |
| `POST` | `/api/v1/auth/logout/` | 登出（黑名單 refresh token） |
| `POST` | `/api/v1/auth/refresh/` | 刷新 access token |
| `POST` | `/api/v1/auth/register/` | 註冊新帳號 |
| `POST` | `/api/v1/auth/verify-email/` | Email 驗證 |
| `POST` | `/api/v1/auth/password-reset/` | 請求密碼重設 |
| `POST` | `/api/v1/auth/password-reset-confirm/` | 確認密碼重設 |
| `GET`  | `/api/v1/auth/social/google/start/` | Google OAuth 起始 |
| `GET`  | `/api/v1/auth/social/google/callback/` | Google OAuth 回調 |

---

## 4. 核心元件

### 4.1 檔案結構

```
core/auth/
├── __init__.py
├── apps.py                 # Django AppConfig
├── urls.py                 # URL 路由
├── views.py                # API Views
├── serializers.py          # Request/Response 序列化
├── backends.py             # 認證後端
├── tokens.py               # JWT Token 工具
├── permissions.py          # 權限類別
├── throttles.py            # 頻率限制
└── social/                 # 社交登入 adapters
    ├── __init__.py
    ├── base.py             # BaseSocialAdapter
    ├── google.py           # GoogleAdapter
    └── github.py           # GitHubAdapter
```

### 4.2 Token 管理

```python
# core/auth/tokens.py

from rest_framework_simplejwt.tokens import RefreshToken
from core._logger import get_logger

logger = get_logger(__name__)

class TokenService:
    """JWT Token 生命週期管理"""

    @staticmethod
    def create_tokens_for_user(user) -> dict:
        """為使用者簽發 access + refresh token"""
        refresh = RefreshToken.for_user(user)
        logger.info("Token signed", extra={"user_id": user.id})
        return {
            "access_token": str(refresh.access_token),
            "refresh_token": str(refresh),
        }

    @staticmethod
    def blacklist_token(refresh_token: str) -> None:
        """將 refresh token 加入黑名單"""
        token = RefreshToken(refresh_token)
        token.blacklist()

    @staticmethod
    def refresh_access_token(refresh_token: str) -> str:
        """用 refresh token 取得新的 access token"""
        token = RefreshToken(refresh_token)
        return str(token.access_token)
```

### 4.3 社交登入 Adapter（可插拔）

```python
# core/auth/social/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass

@dataclass
class SocialUserInfo:
    """社交平台回傳的使用者資訊標準化結構"""
    provider: str
    provider_uid: str
    email: str
    name: str
    avatar_url: str | None = None

class BaseSocialAdapter(ABC):
    """社交登入 Adapter 基底類別"""

    provider_name: str

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """取得 OAuth 授權 URL"""
        ...

    @abstractmethod
    def exchange_code_for_token(self, code: str) -> dict:
        """用 authorization code 換取 access token"""
        ...

    @abstractmethod
    def get_user_info(self, access_token: str) -> SocialUserInfo:
        """取得使用者資訊"""
        ...
```

```python
# core/auth/social/google.py

from .base import BaseSocialAdapter, SocialUserInfo
import httpx

class GoogleAdapter(BaseSocialAdapter):
    provider_name = "google"

    AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "consent",
        }
        return f"{self.AUTHORIZE_URL}?{'&'.join(f'{k}={v}' for k, v in params.items())}"

    def exchange_code_for_token(self, code: str) -> dict:
        response = httpx.post(self.TOKEN_URL, data={
            "code": code,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "redirect_uri": self.redirect_uri,
            "grant_type": "authorization_code",
        })
        response.raise_for_status()
        return response.json()

    def get_user_info(self, access_token: str) -> SocialUserInfo:
        response = httpx.get(
            self.USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        data = response.json()
        return SocialUserInfo(
            provider="google",
            provider_uid=data["sub"],
            email=data["email"],
            name=data.get("name", ""),
            avatar_url=data.get("picture"),
        )
```

### 4.4 社交登入 Registry

```python
# core/auth/social/__init__.py

class SocialAdapterRegistry:
    """管理所有已註冊的社交登入 Adapter"""

    _adapters: dict[str, BaseSocialAdapter] = {}

    @classmethod
    def register(cls, adapter: BaseSocialAdapter):
        cls._adapters[adapter.provider_name] = adapter

    @classmethod
    def get(cls, provider_name: str) -> BaseSocialAdapter:
        if provider_name not in cls._adapters:
            raise ProviderNotFoundError(f"Social provider '{provider_name}' not registered")
        return cls._adapters[provider_name]

    @classmethod
    def list_providers(cls) -> list[str]:
        return list(cls._adapters.keys())
```

---

## 5. 安全設計

### 5.1 Signed State（防止 CSRF + Open Redirect）

```python
import hmac
import hashlib
import json
import time
from django.conf import settings

def create_signed_state(payload: dict, ttl: int = 300) -> str:
    """建立 HMAC 簽名的 OAuth state"""
    payload["exp"] = int(time.time()) + ttl
    data = json.dumps(payload, sort_keys=True)
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        data.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{data}|{signature}"

def verify_signed_state(state: str) -> dict | None:
    """驗證並解開 signed state"""
    try:
        data, signature = state.rsplit("|", 1)
        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(data)
        if payload.get("exp", 0) < time.time():
            return None
        return payload
    except (ValueError, json.JSONDecodeError):
        return None
```

### 5.2 頻率限制

```python
# core/auth/throttles.py

from rest_framework.throttling import AnonRateThrottle

class LoginRateThrottle(AnonRateThrottle):
    """登入嘗試頻率限制：防暴力破解"""
    rate = "5/min"

class RegisterRateThrottle(AnonRateThrottle):
    """註冊頻率限制"""
    rate = "3/min"

class PasswordResetRateThrottle(AnonRateThrottle):
    """密碼重設頻率限制"""
    rate = "3/hour"
```

---

## 6. Know-How

### 6.1 為什麼不用 Django Session？

- SPA 前端與後端通常不在同一個 domain
- 移動端 app 無法使用 cookie-based session
- JWT 是 stateless 的，對水平擴展友好
- 但仍需要 refresh token 機制來平衡安全性與使用者體驗

### 6.2 為什麼社交登入 callback 要用 signed state 而非 session？

- 前後端分離架構下，callback URL 可能跳轉到不同的前端 host
- Session 在跨域場景下不穩定（SameSite cookie 問題）
- Signed state 自包含所有資訊，不依賴伺服器端狀態
- 有 TTL 過期機制，防止 replay attack

### 6.3 Token 黑名單的取捨

- **使用黑名單**（`rest_framework_simplejwt.token_blacklist`）：安全性高，但需要 DB 查詢
- **不用黑名單**：效能好，但無法即時撤銷 token
- **建議**：啟用黑名單，並在 access token TTL 設為 5-15 分鐘以降低風險

### 6.4 Auth 與 Accounts 的邊界

```
auth 模組的職責：          accounts 模組的職責：
─────────────────         ─────────────────────
✅ 登入/登出               ✅ 使用者資料 CRUD
✅ Token 簽發/刷新         ✅ 頭像上傳
✅ 社交登入 OAuth 流程     ✅ Email 變更
✅ 密碼重設流程            ✅ 個人設定
✅ 驗證 request identity   ✅ 使用者搜尋/列表
❌ 使用者資料管理          ❌ 認證邏輯
```
