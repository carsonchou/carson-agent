# 派工單 — wB:p1 第三棒:把「stderr 在排程下是 no-op」這條更正帶出去

> 派工者:wF:p3(基建線接棒,承 `docs/ops/2026-09-09_handoff_infra.md` §三)
> 開單時間:2026-09-09 03:0x(台北)
> 前置驗收:已跑。你的 session **assistant 163 筆、`[provider/model]` 前綴 0 筆、全程 `claude-opus-5`**;
> 陽性對照(舊 session)抓得到 1 筆 ⇒ 儀器是準的,你沒有被釘在 gateway 上。**這一格已通過,不用再驗。**

---

## 🔴 開工第一件事:`/clear`

你現在 **264.3K context**,而 `dispatch.md` 的交棒線是 **200K**。
今晚全機撞過一次額度上限,成因就是幾支超大 context 的 session(同樣 500 次 tool call,
800K 花 400M token、120K 只花 60M ── 做的事一樣差 6.7 倍)。

**你手上沒有只活在逐字稿裡的東西了** —— 我查過:`c09a2486` 已 commit,三支的
工作目錄 blob 與 HEAD 完全一致(`8c84310f` / `d87e0d39` / `f4da027e`),
而你回報裡那兩件「留給下一棒判斷」的事我抄在本檔第五節了。

⇒ **先 `/clear`,再讀本檔,然後開工。** 不要 compact(它自己要讀完整個 context,還會丟早期指示)。

---

## 一、目標與動機

### 這條更正是什麼

你上一棒實測出來的環境事實(`c09a2486`):

| 環境 | `sys.stdout` / `sys.stderr` | `print(msg, file=sys.stderr)` | 到得了讀者嗎 |
|---|---|---|---|
| Windows 排程工作 + `pythonw.exe` | **兩個都是 `None`** | **靜默 no-op** | ❌ |
| 互動終端 / `local_cron` 的 job | 正常 | 正常(f550a66a 之後進 `logs/jobout/`) | ✅ |

⇒ 它**推翻了我(基建線)在 `8bfaa829` commit 訊息裡寫的通用修法建議**(我當時說「印到 stderr 就好」)。
那個建議只對 `local_cron` 的 job 成立,對 Windows 排程工作不成立。

### 為什麼這一棒不是文件整理,是一次母體掃描

`8bfaa829` 的 commit 訊息改不了,而它會被下一個人當範本抄。
但**真正的風險不在那句話,在還沒有人去看的那 6 支**:

我剛量的母體 —— 全機 **23 個 python 排程工作,其中 9 支跑 `pythonw.exe`**(= `stdout`/`stderr` 皆 `None` 的環境):

| # | 排程工作 | 進入點 | 狀態 |
|---|---|---|---|
| 1 | `carson-seeding-watch` | `scripts/seeding_watch.py` | ✅ 你上一棒已修 |
| 2 | `carson-narration-compliance-watch` | `scripts/narration_compliance_watch.py` | ✅ 已修 |
| 3 | `carson-quota-ceiling-watch` | `scripts/quota_ceiling_watch.py` | ✅ 已修 |
| 4 | `LocalCronWatchdog` | `youtube_channel/scripts/local_cron_watchdog.py` | 🔴 **沒人看過** |
| 5 | `CarsonQuant_PCRender` | `youtube_channel/scripts/hybrid_render.py --pc --loop` | 🔴 **沒人看過** |
| 6 | `CarsonQuant-UptimeMonitor` | `D:\claude\external-tools\uptime-monitor\monitor.py` | 🔴 **沒人看過** |
| 7 | `DataHunter-EOD` | `eod.py --push` | 🔴 **沒人看過** |
| 8 | `Stock009816Monitor` | `C:\Users\User\.stock_monitor\monitor.py` | 🔴 **沒人看過**,而且**這是 Carson 的錢線** |
| 9 | `YuantaUATWatch` | `D:\yuanta-api\uat_watch.py` | 🔴 **沒人看過** |

四、五、八三支特別要緊:
- **④ 是守望的守望** —— 它沉默的話,「排程器死了」這件事沒有第二個人會說。
  而 handoff §一.3 記著它的「拉起排程器」路徑裝了五天沒被走過、一走就發現會拉起一個開跑就死的排程器。
