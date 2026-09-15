# 條件(C)追加：`load_verification()` 在今晚實際指令下的「結構性不可達」驗證

**REACHABILITY_RESULT: UNREACHABLE**

- **受驗指令**：`python apply_first_batch_guard.py --batch first --apply`
  （`argv = ["--batch", "first", "--apply"]`）
- **受驗檔案**：`D:\carson-agent\docs\ops\2026-09-11_13支設private_準備\apply_first_batch_guard.py`
- **本次自算 blob hash**：`cdae8fd97fc77069206d886048aea71da1883a90`
  （`git hash-object`，本 session 自己跑出來的值，未抄用先前報告）
- **磁碟位元組 sha256**：`2288f9119cdb3ac48c2e32e44ff83ec3ae8d53d2d410e1cf56edeb5ba4f6aacc`，size `16197` bytes，363 行
- **HEAD 內的同路徑 blob**：`git rev-parse HEAD:...` → `cdae8fd97fc77069206d886048aea71da1883a90`（與自算值相同；working tree 對這兩支檔 `git status --porcelain` 為空）
- **連帶量到的 `set_private_13.py`**：blob `b4f75ef886bcf74413278d726de59452042ac1b3`，sha256 `e65f918f2ef1aebba4d8ad30144efadcf3ca6d22ff3f5771e6ce526fd1b58b6b`，668 行
- **驗證執行時間**：本機 `date` 取得 `2026-09-15 14:26:19` ～ `14:31:54`（`%Z` 輸出空白，系統未標時區字串；本機為台北）
- **本次動作**：全程唯讀。未編輯 `set_private_13.py` / `apply_first_batch_guard.py` 任何一個字（報告末附寫入前後 sha256 比對）；零 `--apply`；零 YouTube API 呼叫；未碰 `crontab.txt`；未碰 `quota_meter` 的 `ENFORCE`/`RESERVE`；未讀任何 `.env`/憑證檔。

---

## 0. 這份報告在回答什麼、不回答什麼

督導的追加要求原話是：「用突變或靜態呼叫圖證明 `load_verification()` 在該路徑下不可達（不是『沒試到』，是『到不了』）。」

- **回答**：從 `main(argv)` 進入、`argv = ["--batch","first","--apply"]`，到 process 結束為止，`load_verification()` 這個 call site 會不會被執行。
- **不回答**：`load_verification()` 本身的三個邏輯缺陷有沒有修（沒有，本次未動任何程式碼）；`--batch rest` 是否安全（先前報告判 FAIL，本報告不推翻也不背書）。

我先獨立重新確認了先前報告存在（`docs/ops/2026-09-15_taskA_C_freshcontext_verification.md`，21,498 bytes，mtime 2026-09-15 14:16），但**本報告的每一項結論都是我自己重新量出來的**，不引用其結論當前提。

---

## 1. `load_verification` 在全 repo 的出現位置（自己 grep，不採信任何轉述行號）

用 ripgrep 掃全 repo `*.py`（工具跑完、非逾時、路徑存在、有輸出）：

```
apply_first_batch_guard.py:42:def load_verification(path=VERIFY_PATH):        ← 定義
apply_first_batch_guard.py:78:        v = load_verification(verify_path)       ← 唯一的正式路徑 call site
apply_first_batch_guard.py:303: [("        v = load_verification(verify_path)\n        if v is None:\n",
apply_first_batch_guard.py:304:   "        v = load_verification(verify_path)\n        if False:\n")], "S2"),
```

**全 repo 只有這一支檔案提到這個名字**。第 303/304 行是 SELF-TEST 的突變字串常值（`MUT` 表的 `M1`），只有 `--self-test` 路徑才會被 `exec()` 成獨立模組去跑。

