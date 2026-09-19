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
⇒ 用詞要分兩層(2026-09-09 補記,承驗證 `97dfb42b` §六①):
**`State=Ready` 的是 8 支**(只有 `UptimeMonitor` 是 Disabled);
其中 `CarsonQuant_PCRender` 雖然 Ready,但觸發器只有 Logon、且進 `--loop` 之前就早退
⇒ **實際會週期性跑起來的是 7 支**。
⚠️ 我原本只寫「活著的是 7 支」,把自己的**判斷**寫成了系統的**狀態** —— 那正是 memory
`read-the-sibling-tool-first` 那條病(寫斷言前問「主詞是世界還是我」)。

### ④~⑨ 逐支結論(格式照派工單 §三.1)

| # | 工作名 | 進入點:行號 | 有沒有到得了讀者的通道 | 沉默的後果 | 處置 |
|---|---|---|---|---|---|
| ④ | `LocalCronWatchdog` | `local_cron_watchdog.py:76` `_log()` / `:128` `_push()` | **有**(log 檔為主 + ntfy,且 `:186` **有看 push 回傳值**,沒送出就不記冷卻) | — | **不改**。真環境陽性對照:09-08 08:12:58 它在 pythonw 下寫了 log、拉起排程器、推播成功 |
| ⑤ | `CarsonQuant_PCRender` | `hybrid_render.py:408-414` | 🔴 **沒有**(唯一那則操作員訊息寫 `file=sys.stderr`) | 「這個排程工作已無用途,可以 Unregister」這句話 **08-29 寫下後從沒有人讀到過** | **已改**:改走 `_operator_note()`,主通道寫 `logs/hybrid_render_pc.log` |
| ⑥ | `CarsonQuant-UptimeMonitor` | `monitor.py:19-24` `TARGETS` | n/a | 無 | **不改**。**Disabled**(2026-07-11 起)**且 `TARGETS` 是空清單** —— 唯一目標(雲端 droplet)已註解掉。即使啟用也監控不到任何東西 |
| ⑦ | `DataHunter-EOD` | `eod.py:42-47` | **有**。偵測到 `pythonw` 就把 `sys.stdout/stderr` 導向 `logs/eod_YYYYMMDD.log` | — | **註解更正 + 兩處留痕**(見 §三) |
| ⑧ | `Stock009816Monitor` | `monitor.py:73-113` | 🔴 **完全沒有**(只有 `print`,無 log 檔) | **Carson 錯過加碼點/收盤快照,零訊號** | **已修**(wF:p3 授權後,走完獨立驗證才上機)。見 §四;`77ef35c655b39ad9`→`a0fd9a605d99ce38` |
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

## 四、🔴 ⑧ `Stock009816Monitor` —— 已修(wF:p3 2026-09-09 授權「那三行照建議改」)

`C:\Users\User\.stock_monitor\monitor.py`,不在本 repo,是 Carson 的錢線。
派工單 §二.B 要求先回報 ⇒ 先只讀只診斷;**回報後 wF:p3 點頭才動手**。
紅線流程照 CLAUDE.md 走完:候選寫 scratchpad → 沙箱對照 → **獨立驗證(fresh-context opus)** → 才上機。
指紋:`77ef35c655b39ad9` → `a0fd9a605d99ce38`(9,488 bytes)。
原檔備份在 scratchpad `monitor_ORIGINAL_backup.py`(sha 與動手前正式機一致),可一行回滾。

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

### 4.3 已實作的三件(＋獨立驗證逼出來的三處修正)

1. `fetch_price()` 包 try,失敗回 `None`(`:65-69` 連線/解析、`:71-73` 空 msgArray、`:88-90` 無有效價)。
2. `tg()` 一律回 bool 並把原因寫 log(`:102-110`);呼叫端**送出去才准推進旗標**(`:167-174`、`:178-192`)。
3. `monitor.log`(`:24`、`:27-39`),寫法沿用 `uat_watch.py:41`;`print` 保留當第二條路。

**獨立驗證員(fresh context, opus)找出三處,都已修** —— 它的價值不在背書,在這三件:

