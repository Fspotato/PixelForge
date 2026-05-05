import type { RequestConfig, ApiResponse, BlobApiResponse } from "../types"

const CSRF_COOKIE_NAME = "csrftoken"
const CSRF_HEADER_NAME = "X-CSRFToken"
const CSRF_ENDPOINT = "/api/v1/system/csrf/"
const REFRESH_ENDPOINT = "/api/v1/auth/refresh/"
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS", "TRACE"])
export const AUTH_CLEARED_EVENT = "pixelforge:auth-cleared"

let refreshRequest: Promise<boolean> | null = null

function getCookie(name: string): string | null {
  const cookies = document.cookie ? document.cookie.split("; ") : []

  for (const cookie of cookies) {
    const [key, ...valueParts] = cookie.split("=")
    if (key === name) {
      return decodeURIComponent(valueParts.join("="))
    }
  }

  return null
}

async function ensureCsrfToken(): Promise<string> {
  const existingToken = getCookie(CSRF_COOKIE_NAME)
  if (existingToken) {
    return existingToken
  }

  const response = await fetch(CSRF_ENDPOINT, {
    method: "GET",
    credentials: "include",
  })

  if (!response.ok) {
    throw new Error("無法初始化 CSRF Token")
  }

  const token =
    getCookie(CSRF_COOKIE_NAME) ||
    ((await response.json()) as { csrf_token?: string }).csrf_token

  if (!token) {
    throw new Error("後端未提供 CSRF Token")
  }

  return token
}

async function readResponseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") || ""
  if (contentType.includes("application/json")) {
    return response.json()
  }
  return response.text()
}

function readResponseHeaders(response: Response): Record<string, string> {
  const responseHeaders: Record<string, string> = {}
  response.headers.forEach((value, key) => {
    responseHeaders[key] = value
  })
  return responseHeaders
}

async function performFetch(config: RequestConfig): Promise<{ response: Response; duration: number }> {
  const startTime = performance.now()
  const requestHeaders = new Headers(config.headers)
  const needsCsrf = !SAFE_METHODS.has(config.method)

  if (needsCsrf && !requestHeaders.has(CSRF_HEADER_NAME)) {
    requestHeaders.set(CSRF_HEADER_NAME, await ensureCsrfToken())
  }

  const init: RequestInit = {
    method: config.method,
    headers: requestHeaders,
    credentials: "include",
  }

  if (config.body && config.method !== "GET") {
    init.body = config.body
  }

  const response = await fetch(config.url, init)
  return {
    response,
    duration: Math.round(performance.now() - startTime),
  }
}

async function performRequest(config: RequestConfig): Promise<ApiResponse> {
  const { response, duration } = await performFetch(config)

  return {
    status: response.status,
    statusText: response.statusText,
    headers: readResponseHeaders(response),
    body: await readResponseBody(response),
    duration,
  }
}

async function performBlobRequest(config: RequestConfig): Promise<BlobApiResponse> {
  const { response, duration } = await performFetch(config)

  return {
    status: response.status,
    statusText: response.statusText,
    headers: readResponseHeaders(response),
    body: await response.blob(),
    duration,
  }
}

function shouldAttemptRefresh(url: string): boolean {
  return !url.startsWith("/api/v1/auth/")
}

async function refreshAuthSession(): Promise<boolean> {
  if (refreshRequest) {
    return refreshRequest
  }

  refreshRequest = (async () => {
    const csrfToken = await ensureCsrfToken()
    const response = await fetch(REFRESH_ENDPOINT, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
        [CSRF_HEADER_NAME]: csrfToken,
      },
      body: "{}",
    })
    return response.ok
  })()

  try {
    return await refreshRequest
  } finally {
    refreshRequest = null
  }
}

async function withRefreshRetry<T extends { status: number }>(
  config: RequestConfig,
  execute: (config: RequestConfig) => Promise<T>,
): Promise<T> {
  const response = await execute(config)

  if (response.status !== 401 || !shouldAttemptRefresh(config.url)) {
    return response
  }

  let refreshed = false
  try {
    refreshed = await refreshAuthSession()
  } catch {
    window.dispatchEvent(new CustomEvent(AUTH_CLEARED_EVENT))
    return response
  }

  if (!refreshed) {
    window.dispatchEvent(new CustomEvent(AUTH_CLEARED_EVENT))
    return response
  }

  const retriedResponse = await execute(config)
  if (retriedResponse.status === 401) {
    window.dispatchEvent(new CustomEvent(AUTH_CLEARED_EVENT))
  }
  return retriedResponse
}

/**
 * 發送 HTTP 請求並回傳包含計時的回應。
 * 用於 API 測試面板的底層請求函式。
 */
export async function sendRequest(config: RequestConfig): Promise<ApiResponse> {
  return withRefreshRetry(config, performRequest)
}

/** 取得需要認證的二進位內容，並沿用同樣的自動續期邏輯。 */
export async function sendBlobRequest(config: RequestConfig): Promise<BlobApiResponse> {
  return withRefreshRetry(config, performBlobRequest)
}
