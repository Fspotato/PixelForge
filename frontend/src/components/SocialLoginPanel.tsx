import { useEffect } from "react"
import { useQuery } from "@tanstack/react-query"

interface SocialLoginPanelProps {
  provider: "google"
  hideStatus?: boolean
  fullWidth?: boolean
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

function GoogleIcon() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path fill="#34A853" d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path fill="#FBBC05" d="M5.84 14.1c-.22-.66-.35-1.36-.35-2.1s.13-1.44.35-2.1V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.84z" />
      <path fill="#EA4335" d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06L5.84 9.9c.87-2.6 3.3-4.52 6.16-4.52z" />
    </svg>
  )
}

export function SocialLoginPanel({ provider, hideStatus = false, fullWidth = false }: SocialLoginPanelProps) {
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
      <div className={`text-xs text-gray-500 dark:text-gray-400 bg-gray-50 dark:bg-gray-800/60 px-3 py-2 rounded ${hideStatus ? "hidden" : ""}`}>
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
      {!hideStatus && (
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
      )}

      <button
        onClick={handleStartLogin}
        className={`inline-flex items-center justify-center gap-3 rounded-lg px-4 py-2 text-sm font-semibold transition-colors ${
          fullWidth ? "w-full" : ""
        } ${
          query.data.configured
            ? "border border-white/20 bg-white text-slate-900 hover:bg-slate-100"
            : "bg-amber-600 text-white hover:bg-amber-700"
        }`}
      >
        {query.data.configured && <GoogleIcon />}
        {query.data.configured ? "使用 Google 登入" : "查看缺少的設定"}
      </button>
    </div>
  )
}
