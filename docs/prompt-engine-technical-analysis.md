# PixelForge Prompt Engine 技術分析報告

## 結論

目前的 `prompt_engine` 不建議「保留原樣微調」，但也不建議直接整個放棄成「純大語言模型自由輸出 prompt」。比較穩健的方向是：

**打掉目前固定片段串接式 PromptRenderer，重構為「混合式 Prompt Planner」。**

具體來說：

1. 保留現有模板系統中有價值的部分：模板檔案、色盤、處理器預設、版本化、`StylePreset` 同步。
2. 移除目前以 `subject_template + base + style + composition + quality` 靜態串接為主的 Prompt Engine 核心。
3. 導入類似 `/docs/generate2dsprite` 的工作流：先決定資產計畫，再生成 prompt，再用 deterministic processor 與 QC gate 檢查結果。
4. 使用大語言模型時，不讓它直接自由控制整個流程，而是讓它輸出結構化的「Prompt Plan」，再由 deterministic renderer 轉成最終 prompt。

換句話說，應該重做的是 **Prompt Engine 的決策層與拼裝方式**；不應該丟掉的是 **模板、色盤、後處理與資料保存能力**。

## 分析依據

本次檢視了目前系統已保存的 `GenerationJob.prompt`、processor config、style consistency metadata，以及 dev 容器內最近生成的樣本檔案。現有系統確實有保存生成時使用的 prompt：

- `GenerationJob.prompt`：完整實際送往生圖模型的 prompt。
- `GenerationJob.metadata.prompt_hash`：prompt hash。
- `GenerationJob.metadata.template_key` / `template_version`：模板來源。
- Asset 封存時也會把 prompt 寫入 metadata / snapshot。

抽樣資料如下。

| Job ID | Subject | Preset | Prompt Hash | Prompt 長度 | 觀察 |
|---|---|---|---|---:|---|
| `648274ae` | 光劍 | `scifi` | `892fd7402ad94546` | 1618 | bbox 佔滿 320x320，觸及四邊，但 score 仍有 91 |
| `1a82c8f2` | 光劍 | `scifi` | `892fd7402ad94546` | 1618 | 同 prompt hash，但 bbox、透明率、色數與上一張差異明顯 |
| `3a29e52e` | 光劍 | `scifi` | `892fd7402ad94546` | 1618 | 同 prompt hash，輸出尺寸與 bbox 又不同，仍有觸邊問題 |
| `341acedd` | slime with a golden crown | `arcane_craft` | `6b811ccabe30b7d9` | 1655 | processed 透明率只有 0.0112，幾乎整張不透明，背景處理失敗風險高 |

從這些資料可以得到幾個重點：

1. **同一 prompt hash 不代表穩定輸出。**  
   `光劍` 連續三次使用同一 prompt hash，但 bbox、透明率、輸出佔比差異很大。這代表目前 prompt 無法把構圖、尺度、背景、主體邊界穩定約束住。

2. **目前 prompt 太長，且約束太分散。**  
   單張靜態素材 prompt 約 1600 字元。對通用圖像模型來說，這種長 prompt 容易出現注意力稀釋：模型可能抓到「pixel art / scifi / game asset」，但忽略「magenta only / no edge crossing / no detached props」等真正對 pipeline 重要的硬規則。

3. **style consistency 分數目前不足以代表可用性。**  
   `648274ae` 的 style score 是 91，但 bbox 是 full canvas。對像素資產來說，觸邊與滿版通常是嚴重失敗，但目前分數仍偏高，表示 QC 指標還不夠貼近產品品質。

4. **後處理正在掩蓋 prompt 問題。**  
   palette hit rate 幾乎都是 1.0，這是因為 `palette_mapper` 強制映射色盤。這能保證色彩統一，但不能證明 prompt 產出了正確構圖、正確主體、乾淨背景或可用 silhouette。

5. **generate2dsprite 的效果好，不只是因為 prompt，而是因為完整工作流。**  
   `/docs/generate2dsprite` 的核心不是單一 prompt 模板，而是：
   - 明確 infer asset plan。
   - 嚴格指定 sheet/cell/scale/containment。
   - 使用 `#FF00FF` chroma key。
   - 後處理切格、對齊、component 過濾。
   - QC 後必要時重跑或重生。

目前 PixelForge 只吸收了其中一部分 prompt 規則，還沒有完整吸收「計畫 → 生成 → 處理 → QC → 重試」這個閉環。

## 現有 Prompt Engine 的問題

