# ch3 長片分發管道實測證據(sec ch.,2026-09-01 結案)

> 本檔內容自 `docs/ops/premises.md` 第 2 條原文搬出(09-02 格式壓縮,登記處只留指標)。
> 實測與結論皆為 sec ch. 的工作,原文照錄;sec ch. 可自行搬到自己線的目錄。

## 結論:長片沒有分發管道(不是被壓制,是沒有門)

- 分格式 08-23~08-31:長片 **4 次觀看** vs Shorts **203**
- 流量來源:SHORTS feed 191、搜尋 6、頻道頁 6、訂閱 1、**瀏覽與推薦 = 0**
- 22 支長片全部 public + processed + 無 rejectionReason —— 排除「被壓制」假說
- `impressions`/CTR 這個頻道回 400 拿不到,以流量來源代理

## 搜尋盤點(另計)

14 支裡同時滿足「自動完成有該字串」+「現有結果過萬觀看」+「第一頁非大頻道佔滿」的是 **3 支**:
hungry_judges / sugar_hyperactivity / dunning_kruger。
marshmallow、hot_hand、false_memory 第一頁分別被 SciShow、Numberphile、TED 佔第一 → 判 0 不是 0.5。

## 承重轉移

整條 ch3 產能是否續投:**改由「那 3 支的搜尋長尾打不打得到」承重,長片格式本身不再是待驗項。**

---

## 驗收:09-02 停排程這件事有沒有生效(任何人都能跑,不需要今晚的脈絡)

**背景**:09-02 把 `youtube_channel/deploy/crontab.txt` 的 732/733/734
(ch3_publish 的 8:25 / 14:25 / 20:25)註解掉。741 的 `ch3_health` 刻意留著。

**🔴 不要拿 `ch3_health` 的推播當驗收。** 它的設計是「只在有事時才推播」,
而我們期待的結果**正是沒事**。於是:

| 真實狀況 | 健檢行為 |
|---|---|
| 改動成功,沒發 | 不推播 |
| 健檢自己沒跑 / local_cron 死了 / 整個排程掛了 | **也不推播** |

兩者長得一模一樣 —— 那是 memory `verification-that-cannot-fail` 的第一種:
**不會叫的警報**。09-01 那整晚在修的就是這個形狀,結果驗收方式自己又是一個。

### 正向檢查(兩條,都有輸出)

**基準(2026-09-02 台北 10:00 實測)**:
`uploaded_shorts.json` = **37**、`uploaded.json` = **22**、`uploaded_comp.json` = **1**

**① 帳本筆數沒變 → 真的沒發**

```bash
cd D:/carson-agent/ch3_lab
python -c "import json,pathlib; print({f: len(json.loads(pathlib.Path(f).read_text('utf-8'))) for f in ('uploaded_shorts.json','uploaded.json','uploaded_comp.json')})"
# 期待 {'uploaded_shorts.json': 37, 'uploaded.json': 22, 'uploaded_comp.json': 1}
# 任何一個變大 = 還有第三條觸發路徑,今晚的結論是錯的
```

**② 排程日誌有別的 job、但沒有 ch3_publish → 排程活著且 ch3 真的停了**

> 🔴 **2026-09-02 11:05 修正**:原本這裡寫的是 `youtube_channel/logs/cron.log`,
> **那個檔案在本機不存在**(`cron.log` 是 crontab 行尾 `>> /root/yt/logs/cron.log`
> 留下的雲端路徑;本機 local_cron 寫的是 `local_cron.log`)。照原指令跑會得到
> 「No such file or directory」、stdout 空白 —— **一個為了修沉默通道而寫的檢查,
> 自己又是沉默的**。同一形狀第五次。改成存在的路徑,並加上日期過濾。

```bash
cd D:/carson-agent
TODAY=$(date +%Y-%m-%d)
L=youtube_channel/logs/local_cron.log
[ -f "$L" ] || echo "🔴 日誌檔不存在 —— 這本身就是警報,不要當成『沒發』"
# 09-02 當天用這個(要排掉 08:25 那次 —— 它在改動之前,不是失敗):
grep "$TODAY 1[4-9]:\|$TODAY 2[0-3]:" "$L" | grep -c ch3_publish   # 期待:0
# 09-03 起用這個(整日都在改動之後):
grep "$TODAY" "$L" | grep -c ch3_publish                            # 期待:0
# 兩者共用的活性檢查:
grep -c "$TODAY" "$L"                      # 期待:遠大於 0(排程活著;若是 0 = 排程死了,真警報)
```

> ⚠️ **09-02 當天的陷阱(實跑後才發現)**:直接數整日會得到 **2**,那是
> `[2026-09-02 08:25:03] ▶ 啟動` 與 `08:25:49 ✓ 完成` —— **改動前**的正常執行。
> 不做時間過濾就會把它讀成「還有第三條觸發路徑」,**一個把成功誤報成失敗的假警報**。
> 沉默通道的反面同樣要防。

**判讀表**(兩個數字要一起看,單看任一個都會誤判):

| 今日 ch3_publish | 今日總筆數 | 結論 |
|---|---|---|
| 0 | 大(數百) | ✅ 改動成立:ch3 停了、排程活著 |
| 0 | 0 | 🔴 **排程整個死了** —— 不是成功,是最該處理的狀況 |
| >0 | 大 | 🔴 還有第三條觸發路徑,09-02 的結論是錯的 |

