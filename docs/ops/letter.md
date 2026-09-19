# 給未來 session 的信(letter.md)

> 寫於 2026-07-03,Carson 唯一一次 Fable 5 session。你(正在讀的模型)大概是 Sonnet、Opus 或 Haiku。這封信講三件 Carson 沒問、但我認為對這個環境最重要的事,以及這套制度最可能怎麼壞掉。

---

## 三件最重要的事

### 1. 這個環境的錯誤成本是真金白銀,而且 Carson 賠不起
Carson 月收入約 8000(台幣),後備金 8 萬,質押借貸方案是精算過的緊平衡(memory `stock-pledge-carry-plan`);API 額度曾一個月被燒掉約 US$70,其中大半是模型選用不當(memory `youtube-api-cost-breakdown-2026-06`)。這裡的「動錢紅線」「省額度」不是官僚條文 — 一次自信的錯誤判斷(下錯單、發錯內容、燒爆額度)對他的傷害是實質的。**當你在「快速做完」和「多驗一次」之間猶豫,而事情碰到錢或對外時,永遠選後者。**

### 2. 這個環境最缺的是減法,不是加法
盤點結果:301 個 skills(絕大多數從未用過)、三個框架、兩套 hooks(一套指向殭屍路徑)、三個 config 目錄。歷史軌跡很清楚:每次想「變強」就再裝一層,沒有人拆。**你想幫 Carson 提升環境時,第一個問題應該是「什麼可以拆掉」,而不是「還能裝什麼」。** 新工具要過的門檻:它解決的問題,現有工具真的解決不了嗎?(DIAGNOSIS.md 有具體的待拆清單。)

### 3. Carson 的信任是資產,你的自驗紀律是唯一防線
Carson 給常駐授權、要你自主做完、不逐行審產出。這代表:**你回報「完成」他就當真了**。沒有 code review、沒有 QA、沒有第二雙眼睛 — dispatch.md 的「驗證不自驗」就是這個環境唯一的品質關卡。誠實的「做到 80%,剩下卡在 X」永遠優於漂亮的「全部完成」;前者他能處理,後者會在幾天後變成產線停擺或正式機事故(兩者都真實發生過)。

---

## 這套制度最可能的退化方式(按可能性排序)與預防

### 退化 1:規則被「善意繞過」,例外累積成慣例
「這次很簡單,不用派 agent 驗了」「趕時間,直接改」— 每次單獨看都合理,三次之後制度名存實亡。
**預防**:紅線類(對外/動錢/正式機)零例外,沒有「這次很簡單」;非紅線類允許從簡,但回報裡要明說「未驗」。讓例外可見,就不會變成慣例。

### 退化 2:環境漂移讓規則悄悄過時,但表面看起來還對
這是最危險的一種,因為弱模型會自信地遵循錯誤指示(舊 CLAUDE.md 的錯路徑就這樣存活了一個月)。
**預防**:任何從文件/記憶讀到的路徑與工具名,用前先驗證存在;發現對不上,照 maintenance.md 就地修正+登記。**制度檔對不上現實時,現實是對的。**

### 退化 3:膨脹到沒人讀
每個 session 往裡加一點,兩個月後 dispatch.md 變 800 行,等於沒有。
**預防**:maintenance.md 的硬閾值(CLAUDE.md ≤60 行、ops 檔 ≤250 行)。加新規則時先問:能不能改一條現有規則,而不是加一條?

### 退化 4:制度檔根本沒被讀
CLAUDE.md 的路由被忽略,或 compaction 之後忘了制度存在。
**預防**:雙保險已設 — CLAUDE.md 路由表 + memory `ops-governance-established`(MEMORY.md 有索引行)。如果你現在是透過 memory 找到這裡的,說明保險生效了;請順手檢查 CLAUDE.md 的路由表還在不在。

---

## 誠實條款:這個 harness 的極限(制度補不了的)

1. **品味與模糊題**:拆解、驗證、多答案評審能拉高執行品質的下限,補不了品味判斷的上限。處理方式在 judgment.md 第 6 節:升 opus + 多答案評審 + 明說信心有限,讓 Carson 裁決。不要假裝rubric能解決審美。
2. **分類器牆**:寫 settings/hooks、寫正式機設定、裝陌生 repo,分類器會擋,重試一次仍擋就整理好指令請 Carson 用 `!` 執行(memory `untrusted-install-classifier-wall`、`droplet-prod-writes-classifier-blocked`)。這不是制度能繞的,別浪費輪次嘗試。
3. **compaction 不可控**:長 session 的早期指示會被壓縮掉。對策只有結構性的:重要結論隨做隨寫進檔案,別留在對話裡。
4. **弱模型的遵循極限**:規則寫了也可能被忽略 — 所以這套制度刻意「少而硬」(docs/ops/ 七檔 + CLAUDE.md 路由、每檔一個主題、硬閾值),而不是完備但沒人讀的百科。維護時請守住這個設計哲學。

---

## 交接區(未完成項,後續 session 可接手)

- [ ] **待 Carson 決定**:拔除專案 `.claude/settings.json` 的殭屍 claude-flow hooks(DIAGNOSIS.md 第一名,有具體步驟)
- [ ] **待 Carson 決定**:`.claude/commands/` 的 claude-flow stock 目錄搬移歸檔(同上)
- [ ] **待 Carson 本人**:`D:\.claude` 確認無獨有內容後改名 `D:\.claude-DEAD`(DIAGNOSIS.md 第二名)
- [ ] **待 Carson 決定**:從專案 `.claude/settings.local.json` 的 `enabledMcpjsonServers` 移除 `filesystem`(與原生工具全重疊,是弱模型參數混淆頭號來源;移除前靠 failsafe.md §1.1 的規則擋)
- [ ] MEMORY.md 索引已超過 maintenance.md 第 4 節的 50 條閾值;下次照該節程序精簡(合併 yt-studio 系列、droplet/classifier 系列的重疊條目)
