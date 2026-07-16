# VERIFY_REPORT_c9538e6 — 找碴驗證 team-lead 的修復 commit

> 驗證人:verifier-sku2(fresh-context,未參與 c9538e6 實作)｜日期:2026-07-16
> 對象:`git show c9538e6`(修 phase3a 抓到的 B1 / A1 / A2 / A3)
> 立場:**試圖證明這個修法錯了或不夠**。重算部分**零 import 引擎**(自寫 Python 直讀 state.json / chips / valuation / csv / checkup facts);gate 鬆緊與 B1 邊界則必須 import 受測引擎本身(那正是待測物)。
> 唯讀:未改任何程式碼/產物、未打外部網路、未動 .env(未讀任何密鑰值)。
> 重現腳本:`scratchpad/verify_c9538e6.py`、`verify_c9538e6b.py`、`gate_stress.py`、`coverage_gap.py`、`b1_edge.py`

## 總結

| 攻擊面 | 結論 |
|---|---|
| 存證是不是又一個空殼 | **PASS** — 64 筆獨立重算 **0 FAIL**;`source` 標籤**逐一可解析** |
| 覆蓋率是不是灌水 | **PASS** — **零**完全重複記錄;PDF 績效數字覆蓋率 **100%** |
| **gate 有沒有被弄鬆** | **PASS** — 8/8 段仍擋下憑空數字;`_bind` 相對舊 `_pool` 只多綁 1 個真來源值、**零漏綁** |
| A2 是不是真的沒截斷 | **PASS** — S7 71/71 逐字相同,0 筆斷在數字中間 |
| A3 tier-aware 反向漏洞 | **PASS** — 零洩漏,且 basic **沒被少記** |
| **B1 的 400 有沒有副作用** | **FAIL** — 正常流未受影響,但**「合法 JSON 但非物件」三平台仍 500** |

**0 BLOCKER / 1 MAJOR / 2 MINOR。A1・A2・A3 三個修法我打不破——存證是真的,不是第二個空殼。B1 只修了一半。**

> **併發雜訊聲明(兩處,皆已排除干擾)**
> 1. `pytest quant-service/ecommerce/tests` 現有 5 個 FAIL,全在 `test_product_factory_v2.py`,根因是 **fixer-sku 正在改的 `product_factory_v2.py:969` NameError**,該檔**不在 c9538e6 的改動清單內**(`git show c9538e6 --stat | grep -c product_factory_v2` → 0)。**c9538e6 自己的範圍:66 passed**(`test_weekly_report_v2.py` + `webhook/tests`),與 commit message 宣稱一致。
> 2. `quant-service/webhook/app.py` 目前有**未提交改動,是 fixer-env 的**(加 `env_report_lines()` 啟動摘要,治我 runbook 報告的 B1 靜默失敗),非本驗證者所為。**關鍵確認:`git diff c9538e6 -- webhook/app.py | grep -c "_json_or_400"` → 0**,即受測的 `_json_or_400` 自 c9538e6 起未被任何人改動 → 下方 M1 的實彈結果**確實是對 c9538e6 版本的檢驗**,未被併發改動污染。

---

## MAJOR

### M1 B1 只修一半:「合法 JSON 但不是物件」→ 三平台仍 500(retry storm 未除)

`_json_or_400`(`app.py:29-40`)只捕 `JSONDecodeError` / `UnicodeDecodeError`。**合法 JSON 但不是 dict 時,它原樣回傳**,parser 立刻對它 `.get()` → `AttributeError` **未捕捉** → **500**。

實彈(in-process ASGI,假密鑰 + tmp 路徑,零外網;`scratchpad/b1_edge.py`):