| # | 抓到什麼 | 為什麼要緊 | 處置 |
|---|---|---|---|
| a | **`--test` 的 exit code 被我改掉了**(原版恆 0) | 超出授權的三件事,且與「抓價失敗 rc=1」撞碼 | **還原成恆 0**(`:148-153`) |
| b | **推播失敗仍回 0 = 我自己製造的新盲點** | 舊版 `tg()` 拋例外時行程死掉 ⇒ rc=1;我把例外接住後若照樣回 0,`LastTaskResult` 會從「1」變成「0=看起來成功」,而通知其實掉了 | 兩條推播失敗路徑改 **rc=2**(和 rc=1 分得開) |
| c | **falsy 陷阱仍在**:`num("b") or num("h") or num("o")` 在三者皆 `0.0` 時回 `0.0`(不是 `None`) | `0.0 <= 14.0` 成立 ⇒ **推一則假的加碼點通知**。原版同病、非本次引入,但我的新守衛就在那一行旁邊 | 守衛改成 `if not price or price <= 0`(`:88`) |

### 4.4 🔴 最重的一項:**「下一輪重試」對收盤快照近乎空話**(排程要另外決定)

驗證員提出,我**獨立複查排程定義證實**:
`StartBoundary 09:00` + `Repetition Interval=PT15M` + **`Duration=PT4H45M`** + `DaysOfWeek=Mon–Fri`
⇒ **當天最後一輪是 13:45**。而快照門檻是 `now >= 13:25`
⇒ **一天只有 13:30 與 13:45 兩次機會;13:45 這次失敗,當天就沒有下一輪**(週五要等到週一)。
**09-08 掉的那則就是這樣掉的**(LastRunTime 13:45 / rc=1 / `snapshot_sent` 仍是 false)。
另:`DisallowStartIfOnBatteries=True` + `StopIfGoingOnBatteries=True` ⇒ 沒插電時整條線一次都不跑。

⇒ **我沒有動排程**(授權範圍是那三行;改觸發器是另一類正式機變更)。
但程式碼裡那句「下一輪重試」已改成講實話(`:183-191`),log 也會把這件事印出來
—— 否則那就是一句寫在註解裡、下一個人會當規格的假話。
**要真的有重試,得把 `Repetition Duration` 從 `PT4H45M` 拉到約 `PT5H30M`(跑到 14:30,快照留 5 次機會)
—— 這一項等 Carson 拍板。**

### 4.5 實測(沙箱,真實 Telegram 0 次)

合成 config(**假 token,真 token 不進 temp 目錄**)+ 入口把 `tg` 換掉並斷言 + `urlopen` 換成會炸的守衛。
六組共 15 項全過:①抓價連線失敗 → rc=1 且 log 說得出原因 ②加碼點推播失敗 → rc=2、`buy_alerted` 不前進
③加碼點推播成功 → rc=0、旗標前進(不會每 15 分洗版)④快照推播失敗 → rc=2、`snapshot_sent` 不前進
⑤**陰性對照**:無動作 → `tg` 零呼叫、rc=0、仍留一行正向輸出
⑥`b/h/o` 全 `0.0` → rc=1、**零推播**(假加碼點被擋住)。

**真環境端到端**(2026-09-09 05:51:48,`Start-Process pythonw`、無 console、跑正式機那一份):
rc=0,`C:\Users\User\.stock_monitor\monitor.log` 長出
`[2026-09-09 05:51:48] 無動作 price=16.12 chg=-0.31% buy=False`
⇒ **這條線上第一次有「今天它跑過、而且一切正常」的正向證據。**
跑之前先確認兩條推播路徑都不成立(price 16.12 > 14.0、chg −0.31% > −3%、05:51 < 13:25)⇒ 不會誤送。

⚠️ 順帶(不是這一棒的事,但看到了):`config.json` 的 `_comment_position` 欄位是 **Big5 亂碼**。
不影響邏輯(沒有程式讀它),但下次動這個檔的人會看到亂碼。

### 4.7 第二輪(2026-09-09,Carson 核准三件;上機後獨立驗證 `7ef69070` 的第 1、2 點併入)

