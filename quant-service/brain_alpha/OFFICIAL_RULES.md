# BRAIN 官方教材萃取規則（OFFICIAL_RULES.md）

> 來源：`D:\carson-agent\quant-service\brain_alpha\TUTORIALS.md`（9 篇官方教材完整逐段讀畢，2026-08-27）。
> 原則：每條規則附教材原文引用；教材沒講的明寫「教材未提及」；表達式逐字照抄。
> ⚠️ 原始檔已知損壞處：`[alpha-submission]` 的提交門檻表格中，Turnover 那格內容被截斷、與 Self-Correlation 說明文字合併成一格；`[parameters-simulation-results]` 的 Fitness 評級表最後一列（Needs Improvement）內容被截斷。以下引用只用倖存的原文。

---

## 1. 提交檢查項目：官方定義與通過建議

### 1.1 門檻總表（[alpha-submission] Submission Tests for Alphas）

原文表格（倖存部分）：
- Fitness: "At least "Average": Greater than 1.3 for Delay-0 or Greater than 1 for Delay-1"
- Sharpe: "Greater than 2 for Delay-0 Alphas or Greater than 1.25 for Delay-1 Alphas"
- Turnover: 表格此格已損壞，僅剩開頭 "1%"。另一篇 [intermediate-pack-part-1] 有完整句："The passing requirement for turnover on BRAIN is to be between 1% and 70%."

檢查執行順序（[alpha-submission] Interpreting Status Messages）——**測試按序執行，先掛哪個就報哪個**：

| 序 | 測試 | 失敗訊息（原文） |
|---|---|---|
| 1 | Weight test | "Maximum weight on an instrument is greater than 10% OR Weight is too strongly concentrated or too few instruments are assigned weight." |
| 2 | Correlation test | "Reduce max correlation" |
| 3 | Fitness test | "Improve fitness" |
| 4 | Delay 0 Alpha fails checkDelay1Sharpe | "Alpha better suited for Delay 1" |
| 5 | SubUniverse test | "Improve Sharpe in SubUniverse" |

### 1.2 Weight test（= 你的 CONCENTRATED_WEIGHT）

官方定義（[alpha-submission] Weight 節，原文）：
> "Alphas can fail this test if: Too few stocks are assigned weight for significant number of days in a year. ... The exact number of minimum stocks varies with the simulation universe. Alpha weight is too concentrated in any one stock. For example, if one stock has 30 percent of all Alpha weight, it will fail this test."

補充：模擬一開始全零權重不算失敗（原文："assigning zero weights to all stocks at the start of the simulation does not fail this condition, it only applies after the Alpha starts assigning weights."）。單一 instrument 上限是 10%（見上表失敗訊息）。

**官方給的修法**（[intermediate-pack-part-1] Passing IS Stage and Troubleshooting，原文）：
> "Common fixes to this include: Adding range-normalized functions such as rank, setting truncation at 0.1, and using ts_backfill."

→ 可直接行動：你鎖死的 `truncation=0.05` 官方明講可以放到 **0.1**；外層包 `rank()`；低覆蓋欄位用 `ts_backfill`。

### 1.3 Self-Correlation

官方講到的全部內容（[alpha-submission]，原文，出現在損壞表格的倖存文字中）：
> "Alphas can also qualify if their Sharpe is greater, by 10% or more, than that of all Alphas with which their correlation is higher than the cutoff. For example, if your earlier submitted Alpha X has a Sharpe of 3.18, you can submit a highly correlated Alpha Y, if its Sharpe is 3.5 or more. This allows for making improvements to an existing Alpha. The Sharpe value used for this comparison (3.18) is visible in the correlation summary table in the simulation results. Self correlation operates on a four-year window whereas the inner correlation operates on the intersect of the selected Alpha's PnL time periods."

要點：
1. **逃生門**：與已提交 alpha 高度相關仍可提交，條件是 Sharpe 比所有相關 alpha 高 ≥10%。
2. Self correlation 用**四年窗口**計算。
3. 具體 correlation cutoff 數值：**教材未提及**（表格損壞處可能原本有）。
4. 怎麼避開：官方策略建議（[alpha-submission] Selecting Alphas For Submission，原文）：
> "It is generally better to try out new ideas with low correlation to previous ones than to improve performance of Alphas with high correlation. Generally, low correlation is more important than minor increase in performance."

以及同節：
> "Do not submit Alphas as soon they clear the performance cutoff. Improve the idea until you have the best version: in terms of both performance and correlation."