⚠️ 這是一個「零命中」型證據，按本專案的判準必須三者齊全才算數：路徑存在（✅ 有命中行、檔案 `ls` 得到）、退出碼 0（✅ ripgrep 正常回傳）、沒逾時（✅ 工具完成）。
我第一次用 `grep -rn` 掃全 repo **逾時被移到背景**——那種輸出和「真的零命中」長得一模一樣，**我沒有採信它**，改用 ripgrep 重做；背景那支後來完成（exit 0）結果與 ripgrep 一致，兩者互為佐證。

同時掃了 `youtube_channel/scripts/` 全目錄：
- `apply_first_batch_guard` / `load_verification` → **零引用**
- `sys.modules["__main__"]` / `import __main__` / `getattr(__main__` → **零引用**

也就是說：**沒有任何第三方程式碼持有通往 `load_verification` 的參照**。這條比控制流分析更強——就算控制流被我看漏，別的模組也沒有東西可以呼叫它。

---

## 2. 靜態控制流：從 `main(argv)` 逐行追到底

### 2.1 argparse 解析結果（實跑，非推測）

離線呼叫 `build_parser().parse_args(["--batch","first","--apply"])` 得到：

```
{'batch': 'first', 'apply': True, 'include_9ybt': False, 'self_test': False}   batch_type = str
```

`--batch` 宣告在第 91 行：`ap.add_argument("--batch", choices=["first", "rest"], ...)`，**沒有 `type=`**，所以值保持普通 `str`，不是任何自訂 `__eq__` 的子類。

### 2.2 `main()` 第 101–120 行的分支（逐字）

```python
101	    if a.self_test:
102	        if a.apply or a.batch:
103	            ap.error("--self-test 不能配 --apply/--batch")
104	        return self_test()
105	    if not a.batch:
106	        ap.error("必須指定 --batch first 或 --batch rest")
```

- `a.self_test` = `False`（`--self-test` 未出現，`store_true` 預設 `False`）⇒ **第 104 行的 `self_test()` 不會被呼叫**。這很重要，因為 `self_test()` **是**另一條真的會呼叫到 `load_verification` 的路徑（經第 327 行 `exec` 出來的模組副本，在 S2/S3/S4 情境裡跑 `guarded_run(..., "rest", ...)`）。它在本 argv 下進不去。
- 附帶：就算有人同時打 `--self-test --batch first --apply`，第 102–103 行會 `ap.error()` 直接退出（argparse `error()` 呼叫 `sys.exit(2)`），仍到不了 `guarded_run`。
- `a.batch` = `"first"`（非空字串，truthy）⇒ 第 106 行不觸發。

接著第 107–120 行（逐字）：

```python
107	    allowed = sp13.load_allowed(sp13.CAND_PATH, a.include_9ybt)
108	    os.chdir(sp13.YC)
109	    sys.path.insert(0, os.path.join(sp13.YC, "scripts"))
110	    import daily_publish as dp
111	    import quota_meter as qm
112	    print("# apply_first_batch_guard  %s  batch=%s  模式=%s"
113	          % (sp13.now_iso(), a.batch, "APPLY" if a.apply else sp13.DRY_TAG))
114	    print("# quota_meter(唯讀):ENFORCE=%s RESERVE=%s remaining=%s" % (qm.ENFORCE, qm.RESERVE, qm.remaining()))
115	    yt = dp.get_service()
116	    if not a.apply:
117	        yt = sp13._NoWrite(yt)
118	    code = 0
119	    try:
120	        res = guarded_run(yt, a.batch, allowed, a.apply, sp13.LOG_PATH, (qm.QuotaExhausted,))
```

`a.apply = True` ⇒ 第 117 行的 `_NoWrite` 包裹**不會**套用（這是預期行為：今晚就是要真送第一支）。`a.batch` 從第 100 行賦值後到第 120 行之間**沒有任何重新賦值**（`a.batch` 只在 102/105/113/120 被讀）。

### 2.3 `guarded_run()` 第 72–86 行（逐字）