指紋 `a0fd9a605d99ce38`(9,488 B)→ **`d28b8ac09582c0fa`(10,452 B)**。
`diff` 只有一塊(71 行),`chg` 歸零那條(`:132`)與 `log()` 的 `except: pass`(`:34-35`)**逐字未動**
—— 那兩件(驗證 §3、§4)**沒有被核准,本輪刻意不碰**。

**① rc `2` → `3`**(推播失敗的兩條路徑)。

> 🔴 **2026-09-09 更正:下面那個理由是假的,別再拿它當規格**
> (第二輪獨立驗證用實驗推翻,見 `2026-09-09_verify_009816_round2.md` §一)。
> 六個臨時排程工作實測:**排程自己啟動失敗放的是 HRESULT** —— 找不到執行檔/路徑錯 → `2147942402`(`0x80070002`)、
> 權限不足 → `2147942405`(`0x80070005`);而程式真的 `exit 2` → `2`、`exit 3` → `3`。
> ⇒ **裸的 `2` 只可能來自程式本身,從來沒有和「排程沒啟動起來」撞過。撞碼不存在。**
> 改動本身無害(3 同樣沒問題),**不必改回去**;要修的是理由。
> ⚠️ 這個錯的傳播路徑:第一輪驗證員提出 → **wF:p3 沒查證就轉述** → 寫進程式碼註解。
> 🔴 **`C:\Users\User\.stock_monitor\monitor.py:163-166` 那段註解仍然寫著這個假理由,還沒改**
> —— 那是錢線檔案,動它要 Carson 授權,已回報。

~~理由不是美觀:**`2 = 0x2` 是 Windows 的 `ERROR_FILE_NOT_FOUND`**,在 `LastTaskResult` 上
和「排程根本沒把程式啟動起來」同值。~~
(仍然成立的那半:本機 `TaskScheduler/Operational` 是 `IsEnabled=False`
⇒ **`LastTaskResult` 是唯一那一格**、會被下一輪覆蓋。那是真的,只是它不構成撞碼。)

**② 加碼與快照改成各自獨立嘗試**。
驗證 §2 講的是「加碼**觸發**就壓掉快照」,但真正咬人的形狀更嚴、而且**不會自己癒合**:
排程拉長後,「加碼**成功**所以壓掉快照」下一輪就補得回來(`buy_alerted` 已是 True);
**加碼一直失敗那條不會** —— `buy_alerted` 留 `false` ⇒ 每一輪都重試加碼、每一輪都在快照之前 `return`
⇒ **一次持續性的 Telegram 中斷,會讓快照當天連一次都沒被嘗試過**,而那正是最需要快照的那天。
⇒ 兩條各自跑、各自留痕,最後統一存檔一次。
**exit code 合併成 3(任一條掉了就是 3);要分辨是哪一條掉的看 log** —— rc 只有一格,塞不下兩件事。

**③ 排程 `Repetition.Duration` `PT4H45M` → `PT5H30M`**。
改法是取出既有 task 物件、**只改 `Triggers[0].Repetition.Duration` 再 `Set-ScheduledTask -InputObject`**,
principal / settings / actions 都沒有重建。
逐欄比對 20 個欄位:**只有 `Duration` 變了**(`Exec`/`Args`/`UserId`/`LogonType`/`RunLevel`/`Enabled`/
`DisallowBatt`/`StopBatt`/`MultInst`/`ExecLimit`/`StartWhenAvail`/`TrigCount`/`Start`/`Days`/`Interval`/
`NextRun`/`LastRun`/`LastRc` 全部相同)。觸發器 `Enabled` 回讀 = `True`。

⚠️ **它沒有解決電池那條**:`DisallowStartIfOnBatteries` 與 `StopIfGoingOnBatteries` **都還是 True**
⇒ 沒插電時整條線一次都不跑,跑到一半拔電也會被砍。**那件沒有被核准,本輪沒有動。**

#### 4.7.1 陽性 / 陰性對照(沙箱,真實 Telegram 0 次)