第二條是用來**區分「ch3 沒發」和「整個排程死了」**的 —— 後者才是真警報,
而且它在只看第一條時會偽裝成前者(帳本也不會變)。

### 什麼時候跑:**09-02 14:30**,不是隔天早上

> 🔴 **2026-09-02 11:05 修正**:原本寫「明天 9:30 的 ch3_health」。**時間點錯了。**
> 三個發布時段是 8:25 / 14:25 / 20:25,而 cron 是 09-02 約 10:00 註解掉的 ——
> 所以第一個真正的試驗是**當天 14:25**,不是隔天 8:25。日誌實證:
> `[2026-09-02 08:25:03] ▶ 啟動 scripts/ch3_publish.py` 是**改動之前**跑的那次,
> 它證明的是排程原本會發、不是改動失敗。
> **驗收提前約 19 小時,14:30 就能得到是/否。**

### 這件事不需要任何 session 掛著等

上面兩條是兩個指令,誰在都能跑,結果是明確的是/否。
**不要為了等一行日誌而讓 session 活著** —— 記憶體成本高於價值。

---

## 🔴 2026-09-03 複驗:搜尋盤點的正確答案是 **0**,而且「搜尋沒被測過」這個假設是錯的

09-02 給總督導的數字是 **3**(hungry_judges / sugar_hyperactivity / dunning_kruger)。
09-03 派了一個**盲驗**(不告知先前結論,避免錨定)獨立重量,得到 **0**。兩份在具體題目上
直接衝突,所以我自己做了第三次量測。**兩份先前的量測各自都有錯,方向相反。**

### 錯因一:suggest 端點會把你打的字原樣回吐

打完整字串 `hungry judge effect` 會拿到它自己當第一筆建議 —— 那是回吐,不是需求證據。
**正確測法是打前綴看它補不補得出來**:

| 前綴 | 補完結果 | 判定 |
|---|---|---|
| `hungry judge` | → **hungry judge effect** | ✓ 真需求(盲驗員判錯,它只測了空的 `...debunked` 變體) |
| `does sugar cause` | → diabetes / cholesterol / acne / cancer / inflammation | ✗ **兩份先前量測都錯**,sugar 那題沒有需求 |
| `dunning kruger effect de` | → **debunked** | ✓ 真需求 |
| `marshmallow test de` | → **debunked** | ✓ 真需求 |
| `mozart effect de` | → mozart smart music | ✗ |

### 錯因二:「第一頁最高觀看 ≥ 10,000」這個需求代理是壞的

`hungry judge effect` 第一頁實測(search.list,2026-09-03):

| 名次 | 觀看 | 頻道(訂閱) |
|---|---|---|
| 1 | 806,627 | StarTalk(5,880,000) |
| 2 | 37 | facts4you(0) |
| 3 | 235 | Psych Papers(879) |
| 4 | 344 | Life and a bit more(1,840) |
| 5 | 23,532 | Wisdom Time(3,090) |
| 6 | 14 | روان نشناس(42) |
| 7 | 593 | Short Story…(1,490) |
| **8** | **0** | **One Quiet Hour(1)← 我們自己** |
| 9 | 424 | Psych Papers(879) |
| 10 | 65 | John C. Checco(4) |

StarTalk 的 80 萬觀看來自**它有 588 萬訂閱**,不是來自這個 query 的流量。
同一頁上每個小頻道都只有 14~593 次觀看。**第一頁的觀看數量的是頻道的觸及,不是 query 的量。**
兩份先前量測都拿它當條件 A 的證據,所以都被同一個混淆項騙了。

### 🔴 最重要的一項:搜尋不是「沒被測過」,是**測過了,結果是 0**

第 8 名那支是我們自己的 `hungry_judges`。**它早就上線了**,標題含完整 query 字串,
在這個有真實自動完成需求的 query 上**排進第一頁,而且第一頁沒有被大頻道佔滿**
(2~10 名全是 0~3,090 訂閱的小頻道)—— 條件 B 其實成立。

**然後它拿到 0 次觀看。**

這推翻了 09-03 上午我自己提的假設(「長片標題從來沒對準過 query,所以搜尋這個入口沒被敲過」)。
敲過了。在最有利的條件下 —— 有需求、搶得到位、標題對準 —— 結果仍是 0。
**所以結論從「推論長片沒有分發」升級為「在最好的情況下實測仍為 0」。**

### 附帶抓到:帳本與頻道實況不同步(重傳風險)

`uploaded.json` 22 筆全部以 `eps/epNNN` 為 key,**不記 rechecked 的 slug**。
拿 slug 去查一律得到「未發布」。實際比對頻道上線影片:**14 支 rechecked 有 10 支已經在線上**
(不在的只有 facial_feedback / moral_licensing / stanford_prison / sugar_hyperactivity)。

09-01 那份「11 支未發布長片」和 09-03 我自己那份「三支可搶的都未發布」**都是被這個 key 不一致騙的**。
🔴 若日後有人重啟 ch3 並用 `--only <slug>` 出貨,**帳本擋不住重傳**。
那三本帳是唯一防重傳的東西,而它現在對 rechecked 這個 kind 是盲的。