```python
72	def guarded_run(yt, batch, allowed, apply, log_path, qe_types=(), out=print, verify_path=VERIFY_PATH):
73	    """..."""
75	    if batch == "first":
76	        targets = [FIRST]
77	    elif batch == "rest":
78	        v = load_verification(verify_path)
79	        if v is None:
80	            raise FirstBatchCapExceeded(...)
83	        targets = list(REST)
84	    else:
85	        raise FirstBatchCapExceeded("🔴 batch 必須是 'first' 或 'rest',收到 %r —— 不送" % (batch,))
86	    return sp13.run(yt, targets, allowed, apply, log_path, qe_types, out)
```

- `batch` 是**位置參數（區域變數）**，在函式全域內只被讀（75、77、85 行），**沒有任何一行對它賦值**。函式內沒有 `nonlocal`/`global`/`exec`/`locals()` 寫回。
- `if / elif / else` 在 Python 語意上互斥：`batch == "first"` 為 True 時，直譯器**不會求值** `elif` 的條件，更不會進入其 body。
- `guarded_run` **不接受 `targets` 參數**，呼叫端無法自組清單繞過。

### 2.4 位元碼層級證據（`dis.dis(guarded_run)`）

字節碼把「不可達」講得比原始碼還死：

```
 75           0 LOAD_FAST                1 (batch)
              2 LOAD_CONST               1 ('first')
              4 COMPARE_OP               2 (==)
              6 POP_JUMP_IF_FALSE       16
 76           8 LOAD_GLOBAL              0 (FIRST)
             10 BUILD_LIST               1
             12 STORE_FAST               8 (targets)
             14 JUMP_FORWARD            78 (to 94)      ← 無條件跳過整個 elif/else 區塊
 77     >>   16 LOAD_FAST                1 (batch)
             ...
 78          24 LOAD_GLOBAL              1 (load_verification)
             26 LOAD_FAST                7 (verify_path)
             28 CALL_FUNCTION            1
```

- `batch == "first"` 為真 ⇒ offset 6 的 `POP_JUMP_IF_FALSE 16` **不跳**，落到 8–12，然後 offset 14 是 **`JUMP_FORWARD` 到 94**，也就是**無條件**越過 offset 16–92（整個 `elif "rest"` 與 `else` 區塊，包含 offset 24 的 `LOAD_GLOBAL load_verification` / `CALL_FUNCTION`）。
- 沒有任何其他字節碼位址會跳進 offset 24。這是結構性的，不是「這次剛好沒走到」。

### 2.5 沒有裝飾器 / 包裝

- 全檔 grep `@[a-zA-Z]` 開頭的裝飾器行 → **零命中**。
- 實測 `type(guarded_run).__name__ == 'function'`、`hasattr(guarded_run, '__wrapped__') == False`。
- `sys.settrace` 追蹤時，frame 的 `f_code is guarded_run.__code__` 成立（若被包裝，追到的會是 wrapper 的 code object）。

---

## 3. 對抗性嘗試：我試過哪些「繞進去」的手段，全部失敗