入口把 `tg` 與 `urllib.request.urlopen` 都換掉並**立刻斷言身分**,`finally` 還原(回報時已確認還原成功);
沙箱 config 用假 token。16 項全過:

| 對照 | 結果 |
|---|---|
| ★**②核心陽性**:加碼連續失敗 | `tg` 被呼叫 **2 次**(加碼+快照各一)、`rc=3`、兩個旗標都留 `false`、**log 分得出兩條各自掉了** |
| ②同輪兩條都成功 | `tg` 2 次、`rc=0`、兩旗標都 `True` |
| ①加碼成功但快照失敗 | `rc=3`、`buy_alerted=True` 而 `snapshot_sent=False` |
| **陰性 A**:正常日(非買點、未到 13:25) | `tg` **零呼叫**、`rc=0`、仍留一行「無動作」正向輸出 |
| **陰性 B**:當天兩則都推過 | `tg` **零呼叫**、`rc=0` |
| 回歸:抓價失敗 | 仍 `rc=1`(沒有被 `rc=3` 蓋掉) |

#### 4.7.2 排程那件的陽性對照(**回讀,不是算術**)

`Export-ScheduledTask` 拿 OS 自己存的註冊 XML:`Interval=PT15M` / **`Duration=PT5H30M`** / Mon–Fri / Start `09:00`。
依這組**回讀值**展開,當天 23 輪、最後一輪 **14:30**;落在快照門檻 13:25 之後的是
**13:30 / 13:45 / 14:00 / 14:15 / 14:30 共 5 次**(改前只有 13:30、13:45 兩次)。

⚠️ **沒查到的一項**:想用 `IRegisteredTask.GetRunTimes()` 讓 OS 自己列舉那幾個時刻(那才是最硬的證據),
但這台的 COM 繫結兩種呼叫法都回 `DISP_E_MEMBERNOTFOUND` ⇒ **拿不到 OS 列舉**。
所以上面那五個時刻是**從 OS 回讀的註冊值展開的**,不是從 OS 的排程佇列讀出來的 —— 差別要講清楚。
真正的行為證據要等 13:30 之後那幾輪跑過,看 `monitor.log` 有沒有出現 14:00 以後的行。

#### 4.7.3 今天 09:00 那輪:**沒有被影響**

改排程前後 `NextRunTime` 都是 `2026-09-09 09:00:00`(逐欄比對表裡是 `same`)。
另外上機後在 06:47 用 `Start-Process pythonw`(無 console)實跑一次線上那份:
`rc=0`、`monitor.log` 長出 `[2026-09-09 06:47:04] 無動作 price=16.12 chg=-0.31% buy=False`、
**`state.json` 前後逐字相同**(`buy_alerted`/`snapshot_sent` 都還是 `false`)⇒ 沒有吃掉今天任何一個訊號。
跑之前先確認兩條推播路徑都不成立(06:47 < 13:25、16.12 > 14.0)。

### 4.8 我沒有做、也建議不要順手做的

- **沒有**用 `--test` 跑它(那條路一定會推一則真訊息到 Carson 手機)。
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
| `quant-service/data_hunter/eod.py` | `3458fd60` ⚠️**工作區,非 git parent** | `bc266573` | 註解更正 + 摘要用詞;**另收編 12 行**,見下方 |
| `quant-service/data_hunter/scan.py` | `8b8af8b6` | `d8496fc3` | broadcast 回傳值 |
| `/d/yuanta-api/uat_watch.py`(repo 外) | `30492a58` | `e44ef7bc` | ⑨ |

### 🔴 這張表的口徑不一致 —— eod.py 那一列(2026-09-09 補記,承驗證 `97dfb42b` §三)

上表七列的「前 blob」等於 git parent(工作區與 HEAD 一致),**只有 `eod.py` 那一列的「前」是工作區**。
差別是真的:`eod.py` 在 `bb7ea299^` 的最後一次 commit 是 **`244c18fe` / 2026-07-03**,
git parent 的 blob 是 **`942accfd`**,而我表上寫的 `3458fd60` 是**我編輯前的磁碟檔**。

