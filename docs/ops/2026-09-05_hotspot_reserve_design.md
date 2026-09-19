# 時事發布拿不到 1,600 —— 根因是預留的**粒度**,不是排序(2026-09-05,基建線督導)

> 🔴 **結案，不套（2026-09-05 總督導裁示）** —— 時事片停產（`6e205e40`，已外部確認）。
>
> ⚠️ **但不只是「服務對象沒了」—— 它從一開始就放不進去。**
> 本文的 `DEFAULT_RESERVE_UNITS = 24,750` 是用 11 × **2,100** 算的，
> 而 2,100 已於 `52593619` 撤回（每支長片確實有一筆 `playlistItems.insert` 50，
> 呼叫在 `daily_publish.py:1273-1276` → `playlist_engine.py:498`）。
> 以確認的 **2,150** 重算：11 × 2,150 = 23,650，加時事一支 1,650 = **25,300**；
> 而主頸道線把「其他活動」的安全值從 1,600（中位數）提到 **2,400**
> （實際 1,023~2,351，而 09-03 那個 2,351 還是被天花板截斷的**下界**）。
> ⇒ 23,650 + 2,400 = **26,050 > 26,001**，**現行 11 支本身就沒有餘裕**，
> 還沒算進時事那 1,650。
> ⇒ **將來就算時事片復活，這份設計也不能直接撄回來用** ——
> 它需要的不是更好的預留機制，是先把發布量或維運砍掉一塊。
>
> 狀態:**設計已定、patch 未套用**。動 `quota_meter.py` 與 crontab = 正式機,
> 依 CLAUDE.md 須先過 fresh-context 獨立驗證,零例外。

---

## 🔴 驗證結果(2026-09-05,fresh-context 驗證員):**不可套用**

承重論證(第 4 項「級距」)PASS —— 靠拉高舊版支數 RESERVE 解決不了問題,
所以確實需要一條絕對值旁路。但三處要改,而且 scope 有缺口:

**① 上傳鏈的成本被我算多了 50,而且是因為我把公式當成執行期行為。**
`daily_publish.py` 全文**沒有** `playlistItems().insert()` 的呼叫。
打那支 API 的是 `organize_dept.py` / `build_playlists.py` / `playlist_engine.py` /
`industry_playlists.py`,全是播放清單維運腳本。
(佐證:`ops_log.txt:11568` `[09-04 09:45:39] 頻道整理｜歸類完成 新增15`,
`organize_dept.py:125` 的 `added` 直接等於成功的 insert 次數 = 15 calls / 750 units。)
⇒ 09-04 的 `playlistItems.post` 1,000 units **全部是維運,0 來自上傳鏈**。
⇒ 走主批次的長片真實成本 = 1600 + 400 + 50(thumbnails :1018)+ 50(commentThreads,
在 :1272 主迴圈而非 `upload_one` 內)= **2,100**,不是 2,150。
⇒ **`PUBLISH_UNIT_COST = 2150` 的註解(`quota_meter.py:595-597`)列了一個
`upload_one` 從不呼叫的科目。** 這是既有誤差,不是本設計新增的,但本設計繼承了它。

**② 時事片的真實成本是 1,650,不是 1,600 也不是 2,150。**
`news_dept.py` → `produce_batch.py:6476`(`--topic` 強制 `make_one("short", ...)`,
**永遠是 Short**)→ `_publish_now`(:6243)只呼叫 `dp.upload_one()`,不走主批次迴圈。
`upload_one` 內:videos.insert 1600 一定執行;字幕 `if is_short: 跳過`(:956-957);
thumbnails.set 50(:1018);commentThreads **走不到**。
⇒ 我原文擔心的「後面幾筆照樣撞線、修法只是把失敗點往後挪一格」**沒有成立**:
縮圖失敗有 try/except(:1017-1031),片子會進 `pending_thumbs.json` 排隊,
`upload_one` 仍 `return vid`,發布仍算成功。但留 1,600 會讓那 50 固定撞線
⇒ **每天多產生一批排隊補件**,所以要留 1,650。

