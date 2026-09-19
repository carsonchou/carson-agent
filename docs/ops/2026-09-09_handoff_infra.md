# 基建線交接 — 2026-09-09(/clear 前)

> **為什麼現在交棒**:context 已到 **77% / 770.5K**,而 dispatch.md 的交棒線是 200K。
> memory `claude-context-budget-2026-09` 實測:同樣 500 次 tool call,800K context 花 400M token、
> 120K 只花 60M —— **做的事一樣,差 6.7 倍**。今晚全機已撞過一次額度上限
> (00:00~01:42 線上零 commit),而我是主要成因之一。
>
> ⚠️ **不要用 compact 續命** —— compact 本身要讀完整個 context,而且會丟早期指示。**交棒優於 compact。**

---

## 🔴 一、最容易誤讀的三點(先讀這個,它們不在任何單一 commit 裡)

### 1. `fact_source_guard` **不可以拔**,而且盤點檔裡「已證明瞎」那五個字是我寫錯的

`docs/ops/2026-09-08_gate_health_inventory.md` §3.3 初稿寫「已經證明瞎掉的(1 道)」,
總督導據此裁示「拔掉」。**執行到最後一步、拔完跑驗證時翻車**:
那道閘門在 **91 支真實候選裡實際擋下 20 支(22%)**。

我錯在**量錯函式**:產線判準是 `_sourced_unit()`,定義是「**舊判定 AND 單位判定**」,
而我的探針只量了前半段 `_sourced()`(無單位池)。修正後:

| 數字類別 | 產線 `_sourced_unit` | 我先前量的 |
|---|---|---|
| 百分比 0~200 / 200~10000 | 100% 放行(**確實瞎**) | 100% |
| **金額 1~10000 萬** | **2.0% 放行 ⇒ 擋掉 98%** | 100%(**錯**) |

⇒ 正確描述是**「在百分比上瞎、在金額上有效」**。已就地更正三處(表格列、§3.3 節、§六優先序),
並在 §六 那項加了刪除線 +「已撤銷,不要做」。**看到「已證明瞎」請確認你讀的是 `bb753716` 之後的版本。**

### 2. 缺的不是一道閘門,是**一格**

實測分工:

| 內容 | 百分比型宣稱 | 金額型宣稱 |
|---|---|---|
| 個股體檢長片(~198) | ✅ `per_stock_fact_gate` 擋 **100%**(七檔實測 0/400) | ✅ |
| **非個股體檢(749 Shorts + ~107 長片)** | 🔴 **兩道都不擋** | ✅ `fsg` 擋 98% |

`per_stock.check():638` 對非個股體檢片明文回「本閘門不適用」。
**而那一格不可能靠調容差修好**:全域池 0~200 區間有 32,947 個數字、相鄰間距中位 **0.0000**,
要擋隨機值容差得 ≈0,而合法四捨五入引用需要 ≥0.3 —— **差 12,768 倍,無解**。
唯一修法是**縮小池子**(把 per-stock 的設計延伸到非個股內容)⇒ 設計改動,**沒有人在做**。

### 3. 「還沒發生」和「這條路是壞的」在觀測上一模一樣

今天撞了兩次,兩次都是真的壞掉:
- watchdog 的「拉起排程器」路徑裝了五天沒被走過 → 一走就發現它會拉起一個**開跑就死**的排程器,還推一則報喜通知
- `auditability_coverage` 的 `log_ops` 寫錯模組 → 被 bare except 吞掉,**上線兩天 ops_log 0 筆**

⇒ **看到「數量是 0」先問是哪一種。**

---

## 二、今天做完的(不要重做)

| commit | 件 |
|---|---|
| `f550a66a` | `local_cron` 的 job stdout 不再進 DEVNULL → `logs/jobout/<腳本名>.log`(**一支腳本一個檔**,共用一個檔在 Windows 上會拼接壞行) |
| `6750ed73` / `d4cf1aa2` | watchdog 拉起的排程器會 cp950 崩潰;兩層修法 + 端到端驗過(**刻意複製敵意環境**驗的,不是靠 env 繞過) |
| `8bfaa829` | `auditability_coverage` 的 `sc.log_ops` → `from ops import log_ops`,並讓吞掉變成看得見 |
| `954e283c` | 合規哨判準改成 `from produce_batch import CHECKUP_SUMMARY_MARKERS`(判準從被監控物長出來) |
| `bb753716` / `28feb383` | ③ 撤銷 + 就地更正 |
| `7609dba8` / `a4a57f73` | 證據鏈盤點 + sidecar 驗證 |
| `8f7e67d9` | 兩個銳角交付檔(**總督導已轉給 wF:p1,不要再送一次**) |
| `686c8ba5` / `7e000693` | 全機排程鎖互動登入;行動單 ⑤ 分三格 + ④ 就地更正 |
| `83e39b55` / `a42870f0` | `non.` 停擺四天的落檔 + 重啟結果 |

