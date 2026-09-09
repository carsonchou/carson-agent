# 交棒檔 — wB:p1 第三棒(/clear 前)

> 寫這份的理由:context **412.2K**,`dispatch.md` 的線是 **200K**。
> 412K 接新工作 = 同樣的 tool call 吃 6.7 倍 token(memory `claude-context-budget-2026-09`),
> 而撞頂是**靜默停擺**、零訊號(memory `usage-limit-silent-stall`)。
> **交棒優於 compact** —— compact 自己要讀完整個 context,還會丟早期指示。
>
> 監督:wF:p3。下一件工作的規格在 `docs/ops/2026-09-09_ch3_recurrence_test_spec.md`(`5bab32f6`)。

---

## 〇、/clear 之後第一件事

**讀 `docs/ops/2026-09-09_ch3_recurrence_test_spec.md`,不要讀本檔當規格。**
本檔只回答一個問題:**「上一棒手上有沒有只活在逐字稿裡的東西?」**
答案是:**有一件**(§一),其餘全部已 commit。

---

## 一、🔴 唯一一件需要處置的:一份轉抄進來的核准

wF:p3 從我的輸入框逐字抄出一份**沒送出的草稿**,原文:

```
drill regression 那支排進排程,我核准了
```

已落檔在規格檔 `:41`(§0.3)⇒ **它活得過 /clear,不會再掉**。

**處置方式(下一棒要做的)**:

1. ⚠️ **先跟 Carson 確認一句**:那是輸入框裡**沒送出**的草稿,而
   memory `herdr-pane-read-prompt-traps` 明記「**輸入框的字未必是別人打的**」。
   wF:p3 說「那是一份核准,不是我的」⇒ 來源指向 Carson,但**我沒有直接收到過它**。
   ⇒ 動手前用一句話確認,不要拿轉抄當授權。(這不是懷疑 wF:p3,是這條 memory 的標準流程。)
2. 確認後:**排進排程 = 寫正式機 ⇒ 仍要過一次 fresh-context 獨立驗證**(CLAUDE.md,有授權也不免驗)。
3. 註冊指令**已備妥**,在 `docs/ops/2026-09-09_pythonw_stdio_correction.md` §六.6,原文照抄即可。
   ⚠️ 註冊後**必須回讀 `NextRunTime` 確認非空** —— `WATCHDOG.md:24` 記著:
   只掛登入觸發會「註冊成功但永遠不會跑」,那個坑 09-03 踩過。
4. 排進去之後,`WATCHDOG.md` 那句「🔴 另一半還沒處理」要就地更正
   —— 否則它會變成下一個人讀到的過時規格(memory `detector-failure-shapes-2026-09`)。

---

## 二、這一棒做完的(**全部已 commit,不要重做**)

| commit | 件 |
|---|---|
| `bb7ea299` | 三種形狀實測 + 母體掃描 ④~⑨ + 範本先修(`_SWALLOWED` 綴判決行 / `finally` 收尾行 / `pushfail`·`pushraise`)+ quota 基準判準改 `state_existed` + 原子寫 |
| `fd70104b` | ⑧ 009816 第一輪(`fetch_price` 包 try / `tg()` 回傳值 / `monitor.log`)+ 獨立驗證逼出的三處修正 |
| `4f8bdbe1` | ⑧ 第二輪(rc 2→3 / 加碼與快照各自獨立嘗試 / 排程 Duration `PT4H45M`→`PT5H30M`) |
| `f6ea476b` | ③口徑混用就地標注 ④`watch_drill_regression.py` + WATCHDOG 演習清單 ⑤quota 空對照改成寫真檔案 |

