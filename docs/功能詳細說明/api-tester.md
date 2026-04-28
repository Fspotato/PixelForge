# API 測試面板

## 概述

`frontend/` 提供一個瀏覽器內的 API 測試工具，可用於驗證後端暴露的所有 REST 端點，包含認證登入、JWT Token 管理、Cookie 處理與系統健康檢查。

技術棧：React 19 / Vite 6 / TypeScript / TanStack React Query / Tailwind CSS。

## 功能

### 日夜模式

右上角 ☀️/🌙 按鈕可切換淺色與深色主題。選擇會存入 `localStorage`，重新開啟時自動套用。首次進入會跟隨系統偏好設定。

### 自適應填入測試案例

切換端點時，面板會自動填入該端點的預設測試資料：

| 觸發情境 | 自動行為 |
|---------|---------|
| 登入成功 | 自動擷取並儲存 `access_token` / `refresh_token` |
| 切換到需認證端點 | 自動注入 `Authorization: Bearer <token>` Header |
| 切換到「登出」或「刷新 Token」 | 自動填入已儲存的 `refresh_token` 到請求內容 |
| 建立 Ping 任務成功 | 自動記錄 `task_id` |
| 切換到「查詢任務狀態」 | 自動填入已記錄的 `task_id` 到路徑參數 |

### 支援的端點

#### 系統

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/v1/system/ping/` | 簡單健康檢查 |
| GET | `/api/v1/system/health/` | 完整健康檢查（DB、Redis、Celery） |
| POST | `/api/v1/system/tasks/ping/` | 建立非同步 Celery 任務 |
| GET | `/api/v1/system/tasks/{task_id}/` | 查詢任務狀態 |

#### 認證

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/api/v1/auth/register/` | 註冊新帳號 |
| POST | `/api/v1/auth/login/` | 帳號密碼登入 |
| POST | `/api/v1/auth/refresh/` | 刷新 access token |
| POST | `/api/v1/auth/logout/` | 登出（黑名單 refresh token）🔒 |
| POST | `/api/v1/auth/verify-email/` | Email 驗證 |
| POST | `/api/v1/auth/password-reset/` | 請求重設密碼 |
| POST | `/api/v1/auth/password-reset-confirm/` | 確認重設密碼 |

#### 帳號

| 方法 | 路徑 | 說明 |
|------|------|------|
| GET | `/api/v1/accounts/me/` | 取得個人資料 🔒 |
| PATCH | `/api/v1/accounts/me/` | 更新個人資料 🔒 |
| POST | `/api/v1/accounts/me/deactivate/` | 停用帳號 🔒 |
| POST | `/api/v1/accounts/me/change-email/` | 更改 Email 🔒 |
| GET | `/api/v1/accounts/me/social-accounts/` | 社交帳號列表 🔒 |

> 🔒 標記表示需要先登入取得 JWT Token。

## 架構

```text
frontend/
├── index.html                     HTML 入口
├── package.json                   依賴與指令
├── vite.config.ts                 Vite 設定（含 API proxy）
├── tailwind.config.ts             Tailwind 設定（dark mode: class）
├── tsconfig*.json                 TypeScript 設定
└── src/
    ├── main.tsx                   React 掛載點
    ├── App.tsx                    根元件（串接 Provider）
    ├── index.css                  Tailwind 入口
    ├── api/
    │   └── client.ts              HTTP 請求封裝（含計時）
    ├── hooks/
    │   ├── useTheme.tsx           日夜模式 Context
    │   └── useAuthStore.tsx       JWT Token 與動態值 Context
    ├── components/
    │   ├── Layout.tsx             整體佈局（Header + 內容區）
    │   ├── ThemeToggle.tsx        日夜模式切換按鈕
    │   ├── Sidebar.tsx            左側端點列表
    │   ├── RequestPanel.tsx       請求建構面板
    │   └── ResponsePanel.tsx      回應展示面板
    ├── data/
    │   └── testCases.ts           預定義測試案例
    └── types/
        └── index.ts               TypeScript 型別定義
```

## 啟動方式

### 搭配 Docker（推薦）

```bash
make dev
```

前端會與後端一起啟動：

- 後端 API：http://127.0.0.1:8001
- 前端測試面板：http://127.0.0.1:8002

Vite dev server 會自動將 `/api/*` 請求代理到後端服務，不需要額外設定 CORS。

### 獨立啟動（需要先啟動後端）

```bash
cd frontend
npm install
npm run dev
```

預設代理目標為 `http://127.0.0.1:8001`，可透過環境變數覆蓋：

```bash
API_PROXY_TARGET=http://your-backend:8001 npm run dev
```

## 測試流程範例

1. `make dev` 啟動完整開發環境
2. `make dev-create-superuser` 建立管理員帳號
3. 瀏覽器開啟 http://127.0.0.1:8002
4. 先點擊 **系統 → Ping** 確認後端連線正常
5. 點擊 **認證 → 登入**，使用預填的管理員帳號送出請求
6. 登入成功後，側邊欄顯示「✅ 已登入」
7. 點擊任何 🔒 端點，Authorization header 自動注入

## 新增測試案例

編輯 `frontend/src/data/testCases.ts`，依照 `TestCase` 介面新增項目：

```typescript
{
  id: "my-endpoint",
  category: "分類名稱",
  name: "端點名稱",
  method: "POST",
  path: "/api/v1/my-module/endpoint/",
  description: "端點說明文字",
  requiresAuth: true,
  body: {
    field: "value",
  },
}
```

支援的模板變數：

- `"{{refreshToken}}"` — 自動替換為目前的 refresh token
- `"{{accessToken}}"` — 自動替換為目前的 access token

路徑參數使用 `{param_name}` 語法搭配 `pathParams` 欄位定義。
