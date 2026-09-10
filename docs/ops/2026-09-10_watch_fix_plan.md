# 哨沉默的修法 —— 動工前的施工圖(2026-09-10)

> 成因與證據見 `2026-09-10_watch_silence_rootcause.md`(commit `574ad6e6`)。
> **本檔寫在動工之前**,理由:動正式機排程的過程中被壓縮是最糟的時間點,
> 而 memory `only-what-lands-on-disk-exists`:**做了也講了但講在對話裡 = 沒做**。
> 🔴 本檔的每一格都要能讓**另一個人**照著做完,不需要問我。

---

## 0. 三件事,一起過同一次獨立驗證

| # | 修什麼 | 動到哪 | 類別 |
|---|---|---|---|
| 一 | 三支哨互查(讓沉默會叫) | 3 支正式機腳本 + 1 支新模組 | 寫正式機 |
| 二 | 加 `AtLogOn` 觸發(讓錯過有第二次機會) | 2 個正式機排程工作 | 寫正式機 |
| 三 | `narration` 出口碼拆 1 / 2 | 1 支正式機腳本 | 寫正式機 |

🔴 **三件都是「寫正式機」⇒ CLAUDE.md:執行前一律先過一次 fresh-context 獨立驗證,有授權也不免驗,零例外。**
實作與驗證**不同人**(驗證不自驗)。

---

## 1. 修(一):三支互查

### 1.1 確切改動點

**新檔** `scripts/watch_crosscheck.py`(唯讀,不推播,不寫任何 log):

```python
WATCHES = {
    "seeding":   REPO/"docs"/"ops"/"seeding-watch.log",
    "narration": REPO/"docs"/"ops"/"narration-compliance-watch.log",
    "quota":     REPO/"docs"/"ops"/"quota-ceiling-watch.log",
}
def today_lines(path, today) -> dict   # {"sched": n, "manual": n}
def crosscheck(self_key, today) -> (ok: bool, msg: str)
```

判準(逐字寫死,不要靠讀者推論):
- 只看**非 `[DRILL]`** 的行。`[DRILL]` 行一律不算讀數 —— 演習不是讀數。
- `[MANUAL]` 開頭的行**算讀數,但單獨計數**,而且告警文字必須把兩者分開講:
  🔴 **「今天有人補跑過」不等於「排程今天有跑」**,合併計數會讓下一個人把補跑讀成排程正常。
- 缺任何一支 ⇒ 呼叫端 `alert()` + `record()`。

**改動點(三支各一處)**,都放在 `main()` **寫完自己那一行之後、`return` 之前**:

| 檔 | 函式 | 插入位置 |
|---|---|---|
| `scripts/seeding_watch.py` | `main()` | 判決 `record()` 之後 |
| `scripts/narration_compliance_watch.py` | `main()` | 三個 `record()` 出口之後(§3 拆碼後仍是三個) |
| `scripts/quota_ceiling_watch.py` | `main()` | 判決 `record()` 之後 |

🔴 **順序不可以反**:先寫自己的行、再互查。反過來的話,自己那行還沒落地,
另外兩支若同時在跑會互相判定對方缺席 —— **一個會製造假告警的競態**。

### 1.2 陽性對照(真案例,實測值)

今天 18:05 補跑**之前**的真實檔案內容,可以用截斷還原(這兩個數字是本次補跑前實測的):

```
docs/ops/seeding-watch.log               59,289 bytes   ← 18:05 補跑前
docs/ops/narration-compliance-watch.log  17,589 bytes   ← 18:05 補跑前
docs/ops/quota-ceiling-watch.log         (未動)          ← 今天 15:20 有行
```

⇒ **把前兩份複製一份、截到上面的長度,那就是今天 15:20 那一刻的真實磁碟內容。**
互查對這組語料**必須叫**,而且訊息要指名缺的是哪兩支。
🔴 **不要用合成 fixture** —— 這條的難點正是真實 log 的行長相(`[DRILL]` / `[MANUAL]` / 表情符號 / 全形括號)。

**陰性**:現況(三支今天都有行)必須安靜。

### 1.3 🔴 告警設計說明 —— 三個母體(memory `gate-verification-population`)

**這一節要原樣寫進 `watch_crosscheck.py` 的 docstring,不是只留在本檔。**

| 母體 | 內容 | 這道閘門的表現 |
|---|---|---|
| ① 今天會叫的 | 截回 18:05 前的兩份 log | **叫**(這是它存在的理由) |
| ② **全部會經過它的日子** | 週末、機器整天沒開、只有一支跑的日子、連假 | 見下面「已知會誤叫/不叫的日子」 |
| ③ **反方向被放掉的** | **三支全部沒跑的那一天** | 🔴 **靜音,不叫** |

②的展開(**這幾格是判準的一部分,不是註解**):
- **機器整天沒開**:三支都沒行 ⇒ 落入③,靜音。
- **只有一支跑**:那一支會叫,報另外兩支缺席 ⇒ 正確。
- **週末**:三支都排每日,週末照跑 ⇒ 無特例。若未來改成只跑平日,這道互查會每個週末誤叫,**改排程的人要同時改這裡**。