---

## 三、wB:p1(`non.`)—— 你要接手盯的

**驗收條件(每次派工前先跑一次,判準是狀態不是事件)**:

```bash
cd /d/claude/projects/D--carson-agent && PYTHONIOENCODING=utf-8 python -c "
import json,re
def scan(p):
    n=pref=0; models=set()
    for l in open(p,encoding='utf-8',errors='replace'):
        try: d=json.loads(l)
        except: continue
        if d.get('type')!='assistant': continue
        n+=1
        m=d.get('message') or {}
        if m.get('model'): models.add(m['model'])
        c=m.get('content')
        t=' '.join(x.get('text','') for x in c if isinstance(x,dict)) if isinstance(c,list) else str(c or '')
        if re.search(r'\[[a-z]+/[a-z0-9-]+\]', t): pref+=1
    return n,pref,sorted(models)
print('新:', scan('1c507bc3-a46a-4c97-b813-408b453385fd.jsonl'))
print('舊(陽性對照,應有 1 筆前綴):', scan('cda0ca12-c657-48a7-a311-7752a7c041a8.jsonl'))
"
```

🔴 **「沒再看到 429」不算證據** —— 429 本來就間歇。判準是錯誤訊息**帶不帶 `[provider/model]` 前綴**。
最後一次驗(09-08 23:5x):assistant 84 筆、**前綴 0 筆**、全程 `claude-opus-5`;陽性對照抓得到 1 筆。

**它已交的**:
- `b0a76053` 上游斷料哨「讀不到事實庫」不再靜默 —— **我獨立驗過**(unreadable/upstream 都引爆、真實資料不誤叫、附正式機指紋未被動過)
- **第二棒剛交、我還沒驗**:三支哨的「吞掉但留痕」。⚠️ 它裡面有一個**值得帶走的發現**:
  它實測 **Windows 排程 + `pythonw.exe` 下 `sys.stdout` 與 `sys.stderr` 都是 `None`**
  ⇒ `print(msg, file=sys.stderr)` 是**靜默 no-op**、`sys.stderr.write` 拋 `AttributeError`,
  **所以照抄 `auditability_coverage` 那個「印到 stderr」的範本會在唯一重要的環境裡完全失效**,
  而在互動終端測起來是好的。它改成**主通道寫 log 檔、stderr 只當第二條路**。
  🔴 **這推翻了我在 8bfaa829 commit 訊息裡建議的通用修法**(我當時說「印到 stderr」)——
  那個建議只對 local_cron 的 job 成立,對 Windows 排程工作不成立。**下一棒請驗它並把這條更正帶出去。**

