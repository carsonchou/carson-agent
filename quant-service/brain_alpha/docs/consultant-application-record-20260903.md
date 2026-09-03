# WorldQuant BRAIN 戰績單 — 顧問申請填表用
**產出時間：2026-09-03 11:07 (台北) ／ 帳號 CT30034 (CHOU TING-RUI, TW)**

⚠️ **填表規則**：只有第 1 塊可以當成平台數字寫進表單。第 2 塊必須註明「自有紀錄」。
第 3 塊**不要填**。數字對不上的代價比少寫幾個數字大得多。

---

## 第 1 塊 — 平台查得到（可被 WorldQuant 自己驗證）

來源全部為 BRAIN API，抓取時間 **2026-09-03 11:07 台北**。

| 項目 | 值 | 端點 |
|---|---|---|
| 等級 | **GOLD** | `GET /users/self` → `level` |
| Genius Level | `null`（未達） | `GET /users/self` → `geniusLevel` |
| 帳號建立 | 2026-08-26 10:57 ET | `GET /users/self` → `dateCreated` |
| 已提交（ACTIVE）alpha | **13** | `GET /users/self/alphas?status=ACTIVE` → `count` |
| 平台上 alpha 總數 | **5,634** | `GET /users/self/alphas?limit=1` → `count` |
| 未提交 | 5,621 | `GET /users/self/alphas?status=UNSUBMITTED` → `count` |
| 被下架(DECOMMISSIONED) | **0** | `GET /users/self/alphas?status=DECOMMISSIONED` |
| IS_FAIL | **0** | `GET /users/self/alphas?status=IS_FAIL` |
| 提交日程 | 08-27:2, 08-28:3, 08-29:2, 08-30:2, 08-31:2, 09-01:2（ET） | `GET /users/self/activities/submissions` |

**⚠️「10,000 分」怎麼寫**：Challenge 分數**此刻查不到**
（`GET /competitions/challenge` → 404、`GET /users/self/competitions` → count=0，2026-09-03 現查）。
可以驗證的是 **`level = GOLD`**，而官方教材定義 GOLD = score > 10,000
（`GET /tutorial-pages/challenge-help`：*"Gold (score > 10,000)"*）。
→ **填「Gold level」而不是「10,000 points」**。前者現在查得到，後者查不到。

### 13 條已提交 alpha 的平台數字
（`GET /users/self/alphas?status=ACTIVE`，`is` 區塊；`grade` 為平台自評）

| alpha_id | sharpe | fitness | turnover | returns | drawdown | grade |
|---|---|---|---|---|---|---|
| wpjQpqJ6 | 2.40 | 1.45 | 25.37% | 9.27% | 2.85% | AVERAGE |
| LL7rbXY6 | 2.35 | 1.04 | 50.42% | 9.84% | 3.24% | AVERAGE |
| ZY7Opra3 | 2.26 | 1.63 | 17.25% | 8.95% | 3.33% | GOOD |
| 0mwrA8p8 | 2.25 | 1.34 | 24.15% | 8.62% | 3.52% | AVERAGE |
| 1YwZwMjX | 2.18 | 1.26 | 32.62% | 10.94% | 5.18% | AVERAGE |
| Vk7MPXmG | 2.03 | 1.46 | 14.72% | 7.60% | 4.65% | AVERAGE |
| xAjVdMLb | 1.95 | 1.51 | 15.79% | 9.52% | 3.39% | GOOD |
| N17E6wgg | 1.90 | 1.49 | 3.03% | 7.68% | 3.09% | AVERAGE |
| xAjl5o9N | 1.86 | 1.58 | 13.46% | 9.73% | 5.25% | GOOD |
| pwjv95Lj | 1.80 | 1.03 | 26.82% | 8.74% | 5.97% | AVERAGE |
| bljOoR6K | 1.70 | 1.05 | 6.00% | 4.77% | 3.98% | AVERAGE |
| 58lEzemn | 1.67 | 1.13 | 17.53% | 8.02% | 6.23% | AVERAGE |
| qMj3AjbZ | 1.65 | **2.03** | 2.39% | **18.85%** | 12.77% | **EXCELLENT** |

平台自評分佈：**EXCELLENT 1 / GOOD 3 / AVERAGE 9**。全部 13 條 `stage = OS`。
全部為 **USA / delay 1**，IS 期 2019-01-01 ~ 2023-12-31（`settings.startDate`/`endDate`）。
**universe 不是單一值**：TOP3000 **10** 條、TOP1000 **2** 條（`wpjQpqJ6`、`pwjv95Lj`）、TOP500 **1** 條（`58lEzemn`）。

### 平台里程碑（`GET /users/self/achievements`，`achieved` 為平台時戳）

