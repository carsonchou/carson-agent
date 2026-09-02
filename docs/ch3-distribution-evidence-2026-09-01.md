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

**② cron.log 有別的 job、但沒有 ch3_publish → 排程活著且 ch3 真的停了**

```bash
cd D:/carson-agent
grep -c ch3_publish youtube_channel/logs/cron.log   # 期待:今日區段 0 筆
tail -40 youtube_channel/logs/cron.log              # 期待:看得到其他 job 的正常紀錄
```

第二條是用來**區分「ch3 沒發」和「整個排程死了」**的 —— 後者才是真警報,
而且它在只看第一條時會偽裝成前者(帳本也不會變)。

### 這件事不需要任何 session 掛著等

上面兩條是兩個指令,誰在都能跑,結果是明確的是/否。
**不要為了等 23 小時後讀一行日誌而讓 session 活著** —— 記憶體成本高於價值。