**下一棒可派的**(盤點 §六 剩下的):
- §六⑤ `brain_submit_watch` 達標路徑零輸出(「今天已交足額」與「排程沒被觸發」事後分不開)
- §六⑦ 幫 `per_stock_fact_gate` 補一次**獨立於撰寫過程**的引哨(它 09-06 的分數是用同一批語料調出來的 = winner's curse)
- §六⑧ 更新 `deploy/WATCHDOG.md` 那段已過時的「判定路徑一次都沒被真資料走到」(09-07 已經走到了)

---

## 四、證據鏈那件:**刪除者已列完**,結論在 `7609dba8`

檔:`docs/ops/2026-09-08_provenance_one_question.md`。用一支真片(`_Jg5RnQlce4`)走完全鏈。

**答得出來,但脆在三處**:①沒 sidecar ⇒ 對應關係**每次重建**(我是靠人工比對數字才追到的)
②事實按代號存、無集數/日期 ⇒ 重新體檢就覆蓋(現 0.5%,結構上無上限)③上游輸入沒留
(`tw_facts_cache` TTL 20h、`fundamentals_cache` TTL 30 天)⇒ **證得了「我們算了什麼」,證不了「算得對」**。

**刪除者(不只 `_move_slug_files` 一個)**:事實本體兩支寫入者(`stock_checkup_daily.py:441` **在排程**、
`checkup_fundamentals_backfill.py:133` 手動);字幕軌 `fix_captions_sync.py:122`/`fix_caption_drift.py:165`
的 `captions().update()` 會**取代**軌;`quality_scores.json` 的 `scan()` 整檔重寫。

🔴 **最該注意的不是刪除是分家**:`_AUDIT_KEEP_SUFFIX` 是**單一副檔名**,退件後旁白留 `output/`、
字幕與逐字時戳去 `_rejected/`,**沒有任何紀錄說它們是同一支片的**。

---

## 五、只活在我逐字稿裡的東西(不落檔就沒了)

1. **sidecar 四段鏈路我逐段跑過,但沒有連起來跑過。**
   `:2148 record → :2842 pop → :3026 掛上 → :6465 寫檔`,四段各自執行期驗過(寫檔那段是
   **抓原始碼 23 行 compile 後執行**,不是抄本;含「沒 record 不寫檔」「寫檔失敗不拋例外且留 ops」兩個陰性對照)。
   ⇒ **可證偽的期望:下一輪產製後 `ls youtube_channel/output/*.facts.json | wc -l` 應等於該輪個股體檢片數。**
   產了片而是 0 ⇒ 去看 ops_log 的「補產·事實溯源 ⚠️」(它 fail-open,**不會有別的訊號**)。
   ⚠️ 給 Carson 的說法要分兩句:「既有庫存 894 支永遠不會有」是**結構決定的、對的**;
   「新產的會不會長出來」是**四段各自驗過、還沒連起來跑過**。**四段各自跑過 ≠ 連起來跑過。**

2. **`fact_source_guard` 的現成回歸語料 = 那 20 支**,隨時可重跑取得:
   ```python
   led = json.loads(Path('STUDIO/uploaded_ledger.json').read_text(encoding='utf-8'))
   kept, blocked = dp._factguard_gate(dp.find_candidates(led))
   ```
   ⚠️ 07-17 的硬約束:第一版把「舊判定 AND 單位判定」寫成「直接改用同單位子池」時,
   **9 支原本被擋的編造片變成放行**。⇒ **動這道閘門之前必須先證明那 20 支仍被擋。**

3. **重啟 local_cron 的三個坑**(今天各踩一次):
   ① `_lock_fresh()` 判準是鎖檔 **<60 秒** ⇒ kill 後**必須等滿 60 秒**才能起,否則新實例**靜默自殺**
   (它只印一句聽起來很正常的「另一個 local_cron 已在跑」)。
   ② `herdr agent start` 在這台**起不了 claude**:送出的指令帶 bracketed-paste 前綴 `[200~`,
   PowerShell 5.1 不剝 ⇒ `ParserError`。改用 `herdr pane send-text` + `send-keys Enter`。
   (總督導已把這條落進 memory `herdr-pane-read-prompt-traps`。)
   ③ 選窗口要挑**零 job 到點**的分鐘;斷檔補跑**只補白名單四支**,其餘漏了就永久漏。

4. **今天我自己犯的三個錯,形狀值得記**:
   - 量錯函式(`_sourced` vs `_sourced_unit`)⇒ 差點拔掉一道每天擋 22% 的閘門。**救回它的不是警覺,是「拔完跑一次驗證」。**
   - 用 `head -5` 截斷 `ls` 之後把截斷的清單當完整清單讀 ⇒ 宣稱一個存在的檔不存在。
   - 寫了一個**分不出註解和程式碼**的檢查(grep `_factguard_gate(` 命中自己寫的註解),差點誤判改動沒生效。

5. **記憶體**:可用 441MB / commit 94.3%,今晚背景等待被系統砍掉 **5 次**。
   **不要開平行 subagent、不要排重活。** 最大單筆是 cs2 的 9,850MB(Carson 的,不動)。

---

## 六、方法論(唯一會隨 context 消失的東西)

1. **動手改別線的東西之前先跑 `git log --oneline -8`。** 今天差一點做出第二份 sidecar
   —— 主頻道線兩小時前才做完(`cb52ae03`)。那是唯一看得到別的 session 做了什麼的窗口。
2. **一個會讓自己的工作看起來更有價值的假設,要當成需要更多證據的,不是更少。**
   我幾乎寫下「休眠的證據來自那個有盲點的偵測器」——測完是假的(31 支全在 7、8 月,9 月 0)。
3. **驗一道閘門之前,先用 AST 或實跑確認產線到底呼叫哪一個函式。** 名字相近的兩個函式
   中間可能差著整個判準的一半。**更省事的探針要付的代價,是它可能量的是別的東西。**
4. **一個碰巧正確的結論,會替一個錯誤的方法背書。** 那句「隨機 400 個百分比通過率 100%」
   對百分比碰巧是對的,所以沒人發現量法有問題,直到我拿同一個量法去量金額。
5. **跨線的事實只走一條路。** 兩個 session 各送一份給對面,對面分不出哪份是規格
   (memory `yt-quota-is-per-cloud-project`:兩個 session 一起修了一個不存在的問題)。
6. **拔掉/改掉一個防護之後要跑一次驗證再報完成。** 照裁示拔完就回報「已執行」的話,
   這件事會靜靜地過去,而我們會在某天發現金額型編造又出現了、且找不到原因。
