# generate2dsprite 與 PixelForge 產出比較與優化方向

## 用途

這份文件整理 `docs/generate2dsprite` skill 與目前 PixelForge Agent / Generation pipeline 的差異，重點不是比較哪邊「prompt 比較好」，而是說明：

1. `generate2dsprite` 為什麼更容易產出整潔、完整、可直接投入遊戲使用的素材。
2. PixelForge 目前哪些地方已經接近。
3. PixelForge 後續最值得優先補強的方向。

這份文件可作為後續調整 Agent、生圖 Prompt、後處理、QC 與重試策略時的快速參考。

---

## 一句話結論

`generate2dsprite` 品質更穩的主因，不是它有一條神奇 prompt，而是它把流程做成：

**資產規劃 → 強約束 prompt → raw image 生成 → deterministic processor 整理 → QC gate → 必要時重跑**

PixelForge 目前已經具備：

- Agent 對話式規劃
- 候選圖評估
- 去背 / perfect pixel / upscaler 後處理
- 部分自動返工

但在以下幾點仍明顯落後：

- sheet-aware 規劃
- 多幀一致性控制
- deterministic sheet processor
- sheet-level QC
- 區分 reprocess 與 regenerate 的閉環

---

## 比較總表

| 比較維度 | generate2dsprite | PixelForge 現況 | 對最終產出的影響 |
| --- | --- | --- | --- |
| 資產規劃粒度 | 先決定 `asset_type / action / sheet / bundle`，並選最小可用輸出 | 會規劃素材清單，但偏 item 導向，較少明確 sheet 結構 | PixelForge 較容易把應拆開的內容塞進同一輪生成 |
| Prompt 約束強度 | 明確要求 exact grid、same bbox、same scale、no edge crossing、magenta margin | 已有 centered / margin / flat magenta，但對 sheet 與 cell 結構約束較弱 | 多幀動畫或技能素材較容易比例漂移、裁切、越界 |
| 背景規則 | `#FF00FF` 是硬規格，並以此作 chroma-key workflow 前提 | 現在也強調 flat magenta，且去背邏輯已補強粉紫 / 漸層底 | 單張資產背景穩定度已提升，但 raw 輸出仍可能不完全遵守 |
| 後處理能力 | 去背、切格、裁切、主體抽取、共享縮放、對齊、透明 sheet、GIF | 目前主力為 `bg_remover + perfect_pixel + upscaler + thumbnail` | PixelForge 能清單張，但對 sheet 整理能力仍不足 |
| 一致性控制 | `shared_scale`、`align=center/bottom/feet`、`component_mode=largest` | 尚無等價的 sheet-level 對齊與共享尺度流程 | 多幀素材重心、大小與留白較容易不一致 |
| QC 粒度 | 直接檢查 frame 是否 touching edge、component 是否穩定、sheet 是否 coherent | 目前 QC 以 foreground ratio、edge touch、style score 為主，偏單圖 | 能擋部分壞圖，但未真正保證動畫可用性 |
| 重跑策略 | 可先換 processor 參數重新整理，不行再重生 raw image | 目前已有候選圖 ranking 與去背返工，但重試粒度較粗 | 成本與成功率都不如閉環工作流 |
| 輸出物 | raw、clean、transparent sheet、frame PNG、GIF、pipeline meta | 目前以最終 asset 為主，中間產物保留較少 | 開發者除錯、回歸比對與人工挑選難度較高 |

---

## generate2dsprite 為什麼比較容易出乾淨圖

## 1. 它先縮小問題，再叫模型畫圖

`generate2dsprite` 先推斷：

- `asset_type`
- `action`
- `sheet`
- `bundle`
- `anchor`
- `margin`

然後只選「最小但有用」的輸出。例如：

- 法術素材會拆成 `cast + projectile + impact`
- 可控角色會拆成 `player_sheet`
- projectile 會偏向 `1x4`
- impact 會偏向 `2x2`

這讓模型不用一次同時處理太多不同語義的內容，成圖自然更穩。

## 2. 它寫的是版面規格，不是泛用美術描述

`generate2dsprite` 的 prompt 規則會反覆強調：

- 背景必須是 **100% flat `#FF00FF`**
- **exact grid count**
- **no borders / no labels / no UI**
- **same identity / same bounding box / same scale**
- **任何 body part / effect 都不能越出 cell**
- **四邊保留 magenta margin**

這些規則直接約束幾何結構與素材可用性，而不是只描述美術風格。

## 3. 它對不同模式寫不同 prompt

