# PixelForge 風格一致性與圖片處理重製規劃書

## 1. 結論

這次變更方向是正確的，但建議調整重心：**不要再把「風格一致」主要交給圖像生成模型的 prompt 或色盤文字約束，而是改成「模型只負責生成清楚可用的素材草稿，PixelForge 後處理管線負責把素材收斂到統一風格」。**

原因是目前主流圖像生成模型雖然品質高、語意理解強，但對「像素級固定調色盤、精準透明背景、無抗鋸齒、固定輪廓厚度、同一專案資產一致色彩」仍不穩定。這正好符合 PixelForge 的產品定位：解決 AI 生圖不穩定與遊戲資產風格不一致的痛點。

因此本規劃建議：

1. 重製 `style_presets`，把模板從 DB migration 與程式字串中抽離，顯性存放於 `assets/templates/`。
2. 移除 prompt 對調色盤與 negative prompt 的依賴，改用更適合通用圖像生成模型的正向目標描述。
3. 將調色盤收斂移到 `_forge_shared/img_processor`，從演算法層面強制套用。
4. 參考 `old_pixelforge` 強化後處理器，尤其是色彩量化、像素網格重取樣、離群像素清理與多選排序。
5. 前端改回 PixelForge 產品入口，API 測試面板只在 dev 環境開放。

## 2. 現況觀察

| 範圍 | 現況 | 問題 |
| --- | --- | --- |
| `style_presets` | 預設資料寫在 `backend/modules/style_presets/migrations/0002_seed_initial_presets.py` | 模板不可版本化比對，不適合作為產品可調整的美術規格來源 |
| Prompt | `prompt_builder.py` 把調色盤、negative prompt、像素規則組成長 prompt | 現代模型更適合接收明確正向目標；長 prompt 與否定描述會稀釋核心意圖 |
| 調色盤 | `color_quantizer` 支援簡單 PIL palette quantize | 可強制色盤，但效果不如舊版 Lab 色彩空間、Atkinson dithering 與高光保護 |
| `perfect_pixel` | 目前只處理 alpha 閾值與簡單離群像素 | 舊版有 FFT/投影偵測、網格重取樣、多種取樣演算法、連通元件清理 |
| `bg_remover` | 目前只移除接近白色背景 | 舊版有 OpenCV flood fill，較能只移除與邊界相連的背景 |
| Pipeline | 新版只支援單張圖流 | 舊版 pipeline 可讓 processor 回傳多張圖，雖然 `grid_slicer` 目前停用，但架構上較有彈性 |
| 前端 | 首頁仍有「前往 API 測試面板登入」與「API 測試面板」連結 | 一般使用者會看到測試工具入口，不符合產品化定位 |

## 3. 新模板策略

### 3.1 Prompt Engine 設計方向

目前的 provider 與 model 只是測試用，後續會替換，因此 Prompt Engine 不應針對特定 provider 或 model 做最佳化，也不應存在 `model_profiles`、provider override 或 provider-specific prompt 分支。

新版 Prompt Engine 的角色應縮小為：**把使用者主題、模板風格、視角與生成模式組裝成一段清楚、短、正向、模型無關的圖像目標描述。** 模型參數、供應商參數與實際 API 差異應留在 AI Provider 層或 Generation Job 層處理，不進入模板與 Prompt Engine。

Prompt Engine 的輸出只應包含：

| 欄位 | 說明 |
| --- | --- |
| `prompt` | 給圖像生成模型的正向提示詞 |
| `template_key` | 使用的模板 key |
| `template_version` | 使用的模板版本 |
| `prompt_hash` | 方便追蹤與重現的 prompt hash |
| `warnings` | 模板缺欄位或 subject 過長等非致命警告 |

明確不輸出：

| 欄位 | 原因 |
| --- | --- |
| `negative_prompt` | 通用圖像生成模型更適合透過強化「要什麼」來收斂，不應把重點放在「不要什麼」 |
| `provider_name` | Prompt Engine 不負責供應商選擇 |
| `model` | Prompt Engine 不負責模型選擇 |
| `provider_options` / `model_params` | 避免模板被短期測試模型污染 |

