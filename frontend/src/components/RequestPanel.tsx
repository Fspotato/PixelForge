import { useState, useCallback, useEffect, useMemo } from "react"
import { useMutation } from "@tanstack/react-query"
import { useAuth } from "../hooks/useAuthStore"
import { sendRequest } from "../api/client"
import { SocialLoginPanel } from "./SocialLoginPanel"
import type { TestCase, TestCaseVariant, ApiResponse, HttpMethod } from "../types"

const METHOD_BADGE: Record<HttpMethod, string> = {
  GET: "bg-emerald-500",
  POST: "bg-blue-500",
  PATCH: "bg-amber-500",
  PUT: "bg-yellow-500",
  DELETE: "bg-red-500",
}

interface RequestPanelProps {
  testCase: TestCase
  onResponse: (res: ApiResponse) => void
}

/** 將預設 request body 格式化成可編輯 JSON。 */
function substituteBody(body: unknown): string {
  if (!body) return ""
  return JSON.stringify(body, null, 2)
}

function initializePathParams(
  pathParams: TestCaseVariant["pathParams"],
  lastTaskId: string | null,
): Record<string, string> {
  const params: Record<string, string> = {}
  pathParams?.forEach((p) => {
    if (p.key === "task_id" && lastTaskId) {
      params[p.key] = lastTaskId
    } else {
      params[p.key] = ""
    }
  })
  return params
}

