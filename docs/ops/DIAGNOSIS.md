# Harness 快速診斷(2026-07-03,Fable 5 制度化 session)

> 本檔是 `docs/ops/` 制度系列的地基:列出這個 harness 目前最漏 token、最容易失焦、最容易出錯的前三名,各附具體修法。其他制度檔(dispatch.md、judgment.md 等)的規則都是針對這三個病灶設計的。
> 事實來源:2026-07-03 由兩個 Explore agent 實地盤點 `.claude/`、`D:\claude`、memory 目錄後確認,非憑印象。

---

## 第一名:固定 context 開銷 + 殭屍 hooks(最漏 token)

### 症狀
每個 session 還沒開始做事,開場就被塞入:

- **301 個 skills 的完整清單**(含大量 claude-flow stock 文件型 skill,如 `sparc:*`、`swarm:*`、`hive-mind:*` 約 150+ 條,絕大多數從未被使用)
- **40+ 個 agent types**,原生可靠的主要是 `Explore`、`Plan`、`general-purpose`、`claude`(另有 `claude-code-guide`、`statusline-setup` 等特化原生型別);其餘大宗是 claude-flow / SuperClaude vendored 的 persona,品質未經驗證
- **superpowers 的 using-superpowers skill 全文**經 SessionStart hook 注入
- **MEMORY.md 索引 50+ 條**(精確閾值見 maintenance.md 第 4 節)

### 根因
1. 專案 `.claude/settings.json` 的 claude-flow hooks 全部指向 `C:\Users\User\.claude\helpers\hook-handler.cjs` — 這是**殭屍路徑**(junction 指到 `D:\.claude`,而真正生效的 config 目錄是 `D:\claude`,由 `CLAUDE_CONFIG_DIR` 環境變數確認)。這些 hooks 在每次 Bash/Edit/SessionStart/Stop 都嘗試執行。
2. `.claude/agents/` 和 `.claude/commands/` 幾乎全是 claude-flow v3 vendored 內容,只有 `evolution.md` 和 `morning.md` 是 Carson 親寫。vendored 內容持續灌進每個 session 的可用清單。