### 3.2 Prompt 不再直接負責調色盤，也不使用 negative

目前模板要求：

- use only colors derived from grouped palette
- maximum 4-6 distinct colors
- no additional hues
- no gradients

這類文字對模型來說只是語意建議，無法保證輸出色彩。新版建議改為：

1. Prompt 只描述「低色數、硬邊、清楚輪廓、遊戲 sprite、透明或純色背景」。
2. 調色盤收斂交給 `palette_mapper` / `color_quantizer`。
3. 不產生 `negative_prompt`，也避免在正向 prompt 內堆疊大量 `no ...`、`without ...`、`not ...` 這類否定句。
4. 把過去 negative 想避免的問題，改寫成正向品質目標，例如「plain solid background」、「one centered object」、「clean hard edges」、「readable silhouette」。
5. 每個模板加入「後處理策略」，由 PixelForge pipeline 執行。

### 3.3 建議模板檔案位置

新增：

```text
assets/
  templates/
    schema.json
    base/
      pixel_sprite.v1.json
    styles/
      forest.v2.json
      dungeon.v2.json
      scifi.v2.json
      arcane_craft.v2.json
      cozy_farm.v1.json
      gothic_ruins.v1.json
      elemental_magic.v1.json
    palettes/
      forest-16.json
      dungeon-16.json
      scifi-16.json
      arcane-craft-16.json
```

### 3.4 建議模板 schema

```json
{
  "key": "forest",
  "version": 2,
  "name": "森林奇幻道具",
  "description": "明亮自然、RPG 道具、低色數像素資產。",
  "target": {
    "asset_type": "single_sprite",
    "resolution": "64x64",
    "final_grid": "16x16",
    "views": ["top-down", "side-view", "isometric"]
  },
  "prompt": {
    "subject_template": "A single game item sprite of {{subject}}.",
    "base": "Centered isolated object, full object visible, readable silhouette, hard pixel-art edges, low-color pixel art, simple material blocks.",
    "style": "fantasy forest RPG asset, compact shape language, warm natural highlights, readable at small game icon size.",
    "composition": "Plain solid background suitable for background removal, even margins, compact icon composition.",
    "quality": "Crisp edge separation, coherent light direction, simple readable forms."
  },
  "palette": {
    "palette_key": "forest-16",
    "enforce": true,
    "allow_highlight_slots": 2
  },
  "processors": {
    "default": [
      "bg_remover",
      "alpha_trimmer",
      "perfect_pixel",
      "palette_mapper",
      "thumbnail"
    ],
    "config": {
      "bg_remover": {
        "method": "flood_fill",
        "corner_threshold": 200,
        "tolerance": 10
      },
      "perfect_pixel": {
        "sample_method": "adaptive",
        "remove_outliers": true
      },
      "palette_mapper": {
        "mode": "palette",
        "palette_key": "forest-16",
        "dither": true,
        "dither_strength": 0.55
      }
    }
  }
}
```

### 3.5 Prompt Engine 組裝規則

Prompt Engine 建議新增為明確的領域服務，而不是把字串常數散落在 `prompt_builder.py`：

```text
backend/modules/_forge_shared/prompt_engine/
  __init__.py
  engine.py
  loaders.py
  schemas.py
  renderers.py
```

核心流程：

1. `TemplateLoader` 從 `assets/templates/styles/{key}.json` 載入模板。
2. `PromptTemplateSchema` 驗證模板必要欄位。
3. `PromptEngine.render(subject, template_key, view, mode)` 組裝正向 prompt。
4. `PromptRenderer` 只做變數替換、片段排序、長度裁切與空白正規化。
5. 回傳 `PromptResult`，包含 `prompt`、模板資訊、hash 與 warnings。

組裝順序建議固定：

