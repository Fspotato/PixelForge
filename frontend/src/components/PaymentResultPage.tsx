/** 付款結果頁 — 由 Stripe（或其他閘道）回調後顯示交易 / 訂閱詳情。 */

import { useCallback, useEffect, useMemo, useState } from "react"
import { sendRequest } from "../api/client"
import { ThemeToggle } from "./ThemeToggle"

interface PaymentData {
  type: "payment" | "subscription"
  id: string
  status: string
  // payment 欄位
  amount?: string
  currency?: string
  gateway?: string
  order_number?: string
  description?: string
  paid_at?: string | null
  created_at?: string
  // subscription 欄位
  catalog_item_id?: string | null
  pricing_tier_id?: string | null
  gateway_subscription_id?: string | null
  current_period_start?: string | null
  current_period_end?: string | null
  trial_end?: string | null
  cancel_at_period_end?: boolean
}

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  success: { label: "✅ 付款成功", color: "text-emerald-600 dark:text-emerald-400" },
  pending: { label: "⏳ 等待付款", color: "text-amber-600 dark:text-amber-400" },
  failed: { label: "❌ 付款失敗", color: "text-red-600 dark:text-red-400" },
  refunded: { label: "↩️ 已退款", color: "text-blue-600 dark:text-blue-400" },
  active: { label: "✅ 訂閱啟用", color: "text-emerald-600 dark:text-emerald-400" },
  trialing: { label: "🧪 訂閱試用中", color: "text-sky-600 dark:text-sky-400" },
  past_due: { label: "💳 訂閱待補款", color: "text-orange-600 dark:text-orange-400" },
  paused: { label: "⏸️ 訂閱已暫停", color: "text-slate-600 dark:text-slate-400" },
  canceled: { label: "🚫 訂閱取消", color: "text-red-600 dark:text-red-400" },
  expired: { label: "⏰ 訂閱到期", color: "text-gray-500 dark:text-gray-400" },
}

function formatDate(iso?: string | null) {
  if (!iso) return "—"
  return new Date(iso).toLocaleString("zh-TW", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

function InfoRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 py-3 border-b border-gray-100 dark:border-gray-800 last:border-0">
      <span className="text-sm text-gray-500 dark:text-gray-400 w-32 shrink-0">{label}</span>
      <span className="text-sm text-gray-900 dark:text-gray-100 font-medium flex-1 break-all">
        {value}
      </span>
    </div>
  )
}

