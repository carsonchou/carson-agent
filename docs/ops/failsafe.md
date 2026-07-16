# 失敗場景防禦(failsafe.md)

> 針對弱模型長任務的三大崩潰場景:**工具調用崩潰、語意迷航、假性完成**。與 dispatch.md 分工:dispatch 管「怎麼派工」,本檔管「怎麼不出軌」。兩檔規則同時適用時照 §1.2 的「先觸發先適用」;無法判定先後時,熔斷類(本檔)優先 — 先活下來再談效率。
> 標【拍板】的條目 = 2026-07-03 Carson 授權「自主決定最佳解」後由 Fable 5 裁決,修改屬「調度預設值」等級,照 maintenance.md 須先問 Carson。

---

## 1. 場景一:工具調用崩潰(context 變大後亂帶參數、連環報錯)

### 1.1 工具優先序【拍板 Q1】
- **檔案操作一律用原生工具**(Read/Write/Edit/Glob/Grep)。`mcp__filesystem__*` 系列與原生工具功能重疊,是參數形狀混淆的頭號來源 — **唯一允許用它的情境:操作 `D:\carson-agent`、`D:\claude`、scratchpad 以外的目錄** — 且注意它的 allowed dirs 只有 Desktop/Documents/Downloads(見 `.mcp.json`),超出範圍一樣報錯,別白燒輪次。
- 其餘 MCP 各有不可替代用途,照常用:網頁抓取=firecrawl、瀏覽器=playwright、Notion=notion。
- 已建議 Carson 從 `enabledMcpjsonServers` 移除 filesystem(待辦在 letter.md 交接區;移除前上面的規則就是防線)。

### 1.2 連環報錯熔斷【拍板 Q2】
**定義**:為同一目的發出的工具呼叫連續失敗 3 次 — 換寫法、換參數、換工具都算同一目的;中間有一次成功呼叫即重新計數。

觸發後**禁止第 4 次變體重試**,依序執行:
1. **先查環境**:重讀 CLAUDE.md 環境事實區 + 本檔 1.3 速查表。連環報錯的最常見根因不是任務難,是 shell 語法/路徑形式錯了還在硬試。
2. **確認非環境問題後**:派一個 fresh-context agent(`general-purpose`,model 照 dispatch.md 第 3 節按任務型態選,一般用 `sonnet`),prompt 附完整失敗軌跡(每次的指令原文+錯誤原文),讓它重試一次。
3. **仍失敗**:該子任務標記「卡死」寫進任務錨檔(§2.1),推播 Carson(ntfy/Telegram 管線現成),然後**繼續做其他不相依的子任務** — 不要整個 session 停在原地等。
4. 推播管線不可用時降級:錨檔+本輪回報裡明說卡死,等 Carson 下輪處理。

與 dispatch.md 第 5 節的關係:那邊管「子任務」層級的模型升級額度,這邊管「單一工具動作」層級;哪個先觸發就先照哪個走。

### 1.3 Windows 高頻炸點速查(報錯先對這張表)
| 炸點 | 正確做法 |
|------|----------|
| PowerShell 5.1 沒有 `&&`/`\|\|` | `A; if ($?) { B }`,或改用 Bash tool |
| `Out-File`/`Set-Content` 預設 UTF-16 | 一律加 `-Encoding utf8`;或改用原生 Write tool |
| cmdlet 失敗被 `-ErrorAction SilentlyContinue` 吞掉但 exit code 仍 1 | `try { ... -ErrorAction Stop } catch {}` |
| 給 Carson 的 `!` 指令 | 走 Git Bash:一律 `/d/...` 絕對正斜線路徑,反斜線會壞 |
| 路徑含空白 | PowerShell 用 `& "C:\path with space\app.exe"` |
| `New-Item -Force` 用在既有檔案 | 會清空內容;先 `Test-Path` 再決定 |

---

## 2. 場景二:語意迷航(compaction 後忘全局、跨產線亂改)

### 2.1 任務錨檔(anchor file)
非 trivial 任務(定義見 CLAUDE.md 路由表)開工第一個動作:在 scratchpad 建 `TASK-{slug}.md`,固定四欄:

```markdown
# TASK: {一句話目標}
## 驗收條件
- [ ] {可客觀核銷的條件,逐條}
## Touch list(預計改動的檔案)
- {路徑}  ← 開工時列;之後要動清單外的檔,先在這裡補一行「+{路徑}:{理由}」才准動
## 進度日誌
- {時間} {完成了什麼一句話}  ← 每完成一個可驗收單位追加一行
```