| # | 攻擊假說 | 實際查核 | 結果 |
|---|---|---|---|
| 1 | `batch` 被某處改寫成 `"rest"` | 區域參數，函式內僅讀不寫；無 `locals()` 寫回、無 `exec` | 不成立 |
| 2 | 傳入怪異 `str` 子類讓 `==` 兩邊都真 | 即使 `== "first"` 為真，`elif` 在語意上不求值；且 argparse 無 `type=`，值是普通 `str` | 不成立 |
| 3 | 模組層級副作用觸發 | 第 27–35 行只有 `import`、路徑常數、`FIRST`/`REST` 取值；第 31 行 `import set_private_13` 發生在第 42 行 `def load_verification` **之前**，當下該名字根本還不存在於模組 namespace | 不成立 |
| 4 | `sp13` 模組層級回呼 | `set_private_13.py` 模組層級（第 33–53 行）只有 stdlib import、常數、例外類別與函式定義，零呼叫；全檔無 `atexit`/`signal.`/`importlib`/`sys.modules['__main__']` | 不成立 |
| 5 | `sp13.load_allowed()`（第 107 行）間接觸發 | 第 89–101 行：讀 `candidates.json`、算 md5、比對 `HARD13`、回傳 tuple。無 import、無回呼 | 不成立 |
| 6 | `import daily_publish` / `import quota_meter` 的模組層級副作用 | 兩支的模組層級都是 import + 路徑/常數定義；`scripts/` 全目錄對 `load_verification`、`apply_first_batch_guard`、`__main__` 零引用 | 不成立 |
| 7 | `dp.get_service()` / `qm.remaining()` / `qm.ENFORCE` 回呼 | 同上，無參照可用 | 不成立 |
| 8 | `sys.path` 汙染：第 30 行把 `HERE` 插到 sys.path[0]，讓 import 解析到 `準備/` 裡的檔 | `HERE` 內的 .py：`prep`/`dryrun`/`negctl`/`preflight_inst2`/`breakdown441`/`supp_9YbT`/`set_private_13`/`apply_first_batch_guard`。掃 `youtube_channel/` 全目錄 `*.py`，**沒有任何一行 import 這些名字**。且第 109 行後 `scripts/` 位於 sys.path[0]、`HERE` 退到 index 1，`scripts/` 優先 | 不成立 |
| 9 | 有人 `import apply_first_batch_guard`（非 `__main__`）觸發 | 該模組層級不呼叫 `load_verification`；且全 repo 零引用，沒人會這樣 import | 不成立 |
| 10 | 例外處理路徑（第 122–133 行）觸發 | 六個 `except` 分支全部只有 `print(e); code = N`，零呼叫 | 不成立 |
| 11 | 陳舊 / 被竄改的 `.pyc` 讓磁碟原始碼不是實際執行的碼 | `__pycache__/set_private_13.cpython-39.pyc`：magic 正確、`flags=0`（**timestamp-based，非 hash-based-unchecked**），記錄的 mtime=`1789120856`/size=`30897`，與磁碟原始碼**完全相符**。guard 本身以 `__main__` 執行，根本不吃 .pyc | 不成立 |
| 12 | `sitecustomize` / `usercustomize` / `.pth` 啟動期掛鉤 | 見下節，**有東西，但構不成向量** | 不成立（有 caveat） |
| 13 | `PYTHONSTARTUP` / `PYTHONPATH` 注入 | 兩者皆 `None`；且 `PYTHONSTARTUP` 只對互動式直譯器生效 | 不成立 |
| 14 | `sys.addaudithook` / `settrace` / `setprofile` / `atexit` 從外部注入呼叫 | `scripts/` 內僅 `hybrid_render.py` 提到 `atexit`，該檔不在本路徑 import 鏈上；且無論如何都沒有 `load_verification` 的參照可呼叫 | 不成立 |

### 3.1 關於第 12 項：venv 的 `sitecustomize.py` 是真的存在的，我讀了

`D:\carson-agent\youtube_channel\.venv\Lib\site-packages\sitecustomize.py`（29 行）在直譯器啟動時由 `site.py` 自動載入。它做兩件事：把 `scripts/` 插進 `sys.path[0]`，然後 `import _llm_shim`。

`_llm_shim.py`（6,097 bytes）對 `addaudithook` / `settrace` / `setprofile` / `atexit` / `__main__` / `sys.modules` / `exec(` / `eval(` 的 grep **零命中（grep 退出碼 1 = 確實無匹配，檔案存在、指令跑完）**。它唯一做的事是 monkeypatch `requests.post`，且在第 80 行以 URL 字串 `"api.anthropic.com/v1/messages"` 閘住；第 45–48 行在沒有 `OPENROUTER_API_KEY` 時直接 `return` 不接管（我實跑 venv python 時看到的正是這行「未接管」警告）。

**結論**：這個掛鉤改的是 `requests.post`，而 YouTube API 走的是 `googleapiclient`/`httplib2`，不是 `requests`；而且它沒有、也不可能有 `load_verification` 的參照（該函式在 site 初始化時尚不存在）。不構成可達性向量。