它不把所有資產套進同一組模板，而是依模式分別寫：

- player sheet
- projectile
- impact
- cast
- combat
- walk

甚至會明確寫 row / column 各代表什麼，這會大幅降低動畫 sheet 變成插畫的風險。

## 4. 它把 image model 當 raw generator，而不是最終成品機

`generate2dsprite` 預設假設：

- raw image 只是中間產物
- processor 負責把它整理成工程可用輸出
- 如果 processor 後仍不合格，就重跑 processor 或重生成 raw

這種設計比「一次畫到好」穩很多，也更適合遊戲素材流程。

## 5. 它有 deterministic processor 幫忙整理

它的本地處理腳本會做：

- magenta cleanup
- trim border
- clean edges
- connected component 分析
- largest component 保留
- shared scale
- center / bottom / feet 對齊
- frame export
- transparent sheet export
- transparent GIF export
- pipeline metadata 輸出

這些行為會把「接近可用但不夠整齊」的 raw 圖整理成一致、乾淨、可交付的 sprite。

## 6. 它把 QC 當 gating，不是只做評分

它不只是給分，而是會明確檢查：

- frame 是否 touching edge
- scale 是否漂移
- detached effects 是否變成雜訊
- animation 是否 still coherent

如果不合格，就直接換 processor 參數或重生成。這是它比純 prompt 流程更強的地方。

---

## PixelForge 目前已具備的優點

目前 PixelForge 其實已經有幾個很重要的基礎能力：

1. **Agent 對話式規劃**
   - 能先理解使用者需求，再決定要生成什麼。
   - 已支援 follow-up、直接操作意圖、部分失敗重試。

2. **候選圖評估**
   - 有 `evaluate_candidate()`，會看 foreground ratio、edge touch、style score。

3. **後處理管線**
   - 已有 `bg_remover`、`perfect_pixel`、`upscaler`、`thumbnail`。

4. **去背返工**
   - 現在已能針對去背後仍殘留整片背景的 case 進行自動返工。

5. **任務追蹤與結果保存**
   - 已能保存 prompt、processor config、job metadata、asset 封存資料。

也就是說，PixelForge 缺的不是「從零開始」，而是還沒把這些能力串成 generate2dsprite 那種完整閉環。

---

## PixelForge 目前的主要缺口

## 1. 缺少 sheet-aware plan

PixelForge 現在比較像是：

- 先決定要哪些 item
- 每個 item 當成一張獨立素材

但對遊戲 sprite 來說，常常真正需要的是：

- 一張 `1x4 projectile`
- 一張 `2x2 impact`
- 一張 `4x4 player_sheet`
- 一個 `cast + projectile + impact` spell bundle

如果沒有先在 plan 層就表達這些結構，後面很難靠 prompt 補救。

## 2. 缺少 sheet-level processor

目前的後處理器多半是單圖導向：

- 去背
- 完美像素
- 放大

但還沒有：

- 切格
- 每格抽主體
- 多格共享縮放
- 每格重心對齊
- largest component 模式
- sprite sheet 透明導出

因此在多幀或多格場景下，PixelForge 仍然偏弱。

## 3. QC 仍偏單圖導向

目前 QC 重點在：

- foreground ratio
- edge touch
- style score

這對單張素材有幫助，但還不夠檢查：

- 多格之間 bbox 是否飄移
- frame scale 是否一致
- detached debris 是否破壞動畫可讀性
- actor 腳底是否對齊

## 4. 重試策略還不夠分層

目前 PixelForge 比較接近：

- 候選圖評分
- 若失敗，換 config 或重試生成

但理想上應該拆成：

1. raw image 已接近可用 → **先換 processor 參數 reprocess**
2. raw image 結構本身錯誤 → **再 regenerate**

這會比一律重新生成更便宜、更穩。

## 5. 中間產物與 metadata 還不夠完整

若要做品質迭代，理想上應保留：

- raw image
- raw-clean
- transparent sheet
- frame PNGs
- prompt-used
- pipeline-meta
- QC summary

目前 PixelForge 有 metadata 基礎，但可觀察性仍弱於 generate2dsprite。

---

## PixelForge 優化方向

## 優先度 A：應優先做

### A1. 加入 sheet-aware asset plan

讓 Agent 或 planner 可以直接輸出：

- `sheet_shape`
- `frame_count`
- `frame_labels`
- `bundle_structure`
- `anchor`
- `margin_policy`
- `effect_policy`

例如：