export function PaymentResultPage() {
  const params = new URLSearchParams(window.location.search)
  const transactionId = params.get("transaction_id")
  const subscriptionId = params.get("subscription_id")
  const type = params.get("type") ?? (transactionId ? "payment" : "subscription")

  const [data, setData] = useState<PaymentData | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const queryParam = transactionId
    ? `transaction_id=${transactionId}`
    : `subscription_id=${subscriptionId}`

  const fetchResult = useCallback(
    async (manual = false) => {
      const id = transactionId || subscriptionId
      if (!id) {
        setError("找不到交易或訂閱識別碼，請確認連結是否正確。")
        setLoading(false)
        return
      }

      if (manual) {
        setRefreshing(true)
      } else {
        setLoading(true)
      }
      setError(null)

      try {
        const response = await sendRequest({
          method: "GET",
          url: `/api/v1/payments/result/?${queryParam}`,
          headers: { "Content-Type": "application/json" },
        })
        const body = response.body as {
          status?: string
          message?: string
          data?: PaymentData
        }
        if (response.status >= 400 || body.status !== "success") {
          throw new Error(body.message ?? `HTTP ${response.status}`)
        }
        setData(body.data ?? null)
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : "查詢失敗，請稍後再試。")
      } finally {
        setLoading(false)
        setRefreshing(false)
      }
    },
    [queryParam, subscriptionId, transactionId],
  )

  useEffect(() => {
    void fetchResult()
  }, [fetchResult])

  const shouldAutoRefresh = useMemo(() => {
    if (!data) {
      return false
    }
    return ["pending", "trialing", "past_due"].includes(data.status)
  }, [data])

  useEffect(() => {
    if (!shouldAutoRefresh) {
      return
    }

    const timer = window.setTimeout(() => {
      void fetchResult(true)
    }, 5000)

    return () => {
      window.clearTimeout(timer)
    }
  }, [fetchResult, shouldAutoRefresh, data?.status])

  const statusInfo = data ? (STATUS_LABELS[data.status] ?? { label: data.status, color: "text-gray-700" }) : null

  return (
    <div className="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col">
      {/* 頂部導覽列 */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900">
        <h1 className="text-lg font-bold flex items-center gap-2">
          💳 <span>付款結果</span>
        </h1>
        <ThemeToggle />
      </header>

      <main className="flex-1 flex items-start justify-center p-6">
        <div className="w-full max-w-lg bg-white dark:bg-gray-900 rounded-xl shadow-sm border border-gray-200 dark:border-gray-800 overflow-hidden">
          {loading && (
            <div className="flex items-center justify-center py-20 text-gray-400 text-sm">
              <span className="animate-pulse">載入中…</span>
            </div>
          )}

          {error && (
            <div className="p-6">
              <div className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-sm text-red-700 dark:text-red-400">
                {error}
              </div>
            </div>
          )}

          {data && statusInfo && (
            <>
              {/* 狀態橫幅 */}
              <div className="px-6 pt-6 pb-4 border-b border-gray-100 dark:border-gray-800">
                <p className={`text-2xl font-bold ${statusInfo.color}`}>{statusInfo.label}</p>
                <p className="mt-1 text-xs text-gray-400 dark:text-gray-500">
                  {type === "payment" ? "單次付款" : "訂閱方案"}
                </p>
                {shouldAutoRefresh && (
                  <p className="mt-2 text-xs text-amber-600 dark:text-amber-400">
                    系統會每 5 秒自動重刷一次狀態；若 webhook 延遲，也可手動重新整理。
                  </p>
                )}
              </div>

              {/* 詳情 */}
              <div className="px-6 py-2">
                <InfoRow label="識別碼" value={data.id} />

                {/* 付款欄位 */}
                {data.type === "payment" && (
                  <>
                    {data.amount && data.currency && (
                      <InfoRow
                        label="付款金額"
                        value={`${data.amount} ${data.currency}`}
                      />
                    )}
                    {data.gateway && <InfoRow label="金流閘道" value={data.gateway} />}
                    {data.description && <InfoRow label="商品說明" value={data.description} />}
                    {data.order_number && <InfoRow label="訂單編號" value={data.order_number} />}
                    <InfoRow label="付款時間" value={formatDate(data.paid_at)} />
                  </>
                )}

                {/* 訂閱欄位 */}
                {data.type === "subscription" && (
                  <>
                    {data.gateway && <InfoRow label="金流閘道" value={data.gateway} />}
                    {data.gateway_subscription_id && (
                      <InfoRow label="閘道訂閱 ID" value={data.gateway_subscription_id} />
                    )}
                    {data.catalog_item_id && (
                      <InfoRow label="方案 ID" value={data.catalog_item_id} />
                    )}
                    {data.pricing_tier_id && (
                      <InfoRow label="定價層級 ID" value={data.pricing_tier_id} />
                    )}
                    <InfoRow label="週期開始" value={formatDate(data.current_period_start)} />
                    <InfoRow label="週期結束" value={formatDate(data.current_period_end)} />
                    <InfoRow label="試用結束" value={formatDate(data.trial_end)} />
                    <InfoRow
                      label="期末取消"
                      value={data.cancel_at_period_end ? "是" : "否"}
                    />
                  </>
                )}

                <InfoRow label="建立時間" value={formatDate(data.created_at)} />
              </div>
            </>
          )}

          {/* 返回按鈕 */}
          <div className="px-6 pb-6 pt-2 space-y-2">
            <button
              onClick={() => {
                void fetchResult(true)
              }}
              disabled={loading || refreshing}
              className="w-full py-2.5 px-4 rounded-lg border border-gray-300 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-200 text-sm font-medium transition-colors disabled:opacity-50"
            >
              {refreshing ? "重新整理中…" : "🔄 重新整理狀態"}
            </button>
            <button
              onClick={() => {
                window.location.href = "/"
              }}
              className="w-full py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-medium transition-colors"
            >
              ← 返回測試面板
            </button>
          </div>
        </div>
      </main>
    </div>
  )
}