```text
subject_template -> base -> view directive -> mode directive -> style -> composition -> quality
```

其中：

| 片段 | 設計原則 |
| --- | --- |
| `subject_template` | 最重要，永遠放最前面，避免模型忽略使用者主題 |
| `base` | 描述資產型態與像素草稿目標 |
| `view directive` | 只放目前選定視角，例如 top-down / side-view / isometric |
| `mode directive` | single 或 grid 的正向構圖要求 |
| `style` | 描述世界觀、形狀語言、材質語言，不描述色盤 HEX |
| `composition` | 描述置中、邊距、背景可去除等可被模型理解的構圖 |
| `quality` | 描述清楚輪廓、硬邊、可讀性等正向品質 |

禁止規則：

1. 不輸出 `negative_prompt`。
2. 不在模板內放 provider/model 條件。
3. 不把 HEX 色票塞進 prompt。
4. 不在 prompt 中堆疊否定詞清單。
5. 不讓 Prompt Engine 自動補「猜測性」風格描述；模板缺欄位應回 warnings 或驗證錯誤。

### 3.6 舊模板遷移

| 舊欄位 | 新去向 |
| --- | --- |
| `primary_palette` / `shadow_palette` / `accent_palette` / `effect_palette` | 移到 `assets/templates/palettes/*.json`，作為後處理色盤來源，不再塞進 prompt |
| `negative` | 不遷移到新模板；若舊資料仍存在，只作相容讀取但不輸出 |
| `art_direction` | 拆成 `prompt.style`、`prompt.shape_language`、`prompt.material_language` |
| `model_params` | 不屬於 Prompt Engine；後續如需保留，移到 generation defaults 或 AI Provider 設定 |
| `processors` | 模板提供 default pipeline，使用者可在前端覆蓋 |

## 4. `_forge_shared/img_processor` 重製

### 4.1 套件位置

建議新增或重命名為：

```text
backend/modules/_forge_shared/img_processor/
  __init__.py
  base.py
  registry.py
  pipeline.py
  processors/
    bg_remover.py
    alpha_trimmer.py
    perfect_pixel.py
    palette_mapper.py
    color_quantizer.py
    upscaler.py
    thumbnail.py
```

如果要避免一次大改造成 import 風險，可先保留現有 `processors/`，新增 `img_processor` façade，完成測試後再正式遷移。

### 4.2 調色盤功能

新增 `palette_mapper`，與 `color_quantizer` 分工：

| Processor | 職責 |
| --- | --- |
| `palette_mapper` | 嚴格把所有不透明像素映射到指定模板色盤，用於風格統一 |
| `color_quantizer` | 在沒有指定色盤時，自動降低色數並保留高光，用於自由風格素材 |

`palette_mapper` 應參考舊版 `ColorQuantizer` 的演算法：

1. 使用 Lab 色彩空間做最近色映射，避免 RGB 空間造成亮度偏差。
2. 透明像素完整保留，不參與量化。
3. 可選 Bilateral Filter 預處理，去掉 AI 生成的微小雜訊。
4. 可選邊緣感知 Atkinson dithering，但預設強度需比舊版低，避免 16x16 小圖出現髒點。
5. 支援 `highlight_slots`，讓高光色可被模板允許而不是被硬壓成主色。

### 4.3 Processor 優化清單

| Processor | 建議 |
| --- | --- |
| `bg_remover` | 復刻舊版 OpenCV corner flood fill，只移除與四角連通且接近背景色的區域；保留目前白底 threshold 作為 fallback |
| `alpha_trimmer` | 保留新版可配置 padding；加入最小輸出尺寸與置中補邊，避免後續縮圖比例飄移 |
| `perfect_pixel` | 復刻舊版網格偵測、`center` / `majority` / `median` / `adaptive` 取樣與連通元件離群移除 |
| `palette_mapper` | 新增；負責模板色盤強制映射 |
| `color_quantizer` | 復刻舊版 Lab + Wu quantization + highlight detection + Atkinson dithering |
| `upscaler` | 保留最近鄰放大，支援 5x / 10x / 20x；前端配置與後端參數統一用 `scale` |
| `thumbnail` | 維持 system processor，不出現在一般使用者可排序列表，但永遠由後端附加 |