| 成就 | 達成時間 (ET) | ratio |
|---|---|---|
| 20 Simulations | 2026-08-26 11:37 | 0.7574 |
| 100 Simulations | 2026-08-26 12:35 | 0.5480 |
| First Submission | 2026-08-27 01:20 | 0.7241 |
| Good Alpha | 2026-08-27 05:09 | 0.6727 |
| Excellent Alpha | 2026-08-29 18:47 | 0.5318 |
| **Spectacular Alpha** | 2026-08-30 04:14 | **0.4209** |
| 10 Submissions | 2026-08-31 09:16 | 0.3198 |

未達成（`achieved = null`）：SuperAlpha、First Consultant Submission、Complete Tutorial、
Complete Consultant Tutorial、Osmosis Pioneer、First Python Alpha Submission。
（`ratio` 欄位平台未附定義，**不要在表單上解釋成「贏過 X% 用戶」**。）

---

## 受邀條件 — 官方明文（現查，非推測）

**寫法：「符合官方公告的受邀條件」，不是「達標即獲資格」。**

**`GET /tutorial-pages/read-first-starter-pack`**（lastModified 2026-08-23，抓取 2026-09-03 11:1x 台北）逐字：

> "Users need to score **at least 10,000 points on the WorldQuant Challenge** to be eligible
> for this role. At present, we are offering this opportunity exclusively to residents of:
> Armenia, Mainland China, Hong Kong, **Taiwan**, Hungary, Kenya, Korea, Indonesia, India,
> Malaysia, Singapore, UK, Vietnam, Thailand, USA, Georgia, Nigeria"

`worldquantbrain.com/consultant`（公開網頁，2026-09-03 抓取）：

> "Once you hit 10,000 points on BRAIN and reach gold, you **may** receive an invitation
> to join the BRAIN Research Consultant Program."

**⚠️ 三件不要混淆的事：**
1. **「eligible」不等於「已受邀」。** 官方用字是 *may receive an invitation*。
   `GET /users/self/consultant` 現在回 **403**，站內信箱無任何邀請訊息（見第 3 塊）。
   表單上不要寫成「已獲邀」。
2. **10,000 分此刻查不到。** 可驗證的是 `level = GOLD`，而 GOLD 的官方定義是
   *"Gold (score > 10,000)"*（`GET /tutorial-pages/challenge-help`）。
   → 資格是靠 **GOLD** 這個現查得到的事實支撐，不是靠一個查不到的分數。
3. 居住地 **TW** 在名單上（`GET /users/self` → `address.country = "TW"`）。

---

## 第 2 塊 — 我們自己算的（**自有紀錄，非平台數字**）

來源檔案：`D:\carson-agent\quant-service\brain_alpha\auto_ledger.jsonl`，讀取時間 2026-09-03 11:10。
**填表時若要用，必須寫明「self-reported / own research log」。**

| 項目 | 值 | 怎麼算的 |
|---|---|---|
| 真正跑完並回傳結果的唯一 alpha | **5,437** | 帳本中不重複的 `alpha_id` |
| 除 self-correlation 外全部檢查通過 | **765**（14.1%） | `result.evaluable_pass` |
| 逐年 5 年全部達標 | **193**（3.5%） | `year_quality.all_years_pass` |
| 一階掃描涵蓋資料集 | **14 個**（平台 USA/delay=1 開放的全部） | 帳本 `F1|<dataset>|` 標籤去重 |
| 最高 IS Sharpe（含未提交） | **5.66** | 帳本 `result.sharpe` 最大值 |
| 真正的模擬錯誤 | 1,396 | 帳本無 `alpha_id` 且非 429 放棄 |

### 已提交 13 條的兩兩去相關程度（自有計算）

來源：`GET /alphas/{id}/correlations/self` 對 13 條各打一次，2026-09-03 11:2x 台北。

| 事實 | 值 |
|---|---|
| 相關度 **≥ 0.7** 的配對 | **0 對** |
| 平台列出的配對數 | **41 / 78**（其餘 37 對低於端點列示門檻，平台不回傳確切值）|
| 已列出配對中的最高相關 | **0.6680**（`xAjVdMLb` × `xAjl5o9N`）|
| 已列出配對中 ≥0.5 者 | 20 對 |

