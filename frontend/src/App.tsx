import { useEffect, useRef, useState } from "react"
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
import { ImageViewerPage } from "./components/ImageViewerPage"
import { PaymentResultPage } from "./components/PaymentResultPage"
import { SocialLoginPanel } from "./components/SocialLoginPanel"
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
  preset_name?: string
  error?: string
  result_asset_id?: string | null
}

interface HistoryJob {
  id: string
  status: string
  subject: string
  percent: number
  preset_key: string
  preset_name?: string
  error?: string
  asset_id?: string | null
  thumbnail_url?: string | null
  created_at: string
  updated_at: string
  archived_at?: string | null
}

interface Asset {
  id: string
  subject: string
  preset_key: string
  status: string
  metadata?: Record<string, unknown>
  thumbnail_url: string
  image_url: string
  origin_url: string
  metadata_url: string
}

type AssetViewerVariant = "image" | "origin"

interface ProviderConfig {
  id: string
  name: string
  available: boolean
  image_models: string[]
  default_image_model: string
}

interface AiProviderConfigResponse {
  providers: ProviderConfig[]
  default_provider: string
}

interface AgentGenerationItem {
  id: string
  status: string
  category: string
  name: string
  subject: string
  asset_type: string
  prompt_brief: string
  sort_order: number
  retry_count: number
  generation_job_id?: string | null
  percent: number
  error?: string
  asset_id?: string | null
  thumbnail_url?: string | null
  metadata?: Record<string, unknown>
}

interface AgentManifestItem {
  category: string
  name: string
  subject: string
  asset_type: string
  prompt_brief: string
}

interface AgentGenerationMessage {
  id: string
  role: "user" | "assistant" | "system"
  content: string
  client_message_id?: string
  metadata?: Record<string, unknown>
  created_at: string
}

interface AgentGenerationSession {
  id: string
  status: string
  brief: string
  output_name: string
  game_genre: string
  camera_view: string
  style_mode: string
  auto_generate: boolean
  asset_requirements: Record<string, number>
  context?: Record<string, unknown>
  preset_key?: string | null
  preset_name?: string | null
  manifest: {
    style?: Record<string, unknown>
    notes?: string[]
    items?: AgentManifestItem[]
    [key: string]: unknown
  }
  planning_steps: { key: string; label: string; status: string }[]
  item_counts: Record<string, number>
  messages?: AgentGenerationMessage[]
  items?: AgentGenerationItem[]
  error?: string
  last_orchestration_task_id?: string
  latest_chat_at: string
  last_message?: string
  created_at: string
  updated_at: string
}

const PROCESSOR_DEFS: Record<string, { label: string; description: string }> = {
  bg_remover: { label: "背景移除", description: "移除 AI 生圖背景，預設用品紅 chroma key" },
  alpha_trimmer: { label: "透明裁切", description: "裁切透明邊界並保留 padding" },
  perfect_pixel: { label: "完美像素", description: "自動偵測格線並重建對齊的像素圖" },
  palette_mapper: { label: "模板色盤", description: "強制映射到所選風格色盤" },
  color_quantizer: { label: "自動量化", description: "自動降低色數並保留高光" },
  upscaler: { label: "像素放大", description: "以最近鄰插值輸出展示圖" },
}

const DEFAULT_PROCESSORS = ["bg_remover", "perfect_pixel", "upscaler"]
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
]
const ACTIVE_JOB_STATUSES = new Set(["QUEUED", "PLANNING", "GENERATING", "PROCESSING"])

const JOB_STATUS_LABELS: Record<string, string> = {
  QUEUED: "已排隊",
  PLANNING: "正在生成風格化 Prompt",
  GENERATING: "正在生成圖片",
  PROCESSING: "正在處理圖片",
  ARCHIVED: "已完成",
  FAILED: "失敗",
  DISMISSED: "已移除",
}

const JOB_STAGE_DESCRIPTIONS: Record<string, string> = {
  QUEUED: "任務已建立，等待背景 worker 接手。",
  PLANNING: "正在生成風格化 Prompt ... (10%)",
  GENERATING: "正在生成圖片 ... (30%)",
  PROCESSING: "正在處理圖片 ... (70%)",
  ARCHIVED: "任務已完成，會保留在這次頁面工作階段中。",
  FAILED: "任務失敗，可移除顯示後重新提交或調整設定。",
}

const AGENT_STATUS_LABELS: Record<string, string> = {
  CHATTING: "對話中",
  PLANNING: "規劃中",
  GENERATING: "生成中",
  COMPLETED: "已完成",
  PARTIAL: "部分完成",
  FAILED: "失敗",
  CANCELED: "已取消",
}

const AGENT_ITEM_STATUS_LABELS: Record<string, string> = {
  PLANNED: "已規劃",
  QUEUED: "已排隊",
  GENERATING: "生成中",
  ARCHIVED: "已完成",
  FAILED: "失敗",
  CANCELED: "已取消",
}
const ACTIVE_AGENT_SESSION_STATUSES = new Set(["PLANNING", "GENERATING"])

function hasActiveJobs(jobs: GenerationJob[]) {
  return jobs.some((job) => ACTIVE_JOB_STATUSES.has(job.status))
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null
}

function asRecordArray(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => item !== null)
    : []
}

function metadataText(value: unknown, fallback = "未記錄") {
  if (typeof value === "string" && value.trim()) return value
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  if (Array.isArray(value) && value.length) return value.join(", ")
  return fallback
}

function totalAssetCount(requirements: Record<string, number> | undefined) {
  return Object.values(requirements ?? {}).reduce((sum, value) => sum + (Number.isFinite(value) ? value : 0), 0)
}

function buildAssetViewerUrl(assetId: string, variant: AssetViewerVariant, title?: string) {
  const params = new URLSearchParams({
    assetId,
    variant,
  })
  if (title?.trim()) {
    params.set("title", title.trim())
  }
  return `/image-viewer?${params.toString()}`
}

interface PixelForgeLoginScreenProps {
  loginIdentifier: string
  loginPassword: string
  message: string
  title: string
  description: string
  onLoginIdentifierChange: (value: string) => void
  onLoginPasswordChange: (value: string) => void
  onLogin: () => void
}