- `projectile` 預設 `1x4`
- `impact` 預設 `2x2`
- `player_sheet` 預設 `4x4`
- `spell_bundle` 預設拆成 `cast + projectile + impact`

**收益：** 直接降低 prompt 與生成階段的歧義。

### A2. 實作 deterministic sheet processor

建議新增一組 processor / service，支援：

- grid split
- frame crop
- connected component filtering
- `component_mode=largest|all`
- `shared_scale`
- `align=center|bottom|feet`
- transparent sheet export
- per-frame PNG export
- GIF export

**收益：** 這會是最接近 `generate2dsprite` 品質穩定度的關鍵能力。

### A3. 將 containment 規則升級為硬約束

在 prompt layer 明確加上：

- exact grid shape
- same bounding box in all frames
- same pixel scale in all frames
- leave margin on all sides
- nothing crosses cell edges
- detached effects must stay grouped near the main subject

**收益：** 對動畫與 bundle 產出最直接。

### A4. 實作 sheet-level QC gate

建議新增 QC 指標：

- `edge_touch_frames`
- `bbox_drift`
- `scale_drift`
- `anchor_drift`
- `detached_component_count`
- `coherence_score`

並在超出門檻時：

- 先嘗試 reprocess
- 再必要時 regenerate

**收益：** 可真正把「像圖但不能用」的結果擋掉。

---

## 優先度 B：第二階段補強

### B1. 區分 reprocess 與 regenerate

把重試流程拆成兩層：

1. **processor retry**
   - 換 `component_mode`
   - 換 `shared_scale`
   - 換 `align`
   - 換 trim / edge clean / padding

2. **generation retry**
   - 當 raw 結構本身錯時才重新生圖

### B2. 保存更多中間產物

建議每個可疑或重要 job 保存：

- origin
- processed
- qc image
- raw-clean
- transparent sheet
- frame list
- pipeline meta

### B3. 不同 asset 類型套不同預設

例如：

- projectile / fx → `align=center`
- ground actor → `align=feet`
- detached sparks 多 → `component_mode=largest`
- bundle → `shared_scale=true`

---

## 優先度 C：第三階段

### C1. 升級 prompt planner

目前 PixelForge 的 prompt 已經比以前好，但若要真正接近 `generate2dsprite`，應該讓 planner：

- 先產生結構化 plan
- 再由 renderer 產出最終 prompt
- 而不是只靠固定片段拼接

### C2. 對 bundle 做多資產協調

例如 spell bundle 應共享：

- 色彩語言
- effect 形狀語言
- 尺度邏輯
- 動作邏輯

這樣 cast / projectile / impact 才會看起來像同一套技能。

---

## 建議的實作順序

若後續真的要讓 PixelForge 往 `generate2dsprite` 靠近，建議順序如下：

1. **先補 sheet-aware plan**
2. **再補 deterministic sheet processor**
3. **再補 sheet-level QC 與 reprocess / regenerate 分層**
4. **最後再升級 prompt planner**

原因很簡單：

- prompt 再好，也救不了錯誤的 sheet 結構
- processor 與 QC 補起來後，品質提升會比單純調 prompt 更大
- 先把閉環打通，再追求語意規劃細緻度，成本效益最好

---

## 下次作業建議直接檢查的項目

下次若要往這個方向實作，可先從以下 checklist 開始：

### 規劃層

- Agent manifest 是否能輸出 `sheet_shape / frame_count / bundle_structure`
- 是否能區分 `single_asset` 與 `spell_bundle / unit_bundle`

### Prompt 層

- 是否明確寫出 exact grid、same bbox、same scale、no edge crossing
- 是否依 `projectile / impact / player_sheet` 使用不同 prompt 模式

### Processor 層

- 是否已有 grid split
- 是否已有 per-frame crop
- 是否已有 `shared_scale`
- 是否已有 `align=feet|bottom|center`
- 是否已有 `component_mode=largest`

### QC 層

- 是否能判定 frame edge touch
- 是否能檢查 bbox / scale drift
- 是否能產出可追蹤 metadata
- 是否能先 reprocess 再 regenerate

---

## 相關檔案

- `docs/generate2dsprite/SKILL.md`
- `docs/generate2dsprite/references/prompt-rules.md`
- `docs/generate2dsprite/references/modes.md`
- `docs/generate2dsprite/scripts/generate2dsprite.py`
- `docs/prompt-engine-technical-analysis.md`
- `backend/modules/agent_generation/services.py`
- `backend/modules/generation_jobs/services.py`
- `backend/modules/_forge_shared/prompt_engine/evaluator.py`

