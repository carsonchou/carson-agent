# 達標 Alpha 清單（**依獨立 base 去重**）

> 自動產生。帳本 1596 條，成功模擬 1089 條。
> 門檻：`Sharpe>=1.25`、`fitness>=1.0`、`turnover 0.01~0.7`、`sub-universe sharpe`（相對值）、`concentrated weight`、`self-correlation<0.7`。

> 🔴 **同一個資料欄位只列一條。** 2026-08-28 實測：同 base 換外層變換的兩條，self-correlation **0.9653**，第二條被擋。決定能不能同時提交的是**底層欄位**，不是分數。
> 排序依「最後一年 Sharpe」——官方分數會每週依樣本外表現更新，近年撐得住才會持續加分。

## 🟢 可提交（全部 checks 通過） — 0 條

_到平台 Alphas → Unsubmitted → Submit Alpha_

（無）

## 🟡 待確認（SELF_CORRELATION 尚未評估） — 7 條

_先按 Check Submission，全綠才提交_

### `operating_income/cap`　— S2A|operating_cap|golden

```
group_rank(ts_rank(winsorize(ts_backfill(operating_income/cap, 120), std=4), 126), subindustry)
```

- Sharpe **2.4** / Fitness **1.45** / Turnover 25.4%
- **最後一年 Sharpe：1.81**（最差年 1.81）
- alpha id：`wpjQpqJ6`
- 同 base 的變體共 2 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `operating_income/close`　— S2A|operating_close|golden

```
group_rank(ts_rank(winsorize(ts_backfill(operating_income/close, 120), std=4), 126), subindustry)
```

- Sharpe **2.3** / Fitness **1.37** / Turnover 25.5%
- **最後一年 Sharpe：1.78**（最差年 1.78）
- alpha id：`0mwYm9VG`
- 同 base 的變體共 3 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `cashflow_op/close`　— S2A|cashflow__close|golden

```
group_rank(ts_rank(winsorize(ts_backfill(cashflow_op/close, 120), std=4), 126), subindustry)
```

- Sharpe **1.8** / Fitness **1.03** / Turnover 26.8%
- **最後一年 Sharpe：1.74**（最差年 1.22）
- alpha id：`pwjv95Lj`
- 同 base 的變體共 2 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `cashflow_op/cap`　— S2A|cashflow__cap|golden

```
group_rank(ts_rank(winsorize(ts_backfill(cashflow_op/cap, 120), std=4), 126), subindustry)
```

- Sharpe **1.81** / Fitness **1.03** / Turnover 26.7%
- **最後一年 Sharpe：1.53**（最差年 1.24）
- alpha id：`pwjv9o1g`
- 同 base 的變體共 1 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `operating_income/equity`　— S2|opinc|golden|TOP3000|t0.1|IND

```
group_rank(ts_rank(winsorize(ts_backfill(operating_income/equity, 120), std=4), 126), subindustry)
```

- Sharpe **1.74** / Fitness **1.1** / Turnover 6.0%
- **最後一年 Sharpe：1.34**（最差年 -0.45）
- alpha id：`vRj128Gz`
- 同 base 的變體共 8 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `est_eps/close`　— S2|esteps|spow|TOP3000|t0.1|IND

```
group_rank(signed_power(ts_zscore(winsorize(ts_backfill(est_eps/close, 120), std=4), 63), 0.5), subindustry)
```

- Sharpe **2.37** / Fitness **1.48** / Turnover 23.4%
- **最後一年 Sharpe：0.81**（最差年 0.81）
- alpha id：`2rljYkR5`
- 同 base 的變體共 44 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

### `operating_income`　— CMB|lin0.5|opinc

```
0.5 * rank(-ts_delta(close, 3)) + 0.5 * rank(ts_rank(ts_backfill(operating_income, 120), 252))
```

- Sharpe **2.18** / Fitness **1.26** / Turnover 32.6%
- **最後一年 Sharpe：?**（最差年 ?）
- alpha id：`1YwZwMjX`
- 同 base 的變體共 4 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：無　未評估：SELF_CORRELATION

## 🔵 雙門檻已過、卡其他檢查 — 3 條

_離終點最近，優先改這幾條_

### `stock_option_exercise_proceeds`　— F1|fundamental2|stock_option_exercise_proceeds

```
group_rank(ts_rank(winsorize(ts_backfill(stock_option_exercise_proceeds, 120), std=4), 126), subindustry)
```

- Sharpe **1.67** / Fitness **1.03** / Turnover 1.8%
- **最後一年 Sharpe：0.97**（最差年 -0.67）
- alpha id：`LL75eZXv`
- 同 base 的變體共 1 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：LOW_SUB_UNIVERSE_SHARPE　未評估：SELF_CORRELATION

### `vested_expected_option_awards_avg_exercise_price`　— F1|fundamental2|vested_expected_option_awards_avg_exercise_price

```
group_rank(ts_rank(winsorize(ts_backfill(vested_expected_option_awards_avg_exercise_price, 120), std=4), 126), subindustry)
```

- Sharpe **1.69** / Fitness **1.07** / Turnover 1.4%
- **最後一年 Sharpe：-0.24**（最差年 -0.24）
- alpha id：`LL75oJl6`
- 同 base 的變體共 1 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：LOW_SUB_UNIVERSE_SHARPE　未評估：SELF_CORRELATION

### `scl12_buzz`　— OFF|scl12_buzz|std10n

```
-ts_std_dev(ts_backfill(scl12_buzz, 120), 10)
```

- Sharpe **1.52** / Fitness **1.26** / Turnover 22.3%
- **最後一年 Sharpe：?**（最差年 ?）
- alpha id：`0mwXzvw8`
- 同 base 的變體共 1 條（**只能交這一條**，其餘會撞 self-correlation）
- 未過：CONCENTRATED_WEIGHT, LOW_SUB_UNIVERSE_SHARPE　未評估：SELF_CORRELATION
