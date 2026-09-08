# `news12` VECTOR × delay=0：150 條跑完，**0 合格** —— 但診斷不是「沒訊號」

> 續 `docs/ops/2026-09-09_delay0_axis_verdict.md`。全程唯讀,**沒有提交**(Carson 09-03 裁決仍生效)。
> log:`quant-service/brain_alpha/news12_vec_20260909.log`

## 結果

| | 實跑 | 合格 | Sharpe 最高 | Sharpe 中位 | **Fitness 最高** |
|---|---|---|---|---|---|
| `news12` VECTOR **delay=0**(本批) | 150 | **0** | 1.71 | 0.45 | **0.38** |
| `news12` VECTOR delay=1(舊帳) | 951 | **0** | 6.54 | — | 7.31 |
| **合計** | **1,101** | **0** | | | |

本批 150 條**零失敗、零結構性失敗**(VEC_FORMS 模板本身是對的),形式平均分佈
`v_raw` / `v_per_px` / `v_per_cap` 各 50。閘門失敗全體:
`LOW_SHARPE 150` / `LOW_FITNESS 150` / `LOW_SUB_UNIVERSE_SHARPE 88` / `HIGH_TURNOVER 4`。

## 🔴 這件事開跑前就知道得到 —— 答案在同一個 repo 裡

`OFFICIAL_RULES.md:14-15`(**原文**):

> Fitness: "At least *Average*: Greater than **1.3 for Delay-0** or Greater than **1 for Delay-1**"
> Sharpe: "Greater than **2 for Delay-0** Alphas or Greater than **1.25 for Delay-1** Alphas"

同檔 `:123` 甚至把後果直接寫出來了:「D1 門檻較低(Sharpe 1.25 vs 2、fitness 1 vs 1.3)」。

**delay=0 的 Sharpe 門檻高 60%、fitness 門檻高 30%。** 我的實測獨立重現了這兩個數字:

| 量法 | delay=0 | delay=1 |
|---|---|---|
| 被判 `LOW_SHARPE` 的最大 \|sharpe\| | 1.88 | — |
| **沒被判 `LOW_SHARPE` 的最小 \|sharpe\|** | **2.08** | **1.25** |
| 合格樣本的最小 fitness | **1.36** | **1.00** |

(delay=1 那欄的「被判的最大」不可用:我取了絕對值,而 sharpe = −3.97 本來就該被判 LOW_SHARPE。
可用的是**沒被判的下界**,兩邊都乾淨。)

⇒ 本批 fitness 最高只有 **0.38**,離 delay-0 的 1.3 差 3.4 倍 ——
**就算放在 delay-1 的 1.0 門檻下也全滅**。

**這是這條線第三次「答案本來就在同一個 repo 裡」**(前兩次:self-correlation 的官方逃生門寫在
`OFFICIAL_RULES.md:43`;帳本已有 951 次同組合零產出的紀錄)。同族 memory `read-the-sibling-tool-first`。
開跑前 grep 一次 `OFFICIAL_RULES.md` 的成本是零。

## 但「0 合格」不等於「這個領域沒訊號」——真正的死因看得出來

delay=1 那 951 條裡有 **23 條 fitness ≥1.0**,其中 22 條 ≥1.3。它們的數字很強:

| label | sharpe | fitness | turnover | 掛在哪 |
|---|---|---|---|---|
| `main_opening_trading_volume\|v_raw` | 5.84 | 6.30 | 6.9% | `CONCENTRATED_WEIGHT`, `LOW_SUB_UNIVERSE_SHARPE` |
| `main_opening_trading_volume\|v_per_cap` | 5.75 | 6.27 | 7.0% | 同上 |
| `main_opening_trading_volume\|v_per_px` | 5.66 | 6.00 | 7.0% | 同上 |
| `closing_session_volume_count\|v_raw` | 5.41 | 5.65 | 7.0% | 同上 |

**那 23 條全部、且只掛在 `CONCENTRATED_WEIGHT` + `LOW_SUB_UNIVERSE_SHARPE` 這兩項。**

turnover 只有 ~7% 是關鍵線索:新聞事件本來就稀疏,
任一天只有少數股票有事件 → `vec_avg` 之後只有那少數股票帶得動訊號 →
權重集中在它們身上 → `CONCENTRATED_WEIGHT` 必掛,而子宇宙(小型股那半)幾乎沒有覆蓋 →
`LOW_SUB_UNIVERSE_SHARPE` 也必掛。

⇒ **新聞領域的阻礙是「覆蓋稀疏 → 權重集中」,那是模板問題,不是 delay 問題也不是資料集問題。**
現行模板 `group_rank(ts_rank(winsorize(ts_backfill(vec_avg(X),120),std=4),126), subindustry)`
是為**比率型稠密欄位**設計的,`ts_backfill(...,120)` 把 120 天前的舊事件拖來填,
在稀疏事件上等於製造陳舊訊號而不是解決覆蓋。