系統 Python（`C:\Users\User\AppData\Local\Programs\Python\Python39\python.exe`，3.9.13）的 site-packages 只有 `coloredlogs.pth` / `distutils-precedence.pth` / `pywin32.pth` 三個標準第三方 `.pth`，且**沒有** `sitecustomize.py` / `usercustomize.py`。

---

## 4. 動態佐證：tripwire + `sys.settrace` 逐行追蹤（含陽性對照）

靜態分析可能看漏，所以我另外寫了一支**離線探針**（放在本 session scratchpad，未落地到 `docs/ops/` 或任何專案目錄），做法是：用 `importlib` 從磁碟路徑載入該模組，**在記憶體裡**把模組物件的 `load_verification` 屬性換成一個會記帳的 tripwire（**磁碟檔案一個字都沒改**，報告末有前後 sha256 佐證），再以 stub service（任何 API 呼叫都被記下來、不出網）呼叫 `guarded_run`。

實測輸出（`PYTHONIOENCODING=utf-8`）：

```
PROBE_SRC_SHA256: 2288f9119cdb3ac48c2e32e44ff83ec3ae8d53d2d410e1cf56edeb5ba4f6aacc
MODULE_LEVEL_EXEC_OK  FIRST=MuXiM5IqVQQ  REST_n=12
A_FIRST_tripwire_calls: 0 (判準=0)
A_FIRST_result: {"already_ok": 0, "ok": 0, "skip": 0, "would_send": 1}
A_FIRST_api_list: ['MuXiM5IqVQQ']  api_update: []
C_executed_lines_in_guarded_run: [75, 76, 86]
C_line78_executed: False (判準=False)
B_POSCTL_raised: 🔴 nonexistent.json 不存在或不合法 —— 第一支(MuXiM5IqVQQ)尚未經獨立驗證,不准送剩下 
B_POSCTL_tripwire_calls_total: 1 (判準>0,證明 tripwire 是活的)
B_POSCTL_api: [] []
POST_SRC_SHA256: 2288f9119cdb3ac48c2e32e44ff83ec3ae8d53d2d410e1cf56edeb5ba4f6aacc
```

三件事：

1. **A（本路徑）**：`batch="first"` 下 tripwire 被呼叫 **0 次**。`sys.settrace` 記錄 `guarded_run` 實際執行過的行號是 **`[75, 76, 86]`**——只有 `if` 條件、`targets = [FIRST]`、`return`。**第 78 行沒有出現在執行行號集合裡**。
2. **B（陽性對照）**：同一支 tripwire、同一顆模組物件，改成 `batch="rest"` 後 tripwire **被呼叫 1 次**、並如預期丟出 `FirstBatchCapExceeded`（零 API）。
   這一條是刻意加的：**沒有陽性對照的「0 次」和「tripwire 自己壞掉」在輸出上長得一模一樣**。有了 B，A 的那個 0 才是「真的沒被呼叫」而不是「量尺是瞎的」。
3. **API 面**：`batch="first"` 全程只有 **1 次 `videos.list`，id 清單是 `['MuXiM5IqVQQ']`**（單一支），`videos.update` 0 次（因為探針用 `apply=False`，落在 `would_send`）。

---

## 5. 附帶查核：真正承重的不是 `load_verification`，是 `targets`

必須講清楚一件事，否則這份報告會給人錯誤的安全感：**`load_verification()` 本身是純唯讀函式**（第 44–69 行只做 `os.path.exists` / 讀檔 / `json.loads` / 欄位比對 / `fromisoformat`），它就算被呼叫也不會送出任何 API、不寫任何檔。真正決定「今晚會不會誤送 12 支」的是 `targets` 這個清單。

所以我另外查了 `sp13.run()`（`set_private_13.py:217–279`），確認 `targets` 不會在下游被放大：

