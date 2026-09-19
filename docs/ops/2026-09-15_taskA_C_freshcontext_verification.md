# (C) fresh-context 獨立驗證報告 —— set_private_13 呼叫層 first/rest 分批閘門

- 驗證者:fresh-context 獨立驗證 agent(無任何先前對話脈絡)
- 現況取樣時刻(自己跑 `date` 拿):`2026-09-15T14:13:19+0800`
- 受驗對象:`D:\carson-agent\docs\ops\2026-09-11_13支設private_準備\apply_first_batch_guard.py`(呼叫層閘門)
  + 其被呼叫模組 `D:\carson-agent\docs\ops\2026-09-11_13支設private_準備\set_private_13.py`
- 驗證期間**零網路呼叫、零 `--apply`、零檔案修改**(兩支腳本與凍結文件皆未被我動過一個字)

---

## 最終結論(逐字)

```
VERIFY_C_RESULT: FAIL
```

**FAIL 的來源不是 first 批次,是 rest 批次的驗證檔閘門 `load_verification()`。**
- **first 批次(今晚要執行的那一批,1 支 `MuXiM5IqVQQ`)**:我用 6 種角度找碴,**找不到任何能讓它一次寫入超過 1 支、或指到別的 id 的路徑**,並且我自己補做了 shipped 自檢缺少的那一條突變,實證那一行是承重的。
- **rest 批次(剩下 12 支,今晚不執行)**:`load_verification()` 的四項檢查中,有 **3 項在不需要任何惡意的情況下就擋不到它自己宣稱要擋的事**(詳見「找碴嘗試」G1/G2/G3)。依驗收條件逐字「找到任何一個可用漏洞就是 FAIL」,整體判 FAIL。

我**不**把範圍自己縮成「今晚只跑 first 所以算 PASS」——範圍縮不縮由派工/督導決定,不由被驗的這一關自己決定。決策所需的區分已如上寫明。

---

## 1. 讀完兩份腳本全文

- `set_private_13.py` 669 行(全文讀畢)
- `apply_first_batch_guard.py` 363 行(全文讀畢;任務單寫「約 230 行」,實際含 SELF-TEST 區段為 363 行,正式路徑止於第 138 行的 SELF-TEST 標記)

承重結構(逐字引用 `apply_first_batch_guard.py:72-86`):

```python
def guarded_run(yt, batch, allowed, apply, log_path, qe_types=(), out=print, verify_path=VERIFY_PATH):
    if batch == "first":
        targets = [FIRST]
    elif batch == "rest":
        v = load_verification(verify_path)
        if v is None:
            raise FirstBatchCapExceeded(...)
        targets = list(REST)
    else:
        raise FirstBatchCapExceeded("🔴 batch 必須是 'first' 或 'rest',收到 %r —— 不送" % (batch,))
    return sp13.run(yt, targets, allowed, apply, log_path, qe_types, out)
```

`FIRST = sp13.HARD13[0]`(`apply_first_batch_guard.py:34`),而 `set_private_13.py:43` 的 `HARD13` 第一支逐字為 `"MuXiM5IqVQQ"` —— 與任務單描述一致,且 `FIRST` 是 **import 時綁定的常數**,不讀檔、不受 `candidates.json` 影響。

---

## 2. set_private_13.py 確實沒被動過

指令與逐字輸出:

```
$ git log --oneline -- "docs/ops/2026-09-11_13支設private_準備/set_private_13.py"
9a4f4b56 feat(ops): 13 支設 private 執行腳本 set_private_13.py —— 預設 dry-run,突變 M1–M6 逐條翻紅、陰性對照全綠;未 --apply
```

```
$ git status --porcelain -- "docs/ops/2026-09-11_13支設private_準備/set_private_13.py"
---END-STATUS---          ← porcelain 零輸出(--END-STATUS-- 是我加的結束標記,證明指令有跑完而不是空輸出)
```

判讀:該檔**自 09-11 落檔以來只有一筆 commit `9a4f4b56`**,本輪(09-15)的任何 commit 都沒有碰它;工作區 porcelain 零輸出=無未提交改動。
⚠️ 限制:`git status --porcelain` 看不見被 `.gitignore` 忽略的檔案改動;本檔不在 ignore 範圍(它有 commit 紀錄且 porcelain 追得到),故此處不受該已知陷阱影響。