（`SELF_CORRELATION` 提交前顯示 PENDING 的現象：教材未提及。）

### 1.4 Sub-Universe test（= 你的 LOW_SUB_UNIVERSE_SHARPE）

官方門檻公式（[alpha-submission]，原文）：
> "The threshold to pass the sub-universe test is defined by the formula: subuniverse_sharpe = 0.75 * sqrt(subuniverse_size / alpha_universe_size) * alpha_sharpe"

TOP3000 的 sub-universe 是 TOP1000（原文："if you are trying to submit an Alpha on USA TOP3000, the platform will also check its performance on USA TOP1000."）。代入即 cutoff = 0.75 × sqrt(1000/3000) × alpha_sharpe ≈ **0.433 × 你的 Sharpe**（此代入為本文件計算，公式本身是原文）。教材例：0.75 × sqrt(1000/3000) × 2.73 = 1.18。

Sub-universe Sharpe 的計算方式（原文）：
> "Pasteurize to the target universe, that is, for all stocks not in the sub-universe, assign value of NaN. Apply market neutralization to resulting set (subtract mean of all values from each value) and then scale Alpha back to original size. Calculate PnL using resulting Alpha values"

**官方通過建議**（[alpha-submission] Tips，原文重點逐條）：
1. > "Avoid using multipliers related to the size of the company in your Alphas, e.g. rank(-assets), 1 – rank(cap), etc."
2. 液性分段 decay（表達式逐字照抄）：
> "instead of "ts_decay_linear(signal, 10)" you can try "ts_decay_linear(signal, 5) * rank(volume*close) + ts_decay_linear(signal, 10) * (1 – rank(volume*close))""
3. > "Check out your Alpha improvements step by step, maybe one of them resulted in better stats, but at the same time Alpha started to fail sub-universe test?"
4. [intermediate-pack-part-1]：> "you can try to improve the Sub-Universe Sharpe by increasing the Universe of instruments (i.e. selecting Top3000)."（你已在 TOP3000。）
5. 放手建議（原文）：> "If nothing helps - don't get upset. Some signals are just not robust. ... Most likely, you just dodged a bad Alpha."

### 1.5 其他測試

- **IS Ladder Sharpe test / 2Y Sharpe test**：僅在 ATOM Alphas 節被點名（原文："ATOM Alphas can skip the IS Ladder Sharpe test. ATOM Alphas must pass regular IS tests and the 2Y Sharpe test."），兩者的定義與門檻**教材未提及**。
- GLB alpha 要三地理區各 Sharpe ≥1、ASI 要 Japan Sharpe ≥1 —— 只影響 GLB/ASI 區域，USA 不適用。

---

## 2. Sharpe 與 fitness 如何同時拉高（蹺蹺板問題）

### 2.1 教材有沒有直接回答？

**沒有直接的「同時達標」配方。** 最接近的兩段原文：

[parameters-simulation-results] Fitness 節：
> "Good Alphas have high fitness. You can optimize the performance of your Alphas by increasing Sharpe (or returns) and reducing turnover. Improving one factor normally has an adverse impact on the other factor. As you work on optimizing your Alpha, an improvement in its fitness is an indication that your changes are having a positive impact."

——官方自己承認蹺蹺板存在（"Improving one factor normally has an adverse impact on the other factor"），給的方針是**以 fitness 本身當單一優化指標**。

[intermediate-pack-part-1]：
> "Good Alphas generally have high fitness. You can seek to improve the performance of your Alphas by increasing Sharpe (or returns) and reducing turnover."

### 2.2 教材裡與蹺蹺板相關的槓桿（每條都有出處）

1. **公式本體**（兩篇皆有，原文 LaTeX）："Fitness = Sharpe * sqrt(abs(Returns) / max(Turnover, 0.125))"
   - ⚠️ 推論（非原文，但直接由原文公式導出）：分母有 `max(Turnover, 0.125)` —— turnover 壓到 12.5% 以下對 fitness **零增益**；你的 fitness 缺口只能靠 Sharpe 或 |Returns| 補。若你 Sharpe 1.46 / fitness 0.90，代表 sqrt(|Returns|/max(TO,0.125)) ≈ 0.62，即 |Returns| 太小或 turnover 太高——先看是哪一個。
