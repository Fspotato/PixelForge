# Tech Reference — Google OAuth + JWT Cookie 持久化

> 目的：給 AI 與工程師參考，將「Google 登入 + 後端 JWT HttpOnly Cookie session」這套作法移植到其他專案。
> 本文件聚焦「資料流向」與「關鍵 API / 設定」，不貼整段程式碼；專案結構不同時請對照自己的框架實作。

---

## 1. 設計目標

- 前端只負責「拿到 Google 的 access_token / id_token」並把它丟給後端。
- 後端負責「驗證 Google token → 建立或取得本地使用者 → 簽發本地 JWT → 寫入 HttpOnly cookie」。
- **Access token 與 Refresh token 全程不出現在 JS 可讀的地方**（不寫入 `localStorage`、不寫入 response body 給前端解析），完全靠 HttpOnly cookie 維持 session。
- 前端只在 `localStorage` 保留**非敏感的 user snapshot**（id / email / name），用於 UI 立即水合（hydration），實際身份仍以 cookie 為準。
- 支援「分頁關閉、隔天回來」仍是登入狀態：透過 refresh cookie 自動換新的 access cookie。

---

## 2. 技術棧（本專案實作）

| 角色 | 套件 / API |
|---|---|
| 前端 Google 登入 | Google Identity Services (GIS) `https://accounts.google.com/gsi/client`，`google.accounts.oauth2.initTokenClient` |
| 後端社群登入 | `django-allauth` + `dj-rest-auth`（`SocialLoginView` + `GoogleOAuth2Adapter`） |
| 後端 JWT | `djangorestframework-simplejwt`（`RefreshToken`、`TokenRefreshView`、blacklist app） |
| Cookie 自訂 | DRF Authentication class（從 cookie 讀 token）+ 自訂 set/clear cookie helpers |

> 換成 Node/NestJS/FastAPI 都可，重點是「同樣的資料流」與下列幾個關鍵動作。

---

## 3. 資料流向（端到端）

### 3.1 首次登入（Google → 後端 → Cookie）

```
[Browser]                          [Frontend SPA]               [Backend]                  [Google]
  │                                     │                           │                          │
  │ 1. 點 "Sign in with Google"         │                           │                          │
  │ ───────────────────────────────────▶│                           │                          │
  │                                     │ 2. GET /api/auth/config/ ─┼─────────▶ 回傳           │
  │                                     │   (取得 google_client_id) │                          │
  │                                     │                           │                          │
  │                                     │ 3. 載入 GIS script        │                          │
  │                                     │    initTokenClient({...}) │                          │
  │                                     │    .requestAccessToken()  │                          │
  │                                     │ ─────────────────────────────────────────────────────▶│
  │                                     │                           │                          │
  │                                     │ ◀────── access_token ────────────────────────────────│
  │                                     │                           │                          │
  │                                     │ 4. POST /api/auth/google/ │                          │
  │                                     │    body: {access_token}   │                          │
  │                                     │    credentials: 'include' │                          │
  │                                     │ ──────────────────────────▶                          │
  │                                     │                           │ 5. 用 access_token 向    │
  │                                     │                           │    Google userinfo 驗證  │
  │                                     │                           │ ─────────────────────────▶│
  │                                     │                           │ ◀── email / sub / name ──│
  │                                     │                           │                          │
  │                                     │                           │ 6. 取得或建立本地 User   │
  │                                     │                           │ 7. 簽發 access+refresh   │
  │                                     │                           │ 8. Set-Cookie:           │
  │                                     │                           │    mbti_mail_access      │
  │                                     │                           │    mbti_mail_refresh     │
  │                                     │                           │    HttpOnly; Secure;     │
  │                                     │                           │    SameSite; Path=/api/  │
  │                                     │                           │ 9. 從 response body 移除 │
  │                                     │                           │    access/refresh 字串   │
  │                                     │ ◀── 200 { user: {...} } ─│                          │
  │                                     │                           │                          │
  │                                     │ 10. 把 user 寫入          │                          │
  │                                     │     localStorage（僅快照）│                          │
```

### 3.2 後續 API 呼叫