---

## 3. 呼叫層逐行找碴(見下方「找碴嘗試」專節)

## 4. 親自執行自檢(逐字 stdout)

指令:
```
cd "D:\carson-agent\docs\ops\2026-09-11_13支設private_準備"
PYTHONIOENCODING=utf-8 python apply_first_batch_guard.py --self-test
```

完整逐字 stdout:

```
# apply_first_batch_guard --self-test  2026-09-15T14:10:25+08:00  離線;stub service;突變只作用在 SELF-TEST 標記以上
# 判準:S2(沒驗證檔)必須在零 API 呼叫下擋下 rest 批次;這是九條(D)要求的「會擋人」核心情境

BASE 未突變(同一條 exec 路徑)                                     ✅ 全綠  紅燈情境=無
NC   陰性對照:改一個不相干字串                                        ✅ 全綠  紅燈情境=無
M1   batch=rest 時不檢查驗證檔(直接放行,guard 失效)                    ✅ 翻紅(S2)  紅燈情境=['S2', 'S3']
       S2 沒驗證檔擋rest:沒丟 FirstBatchCapExceeded | 擋下前不該有任何 API 呼叫:list 1、update 12
       S3 驗證檔不合法擋rest:videoId 錯:沒丟 FirstBatchCapExceeded | videoId 錯:不合法的驗證檔卻放行了 update | instrument 是受測腳本自己:沒丟 FirstBatchCapExceeded | instrument 空字串:沒丟 FirstBatchCapExceeded | 時間差 <60 分:沒丟 FirstBatchCapExceeded | 只有 1 個時間戳:沒丟 FirstBatchCapE
M2   驗證檔合法性檢查失效(videoId 不比對)                              ✅ 翻紅(S3)  紅燈情境=['S3']
       S3 驗證檔不合法擋rest:videoId 錯:沒丟 FirstBatchCapExceeded | videoId 錯:不合法的驗證檔卻放行了 update
M3   時間差門檻被拿掉(<60分也算合法)                                   ✅ 翻紅(S3)  紅燈情境=['S3']
       S3 驗證檔不合法擋rest:時間差 <60 分:沒丟 FirstBatchCapExceeded | 時間差 <60 分:不合法的驗證檔卻放行了 update

# 零網路:daily_publish / googleapiclient 載入了嗎 → 都沒有
SELFTEST_RESULT: PASS
EXIT_CODE=0
```

逐項核對:
- 字面 `SELFTEST_RESULT: PASS` **真的存在**(上方逐字輸出倒數第 1 行),exit code 0。這一行是我自己跑出來的,不是引用任何人的回報。
- BASE / NC(陰性對照)**全綠**,紅燈情境=無。
- M1 / M2 / M3 **各自讓被指名的情境翻紅**(M1→S2、M2→S3、M3→S3)。
- 零網路證據行存在:`daily_publish / googleapiclient 載入了嗎 → 都沒有`,且此行參與 `allpass` 計算(`apply_first_batch_guard.py:352` 的 `allpass &= not leaked`),不是只印不判。

### 🔴 4-a 自檢的證據強度缺口(我發現並自己補上)

**在全部 5 條突變裡,情境 `S1 first批次=1支` 從來沒有翻紅過**(每一行的「紅燈情境」欄位都不含 S1)。
也就是說:shipped 的突變列**沒有任何一條釘住「first 只送 1 支」那一行** —— 而那一行正是今晚紅線動作唯一的硬上限。依「承重的那一行要用突變釘」的既有教訓,綠燈在這裡不足以證明 S1 是網子還是絆線。

我自己在記憶體中補做這條突變(不改磁碟、不改檔案),探針腳本位於
`C:\Users\User\AppData\Local\Temp\claude\D--carson-agent\efac2502-3b49-4fd4-9824-cdd4412f74f3\scratchpad\adversarial_probe.py`,逐字輸出:

```
X1  突變『first 只送 1 支』那一行 —— 證明它是承重的(shipped MUT 沒有這條)
    原字串出現次數 = 1
    突變後 first 批次實際上線 13 支 -> S1 斷言([FIRST])會不會翻紅: 會(斷言是真的網子)
    未突變 first 批次實際上線: ['MuXiM5IqVQQ']
```