2. **Decay 降 turnover**（[simulation-settings] 原文）："Decay can be used to reduce turnover, but decay values that are too large will attenuate the signal."
3. **Decay 的機制**（[how-brain-platform-works] 原文）："even if decay is used, more weight is assigned to the most recent values. So decay is an important factor in reducing transaction costs or turnover, as it includes information from previous days, preventing the Alpha from being reactive."
4. **提高 Sharpe 的官方兩路**（[intermediate-pack-part-1] 原文）："How do you get a higher Sharpe? We suggest that you can either increase you Alpha return or reduce your volatility."
5. **Returns 的定義**（多篇）："Annual Return = Annualized PnL / Half of Book Size"；Margin = PnL / total dollars traded。
6. **Rank 壓極值降波動**（[intermediate-pack-part-2] 原文）："The rank operator helps to limit the extreme values of that ratio."（rank 前單一股票佔 80% 資金、rank 後最大 40% 的例子。）
7. **換資料換設定**（[intermediate-pack-part-2] 原文）："you can try out different data fields. We recommend exploring the price volume dataset, model dataset and fundamental dataset. Lastly, you can tinker with different simulation settings."

### 2.3 Fitness 評級表（[parameters-simulation-results]，原文表格，部分損壞）

| Label | Fitness for Delay 1 | Fitness for Delay 0 |
|---|---|---|
| Spectacular | > 2.5 | > 3.25 |
| Excellent | > 2 | > 2.6 |
| Good | > 1.5 | > 1.95 |
| Average | > 1 | > 1.3 |
| Needs Improvement | （原始檔此列截斷） | |

---

## 3. 模擬設定：官方說法與建議值

| 設定 | 官方說法（引原文關鍵句） | 建議值 |
|---|---|---|
| **Delay** | "delay is the assumption of when we can trade stock once we decide on a position... In expression language, delay is applied automatically and you do not have to bother about it." | D1 門檻較低（Sharpe 1.25 vs 2、fitness 1 vs 1.3） |
| **Decay** | "This performs a linear decay function over the past n days... Decay can be used to reduce turnover, but decay values that are too large will attenuate the signal." 合法值："Integer 'n'"；"Using negative or non-integer values for Decay will break simulations." | 教材未給具體數字；官方範例用 0、3、4 |
| **Truncation** | "The maximum weight for each stock in the overall portfolio. When it is set to 0, there is no restriction." | **"The recommended setting is between 0.05 and 0.1 (entailing 5-10%)"**（兩篇教材都寫）；weight test 修法明講 "setting truncation at 0.1" |
| **Neutralization** | "When Neutralization = "Market" it does the following operation: Alpha = Alpha – mean(Alpha)... When Neutralization = Industry or Subindustry, all the instruments in the Alpha vector are grouped into smaller buckets... and neutralization is applied separately to each of the buckets." | "The correct choice of neutralization depends on the logic or formula used by the Alpha. The results should indicate which neutralization will be most effective."（官方要你實驗，無單一建議值） |
| **Universe** | "Universe is a set of trading instruments ranked by their liquidity"（依 average daily dollar volume） | 為過 sub-universe test，官方建議 "increasing the Universe of instruments (i.e. selecting Top3000)" |
| **Pasteurize** | "Pasteurization replaces input values with NaN (pasteurizes) for instruments not in the Alpha universe... The default Pasteurize setting is 'On'. Researchers can switch it to 'Off' and use pasteurize(x) operator for manual pasteurization." | 預設 On；"it may be more appropriate when considering cross-sectional or group operations" |
| **NanHandling** | On："For time series operators, if all inputs are NaN, 0 is returned. For group operators returning one value per group..., the value for the group is returned." Off："NaNs are preserved... Researchers should handle NaNs manually." 預設 Off。警告："NaNHandling = 'On' increases coverage, but may introduce ambiguous information into the Alpha."（ts_zscore 回 0 分不清是無資料還是等於均值） | 預設 Off；手動處理範例（逐字）：`is_nan(ts_zscore(etz_eps, 252)) ? ts_zscore(est_eps, 252) : ts_zscore(etz_eps, 252)` |
| **Unit Handling** | "Unit warnings are provided for reference in simple cases and **do not prevent submission**... You can safely ignore these warnings if you're sure the Alpha correctly handles data units." | ⚠️ 你踩過的 `Incompatible unit` 官方明講**只是警告、不擋提交** |

