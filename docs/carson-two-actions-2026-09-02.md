# Carson:卡在你手上的動作(2026-09-02,09-03 增補③④)

只有你能做的:**① 送 YouTube API 提額表單(約 15 分鐘)、② 下單一條記憶體(約 5 分鐘)、③ 順手重授權 Google 憑證(約 2 分鐘)、④ 裝 RAM 那趟按一次 UAC 修排程任務(約 2 分鐘)。**
兩份文件都已過 fresh-context 獨立驗證(配額包三輪、RAM 包一輪找碴視角),這頁只有動作,論證在連結裡。

## ① 送配額提額申請 — 約 15 分鐘

**為什麼急**:配額每天先歸零,**79 支做好的片發不出去**(09-03 晚點名;申請包內引用的 81/+35 是其量測窗的數字,窗口已在包內標明);審核要 2~4 週,晚一天送晚一天生效。

表單入口:https://support.google.com/youtube/contact/yt_api_form
所有欄位答案照抄:`youtube_channel/docs/yt_quota_increase_2026-09.md` §4(justification 整段直接貼)

送出前三勾(缺一不送):
- [ ] **抄官方核定值**:console.cloud.google.com → 專案 `claude-morning-report-498407`(專案編號應為 **524513894332**;Console 上兩個都看得到,**兩個都對上**才是主頻道那個專案 —— ch2/ch3 是另一個專案 881902283633,別抄錯)→ IAM 與管理 → 配額 → YouTube Data API v3 "Queries per day" → 把 Google 顯示的數字填進表單 "Current daily quota"(不要填我們自己的記帳數)
- [ ] **用 Owner 帳號登入**:crayray86@gmail.com
- [ ] **隱私政策 URL 還活著**:沿用上輪過稽核的那個公開網址,點開確認

## ② 買記憶體 — 約 5 分鐘

**買什麼**:原價屋 → **UMAX DDR5-5600 SO-DIMM 16GB,NT$6,300(09-02 報價;09-04 未能線上複驗原價屋現價,下單時以官網/門市為準)**。09-04 比價站現價對照:Yahoo 6,450 / PChome 7,099(比 09-01 又 +100)——6,300 若仍在就是最低,且漲勢持續。筆電條;千萬別買成桌機 UDIMM。到手插空著的 ChannelB 槽即可,32GB 對稱雙通道。

**不買會怎樣**:現在 16GB 單通道,可用記憶體**已經在**間歇跌破渲染守門的 2,000MB 門檻(09-02 實測一度只剩 1,207MB)——渲染負載由**日產量**決定(目前毛產出均值 ~19/日、尖峰 29),**不是提額後才會來**,所以這是現在進行式的節流、不是未來風險;而且 DRAM 行情單向上行,再拖一個月估多花 NT$300~700(此為偏高端推估、漲勢在放緩,但方向確定)。

完整論證與比價:`docs/ram-upgrade-decision-2026-09.md`

## ④ 裝 RAM 那趟順手:兩支排程任務改「不論登入與否都執行」— 約 2 分鐘(按一次 UAC)

實測發現:設成「僅互動登入時執行」的**不只兩支** —— 🔴 **2026-09-08 重量:全機每一支排程工作都是 `Interactive`**
(`LocalCronWatchdog`、`carson-quota-ceiling-watch`、`carson-seeding-watch`、`carson-narration-compliance-watch`、
`CarsonQuant_PCRender`、`DataHunter-EOD`、`Stock009816Monitor`…),
而且**排程器 `local_cron` 本身**是靠「啟動資料夾」捷徑起的,**也只在互動登入後才跑**;
`HKLM\…\Winlogon\AutoAdminLogon` 與 `DefaultUserName` 都**未設定** ⇒ 本機沒有自動登入。
⇒ **無人值守重開機(Windows Update/跳電)後,產線一個元件都不會起來,包括會發現這件事的那個,零錯誤訊號。**