### 1. 固定片段串接無法理解素材語意

目前 prompt 是固定順序拼接：

1. subject template
2. base
3. view directive
4. mode directive
5. style
6. palette directive
7. composition
8. containment
9. quality
10. background
11. forbidden

這對「所有 subject 都同質」的情況勉強可用，但 PixelForge 的 subject 實際上差異很大：

- `光劍` 是細長武器，適合 side/profile/diagonal composition，不適合泛用 top-down footprint。
- `slime with a golden crown` 是 creature/character-like subject，和 prop icon 的構圖需求不同。
- spell / projectile / impact / prop / equipment 的 containment 方式不同。

固定模板無法推論這些差異，只會把所有素材塞進同一組句型。

### 2. 規則太多但優先級不明

目前 prompt 同時要求：

- single asset
- top-down
- hard surface silhouette
- strict 8-color
- no detached circuits/sparks
- no glow/beam/trail crossing edge
- controlled glow attached to object
- magenta background
- no background items

這些不是全部錯，但缺少優先級與素材特化。通用圖像模型看到過多要求時，常會選擇遵守其中一部分，而不是全部遵守。

### 3. Prompt 無法取代品質控制

例如：

- prompt 要求不要觸邊，但結果仍 bbox 觸邊。
- prompt 要求 magenta background，但 raw 圖仍可能不是乾淨 magenta。
- prompt 要求單一主體，但模型仍可能產生裝飾碎片。

這表示 prompt 只能提高成功率，不能當作 workflow 的唯一控制點。

### 4. 目前模板混合了太多責任

模板同時包含：

- 美術風格描述
- prompt 組裝片段
- 色盤
- processor 預設
- 背景策略
- quality/containment 規則

這會導致模板越改越長，也讓 Prompt Engine 難以維護。模板應該負責「風格」，而不是負責「理解使用者要生成什麼素材」。

## 三條路線比較

### 路線 A：精簡 Prompt Engine

做法：

- 保留 deterministic prompt。
- 大幅縮短 prompt。
- 每種 template 只保留最必要的句子。
- 把規則壓到 500～800 字元內。

優點：

- 低成本、快。
- 行為可預測。
- 容易測試。
- 不依賴額外 LLM。

缺點：

- 仍然無法理解 subject 語意。
- 對於「光劍」「史萊姆」「投射物」「爆炸」「角色」這種不同類型，仍會套同一種句型。
- 無法達到 generate2dsprite 那種 agent-like 的規劃能力。

適合用途：

- 作為 fallback。
- 作為無 LLM 時的最低可用模式。
- 作為 Prompt Planner 失敗時的備援。

技術判斷：

**可以做，但不足以成為最終方案。**

### 路線 B：放棄 Prompt Engine，完全改用大語言模型補 prompt

做法：

- 使用 LLM 讀取 subject、style template、generate2dsprite 規則。
- 直接輸出最終 prompt。
- PixelForge 只保存 prompt 並送生圖。

優點：

- 彈性最高。
- 能根據 subject 做語意推論。
- 最接近 generate2dsprite skill 的 prompt writing 行為。

缺點：

- 成本與延遲增加。
- 非決定性更高。
- 難以測試 prompt 是否符合 schema。
- LLM 可能漏掉必要 processor/QC metadata。
- 若未加約束，很容易把系統變成不可控 prompt 黑箱。

適合用途：

- 研究模式。
- 高價值單張生成。
- 需要多 asset bundle / animation sheet 的進階 workflow。

技術判斷：

**不建議直接純 LLM 化。**  
這會把目前的問題從「固定模板太笨」變成「LLM prompt 黑箱不可控」。

### 路線 C：混合式 Prompt Planner

做法：

1. 使用 deterministic rules 決定基礎 schema。
2. 可選使用 LLM 產生結構化 Prompt Plan。
3. 系統驗證 Prompt Plan 是否符合 schema。
4. deterministic renderer 把 Prompt Plan 渲染成最終 prompt。
5. 後處理與 QC gate 檢查結果。
6. QC 失敗時重試、調整 prompt 或要求再生成。

Prompt Plan 應該是 JSON，而不是自由文字。例如：