**③ 數字全部重算:**

| | 原文 | 更正後 |
|---|---|---|
| 上傳鏈 11 支 | 23,650 | **23,100** |
| 09-04 維運實耗 | ~1,359 | **1,909**(25,009 − 23,100) |
| 時事一支 | 1,600 | **1,650** |
| `YT_QUOTA_RESERVE_UNITS` | 25,250 | **24,750**(23,100 + 1,650) |
| 維運池 | 2,351 → 751 | 2,901 → **1,251**(少 658 ≈ 13 筆 50-unit 維運) |

**④ 🔴 scope 缺口(這是「不可套用」的理由,待驗證員補完第 7 項):**
我只列了三支 cron(16:20 / 16:35 / 09:51),但 `organize_dept.py`(09:45)也在吃同一個池子
且不在我的清單裡。**漏掉任何一支,它就會在預留線之上把額度吃走,整個修法失效。**
⚠️ 還要確認:08-27 撞牆後重試 935 次(45,491 units 被拒)的是哪一支腳本。
若它在清單裡,把預留線拉高等於**每天**把它推進那個重試迴圈 —— 那會比現在更糟。

## 🔴 第二輪驗證:scope 缺口是 **26 行**,而它推翻的是設計方向本身

crontab 帶 `YT_QUOTA_RESERVE=23650` 的共 **29 行**,我的 patch 清單只涵蓋 **3 行**。
漏掉的包含 `organize_dept.py`(週五 09:45,09-04 實花 15 次 playlistItems.insert = 750 units)、
`industry_playlists.py`、`playlist_engine.py`、`build_playlists.py`、`comment_dept.py`
(**每 2 小時一次、全天**,跟時事部同頻率搶同一口井)、`quality_score.py`(15:30 與 06:40 兩班)
等 26 支。**只要其中任何一支在 23,650~24,750 這段還在跑,新留的 1,650 就被吃光。**

⇒ **這不是「補上 26 行」的問題。** 逐行 opt-in 就是根因:
`RESERVE = int(os.environ.get("YT_QUOTA_RESERVE", "0"))`(`:63`)**預設 0 = 不保護**,
靠每支 cron 自己記得加。漏一支是靜默的,而且下一支新增的 cron 還會漏。
判準(`verification-that-cannot-fail` 第零種):**規則沒被遵守時會不會產生輸出?**
opt-in 的漏網不產生任何輸出 —— 那支腳本只是照常把額度吃掉。

## 定案改為:把 opt-in 翻成 opt-out

```python
# 預設就保護。要動用被保護的額度,必須明確宣告自己是被保護的那個部門。
RESERVE_UNITS = int(os.environ.get("YT_QUOTA_RESERVE_UNITS", str(DEFAULT_RESERVE_UNITS)))
```

- `DEFAULT_RESERVE_UNITS = 24,750` = 23,100(發布 11 支 × 2,100)+ 1,650(時事一支 Short)
- **只有發布路徑 opt-out**:`daily_publish` 的兩行(18:00 / 18:30)與時事的
  `news_dept` / `hotspot_dept` 帶 `YT_QUOTA_RESERVE_UNITS=0`
- **其餘 26 支維運腳本一行都不用改**,自動被擋在 1,251 的維運池內

為什麼這比補 26 行好:

| | 逐行 opt-in(原設計) | 預設 opt-out(定案) |
|---|---|---|
| 漏掉一支的後果 | 它把預留吃光,**修法靜默失效** | 它被保護,**保守停下**(冪等,下個配額日接著跑) |
| 新增 cron | 要記得加,不加就漏 | 不用做任何事 |
| 要改的行數 | 29 | **3~4** |
| 失效方向 | fail-open | **fail-safe** |

## 兩個洞,我自己補的(未經驗證,待第三輪)