| 案例 | portaly | lemonsqueezy | whop |
|---|---|---|---|
| 壞 JSON `{not json`(B1 目標) | 400 ✓ | 400 ✓ | 400 ✓ |
| 空 body(B1 目標) | 400 ✓ | 400 ✓ | 400 ✓ |
| **合法 JSON 但是陣列** `[1,2,3]` | **500** | **500** | **500** |
| **合法 JSON 但是純字串** `"hello"` | **500** | **500** | **500** |
| **合法 JSON 但是數字** `123` | **500** | **500** | **500** |
| **合法 JSON 但是 null** `null` | **500** | **500** | **500** |
| 合法物件但欄位全缺 `{}` | 422 ✓ | 200 ✓ | 200 ✓ |
| 合法物件 `{"data":"oops"}` | 422 ✓ | **500** | **500** |
| 合法物件 `{"data":[1,2]}` | 422 ✓ | **500** | **500** |

根因逐一確認:
```
parse_portaly([1,2,3])      → AttributeError: 'list' object has no attribute 'get'
parse_lemonsqueezy("hello") → AttributeError: 'str' object has no attribute 'get'
parse_whop(None, 'wh')      → AttributeError: 'NoneType' object has no attribute 'get'
```
`parse_portaly` 之所以能擋掉 `{"data":"oops"}`,是因為它有 `isinstance(payload.get("data"), dict)` 這道 guard(`normalize.py:168`);LS / Whop 沒有。

**為什麼是 MAJOR 而不是 MINOR**:這**正是 B1 要根治的那個失效模式**——5xx 讓平台無限重投。commit message 寫「壞 JSON 一律 400 不是 500」「平台無限重投同一顆壞蛋」,但對整整一類 payload 沒兌現。`null` 特別現實(平台序列化 bug / 空事件送 `null` body 都會踩到)。觸發前提與原 B1 相同(需持有合法簽章 → 非無密鑰攻擊者可打,realistic 觸發=平台送邊界事件),故沿用原 B1 的嚴重度層級。

**修法建議(交給實作者,我未代修)**:`_json_or_400` 收尾加型別檢查——
```python
obj = json.loads(body.decode("utf-8"))
if not isinstance(obj, dict):
    raise HTTPException(400, "payload must be a JSON object")
return obj
```
一行治全部三個平台,且與既有 fail-closed 風格一致。建議一併補回歸測試(退回修復要會紅)。

---

## MINOR

- **N1 basic PDF 的免責區塊提及 basic 沒交付的段**:basic 版免責寫「S8 結構基準為 2026-06-12 靜態回測快照…估值段(**S5/S7**)只陳述數據位置」,但 basic 買家收不到 S5/S7/S8。屬**靜態 boilerplate**,是過度揭露而非短少(不影響誠信),但對 basic 買家略困惑。已確認**非內容洩漏**:basic PDF 的章節標頭只有 S1/S2/S3/S6,且 S7 專屬數字 `8728.8` 在 basic PDF **不存在**。
- **N2 封面統計未經 `_bind` 綁定**:封面「強弱榜覆蓋 **1001** 檔」「板塊 **34** 類」是資料衍生的顯示數字,但沒進存證(非績效數字,gate 本就不管,不影響 fail-closed)。若要把「每個資料衍生的顯示數字都可回查」做滿,這兩個是殘餘。

---

## 各攻擊面證據

### ✅ 存證不是空殼:64 筆獨立重算,0 FAIL(涵蓋全 8 段)

**零 import 引擎**,自己讀來源檔重算,逐筆對 `value`:

