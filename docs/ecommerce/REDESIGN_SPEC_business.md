# 量化阿森電商 v2 — 商品線 + 定價重規劃規格(商業篇)

> 版本:v2 商業規格 ｜ 撰寫日:2026-07-16 ｜ 定位:把台股數據管線(國際稀缺的護城河)包成可持續變現的數位商品組合,**以訂閱週報為旗艦**。
> 誠信紅線(生死線):寫進任何商品的每一個具體數字都必須綁真實來源欄位(fail-closed),定位「歷史數據體檢,介紹≠推薦」,不喊單、附免責。
> 本規格所有引用的資料檔路徑都經 Test-Path / 實讀樣本驗證存在(見附錄 A 盤點)。

---

## 0. 一句話商品線

**旗艦=「台股全市場週報」訂閱制(NT$99/149 雙層月費,Portaly 訂閱牆)**,由三層一次性 SKU(免費磁鐵→NT$99 tripwire→NT$990~1280 core 數據包)在前面漏斗導流,TradingView 30% 終身返佣為被動輔助收益。一次性 SKU 不再各自為政,每個都標明「爬到訂閱」的階梯關係。

---

## 1. 真實數據資產盤點(規格的地基,全部驗過)

| 資產 | 路徑 | 覆蓋/規模(實測) | 關鍵欄位 | 更新頻率 | v2 用途 |
|------|------|------|------|------|------|
| 全市場自適應回測 | `twdata/adaptive_per_stock.csv` | 1770 檔 | code,name,market,bars,trend_frac,**a_net,a_pf,a_dd,a_tr,a_win,a_rdd**,t_net,t_pf,t_dd,t_tr,t_rdd | 靜態(2026-06-12 跑) | Core 數據包主檔、週報「結構基準」 |
| 多空回測 | `twdata/longshort_per_stock.csv` | 1770 檔 | code,name,market,bh,**l_net,l_pf,l_dd,l_tr,l_rdd,ls_net,ls_pf,ls_dd,ls_tr,ls_rdd,short_trades** | 靜態 | Core 數據包(併入,補做空維度) |
| 回測明細(含風險比) | `twdata/per_stock_results.csv` | 3682 列 | code,ticker,market,name,bars,start,end,net_profit_pct,profit_factor,max_dd_pct,n_trades,win_rate_pct,return_over_maxdd,**sharpe,final_equity** | 靜態 | Core 數據包(補 sharpe/起訖日/最終權益) |
| 全市場強弱掃描 | `quant-service/data_hunter/state.json` | universe 1925、wave_top **1001 檔**、sectors **34**、strong/weak 各 8、signals(long/short)、**track 真實追蹤成績** | gauge(temperature/breadth/adr/nhnl/avg_rsi)、sectors(score/bull_pct/leader/inst_count)、strong/weak(score/rsi/spark/ohlc)、signals.long/short、watch_long、wave_top、chips(foreign_top/trust_top/consec_top/margin_top/retail_exit_top)、track(n_closed/win_rate/avg_r/long_win_rate/short_win_rate/recent) | **每日**(最新 2026-07-16) | **旗艦週報主體** |
| 個股深度體檢事實庫 | `youtube_channel/STUDIO/stock_checkup_facts.json` | by_code **僅 9 檔**、results 104 則、**11 種 fact 類型/檔** | 每則 fact:key/claim/method/**source**/period；類型:long_horizon,annual_extremes,three_way,underwater,halvings,crash(2008/2020/2022),revenue_trend,eps_trend,gross_margin,dividend_history,valuation_position | 每日 cron 累積(慢) | 週報「深度體檢層」、Core 體檢合輯 |
| 估值面 | `twdata/fundamentals/valuation_YYYYMMDD.json` | **1078 檔**/日(近 14 日) | 每 code:pe,dividend_yield,pb | 每日 | 週報「估值位階雷達」 |
| 基本面 | `twdata/fundamentals/stock_XXXX.json` | 135 檔 | eps_q,eps_ttm,eps_yoy,gross_margin,op_margin,rev,rev_yoy,rev_mom,cash_div,stock_div,div_year,ex_date | 按需 | 體檢/週報基本面補充 |
| 法人籌碼(日) | `twdata/chips/YYYY-MM-DD.json` | ~1898 檔/日、**21 個交易日** | foreign_net,trust_net,instinv_net | 每日 | 週報「法人週流向」(跨 5 日加總) |
| 融資券當沖(日) | `twdata/margin/YYYY-MM-DD.json` | ~1845 檔/日、**16 日** | margin_balance,margin_chg,short_balance,short_margin_ratio,day_trade_lots | 每日 | 週報籌碼補充 |
| 分級交易區 | `twdata/zones.json` | daytrade/swing/longterm 各 15 檔 | code,name,industry,price,chg,zscore,setups,metrics,play(entry/stop/target) | 每日 | 免費磁鐵/週報 swing 區 |
| 當沖適格 | `twdata/daytrade_eligibility_*.json` | disposition/attention 清單 | disposition[],attention[] | 每日(檔 <400B) | **免費磁鐵**(不再當付費 SKU) |