### 4.4 Pipeline 多選與排序

新版 pipeline 應復刻舊版「多選效果」：

1. 使用者選取的 processor 順序必須被保留。
2. `thumbnail` 為 system processor，自動追加到最後。
3. 前端可拖曳調整順序，後端依 `processors` array 順序執行。
4. 若 processor 回傳 list，pipeline 能處理多張圖，但 generation asset path 初期仍只保存第一張或由後續需求擴充 grid asset。
5. generation pipeline 建議預設順序：

```text
bg_remover -> alpha_trimmer -> perfect_pixel -> palette_mapper -> thumbnail
```

自由處理模式可允許：

```text
bg_remover -> alpha_trimmer -> perfect_pixel -> color_quantizer -> upscaler -> thumbnail
```

## 5. 前端重製規劃

### 5.1 產品標題

需要把一般入口的品牌明確改成 PixelForge：

| 位置 | 變更 |
| --- | --- |
| `frontend/index.html` | `<title>` 改成 `PixelForge` |
| `frontend/src/components/Layout.tsx` | API 測試面板 layout 只在 dev `/test` 使用；一般產品 header 顯示 PixelForge |
| `frontend/src/App.tsx` | 未登入畫面不再導向 `/test`，改成正式登入流程或顯示登入表單 |

### 5.2 API 測試面板 dev-only

建議加入環境旗標：

```text
VITE_ENABLE_API_TESTER=true
```

行為：

1. `import.meta.env.DEV && VITE_ENABLE_API_TESTER === "true"` 時，`/test` 才載入 `ApiTesterApp`。
2. 非 dev 或未啟用時，`/test` 回到首頁或顯示 404。
3. 主頁不顯示 API 測試面板連結。
4. README 與 `docs/功能詳細說明/api-tester.md` 註明此面板只給測試者與開發者使用。

### 5.3 復刻舊版 img_processor 前端操作

需要把舊版 `ProcessorSelector` 的核心互動搬回新前端：

1. Checkbox 多選 processor。
2. 已啟用項目可拖曳排序。
3. `perfect_pixel` 展開設定：
   - `sample_method`: `adaptive` / `center` / `majority` / `median`
   - `remove_outliers`: boolean
4. `palette_mapper` / `color_quantizer` 展開設定：
   - 模式：模板色盤 / 自動色數
   - 色數：8 / 16 / 32
   - dither 強度
5. `upscaler` 展開設定：
   - 5x / 10x / 20x
6. 當選擇模板色盤模式時，顯示色票預覽。

## 6. 額外優化建議

### 6.1 風格一致性評分

新增 `style_consistency_score`，每次生成後分析：

| 指標 | 說明 |
| --- | --- |
| 色盤命中率 | 不透明像素中落在模板色盤的比例 |
| 透明背景比例 | 背景移除後透明區域是否合理 |
| 色數 | 最終圖片 distinct color count |
| 輪廓清晰度 | alpha 邊界與高對比邊緣比例 |
| 尺寸一致性 | trim 後主體 bounding box 是否落在模板預期範圍 |

分數低於門檻時，資產仍可保存，但 UI 顯示「風格偏離」並提供一鍵重處理或重生成。

### 6.2 Reference style anchor

每個模板除了 JSON 以外，建議增加一組人工挑選的 reference sprites：

```text
assets/templates/references/forest/*.png
```

未來若支援參考圖生成或圖像編輯能力，可把 reference 作為模型輸入；目前不依賴特定 provider 時，reference 仍可作為色盤、輪廓與品質測試基準。

### 6.3 Asset lineage

每個資產應記錄：

- template key/version
- execution provider/model（僅追蹤實際呼叫，不作模板或 prompt 分支）
- raw prompt hash
- processor pipeline/version
- palette key/version
- style consistency score
- source asset id / retry source id

