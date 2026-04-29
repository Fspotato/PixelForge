import { useEffect, useState } from "react"
import { ThemeProvider } from "./hooks/useTheme"
import { AuthProvider, useAuth } from "./hooks/useAuthStore"
import { Layout } from "./components/Layout"
import { Sidebar } from "./components/Sidebar"
import { RequestPanel } from "./components/RequestPanel"
import { ResponsePanel } from "./components/ResponsePanel"
import { AiTestPanel } from "./components/AiTestPanel"
import { OrderSyncPanel } from "./components/OrderSyncPanel"
import { SubscriptionSyncPanel } from "./components/SubscriptionSyncPanel"
import { CatalogActionPanel } from "./components/CatalogActionPanel"
import { EntityBrowserPanel } from "./components/EntityBrowserPanel"
import { PaymentResultPage } from "./components/PaymentResultPage"
import { testCases } from "./data/testCases"
import type { ApiResponse } from "./types"
import { sendRequest } from "./api/client"

const ENABLE_API_TESTER =
  import.meta.env.DEV && import.meta.env.VITE_ENABLE_API_TESTER === "true"

/** AI 互動式測試面板的 test case ID */
const AI_INTERACTIVE_IDS = new Set(["ai-chat", "ai-image"])
/** 訂單同步面板的 test case ID */
const ORDER_SYNC_IDS = new Set(["payments-sync-orders"])
/** 訂閱同步面板的 test case ID */
const SUBSCRIPTION_SYNC_IDS = new Set(["subscriptions-sync-all"])
/** 結帳建立面板的 test case ID */
const CHECKOUT_PANEL_IDS = new Set(["payments-checkout"])
/** 訂閱建立面板的 test case ID */
const SUBSCRIPTION_CREATE_IDS = new Set(["subscriptions-create"])
/** 訂單列表面板的 test case ID */
const ORDER_BROWSER_IDS = new Set(["payments-order-list"])
/** 訂閱列表面板的 test case ID */
const SUBSCRIPTION_BROWSER_IDS = new Set(["subscriptions-list"])

function ApiTesterApp() {
  const [selectedId, setSelectedId] = useState(testCases[0].id)
  const [response, setResponse] = useState<ApiResponse | null>(null)

  const selectedCase =
    testCases.find((tc) => tc.id === selectedId) || testCases[0]

  const isAiInteractive = AI_INTERACTIVE_IDS.has(selectedCase.id)
  const isOrderSync = ORDER_SYNC_IDS.has(selectedCase.id)
  const isSubscriptionSync = SUBSCRIPTION_SYNC_IDS.has(selectedCase.id)
  const isCheckoutPanel = CHECKOUT_PANEL_IDS.has(selectedCase.id)
  const isSubscriptionCreatePanel = SUBSCRIPTION_CREATE_IDS.has(selectedCase.id)
  const isOrderBrowser = ORDER_BROWSER_IDS.has(selectedCase.id)
  const isSubscriptionBrowser = SUBSCRIPTION_BROWSER_IDS.has(selectedCase.id)

  return (
    <ThemeProvider>
      <AuthProvider>
        <Layout>
          <Sidebar
            testCases={testCases}
            selectedId={selectedId}
            onSelect={(tc) => {
              setSelectedId(tc.id)
              setResponse(null)
            }}
          />
          <main className="flex-1 flex flex-col overflow-hidden">
            {isAiInteractive ? (
              /* AI 文字聊天 / 圖像生成 — 使用專屬互動面板 */
              <AiTestPanel key={selectedCase.id} testCase={selectedCase} />
            ) : isOrderSync ? (
              /* 訂單狀態同步 — 使用專屬面板 */
              <OrderSyncPanel key={selectedCase.id} />
            ) : isSubscriptionSync ? (
              /* 訂閱狀態同步 — 使用專屬面板 */
              <SubscriptionSyncPanel key={selectedCase.id} />
            ) : isCheckoutPanel ? (
              /* 商品化結帳建立 — 使用專屬面板 */
              <CatalogActionPanel key={selectedCase.id} mode="checkout" />
            ) : isSubscriptionCreatePanel ? (
              /* 商品化訂閱建立 — 使用專屬面板 */
              <CatalogActionPanel key={selectedCase.id} mode="subscription" />
            ) : isOrderBrowser ? (
              /* 訂單列表瀏覽 — 自動載入與點選詳情 */
              <EntityBrowserPanel key={selectedCase.id} resource="orders" />
            ) : isSubscriptionBrowser ? (
              /* 訂閱列表瀏覽 — 自動載入與點選詳情 */
              <EntityBrowserPanel key={selectedCase.id} resource="subscriptions" />
            ) : (
              <>
                {/* key 確保切換測試案例時重新掛載，觸發自適應填入 */}
                <RequestPanel
                  key={selectedCase.id}
                  testCase={selectedCase}
                  onResponse={setResponse}
                />
                <ResponsePanel response={response} />
              </>
            )}
          </main>
        </Layout>
      </AuthProvider>
    </ThemeProvider>
  )
}

