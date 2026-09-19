# w1:p1 收線盤點 —— 落盤清單與「下一棒不要重走」

> 對應 `docs/ops/2026-09-10_brain_line_shutdown_handoff.md`(wF:p4 那份)。
> 判準照 memory `only-what-lands-on-disk-exists`:**這件事現在有沒有一個檔案指得出來。**
> 提交仍照 Carson 09-03 停著,本次零提交動作、零模擬。

## 盤點結果:找到 **3 件**沒落盤的,已全部補上

### ① `2026-09-09_delay0_axis_verdict.md` **漏了「已排除/沒有排除」段**

今晚三個負結果裡**唯一漏寫這段的**。已補(4 條已排除 / 3 條沒有排除)。
督導問的第 ① 題答案是:**現在三份都有了,補完之前是 2/3。**

### ② `2026-09-09_news12_template_result.md` 有一句**過時到會誤導下一棒**的話

原文寫:那 1 格因 worker 被連線中斷殺掉「**沒補跑**」。
**它不用補跑 —— 它在平台上**:`vRkvQvmv`(trunc 0.05 = 變體 B),
sharpe **4.09** / fitness **3.95**,`FAIL = CONCENTRATED_WEIGHT, LOW_SUB_UNIVERSE_SHARPE`。
worker 是死在**印進度行之後、`append()` 之前**,模擬本身早就送出去了。

⇒ **A/B 現在是完整的 24 格,0 格解掉 `CONCENTRATED_WEIGHT`。**

同檔還有兩處被這件事作廢的敘述,一併加了撤回標記
(照 `docs/ops/dispatch.md:149`:**錯的結論不可以留在正確結論的上游**):
- 「⚠️ A/B 的證據基礎只有 10 格」那一整節的標題
- 「沒有排除」表裡的兩列(`group_backfill` 單位相容那格、放寬 `unitHandling`)

### ③ 已提交池那 6 條舊標籤的**正確領域歸屬**(督導點名要的)

督導從 `expr` 反推的「會計基本面 6 + 分析師預估 4 = 10/13」**完全正確**。
補上那 6 條的逐條歸屬(從 `numerator` + `expr` 查,不是猜):

| alpha | 舊標籤 | 分子 | 領域 |
|---|---|---|---|
| `bljOoR6K` | `RAT\|opinc_eq\|golden` | `operating_income` | 會計基本面 |
| `pwjv95Lj` | `S2A\|cashflow__close\|golden` | `cashflow_op` | 會計基本面 |
| `wpjQpqJ6` | `S2A\|operating_cap\|golden` | `operating_income` | 會計基本面 |
| `0mwrA8p8` | `RAT\|esteps_close\|golden` | `est_eps` | 分析師預估 |
| `58lEzemn` | `S2\|esteps\|avdiff\|TOP500` | `est_eps` | 分析師預估 |
| `1YwZwMjX` | `CMB\|lin0.5\|opinc` | `operating_income` | **混合** — 表達式是 `0.5*rank(-ts_delta(close,3)) + 0.5*rank(...operating_income...)`,**一半是價量動能** |

**13 條完整組成**:會計基本面 **6**(`bljOoR6K` `pwjv95Lj` `wpjQpqJ6` `xAjl5o9N` `xAjVdMLb` `N17E6wgg`)
／分析師預估 **4**(`0mwrA8p8` `58lEzemn` `Vk7MPXmG` `ZY7Opra3`)
／選擇權 **1**(`LL7rbXY6`,`call_breakeven_20`,來自 `option9`)
／價量關係圖 **1**(`qMj3AjbZ`)／混合 **1**(`1YwZwMjX`)。

⚠️ **但「池子偏食」這個解釋要打個折。** 吸走 pv13 那 17 條裡 14 條的是 `xAjVdMLb`,
它的分子是 `option_exercise_total_intrinsic_value` —— 一個**關於選擇權行權的會計科目**,
跟 pv13 的圖中心性排名不是直覺上的同一件事。
「10/13 是會計＋預估」是真的,但它**沒有解釋為什麼是那一條**吸走 14 條。
⇒ 偏食是**部分解釋**,不是完整機制。這一格仍然未知。

## 督導三問的直接回答

| 問 | 答 |
|---|---|
| ① 三個負結果各自排除了什麼假設 | **現在三份都有專段**。補之前 `delay0_axis_verdict` 缺,已補 |
| ② 有沒有實驗跑完但結論只在對話裡 | **有一件,就是上面 ②**(那格在平台上)。已寫進檔案 |
| ③ 有沒有已知但沒寫下來的「不要重走」 | **有,四條,列在下面** |