| 段 | 來源 | 重算筆數 | 結果 |
|---|---|---|---|
| S1 | `state.json:gauge+index` | 11 | 11/11 命中(溫度 45.4 / breadth 40.9 / adr 1.8 / nh 95 / nl 88 / avg_rsi 48.8 / adv 1060 / dec 588 / flat 277 / index_chg 0.09 / index_price 106.4) |
| S2 | `state.json:sectors[*]` | 7 | 7/7(貿易百貨業 avg_chg 1.06 / bull_pct 63 / score 54 / count 19 / inst_count 15…) |
| S3 | `state.json:wave_top[*]` | 8 | 8/8(2634 chg 1.79・rsi 78.9・score 94・price 68.3;2910…) |
| S4 | `twdata/chips[*]` 本週日檔加總 | 6 | 6/6(2618 foreign_net_5d **223,296**;5880 44,465;2892 43,887…) |
| S5 | `valuation_20260716.json` | 10 | 10/10(pe_p25 14.24 / median 20.7 / p75 41.67 / sample_n 831;2442 殖利率 13.99・pe 3.68・pb 0.83…) |
| S6 | `state.json:track`(招牌) | 7 | 7/7(n_closed 19 / win_rate 15.8% / long 16.7% / short 15.4% / avg_r -0.61 / avg_ret -7.77% / n_open 278) |
| S7 | `stock_checkup_facts.json` | 71 | 71/71 逐字相同(見 A2) |
| S8 | `adaptive_per_stock.csv` | 14 | 14/14(sample_n 1770 / median 6.165 / n_pos 940 / pct 53.10734…;5386 a_net 10027.73…) |

**`source` 不是亂標**:我用 `source` 字串裡的鍵(`sectors[貿易百貨業]`、`wave_top[2634]`、`chips[2618]`、`valuation:data[2442]`、`adaptive_per_stock.csv[5386]`)**回頭去來源檔查,全部找得到且數值相符**——沒有任何一筆 source 指向不存在的位置。
S4 的視窗我獨立取「最後 5 個 chips 檔」= 2026-07-08/09/13/14/15,與存證 source 標的「本週日檔加總」一致。

### ✅ 覆蓋率不是灌水

- **完全重複的 `(section, field, value, source)` 組合 = 0 筆** → 沒有靠重複記同一數字撐筆數。
- 283 筆有 `value`(commit 宣稱 283 ✓),261 個相異值;22 個重複是**跨欄位的合法碰撞**(如 9.0 同時是不同欄位的值),非灌水。
- 每段筆數與該段實際內容量成比例,非「只記好記的」:S1 11 / S2 60(12 板塊 × 5 欄) / S3 120(30 檔 × 4 欄) / S4 32 / S5 49 / S6 7 / S7 71 / S8 14。

**A1 真正的衡量 —— PDF 有呈現但沒進存證的數字還剩多少:**

| 版本 | PDF 相異**績效%宣稱** | 未進存證 | PDF 全部相異數字 | 未進存證 |
|---|---|---|---|---|
| full | 229 | **0(100% 覆蓋)** | 580 | 80 |
| basic | 59 | **0(100% 覆蓋)** | 230 | 39 |

那 80 / 39 個「未覆蓋」我**逐一查了 PDF 語境**,結論:**零個是績效數字**——
- **約 9 成是股票代號**(1101 台泥 / 1102 亞泥 / 1301 台塑 / 2330 台積電 / 5386 青雲 / 6505 台塑化 …)
- 其餘:定價 99 / 149 / 1290(來自 `config.py`,非資料來源)、年份 2026、頁碼、覆蓋檔數 1001、板塊數 34、`00878` 拆出的 878
- **代號不入池是正確設計**(綁進去會把池撐大、反而弱化守門),故此殘餘不是缺陷。

> 誠實補充:我第一版抽取器把千分位逗號的 `+223,296` 切成 `223` 和 `296`,誤報 97 個未覆蓋。改成 comma-aware 後降到 80,且全為上述非績效 token。**我沒有把自己的抽取器 bug 當成對方的缺陷報出去。**

### ✅ gate 沒有被弄鬆(最重要的一面)

**攻擊**:對 8 段各自注入「憑空手打的績效數字」,看 fail-closed 擋不擋(手法對齊既有 `test_provenance_rejects_unsourced_number`):

```
S1 87.3% → ✓ 被擋   S2 87.3% → ✓ 被擋   S3 87.3% → ✓ 被擋   S4 87.3% → ✓ 被擋
S5 87.3% → ✓ 被擋   S6 87.3% → ✓ 被擋   S7 45.7% → ✓ 被擋   S8 87.3% → ✓ 被擋
結論:8/8 段擋下憑空數字,0/8 段放行
```