其他事實：Book size 恆定 $20M，"Performance (like Returns, Sharpe) is computed on a base of $10 million"；IS 期間 "The rolling 5-year In-Sample simulation period begins seven years ago and ends two years ago"；最近兩年是 Semi-OS 隱藏。官方防過擬合建議（[parameters-simulation-results]）："you can divide your In-Sample (IS) period into a Train and Test period... An Alpha developed based on the simulation results of training period and performs well in both periods is likely a strong candidate for submission and may have avoided overfitting."

---

## 4. 官方 Alpha 範例（表達式逐字照抄）

⚠️ 檔案中「19-alpha-examples」章節**實際只收錄 5 個範例**（教材檔可能只抓到部分）。全檔 10 個 SIMULATION_EXAMPLE 如下。

### 4.1 [19-alpha-examples] 的 5 個範例

| # | 名稱 | 表達式（逐字） | 設定重點 |
|---|---|---|---|
| 1 | Operating Earnings Yield | `ts_rank(operating_income,252)` | SUBINDUSTRY / trunc 0.08 / decay 0 |
| 2 | Appreciation of liabilities | `-ts_rank(fn_liab_fair_val_l1_a,252)` | SUBINDUSTRY / trunc 0.08 / decay 0 |
| 3 | Power of leverage | `liabilities/assets` | MARKET / trunc 0.01 / decay 0 |
| 4 | Earnings Yield Momentum | `group_rank(ts_rank(est_eps/close, 60),industry)` | INDUSTRY / trunc 0.08 / decay 0 |
| 5 | Short-Term Sentiment Volume Stability | `-ts_std_dev(scl12_buzz, 10)` | INDUSTRY / trunc 0.08 / decay 0 |

各範例官方 hypothesis / hint（摘錄原文）：
1. "If the operating income of a company is currently higher than its past 1 year history, buy the company's stock and vice-versa." Hint: "Rather than comparing the value directly, can calculating a ratio that includes stock market moves, improve the signal?"
2. "An increase in the fair value of liabilities could indicate a higher cost than expected." Hint: "Could observing the increase over a shorter period improve accuracy?"
3. "Companies with high liability-to-asset ratios – excluding those with poor financial health or weak cashflows – often leverage debt as a strategic tool..." Hint: "This ratio can vary significantly across industries. Would it be worth considering alternative neutralization settings?"
4. "Stocks whose earnings yield has been high more often over the last quarter, relative to their own history, may be undervalued thus we should long them." Hint: "Use NAN HANDLING to preprocess data and boost the performance"
5. "A high 10-day standard deviation of sentiment volume for a stock means that investor attention is unstable... causing the stock to underperform afterward." Hint: "Would observing stability over a shorter horizon be more effective for more liquid stocks?"

### 4.2 其他章節的 5 個範例（逐字）

| 出處 | 表達式 | 用途 |
|---|---|---|
| [simulation-settings] Pasteurize | `group_rank(pasteurize(sales_growth),sector) - group_rank(sales_growth,sector)` | 示範手動 pasteurize |
| [simulation-settings] NanHandling | `ts_zscore(etz_eps, 252)` | 示範 NaN 行為 |
| [simulation-settings] NanHandling | `groupmax(sales, industry)` | 示範 group operator 的 NaN 行為 |
| [read-first-starter-pack] | `volume` | 技術分析示例 |
| [read-first-starter-pack] | `inventory_turnover` | 基本面示例（"Inventory Turnover = Sales / Average Inventory"） |

另外散見文中的表達式（逐字）：`rank(-returns)`（how-brain-platform-works 的完整教學例，reversion idea）、`rank(sales/assets)`、`close/open`、`ts_decay_linear(signal, 5) * rank(volume*close) + ts_decay_linear(signal, 10) * (1 – rank(volume*close))`。

---

## 5. 教材提到、你可能沒用過的運算子與資料集

**運算子**（教材點名，含用法出處）：
- `ts_rank`、`ts_delta`（intermediate-pack-part-2，有專節）
- `group_rank`、`groupmax`、`groupmedian`、`groupcount`（group 系列）
- `ts_zscore`、`ts_std_dev`、`ts_median`、`ts_decay_linear`
- `pasteurize(x)`（手動 pasteurization）
- `is_nan(...) ? ... : ...`（三元條件處理 NaN）
- **backfill 系列**（[data] 原文）："Low coverage fields can be handled by making use of backfill operators like ts_backfill, kth element, group_backfill, etc."
- `inst_pnl`（注意："Using the inst_pnl operator will be counted as using the pv1 dataset."）
- `rank`（壓極值、修 weight test）