**指紋鏈(`monitor.py` 在 repo 外,git 不會記得它被改過)**:
`77ef35c655b39ad9`(4,346 B)→ `a0fd9a605d99ce38`(9,488 B)→ **`d28b8ac09582c0fa`(10,452 B,線上現況)**。
兩份耐久備份都在 `C:\Users\User\.stock_monitor\`,可回滾到任一輪。
**唯一的紀錄是 `docs/ops/2026-09-09_pythonw_stdio_correction.md` §五。**

---

## 三、承重結論(引用時要連限制一起帶)

1. **排程下的標準輸出是三種形狀,不是兩種。**
   A 終端機跑 pythonw(繼承 handle,**最會騙人**)/ B 排程+pythonw(都是 `None`)/
   C 排程+`python.exe`(**有效 handle 指向沒人看得到的 console,寫成功然後蒸發,連例外都沒有**)。
   ⇒ 那 14 支 `python.exe` 排程要照 C 講,**不要併進 B**。

2. **排程 Duration 拉長那件:真行為證據已經有了(`f67288f9`,不要重做)。**
   14:00 / 14:15 / 14:30 三行都在、價格有效,`LastRunTime=14:30:00` / `rc=0`
   與 `09:00 + PT5H30M` 獨立對上。
   🔴 **引用時必須帶兩個限制**:
   - **陰性對照是儀器層面拿不到的** —— Operational 頻道 `IsEnabled=False`,
     且 log 歷史在改機時被換掉 ⇒ 拿不到「改之前同時段沒有那三行」的對照。
   - **今天 13:30 第一次機會就成功 ⇒ 延長出來的窗口沒有被用到**,
     **「重試路徑會動」還沒被證明**。已證的只有「窗口確實變長了」。

3. **兩處我講過而後來被實測推翻的,已就地撤回,不要再引用**:
   - ~~「拉長 Duration 買不到 TWSE 重試」~~ → 實測 13:30/13:45 全逾時、14:00 恢復 → 快照照樣送出。
     成立的只有更窄那句:**單次執行內 `fetch_price` 失敗時兩條分支都不嘗試**。
   - ~~「rc=2 會撞 Windows 的 `ERROR_FILE_NOT_FOUND`」~~ → 排程啟動失敗放的是 **HRESULT**
     (`2147942402` / `2147942405`),**裸的 2 只可能來自程式本身,從來沒撞過**。
     `2→3` 無害不必改回去。

4. **方法論(這一棒付過學費的)**:
   - **空對照出現三次**,形狀一樣:把被測的那半段跳過,而斷言照樣通過。
     ①`tcp_open` 一律 stub 成 False ⇒ 中斷分支根本沒走到(我自己抓到)
     ②quota 演習直接注入 `state_existed` ⇒ `STATE.exists()` 壞掉照樣過(驗證員抓到)
     ③`notified_open` 那個斷言為了錯的理由通過(我自己抓到)
     ⇒ **判準:寫完斷言後問「把被測的那個機制弄壞,這個對照會不會跟著失敗?」**
       本棒每一件都補了破壞測試,答案要是「會」。
   - **我製造過一次新盲點**:把「靜默死亡 rc=1」接住之後回 0,
     `LastTaskResult` 從 1 變成「0=看起來成功」而通知其實掉了。
     **接住例外的時候,要問接住之後那個訊號去哪了。**

---

## 四、還沒動、且**都需要拍板**的(不要順手做)

**錢線 `C:\Users\User\.stock_monitor\monitor.py`(紅線)**
1. `:163-166` 還留著一段**假理由**(rc 撞碼),已證不成立,要改但那是錢線 ⇒ 等點頭。
2. `chg` 歸零讓「單日跌 3%」那半條判準**靜默失效**(`:132`)。
3. `log()` 自己失效時沒有備援、rc 仍 0。
4. 電池兩個旗標都是 True ⇒ 沒插電整條線一次都不跑(拉長 Duration **沒有**解決這條)。
5. `StartWhenAvailable=False` + `NumberOfMissedRuns=3` ⇒ 錯過的輪次**永不補跑**。
6. trigger 是週一~週五 ⇒ **台股補班的週六靜默全失**。
7. 新買到的 14:00~14:30 可能落在 MIS 收盤後回**空 `msgArray`** 的區間。

**其他**
8. `watch_drill_regression.py` 還沒排程(見 §一)。
9. Task Scheduler Operational log 是 `IsEnabled=False` ⇒ 全機 23 支排程的 exit code **沒有歷史**。
   在它打開之前,**任何「靠 exit code 就看得到」的設計都是空的**。
10. ⑤ `CarsonQuant_PCRender` 要不要 Unregister(它已無用途)。
11. `notify.push` 只回 bool,分不出「沒設定」與「後端全失敗」—— 修它會動到所有呼叫端,單獨開一棒。

---

## 五、下一件工作(ch3 復發測試)最容易被略過的三條

規格全文在 `docs/ops/2026-09-09_ch3_recurrence_test_spec.md`。**以規格為準**,這裡只複述三條紅字:

1. 🔴 **不要取消 `crontab.txt` 775~777 的註解。** 那三行會開始發 `ch3_lab` 裡 **35 支舊題材庫存**,
   那不是這個測試,而且會**污染量測窗**。6 支要**新產**,走手動或一次性排程。
2. 🔴 **事前登記檔要在「產製之前」commit**,不是發布之前。
   **git log 的時間序要查得出來,事後補的沒有證據力。**
3. 🔴 **發布前一律過一次 fresh-context 獨立驗證**,有 Carson 授權也不免驗。三件:
   不是舊庫存改標題 / 登記檔真的在產製之前 / 常態排程沒被打開。

**回報節奏(回報給 wF:p3)**:事前登記 commit 後一次 → 獨立驗證通過且**發布之前**一次 → 發布之後第三次。