⚠️ 本項的修法**刻意只改兩支**(看門狗 + 天花板守望),那是最小有效集合:
看門狗活著就會把 `local_cron` 拉起來,113 個 job 隨之回來。
**但要知道剩下的仍然是死的** —— `carson-seeding-watch` 與 `carson-narration-compliance-watch`
在無人值守情境下不會跑,那兩道哨的空窗要另外處理(不阻塞本項)。

🔴 **2026-09-08 新增的理由(讓本項比原本更急)**:那條「看門狗把排程器拉回來」的路徑
**在今天以前是壞的** —— 它會成功拉起一個**開跑就死**的排程器,並推播一則 restarted 成功通知
(根因:watchdog 用 `Popen(stdout=<檔>)` 啟動,該 handle 預設 cp950,排程器印 `▶` 就 UnicodeEncodeError;
已修並端到端驗過,見 `6750ed73` / `d4cf1aa2`)。
⇒ **救援路徑今天才真的能用,而它本身仍鎖在互動登入後面。修好的救援 ≠ 救援會發生。**

做法:系統管理員 PowerShell 跑 `D:\carson-agent\scripts\fix_task_principals.ps1`(已過獨立驗證;改 S4U=不存密碼、維持你的帳號身分)。

**驗收欄(任一 session 讀到都能代執行):**
- [ ] **立即**:腳本自帶——它會在新上下文實測送一則 ntfy「[驗收] S4U 上下文 ntfy 實測」到你手機,並印 PASS/FAIL(FAIL 就**不要重開機收工**,先回報;這是本修法唯一可能弄壞的東西)。結果檔的 `cron_procs_visible` 讀法:≥2=跨 session 可見性證實;**0 只有在產線 local_cron 當下活著時才是警訊**,它剛好死著時 0 是正常
- [ ] **裝完 RAM 重開機後,先做這個再做別的**:`Get-ScheduledTaskInfo LocalCronWatchdog,carson-quota-ceiling-watch` 兩者 LastRunTime 都在重開機之後 + local_cron 心跳活著(`STUDIO/local_cron.lock` mtime 新鮮)= 真驗收通過,並更新 premises.md 該條為已修

**已知取捨(驗證員第 10 條,接受)**:watchdog 在無人值守狀態救回的 local_cron 會活在 session 0——核心發布/渲染照跑,但 **TikTok 上傳與社群貼文兩個 headed 瀏覽器 job 起不來**,要等有人登入後手動重啟 local_cron 才恢復(救援時必發「⚠️ 排程器被重啟」推播,看到那則就找機會重啟)。無人值守重開機場景從「全死」變「核心活、兩 job 暫停」=嚴格變好;唯一退步是「登入中死掉被救」也會進 session 0。

**回退一行(改壞了用,系統管理員 PowerShell)**:
`$p = New-ScheduledTaskPrincipal -UserId "信義猛龍\User" -LogonType Interactive -RunLevel Limited; "LocalCronWatchdog","carson-quota-ceiling-watch" | ForEach-Object { Set-ScheduledTask -TaskName $_ -Principal $p }`
(腳本若中途炸掉留下殘件:`Unregister-ScheduledTask -TaskName NtfyS4UTest_temp -Confirm:$false`)

## ③ 重授權 Google 憑證 — 約 2 分鐘(你人已在機器前,順手)

`scripts/google_token.json` 的 refresh token 已失效(invalid_grant)——**早晨日報(/morning)的 Gmail+行事曆下次跑必炸**,信箱證據查證路也斷了。
在專案目錄跑:`python scripts/google_auth_setup.py` → 瀏覽器跳出 → 用 **crayray86@gmail.com** 點同意即可。

---
四件互不相依,順序隨意(②④同一趟做最省:裝 RAM 要重開機,④的真驗收正好靠那次重開機)。做完任一件跟任一個 session 說一聲即可。

---

## ⑤ 環境變數與 OmniRoute 現況 — **不是待辦,是一張分格的清單**(2026-09-08 實測)

> ⚠️ **這一節刻意分三格,不要合併成一個「殘留清單」。**
> 上一輪就是沒分格,差一點把①(一把**活的**金鑰)送進「待清」——
> 而 Jarvis 壞掉的訊號要等到有人去用才會出現。

### 🟢 格一:**不要清**(清了會弄壞東西)