**洞 1:預設保護會把 1-unit 的讀取也擋掉。**
`videos.get` / `playlistItems.get` / `commentThreads.get` 都是 1 unit,
而它們是幾乎每支腳本判斷狀態的前提。擋住一個 1-unit 讀取,
收益是保住 1 unit,代價是那支腳本整件事做不了 ——
這正是既有 `_reserve_guard` 註解裡「剩 106 / RESERVE 2200 → 放行」
處理過的同一種不對稱(原文:「1 unit 的抓留言是知道觀眾想看什麼的唯一管道」)。

⇒ 加一道小額豁免。門檻取 **units >= 50**:
本專案所有讀取類都是 1 unit,所有寫入類最小是 50(thumbnails.set / commentThreads.insert
/ playlistItems.insert / comments.post),**50 這個切點正好把讀寫分開**,不是湊出來的。
代價:09-04 全部 1-unit 讀取合計 **159 units**(videos.get 95 + playlistItems.get 45
+ commentThreads.get 10 + channels.get 6 + playlists.get 2 + channelSections.get 1)。
用 159 units/日 換所有狀態判斷正常運作。

**洞 2:預留 1,650 只夠一支,而時事部每日上限是 3 支。**
`crontab.txt:58` 註解寫明「每日上限 3 支」。3 × 1,650 = 4,950,
而 26,001 − 23,100(發布)= 2,901 —— **放不下**。
⇒ 這個修法把時事從「結構性歸零」變成「每天一支」,**不是變成「三支」**。
不可以宣稱它讓時事部恢復正常運作;它讓時事部從 0 變成 1。
另外兩支仍會撞線,但那時是**有意的資源分配**,不是無聲的結構性失效。

## 已知代價(不是未知數,是選擇)

1. **維運腳本會被擋得比現在多。** 池子 2,901 → 1,251。被擋時是純本地端 raise
   (`_orig` 呼叫**之前**),零 units、零網路成本,不會製造真 403。
2. **噪音**:`organize_dept.py:113-121` 與 `thumbnail_dept.py` 被擋時是
   `except Exception: print(警告); continue`(**沒有 break**),會對整份 ledger 逐一撞牆
   ⇒ ledger 幾百支就印幾百行警告。**燒的是 log 不是配額**,但這是實打實的噪音。
   ⚠️ 另外 24 支是否有 quota-break 收尾**未逐一核對**。
3. `DEFAULT_RESERVE_UNITS = 24,750` 綁死「11 支長片 + 1 支時事 Short」這個現況。
   **發布量一改它就過期**,而過期的方向是「保護不足」。
   ⇒ 落地時這個常數的定義處要寫明它從哪裡算出來,並在 `premises.md` 掛一條隨發布量失效。

**⑤ 09-04 的 `spent` 我寫 25,009、驗證員讀到 25,032~25,033** —— 配額日還在跑,
兩者都是快照。本文所有 09-04 數字的快照時點:**台北 2026-09-05 02:4x**。

---

## 一句話

不是額度不夠、也不只是排序。是 `YT_QUOTA_RESERVE` **只能以「支」為級距**
(`want_n = RESERVE // PUBLISH_UNIT_COST`),而時事需要的是 **1,600 這個不到一支的整塊**。
機制表達不了「留 1,600」,所以時事永遠只能撿碎片,而碎片永遠湊不到 1,600。

## 觀測(不是推論)

`ops_log.txt` 全部 13 次(不是 10 次)`時事發布｜⚠️ 即時發布失敗`,09-01~09-05:

    剩 0 / 0 / 1133 / 1109 / 1088 / 1428 / 1425 / 1380 / 886 / 0 / 1066 / 1043 / 996

**沒有一次到過 1,600。** 訊息前綴是 `quota exhausted:`(ENFORCE 那道)
不是 `quota reserve:`,所以它不是被預留擋的,是真的沒有。

`quota_meter.json` 09-04 by_op 拆解(spent 25,009):

| 塊 | units | 說明 |
|---|---|---|
| 上傳鏈 11 支 | 23,650 | videos.post 17,600 + captions.post 4,400 + 每支 thumbnails/playlistItems/commentThreads 各 50 |
| 維運實耗 | ~1,359 | 舊片換圖 550(11 支)+ playlistItems 同步 450 + videos.get/put 245 + 雜項 |
| **未用完** | **~992** | ← 湊不到 1,600,時事拿不到 |

