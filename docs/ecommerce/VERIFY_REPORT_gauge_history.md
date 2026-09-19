# VERIFY_REPORT_gauge_history — 找碴驗證(動到產線掃描器)

> 驗證人:verifier-sku2(fresh-context,未參與實作)｜日期:2026-07-17
> 對象:`quant-service/data_hunter/scan.py`(**正在跑的產線掃描器**,S1/S2/S3/S6 全靠它)+ `tests/test_gauge_history.py`(新增),未 commit
> 立場:**試圖證明它會弄壞掃描**。故障注入/突變/原子性模擬全部自己動手。
> 唯讀:未改任何程式、**未跑全掃描**(不覆寫 state.json)、未打外部網路、所有寫入都在 tmp。
> 重現:`scratchpad/attack_gauge.py`、`mutate_gauge.py`

## 總結

| 攻擊面 | 結論 |
|---|---|
| 1 零行為改變 | **PASS** — hook 在 state.json 落地**之後**,且對 `state` 物件零副作用 |
| 2 絕不炸掃描 | **PASS** — 9/9 故障注入全部回 False 不拋;突變後容錯測試轉紅 |
| 3 冪等 | **PASS,但有一個 MAJOR 副作用**(見 M1) |
| 4 原子性 | **PASS** — 整檔重寫 **比 append-only 更安全**,team-lead 的擔憂不成立 |
| 5 足以重建 ④ | **PASS** — 我獨立重算 = 45.4,與官方逐位一致 |
| 6 既有測試 | **PASS** — data_hunter **335**、ecommerce **92**,與宣稱一致 |

**0 BLOCKER / 1 MAJOR / 3 MINOR。**

**掃描器的安全性我打不破——這部分做得很紮實。** 但它**靜默地達不到自己存在的目的**:看板 app 只要開著,每天最後一筆幾乎必然是 `confirmed=False`,半年後想濾出的「乾淨 confirmed 序列」會幾乎是空的。

---

## MAJOR

### M1 看板 app 每 30 分鐘覆蓋掉當天的 confirmed 記錄 → 半年後這個檔等於白存

**這個改動的唯一理由**,是它自己 docstring 寫的:「盤中的讀數是**暫定值**、收盤後才是**確認值**……未來分析必須能濾出 confirmed 的那條乾淨序列」。

**但去重規則是「同日只留最後寫的那筆」,而最後寫的那筆幾乎必然是盤後的 realtime 掃描。**

證據鏈:
1. `app.py:59` 背景迴圈無條件呼叫 `scan.run_once(push=True, realtime=True)`
2. `realtime=True` → `drop_last = realtime or intraday` = True → `confirmed_mode = not drop_last` = **False**
3. **盤中閘沒有守在 run_once 上**:`mh = _market_hours()` 只用來決定**睡多久**(`wait = 2 if mh else 30`),而且它自己會印「盤後」——這個迴圈是**設計成盤後繼續跑的**
4. → 看板開著時,**盤後每 30 分鐘就寫一筆 `confirmed=False`**,把當天 cron/`全市場掃描.bat` 寫的確認值蓋掉

實測重現(`attack_gauge.py`,模擬真實日程):
```
14:00 cron(--full)     → confirmed=True
app 盤後每 30 分跑 3 輪 → 檔案 1 筆,最終 confirmed=False mode=intraday
→ 當天的 confirmed 讀數被蓋掉了
```

**為什麼是 MAJOR 而不是 MINOR**:
- 它**不會弄壞掃描**(安全面完全沒問題),但它讓這個改動**達不到唯一的目的**。
- **失敗是靜默的**:沒有任何錯誤訊息,檔案看起來很正常、每天都有一筆。**要等到半年後真的要用時,才會發現 confirmed 幾乎全是 false** —— 而那時已經沒有時光機可以補。這正是這個檔存在的理由(資料無法回填),所以「晚半年才發現」的代價就是**再等半年**。
- 這是本專案第二次出現「靜默失敗、要很久以後才會發現」的同型問題(前一次是 `.env` 載入斷鏈)。

**測試為什麼沒抓到**:`test_intraday_then_confirmed_keeps_confirmed` 只測了**有利的方向**(盤中→收盤,保留 confirmed ✓ 我實測也過),**沒測會壞的反方向**(收盤→盤中)。我實測反方向:
```
收盤(confirmed=True) → 盤中(confirmed=False) → 最終 confirmed=False  ⚠ 確認值被暫定值覆蓋
```

