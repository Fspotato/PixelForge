import { useState, useEffect, useMemo } from "react"
import { useMutation, useQuery } from "@tanstack/react-query"
import { useAuth } from "../hooks/useAuthStore"
import { sendRequest } from "../api/client"
import type { TestCase } from "../types"

/* ── 類型定義 ─────────────────────────────────────── */

interface ProviderConfig {
  id: string
  name: string
  available: boolean
  text_models: string[]
  image_models: string[]
  default_text_model: string
  default_image_model: string
}

/* ── 元件 ────────────────────────────────────────── */

interface AiTestPanelProps {
  testCase: TestCase
}

export function AiTestPanel({ testCase }: AiTestPanelProps) {
  const auth = useAuth()
  const mode = testCase.id === "ai-image" ? "image" : "text"

  // 從後端 ENV 讀取供應商與模型配置
  const { data: providers = [], isLoading: configLoading } = useQuery({
    queryKey: ["ai-test-config"],
    queryFn: async () => {
      const res = await fetch("/api/v1/ai-providers/test-config/")
      if (!res.ok) throw new Error("無法取得配置")
      const json = await res.json()
      return (json.data?.providers as ProviderConfig[]) ?? []
    },
    staleTime: 5 * 60 * 1000,
  })

  const [providerId, setProviderId] = useState("")
  const [model, setModel] = useState("")
  const [input, setInput] = useState(
    mode === "text"
      ? "你好，請介紹一下你自己"
      : "一隻可愛的貓咪在花園裡玩耍",
  )
  const [responseData, setResponseData] = useState<ResponseShape | null>(null)

  // 配置載入後設定預設供應商與模型
  useEffect(() => {
    if (providers.length > 0 && !providerId) {
      const first = providers[0]
      setProviderId(first.id)
      setModel(
        mode === "text" ? first.default_text_model : first.default_image_model,
      )
    }
  }, [providers, providerId, mode])

  const currentProvider = providers.find((p) => p.id === providerId)
  const isAvailable = currentProvider?.available ?? false
  const models =
    mode === "text"
      ? (currentProvider?.text_models ?? [])
      : (currentProvider?.image_models ?? [])

  const handleProviderChange = (newId: string) => {
    setProviderId(newId)
    setResponseData(null)
    const p = providers.find((x) => x.id === newId)
    if (p) {
      const def =
        mode === "text" ? p.default_text_model : p.default_image_model
      setModel(
        def ||
          (mode === "text" ? p.text_models[0] : p.image_models[0]) ||
          "",
      )
    }
  }

  const mutation = useMutation({
    mutationFn: sendRequest,
    onSuccess: (res) => setResponseData(res),
    onError: (error) =>
      setResponseData({
        status: 0,
        statusText: "網路錯誤",
        headers: {},
        body: { error: String(error) },
        duration: 0,
      }),
  })

  const canSend =
    auth.isAuthenticated &&
    isAvailable &&
    input.trim().length > 0 &&
    !mutation.isPending &&
    model.length > 0

  const handleSend = () => {
    if (!canSend) return

    if (mode === "text") {
      mutation.mutate({
        method: "POST",
        url: "/api/v1/ai-providers/chat/",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: providerId,
          model,
          messages: [{ role: "user", content: input }],
          temperature: 0.7,
        }),
      })
    } else {
      mutation.mutate({
        method: "POST",
        url: "/api/v1/ai-providers/image/generate/",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: providerId,
          model,
          prompt: input,
          n: 1,
          size: "1024x1024",
        }),
      })
    }
  }

  // Ctrl+Enter / Cmd+Enter 快捷鍵
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault()
        handleSend()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  })

  const isMac =
    typeof navigator !== "undefined" &&
    /Mac|iPhone|iPad/.test(navigator.platform)

  const parsed = useMemo(
    () => parseResponse(responseData),
    [responseData],
  )

  /* ── 載入中 ── */
  if (configLoading) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-600 text-sm">
        載入供應商配置中…
      </div>
    )
  }

  /* ── 主畫面 ── */
  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* ── 請求區域 ── */}
      <div className="p-4 border-b border-gray-200 dark:border-gray-800 space-y-4 shrink-0 bg-white dark:bg-gray-900 overflow-y-auto">
        {/* Method + URL */}
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 text-xs font-bold text-white rounded bg-blue-500">
            POST
          </span>
          <code className="flex-1 text-sm font-mono text-gray-800 dark:text-gray-200 bg-gray-100 dark:bg-gray-800 px-3 py-1.5 rounded overflow-x-auto">
            {testCase.path}
          </code>
        </div>

        <p className="text-sm text-gray-500 dark:text-gray-400">
          {testCase.description}
        </p>

        {/* 認證警告 */}
        {!auth.isAuthenticated && (
          <Alert variant="amber">
            ⚠️ 此端點需要認證。請先登入建立 cookie session。
          </Alert>
        )}

        {/* 供應商 / 模型選擇 */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              供應商
            </label>
            <select
              value={providerId}
              onChange={(e) => handleProviderChange(e.target.value)}
              className={SELECT_CLS}
            >
              {providers.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                  {!p.available ? "（尚未啟用）" : ""}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              模型
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className={SELECT_CLS}
            >
              {models.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
              {models.length === 0 && (
                <option disabled>
                  此供應商無{mode === "text" ? "文字" : "圖像"}模型
                </option>
              )}
            </select>
          </div>
        </div>

        {/* 供應商未啟用提示 */}
        {!isAvailable && currentProvider && (
          <Alert variant="amber">
            ⚠️ 「{currentProvider.name}
            」目前尚未設定 API Key，暫時無法調用。
            請先在 .env 中設定對應的 API Key 後再試。
          </Alert>
        )}

        {/* 輸入區域 */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            {mode === "text" ? "訊息內容" : "圖片描述"}
          </label>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            rows={3}
            placeholder={
              mode === "text"
                ? "輸入你想對 AI 說的話…"
                : "描述你想生成的圖片…"
            }
            className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-y focus:outline-none focus:ring-2 focus:ring-blue-500"
            spellCheck={false}
          />
        </div>

        {/* 送出按鈕 */}
        <div className="flex items-center gap-3">
          <button
            onClick={handleSend}
            disabled={!canSend}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-white text-sm font-medium rounded-md transition-colors flex items-center gap-2"
          >
            {mutation.isPending ? (
              <>
                <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                送出中…
              </>
            ) : (
              <>📤 送出請求</>
            )}
          </button>
          <span className="text-xs text-gray-400 dark:text-gray-500">
            {isMac ? "⌘Enter" : "Ctrl+Enter"}
          </span>
        </div>
      </div>

      {/* ── Hint ── */}
      {testCase.hint && (
        <div className="px-4 py-2 text-xs flex items-start gap-2 border-b shrink-0 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400">
          <span className="shrink-0">💡</span>
          <span>{testCase.hint}</span>
        </div>
      )}

      {/* ── 回應區域 ── */}
      <div className="flex-1 overflow-auto p-4 bg-gray-50 dark:bg-gray-950">
        {responseData ? (
          <div className="space-y-3">
            {/* 狀態列 */}
            <div className="flex items-center gap-3">
              <StatusBadge
                status={responseData.status}
                text={responseData.statusText}
              />
              <span className="text-xs text-gray-400">
                {responseData.duration}ms
              </span>
              {parsed.content && <CopyButton text={parsed.content} />}
            </div>

            {/* AI 文字回應 */}
            {parsed.content && (
              <div className="p-4 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800">
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                    🤖 AI 回應
                  </span>
                  {parsed.provider && (
                    <span className="text-xs text-gray-400">
                      {parsed.provider}
                    </span>
                  )}
                  {parsed.model && (
                    <span className="text-xs text-gray-400">
                      • {parsed.model}
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-800 dark:text-gray-200 whitespace-pre-wrap leading-relaxed">
                  {parsed.content}
                </p>
              </div>
            )}

            {/* 圖像回應 */}
            {parsed.images.length > 0 && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <span className="text-xs font-medium text-gray-500 dark:text-gray-400">
                    🎨 生成結果
                  </span>
                  {parsed.provider && (
                    <span className="text-xs text-gray-400">
                      {parsed.provider}
                    </span>
                  )}
                  {parsed.model && (
                    <span className="text-xs text-gray-400">
                      • {parsed.model}
                    </span>
                  )}
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {parsed.images.map((img, i) => (
                    <div
                      key={i}
                      className="rounded-lg overflow-hidden border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900"
                    >
                      <img
                        src={
                          img.url ||
                          `data:image/png;base64,${img.b64_json}`
                        }
                        alt={`生成圖像 ${i + 1}`}
                        className="w-full h-auto"
                      />
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Token 用量 */}
            {parsed.usage && (
              <div className="flex flex-wrap gap-4 text-xs text-gray-400 dark:text-gray-500">
                <span>Prompt: {parsed.usage.prompt_tokens} tokens</span>
                <span>
                  Completion: {parsed.usage.completion_tokens} tokens
                </span>
                <span>Total: {parsed.usage.total_tokens} tokens</span>
              </div>
            )}

            {/* 原始回應 */}
            <details className="text-sm">
              <summary className="cursor-pointer text-gray-500 dark:text-gray-400 font-medium select-none text-xs">
                查看原始回應
              </summary>
              <pre className="mt-2 p-3 bg-white dark:bg-gray-900 rounded-lg border border-gray-200 dark:border-gray-800 text-xs font-mono overflow-x-auto text-gray-700 dark:text-gray-300 max-h-80 overflow-y-auto">
                {JSON.stringify(responseData.body, null, 2)}
              </pre>
            </details>
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-gray-400 dark:text-gray-600 text-sm">
            {mode === "text"
              ? "選擇供應商和模型後，輸入訊息開始對話 💬"
              : "選擇供應商和模型後，輸入描述生成圖片 🎨"}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── 子元件 & 工具 ───────────────────────────────── */

const SELECT_CLS =
  "w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"

type ResponseShape = {
  status: number
  statusText: string
  headers: Record<string, string>
  body: unknown
  duration: number
}

interface ParsedResponse {
  content: string | null
  images: { url?: string; b64_json?: string }[]
  model: string | null
  provider: string | null
  usage: {
    prompt_tokens: number
    completion_tokens: number
    total_tokens: number
  } | null
}

function parseResponse(res: ResponseShape | null): ParsedResponse {
  const empty: ParsedResponse = {
    content: null,
    images: [],
    model: null,
    provider: null,
    usage: null,
  }
  if (!res) return empty
  const body = res.body as Record<string, unknown> | null
  if (!body || typeof body !== "object") return empty
  const data = body.data as Record<string, unknown> | undefined
  if (!data) return empty
  return {
    content: (data.content as string) ?? null,
    images: (data.images as ParsedResponse["images"]) ?? [],
    model: (data.model as string) ?? null,
    provider: (data.provider as string) ?? null,
    usage: (data.usage as ParsedResponse["usage"]) ?? null,
  }
}

function Alert({
  variant,
  children,
}: {
  variant: "amber" | "blue"
  children: React.ReactNode
}) {
  const cls =
    variant === "amber"
      ? "text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20"
      : "text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20"
  return (
    <div className={`text-xs px-3 py-2 rounded ${cls}`}>{children}</div>
  )
}

function StatusBadge({ status, text }: { status: number; text: string }) {
  const cls =
    status >= 200 && status < 300
      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400"
      : status >= 400
        ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
        : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
  return (
    <span className={`px-2 py-0.5 text-xs font-bold rounded ${cls}`}>
      {status} {text}
    </span>
  )
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <button
      onClick={handleCopy}
      className="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
    >
      {copied ? "✅ 已複製" : "📋 複製回應"}
    </button>
  )
}