export function RequestPanel({ testCase, onResponse }: RequestPanelProps) {
  const auth = useAuth()
  const initialVariantId = testCase.variants?.[0]?.id ?? null
  const [selectedVariantId, setSelectedVariantId] = useState(initialVariantId)

  const selectedVariant = useMemo(() => {
    if (!testCase.variants?.length || !selectedVariantId) {
      return null
    }
    return (
      testCase.variants.find((variant) => variant.id === selectedVariantId) ||
      testCase.variants[0]
    )
  }, [selectedVariantId, testCase.variants])

  const effectiveMethod = selectedVariant?.method ?? testCase.method
  const effectivePath = selectedVariant?.path ?? testCase.path
  const effectiveHeaders = selectedVariant?.headers ?? testCase.headers
  const effectiveBody = selectedVariant?.body ?? testCase.body
  const effectivePathParams = selectedVariant?.pathParams ?? testCase.pathParams
  const effectiveDescription = selectedVariant?.description ?? testCase.description
  const effectiveRequiredPermission =
    selectedVariant?.requiredPermission ?? testCase.requiredPermission

  // 若 variant 與 parent 各有不同 hint，合併為多行顯示
  const effectiveHints = useMemo((): string[] => {
    const variantHint = selectedVariant?.hint
    const parentHint = testCase.hint
    if (variantHint && parentHint && variantHint !== parentHint) {
      return [variantHint, parentHint]
    }
    const single = variantHint ?? parentHint
    return single ? [single] : []
  }, [selectedVariant?.hint, testCase.hint])

  const [bodyText, setBodyText] = useState(() => substituteBody(effectiveBody))

  const [pathParams, setPathParams] = useState<Record<string, string>>(() =>
    initializePathParams(effectivePathParams, auth.lastTaskId),
  )

  useEffect(() => {
    setBodyText(substituteBody(effectiveBody))
    setPathParams(initializePathParams(effectivePathParams, auth.lastTaskId))
  }, [effectiveBody, effectivePathParams, auth.lastTaskId, selectedVariantId, testCase.id])

  const buildUrl = useCallback(() => {
    let url = effectivePath
    effectivePathParams?.forEach((p) => {
      const value = pathParams[p.key]
      if (value) {
        url = url.replace(`{${p.key}}`, value)
      }
    })
    return url
  }, [effectivePath, effectivePathParams, pathParams])

  const buildHeaders = useCallback(() => {
    return {
      "Content-Type": "application/json",
      ...effectiveHeaders,
    }
  }, [effectiveHeaders])

  const mutation = useMutation({
    mutationFn: sendRequest,
    onSuccess: (response) => {
      auth.captureFromResponse(response.body)
      if (effectivePath === "/api/v1/auth/logout/" && response.status < 400) {
        auth.clearAuth()
      }
      onResponse(response)
      // 若 testCase 設定了 autoRedirect，收到成功回應後自動跳轉至指定欄位的 URL
      if (testCase.autoRedirect) {
        const responseData = (response.body as Record<string, unknown>)?.data
        const redirectUrl =
          typeof responseData === "object" && responseData !== null
            ? (responseData as Record<string, unknown>)[testCase.autoRedirect]
            : undefined
        if (typeof redirectUrl === "string") {
          window.location.href = redirectUrl
        }
      }
    },
    onError: (error) => {
      onResponse({
        status: 0,
        statusText: "網路錯誤",
        headers: {},
        body: { error: String(error) },
        duration: 0,
      })
    },
  })

  const handleSend = () => {
    mutation.mutate({
      method: effectiveMethod,
      url: buildUrl(),
      headers: buildHeaders(),
      body: bodyText || undefined,
    })
  }

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault()
        if (!mutation.isPending) handleSend()
      }
    }
    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  })

  const isMac =
    typeof navigator !== "undefined" &&
    /Mac|iPhone|iPad/.test(navigator.platform)

  const jsonError = useMemo(() => {
    if (!bodyText.trim()) return false
    try {
      JSON.parse(bodyText)
      return false
    } catch {
      return true
    }
  }, [bodyText])

  const headers = buildHeaders()

  return (
    <div className="p-4 border-b border-gray-200 dark:border-gray-800 space-y-4 overflow-y-auto shrink-0 bg-white dark:bg-gray-900">
      <div className="flex items-center gap-2">
        <span
          className={`px-2.5 py-1 text-xs font-bold text-white rounded ${METHOD_BADGE[effectiveMethod]}`}
        >
          {effectiveMethod}
        </span>
        <code className="flex-1 text-sm font-mono text-gray-800 dark:text-gray-200 bg-gray-100 dark:bg-gray-800 px-3 py-1.5 rounded overflow-x-auto">
          {buildUrl()}
        </code>
      </div>

      <p className="text-sm text-gray-500 dark:text-gray-400">
        {effectiveDescription}
      </p>

      {testCase.variants && testCase.variants.length > 0 && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            測試情境
          </label>
          <select
            value={selectedVariant?.id ?? ""}
            onChange={(e) => setSelectedVariantId(e.target.value)}
            className="w-full px-3 py-2 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-blue-500"
          >
            {testCase.variants.map((variant) => (
              <option key={variant.id} value={variant.id}>
                {variant.label}
              </option>
            ))}
          </select>
        </div>
      )}

      {effectiveRequiredPermission && (
        <span className="inline-flex items-center gap-1 px-2 py-0.5 text-xs font-medium rounded-full bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400">
          🛡️ {effectiveRequiredPermission}
        </span>
      )}

      {testCase.requiresAuth && !auth.isAuthenticated && (
        <div className="text-xs text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 px-3 py-2 rounded">
          ⚠️ 此端點需要認證。請先建立登入 cookie session。
        </div>
      )}

      <details className="text-sm">
        <summary className="cursor-pointer text-gray-500 dark:text-gray-400 font-medium select-none">
          Headers ({Object.keys(headers).length})
        </summary>
        <pre className="mt-1 p-2 bg-gray-100 dark:bg-gray-800 rounded text-xs font-mono overflow-x-auto text-gray-700 dark:text-gray-300">
          {JSON.stringify(headers, null, 2)}
        </pre>
      </details>

      {effectivePathParams && effectivePathParams.length > 0 && (
        <div className="space-y-2">
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300">
            路徑參數
          </label>
          {effectivePathParams.map((p) => (
            <div key={p.key} className="flex items-center gap-2">
              <span className="text-xs font-mono text-gray-500 dark:text-gray-400 w-20 shrink-0">
                {p.key}
              </span>
              <input
                type="text"
                value={pathParams[p.key] || ""}
                onChange={(e) =>
                  setPathParams((prev) => ({
                    ...prev,
                    [p.key]: e.target.value,
                  }))
                }
                placeholder={p.placeholder}
                className="flex-1 px-2 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          ))}
        </div>
      )}

      {effectiveMethod !== "GET" && (
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            請求內容
          </label>
          <textarea
            value={bodyText}
            onChange={(e) => setBodyText(e.target.value)}
            rows={Math.max(3, bodyText.split("\n").length)}
            className={`w-full px-3 py-2 text-sm font-mono border rounded-md bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-y focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              jsonError
                ? "border-red-400 dark:border-red-500"
                : "border-gray-300 dark:border-gray-600"
            }`}
            spellCheck={false}
          />
          {jsonError && (
            <p className="mt-1 text-xs text-red-500 dark:text-red-400">
              JSON 格式錯誤
            </p>
          )}
        </div>
      )}

      {testCase.oauthProvider ? (
        <SocialLoginPanel provider={testCase.oauthProvider} />
      ) : (
        <div className="flex items-center gap-3">
          <button
            onClick={handleSend}
            disabled={mutation.isPending}
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
      )}

      {effectiveHints.length > 0 && (
        <div className="text-xs text-blue-700 dark:text-blue-400 bg-blue-50 dark:bg-blue-900/20 px-3 py-2 rounded border border-blue-200 dark:border-blue-800 space-y-1">
          {effectiveHints.map((h, i) => (
            <div key={i}>💡 {h}</div>
          ))}
        </div>
      )}
    </div>
  )
}
