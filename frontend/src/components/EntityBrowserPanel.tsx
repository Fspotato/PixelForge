import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { sendRequest } from "../api/client"
import { useAuth } from "../hooks/useAuthStore"

type ResourceType = "orders" | "subscriptions"

interface OrderListItem {
  id: string
  order_number: string
  status: string
  total_amount: string
  currency: string
  description: string
  catalog_item_name?: string
  pricing_tier_name?: string
  paid_at: string | null
  created_at: string
}

interface TransactionItem {
  id: string
  gateway: string
  gateway_order_id?: string
  amount: string
  currency: string
  status: string
  created_at: string
}

interface OrderDetail extends OrderListItem {
  catalog_item_id?: string | null
  pricing_tier_id?: string | null
  metadata?: Record<string, unknown>
  transaction_count?: number
  transactions?: TransactionItem[]
}

interface SubscriptionListItem {
  id: string
  status: string
  gateway: string
  catalog_item_id?: string | null
  catalog_item_name?: string
  pricing_tier_id?: string | null
  pricing_tier_name?: string
  current_period_end: string | null
  cancel_at_period_end: boolean
  created_at: string
}

interface SubscriptionPeriodItem {
  id: string
  amount_paid: string
  currency: string
  status: string
  period_start: string
  period_end: string
}

interface SubscriptionDetail extends SubscriptionListItem {
  gateway_subscription_id?: string
  current_period_start?: string | null
  trial_end?: string | null
  canceled_at?: string | null
  terminated_at?: string | null
  terminated_by?: string
  metadata?: Record<string, unknown>
  periods?: SubscriptionPeriodItem[]
}

const STATUS_COLORS: Record<string, string> = {
  pending:
    "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300",
  paid: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  refunded: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  partially_refunded:
    "bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300",
  canceled: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  expired: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  active: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  past_due: "bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300",
  paused: "bg-slate-100 text-slate-700 dark:bg-slate-800/70 dark:text-slate-300",
  terminated: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "—"
  }
  return new Date(value).toLocaleString("zh-TW")
}

function extractRows(resource: ResourceType, body: unknown) {
  const rows = (body as { data?: unknown[] }).data ?? []
  return resource === "orders"
    ? (rows as OrderListItem[])
    : (rows as SubscriptionListItem[])
}

function extractDetail<T>(body: unknown) {
  return ((body as { data?: T }).data ?? null) as T | null
}

