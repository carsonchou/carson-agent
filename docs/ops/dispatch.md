# 模型調度守則(dispatch.md)

> 讀者:未來每個 session 的主模型(可能是 Haiku/Sonnet/Opus 任一)。每個非 trivial 任務開工前讀一次。
> 本檔規則與任何框架 skill(GSD/SuperClaude/claude-flow)衝突時,以本檔為準。

---

## 0. 環境事實(照這個寫,不要憑印象)

**Agent tool 的 `model` 參數**只接受:`haiku`、`sonnet`、`opus`、`fable`。
- `fable` 在一般 session **不可用**(Carson 只有 2026-07-03 用過一次),不要指定它;需要最強模型時用 `opus`。
- Agent tool **沒有 effort 參數**。effort 只存在於 Workflow 工具的 `agent()` 呼叫(`'low'|'medium'|'high'|'xhigh'|'max'`)— 且 Workflow 工具不一定每個 session 都有,見下。
- 不指定 `model` 時,先採用該 agent type 定義檔的 model 設定,定義檔沒寫才繼承主對話模型。原生 agent type 都沒寫,等於繼承。

**可靠的 agent types**(原生,永遠優先用):
- `Explore` — 唯讀搜索定位。快、便宜,但只讀節錄,別拿來做整檔審查
- `Plan` — 設計實作方案
- `general-purpose` — 讀寫皆可的多步驟執行
- `claude` — 萬用後備
- (另有 `claude-code-guide` 問 Claude Code 用法、`statusline-setup` 等特化原生型別,按需用)

**vendored agent types**(claude-flow/SuperClaude 那 40+ 個,如 `backend-architect`、`hierarchical-coordinator`):未經驗證,預設不用。除非 Carson 點名,或你讀過它的定義檔確認內容真的貼合任務。

**工具優先序**:檔案操作一律原生工具(Read/Write/Edit/Glob/Grep),不用 `mcp__filesystem__*`;完整規則與例外見 failsafe.md 第 1.1 節。

**Workflow 工具**:只在 Carson 明確要求多 agent 編排(說「用 workflow」「ultracode」或呼叫 `/evolution` 這類 skill)時使用。平常派工用 Agent tool 就好。**注意:並非每個 session 都有 Workflow 工具** — 先確認它在你的工具清單裡;沒有就用多個 Agent tool 呼叫替代,並向 Carson 說明。

---

## 1. 指揮官不下場

主對話的 context 是全 session 最貴的資源:塞爆 → compaction → 忘記早期指示 → 失焦。所以:

**以下工作一律派 subagent,主對話只收結論:**
- 一個任務內要讀超過 3 個檔案、或任何單檔超過 500 行(`docs/ops/*` 與 `CLAUDE.md` 豁免不計數 — 讀制度檔本身永遠自己讀)
- 掃 repo 找東西(找定義、找引用、找模式)→ `Explore`
- 查網頁/看影片(影片照 memory `watch-link-per-agent`:一連結一 agent)
- 批次改檔(同一模式改 3 處以上)
- 跑長輸出指令並分析結果(測試全量跑、大型 log)

**主對話自己做的:**
- 與 Carson 對話、做決策、整合各 agent 結論
- 讀單檔確認關鍵事實(≤500 行,一個任務內 ≤3 檔)
- 單點編輯(1-2 個檔的小改動)
- 寫最終交付文字

**判準**:動手前自問「這件事的中間過程,我之後還需要嗎?」— 只需要結論的,派出去。

### context 預算(第 1 節的量化版)

每次 tool call 都會把**整個 context 從 cache 重讀一遍**,所以成本隨 context 大小線性放大:
同樣 500 次 tool call,120K context 花 60M token,800K 花 400M —— **做的事一樣,差 6.7 倍**。
2026-09-01 實測:兩支平均 context 787.6K / 396.1K 的 session 吃掉全機當天額度的 72%。

| context 已用 | 動作 |
|---|---|
| ≥ 120K | 收尾當前任務,不開新的複雜工作;還要探索就派 subagent 出去,結論收回來 |
| ≥ 200K | 不接新工作,狀態寫成交棒檔,開新 session 續做 |

- **不要靠 compaction 續命**:compact 會丟早期指示(正是本節開頭要防的失焦),而且它本身要讀完整個 context。**交棒優於 compact。**
- hook 會在這兩個門檻主動提醒。2026-09-02 起改成絕對 token;先前是百分比門檻,在 1M 視窗上等於已用 650K 才第一次叫 = 形同虛設。實據與修法見 memory `claude-context-budget-2026-09`。
- 覺得額度不夠用時,**先量 context 分佈再談減量或分流** —— 換一個額度池(Codex 等)不解根因,倍率浪費會跟著搬家。

---

## 2. 派工三件套(每個 Agent prompt 必含)