結論:`targets = [FIRST]` 這一行**確實承重**(改掉就會上線 13 支),而 S1 的斷言**確實抓得到**。
⇒ 行為本身沒問題;缺口在「shipped 自檢沒有把這條證據印出來」。建議主線把此突變補進 `MUT`(代號如 `M0`,must_red=`S1`),否則下一個人看到的綠燈不會告訴他這一層沒被釘。

---

## 5. 自己算的 blob hash(逐字輸出)

```
$ git hash-object "docs/ops/2026-09-11_13支設private_準備/set_private_13.py"
b4f75ef886bcf74413278d726de59452042ac1b3

$ git hash-object "docs/ops/2026-09-11_13支設private_準備/apply_first_batch_guard.py"
cdae8fd97fc77069206d886048aea71da1883a90
```

這兩個數字是我自己跑指令拿到的,沒有採用任何先前回報的值。
⚠️ 已知限制(既有教訓):在 `autocrlf=true` 下 `git hash-object` 看不見 CRLF 漂移,兩份磁碟位元組不同的檔案可能算出相同 blob。若上游要拿這兩個 hash 當「檔案沒被換掉」的憑證,應另比磁碟 sha1+size,不能只靠 blob。

---

## 6. 四個檔案的工作區狀態

```
$ git status --porcelain -- "docs/ops/2026-09-11_13支設private_準備/set_private_13.py" \
    "docs/ops/2026-09-11_13支設private_準備/apply_first_batch_guard.py" \
    "docs/ops/2026-09-15_taskA_set_private_13_readback_plan.md" \
    "docs/ops/2026-09-15_taskA_set_private_13_upstream_overwrite_risk.md"
---END---                 ← porcelain 對這四個路徑零輸出

$ git log --oneline -1 -- "docs/ops/2026-09-11_13支設private_準備/apply_first_batch_guard.py"
a176e795 docs(ops): 九條(D)(E)(F)三缺口補齊——呼叫層first/rest分批閘門+09-15讀回計畫+上游覆寫風險調查

$ git log --oneline -3
a176e795 docs(ops): 九條(D)(E)(F)三缺口補齊——呼叫層first/rest分批閘門+09-15讀回計畫+上游覆寫風險調查
c1ed860b docs(ops): H-10(4) 第二行取代——wN:p1提案獨立驗證通過(fix_audio_language.py靜態讀碼+09-14 19:58:36現量)
da3b98b8 docs(ops): §R 總督導13:29:15 cc回報——督導改址三方+wN:p1獨立驗證收斂,新增「wF:p5裁決」標記慣例
```

判讀:四個檔案都乾淨、已落在 `a176e795`,無殘留未提交改動。

---

## 找碴嘗試清單(逐一說明結果)

證據來源:我自己寫的探針 `adversarial_probe.py`(記憶體 exec、stub service、零網路),逐字輸出見各條。

### A 組:first 批次(今晚要跑的路徑)—— 全部失敗,找不到繞過