**`_bind` vs 舊 `_pool` A/B 對照(S1,同一份真實資料)**:
```
舊 _pool 池大小 = 11 / 新 _bind 池大小 = 12
新增入池的值:[106.4]      ← 唯一新增
少掉的值:[]               ← 零漏綁
```
唯一新增的 `106.4` = `state.json:index.price`,是**真實來源欄位**,且**本來就顯示在 PDF 上**(「0050 106.4 +0.09%」)。原本「顯示了卻沒綁」,c9538e6 把它綁上 → 這是**修正,不是放水**。

各段池仍然很小(S1=12 / S6=9 / S8=28),**鑑別力沒有被稀釋**——這正是 v1 刻意「空池起步」的設計意圖,`_bind` 完整保住了。S7=819 較大是其「逐字引用 + `_walk_numbers` 全走」的既有設計所致,非本次引入。

### ✅ A2 真的沒截斷

- S7 71 筆存證 `text` 與來源 `claim/summary` **逐字相同:71/71**
- text 長度 min=37 / **max=172** / 平均 87 → 遠超 v1 的 60 字上限,截斷確已移除
- **0 筆**結尾斷在數字中間(v1 特徵如「卡瑪比率 0.」已消失)

> 誠實補充:我的啟發式先報「5 筆長度剛好=60 → 仍在截斷」。逐筆查證後**推翻自己**:那 5 筆全是 `checkup_annual_extremes__*`(同一模板,天然就 60 字),與來源逐字相同。**這是我的誤報,不是缺陷。**

### ✅ A3 tier-aware 兩個方向都對

- basic 存證 `sections_covered` = `['S1','S2','S3','S6']` == `CFG.SECTION_TIERS` 的 basic 段 ✓
- basic 存證裡的 **full-only 記錄 = 0 筆**(零洩漏)✓
- **反向(team-lead 特別要求查的漏洞)**:basic 各段筆數 **== full 同段筆數**(S1 11 / S2 60 / S3 120 / S6 7)→ **basic 該有的一筆都沒少** ✓
- basic PDF 的 59 個績效%宣稱 **全部在 basic 存證檔內**(未覆蓋 0)✓
- 交付面複驗:basic PDF **不含** S4 內容、S7 專屬數字 `8728.8` **不存在** ✓(S5/S7/S8 字樣只出現在靜態免責句 → 見 N1)

### ✅ B1 正常事件流未被 400 誤傷
`{}`(合法物件、欄位全缺)→ portaly **422**(缺 email 無法交付,既有設計)、LS / Whop **200**(事件名不在對應表 → IGNORED)。皆非 400 誤判,正常流未受影響。合法簽章 + 正常 payload 的四平台路徑在 `webhook/tests` 46 passed 中亦全綠。

---

## 值得肯定

1. **A1/A2/A3 我打不破**:64 筆獨立重算 0 FAIL、source 逐一可解析、零重複灌水、績效數字 100% 覆蓋、A2 逐字無損、A3 雙向皆對。**這次的存證是真的,不是 SKU 那批 `records=[]` 的同型空殼**——我帶著「你可能有同型瑕疵」的假設來查,查不到。
2. **最該擔心的事沒發生**:為了讓存證好看而放鬆守門 —— **沒有**。8/8 段仍擋憑空數字,池只多了一個真來源值、零漏綁。
3. **新增的 3 個測試釘得住**:`test_all_sections_write_provenance_records`(每段都要有 source+field)、`test_provenance_records_carry_structured_values`(存證數值須等同來源欄位值)、`test_s7_provenance_text_not_truncated`(逐字比對)——都是**會因退化而變紅**的真回歸,不是套套邏輯。
4. commit message 的每個量化宣稱(71→364、283 有值、basic 198、零 full-only 洩漏、66 tests)**經查全部屬實**,無灌水。