天花板 26,001 − 23,650(RESERVE 保護的發布)= **2,351 是維運與時事共用的池子**。

## 為什麼「改排序」是錯的解

台北時間、太平洋配額日 00:00 = 台北 15:00:

    15:00 配額日開始 ─ 26,001
    16:20 thumb_backfill          ┐ 兩支都帶 YT_QUOTA_RESERVE=23650,
    16:35 refresh_search_thumbs   ┘ 所以只動 2,351,不碰發布的 23,650
    18:00 + 18:30 daily_publish   ─ 23,650(受保護)
    隔日 00:01~14:01 時事(news_dept / hotspot_dept,**兩支都沒有 RESERVE**)

RESERVE 是 2026-08 為了「補件先跑把發布餓死」建的,它保護了發布。
時事排在最後**且它的最小不可分割塊(1,600)比任何維運單筆(50)都大** ——
先到先得的規則下,大塊永遠輸。

⇒ 把時事排前面 = 換發布或維運挨餓(本線 08-28 踩過同一個坑:
「時區錯配的修法只是換一個部門挨餓」)。**排序決定誰餓死,不決定有沒有人餓死。**

## 定案:給 RESERVE 加一個 units 粒度的旁路

`_reserve_guard` 現行判準(`quota_meter.py:600-628`)是對的,不要動它。
新增一個獨立的絕對值預留,沿用同一條「擋住有沒有收益」的判準:

```python
RESERVE_UNITS = int(os.environ.get("YT_QUOTA_RESERVE_UNITS", "0"))

# 在 _reserve_guard 內、支數判準之後:
if RESERVE_UNITS:
    r = remaining()
    # 「還救得回來」才擋 —— 已經低於預留線時擋住毫無收益,
    # 只會讓 50 units 的維運整個配額日做不了(與支數判準同一條理由)。
    if r >= RESERVE_UNITS and r - units < RESERVE_UNITS:
        raise QuotaExhausted(
            f"quota reserve-units:{op} 需 {units},今日剩 {r},"
            f"花下去會跌破預留 {RESERVE_UNITS} → 停在額度線上(冪等,下個配額日接著跑)")
```

crontab 三行加環境變數(**只加,不改既有的 `YT_QUOTA_RESERVE=23650`**):

    16:20 thumb_backfill        → 併加 YT_QUOTA_RESERVE_UNITS=25250
    16:35 refresh_search_thumbs → 併加 YT_QUOTA_RESERVE_UNITS=25250
    09:51 thumbnail_dept        → 併加 YT_QUOTA_RESERVE_UNITS=25250

25,250 = 23,650(發布)+ 1,600(一支時事的 videos.post)。

結果:維運池 2,351 → **751**,時事拿回 1,600。
代價 = 每天約 **12 支舊片換圖**(50/支)。

## 我否決的替代方案

| 方案 | 否決理由 |
|---|---|
| 把時事排到發布之前 | 換發布挨餓;發布是 YPP 時數主線,且上限凍結至 09-15 |
| `YT_QUOTA_RESERVE` 23,650 → 25,800 | 級距是支,25,800→12 支,維運只剩 **201** = 實質關掉;25,250 則 `//2150` 仍是 11,**完全沒有效果** |
| daily_publish `--max` 11 → 10 | 單方面砍產出,而且沒有任何訊號說明為什麼 |
| 砍 captions.post(4,400/日,鏈上第二大宗) | 字幕直接餵搜尋,而搜尋是本頻道 47.1% 流量來源。拿確定的流量換一支時事片,不划算 |
| 等提額核准 | 申請書已由 Carson 凍結,時間不可控;而這件每天在丟片 |

## 誠實的邊界

- 這個修法**只救得回一支**時事片/日。維運需求實測 4,601~7,845,池子只有 751~2,351
  —— **總量真的不夠是算術,不是排序**,那部分只有提額能解。