| # | 嘗試 | 結果 | 證據 |
|---|------|------|------|
| A1 | 把 `--batch` 餵成 `ALL13`、`First`(大小寫變形) | **失敗**。argparse `choices=["first","rest"]` 直接拒絕,exit 2 | `['--batch', 'ALL13'] -> argparse 拒絕(SystemExit 2)` / `['--batch', 'First'] -> argparse 拒絕(SystemExit 2)` |
| A2 | 重複給 `--batch rest --batch first`,期待狀態混淆 | **失敗**。argparse 取最後一個,仍在 choices 內(`batch='first'`) | `['--batch','rest','--batch','first'] -> 接受: batch='first'` |
| A3 | 繞過 `guarded_run`,直接塞自訂 `targets` 清單 | **失敗**。`guarded_run` 簽章**根本沒有 targets 參數**;正式路徑中 `targets` 只有兩處賦值(第 76、83 行),且 `sp13.run(` 在全檔只出現一次(第 86 行,在 `guarded_run` 內) | `guarded_run 簽章: (yt, batch, allowed, apply, log_path, qe_types=(), out=..., verify_path=...)`;grep `sp13.run(` 僅 86 行一處 |
| A4 | 用 `--include-9ybt` 把 allowed 擴成 14 支,期待 first 批次把 `9YbTzPfXz6A` 一起帶出去 | **失敗**。`allowed` 只是允許清單,`targets` 仍硬寫 `[FIRST]` | `allowed=14 支時 first 實際上線: ['MuXiM5IqVQQ']` |
| A5 | `--self-test --apply` / `--self-test --batch first` 期待互斥檢查失效後走到寫入路徑 | **失敗**。`main()` 第 102-103 行 `ap.error` 擋下(實跑) | `error: --self-test 不能配 --apply/--batch` / `EXIT_CODE=2` |
| A6 | 無參數執行期待預設走到某個批次 | **失敗**。`error: 必須指定 --batch first 或 --batch rest`,exit 2(實跑) | `EXIT_CODE=2` |
| A7 | 把 `candidates.json` 當槓桿改變 FIRST 指向 | **失敗**。`FIRST` 綁 `HARD13[0]` 常數,不讀檔;且 `load_allowed` 的 md5 + 逐支常數核對會先丟 `Stop` | `set_private_13.py:41-46, 89-101` 靜態讀碼 |
| A8 | 突變掉「first 只送 1 支」那一行,看斷言會不會漏抓 | **抓得到**(見 4-a)。突變後上線 13 支,S1 斷言翻紅 | X1 逐字輸出 |

**A 組小結:first 批次一次寫入 >1 支,我找不到任何可行路徑。**

### B 組:rest 批次的 `load_verification()` —— 找到 3 個可用缺陷(FAIL 來源)

逐字探針輸出:

```
X3  load_verification 型別/字串繞過嘗試
    instrument 大小寫變形 Set_Private_13.PY           -> 🔴 被接受(rest 會放行)
    instrument 尾端空白 'set_private_13.py '         -> 🔴 被接受(rest 會放行)
    instrument 加路徑 './set_private_13.py'         -> 🔴 被接受(rest 會放行)
    instrument = 0(falsy 數字)                     -> 擋下(None)
    instrument = True(truthy 非字串)                -> 🔴 被接受(rest 會放行)
    verified_by = 0                              -> 擋下(None)
    readback_ts 是字串(長度>=2)                       -> 擋下(None)
    readback_ts 是 dict 兩個 ISO key                -> 🔴 被接受(rest 會放行)
    readback_ts 3 個、只有首尾差 <1h 但中間遠               -> 🔴 被接受(rest 會放行)
    時間戳倒序(晚的在前)                                  -> 🔴 被接受(rest 會放行)
    naive + aware 混用                             -> 例外外洩 TypeError: can't compare offset-naive and offset-aware datetimes
    videoId 前後空白                                 -> 擋下(None)
    videoId 是 list                               -> 擋下(None)
    純數字時間戳 ISO(僅日期) 差 1 天                        -> 🔴 被接受(rest 會放行)
```

**G1(🔴 可用缺陷·不需惡意)— 「不能拿受測腳本自己驗自己」這條實際上擋不住它要擋的事**
程式碼是 `if not instrument or instrument == "set_private_13.py": return None`(第 55 行),**逐字等值比對**。
但真的發生「拿受測腳本自己驗」時,寫檔的人自然會填 `set_private_13.py --self-test`、`./set_private_13.py`、`set_private_13.py(dry-run 回讀)` 之類 —— **這些全都不等於那個字面值,全部放行**。也就是說:這道檢查**只擋得住剛好逐字寫對那 16 個字元的人**,而那恰恰是最不需要擋的情況。這不是型別特技,是判準寫得比它宣稱的範圍窄,失效方向是**放寬**,且失效時**不報錯**。
建議修法:正規化後比對(小寫、strip、取 `os.path.basename`),並改成「白名單:instrument 必須是登記在案的獨立儀器清單其中之一」,而不是「黑名單:不可以是這一個字串」。

