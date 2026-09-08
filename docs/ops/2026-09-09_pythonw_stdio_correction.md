# 排程下的標準輸出:三種形狀 —— 以及 9 支 pythonw 排程的母體掃描

> 執行:wB:p1 第三棒。派工單 `docs/ops/2026-09-09_dispatch_wB-p1_stderr_correction.md`。
> 前置:`c09a2486`(三支哨)+ 其獨立驗證 `docs/ops/2026-09-09_verify_c09a2486.md`。
> 本檔是那條更正的**落點**:`8bfaa829` 的 commit 訊息改不了,而它會被下一個人當範本抄。

---

## 一、🔴 三種形狀,不可以合併成「排程下 stderr 沒用」

同一支探針、同一台機器、2026-09-09 03:08 實測(探針落在 scratchpad,非 repo)。
條件 B/C **真的註冊了 Windows 排程工作**(principal 抄 `carson-seeding-watch`:User / Interactive / Limited),
跑完立刻 `Unregister`,事後 `Get-ScheduledTask` 清點回到 23 支、`zz-claude*` 0 筆。

| 條件 | `sys.stdout` / `sys.stderr` | `STD_*_HANDLE` | `GetConsoleWindow()` | `print(file=sys.stderr)` | `sys.stderr.write` |
|---|---|---|---|---|---|
| **A. 終端機裡跑 `pythonw`** | 真物件 | 1996 / 2664 | 0 | ✅ 看得見 | ✅ |
| **B. 排程工作 + `pythonw.exe`** | **都是 `None`** | **0 / 0** | 0 | **靜默 no-op** | **`AttributeError`** |
| **C. 排程工作 + `python.exe`** | 真物件 | 108 / 112 | **非 0** | 「成功」後蒸發 | 「成功」後蒸發 |

三件事要分開記:

1. **B 證實了上一棒的發現**,而且是在真排程工作裡量的,不是模擬。
   獨立驗證員(fresh context、另一條路徑 `Start-Process`)量到同一結果 ⇒ **兩個獨立儀器**。
2. **A 是那個最容易騙人的條件。** 在終端機裡跑 `pythonw` 會**繼承呼叫端的標準控制代碼**,
   所以 stdout 當然不是 None。⇒ **在終端機裡測 pythonw,量到的是 A 不是 B。**
   `quant-service/data_hunter/eod.py` 08-11 那行註解就是這樣寫錯的(本輪已就地更正)。
3. **C 比 B 更難抓。** 它拿得到**有效** handle,指向一個新配、沒有人看得到的 console:
   不是 None、不拋例外、`print` 完全成功、**寫進去就蒸發,而且沒有任何一層會抱怨**。
   ⇒ B 至少 `.write` 會拋;**C 完全無聲**。那 14 支 `python.exe` 排程要照 C 講,不要併進 B。

**判準(handoff §一.3 的形狀)**:「這件事失敗時,系統會不會產生**留得下來的**輸出?」
A/B/C 三種裡,只有寫檔在三種條件下都成立。

---

## 二、母體:全機 23 個 python 排程工作

`Get-ScheduledTask | ? {$_.Actions.Execute -match 'python'}` = **23 支**,其中 **9 支 pythonw**。
🔴 **實查修正了派工單的兩處**:`CarsonQuant-UptimeMonitor` 是 **Disabled**(不是活的),
且那 14 支 `python.exe` **全部 Disabled** —— 它們是 6/14 搬本機前的舊機制,刻意保持關閉
(`local_cron_watchdog.py:9-11` 記著:打開等於每天發兩次片、燒兩份配額)。
⇒ **活著的 pythonw 排程其實是 7 支,不是 9 支。**

### ④~⑨ 逐支結論(格式照派工單 §三.1)