- 25,250 這個數字綁死了「發布 11 支」這個現況。**發布量一改,它就過期。**
  ⇒ 落地時要在 crontab 那三行的註解裡寫清楚它是從哪裡算出來的
  (記憶 `yt-api-quota-structural-overrun`:排序型優先序要連水位一起記)。
- 我**沒有**驗證 news_dept / hotspot_dept 的實際上傳路徑是不是走完整 2,150 鏈。
  若它們的後續呼叫(字幕/縮圖)也要付費,1,600 只夠 videos.post 那一筆,
  後面幾筆仍會撞線 —— **這一項未知,不能據此宣稱「時事會恢復」**,
  只能宣稱「videos.post 那一筆拿得到額度」。


---

# 第三輪驗證:C 項 FAIL —— 洞是我反轉之後自己捅出來的

`_reserve_guard` 讀的是**全域共用**的 `remaining()`。把 `daily_publish` 和 `news_dept`
**都**設成 `RESERVE_UNITS=0`,等於宣告這兩支互不相讓 —— 而 `news_dept` 是
`0 */2 * * *`(全天每 2 小時),它會在白天啃掉當晚 `daily_publish` 要用的 23,100。
**這是 08 月「補件先跑把發布餓死」的同一種病換了病原體**,而且舊版 opt-in 設計沒有它。

根因是我把它想成**二元**的 opt-in / opt-out。它不是二元,是**優先序階梯**。

## 定案(第三版):三層階梯,預設落在最保守的那層

| 層 | 誰 | `YT_QUOTA_RESERVE_UNITS` | 讓出給誰 |
|---|---|---|---|
| 1 | `daily_publish`(18:00 `--series checkup --max 1`、18:30 `--max 10`) | **0** | 不讓任何人(最高優先) |
| 2 | `news_dept`(00:00 每 2 小時、平日 09:35/11:35/13:35) | **23,100** | 讓出發布 11 支的量 |
| 3 | **其餘全部(預設)** | **24,750** | 讓出發布 + 時事一支 |

- 第 3 層是 `DEFAULT_RESERVE_UNITS`,**不需要任何 cron 宣告** ⇒ 那 26 支一行不用改,
  新增的 cron 自動落在最保守層。
- 只改 **4 行**:`crontab.txt:349`、`:367` 加 `=0`;`:59`、`:374` 加 `=23100`。
- 加 `units >= 50` 小額豁免(1-unit 讀取不受限)。

## 🔴 落地順序(弄反會讓當晚發布全滅)

`:349` / `:367` / `:59` / `:374` **現在四行都沒有任何 RESERVE 設定**(現值等於 0)。
反轉後預設變 24,750 ⇒ **`daily_publish` 自己會先被擋死**。

⇒ 必須:**① 先改 crontab 四行 → ② 驗證四行都生效 → ③ 才改 `quota_meter.py` 的預設值。**
順序弄反、或任何一行沒生效,當晚 11 支發布全滅 —— 那比現在嚴重得多。
這是 opt-out 設計的固有代價:它把「漏掉=靜默失效」換成「漏掉=保守停下」,
但**對被保護的對象本身,漏掉 = 完全停擺**。

## 第三輪其餘更正

**① `units >= 50` 的結論對,但我的論證是錯的。**
價目表(`quota_meter.py:65-101`)全部值只有 `{1, 50, 100, 400, 450, 1600}`,
2~49 之間確實一個都沒有 ⇒ **切點數值上安全**。
但「所有讀取類都是 1 unit」有兩個反例:`("captions","GET")=50`、`("search","GET")=100`。
⇒ 50 不是「讀寫分界」,是「這張價目表剛好沒人填 2~49」—— **巧合,不是結構**。
結論成立、論證不成立,**兩者要分開講**;而且它是巧合就代表**價目表哪天新增一個
20 units 的科目,這個切點就悄悄變成誤傷**。落地時要在常數旁註明這件事。

