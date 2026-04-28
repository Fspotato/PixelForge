import { useEffect, useMemo, useState } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { sendRequest } from "../api/client"
import { useAuth } from "../hooks/useAuthStore"

type PanelMode = "checkout" | "subscription"

interface GatewayInfo {
  name: string
  display_name: string
  is_healthy: boolean
  supported_currencies: string[]
  supports_subscription?: boolean
}

interface CatalogItemSummary {
  id: string
  name: string
  slug: string
  description: string
  base_amount: string
  base_currency: string
}

interface GatewayPriceMapping {
  id: string
  gateway: string
  gateway_price_id: string
  gateway_product_id: string
  is_active: boolean
}

interface PricingTier {
  id: string
  name: string
  amount: string
  currency: string
  billing_interval: string | null
  billing_interval_count: number
  trial_period_days: number
  gateway_mappings: GatewayPriceMapping[]
}

interface CatalogItemDetail extends CatalogItemSummary {
  pricing_tiers: PricingTier[]
}

interface ActionResponse {
  checkout_url?: string
  order_id?: string
  transaction_id?: string
  subscription_id?: string
  status?: string
  gateway?: string
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "message" in body) {
    const message = (body as { message?: unknown }).message
    if (typeof message === "string" && message.trim()) {
      return message
    }
  }
  return fallback
}

function formatTierLabel(tier: PricingTier): string {
  const interval = tier.billing_interval
    ? `${tier.billing_interval_count}${tier.billing_interval}`
    : "單次"
  const title = tier.name || "未命名方案"
  return `${title} — ${tier.amount} ${tier.currency} / ${interval}`
}

function normalizeGatewayName(value: string | null | undefined): string {
  return (value || "").trim().toLowerCase()
}

