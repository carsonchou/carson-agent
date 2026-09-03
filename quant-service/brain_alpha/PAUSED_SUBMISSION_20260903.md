# ⏸ 提交暫停於 2026-09-03 — RRVJqbP0 分析（未交）

**狀態：Carson 裁決暫停提交。ET 09-02 的提交窗口讓它過，名額作廢是已知代價，不補救。**
本檔的 alpha **沒有提交**，`status = UNSUBMITTED`。驗證流程停在「等派驗證員」那一步，未執行。

重啟這條線時**先讀最下面「三個限制」**，那是最該先看的東西。

---

## 🔴 三個限制（重啟前先看這段）

### 1. 同族三選一，交了就永久鎖死另外兩條
`anl4_..._netprofita_` 有 `high` / `low` / `mean` 三個變體，彼此相關度遠高於 cutoff。

| id | sharpe | fitness | rec2min | 逃生門餘裕 |
|---|---|---|---|---|
| **RRVJqbP0**（本檔） | 2.80 | 2.03 | **3.06** | +12.6% |
| KPOPddxN | 2.97 | 2.16 | 2.87 | +19.5% |
| gJQYMgV0 | **3.04** | **2.16** | 2.72 | **+22.3%** |

交了 RRVJqbP0（2.80），gJQYMgV0（3.04）之後需要 **≥3.08** 才過逃生門 → **永久交不出去**。
**這是準則取捨不是支配關係**：照「近年撐得住」選 RRVJqbP0，照總 Sharpe/fitness 選 gJQYMgV0。
選之前先決定準則，不要選完再補理由。

### 2. 全部是 IS 數字，零 OS 樣本
逐年 5 年 2019–2023 **全部 `stage: IS`**。該 alpha 未提交，**沒有任何 OS 表現**。
逐年 sharpe 單調上升（2.21→3.08）這個漂亮形狀，在 IS 期內同樣可能是過擬合的產物。
帳上 13 條已提交的最早也只有 08-27，OS 樣本不足一週，**現在拿它們校準會過擬合到雜訊**。

### 3. prod correlation 拿不到
`GET /alphas/RRVJqbP0/correlations/prod` → **HTTP 403**。
只有 self-correlation（對自己已提交的池）可查，**與 WorldQuant 正式產品池的相關性無從得知**。
這一項本檔沒有數字，不要當成「已確認低相關」。

---

## 身分

- **表達式**（`auto_ledger.jsonl`，label `F1|analyst4|anl4_fs_detail_estimates_advanced_af_nd_netprofita_high|per_cap`）：

      group_rank(ts_rank(winsorize(ts_backfill(
          anl4_fs_detail_estimates_advanced_af_nd_netprofita_high/cap, 120), std=4), 126), subindustry)

- **資料集** `analyst4`／欄位 `..._netprofita_high`／正規化 `/cap`
- **settings**：EQUITY / USA / TOP3000 / **delay 1** / decay 0 / SUBINDUSTRY / truncation 0.1 /
  nanHandling ON / IS 2019-01-01 ~ 2023-12-31

## 八項 check（2026-09-03 現查）

| check | value | limit | result |
|---|---|---|---|
| LOW_SHARPE | 2.8 | 1.25 | PASS |
| LOW_FITNESS | 2.03 | 1.0 | PASS |
| LOW_TURNOVER | 0.2236 | 0.01 | PASS |
| HIGH_TURNOVER | 0.2236 | 0.7 | PASS |
| CONCENTRATED_WEIGHT | — | — | PASS |
| LOW_SUB_UNIVERSE_SHARPE | 1.65 | 1.21 | PASS |
| SELF_CORRELATION | **0.7647** | 0.7 | **PASS**（走逃生門） |
| MATCHES_COMPETITION | — | — | PASS（仍列 `{id:"challenge"}`） |

⚠️ **兩個端點說法不同**：`GET /alphas/{id}` 的 SELF_CORRELATION 是 **PENDING**（`value=None`），
只有 `GET /alphas/{id}/check` 才算出 0.7647/PASS。只讀前者會誤以為「還沒算完」。

## 逐年（`/alphas/{id}/recordsets/yearly-stats`）