| # | 工作名 | 進入點:行號 | 有沒有到得了讀者的通道 | 沉默的後果 | 處置 |
|---|---|---|---|---|---|
| ④ | `LocalCronWatchdog` | `local_cron_watchdog.py:76` `_log()` / `:128` `_push()` | **有**(log 檔為主 + ntfy,且 `:186` **有看 push 回傳值**,沒送出就不記冷卻) | — | **不改**。真環境陽性對照:09-08 08:12:58 它在 pythonw 下寫了 log、拉起排程器、推播成功 |
| ⑤ | `CarsonQuant_PCRender` | `hybrid_render.py:408-414` | 🔴 **沒有**(唯一那則操作員訊息寫 `file=sys.stderr`) | 「這個排程工作已無用途,可以 Unregister」這句話 **08-29 寫下後從沒有人讀到過** | **已改**:改走 `_operator_note()`,主通道寫 `logs/hybrid_render_pc.log` |
| ⑥ | `CarsonQuant-UptimeMonitor` | `monitor.py:19-24` `TARGETS` | n/a | 無 | **不改**。**Disabled**(2026-07-11 起)**且 `TARGETS` 是空清單** —— 唯一目標(雲端 droplet)已註解掉。即使啟用也監控不到任何東西 |
| ⑦ | `DataHunter-EOD` | `eod.py:42-47` | **有**。偵測到 `pythonw` 就把 `sys.stdout/stderr` 導向 `logs/eod_YYYYMMDD.log` | — | **註解更正 + 兩處留痕**(見 §三) |
| ⑧ | `Stock009816Monitor` | `monitor.py:73-113` | 🔴 **完全沒有**(只有 `print`,無 log 檔) | **Carson 錯過加碼點/收盤快照,零訊號** | 🔴 **沒有動它**(紅線·動錢鄰接區)。診斷 + 建議改法見 §四 |
| ⑨ | `YuantaUATWatch` | `uat_watch.py:41` `log()` ✅ / `:128`、`:137` `tg()` 回傳值被丟 | **一半**:log 通道好,但推播失敗後**狀態照樣前進** | IP 變了而推播失敗 → `last_ip` 仍被更新 → **白名單失效永遠不會再叫第二次** | **已改**(見 §三) |

### 那 14 支 `python.exe`:共同結論 + 一支實測

**共同結論**:14 支**全部 Disabled**,因此今天不是活的風險。
但它們的形狀是上表的 **C**,不是 B ——
一旦有人啟用任何一支,它的輸出會寫進一個新配的、沒有人看得到的 console,**成功寫入然後蒸發**,
且不像 pythonw 那樣至少 `.write` 會拋例外。**啟用前必須先給它一條落檔通道。**

**實測一支(不外推)**:條件 C 那一列就是拿 `python.exe` 註冊真排程工作量到的
(handle 108/112、`GetConsoleWindow()` 非 0、`print` 與 `.write` 都不拋例外)。

---

## 三、本輪改動(每一處都有陽性 + 陰性對照)

### 3.1 範本先修(承驗證 §4.1 / §4.2)——三支哨

驗證員推翻了 `c09a2486` 的完成度,而**那個範本正要被複製到另外 6 支**,所以先修範本:

- **§4.1 `_SWALLOWED` 唯寫**(判決行永遠不說「這輪吞了東西」,而推播失敗那條排在判決行**後面**
  ⇒ 只看最後一行或 grep 判決行的人拿到「✅ 正常」)。
  兩條都補:①`record()` 一律綴 `swallow_suffix()` ②收尾 `swallow_epilogue()` 放 `finally`,
  讓 **log 的最後一行**一定講得出這輪有沒有吞掉東西。
  ⚠️ **exit code 不動** —— 它是排程/watchdog 在讀的穩定基準(派工單 §五.2 同一理由)。
- **§4.2 零常駐回歸**(`alert()` 在 SELFTEST 下碰 `push` 之前就 return ⇒ 13 個演習模式留痕全 0)。
  新增 `--selftest=pushfail` / `pushraise` 兩個模式,把兩條失敗路徑各引爆一次。
  推播邏輯抽成 `_push_and_trace(pusher, ...)`,**演習與正式走同一份程式碼**(pusher 當參數傳)
  —— 複製一份演習版只證明得了複本會叫。
  真 `push` 只在非 SELFTEST 分支才 `import` ⇒ 演習路徑上它**根本不存在**(禁令放入口,`dispatch.md` §6)。