### 盤點發現的資料資產風險(重要,直接影響商品可行性)
1. **體檢事實庫只覆蓋 9 檔**(2330/2317/2454/2603/2412/2882/00878/2408/2327),results 104 則。v1 週報以體檢為主體 → 一週餓死。**v2 已改用 state.json(1001 檔)當週報主體,體檢降為加值層。** 長期靠 `stock_checkup_daily` cron 累積覆蓋,覆蓋數是訂閱深度的成長曲線。
2. **回測三檔(adaptive/longshort/per_stock)是 2026-06-12 靜態快照**,非即時。只能當「結構背景/教學基準」,商品文案**不得**宣稱即時或可交易訊號。
3. **chips 僅 21 日、margin 僅 16 日** → 可算「本週法人流向」,但無法做長期籌碼趨勢;需持續累積。
4. **valuation 覆蓋 1078 檔(非全 1925)**,且含 null(如 pe=null),渲染需濾空。
5. **daytrade_eligibility 是每日小快照(<400B)**,賣成靜態商品隔天就過期 → v2 砍為免費磁鐵(每日重生)。
6. **state.json 休市/熔斷時 signals 可能空**(實測 daytrade.json circuit_breaker tripped、signals=[]) → 週報排版需 fail-safe(有就列、無則跳過,不硬湊)。

---

## 2. 旗艦:「台股全市場週報」訂閱規格

### 2.1 產品定義
- **名稱**:量化阿森 台股全市場週報(Carson Quant — Taiwan Whole-Market Weekly)
- **平台**:Portaly 訂閱牆(台灣)、Whop(國際實驗,第二階段)
- **交付**:每週一次完整週報(Email + Telegram 私訊),訂閱者另享每日掃描(daily bonus)
- **引擎**:`quant-service/ecommerce/subscription_report.py`(v2 重寫,見交付規格)
- **雙層**:基礎版 NT$99/月(§2.3 標 ★)、完整版 NT$149/月(全 section + 數據下載 + 深度體檢)

### 2.2 誠信結構(每個 section 都綁來源)
週報引擎**不產生任何新數字**:所有數值一律逐字引用來源檔既有欄位/claim 字串;缺 source/claim/data 的事實由 `_fact_ok` fail-closed 濾除(沿用 v1 `subscription_report._fact_ok`,不自造弱化版)。全市場榜單數字直接來自 state.json 欄位,渲染層只做「取欄位→格式化」不做推論。

### 2.3 週報 Section 規格(7 個固定 + 1 個輪替)

