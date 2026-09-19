# 那 14 格「單位不相容」：**根本不用重跑，平台上一條不漏全在**

> 續 `docs/ops/2026-09-09_news12_template_result.md`(該檔記「A/B 的證據基礎只有 10 格不是 24 格」)。
> **零提交動作**、**0 條新模擬**。**實際找回 14 / 預期 14。**

## 結論一句

那 14 格**不是沒跑起來,是跑完了而我們把它丟掉了**。
`status=WARNING` 被 `simulate()` 當成失敗,但官方明文說那只是警告。
14 格全部在平台上找回來 —— **而且沒有任何一格解掉 `CONCENTRATED_WEIGHT`**。

## 官方原文(`OFFICIAL_RULES.md:130`)

> "Unit warnings are provided for reference in simple cases and **do not prevent submission**...
> You can safely ignore these warnings if you're sure the Alpha correctly handles data units."

**這一行本來就在 repo 裡,連旁邊的註解都寫著「你踩過的 `Incompatible unit` 官方明講只是警告、不擋提交」。**
這是這條線第四次「答案本來就在同一個 repo 裡」。

錯誤原文長這樣(帳本):

    Incompatible unit for input of "group_backfill" at index 0,
    expected "Unit[]", found "Unit[CSShare:1]"

## 14 格找回來的結果:**0 格解掉 `CONCENTRATED_WEIGHT`**

7 條相異運算式 × 2 個 truncation = 14 個 alpha,全部命中。

| 欄位 / 形式 | trunc 0.1 | trunc 0.05 | sharpe / fitness | 仍在的 FAIL |
|---|---|---|---|---|
| `all_sessions_vwap` `v_raw` | `QP398Z3w` | `vRkvQvmv` | **4.09 / 3.95** | `CONCENTRATED_WEIGHT`,`LOW_SUB_UNIVERSE_SHARPE` |
| `main_post_session_vwap` `v_raw` | `1YxzM1GQ` | `qMW6RprK` | 2.81 / 2.35 | 同上 |
| `closing_session_volume_count` `v_per_px` | `E5vedXgm` | `E5vedQ0m` | 1.55 / 0.95 | +`LOW_FITNESS` |
| `main_opening_trading_volume` `v_per_px` | `le83mL2O` | `MP1LrxN6` | 1.09 / 0.61 | +`LOW_SHARPE`,`LOW_FITNESS` |
| `after_hours_vwap_value` `v_per_px` | `9qV7naj2` | `akLE5kn5` | −1.58 / −1.00 | +`LOW_SHARPE`,`LOW_FITNESS` |
| `main_opening_trading_volume` `v_raw` | `O0rxLlZq` | `3q9eNAWX` | 0.39 / 0.12 | +`LOW_SHARPE`,`LOW_FITNESS` |
| `premarket_vwap` `v_per_px` | `78Znpgp2` | `wpYErPkx` | −3.35 / −3.14 | +`LOW_SHARPE`,`LOW_FITNESS` |

⇒ **A/B 兩個變體的證據基礎從 10 格補齊到 24 格,而結論不變:0 格解掉。**
前一份報告那個「別把結論說得比證據強」的但書**現在可以撤掉了** —— 證據補滿了,結論一樣。

一個值得記的副產品:`all_sessions_vwap|v_raw` 從基準的 2.11/1.35 變成 **4.09/3.95**,
`group_backfill` 對它是**大幅改善**的 —— 但照樣掛 `CONCENTRATED_WEIGHT`。
**指標變好跟閘門解不解得掉是兩件事。**

## 順便第二次證實:truncation 完全沒被觸發

7 條運算式各跑了 0.1 與 0.05 兩次,**七組的 sharpe / fitness 全部一模一樣**
(0.39/0.12、1.09/0.61、4.09/3.95、1.55/0.95、−3.35/−3.14、2.81/2.35、−1.58/−1.00)。

前一份報告用 C 變體的 8 格得到同一結論,**這裡是 7 組獨立的重現**,合計 15 組。
**「單一股票權重過高」那一支可以確定地排除了。**

## 修法:`status=WARNING` 不再被當失敗

`simulate()` 原本只認 `COMPLETE`,於是**模擬已跑完、平台已建立 alpha** 的情況被記成失敗、
`alpha_id` 丟掉、去重讓它永遠不會重試。判準改成**有沒有 alpha**,不是狀態字串好不好看。
警告本身落帳在 `rec["warning"]`(它是那條 alpha 的性質,不是這次執行的雜訊)。

**同族第二次**:`docs/ledger-platform-gap-20260905.md` 那 199 條缺口裡,
`status=WARNING` 那 5 條就是同一個原因。這次修掉的是同一個洞。

四個對照都跑過(stub,入口就把 `auth` 換成會拋的,不連網;帳本 md5 前後一致):

| 情境 | 預期 | 實際 |
|---|---|---|
| `WARNING` + 有 alpha | 收 | 收 ✅(帶 warning) |
| `WARNING` + 沒有 alpha | 拒 | 拒 ✅ |
| **陰性** `ERROR` + 有 alpha | 拒 | 拒 ✅ |
| **陰性** `COMPLETE` | 收 | 收 ✅ |

**不需要回填帳本**:`pick_next.build_pool` 的候選池是「帳本 ∪ 平台快照」,
下一次 `reconcile.py --snapshot` 會自動把這 14 條收進來。

## 已排除 / 沒有排除

### 已排除

| 假設 | 憑什麼 |
|---|---|
| 「那 14 格因為單位不相容所以沒跑」 | 14/14 在平台上找回來,指標完整 |
| 「`group_backfill` 也許在單位相容的欄位上有用」 | 補滿的 24 格裡 **0 格**解掉 `CONCENTRATED_WEIGHT` |
| 「`CONCENTRATED_WEIGHT` 是單一股票權重過高」 | 15 組 truncation 0.1 vs 0.05 結果完全相同 |
| 「要放寬 `unitHandling` 才能測」 | 不用。官方說警告不擋提交,問題在我們的判讀 |

### **沒有**排除

| 仍然未知 | 為什麼 |
|---|---|
| 這 14 條的 self-correlation | 沒量。它們全部掛閘門,**量了也不能提交**,不是現在該花的 |
| 「被賦權股票太少」還有沒有別的解法 | `group_backfill` 是唯一測過的跨股票補值工具 |
| 帳本裡歷史上有多少 `status=WARNING` 被丟掉 | 修法只對**未來**生效;歷史那些要靠 `reconcile.py` 撿 |

## 對停止規則的影響:**不變**

`2026-09-09_news12_template_result.md` 的停止條件是「0 格解掉 ⇒ 新聞領域收工」。
證據從 10 格補到 24 格之後,**0 格仍然是 0 格**。停止規則維持。
差別只在:當時那個「證據不足」的但書沒有了,現在是滿的。