### 具體修法(需 Carson 放行的列為建議,弱模型不要自己動)
| 修法 | 誰能做 | 動作 |
|------|--------|------|
| 拔掉專案 `.claude/settings.json` 裡的整個 claude-flow `hooks` 區塊(路徑已死,只剩開銷) | **Carson 放行後才能改**(settings 寫入常被分類器擋) | 刪 `hooks` 中所有指向 `C:\Users\User\.claude\helpers` 的條目;保留 `permissions` 區塊 |
| 移除 `.claude/commands/` 下的 claude-flow stock 目錄(agents/analysis/automation/coordination/github/hive-mind/hooks/memory/monitoring/optimization/sparc/swarm/workflows + claude-flow-*.md),只留 `evolution.md`、`morning.md` | **Carson 放行**(建議先搬到 `D:\claude-flow-archive\` 而非刪除) | 這一項砍掉開場 skill 清單裡約 150 條 noise |
| MEMORY.md 索引精簡:同主題多條合併、已淘汰專案(如 triple-supertrend)標註歸檔 | 弱模型可自做(閾值與程序見 maintenance.md 第 4 節,以該檔為準) | 超過 50 條時執行 |
| 不要在主對話讀大檔案(見第三名) | 弱模型每輪自律 | 見 dispatch.md |

---

## 第二名:設定漂移 — 三個 config 目錄 + 過時 CLAUDE.md(最容易出錯)

### 症狀
弱模型會**自信地遵循錯誤資訊**:

- 舊 CLAUDE.md 寫工作目錄是 `C:\Users\User\Downloads\carson-agent` → **實際是 `D:\carson-agent`**
- 舊 CLAUDE.md 寫預設模型 Sonnet 4.6 → 已過時
- 舊 CLAUDE.md 把 `defaultPermissionMode: acceptEdits` 寫成散文 → 它不是真的設定,真設定在 settings.json 裡根本沒這個 key

### 根因:三個 config 目錄並存
| 路徑 | 狀態 |
|------|------|
| `D:\claude` | ✅ **唯一生效**(`CLAUDE_CONFIG_DIR` 環境變數,User+Machine 層都設了)。GSD hooks、Superpowers plugin、全域 settings.json 都在這 |
| `D:\.claude` | ❌ 殭屍(舊遷移殘留) |
| `C:\Users\User\.claude` | ❌ junction → `D:\.claude`,一樣是殭屍;但專案 settings.json 的 hook 路徑硬編指向這裡 |

### 具體修法
1. ✅ 已做(本 session):重寫 `CLAUDE.md`,環境事實區只寫已驗證的資訊。
2. **規則(所有未來 session 遵守)**:任何檔案路徑,用之前先驗證存在(`Glob` 或 `Test-Path`),尤其是從記憶或舊文件裡讀到的路徑。路徑衝突時以 `CLAUDE.md` 環境事實區為準;CLAUDE.md 自己也錯時,以 `$env:CLAUDE_CONFIG_DIR` 實測為準,並回頭修 CLAUDE.md。
3. **建議 Carson(需本人做)**:確認 `D:\.claude` 無獨有內容後整目錄改名為 `D:\.claude-DEAD`,讓殭屍引用快速炸出來而不是靜默半生效。

---

## 第三名:無派工與驗證紀律(最容易失焦)

### 症狀
1. **主對話自己下場**大量讀檔/掃 repo/查網頁 → context 塞爆 → 觸發 compaction → 早期指示被壓縮遺失 → 後半段失焦、重問已答過的問題。
2. **自己寫自己驗**:改完就宣布完成,沒有獨立驗證。本 repo 真實事故:
   - `queue_size` 把已發布舊片算進庫存 → 產線誤判停產多日(見 memory `yt-studio-production-halt-rootcause`)
   - web_center 前端測試用 stub 攔錯層(攔 `window.api` 而非 `window.fetch`)→ 誤觸正式雲端 `schedule_publish`(見 memory `web-center-test-prod-misfire`)
3. **模型調度全憑當下心情**:沒有規則決定什麼活派 haiku、什麼活升 opus、錯了怎麼升級。

### 具體修法
全部制度化在兩個檔:
- `docs/ops/dispatch.md` — 指揮官不下場、派工三件套、model/effort 顯式指定、回報合約、升降級路徑、驗證不自驗
- `docs/ops/judgment.md` — 何時升級/何時算完成/何時該問/方向錯訊號/品質底線,附正反例

**一條先行鐵律(其他檔都引用它)**:凡是「對外發布、動錢、寫正式機」三類動作,執行前必須有一次獨立驗證(fresh-context agent),不論任務多小、不論有沒有授權 — 授權解決「能不能做」,驗證解決「做對了沒」,兩者不可互相替代(完整規則見 CLAUDE.md 紅線區)。上面兩個事故都是這條缺席造成的。

---

## 補充(2026-07-03 同日):弱模型長任務三大崩潰場景 → 防禦對照

上面三名是「結構性病灶」;下面是病灶在長任務中的**發作形態**,逆向推導自 Sonnet 等級模型的實際失敗模式。防禦機制全部制度化在 `docs/ops/failsafe.md`:

| 崩潰場景 | 本環境的具體引爆點 | 阻斷方案(failsafe.md 章節) |
|----------|-------------------|------------------------------|
| **工具調用崩潰**:context 變大後亂帶 MCP 參數、連環報錯 | filesystem MCP 與原生工具全重疊(參數形狀混淆頭號來源);PowerShell 5.1 語法陷阱;殭屍 hooks 錯誤噪音加速退化 | 工具優先序(§1.1)+ 連環報錯熔斷:3 次即停,禁止變體重試(§1.2)+ 炸點速查表(§1.3) |
| **語意迷航**:compaction 後忘全局、跨產線亂改已完成代碼 | 單 repo 裝著四條產線(youtube_channel 每日自動跑);本機/雲端雙副本 drift;對話是唯一全局記錄而它會被壓縮 | 任務錨檔+強制重讀時機(§2.1)+ 凍結區清單(§2.2)+ checkpoint commit(§2.3) |
| **假性完成**:回報「已寫入」實際沒落檔 | 遠端自組部署鏈(sftp/base64+exec)三層皆可假完成;分類器擋下的動作被幻覺成已做;PowerShell 寫入吞錯 | 寫入證據合約:通道越間接證據義務越重(§3.1)+ 遠端唯讀複驗鐵律(§3.2)+ 被擋=未完成(§3.3) |

---

## 誠實標註:本診斷的極限
- 以上三名是**結構性**問題,修了之後執行品質會顯著提升;但弱模型在**模糊題與品味判斷**(如「這支影片腳本好不好」「這個 UI 高不高級」)上的差距,制度補不了 — 遇到這類判斷,照 judgment.md 的規則升級模型或明說做不到,不要硬答。
- claude-flow hooks 是否真的每次都執行失敗(而非靜默成功),未實測逐一驗證;「路徑指向殭屍目錄」本身已足以構成拔除理由。
- GSD hooks(`D:\claude\hooks\gsd-*`)實際 token 開銷未量測;它們是生效系統的一部分,本診斷不建議動,除非 Carson 觀察到明顯拖慢。