**實測(三支 × 4~5 模式)**:`pushfail`/`pushraise` → 留痕 1 行 + 收尾 1 行;
`zero`/`err`/`summary`/`biz`/`keyless`/`first`/`up` → 三欄全 0(陰性對照,不製造雜訊)。
`swallow_suffix()` 另外單獨驗過(判決行**之前**就發生的吞掉):拿壞掉的 selftest state 跑,
判決行結尾確實帶出「⚠️ 本輪吞掉 1 件:…JSONDecodeError…」,而正式 state 檔全程未被碰。

### 3.2 quota 的那一行(承驗證 §三)

`quota_ceiling_watch.py`:「不是第一次跑」的判準原本綁在 `prev_broken`(**解析失敗**)上,
而 state 是**合法 JSON 但少了 `effective` 鍵**時 `prev_broken` 是 `None` ⇒ 落到「基準建立」
⇒ 零留痕、不推播、rc=0。判準改成 `state_existed`(**檔案在不在**)。
順手把 `:212` 的非原子寫改成 tmp→`os.replace`(它正是「合法 JSON 但少鍵」的來源之一;
同 repo `quota_meter.py:195-208` 09-03 已為同一理由改過)。

**實測**:`--selftest=keyless` / `nullval` → 🔴 基準被迫重建(改前是靜默的「基準建立」);
`--selftest=first`(檔案不存在)→ 仍然是「基準建立」**不報警**(陰性對照,避免真的第一次跑被誤報);
`--selftest=up` → 🎉 上移路徑未退化。正式 state 檔 size/mtime 全程未變。

### 3.3 ⑤ `hybrid_render.py`

`main():408` 的操作員訊息改走 `_operator_note()`:先落 `logs/hybrid_render_pc.log`,
`stderr` 只當第二條路且 **None-safe**。
**實測**:條件 A(互動 python)既印出來也落檔;條件 B(`Start-Process pythonw`,無 console)**只落檔而確實落了**
⇒ 那則訊息現在到得了讀者。

### 3.4 ⑦ `eod.py` + `scan.py`

- `eod.py:38-52` 的註解就地更正(原文「pythonw 下 sys.stdout 非 None」只在條件 A 成立)。
  ⚠️ **判準本身沒錯**:用執行檔名 `stem.endswith("w")` 判斷在 A/B 兩種條件下都成立,錯的是註解寫的理由。
- `eod.py` 的摘要行原本寫 `'已推播' if push else '未推'` —— **拿旗標當結果報**。改成「已要求推播」。
- 真正的機制在 `scan.py:push_new_signals`:`broadcast()` 回 `{"ntfy": bool, "line": bool}` 而**回傳值被丟掉**
  ⇒ 一則都沒送出去時照樣 `_save_pushed()`,而那是**永久去重** ⇒ 訊號再也不會被推第二次。
  改成全部管道皆失敗就不記已推(下一輪重試)並印出原因。

### 3.5 ⑨ `uat_watch.py`

`:128` / `:137` 的 `tg()` 回傳值被丟,且狀態(`notified_open` / `last_ip`)**無條件前進**。
改成推播成功才推進狀態。
**實測(沙箱 + 執行期隔離斷言,真實 Telegram 0 次)**:
推播失敗 → tg 被呼叫 2 次、兩個狀態都維持原狀(下一輪會重試);
推播成功 → 兩個狀態照常前進(不會每輪洗版)。
⚠️ 第一版的對照**是空的**:我把 `tcp_open` 一律 stub 成 `False`,`net_ok` 因此是 False、
中斷分支根本沒被走到,而斷言照樣通過 —— 改成分主機回答後才真的引爆到兩個分支。
(`verification-that-cannot-fail` 當場又收一例。)

### 3.6 §C:把更正落到會被讀到的那頁