```python
217	def run(yt, targets, allowed, apply, log_path, qe_types=(), out=print):
218	    targets = list(targets)
219	    for vid in targets:
220	        guard_id(vid, allowed)
221	    if len(set(targets)) != len(targets) or len(targets) > 50:
222	        raise Stop(...)
...
227	    todo = [v for v in targets if v not in done]
237	    resp = yt.videos().list(part="status,snippet", id=",".join(todo)).execute(num_retries=0)
249	    for n, vid in enumerate(todo, 1):
```

`allowed`（13 支）在 `run()` 內**只被當成 `guard_id()` 的成員資格白名單使用**，從來沒有被當成迭代來源；唯一的迭代來源是 `targets` 和由它導出的 `todo`。`targets = [FIRST]` ⇒ `videos.list` 只問 1 支、迴圈只跑 1 圈、`_send` 最多 1 次。第 4 節的探針實測 `api_list == ['MuXiM5IqVQQ']` 與此相符。

另外：`first_batch_verified.json` **目前不存在於磁碟**（`ls` 確認 No such file）。這代表縱深防禦仍在——即使有人誤打成 `--batch rest`，第 44–45 行會立刻回 `None`、第 80 行丟例外、零 API。

---

## 6. Caveat 四件套

### (1) 未量到什麼

- **未量**：`--batch rest` 路徑的安全性。本報告不對它下任何判斷；先前那份報告判 FAIL，我既不背書也不推翻。
- **未量**：`load_verification()` 那三個邏輯缺陷是否已修（**沒修，我一個字都沒改**）。
- **未量**：`dp.get_service()` 實際建立 OAuth service 的行為（依紅線禁止建真連線，探針全程用 stub）。我只靜態確認 `daily_publish.py` 模組層級與 `get_service` 呼叫鏈上沒有 `load_verification` 的參照。
- **未量**：C 擴充模組 / 直譯器本身被竄改的情形（例如被改過的 `python39.dll`、被改過的 `argparse` 模組）。這超出靜態＋動態分析能覆蓋的範圍。
- **未量**：指令被實際輸入時的**打字正確性**。本報告的結論嚴格綁定 `argv == ["--batch","first","--apply"]`；`--batch rest` 是另一條路徑，會呼叫 `load_verification`（這正是它該做的事）。
- **未量**：`youtube_channel/` 底下被 gitignore 的 `*.py` 是否存在同名遮蔽模組。ripgrep 預設尊重 `.gitignore`。不過這一項**不影響結論**，因為決定性的證據是「全 repo 沒有任何東西持有 `load_verification` 的參照」，遮蔽一個不相干的模組名也變不出這個參照。

### (2) 量法（下一個人可以原樣重跑）

```bash
# 指紋
git hash-object "docs/ops/2026-09-11_13支設private_準備/apply_first_batch_guard.py"
sha256sum   "docs/ops/2026-09-11_13支設private_準備/apply_first_batch_guard.py"

# 呼叫圖（要用 ripgrep 或確認 grep 沒逾時；逾時的空輸出 ≠ 零命中）
rg -n "load_verification|apply_first_batch_guard" --glob '*.py' D:\carson-agent

# 位元碼跳轉
python -c "import importlib.util,dis; s=importlib.util.spec_from_file_location('g', r'<path>'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); dis.dis(m.guarded_run)"

# tripwire + settrace（必須同時跑 batch='rest' 的陽性對照，否則那個 0 不算數）
```

探針腳本本身放在本 session 的 scratchpad（`...\scratchpad\probe_reachability.py`），**刻意不落地到專案目錄**——它是一次性量具，落地只會讓下一個人以為它是產線資產。要重跑請照上面的量法自己寫一份。

### (3) 撤銷門檻（什麼情況下這份 UNREACHABLE 就作廢）

這份結論**只綁定磁碟上 blob `cdae8fd97fc77069206d886048aea71da1883a90` 的那一版**。以下任一發生，本報告即刻失效、必須重驗：

