import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  type ReactNode,
} from "react"
import { AUTH_CLEARED_EVENT, sendRequest } from "../api/client"

interface AuthState {
  user: AuthUser | null
  lastTaskId: string | null
  isRestoring: boolean
}

interface AuthUser {
  id: string
  email: string
  [key: string]: unknown
}

interface AuthContextValue extends AuthState {
  isAuthenticated: boolean
  clearAuth: () => void
  logout: () => Promise<void>
  restoreAuth: () => Promise<void>
  setLastTaskId: (id: string) => void
  /** 從 API 回應中自動擷取並儲存使用者快照 / task_id */
  captureFromResponse: (body: unknown) => void
}

const AuthContext = createContext<AuthContextValue>(null!)

const STORAGE_KEY_USER = "auth_user_snapshot"

function isAuthUser(value: unknown): value is AuthUser {
  return !!value && typeof value === "object" && "id" in value && "email" in value
}

function loadStoredUser(): AuthUser | null {
  const rawValue = localStorage.getItem(STORAGE_KEY_USER)
  if (!rawValue) {
    return null
  }

  try {
    const parsed = JSON.parse(rawValue) as unknown
    return isAuthUser(parsed) ? parsed : null
  } catch {
    localStorage.removeItem(STORAGE_KEY_USER)
    return null
  }
}

function persistUser(user: AuthUser | null) {
  if (user) {
    localStorage.setItem(STORAGE_KEY_USER, JSON.stringify(user))
    return
  }
  localStorage.removeItem(STORAGE_KEY_USER)
}

function extractUserFromBody(body: unknown): AuthUser | null {
  if (!body || typeof body !== "object") {
    return null
  }

  const payload = body as Record<string, unknown>
  const data = payload.data
  if (!data || typeof data !== "object") {
    return null
  }

  const record = data as Record<string, unknown>
  if (isAuthUser(record.user)) {
    return record.user
  }
  return isAuthUser(record) ? record : null
}

/** 認證 Provider — 管理 cookie session 與動態測試值 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: loadStoredUser(),
    lastTaskId: null,
    isRestoring: true,
  })

  const clearAuth = useCallback(() => {
    persistUser(null)
    setState((s) => ({ ...s, user: null, isRestoring: false }))
  }, [])

  const setLastTaskId = useCallback((id: string) => {
    setState((s) => ({ ...s, lastTaskId: id }))
  }, [])

  const restoreAuth = useCallback(async () => {
    setState((s) => ({ ...s, isRestoring: true }))

    try {
      const response = await sendRequest({
        method: "GET",
        url: "/api/v1/accounts/me/",
      })
      const user = extractUserFromBody(response.body)

      if (response.status < 400 && user) {
        persistUser(user)
        setState((s) => ({ ...s, user, isRestoring: false }))
        return
      }
    } catch {
      // 保持靜默，改由下方統一清理狀態
    }

    persistUser(null)
    setState((s) => ({ ...s, user: null, isRestoring: false }))
  }, [])

  useEffect(() => {
    void restoreAuth()
  }, [restoreAuth])

  useEffect(() => {
    const handleAuthCleared = () => {
      clearAuth()
    }

    window.addEventListener(AUTH_CLEARED_EVENT, handleAuthCleared)
    return () => {
      window.removeEventListener(AUTH_CLEARED_EVENT, handleAuthCleared)
    }
  }, [clearAuth])

  const captureFromResponse = useCallback((body: unknown) => {
    const user = extractUserFromBody(body)
    if (user) {
      persistUser(user)
      setState((s) => ({ ...s, user }))
    }

    if (!body || typeof body !== "object") return
    const b = body as Record<string, unknown>
    if (typeof b.task_id === "string") {
      setState((s) => ({ ...s, lastTaskId: b.task_id as string }))
    }
  }, [])

  const logout = useCallback(async () => {
    try {
      await sendRequest({
        method: "POST",
        url: "/api/v1/auth/logout/",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      })
    } finally {
      clearAuth()
    }
  }, [clearAuth])

  const value: AuthContextValue = {
    ...state,
    isAuthenticated: !!state.user,
    clearAuth,
    logout,
    restoreAuth,
    setLastTaskId,
    captureFromResponse,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