interface StylePreset {
  key: string
  name: string
  description: string
  resolution: string
  palette_hex: string[]
  model_params?: {
    palette_key?: string
  }
}

interface GenerationJob {
  id: string
  status: string
  subject: string
  percent: number
  preset_key: string
  error?: string
  result_asset_id?: string | null
}

interface Asset {
  id: string
  subject: string
  preset_key: string
  status: string
  thumbnail_url: string
  image_url: string
}

const PROCESSOR_DEFS: Record<string, { label: string; description: string }> = {
  bg_remover: { label: "背景移除", description: "主體分離優先，清除 AI 生圖背景與亮色邊緣" },
  alpha_trimmer: { label: "透明裁切", description: "裁切透明邊界並保留 padding" },
  perfect_pixel: { label: "像素修正", description: "重取樣、硬化 alpha、清理離群像素" },
  palette_mapper: { label: "模板色盤", description: "強制映射到所選風格色盤" },
  color_quantizer: { label: "自動量化", description: "自動降低色數並保留高光" },
  upscaler: { label: "像素放大", description: "以最近鄰插值輸出展示圖" },
}

const DEFAULT_PROCESSORS = ["bg_remover", "alpha_trimmer", "perfect_pixel", "palette_mapper"]
const COLOR_COUNTS = [8, 16, 32]
const UPSCALE_FACTORS = [5, 10, 20]
const SAMPLE_METHODS = ["adaptive", "center", "majority", "median"]
const PIXEL_TARGETS = [
  { label: "不壓縮", value: "none" },
  { label: "16x16", value: 16 },
  { label: "32x32", value: 32 },
  { label: "64x64", value: 64 },
  { label: "128x128", value: 128 },
]
const BG_REMOVER_METHODS = [
  { label: "品紅去背", value: "magenta" },
  { label: "主體分離", value: "subject" },
  { label: "邊界填充", value: "flood_fill" },
  { label: "白底閾值", value: "threshold" },
]
const HIDDEN_JOB_STATUSES = new Set(["ARCHIVED", "DISMISSED"])

const JOB_STATUS_LABELS: Record<string, string> = {
  QUEUED: "已排隊",
  PLANNING: "提示詞規劃中",
  GENERATING: "圖像生成中",
  PROCESSING: "候選評估與後處理",
  ARCHIVED: "已完成",
  FAILED: "失敗",
  DISMISSED: "已移除",
}

const JOB_STAGE_DESCRIPTIONS: Record<string, string> = {
  QUEUED: "任務已建立，等待背景 worker 接手。",
  PLANNING: "LLM 正在把主題轉成精簡 PromptPlan；這一步現在會顯示在進度中。",
  GENERATING: "正在多次呼叫圖像模型產生候選圖。",
  PROCESSING: "正在後處理、評估候選圖並挑選最佳結果。",
  FAILED: "任務失敗，可移除顯示後重新提交或調整設定。",
}

