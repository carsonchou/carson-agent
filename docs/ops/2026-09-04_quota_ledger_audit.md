# 配額記帳量測(欠件③)結論:分母**沒有**偏低,方向是**偏高**

> 2026-09-04 夜,main ch.(w9)。零 API 呼叫、零產線寫入,全部從既有帳本與原始碼推。
> 交付範圍:只回答「分母偏低多少、或沒有偏低」。**未改申請書任何數字。**

## 0. 一句話

欠件③ 的疑慮(`remaining()` 掉 2 而 `by_op` 記 1 = 記帳少記)**不成立**。
帳內恆等式全期成立、計量覆蓋率無缺口。分母真正的偏差方向是**偏高(上界)**,
而那件事申請書草稿自己已經揭露了。

## 1. 原始疑慮的兩種解釋,都不對

`remaining()` **不問 Google**:`remaining(day) = effective_limit() - spent(day)`,
而 `spent()` 讀的是 `quota_meter.json` 裡 `days[day]["spent"]`(`quota_meter.py:504,556`)。
`spent` 和 `by_op` 是同一個檔、同一個 day bucket。

但「同一本帳」**不等於**「是記帳 bug」—— 那本帳是 `_load()`→改→`_save()` 的**跨行程共享檔**,
四條 session 加 cron 都在寫(`_save` 自己的註解:「四條線共用這個 repo,爭用是常態」)。
別的行程打一發別的 op:`spent` +2、我的 `by_op[我的op]` +1。**觀測值同一本帳就能重現。**

### 判別法(不必控併發、不燒 unit)

> 🔴 **2026-09-04 22:0x 更正(獨立驗證員打掉,main ch. 自認)——上面那句全稱句是假的。**
> 我寫「`_unrecord()` 兩邊一起減」,**它沒有**(`quota_meter.py:404-409`):
> `:404-405` 無條件扣 `spent`/`calls`,`:406-407` 的 `if o:` **只守 `by_op` 那一邊**,
> 且兩個 `max(0,…)` 各自 clamp。⇒ op 桶不存在、或 `o["units"] < units` 時**單邊扣**。
> 可觸發路徑不需惡意輸入:`:399` 重算 `_pacific_date()`,而收費是在 `_charge_once` 當下記的,
> **resumable 上傳跨太平洋換日(台北 15:00~16:00,正是 15:25 補件 cron 的時段)就會扣到別天的 bucket**;
> 另有 `record()` 的 `_unreadable` 提前 return 與 `_save()` 的 `except: pass` 讓收費沒落地、
> 而 `_unrecord` 照扣。三種都讓 `spent < sum(by_op)`,**方向就是申請書低報**。
>
> ⇒ **正確的說法:「這 12 天沒量到低報」,不是「併發破壞不了它」。**
> 實證結論不變(12/12 差 0、無 `unknown:` op、無外部單邊寫入者),
> 但**帳本沒有結構上防止低報的保證**,那條恆等式是經驗事實不是定理。
> 我犯的形狀正是 memory `verification-claims-in-commit-messages` 記的那個:
> **把「`record()` 這一段成立」講成「整條恆等式必成立」。**
> 待辦(明早後,產線碼要獨立驗證才動):`_unrecord()` 缺 `record()` 兩條分支都有的
> `_unreadable` 守衛,目前靠 `:401-403` 巧合擋住,但 `_from_bak` 那條路徑沒擋 ——
> 會在舊快照上改再 `_save` 整檔,抹掉中間所有行程的寫入。09-03「rejected 分支繞過保護」
> 同一個病的第三處換皮,三個寫入點裡唯一沒被那次修補掃到的。


`record()` 非 rejected 路徑(`quota_meter.py:363-366`):

```python
b["spent"]  = int(b.get("spent", 0)) + int(units)
o["units"] += int(units)
```

同一個 `units`、同一段、無條件成對;~~`_unrecord()` 兩邊一起減~~(**錯,見上**);`rejected` 分支兩邊都不碰;
日期裁切砍整個 day bucket。⇒ **`sum(by_op[*].units) == spent` 在任何交錯順序下都必須成立**
(lost update 掉的是整次 `_save`,兩個計數器一起掉)。**併發破壞不了它,只有真 bug 破壞得了。**

### 實測(快照 `quota_meter.json`,2026-08-24 ~ 09-04,12 天)

| 項 | 值 |
|---|---|
| 全期 `spent` 合計 | 257,744 |
| 全期 `by_op` 合計 | 257,744 |
| 差 | **0** |
| 逐日 `spent == sum(by_op.units)` | 12/12 成立 |
| 逐日 `calls == sum(by_op.calls)` | 12/12 成立 |

陽性對照:注入 units 偏差 +7 → 命中;注入 calls 偏差 +3 → 命中。**檢查叫得出來。**

⇒ **不是 `by_op` 少記。**

