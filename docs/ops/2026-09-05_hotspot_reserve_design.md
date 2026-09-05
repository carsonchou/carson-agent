# 時事發布拿不到 1,600 —— 根因是預留的**粒度**,不是排序(2026-09-05,基建線督導)

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
