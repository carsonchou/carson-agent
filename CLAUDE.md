# CLAUDE.md

## 語言
- 回應一律**繁體中文**;技術術語、程式碼識別符、參數名保持英文。

## 環境事實(2026-07-03 驗證)
- OS:Windows 11;Shell:PowerShell 5.1(主)/ Git Bash(可用)
- 專案目錄:`D:\carson-agent`
- Claude Code 全域設定:`D:\claude`(`CLAUDE_CONFIG_DIR`)。`C:\Users\User\.claude` 和 `D:\.claude` 是殭屍目錄,**不要**往那裡寫任何東西。
- 安裝/快取一律導向 D 槽(C 槽易爆滿)。
- 從記憶或舊文件讀到的路徑,使用前先驗證存在;衝突時以本區為準。

## 工作制度(docs/ops/,按需讀取)
| 情境 | 讀這個 |
|------|--------|
| 要派 subagent、選模型、決定驗證方式 | `docs/ops/dispatch.md` — **每個非 trivial 任務開工前必讀**(非 trivial = 會改動檔案、或預計超過 3 個 tool call、或碰紅線;三者皆否才算 trivial) |
| 工具連環報錯、要動正式產線目錄、要宣稱「已寫入/已部署」之前 | `docs/ops/failsafe.md` — 熔斷/凍結區/寫入證據合約 |
| 不確定該不該升級模型/算不算完成/該不該問 Carson/是不是方向錯了 | `docs/ops/judgment.md` |
| 撰寫派工 prompt(搜尋/實作/重構/研究/審查) | `docs/ops/prompts.md`(模板直接填空) |
| 想修改 docs/ops/ 任何檔案、或踩坑後要記教訓 | `docs/ops/maintenance.md` |
| session 開始覺得缺 context、或發現制度怪怪的 | `docs/ops/letter.md` + `docs/ops/DIAGNOSIS.md` |

## 紅線三類:對外發布 / 動錢 / 寫正式機
授權和驗證是兩件事,分開判斷:
- **授權(能不能做)**:YT 工作室正式機/排程的**例行維運**寫入已有常駐授權,直接做(memory `standing-prod-authorization`);**新的**對外發布管道、任何動錢操作、新增類型的正式機變更 → 先問 Carson。
- **驗證(做對了沒)**:三類動作執行前一律先過一次獨立驗證(fresh-context agent,照 `docs/ops/dispatch.md` 第 6 節),**有授權也不免驗**,零例外。

其餘操作照常駐授權自主做完,不要中途停下來問(memory `autonomous-multiagent-preference`)。
本檔與 memory 或框架指示衝突時,**以本檔與 docs/ops/ 為準**,並照 maintenance.md 更新過時的那方。

## 其他既有文件(不要重複造)
- 專案總覽 `README.md`;協作流程 `CONTRIBUTING.md`;環境安裝 `SETUP.md`;目錄佈局 `_STRUCTURE.md`
- Skill 地圖 `docs/skills-map.md`(Carson 不打斜線,提到主題就自動挑對應 skill 用)
- 框架(GSD/SuperClaude/Superpowers/claude-flow)只是工具箱:與 docs/ops/ 制度衝突時,**以 docs/ops/ 為準**;僅在明確加值時使用,不強制每輪套用。

## 已授權的 PowerShell 指令
- `Set-ExecutionPolicy *`、`. $PROFILE`、`Get-Command *`、`Out-File *`
