# VERIFY_REPORT_phase3a — 先行驗證(找碴式)

> 驗證人:funnel-face(未參與 A/B 兩元件實作,fresh-context)｜日期:2026-07-16
> 立場:**試圖證明它們做錯**。方法:獨立 Python 重算(不 import 週報引擎)+ webhook 實彈(in-process ASGI HTTP,假密鑰+tmp STUDIO,零外網、不碰真 .env/正式檔)。
> 重現腳本:`scratchpad/recompute_weekly.py`(A)、`scratchpad/webhook_fire.py`(B)。

## 總結
| 區塊 | 檢查數 | PASS | FAIL/發現 | 紅線結論 |
|---|---|---|---|---|
| A 週報誠信溯源 | 33 重算 + 71 S7 逐字 | 33/33 重算全對、71/71 數字⊆來源 | 3 個發現(皆非造假) | **無造假,產品數字全部忠於來源** |
| B 金流 webhook 實彈 | 34 | 32 行為正確(1 為我測試斷言誤判) | 1 個真發現(B1) | **簽章/去重/退款/名冊全對,1 個 500 robustness 缺口** |

**最重的問題排序**:B1(MEDIUM,500 裸奔會誘發平台 retry storm)> A1(MEDIUM,溯源檔只覆蓋 S7)> A2(LOW-MED,溯源紀錄被截斷)> A3(LOW)。**沒有任何紅線級造假/漏帳/偽造放行**。

---

## A. 旗艦週報 v2 — 誠信溯源重算

### A-PASS(獨立重算,容差 abs 0.25 / rel 0.5%,全部命中)
- `[PASS]` S1 溫度 45.4 / 站上20MA 40.9% / ADR 1.8 / avgRSI 48.8 / 新高95 新低88 / 漲1060 跌588 平277 / 0050 106.4 +0.09% — 直讀 state.json.gauge+index,逐欄一致。
- `[PASS]` S2 Top1 板塊(依 score 降序)貿易百貨業 score54.0 均漲1.06% 多方63% count19 inst15;Top5 score [54.0,53.6,51.9,51.1,49.9] 排序正確。
- `[PASS]` S3 全市場強弱榜 Top1(wave_top 依 score 降序)2634 score94.0 chg1.79 rsi78.9;Top5 [2634,2910,3532,4541,6505] 一致。
- `[PASS]` S4 法人5日加總:視窗=**最後5個 chips 檔 2026-07-08,09,13,14,15**(標示 07-08~07-15);台塑化2618 foreign_net 5日=+223,296、台泥1101=-45,307,逐檔重算命中;賣超 Top3 [1314,1303,1102] 一致。
- `[PASS]` S5 估值分布:非空 PE(**831 檔,PE>0**)P25=14.25 / 中位=20.70 / P75=41.66,五種 percentile method 全在容差內(呈現 14.2/20.7/41.7);殖利率 Top5 [2442 13.99%…] 一致。
- `[PASS]` S8 結構基準:**全樣本 1770 檔未過濾**,a_net 中位=6.165(呈現 6.2)、正報酬佔比=53.107%(呈現 53.1%);Top5 by a_net [5386,2383,2028,6223,2486] 一致。
- `[PASS]` S6 誠實成績單(招牌,重點攻擊面):n_closed=19、win_rate 0.158→15.8%、avg_r -0.61、avg_ret -7.77%、long 16.7%、short 15.4%、n_open 278 — 全部與 state.json.track 逐欄一致。
- `[PASS]` S7 逐字:71 筆溯源紀錄的數字**全部⊆ 來源 claim 字串**(2327 國巨 +21051.3% 這種 >10000% 怪物數也命中,靠 _pool_fg tokenizer);PDF/HTML 渲染的是**完整**來源 claim。
- `[PASS]` Tier 分層(產品面):basic 只渲染 S1/S2/S3/S6、full 渲染全 8 段;**full-only 深度內容(S4/S5/S7/S8)不會外洩給 basic 買家**(basic.html 章節標頭僅 S1,S2,S3,S6;2330 8728.8% 等 S7 內容 basic 無)。

### A-發現(皆非造假,屬溯源「檔案」品質缺口)
- `[FAIL:MEDIUM]` **A1 溯源檔只覆蓋 S7**:`weekly_..._provenance.json` 71 筆**全是 S7**;S1–S6、S8 呈現的全市場數字(溫度、榜單、5日籌碼、percentile、中位數、真實戰績)在溯源檔裡**零紀錄**。fail-closed gate 仍對全段跑(數字不在 in-memory pool → 降級,故憑空造假擋得下),但**持久化的稽核檔只覆蓋 1/8 段** → 規格「每個綁定數字→來源存證」只對 S7 兌現,外部稽核者無法只憑該檔驗 7/8 段。
  - 重現:`python -c "import json,collections;p=json.load(open('quant-service/output/ecommerce_ready/weekly_v2/weekly_2026-07-16_full_provenance.json',encoding='utf-8'));print(collections.Counter(r['section'] for r in p['records']))"` → `Counter({'S7': 71})`。
- `[FAIL:LOW-MED]` **A2 溯源紀錄被截斷**:`weekly_report_v2.py:564` 存 `"text": txt[:60]`,**51/71 筆被切斷**,部分斷在數字中間(如 `卡瑪比率 0.`、`…9.0 年（3`)。**產品 PDF 渲染的是完整忠實文字**(3292/0.99 都在),只有稽核用 JSON 的尾巴壞掉 → 稽核檔對長 claim 具誤導性(看起來像壞掉的數字)。
  - 重現:上面同檔取 `field=checkup_long_horizon__00878` 的 `text` → 尾為 `卡瑪比率 0.`;來源 claim 尾為 `卡瑪比率 0.99）`。
