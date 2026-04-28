import { useState } from "react"
import { ThemeProvider } from "./hooks/useTheme"
import { AuthProvider } from "./hooks/useAuthStore"
import { Layout } from "./components/Layout"
import { Sidebar } from "./components/Sidebar"
import { RequestPanel } from "./components/RequestPanel"
import { ResponsePanel } from "./components/ResponsePanel"
import { AiTestPanel } from "./components/AiTestPanel"
import { OrderSyncPanel } from "./components/OrderSyncPanel"
import { SubscriptionSyncPanel } from "./components/SubscriptionSyncPanel"
import { CatalogActionPanel } from "./components/CatalogActionPanel"
import { EntityBrowserPanel } from "./components/EntityBrowserPanel"
import { PaymentResultPage } from "./components/PaymentResultPage"
import { testCases } from "./data/testCases"
import type { ApiResponse } from "./types"

/** AI 互動式測試面板的 test case ID */
const AI_INTERACTIVE_IDS = new Set(["ai-chat", "ai-image"])
/** 訂單同步面板的 test case ID */
const ORDER_SYNC_IDS = new Set(["payments-sync-orders"])
/** 訂閱同步面板的 test case ID */
const SUBSCRIPTION_SYNC_IDS = new Set(["subscriptions-sync-all"])
/** 結帳建立面板的 test case ID */
const CHECKOUT_PANEL_IDS = new Set(["payments-checkout"])
/** 訂閱建立面板的 test case ID */
const SUBSCRIPTION_CREATE_IDS = new Set(["subscriptions-create"])
/** 訂單列表面板的 test case ID */
const ORDER_BROWSER_IDS = new Set(["payments-order-list"])
/** 訂閱列表面板的 test case ID */
const SUBSCRIPTION_BROWSER_IDS = new Set(["subscriptions-list"])

export default function App() {
  // 付款結果頁使用獨立路由，不依賴 React Router
  if (window.location.pathname === "/payment/result") {
    return (
      <ThemeProvider>
        <AuthProvider>
          <PaymentResultPage />
        </AuthProvider>
      </ThemeProvider>
    )
  }

  const [selectedId, setSelectedId] = useState(testCases[0].id)
  const [response, setResponse] = useState<ApiResponse | null>(null)

  const selectedCase =
    testCases.find((tc) => tc.id === selectedId) || testCases[0]

  const isAiInteractive = AI_INTERACTIVE_IDS.has(selectedCase.id)
  const isOrderSync = ORDER_SYNC_IDS.has(selectedCase.id)
  const isSubscriptionSync = SUBSCRIPTION_SYNC_IDS.has(selectedCase.id)
  const isCheckoutPanel = CHECKOUT_PANEL_IDS.has(selectedCase.id)
  const isSubscriptionCreatePanel = SUBSCRIPTION_CREATE_IDS.has(selectedCase.id)
  const isOrderBrowser = ORDER_BROWSER_IDS.has(selectedCase.id)
  const isSubscriptionBrowser = SUBSCRIPTION_BROWSER_IDS.has(selectedCase.id)

  return (
    <ThemeProvider>
      <AuthProvider>
        <Layout>
          <Sidebar
            testCases={testCases}
            selectedId={selectedId}
            onSelect={(tc) => {
              setSelectedId(tc.id)
              setResponse(null)
            }}
          />
          <main className="flex-1 flex flex-col overflow-hidden">
            {isAiInteractive ? (
              /* AI 文字聊天 / 圖像生成 — 使用專屬互動面板 */
              <AiTestPanel key={selectedCase.id} testCase={selectedCase} />
            ) : isOrderSync ? (
              /* 訂單狀態同步 — 使用專屬面板 */
              <OrderSyncPanel key={selectedCase.id} />
            ) : isSubscriptionSync ? (
              /* 訂閱狀態同步 — 使用專屬面板 */
              <SubscriptionSyncPanel key={selectedCase.id} />
            ) : isCheckoutPanel ? (
              /* 商品化結帳建立 — 使用專屬面板 */
              <CatalogActionPanel key={selectedCase.id} mode="checkout" />
            ) : isSubscriptionCreatePanel ? (
              /* 商品化訂閱建立 — 使用專屬面板 */
              <CatalogActionPanel key={selectedCase.id} mode="subscription" />
            ) : isOrderBrowser ? (
              /* 訂單列表瀏覽 — 自動載入與點選詳情 */
              <EntityBrowserPanel key={selectedCase.id} resource="orders" />
            ) : isSubscriptionBrowser ? (
              /* 訂閱列表瀏覽 — 自動載入與點選詳情 */
              <EntityBrowserPanel key={selectedCase.id} resource="subscriptions" />
            ) : (
              <>
                {/* key 確保切換測試案例時重新掛載，觸發自適應填入 */}
                <RequestPanel
                  key={selectedCase.id}
                  testCase={selectedCase}
                  onResponse={setResponse}
                />
                <ResponsePanel response={response} />
              </>
            )}
          </main>
        </Layout>
      </AuthProvider>
    </ThemeProvider>
  )
}
