# 事前預期：正規化假說的配對檢定（`pv13`，9 組三元組）

> **寫在量之前**,量完逐條對答案。提交仍照 Carson 09-03 裁決停著,**零提交動作**。
> 檢定對象:`130edfe3` 提出的假說 —— 共同因子是**模板的正規化**(`/close`、`/cap`)而不是資料領域。

## 先答督導問的那個對不上的數:**兩邊都對**

18 條合格裡確實有 **2 條 raw**:`1YwPvoJk`(`ompetitorgraphrank_hub_rank`)、
`qMj3AjbZ`(`revere_key_sector_total`)。
而我報告的 17 條是**扣掉已提交的 `qMj3AjbZ`** 之後的,所以剩 **1 條 raw**。
督導猜的那個條件(「只有在被排除的正好是第二條 raw 時才對得起來」)**正是實際情況**。
沒有人數錯。

## 🔴 那 8 條模擬不用跑 —— 資料已經在帳本裡

派工單設計是「跑這 8 個欄位的 raw 形式 = 8 條模擬」。**查過帳本後:不需要。**
`field_miner` 的一階掃描本來就是**一個欄位跑三種形式**,所以那些 raw 早就跑過了,
只是**沒過閘**所以不在「18 條合格」裡:

| 欄位 | raw | per_px | per_cap |
|---|---|---|---|
| `com_rk_au` | `zqk05NJG` sh=1.19 | `gJjdmbgv` sh=1.65 ✅ | `O07VnW5g` sh=1.64 ✅ |
| `ompetitorgraphrank_hub_rank` | `1YwPvoJk` sh=**1.67** ✅ | `omqr2l9k` sh=1.49 | `d5joq1Jg` sh=1.50 |
| `revere_index_cap` | `np7Qwz23` sh=0.91 | `E5lLokYP` sh=1.66 ✅ | `N173kRR8` sh=1.64 ✅ |
| `revere_index_value` | `1YwKxZ8R` sh=0.86 | `j2jG3abk` sh=1.62 ✅ | `YP7z5EKv` sh=1.60 ✅ |
| `revere_key_sector_total` | `qMj3AjbZ` sh=1.65 ✅**已提交** | `ZY7MpbJY` sh=1.76 ✅ | `ak7wdarR` sh=1.76 ✅ |
| `revere_term_sector_total` | `3ql5zW5X` sh=1.24 | `RR7KdZP0` sh=1.75 ✅ | `QP7gEl2w` sh=1.81 ✅ |
| `ustomergraphrank_auth_rank` | `rKjG7nL8` sh=1.28 | `wpjGo0j1` sh=2.02 ✅ | `6Xl0GOO7` sh=2.06 ✅ |
| `ustomergraphrank_hub_rank` | `Vk7zb65V` sh=1.33 | `Vk7zbZxY` sh=1.66 ✅ | `np7q5L2q` sh=1.67 ✅ |
| `ustomergraphrank_page_rank` | `j2jGKmoE` sh=1.13 | `KP7zM68j` sh=1.52 ✅ | `omqG0YWm` sh=1.57 ✅ |

⇒ **9 組完整三元組**(不是 8 組配對),**0 條新模擬**,只需補抓 PnL。
而且這正好滿足派工單「不論過不過閘一律量」那條:8 個 raw **本來就是沒過閘的**,
所以「raw 相關低」與「被收下的相關低」在這批資料裡**是分得開的**。

## 🔴 但這批資料自帶一個新的混淆:雜訊衰減

raw 的 Sharpe 是 **0.86~1.33**,per_* 是 **1.49~2.06**。
**訊噪比低的序列,跟任何東西的相關度都會被衰減。**
所以「raw 相關低」有一個跟正規化無關的解釋:**它只是比較吵**。
這個混淆在派工單的設計裡沒有被拆掉,而它足以單獨產生我要找的那個圖案。

**拆它的那一格是 `ompetitorgraphrank_hub_rank`** —— 唯一一組 raw 的 Sharpe(1.67)
**高於**它自己的 per_px(1.49)與 per_cap(1.50)。
在這一組裡,雜訊解釋預測 raw 相關**不低**;正規化解釋預測 raw 相關**仍然低**。
**這一格是整個實驗的判別點。**

## 事前預期(寫死數字)

| # | 預期 | 判定 |
|---|---|---|
| 1 | 9 組裡 **≥7 組** `corr_raw < min(corr_per_px, corr_per_cap)` | 計數 |
| 2 | raw 的 max\|corr\| **中位數 < 0.60**;per_* 的中位數 **≥ 0.72** | 中位數 |
| 3 | **判別點**:`ompetitorgraphrank_hub_rank` 這一組,raw **仍然**低於它的 per_px 與 per_cap | 逐條 |
| 4 | (raw−per_cap 的相關度差)與(raw−per_cap 的 Sharpe 差)**沒有**強關聯 | 看 9 點的散佈 |

## 三種結果分別長什麼樣

| 結果 | 判定 | 意義 |
|---|---|---|
| 預期 1 **且** 3 都成立 | **支持假說** | 正規化是共同因子 ⇒ 模板要改,而且改的是 `/close`、`/cap` 這一層 |
| ≤4 組 raw 較低,**或** 判別點那組 raw 反而較高 | **推翻假說** | 圖案是雜訊衰減造成的 ⇒ **不要把模板改成 raw**,那只會換來一批更弱的 alpha |
| 5~6 組,或預期 1 成立但判別點失敗 | **沒有結論** | 兩個解釋分不開,要另外設計(例如拿 Sharpe 相近的配對子集重比) |

🔴 **最容易被我報成成功的失敗形態**:預期 1、2 都漂亮成立(raw 中位 0.5、per_* 中位 0.75),
我就宣布「正規化是元兇、模板該改」—— 而那整個圖案只是「raw 比較弱所以比較不像任何東西」。
⇒ **預期 3 沒過,就不可以說假說成立**,不管 1 和 2 多好看。
而且真要改模板成 raw 的代價是明擺著的:**那 8 條 raw 全部沒過閘**。
「相關度低但過不了閘」不是跑道,是零。