- 前端所有 `fetch` 都帶 `credentials: 'include'`，瀏覽器自動附上 access cookie。
- 後端 DRF `Authentication` class 流程：
  1. 先看 `Authorization: Bearer …` header（向後相容 mobile/CLI）
  2. 沒有 header 才看 `request.COOKIES[JWT_AUTH_COOKIE]`
  3. 用 simplejwt 的 `get_validated_token()` 驗章 + 過期，再 `get_user()` 帶出 user 物件

### 3.3 Access token 過期 → Refresh

- 任何受保護 API 回 401 時，前端 `apiFetch` helper 自動：
  1. 呼叫 `POST /api/token/refresh/`（body 空 `{}`，瀏覽器自動帶 refresh cookie）
  2. 後端從 cookie 讀出 refresh token → simplejwt `TokenRefreshSerializer` 驗證 → 簽新的 access（如果開 rotation 也簽新 refresh）→ Set-Cookie 蓋回去
  3. 前端用同一份 `RequestInit` 重打一次原本的 API
- 為了避免多個 401 同時併發 refresh，前端用 module-level `refreshRequest: Promise | null` 做 **single-flight 去重**。

### 3.4 重新整理頁面 / 重開瀏覽器

- App 啟動時呼叫 `restoreBackendAuth()`：
  1. `GET /api/auth/me/`（瀏覽器自動帶 access cookie）
  2. 200 → 拿到 user → 設定 React state，把 snapshot 寫回 `localStorage`
  3. 401 → 嘗試一次 refresh → 成功就再打一次 `/me`；失敗就清除本地 snapshot 並 dispatch `mbti-auth-cleared` 事件，App 監聽事件後跳回登入頁

### 3.5 登出

- 前端 `POST /api/auth/logout/`（帶 cookie）
- 後端：
  1. 從 cookie 或 body 取 refresh token
  2. simplejwt `RefreshToken(token).blacklist()` 加入黑名單
  3. `response.delete_cookie()` 把 access + refresh cookie 兩個都刪
- 前端額外清掉 `localStorage` / `sessionStorage` 內所有「使用者特定」的快取，避免換帳號時資料殘留；並 dispatch 自訂事件通知 React 樹清狀態。

---

## 4. 關鍵 API / 介面契約

### 4.1 後端公開 endpoints

| Method & Path | 用途 | 認證 |
|---|---|---|
| `GET /api/auth/config/` | 回傳 `{ google_client_id }`，避免把 client id 寫死在前端 build | 公開 |
| `POST /api/auth/google/` | 收 `{access_token}` 或 `{code}`，登入並 Set-Cookie | 公開 |
| `GET /api/auth/me/` | 回傳當前 user | Cookie/Bearer |
| `POST /api/token/refresh/` | 從 refresh cookie 換新 access cookie | Cookie/Bearer |
| `POST /api/auth/logout/` | Blacklist refresh token + 清 cookie | 公開（容錯） |

### 4.2 Cookie 欄位

| 欄位 | 值 | 為什麼這樣設 |
|---|---|---|
| `HttpOnly` | true | 阻擋 JS 讀取，防止 XSS 偷 token |
| `Secure` | prod=true / dev=false | HTTPS-only |
| `SameSite` | `Lax`（預設） | 防 CSRF；若前後端跨網域要 `None` + `Secure` |
| `Domain` | optional | 跨子網域共用 session 時才設 |
| `Path` | `/api/` | 限制只在 API 路徑送 cookie，靜態資源不浪費頻寬，也降低洩漏面 |
| `Max-Age` | access ~15 min, refresh ~7 days | 短壽 access + 長壽 refresh |

### 4.3 SimpleJWT 設定要點

- `ROTATE_REFRESH_TOKENS = True`：每次 refresh 都換新 refresh token。
- `BLACKLIST_AFTER_ROTATION = True`：舊的 refresh token 立即失效，配合 `token_blacklist` app。
- 登出 = `RefreshToken(token).blacklist()`。

---

## 5. 後端關鍵實作點（不貼程式碼）

