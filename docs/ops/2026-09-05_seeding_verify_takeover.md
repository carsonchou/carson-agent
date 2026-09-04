# 09-05 05:50 種題驗收(總督導親自接手)

**為什麼是我量的**:負責的兩條線在 02:01 前後隨 session 一起 429 停擺
(`wF:p1` 的 monitor `bfv0w1bj2`、基建線缺席哨),兩個哨都不會出聲。
我是當時唯一還在 direct 路由上的 session,所以直接接手,不等它們。

## 結論一句話

**種題停三天的根因是少一行 `import re`,不是題庫空、也不是閘門太嚴。**
已於 09-04 補上;09-05 05:50 那輪正在真的跑(結果另補)。

## 逐日實測(判準:`stock_checkup_daily_state.json` 的 `history[].n_new_topics`)

| 日期 | 筆數 | sum(n_new_topics) | local_cron |
|---|---|---|---|
| 08-30 | 16 | **16** | ✓ 完成(18 分鐘) |
| 09-01 | 16 | **16** | ✓ 完成(12 分鐘) |
| 09-02 | 0 | — | ✗ 失敗 exit 1(15 秒) |
| 09-03 | 0 | — | ✗ 失敗 exit 1(19 秒) |
| 09-04 | 0 | — | ✓ 完成(**2 秒**) |

`last_run_date` 停在 **2026-09-01**。健康長相是 16/16 全中。

## 根因:一行 import

09-02 與 09-03 的 stderr 是**一字不差的同一個 traceback**:

```
File "stock_checkup_daily.py", line 270, in seed_topics_for_code
    hook = re.sub(r"\s*[（(]\s*" + re.escape(code) + r"\s*[)）]\s*", "", hook)
NameError: name 're' is not defined
```

現行檔案 `:48` 已補,註解自己指認了上游:
`import re  # 🔴 2026-09-04 補:c7a9c8e6(09-01)的標題去重用了 re.sub`
⇒ 09-01 的標題去重改動引入 `re.sub` 卻沒 import,隔天早上才爆。

## 🔴 它咬人的是崩潰的「位置」,不是崩潰本身

主迴圈的順序是:

```python
cand["done"] = True
_save_backlog(bl)                 # ← 先存檔
n_new_topics = seed_topics_for_code(...)   # ← 才種題,在這裡炸
```

⇒ 每次崩潰都**已經把那檔標成 done 並落盤**,然後才炸。那檔從此不再被選中,
而它一題都沒種到。**這是靜默掉單,不是失敗重試。**

## 損失:精確是 2 檔

`done` 但 `history` 裡查無此 code 的共 33 檔,**但那個數字不能用**——
`done_at` 顯示它混了至少四堆,大多早於本 bug:

```
07-30: 2   08-03: 3   08-10: 18   09-02: 1   09-03: 1   09-05: 2(今天在跑,非損失)   None: 6
```

本 bug 的損失是 `done_at` 落在 09-02/09-03 的兩檔:

- **8215 明基材**(2026-09-02)
- **5464 霖宏**(2026-09-03)

**修法**:把這兩檔的 `done` 清掉即可重新入列(它們沒被 skip,資料沒問題)。

⚠️ **08-10 那堆 18 檔是另一個洞**,成因不同、規模是本 bug 的 9 倍,今天不順手歸因。
拿 33 去講本 bug 的損失,和拿「81 支待發」去講配額不足是同一個錯:**分母混了幾堆**。

## 尚未解決:09-04 的 2 秒 exit 0

09-04 跑了 2 秒、exit 0、`history` 零列。我曾推測是 backlog 見底走
`remaining` 為空的 `break`,**實測推翻**:`remaining=1308`(total 1925 / done 586 / skip 32)。
**我沒有答案,不補一個看起來合理的。** 這個要另查——
它的形狀正是「閘門執行完全正確但問錯問題」那一類:exit 0 + 零產出 + 零錯誤訊號。

## 未採用的判準

- **不看自環率**:分母跟著處置一起動,愈有效愈像無效(`verification-that-cannot-fail` 第八種)。
- **`last_run_date` 翻日只是必要條件**:它只在 `done_this_run > 0` 時才寫,
  但寫了不代表每檔都種到題(16 列全 0 與它完全相容)。

相關記憶:[[yt-topic-bank-burned-by-regen]] [[verification-that-cannot-fail]]
[[static-reading-vs-runtime-behaviour]] [[usage-limit-silent-stall]]