export function CatalogActionPanel({ mode }: { mode: PanelMode }) {
  const auth = useAuth()
  const [selectedGateway, setSelectedGateway] = useState("")
  const [selectedItemSlug, setSelectedItemSlug] = useState("")
  const [selectedTierId, setSelectedTierId] = useState("")
  const [lastResult, setLastResult] = useState<ActionResponse | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)

  const itemType = mode === "checkout" ? "one_time" : "subscription"
  const panelTitle = mode === "checkout" ? "建立結帳" : "建立訂閱"
  const panelDescription =
    mode === "checkout"
      ? "直接從商品目錄抓取單次商品與定價，選擇後建立結帳並跳轉至付款頁。"
      : "直接從商品目錄抓取訂閱商品與定價，選擇後建立訂閱並跳轉至 Stripe 訂閱結帳頁。"
  const endpoint =
    mode === "checkout" ? "/api/v1/payments/checkout/" : "/api/v1/subscriptions/create/"

  const { data: gateways = [], isLoading: isGatewayLoading } = useQuery<GatewayInfo[]>({
    queryKey: ["catalog-action-gateways"],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: "/api/v1/payments/gateways/",
      })
      if (response.status >= 400) {
        throw new Error(`取得閘道列表失敗 (${response.status})`)
      }
      return ((response.body as { data?: GatewayInfo[] }).data ?? []) as GatewayInfo[]
    },
    enabled: auth.isAuthenticated,
  })

  const { data: items = [], isLoading: isItemsLoading } = useQuery<CatalogItemSummary[]>({
    queryKey: ["catalog-action-items", itemType],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: `/api/v1/catalog/items/?type=${itemType}`,
      })
      if (response.status >= 400) {
        throw new Error(`取得商品列表失敗 (${response.status})`)
      }
      return ((response.body as { data?: CatalogItemSummary[] }).data ?? []) as CatalogItemSummary[]
    },
    enabled: auth.isAuthenticated,
  })

  const { data: selectedItemDetail, isLoading: isDetailLoading } = useQuery<CatalogItemDetail>({
    queryKey: ["catalog-action-item-detail", selectedItemSlug],
    queryFn: async () => {
      const response = await sendRequest({
        method: "GET",
        url: `/api/v1/catalog/items/${selectedItemSlug}/`,
      })
      if (response.status >= 400) {
        throw new Error(`取得商品詳情失敗 (${response.status})`)
      }
      return ((response.body as { data?: CatalogItemDetail }).data ?? null) as CatalogItemDetail
    },
    enabled: auth.isAuthenticated && !!selectedItemSlug,
  })

  useEffect(() => {
    if (!selectedItemSlug && items.length > 0) {
      setSelectedItemSlug(items[0].slug)
    }
  }, [items, selectedItemSlug])

  useEffect(() => {
    if (!selectedItemDetail) {
      return
    }
    const firstActiveTier = selectedItemDetail.pricing_tiers.find((tier) => tier.id) ?? null
    if (!firstActiveTier) {
      setSelectedTierId("")
      return
    }
    if (!selectedTierId || !selectedItemDetail.pricing_tiers.some((tier) => tier.id === selectedTierId)) {
      setSelectedTierId(firstActiveTier.id)
    }
  }, [selectedItemDetail, selectedTierId])

  const selectedTier =
    selectedItemDetail?.pricing_tiers.find((tier) => tier.id === selectedTierId) ?? null

  const availableGateways = useMemo(() => {
    const healthyGateways = gateways.filter((gateway) => gateway.is_healthy)
    if (mode !== "subscription") {
      return healthyGateways
    }

    const subscriptionReadyGateways = healthyGateways.filter(
      (gateway) => gateway.supports_subscription,
    )

    if (!selectedTier) {
      return subscriptionReadyGateways
    }

    const mappedGatewayNames = new Set(
      selectedTier.gateway_mappings
        .filter((mapping) => mapping.is_active)
        .map((mapping) => normalizeGatewayName(mapping.gateway))
        .filter(Boolean),
    )

    if (mappedGatewayNames.size === 0) {
      return subscriptionReadyGateways
    }

    return subscriptionReadyGateways.filter((gateway) =>
      mappedGatewayNames.has(normalizeGatewayName(gateway.name)),
    )
  }, [gateways, mode, selectedTier])

  useEffect(() => {
    if (availableGateways.length === 0) {
      setSelectedGateway("")
      return
    }

    if (!selectedGateway || !availableGateways.some((gateway) => gateway.name === selectedGateway)) {
      setSelectedGateway(availableGateways[0].name)
    }
  }, [availableGateways, selectedGateway])

  const selectedGatewayMapping =
    selectedTier?.gateway_mappings.find(
      (mapping) =>
        mapping.is_active &&
        normalizeGatewayName(mapping.gateway) === normalizeGatewayName(selectedGateway),
    ) ?? null
  const hasSubscriptionPriceMapping =
    mode !== "subscription" || !!selectedGatewayMapping?.gateway_price_id?.trim()

  const createMutation = useMutation({
    mutationFn: async () => {
      setSubmitError(null)

      if (!selectedItemDetail || !selectedTier || !selectedGateway) {
        throw new Error("請先選擇商品、方案與閘道")
      }

      const payload: Record<string, unknown> = {
        gateway: selectedGateway,
        catalog_item_id: selectedItemDetail.id,
        pricing_tier_id: selectedTier.id,
      }

      if (mode === "subscription" && selectedGatewayMapping?.gateway_price_id) {
        payload.gateway_price_id = selectedGatewayMapping.gateway_price_id
      }

      const response = await sendRequest({
        method: "POST",
        url: endpoint,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      })

      if (response.status >= 400) {
        throw new Error(extractMessage(response.body, `請求失敗 (${response.status})`))
      }

      return ((response.body as { data?: ActionResponse }).data ?? {}) as ActionResponse
    },
    onSuccess: (data) => {
      setLastResult(data)
      const checkoutUrl = data.checkout_url
      if (typeof checkoutUrl === "string" && checkoutUrl.trim()) {
        window.location.assign(checkoutUrl)
      }
    },
    onError: (error) => {
      setSubmitError(String(error))
    },
  })

  if (!auth.isAuthenticated) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-500">
        <div className="text-center">
          <p className="text-4xl mb-2">🔒</p>
          <p className="text-sm">請先登入後再建立結帳或訂閱</p>
        </div>
      </div>
    )
  }

  const isLoading = isGatewayLoading || isItemsLoading || isDetailLoading

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-900 shrink-0">
        <h2 className="text-sm font-semibold text-gray-800 dark:text-gray-100">{panelTitle}</h2>
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">{panelDescription}</p>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <div className="flex items-center justify-center h-40">
            <span className="inline-block w-5 h-5 border-2 border-blue-300 border-t-blue-600 rounded-full animate-spin" />
          </div>
        ) : items.length === 0 ? (
          <div className="text-center py-12 text-gray-400 dark:text-gray-500">
            <p className="text-3xl mb-2">📭</p>
            <p className="text-sm">目前沒有可用的商品目錄資料</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)] gap-4">
            <section className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4 space-y-4">
              <div className="space-y-1">
                <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                  金流閘道
                </label>
                <select
                  value={selectedGateway}
                  onChange={(event) => setSelectedGateway(event.target.value)}
                  disabled={availableGateways.length === 0}
                  className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-800 dark:text-gray-100"
                >
                  {availableGateways.map((gateway) => (
                    <option key={gateway.name} value={gateway.name}>
                      {gateway.display_name} ({gateway.name})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                  商品
                </label>
                <select
                  value={selectedItemSlug}
                  onChange={(event) => setSelectedItemSlug(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-800 dark:text-gray-100"
                >
                  {items.map((item) => (
                    <option key={item.id} value={item.slug}>
                      {item.name} ({item.base_amount} {item.base_currency})
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-medium text-gray-600 dark:text-gray-300">
                  定價方案
                </label>
                <select
                  value={selectedTierId}
                  onChange={(event) => setSelectedTierId(event.target.value)}
                  className="w-full rounded-lg border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-2 text-sm text-gray-800 dark:text-gray-100"
                >
                  {(selectedItemDetail?.pricing_tiers ?? []).map((tier) => (
                    <option key={tier.id} value={tier.id}>
                      {formatTierLabel(tier)}
                    </option>
                  ))}
                </select>
              </div>

              {mode === "subscription" && selectedTier && availableGateways.length === 0 && (
                <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                  目前選定方案沒有可用的訂閱閘道。請確認此方案已有有效的 gateway mapping，
                  並且閘道健康檢查通過且支援訂閱。
                </div>
              )}

              {mode === "subscription" &&
                selectedGateway &&
                selectedTier &&
                availableGateways.length > 0 &&
                !hasSubscriptionPriceMapping && (
                  <div className="rounded-lg border border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
                    目前選定的閘道尚未綁定有效的 Stripe Price ID，請先在後台商品定價中設定
                    `gateway_price_id`。
                  </div>
                )}

              {mode === "subscription" && selectedGatewayMapping && (
                <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 px-3 py-2 text-xs text-blue-700 dark:text-blue-300">
                  目前會自動帶入 Price ID：{selectedGatewayMapping.gateway_price_id || "未設定"}
                </div>
              )}

              {submitError && (
                <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 px-3 py-2 text-xs text-red-700 dark:text-red-300">
                  ❌ {submitError}
                </div>
              )}

              <button
                onClick={() => createMutation.mutate()}
                disabled={
                  createMutation.isPending ||
                  !selectedItemDetail ||
                  !selectedTier ||
                  !selectedGateway ||
                  !hasSubscriptionPriceMapping
                }
                className="w-full rounded-lg bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed px-4 py-2 text-sm font-medium text-white transition-colors"
              >
                {createMutation.isPending
                  ? "處理中…"
                  : mode === "checkout"
                    ? "建立結帳並前往付款"
                    : "建立訂閱並前往付款"}
              </button>
            </section>

            <section className="space-y-4">
              {selectedItemDetail && (
                <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
                        {selectedItemDetail.name}
                      </h3>
                      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">
                        {selectedItemDetail.description || "此商品目前沒有描述"}
                      </p>
                    </div>
                    <span className="text-xs px-2 py-1 rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300">
                      {selectedItemDetail.base_amount} {selectedItemDetail.base_currency}
                    </span>
                  </div>

                  {selectedTier && (
                    <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3">
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">方案</p>
                        <p className="mt-1 text-sm font-medium text-gray-800 dark:text-gray-100">
                          {selectedTier.name || "未命名方案"}
                        </p>
                      </div>
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">金額</p>
                        <p className="mt-1 text-sm font-medium text-gray-800 dark:text-gray-100">
                          {selectedTier.amount} {selectedTier.currency}
                        </p>
                      </div>
                      <div className="rounded-lg bg-gray-50 dark:bg-gray-800/70 px-3 py-2">
                        <p className="text-[11px] text-gray-500 dark:text-gray-400">週期</p>
                        <p className="mt-1 text-sm font-medium text-gray-800 dark:text-gray-100">
                          {selectedTier.billing_interval
                            ? `${selectedTier.billing_interval_count} ${selectedTier.billing_interval}`
                            : "單次購買"}
                        </p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-100">
                  最近一次回應
                </h3>
                <pre className="mt-3 overflow-auto rounded-lg bg-gray-950 text-gray-100 text-xs p-3">
                  {JSON.stringify(lastResult ?? { message: "尚未送出請求" }, null, 2)}
                </pre>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  )
}