function PixelForgeLoginScreen({
  loginIdentifier,
  loginPassword,
  message,
  title,
  description,
  onLoginIdentifierChange,
  onLoginPasswordChange,
  onLogin,
}: PixelForgeLoginScreenProps) {
  return (
    <div className="min-h-screen bg-slate-950 text-white grid place-items-center p-6">
      <div className="max-w-lg text-center space-y-4">
        <p className="text-sm uppercase tracking-[0.4em] text-emerald-300">PixelForge</p>
        <h1 className="text-4xl font-black">{title}</h1>
        <p className="text-slate-300">{description}</p>
        <div className="rounded-2xl border border-white/10 bg-white/5 p-4 text-left space-y-3">
          <label className="block text-sm">
            Email 或使用者名稱
            <input
              className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-3"
              autoComplete="username"
              placeholder="輸入 email 或使用者名稱"
              value={loginIdentifier}
              onChange={(event) => onLoginIdentifierChange(event.target.value)}
            />
          </label>
          <label className="block text-sm">
            Password
            <input
              className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-3"
              autoComplete="current-password"
              type="password"
              value={loginPassword}
              onChange={(event) => onLoginPasswordChange(event.target.value)}
            />
          </label>
          <button
            className="w-full rounded-lg bg-emerald-400 px-4 py-2 font-semibold text-slate-950"
            onClick={onLogin}
          >
            登入 PixelForge
          </button>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            <div className="h-px flex-1 bg-white/10" />
            或
            <div className="h-px flex-1 bg-white/10" />
          </div>
          <SocialLoginPanel provider="google" hideStatus fullWidth />
        </div>
        {message && <p className="rounded-lg bg-white/10 p-3 text-sm text-slate-200">{message}</p>}
      </div>
    </div>
  )
}

function extractApiErrorMessage(body: unknown, fallbackMessage: string): string {
  if (!body || typeof body !== "object") {
    return fallbackMessage
  }

  const payload = body as Record<string, unknown>
  const error = payload.error
  if (error && typeof error === "object") {
    const message = (error as Record<string, unknown>).message
    if (typeof message === "string" && message.trim()) {
      return message
    }
  }

  const message = payload.message
  if (typeof message === "string" && message.trim()) {
    return message
  }

  return fallbackMessage
}