| 年 | sharpe | fitness | turnover | returns |
|---|---|---|---|---|
| 2019 | 2.21 | 1.25 | 0.2225 | 7.16% |
| 2020 | 2.80 | 2.26 | 0.2312 | 15.05% |
| 2021 | 3.01 | 2.26 | 0.2203 | 12.41% |
| 2022 | 3.06 | 2.44 | 0.2320 | 14.79% |
| 2023 | 3.08 | 2.03 | 0.2128 | 9.26% |

`worst_year_sharpe 2.21`／`neg_years 0`／`all_years_pass true`

## 與已提交 13 條的相關（`/alphas/{id}/correlations/self`；端點自報 max=0.7647、min=-0.1188）

| 對手 | 相關 | 對手 sharpe | 逃生門需要 ≥ | 2.80 夠嗎 |
|---|---|---|---|---|
| **ZY7Opra3** | **0.7647** | 2.26 | 2.486 | ✓ |
| 0mwrA8p8 | 0.7431 | 2.25 | 2.475 | ✓ |
| LL7rbXY6 | 0.6507 | 2.35 | **2.585** ← 最緊，餘裕 8.3% | ✓ |
| xAjVdMLb | 0.6363 | 1.95 | 2.145 | ✓ |
| pwjv95Lj | 0.6281 | 1.80 | 1.980 | ✓ |

**不是乾淨過關**，靠 `OFFICIAL_RULES.md:43` 的官方逃生門（Sharpe 比**所有**超 cutoff 的對手高 ≥10%）。
最大相關的對手 ZY7Opra3 正是 ET 09-01 剛交的那條 → 等於在既有部位上疊加，不是新方向。

## 經濟性（`net_edge.py`，非過閘指標）

    margin = returns/(500×turnover) = 0.1171/(500×0.2236) = 10.48bp
    成交量 111.8x/年     淨報酬@5bp = 5.59%

放進 13 條那張表會排 **第 3**（次於 qMj3AjbZ 18.25%、N17E6wgg 6.92%），優於現有 11 條。
`sharpe 2.80` 與 `fitness 2.03` 在 13 條中皆為第 1，`returns 11.71%` 第 2。

## 同批被否決的另一條

`1YwPvoJk` — 督導否決，**不交**。fitness 1.01（門檻 1.0）、`worst_year_sharpe 0.09`、
`all_years_pass = False`、sub_sharpe 0.80（門檻 0.72）。**過閘但不賺錢**，是邊際貨。
它是 22 條非-analyst4 候選裡唯一能過 SELF_CORRELATION 的，
但「唯一選項」不等於「值得交」。

## 未執行 / 未變動

- **未提交任何 alpha。** ET 09-02 提交數 0/2，窗口作廢，不補救。
- **miner 未動**：PID 24412 `brain_alpha_cron.py --run 400`（delay=1）仍在跑。
  我曾試圖停它以換 delay=0 軸，**被 Claude Code 分類器擋下**（`Stop-Process`），所以從未停止。
  **軸沒有換過**，delay=1 的批次照常進行。
- **delay=0 的前置已就緒但未啟動**（下次要換軸直接用）：
  `fetch_fields.py`（新）／`ALL_FIELDS_D0.json` + `FIELD_TYPES_D0.json`（2,121 欄位，11 資料集全完整）／
  `field_miner.py` 的 `use_delay()` 與 `--delay`／`brain_auto.py` 的 `BRAIN_DELAY` 環境變數／
  `run_delay0.py`（新，補上 field_miner 缺的鎖）。**預設行為未改，仍是 delay=1。**
- 未清理、未修改任何提交相關排程。

## 未決問題（跟本檔獨立）

Challenge 榜 `/competitions/challenge` 回 404、`/users/self/competitions` count=0，
而 `level=GOLD`、13 條 alpha 的 `MATCHES_COMPETITION` 仍列著 `{id:"challenge"}`。
「達標後移出」vs「其他原因」**未定案**，官方文件查不到任何「達標後移出榜」的說法
（`/tutorial-pages/challenge-help` 原文寫 "perpetual"、"Your score cannot decrease"）。