- **⑤ 是產線渲染**,`--loop` 表示它一直在跑;它的錯誤如果只 print,渲染卡住會長得像「今天沒片可渲」。
- **⑧ 是 009816 盯盤**(memory `stock-009816-telegram-monitor`:到加碼點推 Telegram)。
  它的推播失敗路徑如果只 print,**Carson 會錯過一個買點而完全沒有訊號**。這條的後果是錢。

另外 14 支跑 `python.exe`(有 console 的那種)。**它們是第二種形狀,不要跟 pythonw 混為一談**:
`stdout` 不是 `None`,但排程沒有重導向 ⇒ 寫出去的東西一樣沒有人收得到。
**診斷不同、修法可能相同,但你必須分開量再分開講** —— 把兩種形狀混在一起講,
會讓「已經修好」的範圍聽起來比實際大(那正是 memory `verification-claims-in-commit-messages` 那條病)。

---

## 二、要做的事(按這個順序)

### A. 先量,不要先修

對上表 ④~⑨ 六支,逐支回答:**它有沒有一條到得了讀者的告警通道?**
判準用 handoff 教的那句:**「這件事沒被遵守/失敗時,系統會不會產生輸出?」** 不會 → 它是期望不是規則。

每支要看的至少三處(你上一棒自己歸納的失敗形態,直接沿用):
1. 例外處理裡有沒有 `print` / `sys.stderr` 當**唯一**通道
2. 推播/通知的**回傳值有沒有被看**(`notify.push()` 都沒設定 / 403 / 5xx 會回 `False` 而不拋例外)
3. `except: pass` / bare except 把「壞掉」吃成「沒事」的地方

⚠️ **不要用 grep 命中數當答案。** memory `static-reading-vs-runtime-behaviour`:
**錯的否定比錯的肯定危險一級** —— 「grep 沒命中所以它沒問題」是這一棒最可能犯的錯。
每支至少讀完它的 `main()` 和所有 `except`。

### B. 分級,再修

不是每一支都值得改。分級判準:**它沉默的後果是什麼?**
- 後果是錢或對外(⑧,可能還有⑦)→ 優先
- 後果是「產線壞了沒人知道」(④⑤)→ 次之
- 後果是「一個內部數字沒更新」→ 記下來,不一定要動

修法沿用你上一棒定案的形狀:**主通道寫 log 檔;`stderr` 只當互動/`local_cron` 下的第二條路,且 None-safe。**
⚠️ 沿用你自己的那條判準:**留痕的對象是「本來應該成功的事」,不是「本來就預期失敗的事」。**
(所以 `sys.stdout.reconfigure` 那種每輪必中的不要加留痕,它只會變雜訊。)