**修法建議(約 3 行,我未代修)**:同日已有 confirmed 記錄時,不讓 unconfirmed 覆蓋 ——
```python
prev = next((o for o in rows if str(o.get("date",""))[:10] == day), None)
if prev and prev.get("confirmed") and not rec["confirmed"]:
    return False          # 已有確認值 → 盤中暫定值不覆蓋
```
並補一個反方向的回歸測試(`test_confirmed_is_not_clobbered_by_intraday`)。

---

## 各攻擊面證據

### ✅ 1 零行為改變(0 刪除 ≠ 沒副作用 —— 我另外查了)

**hook 點位置正確**(`scan.py` run_once 尾段,逐行確認):
```
1404  _atomic_write_json(STATE_FILE, state)      ← 主產物先落地
1405  if not state.get("ok"): return state        ← ok 檢查
1409  append_gauge_history(state)                 ← hook 在兩者之後 ✓
```
→ 就算 append 整個爆掉,`state.json` 早就寫完了。**宣稱屬實。**

**對 `state` 物件零副作用(我實測)**:`deepcopy` 前後 `json.dumps(sort_keys=True)` 全等 → `True`。
特別查了共享參照風險:`rec["components"] = g.get("components")` **持有 state 內部 dict 的參照**,但 `_json_safe`(`scan.py:132-141`)是**純函式**(用 comprehension 建新 dict/list,從不就地改),所以序列化不會回頭污染 `state`。`state.gauge.components` 呼叫前後完全相同。

### ✅ 2 絕不炸掃描(9/9 故障注入 + 突變)

| 注入 | 結果 |
|---|---|
| `_atomic_write_text` 拋 `OSError(28, 磁碟滿)` | 回 False 未拋 ✓ |
| path 指向目錄(不可寫)→ PermissionError | 回 False 未拋 ✓ |
| `state=None` / `{}` / gauge 缺 / temperature=None / ok=False / date 格式壞 | 全部回 False 未拋 ✓ |
| gauge 含不可序列化物件 → `TypeError` | 回 False 未拋 ✓ |

**突變測試**(用 AST 把函式最外層 try/except 拿掉再跑):
```
test_write_failure_never_raises              🔴 轉紅 ✓
test_unreadable_existing_file_never_raises   🔴 轉紅 ✓
test_garbage_state_never_raises              🟢 仍綠 → 見 MINOR-2
test_function_body_has_exception_guard       (我的技術驗不了 —— 見下註)
```
→ 防線**有被行為測試釘住**,不是只靠 source 檢查。

> 註:`test_function_body_has_exception_guard` 用 `inspect.getsource`,對我 AST 合成的模組會噴「source code not available」,那個紅是**我技術的假象**、不算它轉紅。它是 source 檢查測試,對真實檔案有效。**我沒有把這個假紅當成證據。**

### ✅ 3 冪等 + 邊界(除 M1 外全過)

| 情境 | 結果 |
|---|---|
| 同日跑兩次 | 1 筆 ✓ |
| 盤中(false)→ 收盤(true) | 1 筆,保留 **confirmed=True / mode=daily** ✓ |
| **收盤(true)→ 盤中(false)** | **confirmed 被覆蓋成 False** ⚠ **→ M1** |
| 跨日 3 天(亂序寫入) | 3 筆,且**依日期排序** `['07-14','07-15','07-16']` ✓ |
| 壞行混入(`{壞行`、空行) | 壞行丟棄、**好行保留**(07-10/07-11 留著)✓ |

### ✅ 4 原子性 —— **整檔重寫比 append-only 更安全,不是更危險**

**team-lead 的擔憂:「重寫途中被砍會不會丟全部歷史(唯一無法重建的資料)」→ 實測:不會。**

`_atomic_write_text`(`scan.py:120-124`)= 寫 `.tmp` → `os.replace`。**`os.replace` 是原子的**:要嘛完全成功、要嘛原檔完全不動,不存在「寫到一半的主檔」。

我模擬「tmp 寫完、`os.replace` 前被砍」:
```
既有 3 筆 → 注入 KeyboardInterrupt 攔在 os.replace → 被砍後檔案 = 3 筆,內容未變 True ✓ 原檔完好
```

**兩種寫法的風險對照(我的裁決)**:

| | 整檔重寫 + tmp/os.replace(現行) | append-only(`open(path,'a')`) |
|---|---|---|
| 寫入途中被砍 | **原檔完好**(replace 沒發生)✓ | **可能留半行**(torn write)→ 檔案本身損壞 |
| 已存在的壞行 | 讀取時丟棄、自我修復 ✓ | 永久留在檔案裡 |
| 同日重跑 | 天然冪等 ✓ | 會累積重複筆,要另外去重 |
| 效能 | 497B/筆 → 一年 121KB、**五年 606KB**;讀 1250 行+寫 0.6MB = 個位數毫秒,**非問題** | 略快(無意義的差距) |