原因:那段偵測 `pythonw` 並把 stdout 導向 `logs/` 的程式碼**從 2026-08-11 就在跑**
(`quant-service/data_hunter/logs/` 有 `eod_20260811.log` 起連續 29 個檔為證),
但**從來沒有進過 git**。⇒ `bb7ea299` 對 git 而言是 `+26/-1`,其中
**12 行不是本輪寫的,是本輪一併收編的**,而 commit 訊息沒有講。

可機械複核:
```
git rev-parse bb7ea299^:quant-service/data_hunter/eod.py      # -> 942accfd
git diff --numstat 942accfd 3458fd60                          # -> 12  0  (本輪之前就在磁碟上的)
git diff --numstat bb7ea299^ bb7ea299 -- .../eod.py           # -> 26  1  (git 看到的總量)
```

⚠️ **這不是造假,是口徑混用**,但後果是實的:它讓「本輪改了多少」看起來比實際大,
而讀者無從分辨哪些是本輪寫的、哪些是本來就在跑只是沒進版控的。
(驗證員記為 +22 行;我用上面第二條指令實算是 **12 行**,以指令輸出為準。)

---

**⑧ 已授權改動(兩輪)**:`monitor.py`
`77ef35c655b39ad9`(4,346 B,原版)
→ `a0fd9a605d99ce38`(9,488 B,第一輪 `fd70104b`)
→ **`d28b8ac09582c0fa`(10,452 B,第二輪 §4.7,線上現況)**
每一輪都是 tmp→`os.replace` 寫入、回讀逐位元組與候選一致、再換獨立儀器 `sha256sum` 複查。

