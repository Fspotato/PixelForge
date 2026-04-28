import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { useAuth } from "../hooks/useAuthStore"
import { sendRequest } from "../api/client"

/* ── 類型定義 ─────────────────────────────────────── */

interface Order {
  id: string
  order_number: string
  status: string
  total_amount: string
  currency: string
  description: string
  paid_at: string | null
  created_at: string
}

interface SyncResult {
  transaction_id: string
  order_id: string
  order_number: string
  gateway: string
  amount: string
  currency: string
  old_status: string
  new_status: string
  changed: boolean
}

interface SyncResponse {
  synced_count: number
  changed_count: number
  results: SyncResult[]
}

/* ── 常數 ─────────────────────────────────────────── */

const STATUS_COLORS: Record<string, string> = {
  pending:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  refunded:
    "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  partially_refunded:
    "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300",
  canceled:
    "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  expired: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
}

/* ── 元件 ────────────────────────────────────────── */

/** 訂單列表 + Stripe 狀態同步面板 */
export function OrderSyncPanel() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [syncResponse, setSyncResponse] = useState<SyncResponse | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  // 載入訂單列表
  const {
    data: orders = [],
    isLoading,
    refetch,
  } = useQuery<Order[]>({
    queryKey: ["order-sync-panel"],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: "/api/v1/payments/orders/",
      })
      if (response.status >= 400) {
        throw new Error(`取得訂單失敗 (${response.status})`)
      }
      return ((response.body as { data?: Order[] }).data ?? []) as Order[]
    },
    enabled: auth.isAuthenticated,
  })

  // 向 Stripe 批次同步 pending 交易
  const syncMutation = useMutation({
    mutationFn: async () => {
      setSyncError(null)
      const res = await sendRequest({
        method: "POST",
        url: "/api/v1/payments/orders/sync-all/",
      })
      if (res.status >= 400) {
        const body = res.body as { message?: string }
        throw new Error(body?.message ?? `同步失敗 (${res.status})`)
      }
      return ((res.body as { data?: SyncResponse }).data ?? {
        synced_count: 0,
        changed_count: 0,
        results: [],
      }) as SyncResponse
    },
    onSuccess: (data) => {
      setSyncResponse(data)
      // 同步後重新載入訂單，反映最新狀態
      queryClient.invalidateQueries({ queryKey: ["order-sync-panel"] })
    },
    onError: (err) => {
      setSyncError(String(err))
    },
  })

  // 未登入時顯示提示
  if (!auth.isAuthenticated) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
        <div className="text-center">
          <p className="text-4xl mb-2">🔒</p>
          <p className="text-sm">請先登入以查看訂單</p>
        </div>
      </div>
    )
  }

  const changedResults = syncResponse?.results.filter((r) => r.changed) ?? []

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* ── 標題列 ── */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
            訂單狀態同步
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            向 Stripe 拉取此用戶所有 pending 交易的最新狀態
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refetch()}
            disabled={isLoading}
            title="重新載入訂單列表"
            className="px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 transition-colors disabled:opacity-50"
          >
            🔄 重新載入
          </button>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="flex items-center gap-1.5 px-4 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-xs font-medium rounded-md transition-colors"
          >
            {syncMutation.isPending ? (
              <>
                <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                同步中…
              </>
            ) : (
              "⚡ 向 Stripe 同步 pending 交易"
            )}
          </button>
        </div>
      </div>

      {/* ── 同步結果 Banner ── */}
      {syncResponse && (
        <div
          className={`mx-4 mt-3 px-3 py-2 rounded-lg text-xs border shrink-0 ${
            changedResults.length > 0
              ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400"
              : "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400"
          }`}
        >
          ✅ 同步完成：共處理 {syncResponse.synced_count} 筆 pending 交易，
          {syncResponse.changed_count} 筆狀態已更新
          {changedResults.length > 0 && (
            <ul className="mt-1 space-y-0.5 pl-4 list-disc">
              {changedResults.map((r) => (
                <li key={r.transaction_id}>
                  訂單 {r.order_number}：{r.old_status} → {r.new_status}（
                  {r.gateway}）
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {/* ── 錯誤 Banner ── */}
      {syncError && (
        <div className="mx-4 mt-3 px-3 py-2 rounded-lg text-xs border bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 shrink-0">
          ❌ {syncError}
        </div>
      )}

      {/* ── 訂單列表 ── */}
      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-24">
            <span className="inline-block w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          </div>
        ) : orders.length === 0 ? (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">
            <p className="text-3xl mb-2">📦</p>
            <p className="text-sm">目前沒有任何訂單</p>
          </div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                {["訂單編號", "狀態", "金額", "說明", "建立時間", "付款時間"].map(
                  (h) => (
                    <th
                      key={h}
                      className="text-left py-2 px-2 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap"
                    >
                      {h}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody>
              {orders.map((order) => (
                <tr
                  key={order.id}
                  className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
                >
                  <td className="py-2 px-2 font-mono text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {order.order_number}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                        STATUS_COLORS[order.status] ??
                        "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {order.status}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-right font-mono text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {order.total_amount} {order.currency}
                  </td>
                  <td
                    className="py-2 px-2 text-gray-500 dark:text-gray-400 max-w-[200px] truncate"
                    title={order.description}
                  >
                    {order.description || "—"}
                  </td>
                  <td className="py-2 px-2 text-gray-400 dark:text-gray-500 whitespace-nowrap">
                    {new Date(order.created_at).toLocaleString("zh-TW")}
                  </td>
                  <td className="py-2 px-2 text-gray-400 dark:text-gray-500 whitespace-nowrap">
                    {order.paid_at
                      ? new Date(order.paid_at).toLocaleString("zh-TW")
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
