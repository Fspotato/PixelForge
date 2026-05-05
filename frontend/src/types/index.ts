export type HttpMethod = "GET" | "POST" | "PATCH" | "PUT" | "DELETE"

/** 單一測試案例的變體設定，可透過下拉選單切換 */
export interface TestCaseVariant {
  id: string
  label: string
  description?: string
  hint?: string
  method?: HttpMethod
  path?: string
  headers?: Record<string, string>
  body?: unknown
  pathParams?: { key: string; label: string; placeholder: string }[]
  requiredPermission?: string
}

/** 單一測試案例定義 */
export interface TestCase {
  id: string
  category: string
  name: string
  method: HttpMethod
  path: string
  description: string
  headers?: Record<string, string>
  body?: unknown
  requiresAuth: boolean
  oauthProvider?: "google"
  pathParams?: { key: string; label: string; placeholder: string }[]
  /** 使用提示：說明如何使用此測試案例、前置步驟、注意事項等 */
  hint?: string
  /** 所需權限：如 "管理員權限"，不標註表示僅需登入或公開 */
  requiredPermission?: string
  /** 收到回應後，若此欄位有值，自動跳轉到該欄位的 URL（例如 "checkout_url"） */
  autoRedirect?: string
  /** 同一端點的多種測試情境，可由 UI 下拉選單切換 */
  variants?: TestCaseVariant[]
}

/** API 回應包裝 */
export interface ApiResponse {
  status: number
  statusText: string
  headers: Record<string, string>
  body: unknown
  duration: number
}

/** 二進位 API 回應包裝 */
export interface BlobApiResponse {
  status: number
  statusText: string
  headers: Record<string, string>
  body: Blob
  duration: number
}

/** sendRequest 的請求參數 */
export interface RequestConfig {
  method: HttpMethod
  url: string
  headers?: Record<string, string>
  body?: string
}