## 2. 覆蓋率:也沒有缺口

`install()` patch 的是 `HttpRequest.execute` **類別方法**,同行程掛一次即全覆蓋(冪等);
但 `local_cron.py:281` 每個 job 是獨立 `subprocess.Popen` ⇒ **每支腳本要各自掛到**。

`youtube_channel/scripts/` 裡建 service 但檔內無 "quota_meter" 字串的有 18 支,逐一追 import 鏈後:
**未計量 0 支。** 全部經 `daily_publish.get_service()`(`:294-295`)、
`decision_dept.yt_service()`(`:40` 模組頂層 install)或 `set_thumbnails.get_service()`(`:28`)之一,
且 install 都在 `.execute()` 之前。`auth_analytics.py` / `yt_analytics.py` 全程只打
youtubeAnalytics(`cost_of()` 回 0 units,另一份配額)。逐檔表見稽核回報。

⇒ **沒有隱形消耗。**

## 3. 真正的偏差:分母是**上界**,方向偏高

`quota_meter.py` `_execute` 的 except 分支只把 `quotaExceeded` 丟進 rejected 桶,
**其餘所有失敗(500 / 逾時 / 權限 / 上傳失敗)照定價計進 `spent` 和 `by_op`**。

這件事 `yt_quota_increase_2026-09.md` 已記:
- `:21` 「記帳為**上界**…08-28 與 08-31 含此類灌水(08-28 實際約 18,500)」→ 該日 23,341,灌水約 **26%**
- `:47` 「錨點對不上:撞牆實測 **24,374** / 記帳最高 26,001」
- 申請書英文段自己也寫了 "it counts failed calls at list price, so figures are upper bounds"

⇒ **交接檔第四節把 ③ 的風險寫成「分母偏低」,實際是偏高,且已揭露。無須修正申請書數字。**

## 4. 順帶查到的兩件(不在③範圍,但壓在同一份證據上)

### 4.1 「帳本實測單價」是同義反覆,不是實測

`2026-09-04_quota_saturation.md` 第 27-29 行寫「**帳本實測單價**…估配額不要查官方文件再乘,
這個專案的帳本自己記著**實際**單價」。

`record()` 存的 units 來自 `cost_of()` 的**寫死表 `_COST`**(`quota_meter.py:224-246`),
所以 `by_op[op].units ≡ _COST[op] × calls` **恆等**。全期 20 個 op 實測:

    units/call 為整數的 op:20/20,非整數 0 個
    videos.post 163,200/102 = 1600 · videos.put 16,750/335 = 50 · captions.put 13,950/31 = 450 …

102 次呼叫除出剛好 1600、335 次除出剛好 50 —— 那是寫死表的指紋,不是活 API 的量測。
**價目表若有一格錯,帳本會用完美的一致性永遠確認它,系統裡沒有任何觀測能反駁。**
`audit_tables()` 拿 `quota_budget.COST` 對帳也救不了:那是同一個假設的第二份拷貝
(memory `verification-claims-in-commit-messages`:兩數吻合先問是不是共用同一個偏差)。

價目本身很可能是對的(就是官方價)。**壞的是那句「不要查官方文件」** —— 它把假設講成實測,
並勸讀者不要去看唯一的獨立來源。已在該檔加撤回標記。

### 4.2 兩個「花到剛好等於天花板」的日子,只有一個是 Google 說的

`youtube_channel/.env:38` 有 `YT_QUOTA_ENFORCE=1`(該檔 gitignored)。ENFORCE=1 ⇒
`_execute` 在 `units > remaining()` 時**本機就 raise**,呼叫根本沒送出、也不記帳。
所以 `spent` 會被 `effective_limit()` 頂住,**26,001 有可能是我們自己畫的線**。

逐日對照:

| 日 | spent | rejected_units | rejected_calls | 那條線是誰畫的 |
|---|---|---|---|---|
| 08-31 | 26,001 | 325 | 31 | **Google**(真 403) |
| 09-03 | 26,001 | 0 | 0 | **我們自己的閘門** |

⇒ saturation 檔那句「近六天有兩天花到**剛好等於天花板**」字面為真,但兩天的**證據種類不同**:
一天是外部拒絕,一天是自我節流。對申請書而言前者強、後者弱(後者只證明需求 ≥ 我們設的上限)。
**未改該檔數字,只加註。**

## 5. 還沒關掉的那一格(不是我能關的)

`yt_quota_increase_2026-09.md:46` 已經寫明:官方核定值要 Carson 到
console.cloud.google.com → `claude-morning-report-498407` → 配額 → YouTube Data API v3
"Queries per day" 親手抄。

**在拿到那個數字之前,「核准額度 = 25,999 / 26,001 / 24,374」三個錨點互不一致,
而它們全部是我們自己的觀測推的。** 這一格我關不掉,不假裝關掉。