→ **現行寫法是對的**,而且比 append-only 更能保護這份不可重建的資料。**擔憂不成立。**

殘餘風險見 MINOR-3(檔案若已損壞,壞行會被靜默丟棄 → 建議留 `.bak`)。

### ✅ 5 記錄足以重建 ④(這是整件事的目的)

溫度公式(`scan.py:968-972`):
```python
temperature = (0.30*comp_rsi + 0.25*comp_breadth + 0.15*comp_adr + 0.20*comp_nhnl + 0.10*comp_vol)
if not mkt_long_ok: temperature *= 0.90
temperature = round(temperature, 1)
```
**我用記錄裡存下的欄位獨立重算**:
```
components = {rsi 48.8, breadth 40.9, adr 64.3, nhnl 50.7, vol 8.0}
0.30*48.8 + 0.25*40.9 + 0.15*64.3 + 0.20*50.7 + 0.10*8.0 = 45.4500
index_trend = "UP" → mkt_long_ok = True → 不乘 0.90 → round(45.45,1) = 45.4
官方 temperature = 45.4  → ✓ 逐位一致
```
**關鍵:`mkt_long_ok` 可由記錄推導** —— `scan.py:822` `long_ok = (trend == "UP")`,而 `trend` 有存成 `index_trend`。**所以記錄是足夠的,不是白存。**

### ✅ 6 既有測試
`data_hunter/tests` **335 passed**(基線 320,+15)、`ecommerce/tests` **92 passed** —— 與宣稱一致,零回歸。

---

## MINOR

- **MINOR-1 重建 ④ 的 `mkt_long_ok` 邊界**:`compute_index` 在 0050 資料不足(`len(df)<30`)時回 `(trend=None, long_ok=True)`。未來寫重建程式的人若照直覺寫 `long_ok = (trend=="UP")`,那些日子會**誤乘 0.90**(差 10%)。正確寫法是 `(trend=="UP") or (trend is None)`。**建議直接在記錄裡多存一個 `mkt_long_ok` 欄位**(它已經在 `run_once` 的作用域外了,要從 `build_state` 帶出來;或至少把這條規則寫進 docstring),免得半年後的人推錯——這個檔的價值就在半年後那次使用。
- **MINOR-2 `test_garbage_state_never_raises` 名稱過度承諾**:它餵的五種爛輸入(`None`/`{}`/`{"ok":True}`/`gauge:None`/`date:None`)**全部在 early-return 就被擋掉**,根本走不到會拋例外的程式碼 → 拿掉 try/except 它**照樣綠**。它不是空測(有斷言真實行為),但**它驗的是 early-return、不是它名字說的 exception guard**。guard 本身由另外兩個測試釘住(都轉紅了),所以整體覆蓋沒有洞,只是這個測試名字會誤導後人。
- **MINOR-3 沒有 `.bak`**:整檔重寫雖然原子,但**若檔案本身已經損壞**(例如硬碟壞軌讓多行變垃圾),下次重寫會把壞行**靜默丟棄**並持久化。極端情況(全部行壞掉)= 只剩今天一筆,**而這是唯一無法重建的資料**。建議 `os.replace` 前先把舊檔複製成 `.bak`(成本 ~100KB/次,微不足道),或在丟棄壞行數 > 0 時 print 警告。
- **MINOR-4 產線目錄有未追蹤垃圾檔**:`data_hunter/` 下有 `1`、`5`、`22`、`30`、`dict`、`pd.DataFrame` 等疑似誤建檔案(非本次改動造成,pre-existing),與 `gauge_history.jsonl` 混在同一層。`.gitignore` 或清理一下,免得日後誤判哪個是產物。

---

## 值得肯定

1. **hook 點選得對**:放在 `state.json` 落地 + `ok` 檢查**之後**,並在 docstring 明講理由。這是「動產線」時最關鍵的一個決定,它做對了。
2. **fail-safe 徹底**:9 種故障注入(含磁碟滿、不可寫、不可序列化)全部回 False 不拋,`print` 而不 raise —— 「寧可漏記一天,也不能讓掃描器掛掉」不是口號,是實際擋得住。
3. **原子寫入沿用既有 `_atomic_write_text`**,不自造輪子;壞行丟棄的自我修復設計比 append-only 更能保護這份資料。
4. **`components` 存得夠**:我獨立重算逐位命中 45.4 —— 目的達成(除了 M1 那個誰是「最後一筆」的問題)。
5. **docstring 把「為什麼值得動產線」寫清楚**(沒有時光機、今天不記半年後還是做不出來),並引用了 ④ 的裁決結論。這是負責任的產線改動該有的樣子。