這能解決「同一專案後來生成的資產為什麼風格變了」的追蹤問題。

### 6.4 Style lock

新增專案級 `StyleLock`：

1. 專案選定模板與 palette version。
2. 同一專案所有 generation job 預設使用同一 template version。
3. 模板升版不影響既有專案，除非使用者明確升級。

這比單純讓使用者每次選 preset 更符合「遊戲資產生產工作流」。

### 6.5 批次生成與挑選

對 AI 不穩定性，建議不要只生成一張：

1. 同一 prompt 生成 4 張候選。
2. 每張跑相同後處理與一致性評分。
3. UI 預設推薦分數最高的一張。
4. 使用者可把其他候選封存或丟棄。

這會比調整 prompt 更有效地提升可用素材率。

### 6.6 Golden image tests

為 processor 建立 golden image 測試：

```text
backend/tests/fixtures/pixelforge/
  input/
  expected/
```

每次演算法改動都比對輸出像素、色數與 alpha bbox，避免「修 processor 造成舊素材風格漂移」。

## 7. 分階段實作計畫

### Phase 1：模板外部化

1. 建立 `assets/templates/`。
2. 定義 `schema.json`。
3. 把現有 `forest`、`dungeon`、`scifi`、`arcane_craft` 轉成 v2 JSON。
4. `StylePresetService` 改為載入模板檔並同步 DB，或以檔案為 source of truth、DB 只做查詢快取。
5. 以 `prompt_engine` 取代散落的 prompt 常數，只輸出正向 `prompt`，不輸出 `negative_prompt`。

### Phase 2：img_processor 重製

1. 建立 `_forge_shared/img_processor`。
2. 遷移現有 processors。
3. 復刻舊版 `bg_remover`、`perfect_pixel`、`color_quantizer`。
4. 新增 `palette_mapper`。
5. 補 processor 單元測試與 golden image 測試。
6. 更新 `generation_jobs` 與 `image_processing` pipeline import。

### Phase 3：前端產品化與 processor UI

1. 一般頁面移除 `/test` 連結。
2. `/test` 改成 dev-only。
3. `index.html` title 改為 PixelForge。
4. 復刻舊版 processor selector：多選、拖曳排序、展開設定、色盤預覽。
5. generation 與 image-processing 共用同一套 processor config builder。

### Phase 4：一致性評分與工作流優化

1. 加入 style consistency analyzer。
2. Asset metadata 保存模板版本、pipeline 版本與分數。
3. UI 顯示風格偏離提醒。
4. 加入批次候選與推薦挑選流程。
5. 規劃 project-level StyleLock。

## 8. 風險與取捨

| 風險 | 說明 | 建議 |
| --- | --- | --- |
| 演算法遷移造成輸出變化 | 復刻舊版 processor 後，現有素材可能與之前結果不同 | 以 template version + processor version 記錄，並用 golden tests 固定預期 |
| OpenCV / numpy 依賴增加 | 舊版演算法依賴 `cv2` 與 `numpy` | 確認 `pyproject.toml` 與 Dockerfile 內依賴，避免本機與容器不一致 |
| Prompt 縮短後模型自由度變高 | 原圖草稿可能更不「像素」 | 後處理會收斂；必要時用 reference image 或模板正向品質片段微調 |
| dev-only API tester 影響測試者 | 測試入口不再明顯 | 在 dev 環境提供小型測試者入口或文件，不給一般使用者 |

## 9. 建議優先順序

最優先做的是 **調色盤後處理與模板外部化**。這兩項直接對應 PixelForge 的核心價值：讓同一專案的美術資產保持一致。

前端 API 測試面板 dev-only 是產品化必要修正，但風格一致性的核心收益較低；可與 processor UI 一起做。批次生成、StyleLock、Reference style anchor 是第二階段產品競爭力功能，適合在基礎 pipeline 穩定後推進。