```json
{
  "asset_type": "prop",
  "action": "single",
  "view": "side",
  "sheet": "single",
  "subject_identity": "a sci-fi energy saber / lightsaber weapon",
  "silhouette_plan": "long diagonal blade with compact handle, readable from small icon size",
  "containment_rules": [
    "entire weapon fits inside canvas",
    "blade tip does not touch edge",
    "no detached sparks outside silhouette"
  ],
  "background": {
    "type": "chroma_key",
    "color": "#FF00FF"
  },
  "style_binding": {
    "template": "scifi",
    "palette_key": "scifi-8"
  },
  "renderer_notes": [
    "use compact prompt",
    "prioritize containment over decorative glow"
  ],
  "qc_expectations": {
    "max_edge_touch": false,
    "foreground_ratio_range": [0.08, 0.55],
    "requires_magenta_background": true
  }
}
```

優點：

- 有 LLM 的語意推論能力。
- 保留 deterministic validation。
- 可以測試、快取、版本化。
- 可以清楚記錄 prompt 為什麼這樣生成。
- 可以接 generate2dsprite 的 asset plan / sheet plan / QC plan。

缺點：

- 實作量比 A 大。
- 需要設計 Prompt Plan schema。
- 需要處理 LLM 不合規輸出的修復與 fallback。

技術判斷：

**這是最推薦路線。**

## 建議架構

### 1. 將 Prompt Engine 拆成三層

#### Prompt Planner

負責決定：

- asset type：prop / creature / character / projectile / impact / fx
- action：single / idle / cast / attack / impact
- view：topdown / side / 3/4
- sheet：single / 1x4 / 2x2 / 2x3 / 4x4
- composition plan
- containment plan
- background strategy
- QC expectations

Planner 可有兩個實作：

- `DeterministicPromptPlanner`
- `LLMPromptPlanner`

#### Prompt Renderer

只負責把合法 Prompt Plan 渲染成 prompt。

Renderer 不應該做語意推論。

#### Prompt QC / Result Evaluator

負責判斷 raw / processed 是否可用：

- raw 是否有足夠 magenta 背景。
- processed bbox 是否觸邊。
- foreground ratio 是否過大或過小。
- transparent ratio 是否合理。
- distinct colors 是否符合色盤。
- grid mode 是否有正確 cell。
- 多 frame 是否 shared scale。

### 2. 模板應該退回「風格資料」

模板應保留：

- palette
- material vocabulary
- shape language
- style adjectives
- forbidden decoration types
- preferred outline / contrast
- processor defaults

模板不應該負責：

- 判斷光劍應該 side-view 還是 top-down。
- 判斷史萊姆是 creature-like 還是 prop。
- 判斷 projectile 是否要 1x4。
- 判斷 detached FX 是否可接受。

這些應該是 Prompt Planner 的工作。

### 3. 保留簡短 deterministic fallback

當 LLM 不可用或失敗時，使用短 prompt：

```text
Single 2D pixel-art game sprite. Subject: {subject}. {asset_type/view hint}.
Centered, full object visible, crisp outline, compact 8-color palette.
Solid flat magenta #FF00FF background only, no gradients, no shadow.
Leave clear magenta margin on all sides; nothing touches the canvas edge.
No text, no UI, no labels, no extra background props.
Style: {template style summary}.
```

這比目前 1600 字左右的 prompt 更可能被模型完整遵守。

### 4. 導入多候選與自動挑選

generate2dsprite 的品質來自「生成後 QC」，PixelForge 也應該做：

1. 同一 Prompt Plan 生成 2～4 張候選。
2. 對每張跑 QC。
3. 選擇不觸邊、背景乾淨、前景比例合理、色盤一致性高的結果。
4. 只有全部失敗時才回傳最佳失敗結果與警告。

這會比單次生成可靠很多。

## 對目前資料的具體判斷

### `光劍` 樣本

三筆 `光劍` 使用同一 prompt hash：`892fd7402ad94546`。

問題：

- 同 prompt 結果差異明顯。
- bbox 多次觸及左邊或全畫布。
- 對 `光劍` 這種長條物，top-down directive 不合理。
- prompt 沒有主動推論「長條武器應以 diagonal/side profile 擺放，blade tip 不可觸邊」。
- prompt 太長，真正重要的 containment 可能被模型忽略。

判斷：

**這不是單純修某一句 prompt 可以解決的問題。**  
它需要 asset-aware planner。

### `slime with a golden crown` 樣本

`arcane_craft` 的 slime 樣本 processed 透明率只有 0.0112，bbox 滿版。

問題：

- 對 creature-like subject，prop icon 模板可能不合適。
- 若 raw 背景沒有遵守 chroma key，magenta 去背無法工作。
- 現有 QC 沒有把「幾乎整張不透明」視為硬失敗。

判斷：

