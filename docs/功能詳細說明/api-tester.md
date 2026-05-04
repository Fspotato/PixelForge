# API 測試面板

## 概述

目前 `frontend/` 的主角色是 **PixelForge 產品前端**；API 測試面板只是其中一個開發工具頁，不再是整個前端的唯一入口。

測試面板路由為：

```text
/test
```

只有在 **Vite dev 模式** 且設定 `VITE_ENABLE_API_TESTER=true` 時才會啟用。正式使用情境仍以：

- `/`：PixelForge 主工作台
- `/history`：歷史任務
- `/agent-generation`：Agent 生圖

為主。

## 目前用途

API 測試面板用來快速驗證後端端點，包含：

- 系統健康檢查與 Celery 範例任務
- PixelForge 相關 API
- 認證、帳號、通知、審計、權限、API 金鑰
- AI Provider、商品目錄、金流支付、訂閱
- 檔案儲存相關端點

## 開關條件

`frontend/src/App.tsx` 內的條件如下：

```ts
import.meta.env.DEV && import.meta.env.VITE_ENABLE_API_TESTER === "true"
```

代表：

1. `npm run dev` 或 Vite dev server 啟動中
2. 額外設定 `VITE_ENABLE_API_TESTER=true`

兩者都成立時，瀏覽 `/test` 才會載入測試面板。

## 啟動方式

### Docker 開發環境

```bash
make dev
```

之後若要開啟測試面板，需讓前端容器或本機 dev server 帶入 `VITE_ENABLE_API_TESTER=true`。

### 本機前端啟動

```bash
cd frontend
npm install
set VITE_ENABLE_API_TESTER=true
npm run dev
```

若要修改 API 代理目標，可設定：

```bash
set API_PROXY_TARGET=http://127.0.0.1:8001
```

Vite 會將 `/api/*` 代理到後端。

## 功能特性

### 自適應測試資料

測試案例定義於 `frontend/src/data/testCases.ts`。切換案例時，面板會自動帶入：

- 預設 request body
- path params
- 部分流程上下文（例如 ping task id）
- 已登入狀態下需要的 cookie / 認證資訊

### 目前案例分類

依 `testCases.ts` 目前內容，主要分類如下：

| 分類 | 範例 |
|---|---|
| 系統 | Ping、健康檢查、Celery 範例任務 |
| PixelForge | 風格預設、生成任務、歷史、資產、圖片處理、管理統計 |
| 認證 / 帳號 | 註冊、登入、Google OAuth、個人資料 |
| AI 模型 | 供應商測試與圖片模型設定 |
| 金流支付 / 訂閱管理 / 商品目錄 | Checkout、Webhook、同步、產品列表 |
| 審計日誌 / 通知 / 權限管理 / API 金鑰 / 檔案儲存 | 平台治理與營運能力 |

## 相關前端結構

```text
frontend/
├── package.json
├── vite.config.ts
└── src/
    ├── App.tsx
    ├── api/client.ts
    ├── components/
    ├── hooks/
    ├── data/testCases.ts
    └── types/
```

與測試面板最直接相關的檔案：

| 檔案 | 作用 |
|---|---|
| `frontend/src/App.tsx` | 根據 `/test` 路徑與 env flag 決定是否載入 `ApiTesterApp` |
| `frontend/src/data/testCases.ts` | 所有測試案例定義 |
| `frontend/src/api/client.ts` | 送出請求與回應解析 |
| `frontend/src/components/RequestPanel.tsx` | 編輯 request |
| `frontend/src/components/ResponsePanel.tsx` | 顯示 response |
| `frontend/src/components/Sidebar.tsx` | 測試案例側邊欄 |

## 新增測試案例

編輯 `frontend/src/data/testCases.ts`，依 `TestCase` 型別新增項目：

```typescript
{
  id: "my-endpoint",
  category: "分類名稱",
  name: "端點名稱",
  method: "POST",
  path: "/api/v1/my-module/endpoint/",
  description: "端點說明",
  requiresAuth: true,
  body: {
    field: "value",
  },
}
```

建議：

1. 分類名稱沿用既有分類
2. 需要 path params 時使用 `{param}` 語法
3. 需要登入時，讓案例 `requiresAuth: true`
4. 若端點有特殊限制，寫在 `hint`