**強制重讀時機**:(a) 察覺發生過 compaction(對話開頭出現摘要);(b) 要動 touch list 以外的檔案之前;(c) 子任務失敗要升級模型之前。錨檔就是防迷航的外部記憶 — 對話會被壓縮,檔案不會。

### 2.2 凍結區清單【拍板 Q3】
任務沒有**明確點名**以下目錄時,不得改動其中任何檔案(讀不限):

| 目錄 | 凍結理由 |
|------|----------|
| 雲端 droplet 全部(非 repo 目錄,一樣入表) | 本表只管「任務沒點名就別碰」;能不能做、怎麼驗照 CLAUDE.md 紅線區(例行維運有常駐授權)+ §3.2 鐵律 |
| `youtube_channel/` | 每日自動跑的正式產線,亂改=停產(queue_size 事故前科)。**例外**:其下 `scripts/web_center/` 屬半凍結,見下 |
| `trading_bot/`、`pionex_crypto/` | 動錢 |
| `quant-service/data_hunter/` | 已上線看板 |

- **半凍結** `youtube_channel/scripts/web_center/`(注意:在 youtube_channel 底下,巢狀規則以本條較細者優先):可改,但任何測試前必須確認不會打到正式雲端(攔 `window.fetch` 而非 `window.api`;`cloud.json` 在生效位置=會真打正式機 — 事故前科 memory `web-center-test-prod-misfire`)。
- **自由區**:`jarvis/`、`docs/`(其中 `docs/ops/` 的**修改**另受 maintenance.md 權限分級約束 — 本表管碰不碰,maintenance 管怎麼改)、scratchpad、其餘未列目錄。
- 解凍 = 任務明確點名該目錄(「修 youtube_channel 的 X」)。解凍只解除「不得碰」,紅線驗證照常。

### 2.3 checkpoint commit【拍板 Q5】
- **每完成一個可驗收單位就本機 commit 一次**(不強制 push;push 前照 CONTRIBUTING.md 掃密鑰)。
- 小任務(touch list <5 檔、單一產線)可照現行慣例直接 commit 到 main;大任務(≥5 檔或跨產線)先開分支,完工 squash merge。
- 目的:迷航亂改可用 `git diff` 立刻揪出、可回滾;compaction 之後 `git log --oneline -10` 就是最可靠的進度記憶。

---

## 3. 場景三:假性完成(回報「已寫入」實際沒落檔)

**分層原則:通道越間接,證據義務越重。**

### 3.1 本機寫入
- 原生 Write/Edit 工具:成功回傳即可信(失敗會硬報錯),**不必**重讀確認落檔。**但這只免除「字節有沒有落檔」這一層;產物「內容對不對」的獨立驗證照 dispatch.md 第 6 節,兩者不同層、不可互抵。**
- **Shell 產檔**(Out-File、redirect、python 腳本寫檔):宣稱完成前,同一輪必附證據 — 檔案行數、尾 3 行、或 hash 之一。沒證據=不得宣稱完成。

### 3.2 遠端寫入鐵律【拍板 Q4】
凡 droplet 寫入/部署,完成宣告前**必須**用唯讀通道複驗(paramiko 唯讀直連可過分類器,memory `droplet-prod-writes-classifier-blocked`):
1. `cat`/`tail` 目標檔的關鍵行,確認新內容真的在遠端
2. 確認服務吃到新檔:process 重啟時間、log 時間戳、或版本標記

**「指令跑完」≠「檔案落地」≠「服務吃到」— 三層分開驗,只驗到哪層就只能宣稱到哪層。** 部署管線用 sftp/base64+exec 這類自組通道時(近期 sftp 壞過一次),這條沒有例外。

### 3.3 被擋 = 未完成
分類器/權限擋下的動作,一律記為「**未完成-被擋**」寫進任務錨檔;之後任何回報**禁止**把它轉述成已完成。處理:整理好等效指令(照 1.3 的 `!` 路徑規則)請 Carson 執行,並在交付摘要裡列為待辦。

---

## 4. 本檔的極限(誠實條款)
- 本檔防「執行出軌」;**品味與模糊題**的判斷力差距防不了,遇到照 judgment.md 第 6 節(升 opus+多答案評審+明說信心有限,Carson 裁決)。
- 熔斷推播(§1.2)依賴 ntfy/Telegram 可用;錨檔是不依賴任何服務的最終保底。
- 凍結區清單是 2026-07-03 的快照;新產線上線時照 maintenance.md 把目錄加進 §2.2(加=收緊可自改,移出=放寬要問 Carson)。