🔴 **`monitor.py` 在 repo 外,git log 不會記得它被改過 —— 這張表是唯一的紀錄。**
耐久備份兩份都在 `C:\Users\User\.stock_monitor\`,可一行回滾到任一輪:
`monitor.py.bak-20260909-pre-fd70104b`(4,346 B)、`monitor.py.bak-20260909-post-fd70104b`(9,488 B)。

**排程 `Stock009816Monitor`**:`Repetition.Duration` `PT4H45M` → **`PT5H30M`**(§4.7),
其餘 19 個欄位逐欄比對前後相同。

**未被碰過(前後 sha 一致)**:`C:\Users\User\.stock_monitor\{state.json, config.json}`
(⚠️ `state.json` 在事後那次端到端實跑中依設計換日成 `2026-09-09` —— 等同 09:00 那輪本來就會做的事,不是額外損失)、
`/d/yuanta-api/{uat_watch_state.json, uat_watch.log}`、
`docs/ops/quota-ceiling-watch.state.json`。

**臨時排程工作**:`zz-claude-stdio-probe-pythonw` / `-python` 各 1 個,**跑完立刻刪**,
事後 `Get-ScheduledTask | ? TaskName -like 'zz-claude*'` = **0 筆**、python 排程總數回到 **23**。

---

## 六、留給下一棒

1. **⑧ 兩輪都已上機**(§四、§4.7),排程 Duration 也已拉到 `PT5H30M`。
   **剩下四件都還沒動,且都需要拍板**:
   ①`chg` 歸零讓「單日跌 3%」那半條判準靜默失效(驗證 `7ef69070` §3)
   ②`log()` 自己失效時沒有備援、rc 仍 0(同 §4)
   ③電池那兩個旗標都還是 True(§4.7)
   ④`fetch_price` 失敗時加碼與快照**都不嘗試**(同附註)。
   ~~⚠️ ①③④ 合起來還有一個沒人算過的組合:**TWSE 在 13:30~14:30 那五輪全部逾時 = 當天仍然全失**
   —— 拉長 Duration 買到的是「Telegram 掉了可以重試」,買不到「TWSE 掉了可以重試」。~~
   🔴 **已撤回(驗證 `616dec76` 實測推翻)**:13:30 / 13:45 全逾時、14:00 恢復 ⇒ 快照照樣送出。
   ⇒ 拉長 Duration **也**買到了 TWSE 的重試。成立的只有更窄的一句:
   **單次執行內 `fetch_price` 失敗時,加碼與快照兩條分支都不嘗試**(`:129-130` 直接 return 1)。

   🔴 **另外四個訊號吞噬點(驗證 `616dec76` §四,全部未授權,先不要動)**:
   `StartWhenAvailable=False` + `NumberOfMissedRuns=3` ⇒ 錯過的輪次**永不補跑**;
   trigger 是**週一~週五** ⇒ **台股補班的週六靜默全失**;
   新買到的 14:00~14:30 可能落在 MIS 收盤後回**空 `msgArray`** 的區間;
   `MultipleInstances=IgnoreNew` + `ExecutionTimeLimit=PT72H`。
2. **Task Scheduler Operational log 是關的**(`IsEnabled=False`)。
   ⇒ 全機 23 支排程的 exit code **沒有任何歷史**,只有一格會被覆蓋的 `LastTaskResult`。
   要不要打開它是一個獨立決策(有 10MB 上限、會寫磁碟),但**在它打開之前,任何「靠 exit code 就看得到」的設計都是空的**。
3. **⑤ 的排程工作要不要 Unregister**(§4.4),Carson 拍板。
4. 驗證 §五 那兩項「降級的觀察」我**沒有處理**:narration 的「旁白全部讀不掉」仍是 rc=0 不推播;
   留痕仍分不出 push 為什麼回 False(`notify.push` 自己的逐後端診斷是 `print`,pythonw 下消失)。
   後者的修法是讓 `notify.push` 回傳原因而不只是 bool —— 那會動到**所有**呼叫端,應該單獨開一棒。
5. **本檔的三支哨改動我不自驗**(`dispatch.md` §6)。上面所有實測都是我自己跑的,
   請比照 `c09a2486` 另派 fresh-context agent。

6. 🔴 **`scripts/watch_drill_regression.py` 還沒有被排進任何排程 —— 引信仍然要人按。**
   它把 12 格演習(陽性 9 + 陰性 3)收成一個指令,每次跑寫一行
   `docs/ops/watch-drill-regression.log`(全過也寫),失敗回 `rc=1` 並指名是哪一支的哪個模式。
   破壞測試已證明它不是恆真的(把 `swallow_epilogue` 改成 `return` → `10/12` + `rc=1`,還原後回 `12/12`)。
   三支哨是 Windows 排程工作(不在 `crontab.txt`),所以它的家也該是排程工作,
   而**新增排程工作屬於另一類正式機變更,等 Carson 拍板**。核准後的註冊指令(每天台北 07:30,
   principal 抄三支哨:User / Interactive / Limited):

   ```powershell
   $P = New-ScheduledTaskPrincipal -UserId 'User' -LogonType Interactive -RunLevel Limited
   $A = New-ScheduledTaskAction -Execute 'D:\carson-agent\youtube_channel\.venv\Scripts\pythonw.exe' `
        -Argument 'D:\carson-agent\scripts\watch_drill_regression.py' -WorkingDirectory 'D:\carson-agent'
   $T = New-ScheduledTaskTrigger -Daily -At 07:30
   Register-ScheduledTask -TaskName 'carson-watch-drill-regression' -Action $A -Trigger $T -Principal $P
   ```
   ⚠️ 註冊後要**回讀 `NextRunTime` 確認非空** —— 本檔上面記過:只掛登入觸發會「註冊成功但永遠不跑」。

7. 🔴 **`C:\Users\User\.stock_monitor\monitor.py:163-166` 還留著一段假理由**
   (「rc=2 會撞 Windows 的 `ERROR_FILE_NOT_FOUND`」)。驗證 `616dec76` 用六個臨時排程工作實測:
   排程自己啟動失敗放的是 **HRESULT**(找不到執行檔 → `2147942402` / `0x80070002`;
   權限不足 → `2147942405`),而程式真的 `exit 2` → `2`、`exit 3` → `3`
   ⇒ **裸的 `2` 只可能來自程式本身,從來沒撞過**。
   `2→3` 這個改動本身無害、不必改回去,**要修的是註解裡那段理由**。
   ⚠️ 那是錢線檔案 ⇒ **等 Carson 點頭才能動,本輪沒有碰。**