- `[FAIL:LOW]` **A3 value 全 null + 溯源檔非 tier-aware**:71 筆 `value` 全 `null`(從不存結構化數值,溯源靠文字/pool 比對而非「數值綁欄位」);且 basic 與 full 的溯源檔內容相同(都含 71 筆 S7),basic 實際不渲染 S7 → 稽核檔描述了未交付給 basic 的段落。

> **可疑但已查證忠實(即使 PASS,列出供覆核)**
> 1. **S6 win_rate 15.8%(招牌)**:忠實引用 state.json.track,但該檔 `recent[]` 278 筆**全是 open**,19 筆已平倉的逐筆明細不在檔內 → 這個誠信招牌數字**無法從 state.json 自身重新導出**,可信度完全繫於 data_hunter 的 track 聚合(週報引擎無責,但這是最該盯的單點)。
> 2. **S4 五日視窗排除了 07-07**:chips 目錄有 07-07 檔卻被 last-5 切掉(取 07-08~07-15)。標示「本週5交易日」誠實,但讀者可能預期含 07-07;屬邊界標籤細節。
> 3. **2327 國巨 +21051.3%**:>10000% 靠 `_pool_fg` 特例入池才過 gate,視覺驚人;已驗證數字確實來自來源 claim,忠實無誤。

---

## B. 金流 webhook v2 — 實彈

環境:`TestClient(build_app(Settings(tmp路徑, 假密鑰, 假 adder/sender/ntfy, dry_run=False)))`,in-process ASGI 真 HTTP 往返,background task 有跑,零外網。

### B-PASS(32 項行為正確)
- `[PASS]` 合法簽章 → 200:Gumroad(token via query)/Portaly(HMAC)/Whop(Standard Webhooks)/LemonSqueezy(HMAC hex)四平台全 accepted。
- `[PASS]` 真寫入:sales_ledger 記帳、customers_book 顧客簿、subscribers_book 名冊(Portaly 訂閱 status=active、tier 依 149 TWD 正確歸 `full`)、交付信送出(fake sender 收到 4 封)、revenue 分幣別(product/TWD 990)。
- `[PASS]` 偽造簽章 → 401:四平台全擋(Portaly/LS 錯 HMAC、Gumroad 錯 token、Whop 錯 v1 sig);**偽造事件未寫入**帳簿。
- `[PASS]` 缺密鑰 → 503:清掉 env 重建 app,Portaly/Gumroad/LS 全回 503(拒絕「無法驗證來源」)。
- `[PASS]` 重放去重(冪等):同一 sale_id ×3 → **ledger 僅 1 筆、revenue.record 僅呼叫 1 次**(重放在 `append_sale` 回 False 時提前 return,不進記帳/交付)。
- `[PASS]` 退款:Portaly refund → **ledger 負值沖銷 -149、revenue 負值 -149、名冊 status=cancelled**;退款重放 → 僅 1 筆沖銷(`:refund` 專屬去重鍵)。
- `[PASS]` 攻擊面:Gumroad token 走 query 與 X-Ping-Token header 皆可;hex 簽章大寫+前後空白仍過(hex 大小寫不敏感、strip,正確);Gumroad token 尾空白 strip 後過、**大小寫錯誤被擋**(token 精確比對)。
- `[PASS]` 超大 payload(200KB)→ 200 正常處理,未 500;整批畸形轟炸後 `/health` 仍 200,**服務進程存活**。

### B-發現
- `[FAIL:MEDIUM]` **B1 畸形但簽章合法的 JSON → HTTP 500 裸奔**:`app.py:68/78/86`(LemonSqueezy/Whop/Portaly)在驗簽通過後 `json.loads(body)` 無 try 包覆;傳空 body 或壞 JSON 且**簽章合法**時 → `JSONDecodeError` 未捕捉 → 回 **500**(非 4xx)。Gumroad 路徑免疫(`parse_qs` 不會炸)。
  - 觸發前提:需**持有 webhook 密鑰**才簽得出合法簽章 → 非無密鑰攻擊者可打(realistic 觸發=平台送出截斷/空 body 邊界事件)。但 5xx 會讓 webhook 平台**持續重試(retry storm)**,而 4xx 不會 → 生產上一個畸形投遞可能變重試風暴。服務進程不死(health 仍 200),屬單請求未處理例外。
  - 重現:`scratchpad/webhook_fire.py` §6 —— 用 `PORTALY_SECRET` 對 `b"{not json"` 簽名 POST /sale-ping/portaly → 500;對 `b""` 簽名 POST /sale-ping/lemonsqueezy → 500。
  - 建議修:三處 `json.loads` 包 try → `raise HTTPException(400, "malformed JSON")`(對齊既有 fail-closed 風格),讓平台收 4xx 不重試。

> 註:B 測試以 TestClient(in-process 真 ASGI HTTP)代替 uvicorn 綁 port——完整跑過路由→驗簽→正規化→業務→原子寫檔全鏈,且可證明零外網、未碰真 .env/正式 STUDIO(全指 tmp)。§4「replay revenue recorded once」在腳本首跑顯示 FAIL,經查為我斷言把 note 截在 [:30] 藏掉 order id 所致;獨立複跑(3 次重放 → revenue.record 僅 1 次)證實冪等正確,已於報告計為 PASS。