③的告警設計說明,**逐字寫進 docstring**:
> 🔴 **互查治的是「單支沉默」,治不了「全部沉默」。**
> 三支之中 `quota` 排 15:20(離開機/登入窗最遠),是這個設計唯一的支點。
> **不要拿這道互查當「守望已完備」的證據** —— 它把單支沉默變成有訊號,
> 把全部沉默留在原地,而全部沉默正是機器整天沒開那一天的長相。

---

## 2. 修(二):加 `AtLogOn` 觸發

### 2.1 確切改動

對 `carson-seeding-watch` 與 `carson-narration-compliance-watch`
**保留**原本的 `CalendarTrigger`(07:00 / 07:10),**追加**一個:

```powershell
$t = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$t.Delay = 'PT5M'
Set-ScheduledTask -TaskName <name> -Trigger @((原本的 CalendarTrigger), $t)
```

🔴 **`Set-ScheduledTask -Trigger` 是整組取代,不是追加** ——
必須先 `Export-ScheduledTask` 存原 XML、把原本的 CalendarTrigger 一起傳回去。
**改完立刻 `Export-ScheduledTask` 回讀比對**:原 CalendarTrigger 的 `StartBoundary`
(`2026-09-06T07:00:00+08:00` / `2026-09-06T07:10:00+08:00`)必須逐字還在。
(同一個形狀:memory `write-truncates-before-it-fails` —— 取代式寫入會靜靜吃掉沒被帶上的那一半。)

**不動** `quota`(它 15:20,不在登入窗,而且它是互查的支點,少動一分是一分)。

### 2.2 代價(寫下來,不要讓下一個人以為是 bug)

有人登入的日子會一天跑兩次 ⇒ 多一行 log(可接受,多的是證據);
`narration` 可能多推一次 —— 它現在**本來就每天在叫**(連四天低於地板),不是新噪音。

### 2.3 驗收

- 改完 `Get-ScheduledTask | Select -Expand Triggers` 必須看到**兩個**觸發。
- 🔴 **驗收不能只驗「兩個觸發存在」** —— 那是設定值,不是行為
  (**今天的教訓就是「設定值 ≠ 會生效」**)。要在下一次登入後看 log 有沒有多一行;
  在那之前,這一格的狀態是**「已設定、未驗證」**,要照實這樣講。

---

## 3. 修(三):`narration` 出口碼拆開

`scripts/narration_compliance_watch.py`,現況四個出口全是 1 或 0:

| 行 | 情況 | 現況 | 改成 |
|---|---|---|---|
| 288 | 判準自檢失敗 | 1 | **2** |
| 295 | 讀不到旁白樣本 | 1 | **2** |
| 313 | 樣本不足只報不判 | 0 | 0(不動) |
| 325 | 遵守率低於地板 | 1 | **1**(不動) |
| 330 | 合規 | 0 | 0(不動) |

⇒ **1 = 產線違規(哨是好的,它在做它的工作);2 = 哨自己壞了。**
docstring 要寫上這張表 —— 🔴 而且照第三輪那條規則:**描述閘門行為的文字要指名它的對照腳本**,
出口碼表要能被 `--selftest` 的既有模式逐格打到(`biz`/`summary` 打 1,判準自檢失敗打 2)。

---

## 4. 給獨立驗證員的三個問題(fresh-context,唯讀)

1. **互查會不會在它最該叫的那天不叫?**
   用 §1.2 的真案例語料(截到 59,289 / 17,589 bytes)實跑,不要讀程式碼推論。
   同時檢查**反方向**:現況三支都有行時它是不是真的安靜(不是恆叫)。
2. **`[MANUAL]` 那一格會不會把「有人補跑」讀成「排程正常」?**
   這是本次事故的核心誤讀。造一份「只有 `[MANUAL]` 行、沒有排程行」的今天 log,
   互查的訊息必須把兩者**分開講**,不可以只說「今天有讀數」。
3. **改排程有沒有把原本的觸發吃掉?**
   `Export-ScheduledTask` 前後逐字比對,`StartBoundary` 與 `ScheduleByDay` 必須原樣還在;
   `quota` 那支必須**一個位元組都沒動**。

⚠️ 一併告訴驗證員:**不准修改 `D:\carson-agent` 底下任何檔案**;
報告要附開工前後 `git status --porcelain -- scripts/ docs/ | wc -l`
與三支 log 的行數/sha256,**不論結論如何都逐字附上**。

---

## 5. 狀態

- [x] 成因查清、(b) 排除、尺驗過
- [x] 今天讀數補跑完成 + `[MANUAL]` 註記
- [ ] 修(一)(二)(三) 實作
- [ ] fresh-context 獨立驗證
- [ ] 套用到正式機 + 回讀
- [ ] 「已設定、未驗證」的那一格(§2.3):下一次登入後才驗得到
