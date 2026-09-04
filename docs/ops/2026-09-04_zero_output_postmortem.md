# 2026-09-04 產出 0 支:一次網路斷線,和我建的三個錯誤因果鏈

## 結論(先講,因為過程比結論長)

**今天 06:07 產出 0 支的原因是網路斷線,不是任何程式缺陷。**

```
05:50 stock_checkup_daily  Could not resolve host: query1.finance.yahoo.com  一檔都抓不到
06:07 produce_batch        所有 LLM 供應商都失敗:
                             gemini      Max retries exceeded (generativelanguage.googleapis.com)
                             openrouter  Max retries exceeded (openrouter.ai)
                             groq        Max retries exceeded (api.groq.com)
08:30 實測                  四個 host 全部解析正常,網路已恢復
```

**產線的行為是正確的**:打不到 LLM → 重試 → 全失敗 → 記「long 連續失敗,跳過」→ 不產出垃圾。
同型:memory `claude-code-autoupdate-ipv4-issue`(IPv4 出口間歇不穩)。

## 我建的三個錯誤因果鏈,以及它們為什麼看起來都很合理

| # | 我的推論 | 憑什麼推的 | 被什麼推翻 |
|---|---|---|---|
| 1 | 餵料端 NameError → 題庫空 → 產出 0 | ops_log 的「去重 15 / 濾掉 18 / long 連續失敗」+ 昨天的 traceback | 今天的失敗**沒有** NameError;題庫有 207 題未用、事實齊全、0 孤兒 |
| 2 | `pull_topic` 只吐 33 題才是真因 | 驗證員指出候選池 ≠ 題庫 | `_grounded >= 5` 的 fail-safe 有生效,選題抽得到題 |
| 3 | `_llm_shim` 昨天改三次可能改壞了 | 昨天確實改了三次,而昨天同一支跑 70 分鐘正常 | stderr 顯示是三家供應商**全部**連不上,不是 shim |

**三個鏈都是在沒有讀 `job_stderr.log` 的情況下建的。答案從頭到尾就在那個檔裡,我第三次才去看。**

而三個都很合理:①有真實的 traceback 撐著 ②有獨立驗證員的資料撐著 ③有時間相關性撐著。
**「合理」在這裡完全沒有鑑別力** —— 因為真因也很合理,而且只有一個。

## 附帶產出:一個真實的、必要的、但和今天無關的修法

`eed3ca25`:`stock_checkup_daily.py` 缺 `import re`,自 `c7a9c8e6`(09-01 21:51)起
`seed_topics_for_code` 每次必然 NameError。**09-02、09-03 兩天的種題確實沒發生**(約 32 檔)。
AST 驗證:修法前 `re` 繫結點 0、使用點 5;修法後繫結點 1、`pyflakes` 0 undefined。

⚠️ 那三行 `re.sub` **寫了三天、跑了零次**,`eed3ca25` 之後才會第一次真的執行。
獨立驗證員拿 407 筆真實已種題乾跑:77 筆會被改寫、**0 筆丟掉非代號的數字**,
涵蓋句中代號、帶連字號股名、全形括號、股名含 `*`。**真實資料上是對的。**

但它用敵意輸入打出三個真缺陷(目前經驗命中 0/407,但空間是真的 ——
51% 的真實 hook 含非代號的四位數,而報酬率常態落在 1000~4000%、台股代號 1101~9962,**區間重疊**):

```
代號=真統計數字   抱20年報酬2330%   → 抱20年報酬%      真數字被靜默刪,留下懸空的 %
代號=小數整數部   報酬2330.5%       → 報酬.5%          (?!\d) 擋不住小數點
代號出現兩次      2303 vs 2303 對決 → vs 對決          count=1 沒限制住(前面的迴圈已剝一次)
代號=年份         2024年大跌40%     → 年大跌40%
```

**而改寫之後沒有任何閘門。** `is_banned_skeleton` / `numbers_sourced_to_fact` 等全部在改寫**之前**
執行;改寫到 `new_recs.append` 之間只重算 `_norm` 指紋。**溯源驗過的是改寫前的標題。**
→ 建議在 append 前重跑一次 `numbers_sourced_to_fact`,便宜且正好擋住上面三種。**尚未實作。**

## 另一個順帶發現:`daily_publish.py:1136` 的防護寫壞了但無害

`pyflakes`(先做陽性對照確認尺對這個病有效)掃出 `undefined name 'TW'`。查證:
那一行是 `datetime.now(TW) if "TW" in dir() else datetime.now()` —— **有防護,不會 NameError**。
但 `dir()` 在函式內回傳的是**區域**名字,看不到模組層(實測 False),
所以它**永遠走 fallback**。而 `TW` 根本沒有定義,本機時區又是台北 → **無實害**。
`pyflakes` 另有 5 處未檢視。

## 給下一個人的兩條

1. **產線異常先讀 `logs/job_stderr.log` 的對應區塊,再建因果鏈。**
   ops_log 只有結果,stderr 才有原因。我今天用 ops_log 建了三個錯的鏈。
2. **「合理」沒有鑑別力。** 三個錯誤的鏈各自都有真實證據撐著(真 traceback、真資料、真時間相關)。
   分辨它們的不是合理程度,是有沒有去看那個會直接說出答案的地方。
