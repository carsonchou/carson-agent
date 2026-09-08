# 模板實驗對答案：**失敗** —— 三個變體、0 格解掉 `CONCENTRATED_WEIGHT`

> 事前預期:`docs/ops/2026-09-09_news12_template_prereg.md`(**跑之前**落檔,commit `0633118d`)。
> 本檔逐條對答案。提交仍照 Carson 09-03 裁決停著,本實驗零提交動作。

## 逐條對事前預期

| # | 事前寫的 | 實際 | 判定 |
|---|---|---|---|
| 1 | A/B(`group_backfill`)解掉 **≥12/24** 格 | **0 格** | ❌ **我錯了** |
| 2 | C(truncation 0.1→0.05)解掉 **≤2/12** 格 | **0 格** | ✅ 對,而且比我預期的更硬(見下) |
| 3 | 原本 `sub_sharpe` 為負的 5 格仍過不了 | 沒有任何一格過任何一關 | ─ 無從檢定 |
| 4 | 整體:0 格解掉 ⇒ **失敗,新聞領域收工** | 0 格 | **觸發停止條件** |

`evaluable_pass`:**0 / 35**。

## 預期的失敗形態發生了,而且比預期更糟

事前寫:「最可能且最容易被報成成功的失敗形態 = 閘門解掉但 Sharpe 從 5+ 崩到 1.25 以下」。
實際是**閘門沒解掉、Sharpe 還先崩了**:

| 欄位 / 形式 | 基準 sh/fit | A、B 的 sh/fit | `CONCENTRATED_WEIGHT` |
|---|---|---|---|
| `all_sessions_vwap` `v_per_px` | 6.08 / 6.80 | **−0.22 / −0.05** | 仍在 |
| `main_post_session_vwap` `v_per_px` | 4.21 / 4.09 | **−1.58 / −1.00** | 仍在 |
| `closing_session_volume_count` `v_raw` | 5.41 / 5.65 | **1.54 / 0.92** | 仍在 |
| `premarket_vwap` `v_raw` | 2.80 / 2.31 | 3.39 / 3.57(**變好**) | 仍在 |

`group_backfill` 把同儕值灌進沒有新聞的股票 —— 訊號被雜訊稀釋,而覆蓋仍然不夠。
4 格裡 3 格崩、1 格變好,方向不一致但**沒有一格動到閘門**。

## C 的結果比「沒解掉」更有資訊:truncation 根本沒被觸發

C 的 12 格裡有 **8 格的 Sharpe / fitness 與基準到小數點第二位完全相同**
(`main_opening_trading_volume|v_per_px` 5.66/6.00 = 5.66/6.00,以此類推)。

排除「平台把它當同一條」這個解釋:

- 11 組可比對的 `alpha_id` **全部不同**(基準 `2rOEYGZ8` vs C `j23rqEWe`,以此類推)
- 從 `expr + settings` 反推 `_key`:**符合 truncation=0.05、不符合 0.10**

⇒ 它們是**真的用 0.05 重跑了一次,結果一模一樣**。
`truncation` 是「單一股票的權重上限」,結果不變代表**從來沒有股票的權重碰到那個上限**。

**這把 `CONCENTRATED_WEIGHT` 的成因釘死了。** 官方把 weight test 拆成兩支
(`OFFICIAL_RULES.md:31`):「被賦權的股票太少」與「單一股票權重過高」。
現在有直接證據排除後者 ⇒ **是前者,而且沒有任何一個測過的槓桿能動它。**

## ⚠️ A/B 的證據基礎只有 10 格,不是 24 格 —— 別把結論說得比證據強

A/B 共 24 格,其中 **14 格根本沒跑起來**:

    status=WARNING msg=Incompatible unit for "group_backfill" ...

`group_backfill` 對輸入的單位有要求,而這些新聞欄位的單位中繼資料不一致
(settings 是 `unitHandling: "VERIFY"`)。失敗分佈跟形式無關、跟**欄位**有關。

⇒ **「`group_backfill` 解不掉 CONCENTRATED_WEIGHT」只有 10 個有效觀測支撐**,
而「truncation 解不掉」是 12/12 有效觀測 + bit-identical 的硬證據。**兩者強度不同。**

另有 1 格(`all_sessions_volume_weighted_avg_price|v_raw|B`)因為 worker 被連線中斷
殺掉而沒落帳 —— 那個 bug 已修(`545ed1ce`),但這一格沒補跑,因為
「≥12/24」的判定不會因為一格而翻盤。

## 已排除 / 沒有排除

### 已排除(不要再花額度)

| 假設 | 憑什麼 |
|---|---|
| `CONCENTRATED_WEIGHT` 是「單一股票權重過高」 | C 的 8 格 bit-identical + alpha_id 全不同 ⇒ 權重上限從未被觸發 |
| 調 `truncation` 能解 | 12/12 格沒解,且結果不變 |
| 只要提高覆蓋就能保住 Sharpe | `group_backfill` 有效的 4 格裡 3 格 Sharpe 崩掉(6.08→−0.22) |

### **沒有**排除

| 仍然未知 | 為什麼 |
|---|---|
| `group_backfill` 在**單位相容**的欄位上有沒有用 | 24 格裡 14 格因 `Incompatible unit` 沒跑起來 |
| 放寬 `unitHandling`(VERIFY → 其他)會怎樣 | 沒試。**但那是繞過檢查不是解決問題**,要先想清楚代價 |
| 其他提高覆蓋的做法(`vec_sum`、`ts_backfill` 更長窗、換分群) | 沒試 |
| `news12` 的 75 個 MATRIX 欄位、`news18` | 沒碰(見前一份報告) |

## 結論

事前寫下的停止條件被觸發了:**0 格解掉 ⇒ 新聞領域收工,不要再有第三批。**

我照這個規則停。**它是在看到結果之前寫的**,所以現在不改判準 ——
上面「沒有排除」那一欄裡確實有沒試過的東西(尤其單位相容那 14 格),
但那是**下一個人的起點,不是我現在繼續的理由**。
要不要投第三批由督導決定,而決定時手上該有的是這份表,不是我的直覺。
