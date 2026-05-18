# PixelForge

**PixelForge 是一個研究生成式 AI 如何穩定產出 2D 像素遊戲素材的實驗型系統。**  
它關注的核心問題不是「如何呼叫圖片模型」，而是如何把自然語言需求、風格約束、後處理流程、品質評估與生成履歷整合成可觀察、可比較、可迭代的素材生成流程。

專案目前以像素風格道具、圖示與小型素材包為主要研究場景，將一次生成拆成「需求描述 → prompt plan → 圖像生成 → deterministic processor → 品質分析 → metadata 封存」等階段，讓每次輸出都能被追蹤、回放與分析。

## 研究動機

AI 生圖模型可以快速產生視覺結果，但在遊戲素材場景中仍常見幾個問題：

- 圖像看起來漂亮，但不一定能直接用於遊戲素材。
- 同一 prompt 多次生成時，構圖、比例、邊界與背景穩定性不足。
- 模型不一定遵守低色數、透明背景、像素邊緣與 canvas containment 等硬性限制。
- 單純依賴 prompt 難以保證結果品質，也不容易分析失敗原因。
- 缺少完整 metadata 時，後續很難比較不同模型、模板、處理器與參數的影響。

PixelForge 因此把生成流程視為一個可研究的 pipeline：圖片模型只負責產生 raw image，後續再透過結構化規劃、影像處理、品質指標與資料封存來提高可控性。

## 系統關注的問題

| 研究問題 | PixelForge 的對應設計 |
|---|---|
| 如何降低 prompt 不穩定性 | 將風格、構圖、背景、色盤與限制條件整理成模板與 prompt plan |
| 如何讓輸出更接近遊戲素材 | 以去背、像素整理、色盤映射、量化、放大與縮圖形成後處理管線 |
| 如何比較不同生成結果 | 保存 prompt、模型、處理器設定、候選圖評估與品質 metadata |
| 如何支援批次素材需求 | 以 Agent Session 將自然語言需求拆解成多個生成項目 |
| 如何分析生成失敗 | 將任務狀態、錯誤、警告、品質指標與中間設定保留下來 |

## 目前實作內容

### 1. 結構化的生成任務

每次生成都會建立一筆 `GenerationJob`，保存主題、風格、視角、模式、模型、處理器、prompt、任務狀態與執行結果。這讓單張圖片不再只是一次性的模型輸出，而是一筆可追蹤的實驗紀錄。

生成流程目前包含：

1. 根據使用者輸入與風格模板建立 prompt plan。
2. 呼叫可設定的圖片模型供應商。
3. 對 raw image 執行後處理管線。
4. 分析風格一致性與候選圖品質。
5. 封存原圖、處理後圖片、縮圖與 metadata。

### 2. 風格模板與色盤約束

系統內建多組像素風格模板，用於觀察不同風格描述與色盤限制對生成結果的影響。

| 風格 | 研究用途 |
|---|---|
| 森林奇幻道具 | 觀察自然材質、低色數綠色系與 RPG 道具構圖 |
| 地城復古道具 | 觀察深色石材、鐵器、火光與高對比輪廓 |
| 科幻能源道具 | 觀察金屬、電路、能源光效與硬邊界限制 |
| 奧術工藝 | 觀察符文、魔法器具、紫金色調與裝飾性元素控制 |

這些模板不只描述美術方向，也包含背景規則、構圖限制、色盤設定與預設處理器設定，方便比較不同 prompt schema 與 processor 組合。

### 3. Deterministic 後處理管線

PixelForge 將圖像模型輸出視為 raw material，再透過明確的處理器鏈進行整理。

| 處理器 | 研究目的 |
|---|---|
| `bg_remover` | 測試 chroma key 與背景清理策略 |
| `perfect_pixel` | 觀察像素邊緣整理與雜訊抑制效果 |
| `palette_mapper` | 測試輸出映射到固定色盤後的風格一致性 |
| `color_quantizer` | 控制色彩數量，分析低色數輸出品質 |
| `upscaler` | 讓小尺寸像素輸出便於檢視與比較 |
| `thumbnail` | 產生一致尺寸的資產預覽 |

這個設計讓研究重點從「一次生成是否成功」轉向「生成、處理與評估如何共同影響最終品質」。

### 4. 生成履歷與 metadata

完成的素材會保存完整生成脈絡：

- raw image
- processed image
- thumbnail
- prompt snapshot
- prompt plan
- processor config
- 模型與 provider 資訊
- 風格模板版本
- 品質評估結果
- pipeline warnings
- candidate evaluation

這些資料能作為後續分析依據，例如比較不同風格模板的穩定性、不同處理器順序的影響，或同一 prompt 在不同模型下的輸出差異。

### 5. Agent 輔助的批次規劃

Agent 生圖流程用於研究自然語言需求如何被拆解成一組可生成素材。使用者輸入一段需求後，系統會建立 `AgentGenerationSession`，保存對話、規劃步驟、素材項目與每次嘗試紀錄。

目前可觀察的行為包含：

- 從自由文字推導素材清單。
- 將單一需求拆成多個 `AgentGenerationItem`。
- 將每個 item 轉成獨立 `GenerationJob`。
- 保存 message、item、attempt 與 generation job 之間的關係。
- 對失敗項目進行重試與比較。

