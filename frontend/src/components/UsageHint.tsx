import type { TestCase } from "../types"

interface UsageHintProps {
  testCase: TestCase
}

/** 根據 testCase 屬性自動產生預設提示 */
function getDefaultHint(testCase: TestCase): string {
  if (testCase.requiresAuth && testCase.pathParams?.length) {
    return "此端點需要認證和路徑參數。"
  }
  if (testCase.requiresAuth) {
    return "此端點需要認證，請先登入。"
  }
  if (
    ["POST", "PUT", "PATCH"].includes(testCase.method) &&
    testCase.body
  ) {
    return "請檢查請求內容後再送出。"
  }
  return "直接送出請求即可。"
}

export function UsageHint({ testCase }: UsageHintProps) {
  const hint = testCase.hint || getDefaultHint(testCase)
  const isWarning = hint.startsWith("⚠️")

  return (
    <div
      className={`px-4 py-2 text-xs flex items-start gap-2 border-b shrink-0 ${
        isWarning
          ? "bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400"
          : "bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800 text-blue-700 dark:text-blue-400"
      }`}
    >
      <span className="shrink-0">{isWarning ? "⚠️" : "💡"}</span>
      <span>{hint}</span>
    </div>
  )
}
