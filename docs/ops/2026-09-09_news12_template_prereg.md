# 事前預期：改模板解 `CONCENTRATED_WEIGHT`（`news12` × delay=1）

> **這份寫在跑之前**,跑完直接對答案。督導要求(總督導轉達)。
> 提交仍照 Carson 09-03 裁決停著,本實驗零提交動作。

## 這次跟昨晚那個負結果差在哪(先答這題,答不出來就是重跑)

| | 09-09 上午(已完成,負結果) | **本實驗** |
|---|---|---|
| 自變因 | `delay`(1 → 0) | **模板 / truncation** |
| 應變數 | self-correlation | **`CONCENTRATED_WEIGHT`** |
| 資料集 | analyst4 / news12 | news12(同一批已知強欄位) |
| delay | 0 | **1** |

**不是換軸,是回到證據所在地。** 那 23 條強者本來就住在 delay=1,而 delay=1 的門檻還低 60%/30%
(`OFFICIAL_RULES.md:14-15`)。我先前把它寫成「換軸」是錯的措辭,已更正。

## 前提修正:天花板是 19 不是 23(督導 wF:p4 指出,我獨立重驗)

23 條只有 **19 個相異 `(sharpe, fitness, turnover)` 指紋**。兩組近別名:

| 配對 | `v_raw` | `v_per_px` | `v_per_cap` |
|---|---|---|---|
| `all_sessions_volume_weighted_avg_price` vs `aggregate_session_vwap_2` | 不同(2.11/1.35 vs 1.92/1.16) | **完全相同** | **完全相同** |
| `main_opening_trading_volume` vs `opening_session_volume_count` | **完全相同** | **完全相同** | 不同(5.75/6.27 vs 5.77/6.31) |

⇒ 是**部分別名**不是全等。效果上當別名處理,但別寫成「同一個欄位」。
而且 19 條**全落在同一族**(開盤/收盤/盤前/盤後的 session 成交量與 VWAP)——
**不是 19 個獨立賭注**。就算全部解掉,也要預期它們彼此高度相關,可提交量遠少於 19。

## 🔴 開跑前發現的更根本問題:訊號不住在大型股

`OFFICIAL_RULES.md:60-62` 的門檻是**比例式**的:
`sub_universe_sharpe ≥ 0.75 × sqrt(1000/3000) × alpha_sharpe` ≈ **0.433 × alpha_sharpe**。
而 TOP3000 的 sub-universe 是 **TOP1000 —— 更大更流動的那一半**。

把 23 條逐格代入:

| 缺口(sub − cutoff) | 格數 | 代表 |
|---|---|---|
| ≥ −0.30(擦邊) | 4 | `main_opening_trading_volume\|v_per_px` **−0.13** |
| −0.30 ~ −0.80 | 4 | `main_post_session_vwap\|v_per_px` −0.72 |
| < −0.80 | 15 | 最差 −2.55 |
| **其中 sub_sharpe 本身為負** | **5** | `closing_session_volume_count\|v_raw` **−0.02** |

**sub_sharpe 為負 = 這條 alpha 在 TOP1000 上是虧錢的。** 那不是權重分佈問題,
是訊號只存在於流動性較差的那一段。**擴大覆蓋不會憑空生出大型股上的訊號。**

而且比例式門檻有個反直覺後果:**headline Sharpe 越高,要過的 cutoff 越高**。
這幾條 Sharpe 5~6.5 反而讓自己更難過關。

## 要跑什麼

- **欄位 6 個**(每組近別名各留一個):`main_opening_trading_volume`、
  `all_sessions_volume_weighted_avg_price`、`closing_session_volume_count`、
  `premarket_volume_weighted_avg_price`、`main_post_session_vwap`、`after_hours_vwap_value`