**Prompt Engine 需要先分類 subject，再選不同構圖與背景策略。**

## 是否應該打掉重做

### 應該打掉的部分

- 固定片段式 `PromptRenderer.render()` 主導 prompt 的方式。
- 以 style template 直接決定完整 prompt 的方式。
- 把所有 subject 都當成 single prop icon 的假設。
- 只靠 prompt 要求背景乾淨、主體不觸邊的策略。
- 只用 style score / palette hit rate 判斷結果好壞。

### 不應該打掉的部分

- `assets/templates` 外部模板化。
- `TemplateLoader` 與 template version。
- 色盤 JSON 與 `palette_mapper`。
- processor config 隨模板保存。
- `GenerationJob.prompt` / metadata 保存。
- 後處理 pipeline。

### 最終判斷

**應該重做 Prompt Engine 的核心，但不是整個模板功能砍掉。**

建議把它升級為：

```text
Template System
  -> Prompt Planner
      -> Deterministic fallback planner
      -> LLM planner
  -> Prompt Plan Validator
  -> Prompt Renderer
  -> Image Generation
  -> Processor Pipeline
  -> QC Evaluator
  -> Retry / Candidate Selection
```

## 建議實作階段

### Phase 1：先止血，精簡 deterministic prompt

目標：

- prompt 長度降到 500～800 字。
- prompt 不再重複說明。
- 對常見 asset type 加 deterministic heuristic：
  - `sword`, `blade`, `gun`, `staff` -> prop weapon, side/diagonal view
  - `slime`, `dragon`, `monster` -> creature, 3/4 or side
  - `fireball`, `orb`, `projectile` -> projectile
  - `explosion`, `impact`, `burst` -> impact/fx

必要變更：

- 新增 `asset_type` 欄位或在 metadata 存推論結果。
- PromptRenderer 改吃 `PromptPlan`，不要直接吃 template prompt dict。
- Style template 只提供 style snippets。

### Phase 2：加入 QC hard gates

把以下情況判定為失敗或警告：

- bbox touch edge。
- foreground ratio 太高，例如 `> 0.75`。
- foreground ratio 太低，例如 `< 0.03`。
- raw magenta compliance 太低，但使用 magenta mode。
- processed 幾乎全不透明。
- grid mode cell 數不正確。

這一步非常重要。沒有 QC，prompt 再好也無法保證工作流穩定。

### Phase 3：導入 LLM Prompt Planner

LLM 不直接輸出最終 prompt，而是輸出 `PromptPlan` JSON。

輸入：

- subject
- selected style template
- generate2dsprite rules 摘要
- user selected mode/view
- existing processor capabilities

輸出：

- asset_type
- view
- composition
- scale/containment rules
- background strategy
- prompt clauses
- QC expectations

系統再 validate schema，失敗則 fallback deterministic planner。

### Phase 4：多候選生成與自動挑選

對高價值輸出可啟用：

- `n=2~4`
- 每張跑 processor + QC
- 選最好的入庫
- 保存 rejected candidates metadata，方便未來分析

### Phase 5：擴展到 generate2dsprite 的 sheet/bundle 能力

逐步支持：

- 1x4 projectile
- 2x2 impact
- 2x3 cast
- 4x4 player sheet
- unit bundle / spell bundle

這時 PixelForge 才會真正接近 generate2dsprite skill 的價值。

## 最小可行重構方案

如果要控制風險，建議下一步不要一次做 LLM。先做：

1. 新增 `PromptPlan` dataclass。
2. 新增 `DeterministicPromptPlanner`。
3. 重寫 renderer，輸出短 prompt。
4. 把模板 JSON 改為 style-only。
5. QC 加入 hard gates。
6. UI 顯示：
   - inferred asset type
   - prompt plan
   - final prompt
   - QC result

完成後再加 LLM planner。

## 推薦決策

**不要直接放棄 Prompt Engine。**  
應該放棄的是目前「固定文字片段堆疊」的實作。

最佳方案是：

1. **短期：精簡 deterministic prompt + 加 QC hard gates。**
2. **中期：把 Prompt Engine 重構成 Prompt Planner / Renderer / Evaluator。**
3. **長期：加入 LLM Prompt Planner，使用 generate2dsprite 規則做語意補完，但輸出必須是結構化 plan。**

這樣可以同時得到：

- generate2dsprite 的高品質 prompt planning 能力。
- PixelForge 需要的模板可控性。
- 可測試、可回放、可分析的生成流程。
- 不會把系統變成不可控的大語言模型黑箱。