**G2(🔴 可用缺陷·不需惡意)— 「間隔 ≥3600 秒」量的是極值差,不是文件宣稱的首尾差**
docstring 第 19 行逐字寫「readback_ts 至少 2 個 ISO8601 時間戳,**首尾**相差 >= 3600 秒」,實作卻是 `span = max(parsed) - min(parsed)`(第 66 行)。
後果:回讀腳本若產出 3 筆時間戳 `[21:15, 隔日05:00, 21:30]`,**首尾只差 15 分鐘**,但因為清單裡存在一個很遠的極值,**照樣放行**(探針該列為 🔴)。同樣地,倒序清單也放行(`abs()` 讓方向失去意義)。
語意上「兩次回讀間隔 ≥60 分鐘」要證的是**相鄰兩次**(或第一次與最後一次)之間真的等了一小時;`max-min` 量的是「這堆時間戳的跨度」,只要清單裡混進任何一個遠的時間點就滿足。規格文字與實作不一致,且**實作比規格寬**。
建議修法:排序後檢查**相鄰**間隔(或明確只取首尾),並要求 `ts` 必須是 list、元素必須是 str。

**G3(可用缺陷·型別混淆)— `readback_ts` 可以是 dict**
`ts = v.get("readback_ts") or []` 之後只檢查 `len(ts) < 2` 再 `for t in ts`。dict 有 ≥2 個 ISO 格式的 key 時完全通過(探針該列為 🔴)。字串型別剛好會被 `fromisoformat` 逐字元解析失敗而擋下,屬於**運氣擋到的**,不是設計擋到的。
建議修法:`if not isinstance(ts, list) or not all(isinstance(t, str) for t in ts): return None`。

**G4(非漏洞,但要記錄)— naive/aware 混用時 TypeError 外洩**
`try` 只包住 list comprehension(第 63-65 行),`max(parsed) - min(parsed)` 在混用 naive/aware 時丟 `TypeError`,**不在 except 範圍**,會一路穿過 `guarded_run` 到 `main()`;`main()` 的 except 清單(`FirstBatchCapExceeded`/`LocalLedgerAbort`/`GoogleAbort`/`Blocked`/`CheckAbort`/`Stop`)接不到 `TypeError`。
方向是 **fail-closed**(探針實測 `list=0 update=0`,零 API 呼叫就中止),所以不是漏洞;但離開碼會是 traceback 的 1 而不是設計的 7,對「被什麼擋下」的判讀會誤導。此條為 fail-closed,列為觀察而非 FAIL 依據。

**G5(說明界線,非本報告的 FAIL 依據)— 驗證檔本質是自述**
`first_batch_verified.json` 的內容由寫檔的人決定,任何「時間戳/儀器名」欄位在技術上都無法由這支腳本證實。因此這道閘門的真實防護力是**防遺漏**(忘了做獨立驗證就想跑第二批),不是**防偽造**。這是檔案式自述的本質限制,不是程式缺陷 —— 但正因為如此,G1/G2/G3 這種「連沒有惡意的正當使用者都會誤過」的鬆動才特別要緊:它侵蝕的正是這道閘門唯一真正有效的那個面向。

### C 組:rest 批次放行後的行為(正確)

```
X7  rest 批次會不會漏送/多送:合法驗證檔下實際上線清單
    rest 上線 12 支;含 FIRST? False;== HARD13[1:]? True
X4  rest 批次在不合法/例外情況下,有沒有在被擋之前打過 API
    videoId 錯            -> FirstBatchCapExceeded(擋下) ; list=0 update=0
    naive+aware 混用       -> 其他例外外洩 TypeError ; list=0 update=0
```
合法時精確送 12 支且不重複碰 first;被擋時在 `sp13.run()` 之前就中止,**零 videos API 呼叫**(故零配額消耗)。

### D 組:閘門的涵蓋範圍(結構性,無法由本檔修補)

```
X8  set_private_13.py 自己的 main() 還在不在(=另一條沒有分批閘門的入口)
    sp13.main 存在: True
    sp13.main 裡 run(...) 的 targets 參數逐字:
       res = run(yt, list(allowed), allowed, a.apply, LOG_PATH, (qm.QuotaExhausted,))
    sp13 預設 apply: False
```