**② `hotspot_dept.py` 根本不打 YouTube API。**
它的資料來源是 Google News RSS,docstring 自己寫明「不即時發(避免和 news_dept 撞車洗版)」,
全檔沒有任何 `.execute()`,只寫本機 `topic_bank.json` / `hotspot_seen.json`。
⇒ `quota_meter` 量不到它,把它列進 opt-out 清單是**無效動作**(不是有害)。
我第一輪寫「news_dept / hotspot_dept 兩支」,第二輪自己已證實只有 `news_dept` 走 `_publish_now`,
**但沒有回頭更新那句話** —— 推翻了的東西沒有跟著改,又是 F1 形狀。

**③ 一個獨立的真 bug(不是配額問題,但要記):**
`news_dept._today_count()`(`:139`)用**台北日曆日**算 `MAX_PER_DAY=3`,
而配額日在**台北 15:00** 重置 ⇒ 一個配額日橫跨兩個台北日曆日,
同一配額日內理論上能產出 **6 支**(15:00~23:59 算 3、次日 00:00~14:59 再算 3)。
在三層階梯下這個 bug 的配額後果會被第 2 層的 23,100 預留線吸收
(它最多吃到 remaining 跌到 23,100),**所以它不再是配額問題,但語意仍是錯的**,單獨列管。

**④ 收尾分類(驗證員實查):**
- 有 quota-break、乾淨停下 **9 支**:`thumb_backfill` / `refresh_search_thumbs` /
  `fix_audio_language`(:104)/ `fix_period_disclaimer`(:182)/ `comment_dept`(:416)/
  `desc_backfill`(:270)/ `zombie_sweep`(:249)/ `build_playlists`(:197)/ `playlist_engine`(:387)
- 只有 `continue`、沒有 break **3 支**:`organize_dept`(:113-121)/ `thumbnail_dept`(全檔)/
  **`industry_playlists`(:249-252)** ← 新查到的,而且它排**週五 16:50**,正好卡在保護視窗中間
- **未逐行核實 16 支**(粗篩只數 `.execute()` 與 `except` 次數):`quality_score` / `comment_watchdog` /
  `channel_facelift` / `ypp_meter` / `analytics_weekly` / `cover_backfill` / `ab_title` / `ab_thumbnail` /
  `early_cta_report` / `gen_media_kit` / `ypp_tracker` / `intel_dept` / `outlier_scan` / `decision_dept` /
  `winner_amplifier` / `reconcile_ledger` —— **這 16 支不算已驗證**,不可據此宣稱「全部會乾淨停下」。


---

# 第四輪:PASS,但它自己查到的第 4 項我不接受它的解法 → 定案第四版

第 1 項驗證員代入算過:`remaining=24,700` 時 news_dept 的 `videos.insert`(1,600)
`24700-1600=23100`,`23100<23100` False ⇒ **通過,精確停在 23,100**;
接著的 `thumbnails.set`(50)`23050<23100` True ⇒ 擋下(片子仍算發布成功,進 `pending_thumbs`)。
**三層階梯確實堵住了第三輪的洞。**

## 但第 4 項是一個真缺口,而「寫進文件提醒」不是解法

三層階梯只保護**透過 `local_cron.py` 排程觸發**的路徑。
手動執行 `python scripts/daily_publish.py --max 10` 拿不到 crontab 那行的 `=0`,
會 fallback 到 `DEFAULT_RESERVE_UNITS=24,750` ⇒ **發布腳本被自己的新預設值卡住**。
`produce_batch.py --topic ... --publish`(`_publish_now` 的真正入口)同理。
而手動補發正是產線出事時的救命路徑(本專案有 `produce_catchup --target N` 手動介入的先例)。

驗證員的建議是「寫進落地文件,手動執行時記得比照 crontab 加同樣的環境變數」。
**不採用。** 判準:規則沒被遵守時會不會產生輸出?不會 —— 忘了加就靜默落到層 3,
只印一句 warning。那是**期望不是規則**(`verification-that-cannot-fail` 第零種)。

## 定案(第四版):層級由程式宣告,不由呼叫方式決定

