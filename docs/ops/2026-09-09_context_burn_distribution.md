# 各 session 的 context 燒法實測(2026-09-09)

**為什麼有這份**:Carson 從三個選項裡挑了「先量出各 session 的 context 分佈」——
因為 memory `claude-context-budget-2026-09` 說同樣的 tool call 數,context 大小決定額度花多少。
量測工具:`scripts/ctx_dist.py`(已入版控,可重跑)。
資料來源:`D:\claude\projects\D--carson-agent\*.jsonl`,取 `type=="assistant"` 且帶 `usage` 的紀錄,
每次呼叫的 context = `input_tokens + cache_creation_input_tokens + cache_read_input_tokens`。
窗口:取樣當下往回 24 小時。

## 🔴 先更正一個我自己講錯的數字

我先前對 Carson 說「context 這根槓桿值 **6.7 倍**」。**那個數字不是可回收倍率。**

- **6.7 倍**是**單次呼叫**的比值(800K context vs 120K context),算術上對。
- **可回收倍率**要用整批實際分佈算:24h 實燒 **839.5M**,
  「全部壓到 120K」的反事實下限是 **436.9M** ⇒ **1.92 倍**。

⇒ 決策不一樣:1.92 倍仍然值得做,但它不是「省掉 85%」。
**引用本檔請引 1.92,不要引 6.7。**

## 實測(24h 窗)

- 總燒量 **839.5M tokens**,**3,791 次呼叫**,**16 個 session**。
- **超過 120K 的那一段佔 402.6M = 全部的 48.0%**。

### 兩格吃掉 46.6%,而且不是因為做比較多事

| 窗格 | 24h 燒量 | 呼叫數 | 平均 context |
|---|---|---|---|
| `wF:p1` | 246.6M | 857 | 288K |
| `wF:p3` | 144.6M | 607 | 238K |
| (我自己) | — | **1,007** | — |

⇒ 我的呼叫數最多,燒量卻不是最高。**差別在每次呼叫扛多大的 context,不在做多少事。**

### 🔴 四格已越過 dispatch.md 的 200K 交棒線

`wF:p4` **507K**、`wF:p5` 245K、`wF:p1` 248K、`wF:p3` 209K(`w9:p1` 正好 199K,貼線)。
**這四格合計佔 24h 燒量的 59.8%。**

dispatch.md 的規則:≥120K 收尾當前任務不開新複雜工作;≥200K 不接新工作、狀態寫成交棒檔、
開新 session 續做,且**不要靠 compaction 續命,交棒優於 compact**。

### 三格 24h 內零 API 呼叫(不燒額度,但各佔約 250MB RAM)

`wA:p1`(`4332a84b`)、`wE:p1`(`8ae57f4b`)、`wB:p1`(`cda0ca12`)。
`wA:p1` 最後一次**真正的 API 呼叫**是 **09-03 08:44**,而它的逐字稿長到 **111MB**。

🔴 **量閒置不能看檔案 mtime**:hook 與使用者輸入會繼續往 jsonl 追加紀錄,
最後一筆**紀錄**的時間 ≠ 最後一次**呼叫**的時間(`wA:p1` 兩者差 2 天)。
必須過濾 `type=="assistant"` 且帶 `usage` 才量得到真的呼叫。

## 待 Carson 拍板(我沒動)

1. 四格越線的要不要請它們寫交棒檔並重開 —— **我不會單方面重啟別人的窗格**
   (會銷毀對方未送出的草稿,見 [[herdr-pane-read-prompt-traps]])。
2. 三格零呼叫的要不要關 —— 關掉省 RAM 不省額度。

相關 memory:`claude-context-budget-2026-09`、`usage-limit-silent-stall`、`herdr-pane-session-map`。