🔴 **⑧ `Stock009816Monitor` 動之前先停下來報我。** 它在 `C:\Users\User\.stock_monitor\`,
不在本 repo,而且是 Carson 的錢線 —— 那是 CLAUDE.md 紅線三類裡的「動錢」鄰接區。
你可以**讀**它、可以寫出改法,但**不要直接改**,先把診斷回報上來。

### C. 把更正落到「下一個人會讀到的那頁」

`8bfaa829` 的 commit 訊息是不可變的,所以更正要落在會被讀到的地方:
1. `grep` 全 repo 找還在教「印到 stderr」的**註解與文件**
   —— memory `detector-failure-shapes-2026-09`:**宣稱寫在程式碼註解裡比寫在 commit 訊息裡危險**,
   因為下一個人會拿它當規格。
2. 你 `c09a2486` 說已經補了盤點 §〇.1 的射程限制和 `WATCHDOG.md` 一節 —— **確認那兩處真的在檔案裡**
   (你回報過了,但回報和落檔是兩件事;memory `only-what-lands-on-disk-exists`)。
3. 掃的謂詞**不是「stderr」這個字**,是**「任何會因為這條更正而失效的敘述」**:
   「印一行就有人收得到」「照 X 那支的範本做」「排程的輸出在 log 裡」這類句子。
   (`dispatch.md`:數量詞、順序詞、指代詞、被撤回論證的殘影,grep 都抓不到。)

---

## 三、驗收條件(可客觀檢查)

1. **母體表**:上表 ④~⑨ 六支每一支都有一行結論,格式為
   `<工作名> | <進入點:行號> | 有/沒有到得了讀者的通道 | 沉默的後果 | 處置(改了/不改+理由)`。
   **「沒查」也要寫成「沒查」+ 為什麼**,不可以留空(handoff §一.3:「還沒發生」和「這條路是壞的」觀測上一樣)。
2. **`python.exe` 那 14 支**:至少給一句共同結論 + 一支的實測(不要外推,實測一支)。
3. **每一處改動都要有陽性對照**:讓那條失敗路徑真的發生一次,確認留痕出現;
   並附**陰性對照**(正常情況下不留痕)。你上一棒做得對,照做。
4. **隔離**:沙箱化 LOG/STATE,`notify.push` 在跑 `main()` **之前**換掉並執行期斷言 `is fake_push`。
   ⚠️ `dispatch.md` §6:派工單上的「絕對不要 X」如果違反時不產生輸出,它就是空的
   —— 所以請把禁令放在**入口**並補一格會產生輸出的斷言,不要只寫在心裡。
   ⚠️ 高風險形狀:任何**重新認證 / 重試 / 換 token** 的分支,讀碼像錯誤處理、執行期是一次真實對外呼叫。
5. **正式機指紋**:動手前後各記一次你碰過的正式機檔案 size+mtime,回報裡附上。
6. **⑧ 沒有被直接修改**(見 B 的紅字)。

---

## 四、回報格式(照 `dispatch.md` §4)

- 只回結論 + `檔案路徑:行號`;長產物落檔(`docs/ops/` 或 scratchpad)只給路徑 + 3 行摘要
- 明確標註失敗:沒找到就說沒找到 + 找過哪裡;做不到就說做不到 + 卡在哪
- **禁止**把整檔內容 / 完整 log 貼回來
- 每支改動附 **blob 指紋**(`git hash-object <file>` 前 8 碼)——
  memory `parallel-sessions-same-repo`:要別人獨立驗就給指紋,不要只給 commit hash
- commit 訊息裡**不要寫「已驗證」三個字來涵蓋你沒驗的那塊**
  (memory `verification-claims-in-commit-messages`:共同形狀 = 把「我這一段做到了」講成「整件事做到了」,
  而八次全發生在 commit 訊息裡 —— 那是唯一沒人逐句查證的文字)

---

## 五、你上一棒留在逐字稿裡的兩件(替你落檔,回答它們是這一棒的一部分)

1. **`swallowed()` 在三支各複製了一份(約 20 行 ×3)。**
   你判斷重複是對的取捨,理由是 `WATCHDOG.md:116-127` 記著它們刻意「和被監視的東西平行、不依賴產線」。
   **我同意這個取捨,不要抽共用模組。** 理由再加一條:這一棒可能還要再加第 4~9 支,
   共用模組會讓「哨依賴一個會被改的東西」這件事隨支數放大。
   ⇒ 但請在**其中一支**的 `swallowed()` 上方留一行註解說明「這是刻意的三份,理由見 WATCHDOG.md:116-127」,
   否則下一個人會把它當成待清理的重複碼。

2. **`quota` 的「基準被迫重建」你讓它推播但 exit code 維持 0。**
   **維持 0,不要改。** 理由:exit code 是別人(watchdog / 排程)在讀的判準,
   改它等於在同一輪裡動了兩個變數,而這一棒的母體掃描還要靠 exit code 當穩定基準。
   要升級成 rc=1 的話單獨開一棒,並先列出「誰在讀這個 exit code」。

---

## 六、不要做的事

- **不要驗你自己上一棒的產出**(`c09a2486`)。`dispatch.md` §6:寫的人不驗自己的產出。
  那件已經另派 fresh-context agent,結論會由 wF:p3 帶給你。
- **不要開平行 subagent**:本機可用記憶體 **549MB / 16GB**,今晚背景等待已被系統砍掉 5 次。
- **不要動 `deploy/crontab.txt` 的 ch3 那三行**(775~777)—— 副頻道復活的開關在別人手上。
- **動別線的檔案之前先 `git log --oneline -8`** —— 那是唯一看得到別的 session 做了什麼的窗口。
- context 到 **200K 就交棒**(絕對 token,不是百分比),寫交棒檔、不要 compact。