```python
# quota_meter.py
DEFAULT_RESERVE_UNITS = 24750
_reserve_units = None          # 程式宣告優先;None 才看 env,env 沒有才用預設

def set_reserve_units(n):
    """呼叫端宣告自己屬於哪一層。放在進入點,不要放模組層級。"""
    global _reserve_units
    _reserve_units = int(n)
```

| 層 | 誰 | 宣告位置 | 值 |
|---|---|---|---|
| 1 | `daily_publish` | `main()`(`:1112`)**內** | `set_reserve_units(0)` |
| 2 | 時事發布 | `produce_batch._publish_now`(`:6243`) | `set_reserve_units(23100)` |
| 3 | 其餘全部 | 不宣告 | `DEFAULT_RESERVE_UNITS = 24750` |

🔴 **宣告必須放在 `main()` 內,不能放模組層級** ——
`_publish_now` 是 `import daily_publish as dp`(`:6246`),模組層級的程式碼會被執行、
`main()` 不會。放模組層級會讓時事片誤升到層 1,把整個保護反轉過來。

## 這一版比環境變數版好在哪

| | 環境變數版(第三版) | 程式宣告版(定案) |
|---|---|---|
| crontab 要改幾行 | 4 | **0** |
| 手動執行 | **靜默落到層 3、發布被自己卡住** | 與排程一致 |
| 落地順序風險 | 順序弄反 → 當晚發布全滅 | **消失**(沒有「先改 cron」這一步) |
| 忘記宣告的後果 | 靜默 | 不可能忘(在程式裡) |
| 要改的檔 | quota_meter + crontab | quota_meter + daily_publish 1 行 + produce_batch 1 行 |

env 仍保留為覆蓋層(給臨時調整用),優先序:**程式宣告 > env > 預設**。

## 第四輪其餘結論(不阻擋,記一筆)

- **層 1 內部**(18:00 `--max 1` 與 18:30 `--max 10`)彼此不協調 —— 但**改版前完全一樣**,
  本來就只靠 `--max` 與 ENFORCE 硬頂兜底,不是本次引入的風險。
- **不會「清空明天」**:配額日 15:00 重置,每天都是新的 26,001。
  若 daily_publish 超支,層 2/層 3 的門檻高於它的目標值,會自動更早卡住,不存在無保護狀態。
- **落地驗證法(零配額、不必等 18:00)**:實際排程器是 `local_cron.py`,
  它**每 60 秒重讀 `deploy/crontab.txt`**(`:338-349`),改檔免重啟;
  `run_job()`(`:259-262`)是 `env = {**env, **jenv}`,jenv 後蓋,`.env` 蓋不掉它
  (且 `.env` 內只有 `YT_QUOTA_ENFORCE=1`,沒有任何 `YT_QUOTA_RESERVE*`)。
  ⚠️ `local_cron.py --list`(`:300-302`)**只印時間欄與腳本,不印 jenv**,驗不了環境變數;
  要驗得直接呼叫 `parse_jobs()` 印 `j[7]`。
  ⇒ **定案第四版不靠 env,所以這一段驗證法用不到了**,但留著,因為它同時證明了
  「`crontab.txt` 是活的、`local_cron.py` 是唯一權威讀者」——這件事本身值得記。

## 仍未查完的(不阻擋套用,但不可宣稱已驗)

- `quota_meter.install()` 只掛 `googleapiclient.http.HttpRequest.execute`。
  **若有腳本繞過 googleapiclient、直接用 `requests`/`urllib` 打 YouTube REST API,
  quota_meter 完全看不到也擋不了。** 29+ 支腳本未逐一核對是否全走 `build()`。
  ⚠️ 這個缺口在**任何**方案下都存在,不是本次改動引入的。
- 第三輪列的 16 支「未逐行核實收尾」仍未核實。
- herdr 上其他 session 直接手動跑這些腳本 —— 在定案第四版下已不再是問題
  (層級跟程式走),但繞過 googleapiclient 那一條仍在。
