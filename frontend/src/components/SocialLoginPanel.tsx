import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"

interface SocialLoginPanelProps {
  provider: "google"
}

interface SocialProviderStatus {
  name: string
  display_name: string
  configured: boolean
  missing_env: string[]
  authorization_path: string
}

interface SocialProvidersResponse {
  status: string
  data?: {
    providers?: SocialProviderStatus[]
  }
}

function buildMissingEnvMessage(missingEnv: string[]) {
  return `.env 裡缺少 ${missingEnv.join("、")}`
}

async function fetchSocialProvider(provider: "google"): Promise<SocialProviderStatus> {
  const response = await fetch("/api/v1/auth/social/providers/", {
    method: "GET",
    credentials: "include",
  })

  if (!response.ok) {
    throw new Error("無法取得社交登入設定")
  }

  const body = (await response.json()) as SocialProvidersResponse
  const providerStatus = body.data?.providers?.find((item) => item.name === provider)
  if (!providerStatus) {
    throw new Error("找不到指定的社交登入設定")
  }

  return providerStatus
}

export function SocialLoginPanel({ provider }: SocialLoginPanelProps) {
  const query = useQuery({
    queryKey: ["social-provider-status", provider],
    queryFn: () => fetchSocialProvider(provider),
  })

  useEffect(() => {
    if (!query.data || query.data.configured) {
      return
    }

    const storageKey = `social-login-warning:${provider}:${query.data.missing_env.join(",")}`
    if (window.sessionStorage.getItem(storageKey) === "shown") {
      return
    }

    window.sessionStorage.setItem(storageKey, "shown")
    window.alert(buildMissingEnvMessage(query.data.missing_env))
  }, [provider, query.data])

  const handleStartLogin = () => {
    if (!query.data) {
      return
    }

    if (!query.data.configured) {
      window.alert(buildMissingEnvMessage(query.data.missing_env))
      return
    }

    const returnUrl = `${window.location.origin}${window.location.pathname}`
    const targetUrl = new URL(query.data.authorization_path, window.location.origin)
    targetUrl.searchParams.set("redirect_url", returnUrl)
    window.location.assign(targetUrl.toString())
  }

  if (query.isLoading) {
    return (
      <div className="text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/60 px-3 py-2 rounded">
        正在檢查社交登入設定…
      </div>
    )
  }

  if (query.isError || !query.data) {
    return (
      <div className="space-y-3">
        <div className="text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded">
          無法取得 Google 登入設定狀態，請先確認後端服務是否正常啟動。
        </div>
        <button
          onClick={() => {
            void query.refetch()
          }}
          className="px-4 py-2 bg-gray-600 hover:bg-gray-700 text-white text-sm font-medium rounded-md transition-colors"
        >
          重新檢查設定
        </button>
      </div>
    )
  }

  const missingMessage = buildMissingEnvMessage(query.data.missing_env)

  return (
    <div className="space-y-3">
      <div
        className={`px-3 py-2 rounded text-sm ${
          query.data.configured
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
            : "bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300"
        }`}
      >
        {query.data.configured
          ? "Google 登入設定已就緒，點擊按鈕後會跳轉到 Google 授權頁。"
          : `Google 登入尚未啟用，${missingMessage}。`}
      </div>

      <button
        onClick={handleStartLogin}
        className={`px-4 py-2 text-white text-sm font-medium rounded-md transition-colors ${
          query.data.configured
            ? "bg-red-600 hover:bg-red-700"
            : "bg-amber-600 hover:bg-amber-700"
        }`}
      >
        {query.data.configured ? "使用 Google 登入" : "查看缺少的設定"}
      </button>
    </div>
  )
}