export function EntityBrowserPanel({ resource }: { resource: ResourceType }) {
  const auth = useAuth()
  const [selectedId, setSelectedId] = useState("")

  const isOrderPanel = resource === "orders"
  const title = isOrderPanel ? "訂單列表" : "我的訂閱列表"
  const description = isOrderPanel
    ? "自動載入目前使用者的訂單，點選任一列後立即查詢該筆訂單詳情。"
    : "自動載入目前使用者的訂閱，點選任一列後立即查詢該筆訂閱詳情。"
  const listUrl = isOrderPanel ? "/api/v1/payments/orders/" : "/api/v1/subscriptions/"
  const detailUrl = isOrderPanel
    ? `/api/v1/payments/orders/${selectedId}/`
    : `/api/v1/subscriptions/${selectedId}/`

  const {
    data: rows = [],
    isLoading: isListLoading,
    refetch: refetchList,
  } = useQuery<OrderListItem[] | SubscriptionListItem[]>({
    queryKey: ["entity-browser-list", resource],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: listUrl,
      })
      if (response.status >= 400) {
        throw new Error(`取得列表失敗 (${response.status})`)
      }
      return extractRows(resource, response.body)
    },
    enabled: auth.isAuthenticated,
  })

  useEffect(() => {
    if (rows.length === 0) {
      setSelectedId("")
      return
    }

    const hasSelectedRow = rows.some((row) => row.id === selectedId)
    if (!selectedId || !hasSelectedRow) {
      setSelectedId(rows[0].id)
    }
  }, [rows, selectedId])

  const {
    data: detail,
    isLoading: isDetailLoading,
    refetch: refetchDetail,
  } = useQuery<OrderDetail | SubscriptionDetail | null>({
    queryKey: ["entity-browser-detail", resource, selectedId],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: detailUrl,
      })
      if (response.status >= 400) {
        throw new Error(`取得詳情失敗 (${response.status})`)
      }
      return isOrderPanel
        ? extractDetail<OrderDetail>(response.body)
        : extractDetail<SubscriptionDetail>(response.body)
    },
    enabled: auth.isAuthenticated && !!selectedId,
  })

  if (!auth.isAuthenticated) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
        <div className="text-center">
          <p className="text-4xl mb-2">🔒</p>
          <p className="text-sm">請先登入以查看資料</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <div>
          <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">{title}</h2>
          <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{description}</p>
        </div>
        <button
          onClick={() => {
            void refetchList()
            if (selectedId) {
              void refetchDetail()
            }
          }}
          className="px-3 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded-md hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-600 dark:text-gray-400 transition-colors"
        >
          🔄 重新載入
        </button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {isListLoading ? (
          <div className="flex items-center justify-center h-40">
            <span className="inline-block w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          </div>
        ) : rows.length === 0 ? (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">
            <p className="text-3xl mb-2">{isOrderPanel ? "📦" : "🧾"}</p>
            <p className="text-sm">{isOrderPanel ? "目前沒有任何訂單" : "目前沒有任何訂閱"}</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)] gap-4">
            <section className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl overflow-hidden">
              <div className="overflow-auto">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="border-b border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-800/60">
                      {(isOrderPanel
                        ? ["單號 / 商品", "狀態", "金額", "建立時間", "付款時間"]
                        : ["商品 / 方案", "狀態", "閘道", "週期結束", "建立時間"]
                      ).map((heading) => (
                        <th
                          key={heading}
                          className="text-left py-2 px-3 font-medium text-gray-500 dark:text-gray-400 whitespace-nowrap"
                        >
                          {heading}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((row) =>
                      isOrderPanel ? (
                        <tr
                          key={row.id}
                          onClick={() => setSelectedId(row.id)}
                          className={`border-b border-gray-100 dark:border-gray-800 cursor-pointer transition-colors ${
                            selectedId === row.id
                              ? "bg-blue-50 dark:bg-blue-900/20"
                              : "hover:bg-gray-50 dark:hover:bg-gray-800/40"
                          }`}
                        >
                          <td className="py-3 px-3">
                            <p className="font-mono text-gray-700 dark:text-gray-200">
                              {(row as OrderListItem).order_number}
                            </p>
                            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                              {(row as OrderListItem).catalog_item_name ||
                                (row as OrderListItem).description ||
                                "未綁定商品"}
                            </p>
                          </td>
                          <td className="py-3 px-3">
                            <span
                              className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                STATUS_COLORS[(row as OrderListItem).status] ??
                                "bg-gray-100 text-gray-600"
                              }`}
                            >
                              {(row as OrderListItem).status}
                            </span>
                          </td>
                          <td className="py-3 px-3 font-mono text-gray-700 dark:text-gray-300 whitespace-nowrap">
                            {(row as OrderListItem).total_amount} {(row as OrderListItem).currency}
                          </td>
                          <td className="py-3 px-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                            {formatDateTime((row as OrderListItem).created_at)}
                          </td>
                          <td className="py-3 px-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                            {formatDateTime((row as OrderListItem).paid_at)}
                          </td>
                        </tr>
                      ) : (
                        <tr
                          key={row.id}
                          onClick={() => setSelectedId(row.id)}
                          className={`border-b border-gray-100 dark:border-gray-800 cursor-pointer transition-colors ${
                            selectedId === row.id
                              ? "bg-blue-50 dark:bg-blue-900/20"
                              : "hover:bg-gray-50 dark:hover:bg-gray-800/40"
                          }`}
                        >
                          <td className="py-3 px-3">
                            <p className="text-gray-700 dark:text-gray-200">
                              {(row as SubscriptionListItem).catalog_item_name || "未綁定商品"}
                            </p>
                            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                              {(row as SubscriptionListItem).pricing_tier_name || "未命名方案"}
                            </p>
                          </td>
                          <td className="py-3 px-3">
                            <span
                              className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                STATUS_COLORS[(row as SubscriptionListItem).status] ??
                                "bg-gray-100 text-gray-600"
                              }`}
                            >
                              {(row as SubscriptionListItem).status}
                            </span>
                          </td>
                          <td className="py-3 px-3 text-gray-700 dark:text-gray-300 whitespace-nowrap">
                            {(row as SubscriptionListItem).gateway}
                          </td>
                          <td className="py-3 px-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                            {formatDateTime((row as SubscriptionListItem).current_period_end)}
                          </td>
                          <td className="py-3 px-3 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                            {formatDateTime((row as SubscriptionListItem).created_at)}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            </section>

            <section className="space-y-4">
              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">詳情</h3>

                {isDetailLoading || !detail ? (
                  <div className="flex items-center justify-center h-32">
                    <span className="inline-block w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
                  </div>
                ) : isOrderPanel ? (
                  <>
                    <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">訂單編號</p>
                        <p className="mt-1 font-mono text-sm text-gray-800 dark:text-gray-100">
                          {(detail as OrderDetail).order_number}
                        </p>
                      </div>
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">交易筆數</p>
                        <p className="mt-1 text-sm text-gray-800 dark:text-gray-100">
                          {(detail as OrderDetail).transaction_count ?? 0}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4">
                      <h4 className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                        交易紀錄
                      </h4>
                      <div className="mt-2 space-y-2">
                        {((detail as OrderDetail).transactions ?? []).map((transaction) => (
                          <div
                            key={transaction.id}
                            className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-mono text-[11px] text-gray-600 dark:text-gray-300">
                                {transaction.id}
                              </span>
                              <span
                                className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                  STATUS_COLORS[transaction.status] ??
                                  "bg-gray-100 text-gray-600"
                                }`}
                              >
                                {transaction.status}
                              </span>
                            </div>
                            <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                              {transaction.gateway} / {transaction.amount} {transaction.currency}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">商品</p>
                        <p className="mt-1 text-sm text-gray-800 dark:text-gray-100">
                          {(detail as SubscriptionDetail).catalog_item_name || "未綁定商品"}
                        </p>
                      </div>
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">Gateway 訂閱 ID</p>
                        <p className="mt-1 font-mono text-sm text-gray-800 dark:text-gray-100">
                          {(detail as SubscriptionDetail).gateway_subscription_id || "—"}
                        </p>
                      </div>
                    </div>

                    <div className="mt-4">
                      <h4 className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                        週期紀錄
                      </h4>
                      <div className="mt-2 space-y-2">
                        {((detail as SubscriptionDetail).periods ?? []).map((period) => (
                          <div
                            key={period.id}
                            className="rounded-lg border border-gray-200 dark:border-gray-700 px-3 py-2"
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="text-xs text-gray-700 dark:text-gray-200">
                                {period.amount_paid} {period.currency}
                              </span>
                              <span
                                className={`px-1.5 py-0.5 rounded-full text-[10px] font-medium ${
                                  STATUS_COLORS[period.status] ??
                                  "bg-gray-100 text-gray-600"
                                }`}
                              >
                                {period.status}
                              </span>
                            </div>
                            <p className="mt-1 text-[11px] text-gray-500 dark:text-gray-400">
                              {formatDateTime(period.period_start)} ~ {formatDateTime(period.period_end)}
                            </p>
                          </div>
                        ))}
                      </div>
                    </div>
                  </>
                )}
              </div>

              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">原始回應</h3>
                <pre className="mt-3 overflow-auto rounded-lg bg-gray-950 text-gray-100 text-xs p-3">
                  {JSON.stringify(detail ?? { message: "尚未載入詳情" }, null, 2)}
                </pre>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
