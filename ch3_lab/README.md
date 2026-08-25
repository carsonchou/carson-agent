# ch3_lab — They Ran It Again

副頻道(`UCbo4EytWhZ7zAGSoIPioJ5g`,crayray8686 帳號)的產線:拿一個當年的
心理學發現,把原始研究與大規模重測的數字並排。

**這個頻道唯一的資產是「片中每個數字都能溯源、沒有一個是編的、沒有過度打臉」。**
所有設計決定都是為了讓那句話結構上為真,而不是靠自律。

## 兩條線,不共用模板

| | FReD 線 | 名案線 |
|---|---|---|
| 資料 | `facts/episode_queue.csv`(FORRT Replication Database) | `facts/famous_episodes.json`(逐句人工核對) |
| 形狀 | 一篇原始研究 **對** 一篇重複研究,兩邊都有 N 和效果量 | 綜合分析或多實驗室重測;**原始效果量常常根本不存在** |
| 敘事 | 0.55 → 0.03,樣本大 143 倍 | 被引用 4,928 次 → 23 個實驗室測出 0.04,CI 跨零 |
| 產生器 | `make_episode.py --row N` | `make_famous.py --slug X` |
| 產出 | `eps/epNNN/` | `eps_famous/<slug>/` |

硬把名案塞進 FReD 的模板會扭曲事實——它會逼你去比較一個你手上沒有的數字。

## 流程

```
build_queue.py          # FReD 母體 → 佇列(雙重去重,見下)
backfill_dois.py        # 缺的 DOI 去 Crossref 補(相似度≥0.90 且年份差≤1)
make_episode.py --row N # 稿 → TTS → 圖表 → mp4
make_famous.py --slug X
publish_meta.py         # 標題/說明/標籤,DOI fail-closed
make_thumbs.py          # 1280x720 縮圖
upload.py --limit 3 --privacy unlisted
upload.py --flip public # 整包帶齊 status,不會洗掉兒童宣告
```

三路並行重產:`_w0.sh` / `_w1.sh` / `_w2.sh`(切片互斥,worker i 只跑
`seq i 3 18`)。**不要另外再 nohup 單集**——曾經有兩個 `romantic_red`
同時跑、互相刪對方的產出。

## 踩過的坑(改之前先讀)

**判定只能有一份。** `tone_of()` 是唯一的定調來源,旁白和收尾視覺卡都用它。
先前視覺卡自己寫了一套二分法,於是 ep005 旁白說「效應不在那裡」、畫面同時
打出「This one held up」。這是這個專案重複發生的模式(閘門兩份、縮圖兩份、
判定兩份)——**修好一份、漏掉另一份**。

**數字溯源得到 ≠ 話講得對。** 稿子產生後一定要印出來逐句讀。實測抓到六個
審核抓不到的錯,全都是「數字對但意思錯」:`abs()` 把 CI `[-0.07, 0.15]` 唸成
「from 0.07 to 0.15」(跨零被講成整段在零右邊)、拿 d 的門檻去講 r 型效果量、
拿手上沒有的原始效果量去比較、沒算過的基準率、437 次引用配「一整片心理學蓋在
上面」。

**要真的把畫面開起來看。** 曾經整批片渲染成功、時長正確、mp4 產得出來,
但**畫面上一個字都沒有**(滿版軸沒鎖 `set_xlim(0,1)`,`ax.plot` 自動縮放把
文字裁到畫面外)。任何自動檢查都不報錯。

**旁白唸的東西畫面上要看得到。** 紅色那集旁白唸「女性那組是 −0.09」時,
畫面只有男性的 `0.09`——觀眾聽到負數、看到正數。

**雙重去重是必要的。** 只按原始研究去重會生出 16 集「X 與外向性正相關」
(同一篇大型重測只換特質名),正中 YPP inauthentic 定義的「模板化、變化極小、
可大規模複製」。要按原始研究**和**重複研究都去重。

**fail-closed 讓數量變少是它在工作。** DOI 湊不出兩個真的就不准發。想讓數字
好看,正解是回頭補 DOI(`backfill_dois.py`),不是放寬 `is_doi()`。
「讓更多東西通過」的改動在這條產線上是紅旗。

**不要用 heredoc 餵 Python 改檔案。** 反斜線逃逸會被吃掉:`\n` 變真換行(會
報語法錯),`\b` 變**退格字元 0x08**(正則永遠不匹配,而且不報錯)。用 Edit/Write。

## 承諾與內容的對應

頻道簡介寫著「Not everything fails. Replications that succeeded get their own
episodes.」——所以佇列**必須真的排進 HOLD 軌**(目前 19 集裡 6 集)。這種
「方法論宣稱」守門結構上看不見(它不含可疑數字),只有回頭看整個佇列的分布
才抓得到。改佇列規則時要一併確認這句話還站得住。

## 卡住的事

頻道名與 @代號都被 YouTube 冷卻期擋住,**只能在 Studio UI 改,API 設不了**
(`channels.update` 帶 title 會回 200 但靜默不改,一定要回讀):
- @代號 → `@theyranitagain`:**2026-08-28** 後
- 頻道名 → `They Ran It Again`:**2026-09-03** 後

進 ch2 的 Studio 要帶 `?authuser=1`。