1. **目標與動機**:做什麼+為什麼(subagent 看不到主對話,動機讓它在邊界情況做對取捨)
2. **驗收條件**:可客觀檢查的完成定義(「測試 X 通過」「找出所有引用並列 檔案:行號」),不是「做好做滿」
3. **回報格式**:明確規定回什麼(見第 4 節回報合約)

缺任何一件就先補,不要發出去。模板見 `docs/ops/prompts.md`,直接填空。

---

## 3. 模型路由(按任務型態,不按主模型)

| 任務型態 | model | 理由 |
|----------|-------|------|
| 機械性:格式轉換、批次改名、套已定案的模式、分類、抽取欄位 | `haiku` | 錯了成本低、量大省錢(呼應 memory `api-credits-frugal`) |
| 搜索定位(Explore) | 不指定(繼承)或 `haiku` | 搜索靠工具不靠智力 |
| 一般實作、除錯、寫文件、研究彙整 | `sonnet` | 日常主力 |
| 架構設計、跨檔 refactor、安全審查、高風險判斷的第二意見、模糊題 | `opus` | 判斷力差距真實存在的場合 |
| 品味判斷(文案好壞、UI 質感、策略取捨) | `opus` + 給 Carson 過目 | 制度補不了品味,見 judgment.md 第 6 節 |

**預設從便宜的開始**,靠下面的升級路徑補救,而不是一開始就全用 opus。

---

## 4. 回報合約(寫進每個派工 prompt)

subagent 的回報必須:
- **只回結論**:判斷結果、關鍵發現、`檔案路徑:行號`
- **長產物落檔傳路徑**:報告、大段代碼、清單 → 寫到檔案(臨時的放 scratchpad,交付的放專案內),回報只給路徑+3 行摘要
- **禁止**把整檔內容、完整 log、逐步過程貼回來
- **明確標註失敗**:沒找到就說沒找到+找過哪裡;做不到就說做不到+卡在哪。禁止「大概」「應該」矇混

主對話收到不合約的回報:抽取有用結論後丟棄,不要全文轉述給 Carson。

---

## 5. 升降級路徑

同一子任務,各層級的嘗試額度(唯一的一套數字,其他檔引用這裡不自帶數字):

| 層級 | 額度 | 用完後 |
|------|------|--------|
| haiku | 1 次 | 直接升 sonnet(不重試 haiku;它錯通常是能力不夠不是運氣不好) |
| sonnet | 2 次 | 帶完整失敗軌跡升 opus:prompt 附上每次嘗試做了什麼、錯在哪、錯誤訊息原文 — 讓 opus 不重蹈,而不是白紙重來 |
| opus | 1 次 | 停下,照 judgment.md 第 3 節問 Carson,附全部失敗軌跡 |

- 總嘗試上限由額度自然決定:haiku 起跳最多 4 次、sonnet 起跳最多 3 次,到頂即停,不要無限重試燒額度
- 本節管「子任務換模型」;**單一工具動作連環報錯**另有更快的熔斷(3 次即停),見 failsafe.md 第 1.2 節,先觸發先適用
- **每次升級前**先回 judgment.md 第 4 節快查:失敗是結構性的(每次錯法一樣)才值得升級;是方向錯了就換路,升級救不了錯方向
- **降級**:opus/sonnet 解出可複製的模式後(例:確定了改法,剩 20 處要套),把模式寫成明確指令,降回 haiku/sonnet 批次執行

---

## 6. 驗證不自驗

**原則:寫的人不驗自己的產出。** 驗收一律派 fresh-context agent(新開、不繼承實作 agent 的 context),因為實作者的盲點會原樣延續到自驗裡。

按產物類型:
| 產物 | 驗法 |
|------|------|
| 檔案/文件 | fresh agent read-back:檔案存在、內容完整、內部引用的路徑真實存在 |
| 程式碼 | 測試或實跑(能跑就跑,不要只 typecheck);驗證 agent 自己執行,不信任實作 agent 的「我跑過了」 |
| 高風險判斷(架構選型、資金策略、對外文案) | 第二意見:另派一個 agent 給同樣輸入獨立作答,比對分歧;或多答案評審選優 |

**風險分級(Carson 拍板:品質優先、關鍵事必驗):**
- **紅線類**(對外發布/動錢/寫正式機,見 CLAUDE.md):100% 必驗,再小都驗。歷史事故 `web-center-test-prod-misfire` 就是 stub 攔錯層直接打到正式機。
- **一般交付**(會留在 repo、Carson 會用的):驗一次(read-back 或測試)
- **純內部雜活**(臨時腳本、探索筆記):可免驗

**驗證 agent 的 prompt 要點**:給它驗收條件原文,要它「試圖證明沒做完/做錯」,而不是「確認做完了」— 找碴視角的驗證才有效。
