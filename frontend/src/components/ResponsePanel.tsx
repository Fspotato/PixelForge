import { useState } from "react"
import type { ApiResponse } from "../types"

function getStatusColor(status: number): string {
  if (status === 0)
    return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300"
  if (status < 300)
    return "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/50 dark:text-emerald-400"
  if (status < 400)
    return "bg-blue-100 text-blue-800 dark:bg-blue-900/50 dark:text-blue-400"
  if (status < 500)
    return "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-400"
  return "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-400"
}

export function ResponsePanel({
  response,
}: {
  response: ApiResponse | null
}) {
  const [copied, setCopied] = useState(false)

  if (!response) {
    return (
      <div className="flex-1 flex items-center justify-center text-gray-400 dark:text-gray-600 text-sm">
        選擇一個端點並送出請求以查看回應
      </div>
    )
  }

  const bodyStr =
    typeof response.body === "string"
      ? response.body
      : JSON.stringify(response.body, null, 2)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(bodyStr)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      {/* 回應標頭 */}
      <div className="flex items-center justify-between px-4 py-2 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-500 dark:text-gray-400">
            回應
          </span>
          <span
            className={`px-2 py-0.5 text-xs font-bold rounded ${getStatusColor(response.status)}`}
          >
            {response.status} {response.statusText}
          </span>
          <span className="text-xs text-gray-400">{response.duration}ms</span>
        </div>
        <button
          onClick={handleCopy}
          className="text-xs px-2 py-1 rounded hover:bg-gray-100 dark:hover:bg-gray-800 text-gray-500 dark:text-gray-400 transition-colors"
        >
          {copied ? "✅ 已複製" : "📋 複製"}
        </button>
      </div>

      {/* Response Headers（可收合） */}
      {Object.keys(response.headers).length > 0 && (
        <div className="px-4 py-2 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0">
          <details className="text-sm">
            <summary className="cursor-pointer text-gray-500 dark:text-gray-400 font-medium select-none">
              Response Headers ({Object.keys(response.headers).length})
            </summary>
            <pre className="mt-1 p-2 bg-gray-100 dark:bg-gray-800 rounded text-xs font-mono overflow-x-auto text-gray-700 dark:text-gray-300">
              {JSON.stringify(response.headers, null, 2)}
            </pre>
          </details>
        </div>
      )}

      {/* 回應內容 */}
      <pre className="flex-1 p-4 text-sm font-mono overflow-auto bg-gray-50 dark:bg-gray-950 text-gray-800 dark:text-gray-200 whitespace-pre-wrap break-words">
        {bodyStr}
      </pre>
    </div>
  )
}