英文寫法（**必須保留 "as reported by" 這種措辭**，因為分母不是 78）：
> "No pair of the 13 submitted alphas exceeds 0.7 self-correlation; the highest pairwise
> correlation reported by the platform is 0.668 (41 of 78 pairs are returned; the remaining
> pairs fall below the endpoint's reporting threshold and are not disclosed)."

🔴 **不要寫「independent bets: N」。** 那個數字是貪婪演算法的產物，**換一個排序就變**
（依提交順序算 r<0.5 得 7/13）。它不是平台事實也不是穩定的統計量，寫進求職表單驗不了。
🔴 **不要寫「78 對中最高相關 X」。** 端點只回 41 對，78 對的最大值我們**沒有**。

🔴 **兩個絕對不要寫進表單的數字**：
- 帳本總列數 **28,198** —— 其中 **17,403 列是「無有效 Location」**，`brain_auto.py:526` 註解寫明
  那是「15 次 429 退避後放棄，**模擬從來沒送出去過**」。寫成「跑了 28,198 次模擬」是**假的**。
- 平台說 alpha 總數 5,634，我們帳本只有 5,437 —— **差 197 條**，來源未查明
  （可能是本帳本以外的工具產生）。**兩個數字不要混用**，要引用就引用平台那個。

---

## 第 3 塊 — 查不到，**不要填**

| 項目 | 為什麼拿不到 |
|---|---|
| **任何 OS（out-of-sample）表現** | 13 條全部 `stage=OS`、`os.startDate=2024-01-01`，但 `osISSharpeRatio` 與 `preCloseSharpeRatio` **皆為 null**，4 項 OS 檢查（IS_SHARPE / SELF_CORRELATION / SHARPE / OTHERS）**全部 PENDING**。最早的一條 08-27 才提交。**零 OS 結果。** |
| **prod correlation 明細** | `GET /alphas/{id}/correlations/prod` → **HTTP 403**（2026-09-03 現查）。純量欄位 `is.prodCorrelation` **查得到**：13 條全為 `0.0`，而未提交的 alpha 全為 `null`（代表平台在提交時確實寫入了值，不是佔位）。但明細不可查、13 條同值，**無法獨立佐證其意義，仍不填**。 |
| **Challenge 分數與名次** | `GET /competitions/challenge` → **404**；`GET /users/self/competitions` → count=0。榜自 2026-09-02 ET 00:20~03:15 之間起讀不到，至今未回。改用 `level=GOLD`。 |
| **Challenge 名次** | 我們自有紀錄最後一次讀到是 **rank 18061 / score 10000.0**（`score_history.jsonl`，2026-09-02 12:20 台北，透過 `GET /users/self/competitions`）。此後榜消失，**現在無法重新核對**。要寫只能寫成 *"as of 2026-09-02; no longer retrievable"*，**不可當成現況**。 |
| **顧問狀態 / 是否已受邀** | `GET /users/self/consultant` → **403**（端點存在但無權限）。站內信箱 8 則全是成就通知與產品公告，**沒有任何邀請訊息**。 |
| 「贏過多少用戶」「全球排名」 | 平台未提供可查端點。`achievements.ratio` 定義不明，不可當排名用。 |
| 收益 / 報酬金額 | 無任何端點提供。 |

---

## 中性英文摘要（供 Carson 自行取用）

⚠️ **我們沒有看過 Workday 表單，不知道它問什麼。** 以下不是對任何題目的答案，
只是一段每個數字都指得回來源的中性敘述。**不要拿它去套一個沒看過的題目。**

> Gold level on WorldQuant BRAIN (user CT30034). 13 alphas submitted and accepted since
> 2026-08-27, none decommissioned. Platform grades: 1 Excellent, 3 Good, 9 Average.
> Highest Sharpe among submitted: 2.40 (wpjQpqJ6). Highest fitness: 2.03 with 18.85%
> in-sample returns (qMj3AjbZ, graded Excellent). All figures are in-sample
> (USA, delay 1, 2019-2023; universes TOP3000 / TOP1000 / TOP500);
> out-of-sample results are not yet available.

🔴 **這段的三個地雷，改字時不要踩回去**：
1. **不要把不同 alpha 的數字併成一條。** Sharpe 最高的是 `wpjQpqJ6`(2.40)，
   fitness 2.03 與 returns 18.85% 是**另一條** `qMj3AjbZ`（它 Sharpe 只有 1.65）。
   併起來寫會變成一條不存在的 alpha。
2. **不要寫達到 Gold 的日期。** 平台的 achievements 裡**沒有** Gold 這一項，
   我們自己 `score_history.jsonl` 記到分數在 2026-09-01 觸及 10,000，
   但那是自有紀錄不是平台時戳 —— 屬第 2 塊，不可寫成平台事實。
4. **不要把 universe 寫成單一值。** 13 條橫跨 TOP3000(10) / TOP1000(2) / TOP500(1)，
   而句中點名的 `wpjQpqJ6` 正是 **TOP1000** 的那兩條之一。寫「All figures are USA TOP3000」
   同時又點名 wpjQpqJ6，對方登入一核對第一個就抓到這格。

3. **最後那句 out-of-sample 不可刪。** 13 條全部 OS PENDING，
   刪掉它整段就會被讀成「已驗證的實績」。
