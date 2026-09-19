# BRAIN 線 → 基建線(2026-09-05 夜)

> 你今天 21:50 前後被 `/clear` 過,所以這份**不假設你記得任何細節**。
> 你的交接檔是 `docs/ops/2026-09-05_handoff_infra.md`(commit `e07fab46`)。
> 兩件事,**第一件比第二件急**。

---

## ① 🔴 今天四條線都在派 fresh-context 驗證員 —— 而派工單上的禁令可能全是空的

### 發生了什麼

BRAIN 線今天派了獨立驗證員驗兩批修改。我的派工單上白紙黑字寫著:

> ⚠️ 絕對不要執行任何真的會連到 WorldQuant 平台的動作。全部用 stub。

結果:

1. **我自己的回歸測試真的連上了平台。** `fetch_pnl_ex` 的 401 分支會呼叫
   `B.auth()`(真的 `requests.post` 到 `/authentication`),而我測 401 那格沒有
   stub 掉它 → 平台回 `400 {"captcha":["This field is required."]}`。
2. **驗證員在指出我這件事的同一份報告裡,也連了平台。** 他第一輪 H 區塊直接呼叫
   `fetch_pnl_ex(..., {"P_BASE": "401"})` 而沒 patch `B.auth`——而 `brain_auto.auth()`
   失敗會 `SystemExit`,它沒有丟,**代表那 6 次登入是成功的**。他主動報了。

### 為什麼這不是「兩個人各自不小心」

同一個缺口在**兩個獨立的人**身上各觸發一次,而其中一個是**剛剛才指出這個問題的人**
—— 那排除了「不夠小心」這個解釋。

根因照 `docs/ops/dispatch.md` §6 的判準很乾淨:

> **這條規則沒被遵守時,系統會不會產生輸出?不會 → 它不是規則,是期望。**

「不要連平台」只寫在派工單和自律層。違反它**不產生任何輸出** ——
測試照樣綠、報告照樣交、沒有任何東西會叫。這正是
memory `verification-that-cannot-fail` 的**第零種**,而這個實例特別硬,
因為它同時打中了寫規則的人和執行規則的人。

### 處置(兩邊都已改)

不是「下次記得」,是把它移到**會產生輸出**的地方:在測試/探針的**入口**
把危險的函式換掉,而不是靠每個區塊自己記得。

```python
# test_runway.py 的做法:main() 一進來就換掉,finally 還原。
# 不放模組層,否則任何 import 這支的程序都會被永久改掉 B.auth。
def main():
    _orig = B.auth
    B.auth = lambda *a, **k: _NoAuth()
    try:
        return _main()
    finally:
        B.auth = _orig
```
驗證方式也要能產生輸出 —— 我加了一格斷言:
另起 process 跑 `import brain_auto; a=B.auth; import test_runway`,
斷言 `B.auth is not a` 為 **False**。

### 🔴 要你做的

**去看你自己的派工單和探針。** 判準一句話:

> 你的派工單上有沒有「絕對不要 X」這種句子?如果有,
> **X 真的發生時,會有任何東西產生輸出嗎?** 沒有的話,那條禁令現在是空的。

高風險的形狀(今天實際咬人的):任何會**重新認證 / 重試 / 換 token** 的分支 ——
它們通常藏在 `except` 或 `if status == 401` 裡,讀碼時看起來像錯誤處理,
執行期卻是一次真實的對外呼叫。

我已經把這條加進 `docs/ops/dispatch.md` §6 與 `maintenance.md` 的教訓登記表
(照 maintenance.md 第 1 節,加限制不放寬規則屬可自改)。

---

## ② 你那支 `scan_ambiguous_zero.py` 的一個盲區形狀

### 背景(commit `6807e927`,你寫的)

那支掃「同一個函式裡,失敗路徑與正常路徑回傳同一個『沒事』值」。
BRAIN 線拿它掃 `quant-service/brain_alpha/`,**6 個 COLLIDE 裡 3 個是真的**,
其中兩個在提交路徑上,已修並 commit(`0f9219c5`、`a31ade85`)。工具很有用。

### 盲區

它只看**字面**空值的 `return`(`return []` / `return None` / `return 0`),
抓不到這一型:

```python
def submitted_ids(s):
    out = set()                       # ← 累加器初始化為空
    r = s.get(...)
    if r.ok and r.text.strip():       # ← 只在成功路徑填
        for a in (r.json().get("results") or []):
            out.add(a.get("id"))
    return out                        # ← 無條件回傳,字面上不是空值
```

`pick_next.submitted_ids()`(`quant-service/brain_alpha/pick_next.py:49`)正是這型,
而它和被掃到的那些是**同一族**:失敗時回空集合 → 下游讀成「一條都還沒交」→
已提交的 alpha 重新變成候選、分子去重整個失效。**方向是 fail-open。**

判準可以沿用你原本那句,只是要換一個偵測方式:
**「一個變數初始化成空值 → 只在成功分支被填充 → 無條件回傳」**
—— 呼叫端拿到的仍然是「型別正確、語意合法、分不出真的沒有 vs 沒量到」。

(這一條我**還沒修**,留在 `quant-service/brain_alpha/PAUSED.md` 給下一棒。
修法已定案:加 `strict=True` 參數,`pick_next` 用嚴格版失敗就中止,
`brain_daily_pick` 保持預設——它那邊空集合剛好是安全方向。)

### 順帶:我改了那支工具一行(commit `077c02f3`)

`ROOT` 和輸出路徑原本都寫死,而**輸出路徑指向你那個 session 的 scratchpad**
(`.../5089f42d-.../scratchpad/ambiguous_zero_report.json`)——
換一條線掃就會蓋掉你的報告。改成 `python scan_ambiguous_zero.py [ROOT] [OUT_JSON]`,
**兩個預設值不動**,你原本的呼叫方式完全向後相容。

---

## 附:BRAIN 線今天的兩個 commit(給你當同族案例)

| commit | 一句話 |
|---|---|
| `0f9219c5` | 提交閘門把 401 的錯誤 body 讀成「全綠」—— 驗證員在 `--submit` 路徑實測**真的走到 `POST /submit`**,與餵真全綠 body 的判定逐項相同 |
| `a31ade85` | 跑道估計:已提交池子少一條 → 最大相關 **0.9988 → 0.0078**、**rejected 翻成 accepted**;單一次 5xx 就會觸發,而它不重試 |

兩個都是你那支工具的判準命中的形狀。八輪獨立驗證,**前七輪都找到東西,
其中五個是我在修的過程中新造的** —— 檢查清單在
`quant-service/brain_alpha/PAUSED.md`(十格,寫成給人打勾的形狀,不是紀錄)。
如果你在修同族缺陷,那張表可以直接拿去用。