**`ANTHROPIC_API_KEY`(使用者層持久化)—— 不是殘留,Jarvis 在用。**

呼叫點(逐一開檔驗過,不是轉述):

| 檔案:行號 | 內容 |
|---|---|
| `jarvis/jarvis.py:254` | `key = os.environ.get("ANTHROPIC_API_KEY", "").strip()` |
| `jarvis/web/server.py:732` | 同上 |
| `jarvis/web/server.py:1031` | 同上 |
| `jarvis/self_improve/optimizer.py:241` | 同上 |
| `jarvis/computer.py:351` | 同上 |

缺了它 `jarvis/jarvis.py:256` 直接 `raise RuntimeError("無 ANTHROPIC_API_KEY")`,web 端回「缺少 ANTHROPIC_API_KEY」。

⚠️ 另一面也要知道(所以它是「不要清」不是「沒事」):照 memory `anthropic-billing-api-vs-oauth`,
**獨立 API key 是額外計費的路徑**(OAuth 才吃訂閱額度)。
⇒ 它該不該存在是**成本決策**(碰「動錢」紅線,基建線不動),
但**在 Jarvis 改掉取用方式之前,刪掉它就是弄壞 Jarvis**。這兩件不要混。

### 🟡 格二:**只記錄,先不動**

**`CLAUDE_CODE_AUTO_COMPACT_WINDOW=200000`(使用者層持久化)** —— auto-switch 那套的遺留,
漏在持久層沒清掉。值本身**無害**且與 memory `claude-context-budget-2026-09` 的 200K 交棒線一致。
⇒ 記著它的出身即可,不必為了整潔去動一個正在幫忙的值。

**`OMNIROUTE_API_KEY`(使用者層持久化)** —— gateway 憑證。
**它只是憑證,不會造成路由**(路由要 `ANTHROPIC_BASE_URL`/`AUTH_TOKEN`/`MODEL`,那三個**都不在**任何持久層)。
⇒ 只要 OmniRoute 還在服役(見格三),留著它是合理的;要退役再一起清。

### 🔵 格三:原本列「待查」,**今天查完了,結論如下**

| 查的東西 | 結果 |
|---|---|
| `D:\omniroute-run\` | **存在**,6 個檔:`start-omniroute.vbs`、`usage_watch.py`、`usage-cache.json`(1.4MB)、`usage-calibration.json`、`patch_allow_rule.py`、`auto-switch.log` |
| 排程觸發器 | **只剩一支** `OmniRoute AutoStart`(`State=Ready`、**登入觸發**、`wscript.exe start-omniroute.vbs`) |
| 會改寫 `settings.json` 的那支 | 🟢 **已經整個不存在** —— `auto-switch.log` 末行:`2026-09-05 01:54:24 [DISABLED] scheduled task 'OmniRoute auto-switch' disabled on Carson's instruction - no further automatic settings.json writes`,而今天列排程時它**連工作都查不到了** |
| OmniRoute 現在在跑嗎 | 🔴 **在跑**:npm 全域安裝(`AppData\Roaming\npm\node_modules\omniroute`),pid 29156 **正在聽 20128** |
| 其他持久層路由鍵 | 使用者層與機器層都掃過,`ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`/`ANTHROPIC_MODEL` **全部不存在** |
| `settings.json` | `env` **0 個鍵**、**無 `model` 鍵** |

⇒ **結論:自動改寫那條路已經斷了(Carson 09-05 下的令生效),但 gateway 服務本身仍在服役且開機自啟。**
這不是殘留,是一個**還在用的東西**。要不要讓它繼續服役是 Carson 的決定,基建線不動。

⚠️ 但風險要講明:**gateway 活著 = 只要有任何東西再把那三個路由鍵設進某個 session 的環境,它就會再被釘住一次**,
而那次釘住**只存在於該程序的執行期**(磁碟上查無來源)⇒ 只能靠重啟解、且症狀是靜默的。
09-08 的 `non.`(wB:p1)就是這樣停擺四天,見 `docs/ops/2026-09-08_gate_health_inventory.md` 第十節。