| # | Section | 資料來源檔:欄位 | 產出規則/公式 | 範例列(取自實檔) | 層級 |
|---|---------|------|------|------|------|
| S1 | 市場溫度與體質 | `data_hunter/state.json`:gauge.temperature,label,breadth,adr,nhnl,avg_rsi;index.trend,above_yearline | 直接陳述溫度與體質,不判斷方向。溫度=components 加權(rsi/breadth/adr/nhnl/vol) | 溫度 45.4(中性)｜站上20MA 40.9%｜漲跌比(ADR) 1.8｜60日新高95/新低88｜0050 趨勢 UP 站上年線 | ★基礎 |
| S2 | 板塊輪動熱力 | `state.json`:sectors[](name,avg_chg,bull_pct,score,count,leader,inst_count) | 34 板塊依 score 排序,列 Top5/Bottom5,附完整 34 板塊 CSV(可排序) | 貿易百貨業 score54.0 均漲+1.06% 多方63% 領漲「統領+10.0%」法人買15檔 | ★基礎 |
| S3 | 全市場強弱榜 | `state.json`:wave_top[](1001 檔:code,name,industry,price,chg,rsi,score,st)、strong/weak、ranks.up/down/amount/amplitude | 1001 檔依 score 排序取 Top30/Bottom30 進報告本體,**全 1001 檔附 CSV** 供 Excel 排序篩選(呼應「版面密可排序」) | 馬光-KY(4139)生技 +9.97% RSI87.6 score96.6 UP | ★基礎 |
| S4 | 法人與籌碼週流向 | `twdata/chips/YYYY-MM-DD.json`×本週5日:foreign_net,trust_net,instinv_net ＋ `state.json`:chips(foreign_top/trust_top/**consec_top連買**/retail_exit_top/margin_top) | 對每 code 加總本週 5 個交易日 foreign_net → 排序;外資/投信連買天數取 consec_top | 2887 外資單日買 47478 張;投信連買榜、散戶提前下車榜 | 完整 |
| S5 | 估值位階雷達 | `twdata/fundamentals/valuation_YYYYMMDD.json`:pe,dividend_yield,pb(1078檔) | 濾 null 後,列全市場殖利率 Top20、本淨比 Bottom20、本益比分布(P25/中位/P75);只陳述位置不判斷貴賤 | 1108 殖利率7.19% PE6.88 PB1.04;全市場 PE 中位數(當期算出) | 完整 |
| S6 | 訊號追蹤 · 誠實成績單 | `state.json`:track(n_closed,win_rate,avg_r,avg_ret_pct,long_win_rate,short_win_rate,recent[]) | 直接亮**真實追蹤戰績**(含輸單),不挑不藏。這是誠信紅線的**正面武器**與差異化(對比只曬贏單的 guru) | 已平倉19筆 勝率X% 平均R值X 多方勝率/空方勝率 + 近期逐筆 | ★基礎(招牌) |
| S7 | 本週深度體檢個股 | `youtube_channel/STUDIO/stock_checkup_facts.json`:results(依 computed_at 落在本週窗)、11 種 fact 的 claim/source | 逐字引用體檢 claim(長期含息報酬/套牢期/腰斬/崩盤三段/毛利/股利/估值位階…),每則附 source | 台積電:近20年含息總報酬8728.8%(年化25.1%,最大回撤-46.5%);史上最長套牢10.7年 | 完整(深度) |
| S8 | 結構基準(輪替/月度) | `twdata/adaptive_per_stock.csv`+`longshort_per_stock.csv` | 每月輪替一次教育性基準:全市場 adaptive 淨報酬中位數、正報酬佔比,教「中位數優先」思維(不被最好幾檔騙) | 全市場 1770 檔 adaptive 中位數淨報酬(當期算出)、正報酬佔比 | 完整 |

> **每日 bonus(訂閱者專屬)**:`generate_daily_scan()` 續用,吃 state.json 當日掃描(溫度/板塊/多空訊號/法人),復用 `data_hunter/daily_post.py` 排版 helper。

