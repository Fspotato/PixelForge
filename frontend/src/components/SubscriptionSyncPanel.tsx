import { useState } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { sendRequest } from "../api/client"
import { useAuth } from "../hooks/useAuthStore"

interface SubscriptionItem {
  id: string
  status: string
  gateway: string
  catalog_item_name?: string
  pricing_tier_name?: string
  current_period_end: string | null
  created_at: string
}

interface SyncResult {
  subscription_id: string
  gateway_subscription_id: string
  gateway: string
  catalog_item_id?: string | null
  pricing_tier_id?: string | null
  old_status: string
  new_status: string
  changed: boolean
}

interface SyncResponse {
  synced_count: number
  changed_count: number
  results: SyncResult[]
}

const STATUS_COLORS: Record<string, string> = {
  pending:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  trialing:
    "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
  active: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  past_due:
    "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  paused: "bg-slate-100 text-slate-700 dark:bg-slate-800/70 dark:text-slate-300",
  canceled: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  expired: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  terminated: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
}

export function SubscriptionSyncPanel() {
  const auth = useAuth()
  const queryClient = useQueryClient()
  const [syncResponse, setSyncResponse] = useState<SyncResponse | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  const {
    data: subscriptions = [],
    isLoading,
    refetch,
  } = useQuery<SubscriptionItem[]>({
    queryKey: ["subscription-sync-panel"],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: "/api/v1/subscriptions/",
      })
      if (response.status >= 400) {
        throw new Error(`取得訂閱失敗 (${response.status})`)
      }
      return ((response.body as { data?: SubscriptionItem[] }).data ?? []) as SubscriptionItem[]
    },
    enabled: auth.isAuthenticated,
  })

  const syncMutation = useMutation({
    mutationFn: async () => {
      setSyncError(null)
      const response = await sendRequest({
        method: "POST",
        url: "/api/v1/subscriptions/sync-all/",
      })
      if (response.status >= 400) {
        const body = response.body as { message?: string }
        throw new Error(body?.message ?? `同步失敗 (${response.status})`)
      }
      return ((response.body as { data?: SyncResponse }).data ?? {
        synced_count: 0,
        changed_count: 0,
        results: [],
      }) as SyncResponse
    },
    onSuccess: (data) => {
      setSyncResponse(data)
      queryClient.invalidateQueries({ queryKey: ["subscription-sync-panel"] })
      queryClient.invalidateQueries({ queryKey: ["entity-browser-list", "subscriptions"] })
      queryClient.invalidateQueries({ queryKey: ["entity-browser-detail", "subscriptions"] })
    },
    onError: (error) => {
      setSyncError(String(error))
    },
  })

  if (!auth.isAuthenticated) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
        <div className="text-center">
          <p className="text-4xl mb-2">🔒</p>
          <p className="text-sm">請先登入以查看訂閱</p>
        </div>
      </div>
    )
  }

  const changedResults = syncResponse?.results.filter((result) => result.changed) ?? []

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
            訂閱狀態同步
          </h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
            向閘道拉取此用戶所有訂閱的最新狀態，作為 webhook 延遲時的補救機制
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => void refetch()}
            disabled={isLoading}
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
              "⚡ 刷新所有訂閱狀態"
            )}
          </button>
        </div>
      </div>

      {syncResponse && (
        <div
          className={`mx-4 mt-3 px-3 py-2 rounded-lg text-xs border shrink-0 ${
            changedResults.length > 0
              ? "bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400"
              : "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400"
          }`}
        >
          ✅ 同步完成：共處理 {syncResponse.synced_count} 筆訂閱，
          {syncResponse.changed_count} 筆狀態已更新
          {changedResults.length > 0 && (
            <ul className="mt-1 space-y-0.5 pl-4 list-disc">
              {changedResults.map((result) => (
                <li key={result.subscription_id}>
                  訂閱 {result.subscription_id.slice(0, 8)}：{result.old_status} →{" "}
                  {result.new_status}（{result.gateway}）
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {syncError && (
        <div className="mx-4 mt-3 px-3 py-2 rounded-lg text-xs border bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400 shrink-0">
          ❌ {syncError}
        </div>
      )}

      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-24">
            <span className="inline-block w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          </div>
        ) : subscriptions.length === 0 ? (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">
            <p className="text-3xl mb-2">🧾</p>
            <p className="text-sm">目前沒有任何訂閱</p>
          </div>
        ) : (
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="border-b border-gray-200 dark:border-gray-700">
                {["商品", "方案", "狀態", "閘道", "週期結束", "建立時間"].map((heading) => (
                  <th
                    key={heading}
                    className="text-left py-2 px-2 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {subscriptions.map((subscription) => (
                <tr
                  key={subscription.id}
                  className="border-b border-gray-100 dark:border-gray-800 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
                >
                  <td className="py-2 px-2 text-gray-700 dark:text-gray-300">
                    {subscription.catalog_item_name || "未綁定商品"}
                  </td>
                  <td className="py-2 px-2 text-gray-500 dark:text-gray-400">
                    {subscription.pricing_tier_name || "未命名方案"}
                  </td>
                  <td className="py-2 px-2">
                    <span
                      className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                        STATUS_COLORS[subscription.status] ?? "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {subscription.status}
                    </span>
                  </td>
                  <td className="py-2 px-2 text-gray-700 dark:text-gray-300 whitespace-nowrap">
                    {subscription.gateway}
                  </td>
                  <td className="py-2 px-2 text-gray-400 dark:text-gray-500 whitespace-nowrap">
                    {subscription.current_period_end
                      ? new Date(subscription.current_period_end).toLocaleString("zh-TW")
                      : "—"}
                  </td>
                  <td className="py-2 px-2 text-gray-400 dark:text-gray-500 whitespace-nowrap">
                    {new Date(subscription.created_at).toLocaleString("zh-TW")}
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