`apply_first_batch_guard.py` 的 docstring 第 8 行逐字寫「**本檔是唯一對外入口**」。
這句話在**模組內部**成立(該檔內 `sp13.run(` 只有第 86 行一處,且在 `guarded_run` 內);但在**檔案系統層面不成立**:`python set_private_13.py --apply` 依然是一條會一次送 13 支的完整路徑,而該檔是紅線禁改檔,呼叫層在技術上無法封掉它。
⇒ 這道閘門是**程序性**的(只要求人走這個入口),不是**技術性**的(無法阻止人走另一個入口)。這不是 `apply_first_batch_guard.py` 的缺陷 —— 它被禁止修改另一支檔 —— 但那句「唯一對外入口」應該加上限定語,否則下一個讀的人會以為 13 支一次送的路徑已經被封死。建議主線在交付文件明記:**first 批次的 1 支上限,其效力範圍僅及於透過 `apply_first_batch_guard.py` 的呼叫**。

### E 組:精確度註記

`main()` 第 115 行 `yt = dp.get_service()` 發生在 `guarded_run()` **之前**。因此 rest 批次被擋的情境雖然零 videos API / 零配額,但 OAuth service 建構(可能含 token 更新的網路往返)已經發生。docstring 的「零 API 呼叫」應理解為「零 YouTube Data API 呼叫 / 零配額」。此為用詞精確度問題,不影響寫入安全。
(此條為靜態讀碼推論,非實測 —— 我沒有、也不准執行 `main()`。)

---

## 本次驗證**沒有涵蓋**的部分(caveat:未量什麼 / 量法 / 撤銷門檻 / 撤掉後仍不敢宣稱什麼)

1. **未量:實際 YouTube API 的回讀正確性。** 本報告完全在離線 stub 下進行,沒有任何真實 API 呼叫。「送出後線上真的變成 private 了嗎」屬於九條的 (E)/(G) 關卡,不在本關。
   量法:執行後以**獨立儀器**(非 `set_private_13.py`)間隔 ≥60 分鐘回讀兩次。撤銷門檻:兩次回讀都拿到 `private` 才可撤此 caveat。撤掉後仍不敢宣稱:「之後不會被上游改回 public」——那是上游覆寫風險文件的範圍。
2. **未量:上游(排程/產線)會不會把這支影片改回 public。** 本報告只讀呼叫層程式碼,沒有盤點誰會寫 `privacyStatus`。
   量法:列出所有會呼叫 `videos.update` 的執行者並逐一檢查。撤銷門檻:每一個執行者都有證據說明它不會碰 `HARD13`。
3. **未量:`quota_meter` 當下的水位與 ENFORCE/RESERVE 實值。** 我沒有讀 `.env`、沒有改任何門檻,`main()` 也沒被執行,所以報告裡沒有任何配額數字。
   量法:執行時由 `main()` 第 114 行自印。撤銷門檻:執行當下的輸出行落檔。
4. **未量:`first_batch_verified.json` 目前是否存在、內容為何。** 本次只驗程式對該檔的處理邏輯,沒有把該檔當前狀態當成任何結論的承重點。
5. **未量:兩支腳本的磁碟位元組指紋(sha1+size)。** 只取了 git blob;在 `autocrlf=true` 下 blob 看不見 CRLF 漂移(見第 5 節限制)。
   量法:`sha1sum` + `stat` 兩者一起取。撤銷門檻:上游若要拿指紋當「檔案沒被換掉」的憑證,必須改用磁碟指紋。
6. **本報告只驗「程式碼 / 呼叫層邏輯」與「自檢本身的真實性」。** 不涉及:授權面(該不該做)、時機面(今晚該不該跑)、影片選取面(這 13 支該不該設 private)。

---

## 給主線的三項建議(不改檔,只回報)

1. **(阻擋 rest 批次前必修)** 修 `load_verification()` 的 G1/G2/G3:instrument 改正規化白名單、間隔改「相鄰/首尾」且加型別檢查、`readback_ts` 強制 `list[str]`。修完後**必須補對應突變**(instrument 正規化、相鄰間隔、型別檢查各一條),否則新的檢查同樣沒有被釘住。
2. **(建議在 first 批次執行前補)** 把「first 只送 1 支」那條突變補進 `MUT`(must_red=`S1`)—— 目前綠燈證明不了這一層不是瞎的,我是在外部另跑才拿到證據。
3. **(文件用語)** 「本檔是唯一對外入口」與「零 API 呼叫」兩處加限定語(見 D 組 / E 組)。

---

```
VERIFY_C_RESULT: FAIL
```