function PixelForgeHome() {
  const auth = useAuth()
  const [presets, setPresets] = useState<StylePreset[]>([])
  const [jobs, setJobs] = useState<GenerationJob[]>([])
  const [assets, setAssets] = useState<Asset[]>([])
  const [providerConfigs, setProviderConfigs] = useState<ProviderConfig[]>([])
  const [defaultProviderId, setDefaultProviderId] = useState("azure_openai")
  const [selectedProviderId, setSelectedProviderId] = useState("")
  const [selectedModel, setSelectedModel] = useState("")
  const [previewAssetId, setPreviewAssetId] = useState<string | null>(null)
  const [previewMetadata, setPreviewMetadata] = useState<Record<string, unknown> | null>(null)
  const [loginIdentifier, setLoginIdentifier] = useState("")
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
    perfect_pixel: { target_size: "none", sample_method: "center", remove_outliers: true },
    palette_mapper: { dither: true, dither_strength: 0.55 },
    color_quantizer: { n_colors: 16 },
    upscaler: { scale: 10 },
  })
  const [message, setMessage] = useState("")
  const liveRequestSequence = useRef(0)
  const jobsRef = useRef<GenerationJob[]>([])

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
    return payload.data ?? null
  }

  async function requestDelete(url: string): Promise<boolean> {
    const response = await sendRequest({ method: "DELETE", url })
    if (response.status >= 400) {
      setMessage(`請求失敗 (${response.status})`)
      return false
    }
    const payload = response.body as { message?: string } | null
    if (payload?.message) setMessage(payload.message)
    return true
  }

  async function loadJobProgress(jobId: string): Promise<GenerationJob | null> {
    const response = await sendRequest({ method: "GET", url: `/api/v1/generation-jobs/${jobId}/progress/` })
    if (response.status >= 400) return null
    const payload = response.body as { data?: GenerationJob } | null
    return payload?.data ?? null
  }

  async function loadPresets() {
    const presetData = await requestJson<StylePreset[]>("GET", "/api/v1/style-presets/")
    if (presetData) {
      setPresets(presetData)
      if (!presetData.some((item) => item.key === preset) && presetData[0]) {
        setPreset(presetData[0].key)
      }
    }
  }

  async function loadJobs(): Promise<GenerationJob[] | null> {
    const requestSequence = liveRequestSequence.current + 1
    liveRequestSequence.current = requestSequence
    const liveJobs = await requestJson<GenerationJob[]>("GET", "/api/v1/generation-jobs/live/")
    if (!liveJobs) return null
    const currentJobs = jobsRef.current
    const missingActiveJobIds = currentJobs
      .filter(
        (job) =>
          ACTIVE_JOB_STATUSES.has(job.status) &&
          !liveJobs.some((nextJob) => nextJob.id === job.id),
      )
      .map((job) => job.id)
    const transitionedJobs = await Promise.all(missingActiveJobIds.map((jobId) => loadJobProgress(jobId)))
    if (requestSequence !== liveRequestSequence.current) return null
    const archivedJobs = [
      ...currentJobs.filter(
        (job) => job.status === "ARCHIVED" && !liveJobs.some((nextJob) => nextJob.id === job.id),
      ),
      ...transitionedJobs.filter((job): job is GenerationJob => job?.status === "ARCHIVED"),
    ]
    const archivedMap = new Map<string, GenerationJob>()
    for (const job of archivedJobs) archivedMap.set(job.id, job)
    const nextJobs = [...liveJobs, ...archivedMap.values()]
    setJobs(nextJobs)
    if (transitionedJobs.some((job) => job?.status === "ARCHIVED")) {
      void loadAssets()
    }
    return nextJobs
  }

  async function loadAssets() {
    const assetData = await requestJson<Asset[]>("GET", "/api/v1/assets/")
    if (assetData) setAssets(assetData)
  }

  async function loadProviderConfig() {
    const providerData = await requestJson<AiProviderConfigResponse>("GET", "/api/v1/ai-providers/test-config/")
    if (providerData) {
      setProviderConfigs(providerData.providers)
      setDefaultProviderId(providerData.default_provider || "azure_openai")
    }
  }

  async function loadInitialData() {
    await Promise.all([
      loadPresets(),
      loadJobs(),
      loadAssets(),
      loadProviderConfig(),
    ])
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return
    void loadInitialData()
  }, [auth.isAuthenticated])

  useEffect(() => {
    jobsRef.current = jobs
  }, [jobs])

  useEffect(() => {
    if (!auth.isAuthenticated || !hasActiveJobs(jobs)) return
    const timer = window.setInterval(() => {
      void loadJobs()
    }, 5000)
    return () => window.clearInterval(timer)
  }, [auth.isAuthenticated, jobs])

  useEffect(() => {
    setShowPaletteDetails(false)
  }, [preset])

  const imageModelOptions = providerConfigs
    .filter((provider) => provider.available && provider.image_models.length > 0)
    .flatMap((provider) =>
      provider.image_models.map((model) => ({
        providerId: provider.id,
        providerName: provider.name,
        model,
      })),
    )
  const selectedModelValue =
    selectedProviderId && selectedModel ? `${selectedProviderId}::${selectedModel}` : ""
  const previewAsset = assets.find((asset) => asset.id === previewAssetId) ?? null
  const metadataStylePreset = asRecord(previewMetadata?.style_preset)
  const metadataModel = asRecord(previewMetadata?.model_info)
  const metadataGeneration = asRecord(previewMetadata?.generation)
  const metadataQuality = asRecord(previewMetadata?.quality)
  const metadataProcessors = Array.isArray(previewMetadata?.processors)
    ? previewMetadata?.processors
    : asRecord(previewMetadata?.processors)?.enabled

  useEffect(() => {
    if (!imageModelOptions.length) {
      setSelectedProviderId("")
      setSelectedModel("")
      return
    }

    const currentProvider = providerConfigs.find(
      (provider) => provider.id === selectedProviderId && provider.image_models.length > 0,
    )
    if (currentProvider?.available) return

    const defaultProvider = providerConfigs.find(
      (provider) =>
        provider.id === defaultProviderId &&
        provider.available &&
        provider.image_models.length > 0,
    )
    const nextProvider = defaultProvider ?? providerConfigs.find(
      (provider) => provider.available && provider.image_models.length > 0,
    )
    setSelectedProviderId(nextProvider?.id ?? "")
  }, [defaultProviderId, imageModelOptions.length, providerConfigs, selectedProviderId])

  useEffect(() => {
    const currentProvider = providerConfigs.find((provider) => provider.id === selectedProviderId)
    if (!currentProvider) {
      setSelectedModel("")
      return
    }
    if (currentProvider.image_models.includes(selectedModel)) return
    setSelectedModel(currentProvider.default_image_model || currentProvider.image_models[0] || "")
  }, [providerConfigs, selectedModel, selectedProviderId])

  useEffect(() => {
    if (previewAssetId && !assets.some((asset) => asset.id === previewAssetId)) {
      setPreviewAssetId(null)
    }
  }, [assets, previewAssetId])

  useEffect(() => {
    if (!previewAsset) {
      setPreviewMetadata(null)
      return
    }
    setPreviewMetadata(previewAsset.metadata ?? null)
    void requestJson<Record<string, unknown>>("GET", previewAsset.metadata_url).then((metadata) => {
      if (metadata) setPreviewMetadata(metadata)
    })
  }, [previewAsset?.id])

  async function createGenerationJob() {
    if (!selectedProviderId || !selectedModel) {
      setMessage("請先在 .env 設定可用的圖像模型")
      return
    }
    setMessage("正在建立任務...")
    const data = await requestJson<GenerationJob>("POST", "/api/v1/generation-jobs/", {
      subject,
      provider: selectedProviderId,
      model: selectedModel,
      preset,
      view,
      mode,
      processors,
      processor_config: processorConfig,
    })
    if (data) {
      setJobs((current) => [data, ...current.filter((job) => job.id !== data.id)])
    }
  }

  async function dismissFailedJob(jobId: string) {
    const previousJobs = jobs
    setJobs((current) => current.filter((job) => job.id !== jobId))
    const data = await requestJson<GenerationJob>("DELETE", `/api/v1/generation-jobs/${jobId}/`)
    if (!data) {
      setJobs(previousJobs)
      return
    }
    if (data?.status === "DISMISSED" || data?.status === "FAILED") {
      setJobs((current) => current.filter((job) => job.id !== jobId))
    } else {
      setJobs(previousJobs)
    }
  }

  async function retryAsset(assetId: string) {
    await requestJson<{ job_id: string }>("POST", `/api/v1/assets/${assetId}/retry/`, {})
    await Promise.all([loadJobs(), loadAssets()])
  }

  async function deleteAsset(assetId: string) {
    const previousAssets = assets
    const previousPreviewAssetId = previewAssetId
    setAssets((current) => current.filter((asset) => asset.id !== assetId))
    if (previewAssetId === assetId) setPreviewAssetId(null)
    const deleted = await requestDelete(`/api/v1/assets/${assetId}/`)
    if (!deleted) {
      setAssets(previousAssets)
      setPreviewAssetId(previousPreviewAssetId)
    }
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
      body: JSON.stringify({ identifier: loginIdentifier, password: loginPassword }),
    })
    if (response.status >= 400) {
      setMessage(extractApiErrorMessage(response.body, `登入失敗 (${response.status})`))
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
      <PixelForgeLoginScreen
        loginIdentifier={loginIdentifier}
        loginPassword={loginPassword}
        message={message}
        title="像素遊戲資產生成工作台"
        description="請登入後開始建立風格一致的像素遊戲資產。"
        onLoginIdentifierChange={setLoginIdentifier}
        onLoginPasswordChange={setLoginPassword}
        onLogin={() => void login()}
      />
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
          <a className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" href="/agent-generation">
            Agent 生圖
          </a>
          <a className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" href="/history">
            任務歷史
          </a>
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
            模型
            <select
              className="mt-1 w-full rounded-lg border border-white/10 bg-slate-950 p-2"
              value={selectedModelValue}
              onChange={(event) => {
                const [providerId, model] = event.target.value.split("::")
                setSelectedProviderId(providerId || "")
                setSelectedModel(model || "")
              }}
              disabled={!imageModelOptions.length}
            >
              {!imageModelOptions.length && <option value="">尚未設定可用圖像模型</option>}
              {imageModelOptions.map((option) => (
                <option key={`${option.providerId}:${option.model}`} value={`${option.providerId}::${option.model}`}>
                  {option.providerName} · {option.model}
                </option>
              ))}
            </select>
          </label>
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
                            使用 #FF00FF 品紅背景作 chroma key，並清理暗品紅陰影與邊界殘留。
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

        <section className="space-y-4">
          <div className="rounded-2xl border border-white/10 bg-slate-900 p-4">
            <h2 className="mb-4 font-bold text-lg">預覽區</h2>
            {previewAsset ? (
              <div className="rounded-xl border border-emerald-300/20 bg-slate-950 p-4">
                <img src={previewAsset.image_url} alt={previewAsset.subject} className="h-80 w-full rounded-lg bg-black/40 object-contain" />
                <div className="mt-3 flex items-center justify-between gap-3">
                  <div>
                    <p className="font-semibold">{previewAsset.subject}</p>
                    <p className="text-xs text-slate-400">{previewAsset.preset_key} · {previewAsset.status}</p>
                  </div>
                </div>
                <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-3 text-xs text-slate-300">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <p className="font-semibold text-emerald-200">圖像來源 metadata</p>
                    <a
                      className="text-slate-400 underline hover:text-slate-200"
                      href={buildAssetViewerUrl(previewAsset.id, "origin", `${previewAsset.subject} 原圖`)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      檢視原圖
                    </a>
                  </div>
                  <dl className="grid gap-2">
                    <div>
                      <dt className="text-slate-500">風格預設</dt>
                      <dd>
                        {metadataText(metadataStylePreset?.name, previewAsset.preset_key)}
                        {" · "}
                        {metadataText(metadataStylePreset?.key, previewAsset.preset_key)}
                        {metadataStylePreset?.version ? ` v${String(metadataStylePreset.version)}` : ""}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">模型</dt>
                      <dd>
                        {metadataText(metadataModel?.provider, "未記錄供應商")}
                        {" · "}
                        {metadataText(metadataModel?.image_model ?? previewMetadata?.model)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">生成設定</dt>
                      <dd>
                        {metadataText(metadataGeneration?.view, "未記錄視角")}
                        {" · "}
                        {metadataText(metadataGeneration?.mode, "未記錄模式")}
                        {" · 品質檢查 "}
                        {metadataText(metadataQuality?.qc_pass === true ? "通過" : metadataQuality?.qc_pass === false ? "未通過" : "未執行")}
                        {" · "}
                        {metadataText(metadataQuality?.score, "未評分")} 分
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">Prompt</dt>
                      <dd className="max-h-24 overflow-auto rounded bg-slate-950 p-2 leading-relaxed">
                        {metadataText(previewMetadata?.prompt)}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-slate-500">處理流程</dt>
                      <dd>{metadataText(metadataProcessors)}</dd>
                    </div>
                  </dl>
                </div>
              </div>
            ) : (
              <p className="rounded-xl border border-dashed border-white/10 bg-slate-950 p-6 text-sm text-slate-400">
                從資產庫點擊「檢視」後，圖片會顯示在這裡。
              </p>
            )}
          </div>

          <div className="rounded-2xl border border-white/10 bg-slate-900 p-4">
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
                  <button className="rounded-md bg-white/10 px-2 py-1 text-sm hover:bg-white/20" onClick={() => setPreviewAssetId(asset.id)}>
                    檢視
                  </button>
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

function PixelForgeAgentGenerationPage() {
  const auth = useAuth()
  const [sessions, setSessions] = useState<AgentGenerationSession[]>([])
  const [currentSession, setCurrentSession] = useState<AgentGenerationSession | null>(null)
  const [loginIdentifier, setLoginIdentifier] = useState("")
  const [loginPassword, setLoginPassword] = useState("")
  const [message, setMessage] = useState("")
  const [chatInput, setChatInput] = useState("")
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [autoGenerateEnabled, setAutoGenerateEnabled] = useState(true)
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  async function requestJson<T>(
    method: "GET" | "POST",
    url: string,
    body?: unknown,
  ): Promise<T | null> {
    const response = await sendRequest({
      method,
      url,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    })
    if (response.status >= 400) {
      const payload = response.body as { error?: { message?: string }; message?: string } | null
      setMessage(payload?.error?.message ?? payload?.message ?? `請求失敗 (${response.status})`)
      return null
    }
    const payload = response.body as { data?: T; message?: string }
    return payload.data ?? null
  }

  function sortByLatestChat(items: AgentGenerationSession[]) {
    return [...items].sort((a, b) => {
      const left = new Date(a.latest_chat_at ?? a.created_at).getTime()
      const right = new Date(b.latest_chat_at ?? b.created_at).getTime()
      return right - left
    })
  }

  function createClientMessageId() {
    return globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }

  function upsertSession(session: AgentGenerationSession, reorder: boolean) {
    setSessions((current) => {
      const next = [session, ...current.filter((item) => item.id !== session.id)]
      if (reorder) return sortByLatestChat(next)
      if (!current.some((item) => item.id === session.id)) return next
      return current.map((item) => item.id === session.id ? session : item)
    })
  }

  async function loadSessions() {
    const data = await requestJson<AgentGenerationSession[]>("GET", "/api/v1/agent-generation/sessions/")
    if (data) setSessions(sortByLatestChat(data))
  }

  async function loadSession(sessionId: string) {
    const data = await requestJson<AgentGenerationSession>("GET", `/api/v1/agent-generation/sessions/${sessionId}/`)
    if (data) {
      setCurrentSession(data)
      upsertSession(data, false)
    }
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return
    void loadSessions()
  }, [auth.isAuthenticated])

  useEffect(() => {
    setAutoGenerateEnabled(currentSession?.auto_generate ?? true)
  }, [currentSession?.id, currentSession?.auto_generate])

  useEffect(() => {
    if (
      !auth.isAuthenticated
      || !currentSession
      || !ACTIVE_AGENT_SESSION_STATUSES.has(currentSession.status)
    ) return
    const timer = window.setInterval(() => {
      void loadSession(currentSession.id)
    }, 3000)
    return () => window.clearInterval(timer)
  }, [auth.isAuthenticated, currentSession?.id, currentSession?.status])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" })
  }, [currentSession?.messages?.length, currentSession?.id])

  async function sendChat() {
    const content = chatInput.trim()
    if (!content) return
    setIsSubmitting(true)
    setMessage("")
    setChatInput("")
    const clientMessageId = createClientMessageId()
    const url = currentSession
      ? `/api/v1/agent-generation/sessions/${currentSession.id}/messages/`
      : "/api/v1/agent-generation/sessions/"
    try {
      const data = await requestJson<AgentGenerationSession>("POST", url, {
        message: content,
        client_message_id: clientMessageId,
        auto_generate: autoGenerateEnabled,
      })
      if (data) {
        setCurrentSession(data)
        upsertSession(data, true)
      } else {
        setChatInput(content)
      }
    } catch {
      setChatInput(content)
      setMessage("訊息送出失敗，請稍後再試。")
    } finally {
      setIsSubmitting(false)
    }
  }

  async function cancelSession() {
    if (!currentSession) return
    const data = await requestJson<AgentGenerationSession>(
      "POST",
      `/api/v1/agent-generation/sessions/${currentSession.id}/cancel/`,
      {},
    )
    if (data) {
      setCurrentSession(data)
      upsertSession(data, false)
    }
  }

  async function approveSession() {
    if (!currentSession) return
    const data = await requestJson<AgentGenerationSession>(
      "POST",
      `/api/v1/agent-generation/sessions/${currentSession.id}/approve/`,
      {},
    )
    if (data) {
      setCurrentSession(data)
      upsertSession(data, false)
    }
  }

  async function retryItem(itemId: string) {
    const data = await requestJson<AgentGenerationSession>(
      "POST",
      `/api/v1/agent-generation/items/${itemId}/retry/`,
      {},
    )
    if (data) {
      setCurrentSession(data)
      upsertSession(data, false)
    }
  }

  async function login() {
    setMessage("")
    const response = await sendRequest({
      method: "POST",
      url: "/api/v1/auth/login/",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: loginIdentifier, password: loginPassword }),
    })
    if (response.status >= 400) {
      setMessage(extractApiErrorMessage(response.body, `登入失敗 (${response.status})`))
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
      <PixelForgeLoginScreen
        loginIdentifier={loginIdentifier}
        loginPassword={loginPassword}
        message={message}
        title="PixelForge Agent"
        description="登入後用聊天描述素材需求，Agent 會追問必要資訊並自動生成。"
        onLoginIdentifierChange={setLoginIdentifier}
        onLoginPasswordChange={setLoginPassword}
        onLogin={() => void login()}
      />
    )
  }

  const sessionStyle = asRecord(currentSession?.manifest?.style)
  const statusLabel = currentSession
    ? AGENT_STATUS_LABELS[currentSession.status] ?? currentSession.status
    : ""
  const currentMessages = currentSession?.messages ?? []
  const currentItems = currentSession?.items ?? []
  const manifestItems = currentSession?.manifest?.items ?? []
  const completedAssetCount = currentSession
    ? Number(currentSession.item_counts?.archived ?? currentItems.filter((item) => item.status === "ARCHIVED").length)
    : 0
  const canCancel = currentSession && ["CHATTING", "PLANNING", "GENERATING"].includes(currentSession.status)
  const canDownloadAll = !!currentSession && completedAssetCount > 0
  const isAgentWorking = !!currentSession && ["PLANNING", "GENERATING"].includes(currentSession.status)
  const requirementsText = currentSession ? String(totalAssetCount(currentSession.asset_requirements) || "") : ""
  const canApprove = !!(
    currentSession
    && !currentSession.auto_generate
    && currentSession.status === "CHATTING"
    && manifestItems.length
    && !currentItems.length
  )

  return (
    <div className="flex h-screen flex-col bg-slate-950 text-slate-100">
      <header className="shrink-0 border-b border-white/10 bg-slate-900/80 px-6 py-4 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-emerald-300">PixelForge</p>
          <h1 className="text-2xl font-black">聊天式 Agent</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <a className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" href="/">
            返回工作台
          </a>
          <a className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" href="/history">
            任務歷史
          </a>
          <span className="text-slate-300">{auth.user?.email}</span>
          <button className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" onClick={() => void auth.logout()}>
            登出
          </button>
        </div>
      </header>

      <main className="grid min-h-0 flex-1 gap-4 overflow-hidden p-4 xl:grid-cols-[320px_minmax(0,1fr)_360px]">
        <aside className="flex min-h-0 flex-col rounded-2xl border border-white/10 bg-slate-900 p-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-lg">Agent Sessions</h2>
            </div>
            <button
              className="rounded-lg bg-emerald-400 px-3 py-2 text-sm font-bold text-slate-950 hover:bg-emerald-300"
              onClick={() => {
                setCurrentSession(null)
                setChatInput("")
                setAutoGenerateEnabled(true)
              }}
            >
              新對話
            </button>
          </div>
          <div className="mt-4 space-y-2 overflow-y-auto pr-1">
            {sessions.map((session) => (
              <button
                key={session.id}
                className={`w-full rounded-xl border p-3 text-left text-sm hover:bg-white/10 ${
                  currentSession?.id === session.id ? "border-emerald-300 bg-emerald-300/10" : "border-white/10"
                }`}
                onClick={() => void loadSession(session.id)}
              >
                <p className="font-semibold">{session.output_name}</p>
                <p className="text-xs text-slate-400">
                  {AGENT_STATUS_LABELS[session.status] ?? session.status} · {session.item_counts?.total ?? 0} 項
                </p>
                <p className="mt-2 line-clamp-2 text-xs text-slate-500">{session.last_message ?? session.brief}</p>
              </button>
            ))}
            {!sessions.length && <p className="text-sm text-slate-400">尚無 Agent Session。</p>}
          </div>
        </aside>

        <section className="flex min-h-0 flex-col overflow-hidden rounded-2xl border border-white/10 bg-slate-900">
          <div className="border-b border-white/10 p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="font-bold text-lg">
                  {currentSession ? currentSession.output_name : "今天要打造什麼素材？"}
                </h2>
                <p className="text-sm text-slate-400">
                  {currentSession ? `${statusLabel} · Agent 會在資訊不足時追問` : "直接用自然語言描述，遊戲類型、視角、數量都可在聊天中補齊。"}
                </p>
              </div>
              <div className="flex flex-wrap justify-end gap-2">
                {canDownloadAll && (
                  <a
                    className="rounded-lg bg-emerald-400 px-3 py-2 text-sm font-bold text-slate-950 hover:bg-emerald-300"
                    href={`/api/v1/agent-generation/sessions/${currentSession.id}/download/`}
                  >
                    下載全部
                  </a>
                )}
                {canCancel && (
                  <button
                    className="rounded-lg bg-red-500/20 px-3 py-2 text-sm text-red-100 hover:bg-red-500/30"
                    onClick={() => void cancelSession()}
                  >
                    取消
                  </button>
                )}
              </div>
            </div>
            {message && <p className="mt-3 rounded-lg bg-white/10 p-3 text-sm text-slate-200">{message}</p>}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {currentMessages.length ? (
              <div className="space-y-4">
                {currentMessages.map((chat) => {
                  const isUser = chat.role === "user"
                  const messageMeta = asRecord(chat.metadata)
                  const messageKind = typeof messageMeta?.kind === "string" ? messageMeta.kind : ""
                  const planItems = asRecordArray(messageMeta?.items)
                  const resultAssets = asRecordArray(messageMeta?.assets)
                  const isResultMessage = messageKind === "generation_result" || messageKind === "generation_item_result"
                  const isRichAssistant = !isUser && (messageKind === "generation_plan" || isResultMessage)
                  return (
                    <article key={chat.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                      <div
                        className={`rounded-2xl px-4 py-3 text-sm leading-relaxed shadow-lg ${
                          isUser
                            ? "max-w-[78%] bg-emerald-300 text-slate-950"
                            : `${isRichAssistant ? "max-w-[92%]" : "max-w-[78%]"} border border-white/10 bg-slate-950 text-slate-100`
                        }`}
                      >
                        <p className="whitespace-pre-wrap">{chat.content}</p>
                        {messageKind === "generation_plan" && (
                          <div className="mt-4 space-y-3">
                            {!!planItems.length && (
                              <div className="grid gap-2 sm:grid-cols-2">
                                {planItems.map((item, index) => (
                                  <div key={`${chat.id}-plan-${index}`} className="rounded-xl bg-white/5 p-3">
                                    <p className="font-semibold text-emerald-200">{metadataText(item.name, `素材 ${index + 1}`)}</p>
                                    <p className="mt-1 text-xs text-slate-400">{metadataText(item.subject)}</p>
                                  </div>
                                ))}
                              </div>
                            )}
                            {canApprove && (
                              <div className="flex flex-wrap gap-2">
                                <button
                                  className="rounded-lg bg-emerald-400 px-4 py-2 text-sm font-bold text-slate-950 hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
                                  disabled={isSubmitting}
                                  onClick={() => void approveSession()}
                                  type="button"
                                >
                                  開始生成
                                </button>
                                <span className="self-center text-xs text-slate-400">確認規劃後即可直接開始。</span>
                              </div>
                            )}
                          </div>
                        )}
                        {isResultMessage && (
                          <div className="mt-4 space-y-3">
                            <p className="text-xs text-slate-400">
                              已整理 {metadataText(messageMeta?.asset_count, String(resultAssets.length))} 個完成素材。
                            </p>
                            {!!resultAssets.length && (
                              <div className="grid gap-3 sm:grid-cols-2">
                                {resultAssets.map((asset, index) => (
                                  <div key={`${chat.id}-asset-${index}`} className="rounded-xl bg-white/5 p-3">
                                    {typeof asset.thumbnail_url === "string" ? (
                                      <img
                                        src={asset.thumbnail_url}
                                        alt={metadataText(asset.name, "素材")}
                                        className="mb-3 h-28 w-full rounded-lg bg-black/40 object-contain"
                                      />
                                    ) : (
                                      <div className="mb-3 grid h-28 w-full place-items-center rounded-lg border border-dashed border-white/10 bg-slate-900 text-sm text-slate-500">
                                        no-image
                                      </div>
                                    )}
                                    <p className="font-semibold">{metadataText(asset.name, `素材 ${index + 1}`)}</p>
                                    <p className="mt-1 text-xs text-slate-400">{metadataText(asset.subject)}</p>
                                    <div className="mt-3 flex flex-wrap gap-2">
                                      {typeof asset.asset_id === "string" && (
                                        <a
                                          className="rounded-md bg-white/10 px-3 py-2 text-sm hover:bg-white/20"
                                          href={buildAssetViewerUrl(
                                            asset.asset_id,
                                            "image",
                                            metadataText(asset.name, `素材 ${index + 1}`),
                                          )}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          檢視
                                        </a>
                                      )}
                                      {typeof asset.asset_id === "string" && (
                                        <a
                                          className="rounded-md bg-white/10 px-3 py-2 text-sm hover:bg-white/20"
                                          href={buildAssetViewerUrl(
                                            asset.asset_id,
                                            "origin",
                                            `${metadataText(asset.name, `素材 ${index + 1}`)} 原圖`,
                                          )}
                                          target="_blank"
                                          rel="noreferrer"
                                        >
                                          原圖
                                        </a>
                                      )}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    </article>
                  )
                })}
                {isAgentWorking && (
                  <article className="flex justify-start">
                    <div className="max-w-[78%] rounded-2xl border border-white/10 bg-slate-950 px-4 py-3 text-sm text-slate-100 shadow-lg">
                      <div className="flex items-center gap-2">
                        <span className="relative flex h-2 w-8 items-center justify-between">
                          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-300" />
                          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-300 [animation-delay:150ms]" />
                          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-300 [animation-delay:300ms]" />
                        </span>
                        <span>{currentSession.status === "GENERATING" ? "Agent 正在生成素材…" : "Agent 正在理解需求…"}</span>
                      </div>
                    </div>
                  </article>
                )}
                <div ref={messagesEndRef} />
              </div>
            ) : (
              <div className="grid h-full min-h-[360px] place-items-center text-center">
                <div className="max-w-xl">
                  <p className="text-xs uppercase tracking-[0.35em] text-emerald-300">Chat-first workflow</p>
                  <h2 className="mt-3 text-3xl font-black">我們應該在 PixelForge 中建置什麼？</h2>
                  <p className="mt-3 text-sm text-slate-400">
                    不用填參數。只要描述你想要的素材包；Agent 不確定遊戲類型、視角或數量時會直接問你。
                  </p>
                </div>
              </div>
              )}
            </div>

          <form
            className="shrink-0 border-t border-white/10 bg-slate-900/95 p-4"
            onSubmit={(event) => {
              event.preventDefault()
              void sendChat()
            }}
          >
            <div className="rounded-3xl border border-white/10 bg-slate-950 p-3 shadow-2xl shadow-emerald-950/20">
              <textarea
                className="max-h-40 min-h-20 w-full resize-none bg-transparent p-2 text-sm outline-none placeholder:text-slate-500"
                value={chatInput}
                onChange={(event) => setChatInput(event.target.value)}
                placeholder="例如：我想做一組俯視角 survival crafting 的魔法工坊素材，先要 1 個發光水晶資源。"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    void sendChat()
                  }
                }}
              />
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-3 rounded-full bg-white/5 px-3 py-2 text-sm text-slate-200">
                    <span>自動生成</span>
                    <button
                      aria-checked={autoGenerateEnabled}
                      className={`relative h-6 w-11 rounded-full transition ${
                        autoGenerateEnabled ? "bg-emerald-400" : "bg-white/10"
                      }`}
                      onClick={() => setAutoGenerateEnabled((current) => !current)}
                      role="switch"
                      type="button"
                    >
                      <span
                        className={`absolute top-0.5 h-5 w-5 rounded-full bg-slate-950 transition ${
                          autoGenerateEnabled ? "left-[22px]" : "left-0.5"
                        }`}
                      />
                    </button>
                  </label>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-xs text-slate-500">
                    {autoGenerateEnabled ? "需求完整後立即生成" : "先規劃，確認後手動開始"}
                  </span>
                  <button
                    className="grid h-10 w-10 place-items-center rounded-full bg-emerald-400 font-black text-slate-950 hover:bg-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
                    disabled={isSubmitting || !chatInput.trim()}
                    type="submit"
                    title="送出"
                  >
                    ↑
                  </button>
                </div>
              </div>
            </div>
          </form>
        </section>

        <aside className="min-h-0 space-y-4 overflow-y-auto pr-1">
          <section className="rounded-2xl border border-white/10 bg-slate-900 p-4">
            <h2 className="font-bold text-lg">Agent 掌握的資訊</h2>
            {currentSession ? (
              <dl className="mt-4 grid gap-3 text-sm">
                <div className="rounded-xl bg-slate-950 p-3">
                  <dt className="text-xs text-slate-500">遊戲類型</dt>
                  <dd className="mt-1">{currentSession.game_genre || "等待聊天確認"}</dd>
                </div>
                <div className="rounded-xl bg-slate-950 p-3">
                  <dt className="text-xs text-slate-500">視角</dt>
                  <dd className="mt-1">{currentSession.camera_view || "等待聊天確認"}</dd>
                </div>
                <div className="rounded-xl bg-slate-950 p-3">
                  <dt className="text-xs text-slate-500">素材數量</dt>
                  <dd className="mt-1">{requirementsText || "等待聊天確認"}</dd>
                </div>
              </dl>
            ) : (
              <p className="mt-4 text-sm text-slate-400">開始聊天後，Agent 會把已確認的需求整理在這裡。</p>
            )}
          </section>

          <section className="rounded-2xl border border-white/10 bg-slate-900 p-4">
            <h2 className="font-bold text-lg">規劃與生成</h2>
            {currentSession ? (
              <div className="mt-4 space-y-4">
                {sessionStyle && (
                  <div className="rounded-xl border border-white/10 bg-slate-950 p-4">
                    <p className="font-semibold">{metadataText(sessionStyle.name, "Agent 風格")}</p>
                    <p className="mt-1 text-sm text-slate-400">{metadataText(sessionStyle.description)}</p>
                    <div className="mt-3 flex flex-wrap gap-1">
                      {(Array.isArray(sessionStyle.palette_hex) ? sessionStyle.palette_hex : []).map((color) => (
                        <span
                          key={String(color)}
                          className="h-6 w-8 rounded border border-white/10"
                          style={{ backgroundColor: String(color) }}
                          title={String(color)}
                        />
                      ))}
                    </div>
                  </div>
                )}

                <div className="space-y-3">
                  {currentItems.map((item) => {
                    const itemLabel = AGENT_ITEM_STATUS_LABELS[item.status] ?? item.status
                    const isDone = item.status === "ARCHIVED"
                    const isFailed = item.status === "FAILED"
                    return (
                      <article key={item.id} className="rounded-xl border border-white/10 bg-slate-950 p-3">
                        {item.thumbnail_url ? (
                          <img
                            src={item.thumbnail_url}
                            alt={item.name}
                            className="mb-3 h-28 w-full rounded-lg bg-black/40 object-contain"
                          />
                        ) : (
                          <div className="mb-3 grid h-28 w-full place-items-center rounded-lg border border-dashed border-white/10 bg-slate-900 text-sm text-slate-500">
                            no-image
                          </div>
                        )}
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <p className="font-semibold">{item.name}</p>
                            <p className="text-xs text-slate-400">{item.category} · {itemLabel}</p>
                          </div>
                          <span className={`text-sm ${isFailed ? "text-red-200" : "text-emerald-300"}`}>
                            {item.percent}%
                          </span>
                        </div>
                        <p className="mt-2 text-sm text-slate-300">{item.subject}</p>
                        <div className="mt-3 h-2 rounded-full bg-slate-800">
                          <div
                            className={`h-2 rounded-full ${isFailed ? "bg-red-400" : "bg-emerald-400"}`}
                            style={{ width: `${Math.min(Math.max(item.percent, isDone ? 100 : 0), 100)}%` }}
                          />
                        </div>
                        {item.error && <p className="mt-2 text-sm text-red-300">{item.error}</p>}
                        <div className="mt-3 flex gap-2">
                          {item.asset_id && (
                            <a
                              className="rounded-md bg-white/10 px-3 py-2 text-sm hover:bg-white/20"
                              href={buildAssetViewerUrl(item.asset_id, "image", item.name)}
                              target="_blank"
                              rel="noreferrer"
                            >
                              檢視
                            </a>
                          )}
                          {isFailed && (
                            <button
                              className="rounded-md bg-amber-400/20 px-3 py-2 text-sm text-amber-100 hover:bg-amber-400/30"
                              onClick={() => void retryItem(item.id)}
                            >
                              重試
                            </button>
                          )}
                        </div>
                      </article>
                    )
                  })}
                  {!currentItems.length && !!manifestItems.length && (
                    <>
                      {manifestItems.map((item, index) => (
                        <article key={`${item.name}-${index}`} className="rounded-xl border border-white/10 bg-slate-950 p-3">
                          <div className="mb-3 grid h-28 w-full place-items-center rounded-lg border border-dashed border-white/10 bg-slate-900 text-sm text-slate-500">
                            planned
                          </div>
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <p className="font-semibold">{item.name}</p>
                              <p className="text-xs text-slate-400">{item.category} · 已規劃</p>
                            </div>
                          </div>
                          <p className="mt-2 text-sm text-slate-300">{item.subject}</p>
                        </article>
                      ))}
                      {canApprove && (
                        <button
                          className="w-full rounded-lg bg-emerald-400 px-4 py-3 text-sm font-bold text-slate-950 hover:bg-emerald-300"
                          onClick={() => void approveSession()}
                        >
                          開始生成
                        </button>
                      )}
                    </>
                  )}
                  {!currentItems.length && !manifestItems.length && (
                    <p className="text-sm text-slate-400">Agent 會在需求足夠後整理規劃，並依你的設定自動生成或等待你手動開始。</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="mt-4 text-sm text-slate-400">尚未選擇或建立 Agent Session。</p>
            )}
          </section>
        </aside>
      </main>
    </div>
  )
}

function PixelForgeHistoryPage() {
  const auth = useAuth()
  const [historyJobs, setHistoryJobs] = useState<HistoryJob[]>([])
  const [loginIdentifier, setLoginIdentifier] = useState("")
  const [loginPassword, setLoginPassword] = useState("")
  const [message, setMessage] = useState("")
  const [deletingJobId, setDeletingJobId] = useState<string | null>(null)

  async function requestJson<T>(
    method: "GET" | "POST" | "DELETE",
    url: string,
    body?: unknown,
  ): Promise<T | null> {
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

  async function requestDelete(url: string): Promise<boolean> {
    const response = await sendRequest({ method: "DELETE", url })
    if (response.status >= 400) {
      setMessage(`請求失敗 (${response.status})`)
      return false
    }
    const payload = response.body as { message?: string } | null
    if (payload?.message) setMessage(payload.message)
    return true
  }

  async function loadHistory() {
    const data = await requestJson<HistoryJob[]>("GET", "/api/v1/generation-jobs/history/")
    if (data) setHistoryJobs(data)
  }

  useEffect(() => {
    if (!auth.isAuthenticated) return
    void loadHistory()
  }, [auth.isAuthenticated])

  async function deleteHistoryJob(jobId: string) {
    const previousJobs = historyJobs
    setDeletingJobId(jobId)
    setHistoryJobs((current) => current.filter((job) => job.id !== jobId))
    const deleted = await requestDelete(`/api/v1/generation-jobs/${jobId}/history/`)
    if (!deleted) {
      setHistoryJobs(previousJobs)
    }
    setDeletingJobId(null)
  }

  async function login() {
    setMessage("")
    const response = await sendRequest({
      method: "POST",
      url: "/api/v1/auth/login/",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identifier: loginIdentifier, password: loginPassword }),
    })
    if (response.status >= 400) {
      setMessage(extractApiErrorMessage(response.body, `登入失敗 (${response.status})`))
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
      <PixelForgeLoginScreen
        loginIdentifier={loginIdentifier}
        loginPassword={loginPassword}
        message={message}
        title="PixelForge 任務歷史"
        description="登入後可查看歷史任務、縮圖與刪除已不需要的結果。"
        onLoginIdentifierChange={setLoginIdentifier}
        onLoginPasswordChange={setLoginPassword}
        onLogin={() => void login()}
      />
    )
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-white/10 bg-slate-900/80 px-6 py-4 flex items-center justify-between">
        <div>
          <p className="text-xs uppercase tracking-[0.35em] text-emerald-300">PixelForge</p>
          <h1 className="text-2xl font-black">任務歷史</h1>
        </div>
        <div className="flex items-center gap-3 text-sm">
          <a className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" href="/">
            返回工作台
          </a>
          <span className="text-slate-300">{auth.user?.email}</span>
          <button className="rounded-md bg-white/10 px-3 py-2 hover:bg-white/20" onClick={() => void auth.logout()}>
            登出
          </button>
        </div>
      </header>

      <main className="mx-auto max-w-6xl p-4">
        <section className="rounded-2xl border border-white/10 bg-slate-900 p-4">
          <div className="mb-4 flex items-center justify-between gap-3">
            <div>
              <h2 className="font-bold text-lg">歷史任務列表</h2>
              <p className="text-sm text-slate-400">每列提供縮圖、任務進度與刪除操作；失敗任務顯示 no-image。</p>
            </div>
          </div>
          {message && <p className="mb-4 rounded-lg bg-white/10 p-3 text-sm text-slate-200">{message}</p>}
          <div className="space-y-3">
            {historyJobs.map((job) => {
              const statusLabel = JOB_STATUS_LABELS[job.status] ?? job.status
              const isFailed = job.status === "FAILED"
              return (
                <article
                  key={job.id}
                  className="grid gap-4 rounded-xl border border-white/10 bg-slate-950 p-4 md:grid-cols-[140px_1fr_auto]"
                >
                  {job.thumbnail_url ? (
                    <img
                      src={job.thumbnail_url}
                      alt={job.subject}
                      className="h-28 w-full rounded-lg bg-black/40 object-contain"
                    />
                  ) : (
                    <div className="grid h-28 w-full place-items-center rounded-lg border border-dashed border-white/10 bg-slate-900 text-sm text-slate-500">
                      no-image
                    </div>
                  )}
                  <div className="min-w-0">
                    <div className="flex items-start justify-between gap-3">
                      <div>
                        <p className="font-semibold">{job.subject}</p>
                        <p className="text-xs text-slate-400">
                          {job.preset_name ?? job.preset_key} · {statusLabel}
                        </p>
                      </div>
                      <span className={`text-sm ${isFailed ? "text-red-200" : "text-emerald-300"}`}>
                        {job.percent}%
                      </span>
                    </div>
                    <div className="mt-3 h-2 rounded-full bg-slate-800">
                      <div
                        className={`h-2 rounded-full ${isFailed ? "bg-red-400" : "bg-emerald-400"}`}
                        style={{ width: `${Math.min(Math.max(job.percent, 0), 100)}%` }}
                      />
                    </div>
                    {job.error && <p className="mt-2 text-sm text-red-300">{job.error}</p>}
                  </div>
                  <div className="flex items-start justify-end">
                    <button
                      className="rounded-md bg-red-500/20 px-3 py-2 text-sm text-red-100 hover:bg-red-500/30 disabled:cursor-not-allowed disabled:opacity-60"
                      onClick={() => void deleteHistoryJob(job.id)}
                      disabled={deletingJobId === job.id}
                    >
                      {deletingJobId === job.id ? "刪除中..." : "刪除"}
                    </button>
                  </div>
                </article>
              )
            })}
            {!historyJobs.length && <p className="text-sm text-slate-400">尚無歷史任務。</p>}
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

  if (window.location.pathname.startsWith("/image-viewer")) {
    return (
      <ThemeProvider>
        <AuthProvider>
          <ImageViewerPage />
        </AuthProvider>
      </ThemeProvider>
    )
  }

  if (window.location.pathname.startsWith("/test") && ENABLE_API_TESTER) {
    return <ApiTesterApp />
  }

  if (window.location.pathname.startsWith("/history")) {
    return (
      <ThemeProvider>
        <AuthProvider>
          <PixelForgeHistoryPage />
        </AuthProvider>
      </ThemeProvider>
    )
  }

  if (window.location.pathname.startsWith("/agent-generation")) {
    return (
      <ThemeProvider>
        <AuthProvider>
          <PixelForgeAgentGenerationPage />
        </AuthProvider>
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider>
      <AuthProvider>
        <PixelForgeHome />
      </AuthProvider>
    </ThemeProvider>
  )
}