## 🔴 下一棒不要重走的四條

### 1. 開跑前先 `grep OFFICIAL_RULES.md` —— 今晚踩了**四次**

四次「答案本來就在同一個 repo 裡」:

| # | 花掉的 | 答案原本在哪 |
|---|---|---|
| 1 | (先前)self-correlation 判準連錯三次 | `OFFICIAL_RULES.md:43` 的官方逃生門 |
| 2 | 150 條 delay=0 news12 VECTOR | 帳本已有 951 條同組合零產出 |
| 3 | 整條 delay=0 軸 | `OFFICIAL_RULES.md:14-15`:delay-0 門檻 Sharpe 2／fitness 1.3(高 60%／30%) |
| 4 | 差點重跑 14 格 | `OFFICIAL_RULES.md:130`:unit warning **"do not prevent submission"**,旁邊註解甚至已經寫著「你踩過的」 |

**這不是四次不小心,是缺一個開工步驟。** 建議寫成硬規則:
**任何「平台為什麼擋我」的問題,第一個動作是 grep `OFFICIAL_RULES.md`,不是設計實驗。**

### 2. `runway.py` 的灰帶:**docstring 與程式碼不一致,而且它改變分類**

- docstring(`runway.py:26`)寫 **0.69~0.71**
- 實際跑的是 `THRESHOLD=0.7` / `GREY=0.02` ⇒ 邊界 **0.68 / 0.72**(`runway.py:447-449`)

實例:`ZY7MpbJY` 的 0.7173 用程式碼那組是「測不準」、用 docstring 那組是「拒」。
**我只把它寫進報告,沒有修 `runway.py`。** 下一棒會再踩一次。
(而且這個錯誤是**經由派工單傳染**的 —— 督導照 docstring 寫,我照程式碼做。)

### 3. `status=WARNING` 的歷史遺留:修法只對**未來**生效

`f84be9d7` 修好了 `simulate()`,但**帳本裡歷史上被丟掉的 WARNING 列沒有回填**。
已知至少 5 條(`docs/ledger-platform-gap-20260905.md` 的 199 條缺口裡)+ 今晚這 14 條。
撿回來的工具已經有了:`python reconcile.py --snapshot` 之後
`pick_next.build_pool` 的池子是「帳本 ∪ 平台快照」會自動收 ——
**但那個 snapshot 沒有人跑過**(最後一次是 09-08 22:40,在今晚所有實驗之前)。
⇒ **下一棒的第一個動作應該是跑一次 `reconcile.py --snapshot`。**

### 4. 三條**已經走死**的路,不要再投

| 路 | 死在哪 | 出處 |
|---|---|---|
| delay=0 這條軸 | 相關度沒降(0.849 vs 0.749)且門檻高 60%/30% | `2026-09-09_delay0_axis_verdict.md` |
| 新聞領域(`news12` VECTOR) | 24/24 格 0 格解掉 `CONCENTRATED_WEIGHT`;成因確定是「被賦權股票太少」(15 組 truncation 對照全部 bit-identical) | `2026-09-09_news12_template_result.md` + `_unit14_result.md` |
| 「把模板改成 raw」 | 30 組裡同時低相關且過閘的只有 **1 條**,而那條是 `1YwPvoJk`(督導 09-03 已否決) | `2026-09-09_pv13_raw_test.md` |

**還沒走死、但也沒驗過的**(留給下一棒判斷,不是推薦):
`vec_sum`(本帳號只開放 `vec_avg`/`vec_sum`,只用過前者)、
`news12` 的 75 個 MATRIX 欄位、`news18`、
模板裡 `ts_rank`/`group_rank`/`subindustry` 分群那幾層(完全沒動過)、
以及 `pv13_raw_test` 那個 **post-hoc 的欄位家族圖案**(圖中心性排名 vs revere sector 聚合)——
它沒有事前登記,**要驗得在另一個資料集上獨立重現**。

## pv13 沒有停止規則 —— 督導補的那條,我同意且補一句

督導在 `2026-09-10_brain_line_shutdown_handoff.md` §2 指出 pv13 沒有停止規則,`66e652c0` 那份只管新聞領域。
**確認屬實。** 補一個可執行的判準給下一棒:

> pv13 的跑道實測 **1 條**(貪婪下界),而那 1 條是已被否決的 `1YwPvoJk`。
> ⇒ **pv13 視同走死,除非有人先獨立重現「欄位家族」那個 post-hoc 圖案。**
> 重現不了就不要再投 pv13 的變體。