## 對整條 delay=0 軸的結論

兩個維度量完了,**都比 delay=1 差**:

| 維度 | delay=0 | delay=1 | 出處 |
|---|---|---|---|
| 對已提交池的相關度(中位) | 0.849 | 0.749 | `2026-09-09_delay0_axis_verdict.md` |
| Sharpe 門檻 | **> 2** | > 1.25 | `OFFICIAL_RULES.md:15` |
| Fitness 門檻 | **> 1.3** | > 1 | `OFFICIAL_RULES.md:14` |

換軸的**唯一理由**是降相關,而它沒降;同時它把閘門抬高了 60% / 30%。
**建議停掉 delay=0 這條軸**,把額度放回 delay=1。
(這是建議不是決定 —— 全部 330 條 delay=0 只涵蓋 7 個資料集,
`fundamental2`/`fundamental6` 那 2,856 條候選沒碰過。但那兩個正是已飽和的領域,
所以「沒碰過」不構成繼續的理由。)

## 下一個變因該是什麼(建議,未驗證)

不是 delay,也不是換資料集 —— 是**模板**。具體可測的一步:
針對稀疏事件欄位換掉 `ts_backfill(...,120)` 與 `subindustry` 分群,
目標是把上面那 23 條的 `CONCENTRATED_WEIGHT` 解掉 ——
它們的 Sharpe 5.4~5.8 / fitness 5.6~6.3 已經遠超門檻,**只差權重分佈這一關**。
那是這條線目前看得到最接近成品的東西,而且它在 **delay=1**。

---

## 已排除什麼 / 沒有排除什麼（2026-09-09 補，督導點名）

負結果的價值是擋住下一個人再走一次,所以這兩欄要分開寫。

### 已排除(有實測支撐,不要再花額度)

| 假設 | 憑什麼排除 |
|---|---|
| 「`news12` VECTOR 只是還沒掃夠」 | 兩個 delay 合計**實跑 1,101 條、0 合格**;delay=0 那 150 條零失敗零結構性失敗,模板跑得動 |
| 「VEC_FORMS 模板餵 VECTOR 有結構性問題」 | 本批**結構性失敗 0**。1,173 列結構性失敗是**舊模板**的舊帳,已修 |
| 「換 delay=0 會讓新聞領域過得了」 | fitness 最高 **0.38**,delay-0 門檻 1.3、delay-1 門檻 1.0,**兩個都全滅** |
| 「delay=0 只是門檻沒差多少」 | 官方明文 Sharpe 2 vs 1.25、fitness 1.3 vs 1(`OFFICIAL_RULES.md:14-15`),實測獨立重現(未被判 LOW_SHARPE 的最小 \|sharpe\|:2.08 vs 1.25) |
| 「這個領域沒訊號」 | **反向排除**:delay=1 有 23 條 Sharpe 3.4~6.5 / fitness 1.2~7.3。訊號在,過不了閘門 |

### **沒有**排除(不要當成已知)

| 仍然未知 | 為什麼還沒答案 |
|---|---|
| `news12` 的 **MATRIX** 欄位(delay=0 有 75 個) | 一條都沒掃過。本批只掃 VECTOR |
| 其他 `vec_*` 運算子 | 本帳號只開放 `vec_avg` / `vec_sum`(`OPERATOR_SIGS.txt` 實查),而我們只用了 `vec_avg`。**`vec_sum` 沒試過** |
| `news18`(delay=0 有 24 個欄位) | 完全沒碰。它是另一個新聞資料集 |
| 那 23 條解掉 `CONCENTRATED_WEIGHT` 之後會不會過 | 正在做,見 `2026-09-09_news12_template_prereg.md` |
| delay=0 的 `fundamental2` / `fundamental6`(2,856 條候選) | 沒碰。但那是已飽和領域,**沒碰不構成該碰的理由** |
| 「新聞領域對已提交池的相關度低不低」 | **無法知道** —— 0 合格就沒有 PnL 可量。這正是負結果最貴的地方 |

### 下一步(建議,與上面兩欄分開)

見 `docs/ops/2026-09-09_news12_template_prereg.md`。一句話:
變因換成**模板**、戰場回到 **delay=1**(23 條強者住在那裡,門檻還低 60%/30%)。
⚠️ 那份事前預期裡記了一件比 `CONCENTRATED_WEIGHT` 更根本的事:
**5 條的 sub-universe Sharpe 是負的** —— 訊號不住在大型股,而擴大覆蓋生不出那裡的訊號。