### 2.4 更新頻率與依賴
- 週報:每週一產出(排程),吃當週最新 state.json + chips 5 日 + valuation 最新日 + 本週新完成體檢。
- 依賴:state.json 每日掃描已在跑(local_cron);chips/valuation cron 已在跑;體檢覆蓋隨 stock_checkup_daily 成長。

---

## 3. 一次性 SKU 重新設計(砍/留/加,全部標明與訂閱的階梯)

> 原則:一次性 SKU 是**漏斗**不是終點。免費磁鐵抓名單 → tripwire 建立付費習慣 → core 服務「不想訂閱只要一份」的買家 → 全部導向訂閱(「這份,但每週更新+真實追蹤」)。

### 階梯 L0 — 免費磁鐵(抓 Email/TG,不收費)
| SKU | 中/英名 | 內容物 | 資料來源 | 目標客群 | 與訂閱關係 |
|-----|---------|--------|----------|----------|-----------|
| M1 | 台股當沖適格清單 / TW Day-Trade Eligibility List | 當日處置股/注意股清單 + 盤前防呆 5 點 | `daytrade_eligibility_*.json`(每日重生,不賣過期) | 當沖/短線新手 | 落地頁換 Email → 週報試閱 |
| M2 | 單檔旗艦體檢報告(台積電) / Single Flagship Health-Check | 2330 的 11 項體檢完整版(PDF) | `stock_checkup_facts.json`:results__2330 | 存股/長線 | 免費嚐鮮 → S7 深度體檢是訂閱常態 |

### 階梯 L1 — Tripwire(建立付費習慣,低價衝動購買)
| SKU | 中/英名 | 內容物 | 資料來源:欄位 | NT$/US$ | 平台 | 與訂閱關係 |
|-----|---------|--------|------|------|------|-----------|
| T1 | 台股定投追蹤模板 / TW DCA Tracker | Excel/CSV 定投模板 + 10年真實對照(All-in vs 定投 vs 0050) | `stock_checkup_facts.json`:checkup_three_way(stock_allin/stock_dca/bench.total_return) | 99 / $5 | 蝦皮·Gumroad | 買家=長線族 → 推 S7/S8 訂閱 |
| T2 | 個股體檢單檔報告(自選權值股) / Single-Stock Health-Check | 任一已覆蓋權值股(9檔可選)的 11 項體檢 PDF | `stock_checkup_facts.json`:results__{code} | 149 / $7 | 蝦皮·Gumroad | 「想每檔都有?訂週報」 |

### 階梯 L2 — Core(一次性高值數據包,服務不想 recurring 的買家)
| SKU | 中/英名 | 內容物 | 資料來源:欄位 | NT$/US$ | 平台 | 與訂閱關係 |
|-----|---------|--------|------|------|------|-----------|
| C1 | 台股全市場回測數據包 / TW Full-Market Backtest Pack | 1770 檔合併 CSV(adaptive+多空+sharpe/起訖/最終權益)+ 摘要 PDF | `adaptive_per_stock.csv`+`longshort_per_stock.csv`+`per_stock_results.csv`(a_net,a_pf,a_dd,a_win / ls_net,short_trades / sharpe,final_equity) | 990 / $35 | Portaly·Gumroad | 一次性;訂閱=「每週更新版」 |
| C2 | 台股權值股體檢合輯 / TW Blue-Chip Health-Check Bundle | 已覆蓋權值股全體檢合輯(隨覆蓋成長)PDF+摘要 | `stock_checkup_facts.json`:全 by_code × 11 fact | 1280 / $39 | Portaly·Gumroad | core 買家 → S7 每週新增體檢 |

### 砍掉的 v1 SKU(說明理由)
- **daytrade_checklist(付費版)** → 砍。賣「當日快照」靜態檔隔天過期,誠信與實用雙輸。改為免費磁鐵 M1(每日重生)。
- **scan_sop(選股SOP純文字)** → 砍。無數據、薄;內容併入訂閱 onboarding 首封信。
- **intl_* 全英版一次性**(v1 每類都做英版)→ 收斂。國際只保留 C1/C2 的英版(Gumroad)+ 訂閱英版(Whop 實驗),不再每個 SKU 都出雙語,降維護成本。

