# 時事發布拿不到 1,600 —— 根因是預留的**粒度**,不是排序(2026-09-05,基建線督導)

> 狀態:**設計已定、patch 未套用**。動 `quota_meter.py` 與 crontab = 正式機,
> 依 CLAUDE.md 須先過 fresh-context 獨立驗證,零例外。

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
