import { useEffect, useMemo, useState } from "react"
import { sendBlobRequest } from "../api/client"
import { useAuth } from "../hooks/useAuthStore"

type ViewerVariant = "image" | "origin"

const VARIANT_LABELS: Record<ViewerVariant, string> = {
  image: "圖片檢視",
  origin: "原圖檢視",
}

function normalizeVariant(value: string | null): ViewerVariant | null {
  return value === "image" || value === "origin" ? value : null
}

function assetImageApiPath(assetId: string, variant: ViewerVariant) {
  return `/api/v1/assets/${assetId}/${variant}/`
}

export function ImageViewerPage() {
  const auth = useAuth()
  const params = useMemo(() => new URLSearchParams(window.location.search), [])
  const assetId = params.get("assetId")?.trim() ?? ""
  const variant = normalizeVariant(params.get("variant"))
  const title = params.get("title")?.trim() || (variant ? VARIANT_LABELS[variant] : "圖片檢視")
  const [imageUrl, setImageUrl] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (auth.isRestoring) {
      return
    }

    if (!assetId || !variant) {
      setImageUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current)
        }
        return null
      })
      setError("圖片參數不完整，請回到原頁重新開啟。")
      setLoading(false)
      return
    }

    if (!auth.isAuthenticated) {
      setImageUrl((current) => {
        if (current) {
          URL.revokeObjectURL(current)
        }
        return null
      })
      setError("登入狀態已失效，請回到原頁重新登入後再開啟圖片。")
      setLoading(false)
      return
    }

    let cancelled = false
    let nextObjectUrl: string | null = null

    setLoading(true)
    setError(null)

    void (async () => {
      try {
        const response = await sendBlobRequest({
          method: "GET",
          url: assetImageApiPath(assetId, variant),
        })

        if (cancelled) {
          return
        }

        if (response.status === 401) {
          throw new Error("登入狀態已過期，請回到原頁重新登入後再開啟圖片。")
        }

        if (response.status >= 400) {
          throw new Error("圖片載入失敗，請回到原頁重新開啟。")
        }

        nextObjectUrl = URL.createObjectURL(response.body)
        setImageUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current)
          }
          return nextObjectUrl
        })
      } catch (loadError: unknown) {
        if (cancelled) {
          return
        }

        setImageUrl((current) => {
          if (current) {
            URL.revokeObjectURL(current)
          }
          return null
        })
        setError(loadError instanceof Error ? loadError.message : "圖片載入失敗，請稍後再試。")
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    })()

    return () => {
      cancelled = true
      if (nextObjectUrl) {
        URL.revokeObjectURL(nextObjectUrl)
      }
    }
  }, [assetId, auth.isAuthenticated, auth.isRestoring, variant])

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      <header className="border-gray-800 border-b bg-gray-900 px-4 py-3">
        <h1 className="font-bold text-lg">{title}</h1>
      </header>

      <main className="flex min-h-[calc(100vh-65px)] items-center justify-center p-6">
        <div className="w-full max-w-6xl overflow-hidden rounded-2xl border border-gray-800 bg-gray-900 shadow-sm">
          {loading && (
            <div className="flex min-h-[70vh] items-center justify-center text-gray-400 text-sm">
              載入圖片中…
            </div>
          )}

          {!loading && error && (
            <div className="p-6">
              <div className="rounded-xl border border-red-900/60 bg-red-950/40 p-4 text-red-300 text-sm">
                {error}
              </div>
            </div>
          )}

          {!loading && !error && imageUrl && (
            <div className="flex min-h-[70vh] items-center justify-center bg-slate-950/95 p-4">
              <img
                src={imageUrl}
                alt={title}
                className="max-h-[calc(100vh-10rem)] w-full object-contain"
              />
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
