# 設計方案:事實庫 key 的歸屬判準(修 `stale_keys` 每天誤刪別人的 key)

> 總督導 2026-09-09 裁示要求的方案書。**未實作、未上機**;實作與驗證在 scratchpad 進行,
> 回報後才動真正的檔。

## 0. 一個會改變做法的事實:**工作區就是正式機**

`youtube_channel/scripts/local_cron.py:413`:
`subprocess.Popen([_py, script] + args, cwd=str(ROOT))`,`ROOT = scripts/ 的上一層`
= `D:\carson-agent\youtube_channel`,而 crontab 給的是相對路徑 `scripts/stock_checkup_daily.py`。

⇒ **編輯那個檔的當下就等於上機**(下一次排程到點就跑新碼),`git commit` 與上機無關。
⇒ 所以本案的實作**不在 repo 內進行**,改在 scratchpad 的副本上做完 + 驗完,回報取得放行後才覆蓋。
⚠️ 附帶推論:今天稍早的 `50a9d243`(寫入端修法)**在存檔那一刻就已經排進明天 05:50**,
不是 commit 那一刻。那支經過三輪獨立驗證,但這個時間差本身要記住。

## 1. 問題重述

`merge_and_write()` 的 `stale_keys` 判準是**集合差**:「屬於本代號、但不在本次輸出裡 ⇒ 過時 ⇒ 刪」。
在**多個寫入端共用同一個 key 命名空間**時,這個判準必然誤刪別人的東西。

總督導的定性我採用:**這不是判準調得不夠細,是判準用錯了維度 —— 它用「內容」去推「歸屬」。**

實測損害:每天 `--count 16` 抹掉 16 檔的 `checkup_industry_rank__{code}`,
等下週日 06:40 `checkup_industry_rank.py --apply` 補回來。
(09-07 後重算的 34 檔留著 rank key 的 **0 檔**;對照 09-06 前重算的 601 檔有 471 檔留著。)

## 2. 前綴母體(不靠印象,實測 8,137 個 key)

| 筆數 | 前綴 | 歸屬 |
|---:|---|---|
| 1,620 | `checkup_crash` | 本腳本 |
| 632 | `checkup_long_horizon` / `checkup_annual_extremes` / `checkup_underwater` / `checkup_halvings`(各 632) | 本腳本 |
| 630 | `checkup_three_way` | 本腳本 |
| 578 / 577 / 574 / 569 / 564 | `checkup_eps_trend` / `checkup_revenue_trend` / `checkup_dividend_history` / `checkup_valuation_position` / `checkup_gross_margin` | 本腳本(走 `stock_fundamentals`) |
| **482** | **`checkup_industry_rank`** | **`checkup_industry_rank.py`** |
| **15** | **`checkup_industry_summary`** | **`checkup_industry_rank.py`**(產業名不是代號,本來就掃不到) |

相異前綴共 **13** 個。獨立交叉印證:`computed_at`/`disclaimer`/`data` 三個欄位只出現 7,640 次,
**缺的 497 = 482 + 15**,剛好就是上面那兩個前綴 ⇒ 前綴表與資料自己說的一致。

## 3. 方案選擇:採 ②(前綴分屬),但做成**結構上不可能重演**的形狀

總督導傾向 ①(每個 key 記寫入端)。我選 ②,理由三條:

1. 🔴 **① 需要對 17.9 MB 正式檔做一次全檔遷移寫入** —— 那是今天可做的動作裡風險最高的一個,
   而它要修的損害是**每週會自己復原**的。用最高風險的動作去修一個可復原的損害,不划算。
2. 🔴 **① 並沒有讓前綴表消失,只是讓它少用一次** —— 遷移時仍然只能靠前綴推歸屬
   (8,137 個既有 key 身上沒有寫入端資訊)。所以 **① = ② + 一次遷移**。
3. **② 的弱點(表會過期而且不報錯)可以結構性消掉**,見下。

### 3.1 三分類,預設是「不要動」

```
OWNED_PREFIXES   = {本腳本產出的 11 個前綴}          → 可以刪(這是原本「清掉改版後失效欄位」的用意)
FOREIGN_PREFIXES = {checkup_industry_rank, checkup_industry_summary}  → 保留,不出聲
其餘(未知前綴)                                      → **保留** + 每次印一行告警
```

關鍵在**預設值**:未知 ⇒ **保留**,不是刪。
⇒ 表過期時的失效方向從「靜默刪掉別人的資料」翻成「多留了幾個過時欄位 + 一行告警」。
**同一類損失結構上不可能再發生一次**,而不是靠人記得維護表。

⚠️ 刻意**不**做成 fail-closed 拋例外:`stock_checkup_daily.py:441` 的 `merge_and_write`
在 try 外面,任何例外都會終止整輪 `--count 16`(獨立驗證第三輪指出)。
未知前綴是「有人加了新寫入端」,不是資料毀損 —— 用告警,不要用停產。

## 4. 🔴 還要補一個**看得見這件事**的檢查(總督導點名)

現有的 `others_after == others_before` 對這個真實事故是**盲的** —— 那個 key 對被合併的代號
前後都算「自己的」,總數不變。判準必須從「總數」換成「**按前綴分組**」。

新增 `scripts/checkup_facts_prefix_health.py`(唯讀,不寫事實庫):

- 對每個前綴,算它在 `by_code` 全部代號裡的**覆蓋率**;
- 再算它在**最近重算過的 N 檔**(依 `by_code[c]["computed_at"]` 排序)裡的覆蓋率;
- **最近覆蓋率顯著低於整體覆蓋率 ⇒ 告警**,並點名前綴。

這是 level-triggered(量狀態)不是 edge-triggered(等事件),
避開 memory `detector-failure-shapes-2026-09` 那個坑。

**🔴 陽性對照用這次的真實事故**(總督導指定):拿 09-07 之後那 34 檔跑一次,
新檢查**必須叫得出來**——今天的真實數字是「最近 34 檔的 rank 覆蓋率 0%,整體 74%」。
叫不出來就是這個檢查沒用,不要上。
⚠️ 同時要有**陰性對照**:對本腳本自己的 11 個前綴,同一支檢查**不可以**叫
(否則分不出「它會叫」和「它對什麼都叫」)。

## 5. 驗收條件(給實作者與驗證員)

1. `checkup_industry_rank__{code}` 在 `merge_and_write` 後**還在**(拿真實 651 檔母體回放)。
2. 本腳本自己的 11 個前綴,改版後的失效欄位**仍然刪得掉**(原用意沒被弄丟)——要有陽性對照。
3. 未知前綴 ⇒ 保留 + 印告警,且**不拋例外**(不可以終止整輪)。
4. 新檢查對 09-07 後那 34 檔**會叫**;對 11 個自有前綴**不叫**。
5. 全程**不碰** `youtube_channel/STUDIO/stock_checkup_facts.json`(開工前/收工後 sha256 相同)。
6. 全程**不碰** `youtube_channel/scripts/` 下的真實檔案(見 §0:那等於上機)。

## 6. 留給未來的

① 仍然是終局形狀。建議在**下一次本來就要全檔重寫**的時機(例如某次 schema 改版)
順便把 `_writer` 欄位灌進去,而不是為了它單獨動一次 17.9 MB。
屆時前綴表就從「判準」降級成「一次性遷移的輸入」。