**資料集**（教材點名）：
- [intermediate-pack-part-2] 原文："We recommend exploring the price volume dataset, **model dataset** and **fundamental dataset**."
- 範例中出現的非 pv1 欄位：`operating_income`、`liabilities`、`assets`、`sales`、`sales_growth`、`inventory_turnover`（fundamental）；`est_eps`、`etz_eps`（estimate/分析師）；`fn_liab_fair_val_l1_a`（fundamental 細項）；`scl12_buzz`（sentiment/social）；`cap`。
- Consultant 才有的 Dataset Value Score："signifies underutilization of a dataset. Consultants are advised to research and make Alphas using datasets with a higher value score."（你現在還看不到，但方向 = 用冷門資料集。）

**探索新資料欄位的 6 招**（[data]，原文表格，設定 None neutralization + decay 0，看 Long/Short Count）：
1. `datafield` → 覆蓋率 ≈ (Long+Short Count)/Universe Size
2. `datafield != 0 ? 1 : 0` → 每日非零覆蓋
3. `ts_std_dev(datafield,N) != 0 ? 1 : 0` → 資料更新頻率（N=66 季、22 月、5 週）
4. `abs(datafield) > X` → 值域邊界（X=1 測是否已標準化到 ±1）
5. `ts_median(datafield, 1000) > X` → 5 年中位數
6. 比較式如 `close = 0` → 驗證資料性質（Long/Short Count 為 0 表示恆正）

---

## 6. 「不要這樣做」警告清單（全部有原文）

1. **別用公司規模乘數**："Avoid using multipliers related to the size of the company in your Alphas, e.g. rank(-assets), 1 – rank(cap), etc."（sub-universe test 殺手）
2. **Decay 別給負數/非整數**："Using negative or non-integer values for Decay will break simulations."
3. **Decay 別太大**："decay values that are too large will attenuate the signal."
4. **Truncation 別超出 [0,1]**："Any values for Truncation outside this range can impact/break simulations."
5. **別一達標就提交**："Do not submit Alphas as soon they clear the performance cutoff."
6. **也別死磕單一 idea**："do not spend extraordinary amount of time improving a single idea either: It is generally better to try out new ideas with low correlation to previous ones..."
7. **NanHandling On 有代價**："NaNHandling = 'On' increases coverage, but may introduce ambiguous information into the Alpha."
8. **高波動 PnL 即使報酬高也不行**："If the graph shows high fluctuations/volatility, despite the returns being high, the Alpha will not be deemed good enough."
9. **Power Pool tag 是單向門**："Once you tag an Alpha as power pool, it stays in the self-correlation pool even if you untag it later."
10. **失敗的 sub-universe alpha 別硬救**："Some signals are just not robust... Most likely, you just dodged a bad Alpha."

---

## 7. 特殊 Alpha 類型（可降低門檻的通道）

- **ATOM Alphas**（單一資料集 alpha）："ATOM Alphas are Alphas that use fields from only 1 dataset. The following grouping fields are excluded when counting datasets: currency, country, exchange, sector, industry, subindustry, market... ATOM Alphas can skip the IS Ladder Sharpe test."
- **Pyramid Alphas**："Pyramids are defined as a combination of region, delay, and dataset category... Pyramid Alphas are Alphas that contribute to a maximum of 2 pyramids."（獎勵機制細節教材未提及。）
- **Power Pool Alphas** 準則（原文，注意原始檔的比較符號疑似被轉成 =）："Sharpe = 1.0, Number of unique operators = 8, Number of unique data fields (excluding grouping fields) = 3, ... Self-Correlation of just your Power Pool Alphas = 0.5 ... Turnover should be between 1%-70% (both inclusive), USA Delay 1"——即 Power Pool 通道的 Sharpe 門檻遠低於 1.25，且 self-correlation 只跟**自己的 Power Pool alphas** 比。

---

## 8. 教材未提及清單（別跟官方說法混淆）

- `LOW_SHARPE` / `LOW_FITNESS` / `HIGH_TURNOVER` 這些 API 檢查碼名稱（教材用文字描述，無代碼）
- Self-correlation 的具體 cutoff 數值
- SELF_CORRELATION 顯示 PENDING 的機制
- `frac` 保留字問題
- IS Ladder Sharpe test 與 2Y Sharpe test 的定義與門檻
- 積分（10,000 分）怎麼算、每條 alpha 給幾分
- Weight test「最少幾檔股票」的確切數字（原文明說 "varies with the simulation universe"）
- decay 的最佳數值區間（只給了方向性 tip）