- `auditability_coverage.py:306` 那段「印到 stderr 就看得見」**沒有改程式碼**(對它是對的:它是 local_cron 的 job),
  但補了**射程限制**:不要當通用範本照抄,pythonw 排程工作要寫自己的 log 檔。
  (memory `detector-failure-shapes-2026-09`:宣稱寫在**程式碼註解**裡比寫在 commit 訊息裡危險。)
- 全 repo 掃過 `file=sys.stderr` / `sys.stderr.write`(ripgrep,約 40 處):**其餘都不在射程內**
  —— 它們分佈在 `jarvis/`、`ch3_lab/`、`quant-service/brain_alpha/`,全是互動或 local_cron 執行,不是 pythonw 排程進入點。
  **沒有為了「統一」去動它們。**
- `c09a2486` 宣稱補的兩處**已確認在檔案裡**(不是只在回報裡):
  `WATCHDOG.md:125-136`、`2026-09-08_gate_health_inventory.md:30` 與 `:651-676`。

---

## 四、🔴 ⑧ `Stock009816Monitor` —— 診斷與建議改法(**我沒有動它**)

`C:\Users\User\.stock_monitor\monitor.py`,不在本 repo,是 Carson 的錢線。
派工單 §二.B 要求先回報 ⇒ **只讀、只診斷,一個位元組都沒改**(指紋見 §五)。

### 4.1 它現在是壞的,而且沒有人看得見

- 排程:每 15 分鐘,`pythonw.exe`,Interactive/Limited。
- **`LastTaskResult = 1`**,最後一次執行 2026-09-08 13:45。
- 而 `state.json` 的 mtime 是 **13:15** ⇒ **13:30 與 13:45 兩輪都沒有走到 `save_state()`**。
- `snapshot_sent` 仍是 `false`,而快照的觸發條件是 `now >= 13:25` ⇒
  🔴 **2026-09-08 的收盤快照沒有送出,而且沒有任何訊號。**

### 4.2 三個缺陷(對應派工單的三種失敗形態)

1. **`fetch_price():29-50` 完全沒有例外處理。** 網路/TWSE 逾時 → 例外穿出 `main()` →
   traceback 寫向 `sys.stderr`(是 `None`)→ **靜默死亡,rc=1**。
   `:77` 的 `return 1` 也是 rc=1 ⇒ **兩種完全不同的失敗在外面長得一模一樣。**
2. **`tg():53-57` 的回傳值三處全被丟掉**(`:96`、`:100`、`:107`)。
   最危險的是 `:100-102`:推播回 `ok=False`(HTTP 200 但 `{"ok":false}`,例如 chat 被封)時,
   **`buy_alerted` 仍被設成 True 並存檔** ⇒ **當天的加碼點訊號永久消失**。這條的後果是錢。
3. **沒有任何 log 檔。** 全檔唯一的輸出是 `print`(`:77,96,102,109,112`),在 pythonw 下是條件 B ⇒ 全部靜默。
   而 **Task Scheduler 的 Operational log 在這台機器上是 `IsEnabled=False`** ⇒
   `LastTaskResult` 是**唯一**紀錄,而且只有一格、每輪覆蓋、要有人去開工作排程器才看得到。

### 4.3 建議改法(三行等級,**等 wF:p3 / Carson 點頭再動**)

1. `fetch_price()` 包 try,失敗回 `None`(它的呼叫端 `:76` 已經處理 `None` 了)。
2. `tg()` 的回傳值要看:`ok` 為 False 就**不要**設 `buy_alerted` / `snapshot_sent`,下一輪(15 分鐘後)自然重試。
3. 加一個 `monitor.log`(同 `uat_watch.py:41` 的寫法,那支就在隔壁且已驗證有效),
   把每輪結果與失敗原因落檔;`print` 保留當第二條路。

⚠️ 順帶(不是這一棒的事,但看到了):`config.json` 的 `_comment_position` 欄位是 **Big5 亂碼**。
不影響邏輯(沒有程式讀它),但下次動這個檔的人會看到亂碼。