- `apply_first_batch_guard.py` 的 blob hash 不再是 `cdae8fd9...`（**含純附加**——依本專案既有裁定，別人核過指紋的檔連附加都算動過）。
- `set_private_13.py` 的 blob hash 不再是 `b4f75ef8...`（`run()` 的 `targets` 語意是本結論的承重前提）。
- 實際指令的 argv 不是逐字的 `["--batch","first","--apply"]`。
- 執行用的直譯器換成上面兩個（系統 Python 3.9.13 / `youtube_channel\.venv` 的 3.9.13）以外的環境，或那兩個環境新增/修改了 `sitecustomize.py`、`usercustomize.py`、`.pth`。

**撤銷的條件是「我量過了」，不是「別人說沒變」**：重驗時請自己跑一次 `git hash-object` 比對，別採信轉述。

### (4) 撤掉這些 caveat 之後，仍然不敢宣稱什麼

即使上面全部重驗通過，我**仍然不敢**宣稱：

- 「今晚這條指令是安全的」。我證的是 `load_verification()` 到不了，以及 `targets` 在下游不會被放大成 12 支。**沒有**涵蓋：OAuth service 建構的副作用、`httplib2`/`google_auth_httplib2` 函式庫層的兩個重送分支（`set_private_13.py` docstring 第 22–23 行自己標註了、本檔擋不到）、`status.containsSyntheticMedia` 的殘留洞（同 docstring 第 26 行）、以及配額帳本的實際水位。
- 「這個 guard 未來仍然不可達」。我量的是一個**磁碟快照**。一次 commit、一次 rebase、一次 `checkout` 換行結尾漂移，這份結論就過期了。**它是照片，不是保單。**
- 「`load_verification()` 沒問題」。它有先前報告指出的三個缺陷，本次完全未處理。這份報告說的只是**今晚這條路不會經過它**。

---

## 7. 唯讀證明（動作前後指紋比對）

| 檔案 | 驗證開始時 | 探針跑完後 | 是否變動 |
|---|---|---|---|
| `apply_first_batch_guard.py` (sha256) | `2288f9119cdb3ac48c2e32e44ff83ec3ae8d53d2d410e1cf56edeb5ba4f6aacc` | `2288f9119cdb3ac48c2e32e44ff83ec3ae8d53d2d410e1cf56edeb5ba4f6aacc` | **無** |
| `set_private_13.py` (sha256) | — | `e65f918f2ef1aebba4d8ad30144efadcf3ca6d22ff3f5771e6ce526fd1b58b6b` | **無**（`git status --porcelain` 空） |

`git status --porcelain` 對這兩支檔案輸出為空，且 `git rev-parse HEAD:<guard>` = `cdae8fd97fc77069206d886048aea71da1883a90` = 我自算的 blob hash，三方一致。

⚠️ 依本專案既有教訓，`git hash-object` 在 `autocrlf=true` 下看不見 CRLF 漂移，所以上表**同時**附了磁碟位元組 sha256 與 size（16197 / 30897 bytes），不是只靠 blob。

**本報告未執行 commit**（依派工要求，commit 留給主線）。

---

**REACHABILITY_RESULT: UNREACHABLE**

在磁碟版本 blob `cdae8fd97fc77069206d886048aea71da1883a90`（sha256 `2288f911...`）下，以 `argv = ["--batch","first","--apply"]` 進入 `main()`，`load_verification()` 的唯一正式 call site（第 78 行）位於 `elif batch == "rest"` 區塊內，字節碼層由 offset 14 的無條件 `JUMP_FORWARD` 越過；全 repo 無任何其他程式碼持有該函式的參照；模組層級、import 鏈、例外路徑、啟動期掛鉤（`sitecustomize`/`.pth`）、`.pyc` 陳舊性共 14 項對抗性假說全部不成立；動態 tripwire + `sys.settrace` 實測呼叫次數 0、執行行號集合 `[75, 76, 86]`，並有 `batch="rest"` 的陽性對照證明量尺是活的。

結論僅綁定此磁碟快照，不延伸到任何後續改動。
