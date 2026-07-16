# Claude 工具學習筆記（來源：IG 競品 3 篇）

> 自動安裝＋自動學習任務。來源貼文：visualaiclub(25 skills)、pb_design_lab(9 工具)、denghao.0304(6 專案)。
> 建立：2026-06-25。安裝位置：`CLAUDE_CONFIG_DIR=D:\claude`（全域）。

## ✅ 已安裝＋已學會

### 1. GSD — Git. Ship. Done.（`@opengsd/gsd-core` v1.5.0）
plan-driven 開發系統：把模糊想法 → 階層式計畫 → 一階段一階段執行，全程狀態追蹤＋原子 commit。約 90 個 workflow。

**3 個入門指令**
```
/gsd-new-project        # 新專案：提問→研究→需求→roadmap
/gsd-plan-phase 1       # 幫 phase 1 做詳細計畫
/gsd-execute-phase 1    # 執行該 phase 全部計畫
```
既有專案先跑 `/gsd-map-codebase` 讓 GSD 認識你的程式碼。

**常用**
| 指令 | 用途 |
|---|---|
| `/gsd-progress` | 我在哪、下一步；`--do "..."` 可丟自由意圖 |
| `/gsd-quick` | 小任務但保有 GSD 保證（計畫目錄＋原子 commit） |
| `/gsd-fast "<task>"` | 瑣碎改動，不開子代理，≤3 檔 |
| `/gsd-debug "<symptom>"` | 持久 debug session，撐過 /clear |
| `/gsd-verify-work <N>` | 完成 phase 的對話式 UAT |
| `/gsd-ship <N>` | 從完成的 phase 開 PR |
| `/gsd-help --full` | 完整參考 |

**對阿森的用法**：量化策略/工作室新功能可用 `/gsd-new-project` 或 `/gsd-quick` 結構化開發；既有 `youtube_channel` / `pionex_crypto` 先 `/gsd-map-codebase`。
更新：`npx @opengsd/gsd-core@latest`

### 2. SuperClaude（`/sc:*` 指令）
一套把 Claude Code 變完整 AI 開發平台的指令集（22 斜線指令、agent、行為模式）。

**重點指令**
| 指令 | 用途 |
|---|---|
| `/sc:brainstorm` | 蘇格拉底式需求探索 |
| `/sc:implement` | 功能實作（自動帶 persona＋MCP） |
| `/sc:analyze` | 品質/安全/效能/架構全面分析 |
| `/sc:research` | 深度網路研究（平行搜尋） |
| `/sc:improve` `/sc:cleanup` | 系統性改善/清理程式碼 |
| `/sc:test` `/sc:troubleshoot` | 測試覆蓋／診斷問題 |
| `/sc:index-repo` | repo 索引，省 token（號稱 58K→3K） |
| `/sc:task` `/sc:spawn` `/sc:workflow` | 複雜任務編排/委派 |
| `/sc:help` | 列全部指令 |

**對阿森的用法**：`/sc:index-repo` 直接對應你「省 API credits」；`/sc:research` 可做競品/幣圈研究。

---

## ⏳ 待裝（GitHub 連線恢復後自動安裝）

> 2026-06-25 當下 github.com 與 api.github.com 走 IPv4 全逾時（已知 IPv4 不穩問題），以下暫時無法 clone。自動重試腳本見 `scripts/install_claude_tools.sh`。

### 6 大專案剩餘
- **Superpowers**（規劃/子任務/TDD/code review/自主 agent，16k★）
- **Awesome Claude Code**（42k★，精選清單，clone 當參考）
- **Claude Code 系統提示**（4k★，揭露內部提示，clone 當參考）
- **Awesome Claude Plugins / Composio**（3k★，外掛清單）

### 9 個開源工具（帳號已用 api.github.com 驗證，2026-06-25）
| 工具 | 正確 repo | ★ | 用途 | 對阿森相關度 |
|---|---|---|---|---|
| Caveman | amanattar/caveman-claude-skill | 356 | 少廢話降 token | ⭐⭐⭐ 省 credits |
| Codeburn | **getagentseal/codeburn** | 8.2k | AI 花費 TUI 儀表板 | ⭐⭐⭐ 省 credits |
| Graphify | safishamsi/graphify | 71k | codebase 知識圖譜 | ⭐⭐ |
| Claude-video | bradautomates/claude-video | 2.5k | 看懂影片 | ✅ 已裝(=/watch) |
| open-design | nexu-io/open-design | 70k | 開源 UI 設計桌面 app | ⭐ |
| impeccable | ⚠️ 查無此 repo(IG OCR pbakus/impeccable 不存在) | — | UI 設計指令 | — |
| design-extract | **Manavarya09/design-extract** | 3.4k | 抽網站設計系統 | ⭐ |
| career-ops | **santifer/career-ops** | 55k | 求職/履歷 skill 組 | ✗ 無關 |
| browser-harness | **browser-use/browser-harness** | 15k | 自癒瀏覽器自動化 | ⭐⭐ 抓取穩定性 |

> 粗體＝IG 圖上 OCR 讀錯的帳號，已修正。安裝腳本 `scripts/install_claude_tools.sh` 已用正確帳號＋tarball 後援更新。

### 25 個 Claude Skills（visualaiclub，鎖在 PDF，僅圖上名稱）
animated-website, budget-dashboard, contract-reviewer, customize, dashboard-style, difficult-conversation-prep, email-drafter, end-of-day-summary, explainer-graphic, find-skills, ig-carousel, invoice-generator, learning-path-generator, morning-briefing, obsidian-daily-note, pdf-guide, quick-research, receipt-scanner, skill-dashboard, skills-audit, slide-deck-builder, visual-explainer, visual-page-builder, workflow-visualizer, customize-test
（這 25 個只有名稱，無原始碼公開；需要的話可按描述自建同名 skill。）

---

## 安裝後處理紀錄（2026-06-25）

### 全裝結果
- 9 repo 全數取得成功（走 api.github.com tarball 後援，因 github.com clone 主機 IPv4 斷線）。
- 副作用：`open-design`+`career-ops` 內建模板庫，把 `D:\claude\skills` 從 ~76 灌到 **302**。
- 處置：**全部保留、不刪**，改用分類地圖 `docs/skills-map.md`（15 類）+ 記憶 [[skill-auto-use-map]]（提到主題自動挑用、免斜線）。

### 覆蓋比對 + 清理
- **無任何舊 skill 被覆蓋**：`cp -r` 撞名只會塞巢狀子目錄、不蓋原檔。佐證：`copywriting`（6/16 舊檔）時間沒變、無巢狀。
- 清掉 3 處巢狀/幻影垃圾：`brainstorming/brainstorming`、頂層幻影 `browser_harness`（內容是 `../../SKILL.md`）、`browser-harness/{skills,src}` 內巢狀 SKILL.md。
- 結果：**302 → 301**，巢狀 SKILL.md 歸零，正常 skill 全在。
- `graphify` 無 root SKILL.md（工具型非 skill），只在 `external-tools`，未進 skills。

### 安裝腳本已強化（`scripts/install_claude_tools.sh`）
- ★永不覆蓋既有同名 skill★（存在即跳過，重跑安全）；`CURATED=1` 只裝 18 個精選 allowlist；修掉假的「抽 README」註解。
