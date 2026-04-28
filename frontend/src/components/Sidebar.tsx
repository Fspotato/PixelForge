import { useState } from "react"
import { useAuth } from "../hooks/useAuthStore"
import type { TestCase, HttpMethod } from "../types"

const METHOD_COLORS: Record<HttpMethod, string> = {
  GET: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400",
  POST: "bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-400",
  PATCH: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-400",
  PUT: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-400",
  DELETE: "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-400",
}

interface SidebarProps {
  testCases: TestCase[]
  selectedId: string
  onSelect: (tc: TestCase) => void
}

export function Sidebar({ testCases, selectedId, onSelect }: SidebarProps) {
  const auth = useAuth()
  const [search, setSearch] = useState("")

  // 搜尋過濾
  const filtered = search.trim()
    ? testCases.filter((tc) => {
        const q = search.toLowerCase()
        return (
          tc.name.toLowerCase().includes(q) ||
          tc.path.toLowerCase().includes(q) ||
          tc.description.toLowerCase().includes(q)
        )
      })
    : testCases

  // 依分類分組
  const groups = filtered.reduce<Record<string, TestCase[]>>((acc, tc) => {
    if (!acc[tc.category]) acc[tc.category] = []
    acc[tc.category].push(tc)
    return acc
  }, {})

  return (
    <aside className="w-64 shrink-0 border-r border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 flex flex-col overflow-hidden">
      {/* 認證狀態 */}
      <div className="p-3 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500 dark:text-gray-400">認證狀態</span>
          {auth.isAuthenticated ? (
            <span className="text-emerald-600 dark:text-emerald-400 text-xs">
              ✅ 已登入
            </span>
          ) : (
            <span className="text-gray-400 dark:text-gray-500 text-xs">
              未登入
            </span>
          )}
        </div>
        {auth.isAuthenticated && (
          <button
            onClick={() => {
              void auth.logout()
            }}
            className="mt-2 w-full text-xs px-2 py-1 rounded bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 text-gray-600 dark:text-gray-400 transition-colors"
          >
            登出並清除狀態
          </button>
        )}
      </div>

      {/* 搜尋框 */}
      <div className="px-3 py-2 border-b border-gray-200 dark:border-gray-800 shrink-0">
        <div className="relative">
          <span className="absolute left-2 top-1/2 -translate-y-1/2 text-gray-400 text-xs">
            🔍
          </span>
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜尋端點..."
            className="w-full pl-7 pr-2 py-1.5 text-xs border border-gray-300 dark:border-gray-600 rounded bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>

      {/* 端點列表 */}
      <nav className="flex-1 overflow-y-auto p-2">
        {search.trim() && Object.keys(groups).length === 0 && (
          <p className="px-2 py-4 text-xs text-center text-gray-400 dark:text-gray-500">
            無符合的端點
          </p>
        )}
        {Object.entries(groups).map(([category, cases]) => (
          <div key={category} className="mb-4">
            <h3 className="px-2 py-1 text-xs font-semibold text-gray-400 dark:text-gray-500 uppercase tracking-wider">
              {category}
            </h3>
            {cases.map((tc) => (
              <button
                key={tc.id}
                onClick={() => onSelect(tc)}
                className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-sm text-left transition-colors ${
                  selectedId === tc.id
                    ? "bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300"
                    : "hover:bg-gray-50 dark:hover:bg-gray-800 text-gray-700 dark:text-gray-300"
                }`}
              >
                <span
                  className={`inline-flex items-center justify-center min-w-[3rem] px-1.5 py-0.5 text-[10px] font-bold rounded ${METHOD_COLORS[tc.method]}`}
                >
                  {tc.method}
                </span>
                <span className="truncate">{tc.name}</span>
                {tc.requiresAuth && (
                  <span
                    className="ml-auto text-[10px] text-gray-400 shrink-0"
                    title="需要認證"
                  >
                    🔒
                  </span>
                )}
              </button>
            ))}
          </div>
        ))}
      </nav>
    </aside>
  )
}