- **形式 2 種**:`v_raw`、`v_per_px`。**刻意不跑 `v_per_cap`** ——
  `OFFICIAL_RULES.md` sub-universe 官方建議第 1 條逐字:
  *"Avoid using multipliers related to the size of the company"*,而 `/cap` 正是那個東西。
  (代價:`v_per_cap` 是目前 fitness 最高的形式(7.31)。**我選過關不選分數。**)
- **變體 3 個**(2×2 減去已量過的基準格):

| 代號 | 運算式 | truncation | 動了什麼 |
|---|---|---|---|
| 基準 | `group_rank(ts_rank(winsorize(ts_backfill(vec_avg(F),120),std=4),126), subindustry)` | 0.1 | **已量過**,見上表 |
| **A** | `group_rank(ts_rank(group_backfill(vec_avg(F), subindustry, 120, std=4),126), subindustry)` | 0.1 | 補值來源:自己的歷史 → **同產業同儕** |
| **B** | 同 A | **0.05** | A + 壓單股權重上限 |
| **C** | 同基準 | **0.05** | 只動 truncation,分離設定的效果 |

6 × 2 × 3 = **36 條**。

⚠️ **A 有一個承認的混淆**:`group_backfill(x, group, d, std=4)` 自帶 std ⇒ 外層的
`winsorize(..., std=4)` 被它吸收掉了。所以 A 同時改了「補值來源」和「winsorize 的位置」。
不拆是因為拆開要多一組 12 條,而 `group_backfill` 的自然用法就是這樣。**若 A 有效,
不能斷言是補值來源的功勞。**

## 事前預期(可證偽,跑完逐條對)

**主要應變數:`CONCENTRATED_WEIGHT` 從 `failed` 消失的格數(共 36 格)**

1. **A / B 會解掉 ≥ 半數**(≥12/24 格)。理由:官方把 weight test 拆成兩個分支
   (`OFFICIAL_RULES.md:31`)——「被賦權的股票太少」與「單一股票權重過高」。
   官方三個修法(`rank`、`truncation 0.1`、`ts_backfill`)我們**全都已經做了**還是掛,
   ⇒ 我們掛在「股票太少」那支,而 `group_backfill` 正是唯一能跨股票補值的工具。
2. **C 不會解掉**(≤2/12 格)。理由:truncation 0.1→0.05 只壓單股上限,
   **不增加被賦權的股票數**。
   👉 **若 C 也解掉了,我對失敗成因的判斷就是錯的**(是「單股過高」不是「股票太少」)。

**次要應變數:`sub_sharpe / (0.433 × sharpe)` 這個比值**

3. 比值會上升,但**只有原本缺口 ≥ −0.80 的那 8 格有機會真的過**。
4. **原本 `sub_sharpe` 為負的 5 格,預測仍然過不了。** 那不是權重問題。

**整體判準**

| 結果 | 判定 | 之後怎麼辦 |
|---|---|---|
| ≥1 條 `evaluable_pass` | **成功** | 量它對已提交池的相關度,再談下一步 |
| CONCENTRATED_WEIGHT 解掉 ≥12/24 但 sub-universe 全擋 | **部分成功** | 診斷一對一錯,兩個閘門是獨立問題;新聞族的瓶頸是「訊號不在大型股」 |
| CONCENTRATED_WEIGHT 一格都沒解 | **失敗** | 覆蓋不是這兩個槓桿能動的,**新聞領域收工**,不要再有第三批 |

**🔴 最可能發生、且最容易被報成成功的失敗形態**:
`CONCENTRATED_WEIGHT` 解掉了,但 Sharpe 從 5+ 崩到 1.25 以下 ——
`group_backfill` 把同儕值灌進沒有新聞的股票,等於用雜訊稀釋訊號。
**那是用一個閘門換另一個閘門,不是進展。**
⇒ 跑完的回報**必須同時給 Sharpe 的變化**,不可以只報「閘門過了幾格」。
預先講明:若 A/B 的 Sharpe 中位數掉到 1.25 以下,我會把它報成失敗而不是「解掉了」。
