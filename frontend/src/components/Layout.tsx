import type { ReactNode } from "react"
import { ThemeToggle } from "./ThemeToggle"
import { useAuth } from "../hooks/useAuthStore"

export function Layout({ children }: { children: ReactNode }) {
  const auth = useAuth()

  return (
    <div className="h-screen flex flex-col bg-gray-50 dark:bg-gray-950">
      {/* 頂部導覽列 */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 shrink-0">
        <h1 className="text-lg font-bold flex items-center gap-2">
          🔧 <span>API 測試面板</span>
        </h1>
        <div className="flex items-center gap-3">
          {auth.isAuthenticated && (
            <span className="text-xs text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-900/30 px-2 py-1 rounded-full">
              ✅ 已登入
            </span>
          )}
          <ThemeToggle />
        </div>
      </header>

      {/* 主要內容區 */}
      <div className="flex-1 flex overflow-hidden">{children}</div>
    </div>
  )
}