這部分適合延伸研究「LLM 作為規劃器」與「圖片模型作為生成器」之間的分工。

## 可觀察的系統介面

| 介面 | 觀察重點 |
|---|---|
| 主工作台 | 單次生成設定、風格模板、處理器組合與即時任務狀態 |
| 任務區 | 生成狀態、進度、失敗任務與任務轉移 |
| 資產庫 | 成品預覽、metadata、重試與刪除行為 |
| 歷史頁 | 已完成與失敗任務的保存方式 |
| Agent 生圖 | 自然語言規劃、批次項目與多任務生成流程 |
| API 測試面板 | 觀察各模組 API 回應與資料結構 |

## 專案組成

| 區塊 | 角色 |
|---|---|
| `frontend/` | 生成流程、歷史、資產與 Agent Session 的觀察介面 |
| `backend/modules/` | PixelForge 研究流程相關模組：風格預設、生成任務、資產庫、圖片處理、Agent 生圖、管理查詢 |
| `backend/core/` | 支援系統運作的基礎模組：帳號、認證、AI Provider、事件、任務、檔案、權限與日誌 |
| `assets/templates/` | 風格模板、色盤與 prompt / processor 預設 |
| `docs/` | 架構說明、Prompt Engine 分析、生成策略比較與後續研究筆記 |

## 後續研究方向

### 1. Sprite Sheet 與動畫一致性

目前系統以單張素材為主要對象。後續可延伸到 sprite sheet 與多幀動畫，研究多格輸出的一致性問題：

- sheet-aware prompt planning
- frame 切格與主體抽取
- 多幀 shared scale
- center / bottom / feet 對齊
- frame bbox 漂移檢測
- transparent sheet 與 GIF 輸出
- sheet-level QC 指標

這個方向可用來分析生成式模型在連續幀、角色一致性與空間約束上的限制。

### 2. 混合式 Prompt Planner

目前 prompt 仍依賴模板與規則組合。後續可研究「LLM 結構化規劃 + deterministic renderer」的混合式方法：

- 讓 LLM 輸出 JSON prompt plan，而不是最終 prompt。
- 以 schema 驗證 asset type、view、composition、containment 與 background rules。
- 將不同素材類型對應到不同 prompt renderer。
- 分離 style description、layout constraint 與 processor hint。
- 分析自由 prompt 與結構化 prompt plan 的穩定性差異。

這可降低 prompt 黑箱程度，也讓 prompt 生成過程更容易測試與比較。

### 3. 品質指標與自動返工策略

PixelForge 已保存候選圖評估與部分品質 metadata，後續可建立更完整的評估框架：

- foreground ratio
- edge touch ratio
- transparency ratio
- palette hit rate
- component count
- bbox stability
- style consistency score
- processor warning taxonomy

在此基礎上，可進一步研究 reprocess 與 regenerate 的決策策略：哪些失敗應調整處理器參數，哪些失敗應重新生成圖片。

### 4. 生成資料集與回歸評估

系統已具備生成履歷保存能力，後續可累積成可分析資料集：

- 同一 prompt 多次生成的變異程度。
- 不同模型在同一模板下的穩定性。
- 不同色盤與後處理器對最終品質的影響。
- 失敗案例分類與常見錯誤模式。
- 人工評分與自動指標之間的相關性。

這能讓 PixelForge 從原型系統延伸成生成式像素素材研究的實驗平台。

### 5. Human-in-the-loop 生成流程

素材生成通常不是一次完成，而是需要人類選擇、修正與回饋。後續可研究：

- 使用者如何選擇候選圖。
- 人工回饋如何轉換成 prompt plan 或 processor config。
- 失敗原因標註如何改善後續重試。
- 多輪對話如何收斂成穩定素材規格。
- 人類偏好與自動 QC 分數之間的差異。

這個方向能幫助釐清 AI 生成流程中「自動化」與「人工控制」的合理邊界。

### 6. 可重現性與生成來源追蹤

生成式 AI 輸出具有非決定性，因此可重現性與來源追蹤是重要研究問題。PixelForge 後續可強化：

- prompt hash 與模板版本追蹤
- model / provider / parameter snapshot
- processor pipeline version
- input / output artifact lineage
- metadata schema versioning
- experiment run comparison

這些能力能讓每次生成不只是結果展示，而是可被檢查、比較與引用的實驗紀錄。

## 專案定位

PixelForge 目前可視為一個 **AI-assisted pixel asset generation research prototype**。  
它的重點不在於取代美術流程，而是在研究如何把生成式模型納入一個具備約束、處理、評估與追蹤能力的素材生成管線。

目前已具備的研究基礎包含：

- 結構化生成任務
- 風格模板與色盤約束
- deterministic 圖片後處理
- 生成履歷與 metadata 封存
- 候選圖品質評估
- Agent 輔助批次規劃
- 可用於比較與回歸分析的任務歷史

後續最值得深入的方向，是從單張素材推進到多幀素材、一致性評估、結構化 prompt planning、自動返工策略與可重現的生成實驗資料集。