---

## 4. 定價階梯(NT$ / US$ + 定價邏輯)

### 4.1 完整價格表
| 層 | 商品 | NT$ | US$ | 平台 | 定價邏輯 |
|----|------|-----|-----|------|----------|
| L0 磁鐵 | M1 當沖清單 / M2 單檔體檢 | 0 | 0 | 落地頁 | 抓名單,0 摩擦 |
| L1 tripwire | T1 定投模板 | 99 | 5 | 蝦皮/Gumroad | 對齊 Gumroad 數位小物 $5 心理價;NT$99 台灣衝動購買甜蜜點 |
| L1 tripwire | T2 單檔體檢 | 149 | 7 | 蝦皮/Gumroad | 略高於 T1,錨定「一檔=一杯咖啡」 |
| L2 core | C1 全市場回測包 | 990 | 35 | Portaly/Gumroad | 稀缺台股全市場數據,國際 $35 仍遠低於機構數據 |
| L2 core | C2 體檢合輯 | 1280 | 39 | Portaly/Gumroad | 深度>廣度,最高一次性價位 |
| **旗艦訂閱** | **週報 基礎版(★section)** | **99/月** | **9/月** | **Portaly/Whop** | 見下 |
| **旗艦訂閱** | **週報 完整版(全section+下載+深度體檢)** | **149/月** | **15/月** | **Portaly/Whop** | upsell,+50% 拿深度層 |
| 訂閱 年繳 | 完整版年繳 | 1290/年 | 129/年 | Portaly/Whop | ≈NT$107/月,省 28%,鎖 LTV |
| 聯盟 | TradingView 30% 終身 | — | recurring | 內嵌 | 被動,不佔漏斗主線 |

