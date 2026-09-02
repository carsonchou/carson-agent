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
