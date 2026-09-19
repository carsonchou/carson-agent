# Phase 3c 交叉驗證報告 — 漏斗門面(Task #5 / funnel-face 交付)

> 驗證者:spec-business(未參與 Task #5,獨立交叉驗)｜日期:2026-07-16
> 模式:找碴式(試圖證明做錯)｜唯讀+本機,未打外部網路、未動 .env
> 驗證對象:`make_landing.py` + `assets/landing/index.html`、`listing_templates.py` + 9 份 listings_copy、`tg_magnet.py` diff、5 張 pinterest pin

## 總評:PASS(5/5 檢查面通過)｜0 BLOCKER｜0 MAJOR｜2 MINOR

funnel-face 的交付誠信與一致性紮實:定價全對齊 config、數字宣稱全部對得上實際成品/資料、
零誇大詞、兩套 listing 不打架、tg 磁鐵讀真檔、RWD 不爆版。只有 2 個 MINOR(都非阻斷,建議上線前順手修)。

---

## 檢查面逐項

### 檢查 1 — 再生穩定性(WYSIWYG / drift):PASS
- 親跑 `python make_landing.py` 重產 index.html → **MD5 前後完全相同**(`603a43aa159ad707819961bcb174de07`),`diff` 空 → 生成器與產物真的 WYSIWYG、無 drift。
- **placeholder 數 = 4**(grep `PLACEHOLDER`),與宣稱一致。
- **零商業真連結**:grep portaly/gumroad/shopee/whop/lemonsqueezy 的 http 連結 = 0;商品按鈕走 placeholder。頁面上的真連結只有既有聯盟/社群(Pionex/Perplexity/TradingView/YouTube/tg bot),非本次金流管道,符合預期。
- 註:index.html 為 funnel-face 的工作區變更;我的重產與其位元組相同,故**不需 git checkout 還原**(還原反而會誤revert funnel-face 的變更)。

### 檢查 2 — 文案宣稱 vs 成品一致 + 兩套 listing 打架:PASS(1 MINOR)
**定價**(9 份 listings_copy vs `ecommerce/config.py`):全對齊,零矛盾。
| SKU | copy 標價 | config | |
|---|---|---|---|
| T1 | NT$99 / US$5 | 99 / 5 | ✓ |
| T2 | NT$149 / US$7 | 149 / 7 | ✓ |
| C1 | NT$990 / US$35 | 990 / 35 | ✓ |
| C2 | NT$1280 / US$39 | 1280 / 39 | ✓ |
| 訂閱 | NT$99/149/1290 | basic99/full149/annual1290 | ✓ |

**數量宣稱 vs 真實資料/成品**:
- C1「1770 檔」→ xlsx 實際 1770 資料列(親開 openpyxl 驗)✓
- 訂閱「每週掃 1900+ 檔」→ state.json universe=1925 ✓;「約 1000 檔強弱榜」→ wave_top=1001 ✓;「估值約 1078 檔」→ 最新 valuation=1078(精準)✓;「34 板塊」→ sectors=34 ✓
- C2/T2「20 年」、T1「10 年」→ 對齊體檢事實 long_horizon 20 年 / three_way 10 年 ✓

**兩套 listing 打架檢查**(funnel-face `listings_copy/*.md` vs 我 product_factory 產的 `*/listing.json`,同 SKU):
- **定價完全相同**(兩者都讀同一份 config)→ 無矛盾。
- 名稱/內容物描述用詞不同但**指向同一商品、同一規格**(1770檔/含息還原20年/多空+Sharpe/估值位階…)→ 買家看兩版不會覺得被騙。
- **結論:兩套 listing 不打架。**
- **[MINOR-1]** C2 copy 寫「EPS 趨勢圖端點為真實年度值,中間為示意序列並已標注」,但實際 product_factory_v2 的 EPS/營收/毛利 sparkline 用的是**完整真實年度序列**(非只端點),此 caveat 是沿用產品篇 mockup 的舊限制、與實際成品不符。方向是「少講」(under-promise)不構成欺騙,但建議修正措辭以精準對應成品。

### 檢查 3 — 誇大詞與誠信:PASS
- 掃 15 個誇大詞(穩賺/保證/翻倍/財富自由/年化必達…)於 9 份 copy + landing:唯一命中「保證」**全部是「不保證收益 / 歷史數據非未來保證」的否定用法**(逐一看 context 確認),非誇大,反而是誠信揭露。
- 「介紹 ≠ 推薦」+ 免責:9 份中文 copy + landing **每處都在**;4 份英文 copy 有等義「Description ≠ recommendation / not investment advice / not a recommendation」。
- pin 圖(親看旗艦+數據兩張):數字皆有據(34 板塊、1770 檔、NT$99–149、NT$990 全對),旗艦 pin 帶「介紹 ≠ 推薦」、數據 pin 帶「歷史快照,非即時、非可交易訊號」——**免責做進圖裡**,無誇大。

### 檢查 4 — tg_magnet:PASS
- `git diff` 讀畢(+72/-4):新增 `_daytrade_magnet()` **真讀 `twdata/daytrade_eligibility_*.json` 最新檔**(非寫死樣本)——smoke run 實跑吐出「資料日 2026-07-13、處置股 21 檔」與該日檔一致;讀不到檔 fail-safe 退回純防呆清單,永遠有內容。
- `_PORTALY_SUBSCRIPTION_URL` 已定義(line 98,env 讀取,預設 `[PORTALY_URL_PLACEHOLDER]`);`_subscribe_cta()` 未設時**落回 landing**、不外發假訂閱連結 → placeholder 機制未破壞。
- `_TWDATA = ROOT.parent/"twdata"` 路徑解析正確(ROOT=youtube_channel)。
- `python -m py_compile tg_magnet.py make_landing.py listing_templates.py` → 全過。
- 磁鐵名單只列真實代號、明寫「不是選股名單、不喊買賣」→ 誠信 OK。

### 檢查 5 — RWD 抽驗(375px):PASS
- Playwright 375×812 開 index.html:`scrollWidth==clientWidth==375`(**無水平溢出、無爆版**)。
- 全頁截圖親看:數據鋪商品卡(旗艦訂閱三檔價/免費磁鐵/入門/數據包/EN pack)版面乾淨、字級與卡片自適應、底部免責完整。

---

## 跨切面發現

- **[MINOR-2] YouTube handle 不一致(非 funnel-face 之過,但上線前該收斂)**:全 repo `@carson-quant` 125 次 vs `@carsonquant` 5 次。landing/make_landing 用**多數派 `@carson-quant`**(與 repo 一致);少數派 5 處在 `ecommerce/config.py`、`subscription_report.py`、`finance_dept.py`(其他 agent 的檔)。→ landing 站在正確的一邊;建議 Carson 確認哪個是真實頻道 handle,並把落單的 5 處統一。**若 `@carson-quant` 其實是錯的,則升級為 MAJOR**(公開頁死連結),但證據(125:5)指向它是對的。

## 建議修正優先序(都非阻斷)
1. MINOR-1:改 C2 copy 的 EPS 示意序列措辭,對齊實際成品的完整真實序列。
2. MINOR-2:確認並收斂 YouTube handle(以 landing 的 @carson-quant 為準,修 config/subscription_report/finance 的 5 處)。

## 驗證方法留痕
- 重產 diff、MD5 比對、openpyxl 開 xlsx 數列、state.json/valuation 欄位核對、git diff 逐讀、py_compile、tg_magnet smoke run 讀真檔、Playwright 375px 溢出量測 + 截圖親看、pin 圖親看。全程唯讀本機、未打外網、未動 .env。