function visibleJobs(jobs: GenerationJob[]) {
  return jobs.filter((job) => !HIDDEN_JOB_STATUSES.has(job.status))
}

function PixelForgeHome() {
  const auth = useAuth()
  const [presets, setPresets] = useState<StylePreset[]>([])
  const [jobs, setJobs] = useState<GenerationJob[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [loginEmail, setLoginEmail] = useState("")
  const [loginPassword, setLoginPassword] = useState("")
  const [subject, setSubject] = useState("magic forest potion")
  const [preset, setPreset] = useState("forest")
  const [view, setView] = useState("top-down")
  const [mode, setMode] = useState("single")
  const [processors, setProcessors] = useState(DEFAULT_PROCESSORS)
  const [draggedProcessor, setDraggedProcessor] = useState<string | null>(null)
  const [showPaletteDetails, setShowPaletteDetails] = useState(false)
  const [processorConfig, setProcessorConfig] = useState<Record<string, Record<string, unknown>>>({
    bg_remover: { method: "magenta", threshold: 100, edge_threshold: 150, tolerance: 18, edge_cleanup: true },
    perfect_pixel: { target_size: "none", sample_method: "adaptive", remove_outliers: true },
    palette_mapper: { dither: true, dither_strength: 0.55 },
    color_quantizer: { n_colors: 16 },
    upscaler: { scale: 5 },
  })
  const [message, setMessage] = useState("")

  async function requestJson<T>(method: "GET" | "POST" | "DELETE", url: string, body?: unknown): Promise<T | null> {
    const response = await sendRequest({
      method,
      url,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (response.status >= 400) {
      setMessage(`請求失敗 (${response.status})`)
      return null
    }
    const payload = response.body as { data?: T; message?: string }
    if (payload.message) setMessage(payload.message)
    return payload.data ?? null
  }

  async function loadData() {
    const presetData = await requestJson<StylePreset[]>("GET", "/api/v1/style-presets/")
    const jobData = await requestJson<GenerationJob[]>("GET", "/api/v1/generation-jobs/")
    const assetData = await requestJson<Asset[]>("GET", "/api/v1/assets/")
    if (presetData) {
      setPresets(presetData)
      if (!presetData.some((item) => item.key === preset) && presetData[0]) {
        setPreset(presetData[0].key)
      }
    }
    if (jobData) setJobs(visibleJobs(jobData))
    if (assetData) setAssets(assetData)
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return
    void loadData()
    const timer = window.setInterval(() => void loadData(), 3000)
    return () => window.clearInterval(timer)
  }, [auth.isAuthenticated])

  useEffect(() => {
    setShowPaletteDetails(false)
  }, [preset])

  async function createGenerationJob() {
    setMessage("正在建立任務...")
    const data = await requestJson<GenerationJob>("POST", "/api/v1/generation-jobs/", {
      subject,
      preset,
      view,
      mode,
      processors,
      processor_config: processorConfig,
    })
    if (data) {
      setJobs((current) => visibleJobs([data, ...current]))
    }
  }

  async function dismissFailedJob(jobId: string) {
    const data = await requestJson<GenerationJob>("DELETE", `/api/v1/generation-jobs/${jobId}/`)
    if (data?.status === "DISMISSED" || data?.status === "FAILED") {
      setJobs((current) => current.filter((job) => job.id !== jobId))
    }
  }

  async function retryAsset(assetId: string) {
    await requestJson<{ job_id: string }>("POST", `/api/v1/assets/${assetId}/retry/`, {})
    await loadData()
  }

  async function deleteAsset(assetId: string) {
    await requestJson("DELETE", `/api/v1/assets/${assetId}/`)
    setAssets((current) => current.filter((asset) => asset.id !== assetId))
  }

  function toggleProcessor(name: string) {
    setProcessors((current) =>
      current.includes(name)
        ? current.filter((item) => item !== name)
        : [...current, name],
    )
  }

  function reorderProcessor(source: string, target: string) {
    if (source === target) return
    setProcessors((current) => {
      const sourceIndex = current.indexOf(source)
      const targetIndex = current.indexOf(target)
      if (sourceIndex < 0 || targetIndex < 0) return current
      const next = [...current]
      const [item] = next.splice(sourceIndex, 1)
      next.splice(targetIndex, 0, item)
      return next
    })
  }

  function updateProcessorConfig(name: string, patch: Record<string, unknown>) {
    setProcessorConfig((current) => ({
      ...current,
      [name]: { ...(current[name] || {}), ...patch },
    }))
  }

  const selectedPreset = presets.find((item) => item.key === preset)
  const selectedPalette = selectedPreset?.palette_hex ?? []
  const selectedPaletteKey = selectedPreset?.model_params?.palette_key ?? selectedPreset?.key ?? ""

  async function login() {
    setMessage("")
    const response = await sendRequest({
      method: "POST",
      url: "/api/v1/auth/login/",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: loginEmail, password: loginPassword }),
    })
    if (response.status >= 400) {
      setMessage(`登入失敗 (${response.status})`)
      return
    }
    auth.captureFromResponse(response.body)
    await auth.restoreAuth()
    setMessage("登入成功")
  }

  if (auth.isRestoring) {
    return <div className="min-h-screen grid place-items-center">載入登入狀態中...</div>
  }

  if (!auth.isAuthenticated) {
    return (
      <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
        <div className="max-w-lg text-center space-y-4">
          <p className="text-sm uppercase tracking-[0.4em] text-emerald-300">PixelForge</p>
          <h1 className="text-4xl font-black">像素遊戲資產生成工作台</h1>
          <p className="text-slate-300">請登入後開始建立風格一致的像素遊戲資產。</p>
          <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-left space-y-3">
            <label className="block text-sm">
              Email
              <input className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-3" value={loginEmail} onChange={(event) => setLoginEmail(event.target.value)} />
            </label>
            <label className="block text-sm">
              Password
              <input className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-3" type="password" value={loginPassword} onChange={(event) => setLoginPassword(event.target.value)} />
            </label>
            <button className="w-full rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950" onClick={() => void login()}>
              登入 PixelForge
            </button>
          </div>
          {message && <p className="rounded-lg bg-white/10 p-3 text-sm text-slate-200">{message}</p>}
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-900/80 px-6 py-4 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-emerald-300">PixelForge</p>
          <h1 className="text-2xl font-black">像素資產生成與後處理</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <span className="text-slate-300">{auth.user?.email}</span>
          <button className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" onClick={() => void auth.logout()}>
            登出
          </button>
        </div>
      </header>

      <main className="grid gap-4 p-4 lg:grid-cols-[320px_1fr_360px]">
        <section className="rounded-2xl border border-white/10 bg-slate-900 p-4 space-y-4">
          <h2 className="font-bold text-lg">Generate</h2>
          <label className="block text-sm">
            主題
            <textarea
              className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-3"
              rows={4}
              value={subject}
              onChange={(event) => setSubject(event.target.value)}
            />
          </label>
          <label className="block text-sm">
            風格預設
            <select className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-2" value={preset} onChange={(event) => setPreset(event.target.value)}>
              {presets.map((item) => (
                <option key={item.key} value={item.key}>{item.name}</option>
              ))}
            </select>
          </label>
          {selectedPreset && (
            <div className="rounded-xl border border-emerald-300/20 bg-emerald-300/5 p-3 text-xs text-slate-300">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-emerald-200">{selectedPreset.name}</p>
                  <p className="mt-1 leading-relaxed">{selectedPreset.description}</p>
                </div>
                <span className="shrink-0 rounded-full bg-white/10 px-2 py-1 text-[11px] text-slate-300">{selectedPreset.resolution}</span>
              </div>
              <div className="mt-3 flex items-center justify-between gap-2">
                <p className="font-medium text-slate-200">模板色盤：{selectedPaletteKey}</p>
                <div className="flex items-center gap-2">
                  <p className="text-slate-500">{selectedPalette.length} 色</p>
                  <button className="rounded bg-white/10 px-2 py-0.5 text-slate-300 hover:bg-white/20" onClick={() => setShowPaletteDetails((value) => !value)}>
                    ...
                  </button>
                </div>
              </div>
              <div className="mt-2 grid grid-cols-8 overflow-hidden rounded-lg border border-white/10">
                {selectedPalette.map((color) => (
                  <div key={color} className="h-8" style={{ backgroundColor: color }} title={color} />
                ))}
              </div>
              {showPaletteDetails && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {selectedPalette.map((color) => (
                    <span key={color} className="rounded bg-slate-950 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">{color}</span>
                  ))}
                </div>
              )}
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm">
              視角
              <select className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-2" value={view} onChange={(event) => setView(event.target.value)}>
                <option value="top-down">top-down</option>
                <option value="side-view">side-view</option>
                <option value="isometric">isometric</option>
              </select>
            </label>
            <label className="block text-sm">
              模式
              <select className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-2" value={mode} onChange={(event) => setMode(event.target.value)}>
                <option value="single">single</option>
                <option value="grid">grid</option>
              </select>
            </label>
          </div>
          <div>
            <p className="mb-2 text-sm">處理流程</p>
            <div className="space-y-2">
              {[...processors, ...Object.keys(PROCESSOR_DEFS).filter((item) => !processors.includes(item))].map((item) => {
                const def = PROCESSOR_DEFS[item]
                const enabled = processors.includes(item)
                return (
                  <div
                    key={item}
                    onDragOver={(event) => {
                      if (enabled && draggedProcessor) event.preventDefault()
                    }}
                    onDrop={(event) => {
                      event.preventDefault()
                      if (enabled && draggedProcessor) reorderProcessor(draggedProcessor, item)
                      setDraggedProcessor(null)
                    }}
                    className={`rounded-lg border border-white/10 bg-slate-950 p-2 transition ${draggedProcessor === item ? "opacity-50 ring-2 ring-emerald-300" : ""} ${enabled ? "" : "opacity-70"}`}
                  >
                    <div className="flex items-center gap-2 text-sm">
                      <input type="checkbox" checked={enabled} onChange={() => toggleProcessor(item)} />
                      <span
                        className={`select-none rounded px-1 text-slate-500 ${enabled ? "cursor-grab active:cursor-grabbing hover:bg-white/10" : "opacity-30"}`}
                        draggable={enabled}
                        onDragStart={() => enabled && setDraggedProcessor(item)}
                        onDragEnd={() => setDraggedProcessor(null)}
                        title="拖曳調整順序"
                      >
                        ⋮⋮
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="font-medium">{def.label}</p>
                        <p className="text-xs text-slate-500">{def.description}</p>
                      </div>
                    </div>
                    {enabled && item === "bg_remover" && (
                      <div className="mt-2 space-y-2 pl-6 text-xs text-slate-400">
                        <div className="flex flex-wrap gap-1">
                          {BG_REMOVER_METHODS.map((method) => (
                            <button key={method.value} className={`rounded px-2 py-1 ${processorConfig.bg_remover?.method === method.value ? "bg-emerald-400 text-slate-950" : "bg-white/10"}`} onClick={() => updateProcessorConfig("bg_remover", { method: method.value })}>{method.label}</button>
                          ))}
                        </div>
                        {processorConfig.bg_remover?.method === "magenta" ? (
                          <div className="rounded bg-white/5 p-2 leading-relaxed text-slate-500">
                            使用 #FF00FF 品紅背景作 chroma key，會移除純品紅與邊界附近的品紅殘留。
                          </div>
                        ) : (
                          <>
                            <label className="flex items-center gap-2">
                              <span>分離敏感度</span>
                              <input className="w-24 accent-emerald-300" type="range" min="8" max="32" value={Number(processorConfig.bg_remover?.tolerance ?? 18)} onChange={(event) => updateProcessorConfig("bg_remover", { tolerance: Number(event.target.value) })} />
                              <span>{String(processorConfig.bg_remover?.tolerance ?? 18)}</span>
                            </label>
                            <label className="flex items-center gap-1">
                              <input type="checkbox" checked={processorConfig.bg_remover?.edge_cleanup !== false} onChange={(event) => updateProcessorConfig("bg_remover", { edge_cleanup: event.target.checked })} />
                              清理亮色邊緣 halo
                            </label>
                          </>
                        )}
                      </div>
                    )}
                    {enabled && item === "perfect_pixel" && (
                      <div className="mt-2 space-y-2 pl-6">
                        <div className="flex flex-wrap gap-1">
                          {PIXEL_TARGETS.map((target) => (
                            <button key={target.label} className={`rounded px-2 py-1 text-xs ${processorConfig.perfect_pixel?.target_size === target.value ? "bg-emerald-400 text-slate-950" : "bg-white/10"}`} onClick={() => updateProcessorConfig("perfect_pixel", { target_size: target.value })}>{target.label}</button>
                          ))}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {SAMPLE_METHODS.map((method) => (
                            <button key={method} className={`rounded px-2 py-1 text-xs ${processorConfig.perfect_pixel?.sample_method === method ? "bg-emerald-400 text-slate-950" : "bg-white/10"}`} onClick={() => updateProcessorConfig("perfect_pixel", { sample_method: method })}>{method}</button>
                          ))}
                        </div>
                        <label className="flex items-center gap-1 text-xs">
                          <input type="checkbox" checked={processorConfig.perfect_pixel?.remove_outliers !== false} onChange={(event) => updateProcessorConfig("perfect_pixel", { remove_outliers: event.target.checked })} />
                          離群移除
                        </label>
                      </div>
                    )}
                    {enabled && item === "color_quantizer" && (
                      <div className="mt-2 flex flex-wrap gap-1 pl-6">
                        {COLOR_COUNTS.map((count) => (
                          <button key={count} className={`rounded px-2 py-1 text-xs ${processorConfig.color_quantizer?.n_colors === count ? "bg-emerald-400 text-slate-950" : "bg-white/10"}`} onClick={() => updateProcessorConfig("color_quantizer", { n_colors: count })}>{count} 色</button>
                        ))}
                      </div>
                    )}
                    {enabled && item === "palette_mapper" && (
                      <div className="mt-2 space-y-2 pl-6 text-xs text-slate-400">
                        <label className="flex items-center gap-1">
                          <input type="checkbox" checked={processorConfig.palette_mapper?.dither !== false} onChange={(event) => updateProcessorConfig("palette_mapper", { dither: event.target.checked })} />
                          Atkinson dithering
                        </label>
                        <p className="text-slate-500">目前會映射到上方 {selectedPaletteKey} 的 {selectedPalette.length} 色模板色盤。</p>
                      </div>
                    )}
                    {enabled && item === "upscaler" && (
                      <div className="mt-2 flex flex-wrap gap-1 pl-6">
                        {UPSCALE_FACTORS.map((scale) => (
                          <button key={scale} className={`rounded px-2 py-1 text-xs ${processorConfig.upscaler?.scale === scale ? "bg-emerald-400 text-slate-950" : "bg-white/10"}`} onClick={() => updateProcessorConfig("upscaler", { scale })}>{scale}x</button>
                        ))}
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
          <button className="w-full rounded-xl bg-emerald-400 px-4 py-3 font-bold text-slate-950 hover:bg-emerald-300" onClick={() => void createGenerationJob()}>
            建立生成任務
          </button>
          {message && <p className="rounded-lg bg-white/10 p-3 text-sm text-slate-200">{message}</p>}
        </section>

        <section className="rounded-2xl border border-white/10 bg-slate-900 p-4">
          <h2 className="mb-4 font-bold text-lg">任務進度</h2>
          <div className="space-y-3">
            {jobs.map((job) => {
              const isFailed = job.status === "FAILED"
              const statusLabel = JOB_STATUS_LABELS[job.status] ?? job.status
              const stageDescription = JOB_STAGE_DESCRIPTIONS[job.status] ?? "任務進行中。"
              return (
              <article key={job.id} className={`rounded-xl border p-4 ${isFailed ? "border-red-400/30 bg-red-950/30" : "border-white/10 bg-slate-950"}`}>
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold">{job.subject}</p>
                    <p className="text-xs text-slate-400">{job.preset_key} · {statusLabel}</p>
                  </div>
                  <span className={`text-sm ${isFailed ? "text-red-200" : "text-emerald-300"}`}>{job.percent}%</span>
                </div>
                <p className="mt-2 text-xs text-slate-400">{stageDescription}</p>
                <div className="mt-3 h-2 rounded-full bg-slate-800">
                  <div className={`h-2 rounded-full ${isFailed ? "bg-red-400" : "bg-emerald-400"}`} style={{ width: `${job.percent}%` }} />
                </div>
                {job.error && <p className="mt-2 text-sm text-red-300">{job.error}</p>}
                {isFailed && (
                  <button className="mt-3 rounded-md bg-red-500/20 px-3 py-1.5 text-sm text-red-100 hover:bg-red-500/30" onClick={() => void dismissFailedJob(job.id)}>
                    移除顯示
                  </button>
                )}
              </article>
              )
            })}
            {!jobs.length && <p className="text-sm text-slate-400">尚無生成任務。</p>}
          </div>
        </section>

        <section className="rounded-2xl border border-white/10 bg-slate-900 p-4">
          <h2 className="mb-4 font-bold text-lg">資產庫</h2>
          <div className="grid gap-3">
            {assets.map((asset) => (
              <article key={asset.id} className="rounded-xl border border-white/10 bg-slate-950 p-3">
                <img src={asset.thumbnail_url} alt={asset.subject} className="mb-3 h-32 w-full rounded-lg object-contain bg-black/40" />
                <p className="font-semibold">{asset.subject}</p>
                <p className="text-xs text-slate-400">{asset.preset_key} · {asset.status}</p>
                <div className="mt-3 flex gap-2">
                  <a className="rounded-md bg-white/10 px-2 py-1 text-sm hover:bg-white/20" href={asset.image_url} target="_blank" rel="noreferrer">
                    檢視
                  </a>
                  <button className="rounded-md bg-white/10 px-2 py-1 text-sm hover:bg-white/20" onClick={() => void retryAsset(asset.id)}>
                    重試
                  </button>
                  <button className="rounded-md bg-red-500/20 px-2 py-1 text-sm text-red-200 hover:bg-red-500/30" onClick={() => void deleteAsset(asset.id)}>
                    刪除
                  </button>
                </div>
              </article>
            ))}
            {!assets.length && <p className="text-sm text-slate-400">尚無資產。</p>}
          </div>
        </section>
      </main>
    </div>
  )
}

export default function App() {
  if (window.location.pathname === "/payment/result") {
    return (
      <ThemeProvider>
        <AuthProvider>
          <PaymentResultPage />
        </AuthProvider>
      </ThemeProvider>
    )
  }

  if (window.location.pathname.startsWith("/test") && ENABLE_API_TESTER) {
    return <ApiTesterApp />
  }

  return (
    <ThemeProvider>
      <AuthProvider>
        <PixelForgeHome />
      </AuthProvider>
    </ThemeProvider>
  )
}