### 4.4 我沒有做、也建議不要順手做的

- **沒有** `--test` 跑它(那會真的推一則訊息到 Carson 手機)。
- 我對 Telegram 只用了 **`getMe`**(唯讀,不送訊息)確認 token 與連線正常 ⇒ **token 是好的**,
  所以 09-08 那兩次失敗是別的原因(最可能是網路或 TWSE 端瞬時失敗)。
- **沒有**把 ⑤ 的 `CarsonQuant_PCRender` 排程工作刪掉:它已無用途(`--pc` 需要的 `cloud.json` 不存在,
  droplet 早停權),且觸發器只有 Logon、最後一次執行 2026-08-29 rc=267014(被終止)、目前沒有任何 hybrid_render 程序在跑。
  **刪不刪是 Carson 的決定**,腳本現在會把這句建議寫進 log。

---

## 五、正式機指紋(動手前後)

| 檔案 | 前 blob | 後 blob | 說明 |
|---|---|---|---|
| `scripts/seeding_watch.py` | `8c84310f` | `42bddc0e` | 範本 §4.1+§4.2 |
| `scripts/narration_compliance_watch.py` | `d87e0d39` | `aae25b6f` | 同上 |
| `scripts/quota_ceiling_watch.py` | `f4da027e` | `4faaea87` | 同上 + 基準判準 + 原子寫 |
| `youtube_channel/scripts/hybrid_render.py` | `61422e1c` | `f594bf44` | ⑤ |
| `youtube_channel/scripts/auditability_coverage.py` | `935a8690` | `0f862b5b` | 只加註解射程限制 |
| `quant-service/data_hunter/eod.py` | `3458fd60` | `bc266573` | 註解更正 + 摘要用詞 |
| `quant-service/data_hunter/scan.py` | `8b8af8b6` | `d8496fc3` | broadcast 回傳值 |
| `/d/yuanta-api/uat_watch.py`(repo 外) | `30492a58` | `e44ef7bc` | ⑨ |

**未被碰過(逐一比對 size + mtime + sha256,前後一致)**:
`C:\Users\User\.stock_monitor\{monitor.py, state.json, config.json}`(⑧,`monitor.py` sha `77ef35c655b39ad9`)、
`/d/yuanta-api/{uat_watch_state.json, uat_watch.log}`、
`docs/ops/quota-ceiling-watch.state.json`。

**臨時排程工作**:`zz-claude-stdio-probe-pythonw` / `-python` 各 1 個,**跑完立刻刪**,
事後 `Get-ScheduledTask | ? TaskName -like 'zz-claude*'` = **0 筆**、python 排程總數回到 **23**。

---

## 六、留給下一棒

1. **⑧ 的三個改法在 §4.3**,等點頭。它現在每天有兩輪在失敗,而收盤快照已經漏掉至少一次(09-08)。
2. **Task Scheduler Operational log 是關的**(`IsEnabled=False`)。
   ⇒ 全機 23 支排程的 exit code **沒有任何歷史**,只有一格會被覆蓋的 `LastTaskResult`。
   要不要打開它是一個獨立決策(有 10MB 上限、會寫磁碟),但**在它打開之前,任何「靠 exit code 就看得到」的設計都是空的**。
3. **⑤ 的排程工作要不要 Unregister**(§4.4),Carson 拍板。
4. 驗證 §五 那兩項「降級的觀察」我**沒有處理**:narration 的「旁白全部讀不掉」仍是 rc=0 不推播;
   留痕仍分不出 push 為什麼回 False(`notify.push` 自己的逐後端診斷是 `print`,pythonw 下消失)。
   後者的修法是讓 `notify.push` 回傳原因而不只是 bool —— 那會動到**所有**呼叫端,應該單獨開一棒。
5. **本檔的三支哨改動我不自驗**(`dispatch.md` §6)。上面所有實測都是我自己跑的,
   請比照 `c09a2486` 另派 fresh-context agent。