### 4.2 定價邏輯與對照組(查證 2026-07-16)
- **Seeking Alpha Premium ≈ US$24.92/月**(US$299/年);**Seeking Alpha Pro US$200/月**。來源:[about.seekingalpha.com/premium-subscription-price-update](https://about.seekingalpha.com/premium-subscription-price-update)、[seekingalpha.com/subscriptions](https://seekingalpha.com/subscriptions)
- **Substack 財經電子報平均 ≈ US$30.6/月**,平台最低 $5/月,年繳常見 $50。來源:[readless.app/blog/best-paid-substack-newsletters-2026](https://www.readless.app/blog/best-paid-substack-newsletters-2026)、[support.substack.com](https://support.substack.com/hc/en-us/articles/360037607131-How-much-does-Substack-cost)
- **定價策略**:我方訂閱 US$9~15/月 = 對國際同類(SA $25 / Substack $30)**積極低價卡位**,理由=(1)台股全市場數據英文世界稀缺,但(2)頻道現況約 30 訂閱、信任尚未建立,land-grab 定價優先衝訂閱數與口碑。台灣端 NT$99~149/月,相對台灣財經 VIP 服務常見 NT$300~1000/月級距(一般市場認知,非單一 URL)明顯低價,對齊 Carson「先衝規模+誠信建立信任」策略。
- **年繳邏輯**:省 28% 換 12 個月 LTV 鎖定,對抗訂閱早期高流失。

---

## 5. 上線順序(訂閱主柱優先)

| 序 | 動作 | 平台 | 依賴 | 對外紅線 |
|----|------|------|------|----------|
| 1 | 週報引擎 v2 重寫 + 產一份**公開免費樣本週報**(證明價值) | 本機→落地頁 | state.json(已跑)、subscription_report v2 | 內容審(誠信驗證)後才公開 |
| 2 | L0 免費磁鐵 M1/M2 上落地頁 + Email/TG 抓名單 | 落地頁 + tg_magnet | 漏斗頁重做(Phase 2c) | opt-in 名單 |
| 3 | Portaly 訂閱牆設定(基礎/完整/年繳三檔)+ webhook v2 驗簽 + send_report 交付串接 | Portaly | webhook v2(Phase 2d)、PING/簽章欄位校準 | **動錢/新對外管道→先問 Carson** |
| 4 | L1 tripwire T1/T2 上蝦皮+Gumroad | 蝦皮·Gumroad | product_factory v2、Gumroad PING_TOKEN | 上架前誠信驗證 |
| 5 | L2 core C1/C2 上 Portaly+Gumroad | Portaly·Gumroad | product_factory v2 | 同上 |
| 6 | Whop 國際訂閱實驗(英版週報) | Whop | 訂閱引擎穩定後 | 新對外管道→先問 Carson |

> 關鍵路徑:**序 1→3 是旗艦主柱**。一次性 SKU(序 4/5)可與訂閱並行,但資源優先給訂閱。所有真實對外發送(送信/上架/收款)一律先過 fresh-context 誠信驗證(Phase 3),有授權也不免驗。

---

## 6. v1 哪裡不夠好 → v2 怎麼改(對照)

1. **旗艦模糊**:v1 訂閱與一次性平等對待、SKU 各自為政 → **v2 明確以訂閱週報為旗艦**,所有一次性 SKU 重新定位成漏斗階梯(磁鐵→tripwire→core→訂閱),每個標明爬升關係。
2. **週報餓死**:v1 週報只吃體檢事實庫(僅覆蓋 9 檔)→ 一週沒幾條 → **v2 週報主體改吃 state.json 全市場掃描(1001 檔 wave_top+34 板塊+強弱榜+法人籌碼+真實訊號追蹤)**,體檢降為深度加值層,徹底解決覆蓋不足。
3. **賣過期數據**:v1 把 daytrade_checklist「當日快照」賣成靜態商品(隔天過期)→ **v2 砍為免費磁鐵**(每日重生),不賣會壞掉的東西。
4. **沒有誠實武器**:v1 無「成績單」→ **v2 把 data_hunter track 的真實追蹤勝率(含輸單)做成固定招牌 section**——把誠信紅線從「防捏造的守門」升級成「主動亮真實戰績」的差異化賣點(對比只曬贏單的 guru)。
5. **版面不密不可排序**:v1 是散落 md → **v2 要求全市場榜單一律附完整 CSV**(1001 檔強弱、34 板塊可在 Excel/Sheets 排序篩選),報告本體給 Top/Bottom+分布,呼應 Carson「準則更專業+範圍更廣+版面更密可排序」品味。
6. **數據包單薄**:v1 fullmarket 只用單一 adaptive csv → **v2 core C1 合併 adaptive+多空+per_stock 三檔**,補做空維度與 sharpe/起訖日/最終權益。
7. **薄 SKU 佔位**:v1 scan_sop 純文字無數據 → **砍掉**,併入訂閱 onboarding。
8. **無 recurring 主柱**:v1 全一次性 → **v2 建雙層月訂閱(NT$99/149)+ 年繳鎖 LTV**,才是可持續變現。

---

## 附錄 A:路徑存在性驗證(全部實測)
所有 §1 表列路徑均以 `ls`/Glob/`python json.load`/`head` 於 2026-07-16 實讀樣本確認存在且欄位如表所述。體檢庫 by_code 實測 9 檔(2330,2317,2454,2603,2412,2882,00878,2408,2327);valuation 最新檔 `valuation_20260716.json` 1078 檔;state.json wave_top 1001 檔、sectors 34;回測三檔各 1770/1770/3682 列。

## 附錄 B:對外/動錢紅線提醒
訂閱牆收款、名單發送、平台上架皆屬「對外發布/動錢」紅線 → 執行前先問 Carson(新管道/動錢)且一律過 fresh-context 誠信驗證。product_factory v2 沿用 fail-closed 溯源守門,任何查無來源數字 → 該 SKU 整個中止不出檔。