1. **自訂 Authentication class**：繼承 simplejwt `JWTAuthentication`，覆寫 `authenticate()`：先看 header，再 fallback 看指定名稱的 cookie；放到 DRF `DEFAULT_AUTHENTICATION_CLASSES` 的第一順位。
2. **Set-Cookie helper**：包一個函式接受 `response, access_token, refresh_token`，根據設定（cookie 名稱、HttpOnly、Secure、SameSite、Domain、Path、Max-Age = `ACCESS_TOKEN_LIFETIME.total_seconds()`）寫入 cookie。
3. **Strip-tokens helper**：登入/refresh 成功後從 `response.data` 把 `access`、`refresh` 鍵移除，避免它們被前端 JS 看到。**這一步是「HttpOnly only」設計的關鍵**。
4. **GoogleLogin view**：繼承 `dj_rest_auth.registration.views.SocialLoginView`，指定 `adapter_class = GoogleOAuth2Adapter`。`post()` 呼叫 super 取得簽好的 JWT，再呼叫 set-cookie helper + strip-tokens helper。
5. **SafeTokenRefreshView**：繼承 simplejwt `TokenRefreshView`，覆寫 `post()`：若 body 沒帶 refresh，從 cookie 撈；若 user 已被刪掉，把 `ObjectDoesNotExist` 轉 401（避免 500）。同樣 set-cookie + strip-tokens。
6. **Logout view**：撈 refresh token（cookie 或 body）→ `RefreshToken(...).blacklist()`（`TokenError` 視為已登出，不要 raise）→ `delete_cookie` 必須帶與 set 時相同的 `domain` 和 `path`，否則瀏覽器不會清。
7. **`SECURE_CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'`**：Google Identity Services 用 popup 流程時必要，否則會被 COOP 擋住。
8. **Allauth socialaccount provider 設定**：在 `SOCIALACCOUNT_PROVIDERS["google"]["APP"]` 填 `client_id` / `secret`。`SOCIALACCOUNT_AUTO_SIGNUP = True` 讓首次 Google 登入自動建立 user。

---

## 6. 前端關鍵實作點

1. **載入 GIS script**：動態 inject `<script src="https://accounts.google.com/gsi/client">`，並用同一個 promise cache 避免重複載入。
2. **取 access token**：`google.accounts.oauth2.initTokenClient({client_id, scope: 'openid email profile', callback})`，呼叫 `requestAccessToken({prompt: 'select_account'})`。callback 內 `resp.access_token` 就是要送給後端的東西。
3. **送後端**：`fetch('/api/auth/google/', {method:'POST', credentials:'include', body: JSON.stringify({access_token})})`。**`credentials: 'include'` 是必須的**，否則 Set-Cookie 會被瀏覽器丟掉。
4. **本地 snapshot**：只把 `{ user: { id, email, name, ... } }` 寫進 `localStorage`，**絕不寫入任何 token**。snapshot 僅供 UI 在啟動時瞬間顯示「已登入」，真正權限驗證仍要靠 `/me`。
5. **`apiFetch` 包裝器**：所有受保護請求都走它。流程 = fetch → 401 → single-flight refresh → 成功就重打一次。
6. **跨頁簽出事件**：清 storage 後 `window.dispatchEvent(new CustomEvent('mbti-auth-cleared'))`，App root 監聽並把 React 內的 user state 一起歸零，避免不同分頁 / 不同元件 state 不一致。
7. **同源 / 反向代理**：前端用 **相對 URL**（`/api/...`），由 Vite dev proxy 或 prod 反向代理導到後端，這樣 cookie 自動同源、不需要 CORS preflight 也不需要 `SameSite=None`。

---

## 7. 安全性要點

- ✅ **HttpOnly + Secure + SameSite=Lax**：防 XSS 偷 token、防 CSRF。
- ✅ **Refresh token rotation + blacklist**：偷到的舊 refresh 一旦被用過就失效。
- ✅ **Cookie Path 限制在 `/api/`**：靜態資源請求不會帶 token。
- ✅ **`COOP = same-origin-allow-popups`**：Google popup 不被擋。
- ⚠️ **跨網域**：若前端在 `app.example.com`、API 在 `api.example.com`，需 `SameSite=None; Secure` + 後端正確設 CORS（`Access-Control-Allow-Credentials: true`、`Access-Control-Allow-Origin` 不能是 `*`）。
- ⚠️ **登出時的 `delete_cookie`** 必須帶與 set 時一致的 `domain` 與 `path`，否則前端 cookie 不會被清。
- ⚠️ **登出後清快取**：使用者特定的 `localStorage` / `sessionStorage` 必須一起清，否則 A 帳號登出後 B 帳號登入會看到 A 的快取。