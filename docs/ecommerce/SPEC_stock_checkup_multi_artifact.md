# 個股體檢「多檔動態選股」Demo → 正式商品 — 規格草案

> 起因:claude.ai Artifact 原型 `stock_checkup_demo.html`(使用者上傳截圖/輸入代號 → 最多 5 檔
> → 6 大指標體檢 → NT$399 假付款頁)。本文把它對到既有系統,原始規格討論列出三個要 Carson
> 拍板的決策點,後續 T3 付款平台又經歷兩次拍板改道(決策點 4:蝦皮→LINE Pay;決策點 5:
> LINE Pay→ECPay 綠界),**本文第 3 節「實作結果」已隨最新拍板同步更新,現況為 ECPay**。
> 姊妹文件:`REDESIGN_SPEC_business.md`(定價與商品線事實來源)、`GO_LIVE_RUNBOOK.md`(上線步驟範例格式)。

---

## 0. 結論先講:demo 不是地基,是視覺原型

claude.ai 的 Artifact 網路被封鎖,無法打自架的 `data_hunter` / `webhook` API(`mcp` 能力只接
claude.ai 已註冊的官方連接器,不是任意 localhost 服務)。所以正式版**不會是這個 Artifact 長大**,
而是掛在 `quant-service` 底下一支真的部署頁面,伺服端直接 import 既有模組。Artifact 頁面的唯一
產出是「畫面長怎樣、流程怎麼走」的可視化原型,供這輪規格討論用。

---

## 1. 可重用的既有基礎建設(已是活系統,非新建)

### 1.1 股票資料庫 —— 對應 demo 的 6 大指標

`quant-service/data_hunter/` 已有:

| 模組 | 提供的資料 |
|---|---|
| `fundamentals.py` | 營收 YoY/MoM、EPS、毛利率/營益率、股利、財務比率(流動比/負債比/FCF/ROE) |
| `valuation.py` | 四法估值(PE/殖利率/PB/PEG+Gordon)→ 合理價區間 + 現價落點 |
| `chips.py` / `tdcc.py` | 籌碼/股權分散 |
| `margin.py` | 融資融券 |
| `zones.py` | 支撐壓力區間 |
| `twse_price.py` | 即時報價 |

這套就是「個股體檢系列 YouTube 長片」在用的資料源,已產出 demo 頁面那 6 個指標對應的內容。
`data_hunter/server.py` 是純標準庫 HTTP server(`ThreadingHTTPServer`,無 FastAPI 相依),已有
`/api/*` 路由 + SSE 推播,`app.py` 是桌面一鍵啟動殼。掃描宇宙 `universe.py` 精選約 130 檔流動性好
的台股(非全 1841 檔)——**若多檔體檢要支援 universe 外的代號,需另外確認 fundamentals/valuation
是否走「即時抓」路徑(可,見 fundamentals.py docstring:離線只讀快取、線上缺快取即時抓一次)**。

### 1.2 金流 —— 對應 demo 的付款頁

`quant-service/webhook/` 是已上線的 FastAPI 服務,接 Gumroad / Portaly / LemonSqueezy / Whop 四平台,
fail-closed(密鑰未設 → 503,不會誤放行)。交付層 `delivery.py` 是 **config 驅動**:新增 SKU 只改
`ecommerce/config.py`,不用碰程式邏輯。`ecommerce/config.py` 的 `ONE_OFF` 目錄裡已有對應品項:

```python
"T2": {"name_zh": "個股體檢單檔報告", "ntd": 149, "usd": 7,
       "platform_zh": "shopee", "platform_en": "gumroad"},
"C2": {"name_zh": "台股權值股體檢合輯", "ntd": 1280, "usd": 39,
       "platform_zh": "portaly", "platform_en": "gumroad"},
```

T2 是單檔固定 149 元;C2 是「合輯」但目前定位是固定股票清單(權值股),不是使用者動態選股。

---

## 2. 三個待拍板的決策點

### 決策點 1 —— 架構落點:掛哪支服務、哪個域名/路徑 **(已拍板:掛 webhook 服務)**

兩個候選:

| 候選 | 說明 |
|---|---|
| `data_hunter/server.py` | 標準庫 HTTP server,已有 6 大指標資料存取,但**沒有**金流/checkout 整合 |
| `webhook`(FastAPI,建議✅) | 已上線、已接四平台 checkout+webhook、交付層 config 驅動 |

**建議且採用:掛 `webhook` 這支既有 FastAPI 服務**,理由:
- 付款這步(決策點 3)本來就要落在 webhook 的 checkout 導轉 + `delivery.py` 交付流程上,掛同一支
  服務可以**共用同一個 SKU 目錄、同一組 `.env` 密鑰、同一套 fail-closed 驗簽**,不必在兩支服務間
  傳遞訂單狀態。
- `webhook` 已是 FastAPI(有路由框架),`data_hunter/server.py` 是純標準庫、沒有路由框架,硬要接
  checkout 反而要自己重造一套。
- 6 大指標的計算邏輯不搬家——新路由裡直接 `import` `data_hunter.fundamentals` / `valuation` 等模組
  即可,不需要把 `data_hunter` 整支服務掛過去,只借它的計算函式。

用既有 `webhook` 服務加路由屬「例行維運」,不算開新的對外發布管道,不需另外走紅線確認;
如果之後 Carson 想要獨立網域/新 landing page 取代目前的方式,那才算新管道,需要先問。

### 決策點 2 —— 定價與 SKU **(已拍板:新增 SKU,NT$100)**

Carson 拍板:選方案 A(新增 SKU,非動態疊加),價格 **NT$100**(非 demo 原寫的 399)。已落地:

- `quant-service/ecommerce/config.py` `ONE_OFF` 新增 **`T3`**:
  `{"name_zh": "個股體檢多檔組合(最多5檔)", "name_en": "Multi-Stock Health-Check Bundle (up to 5)",
  "ntd": 100, "usd": 4, "langs": ["zh"], "platform_zh": "line_pay", "platform_en": "gumroad"}`
  ——`platform_zh` 09-16 由 `shopee` 改為 `line_pay`(見下方決策點 4:Carson 拍板中文市場改走
  LINE Pay,不用蝦皮);`platform_en` 維持 `gumroad` 不變(國際市場沒有改動指示)。此欄位目前只是
  文案/分類 metadata,`product_factory_v2.py` 對 T3 沒有讀它的下游邏輯,改動不影響其他程式路徑。
- 🔴 **實查發現一次性 SKU 有兩張表,不是一張**:`ecommerce/config.py` 的 `ONE_OFF` 只是
  `product_factory_v2` 讀的定價/文案表;`webhook` 真正用來把「訂單商品名」判成 SKU、決定寄不寄
  下載連結的是 **`webhook/config.py` 的 `SKU_CATALOG`**(關鍵字比對,獨立清單,只有**訂閱**定價
  有 `_tiers_from_single_source()` 自動從 `ecommerce/config.py` 導出,一次性 SKU 沒有這道自動同步)。
  只改 `ONE_OFF` 不會讓 webhook 認得新商品,會被判成 `unknown`(仍會寄信但帶不出下載連結、名冊
  也會標記未知)。已同步補上 `webhook/config.py` `SKU_CATALOG` 的對應項:
  `{"sku_id": "T3_multi_checkup", "kind": "one_time", "match": ["多檔體檢", "多檔組合",
  "multi-stock health", "multi stock health"], "dl_env": "ECOMMERCE_DL_T3"}`。
- 已跑 `webhook/run_tests.py`(66 tests)全過,沒有破壞既有行為。
- **09-19 補 T4**(`T4_multi_checkup_50`,最多50檔 NT$500,commit fb58bf3c 加進 `stock_checkup._SKUS`
  但漏登記 `SKU_CATALOG` → `download_url_for()` 回 None,設了連結也寄不出):已補
  `{"sku_id": "T4_multi_checkup_50", ..., "dl_env": "ECOMMERCE_DL_T4"}`,並**排在 T3 前面**——
  `resolve_sku` 是依序子字串比對,T4 商品名也含 T3 的「多檔組合」,排後面會被判成 T3。
  `ecommerce/config.py` `ONE_OFF` 同步補 T4(ntd 500,usd 未定 → None)。
  測試 `webhook/tests/test_sku_t4.py`:有連結→寄出、沒連結→仍 fail-closed、T3/T4 不混淆、
  `_SKUS` 與 `ONE_OFF` 價格/品名一致。上線時要另設 `ECOMMERCE_DL_T4`。
- 尚待上線時補:蝦皮/Gumroad 後台真的上架 T3(NT$100/US$4)、設 `ECOMMERCE_DL_T3` 環境變數帶真下載
  連結(在那之前交付信會帶 placeholder 文字,不會寄假連結給付費客人——沿用既有機制)。

### 決策點 3 —— 付款走向:導去既有 hosted checkout,不是自架收單 **(09-16 因決策點 4 部分改寫)**

原規劃是「導去 Portaly/蝦皮 hosted checkout → 對方 webhook 打回 `quant-service/webhook` →
`normalize.py` 判事件 → `delivery.py` 依 `download_url_for(sku_id)` 寄交付信」,**沒有自架信用卡
收單頁**。T3 後來因決策點 4 改走 LINE Pay,細節見下方決策點 4——但「不自架收單、沿用既有
`delivery.py`/`normalize.py` 交付流程」這條大原則不變,只是 T3 的「導去哪個付款頁、怎麼確認付款」
從靜態 hosted checkout 連結換成 LINE Pay 的 Request/Confirm API 兩段式流程。T1/T2/C1/C2 等其餘
SKU 仍是原本的靜態 checkout 連結模式,未受影響。

Demo 裡的假信用卡表單這步要整支換掉,不是接上真收單 API。

**此決策點技術上已確定(沿用既有架構,不自架收單),不需要 Carson 再拍板**,除非要改成自架收單
(不建議,且那屬於「動錢」紅線,會需要另外走 PCI/收單商合規)。

### 決策點 4 —— T3 中文市場付款平台:蝦皮 → LINE Pay **(2026-09-16 Carson 拍板)**

Carson 明確指示:「不要用蝦皮,用 line pay」。追問範圍後,Carson 選擇**真的串接 LINE Pay 金流
回呼**(而非只換 metadata 標籤)。這是「動錢」+「新增對外發布管道」,已在動工前取得 Carson 本人
確認。

**架構跟其餘四平台(Gumroad/Portaly/LemonSqueezy/Whop)不同**:那四個是平台主動打我們的
webhook(`verify.py` 驗 inbound 簽章);**LINE Pay 沒有伺服器對伺服器的 inbound webhook**,是我們
伺服端主動打 LINE Pay 的 API:

1. `POST /api/stock-checkup/order` → 伺服端呼叫 LINE Pay **Request API**(`linepay.py`
   `request_payment()`),帶 `orderId`(= 訂單 token)/`amount`/`currency`,拿到
   `info.paymentUrl.web`,回給前端導使用者過去付款。
2. 使用者在 LINE Pay 頁面完成付款,LINE Pay 用 302 導回我們的 `confirmUrl`,自動附上
   `?transactionId=...&orderId=...`(LINE Pay 加的,不是我們拼的)。
3. `GET /api/stock-checkup/linepay/confirm` 拿 `transactionId` 呼叫 LINE Pay **Confirm API**
   (`linepay.py` `confirm_payment()`,帶回同一組 `amount`/`currency`)——**這通 API 呼叫本身就是
   驗證來源的機制**:金額/幣別對不上、或我們的 channel secret 簽章不對,LINE Pay 直接拒絕(非
   `0000`),不記帳不交付。故不需要像其他四平台那樣另外驗 inbound 簽章。
4. Confirm 成功後,手動組一個 `NormalizedEvent`(不經 `normalize.py`,因為沒有原始 webhook
   payload 可解析——欄位我們自己都已知道)丟進既有 `service.process_event()`,走一模一樣的
   記帳/名冊/交付信/ntfy 流程,`service.py`/`delivery.py`/`ledger.py` **零改動**。
5. 使用者取消 → `GET /api/stock-checkup/linepay/cancel`,單純顯示取消頁面,不記帳不改訂單狀態。

新增設定(`webhook/config.py` `Settings`):
- `LINE_PAY_CHANNEL_ID` / `LINE_PAY_CHANNEL_SECRET` —— 未設一律 fail-closed(`checkout_url:null` +
  「尚未上架」,不吐假連結、不假裝付款成功),與四平台 `verify.py` 紅線一致。
- `LINE_PAY_ENV` —— 預設 `sandbox`(打 `sandbox-api-pay.line.me`),只有明確設成 `production` 才
  打正式環境(`api-pay.line.me`),故意設計成「不小心也不會動真錢」。
- `PUBLIC_BASE_URL` —— 組 `confirmUrl`/`cancelUrl` 要用的對外可達網址,LINE Pay 的伺服器要能連到
  這兩個 URL 才能完成 302 導回。未設也是 fail-closed(不會打一個組不出 confirmUrl 的 Request)。

`ECOMMERCE_DL_T3` 這個既有的交付信下載連結環境變數**不受影響**,LINE Pay 只是換了「怎麼確認付款」,
交付信仍走同一套 placeholder-not-fabricated 機制。

### 決策點 5 —— T3 付款平台二次改道:LINE Pay → ECPay 綠界 **(2026-09-16 Carson 拍板)**

同日內,Carson 在決策點 4 落地、78/78 測試全過之後又追問了 LINE Pay 個人申請門檻,最後拍板
「算了 用綠界科技好了」——**LINE Pay 個人身分申請卡在「Online API」產品資格未釐清**(第三方
教學顯示個人申請多半只給得到「Online API 一般收款」而非需要伺服端 callback 的完整功能,細節
需要 Carson 自己跟 LINE Pay 客服確認,不在我方可驗證範圍內),改走 ECPay 綠界科技這家更成熟的
台灣第三方支付,個人/商務賣家都能申請到本次需要的 AioCheckOut 全方位金流。

**架構跟 LINE Pay 不同、反而跟其餘四平台(Gumroad/Portaly/LemonSqueezy/Whop)一致**:ECPay 是
**inbound 背景通知簽章驗證**,不是我方主動打 API 確認付款:

1. `POST /api/stock-checkup/order` → 伺服端**不打任何外部 API**,而是用 `ecpay.py`
   `build_checkout_params()` 就地算好一組簽章(`CheckMacValue`)參數,存進訂單,回傳我方自己的
   `GET /api/stock-checkup/ecpay/checkout/{token}` 當 `checkout_url`(前端不需要知道背後是
   ECPay)。
2. 使用者打開該網址,拿到一頁 `onload` 自動送出的 HTML 表單,瀏覽器直接 POST 到 ECPay 官方
   AioCheckOut 付款頁(測試:`payment-stage.ecpay.com.tw`;正式:`payment.ecpay.com.tw`)——
   這步**沒有經過我方伺服器**,金流資料直接在使用者瀏覽器跟 ECPay 之間交換。
3. 使用者完成付款後,ECPay 主動對我方 `ReturnURL`(`POST /api/stock-checkup/ecpay/notify`)
   發送伺服器對伺服器的背景通知,帶 `RtnCode`/`TradeAmt`/`TradeNo`/`CheckMacValue` 等欄位——
   驗 `CheckMacValue`(`ecpay.verify_notify()`,`hmac.compare_digest` 比對,跟 `verify.py`
   四平台紀律一致)、驗 `RtnCode=="1"`、驗 `TradeAmt` 與訂單金額吻合三者皆過,才手動組
   `NormalizedEvent` 丟進既有 `service.process_event()`,記帳/名冊/交付信/ntfy 流程
   **零改動**。回應必須是純文字 `"1|OK"`,否則 ECPay 會持續重送(已對重複通知做冪等,不重複
   記帳/交付)。
4. 使用者付款後瀏覽器另外會被導回 `OrderResultURL`(`GET/POST /api/stock-checkup/ecpay/result`)
   ——這只是**給人看的提示頁**,不是權威判定(權威判定只看第 3 步的背景通知,因為使用者可能在
   通知抵達我方伺服器之前就先看到這個導回頁)。

**新增設定(`webhook/config.py` `Settings`)**:
- `ECPAY_MERCHANT_ID` / `ECPAY_HASH_KEY` / `ECPAY_HASH_IV` —— 三者缺一律 fail-closed
  (`checkout_url:null` + 「尚未上架」),與四平台 `verify.py`、LINE Pay 紅線一致。
- `ECPAY_ENV` —— 預設 `test`(打 `payment-stage.ecpay.com.tw`),只有明確設成 `production`
  才打正式環境,故意設計成「不小心也不會動真錢」。
- `PUBLIC_BASE_URL` —— 沿用決策點 4 就有的欄位,組 `ReturnURL`/`ClientBackURL`/`OrderResultURL`
  要用的對外可達網址,ECPay 的伺服器要能連到 `{PUBLIC_BASE_URL}/api/stock-checkup/ecpay/notify`
  才能完成背景通知。

**LINE Pay 的既有程式碼(`linepay.py` + `Settings` 對應欄位)保留不刪**,只是 `stock_checkup.py`
不再 import/引用——已測過、能動的程式碼,留作日後若要切回的備案,不因為又一次改道就浪費掉;
`config.py` 對應欄位已加註解說明現況。

`ECOMMERCE_DL_T3` 這個既有的交付信下載連結環境變數依然**不受影響**,只是又換了一次「怎麼確認
付款」,交付信仍走同一套 placeholder-not-fabricated 機制。

**ECPay 商家申請備忘**(Carson 尚未申請,以下是研究所得、非我方可代辦):
- 個人賣家申請需要身分證等 ID 驗證文件,檔案格式限 JPG/JPEG/PNG/GIF/PDF,單檔 ≤5MB、總計
  ≤25MB;一組身分證字號只能申請一個帳號。
- 客服電話 02-2655-1775(週一至週五 09:00-12:00 / 13:00-18:00),申請流程或資格問題可直接問。
- 本次要用的 AioCheckOut 導轉付款,在個人/商務等級都能申請到,不需要等到「特約商店」等級
  (特約商店等級才有的是站內付 2.0 iframe 嵌入式付款,本次沒有採用,不影響上線時程)。

---

## 3. 實作結果(2026-09-16 三版;決策點 5 落地後,T3 現行方案為 ECPay)

路由已掛進既有 `webhook` 服務,不開新服務、不改既有路由行為:

- `quant-service/webhook/stock_checkup.py` —— 端點:
  - `GET /stock-checkup`:回傳前端頁面(暗色風格,沿用 demo 的配色 token)。
  - `POST /api/stock-checkup/analyze`:body `{codes:[...]}`(最多 5、去重、格式檢查),
    對每檔呼叫 `data_hunter/query.py` 的 `analyze_stock(code, live=False)`
    (+ 內部已含的 `health.compute_health()`)——**沒有重造指標邏輯**,借用既有引擎;
    單檔失敗不拖垮整批,回傳裡該檔標 `ok:false` + 原因。
  - `POST /api/stock-checkup/order`:body `{codes, email}`,產生 `T3`+14 碼十六進位英數字的
    token(當 `MerchantTradeNo`,ECPay 限英數字 ≤20 字元,不能沿用其餘平台的 `token_urlsafe`),
    用 `ledger.save_json_atomic`/`load_json` 記一筆待付訂單到 `Settings.stock_checkup_orders`,
    呼叫 `ecpay.build_checkout_params()` **就地算簽章**(沒有任何外部 API 呼叫)存進訂單、回傳
    我方自己的 `checkout_url`;`PUBLIC_BASE_URL` 或 ECPay 密鑰未設時,回 `checkout_url: null` +
    「尚未上架」訊息,**不捏造連結**。回應格式(`token/sku_id/ntd/checkout_url/checkout_configured/
    note`)維持跟初版一致,前端頁面零改動。
  - `GET /api/stock-checkup/ecpay/checkout/{token}`:把訂單存好的簽章參數包成一頁
    `onload` 自動送出的 HTML 表單,瀏覽器直接 POST 到 ECPay AioCheckOut 付款頁;這就是
    `/order` 回的 `checkout_url`,前端不需要知道背後是 ECPay。訂單不存在/沒有簽章參數 → 404。
  - `POST /api/stock-checkup/ecpay/notify`:ECPay 的背景通知(`ReturnURL`)端點,`ecpay.
    verify_notify()` 驗 `CheckMacValue`、比對 `RtnCode=="1"`、比對 `TradeAmt` 與訂單金額,三者
    皆過才完成訂單並觸發 `service.process_event()`;重複通知/未知訂單/驗章失敗/金額不符皆有
    對應分支,一律回純文字 `"1|OK"`(驗章失敗除外,回 `"0|CheckMacValueError"`)以符合 ECPay
    「非 1|OK 會持續重送」的規範。
  - `GET/POST /api/stock-checkup/ecpay/result`:使用者付款後瀏覽器導回的提示頁
    (`OrderResultURL`),純顯示用,不是權威付款判定。
- `quant-service/webhook/ecpay.py`(新檔)—— ECPay AioCheckOut 簽章客戶端:`CheckMacValue`
  演算法(A-Z 排序 → 金流版 URL encode → SHA256 轉大寫,依官方 `ECPay-API-Skill` 文件核對)、
  `build_checkout_params()`/`verify_notify()`。**沒有任何對外 HTTP 呼叫**,純函式,比
  `linepay.py` 更好測(不需要假 HTTP transport)。密鑰未設一律拋 `ECPayError` / 驗章回 `False`,
  呼叫端接住轉成「尚未上架」。
- `quant-service/webhook/linepay.py` —— **保留不刪**(決策點 5 已改道,`stock_checkup.py`
  不再引用),LINE Pay Online API v3 客戶端維持原樣,留作日後若要切回的備案。
- `quant-service/webhook/static/stock_checkup.html` —— 前端頁面:手動輸入代號 → 打 `/analyze`
  看免費摘要 → 填 email 打 `/order` → 有 `checkout_url` 就導去(我方 checkout 頁再轉 ECPay)、
  沒有就顯示「尚未上架」。**零改動**(checkout_url 對前端而言只是一個網址,不需要知道背後平台)。
- `app.py`:`build_app()` 內 `api.include_router(stock_checkup_router)`,不影響既有四條
  `/sale-ping/*` 路由。

**驗證**(`webhook/tests/test_stock_checkup.py`,TestClient + 本地算的真實 `CheckMacValue`
簽章模擬 ECPay 背景通知,非猜測):
- `GET /stock-checkup` 200,回傳完整頁面。
- `POST /analyze` 對 `2330` 真的跑出 `data_hunter` 的即時數據,證明串接是活的,不是回假資料。
- `POST /order` 密鑰/`PUBLIC_BASE_URL` 齊備時回傳指向我方 `/ecpay/checkout/{token}` 的
  `checkout_url`,該頁確實含正確簽章的 hidden inputs 且導向 `payment-stage.ecpay.com.tw`;
  `PUBLIC_BASE_URL` 未設、或 ECPay 密鑰未設,都正確 fail-closed 回 `checkout_url:null`。
- `POST /ecpay/notify`:驗章通過+`RtnCode=1`+金額吻合 → 完成訂單並觸發
  `service.process_event()`(以 ntfy MANUAL DELIVERY 通知斷言副作用發生);驗章失敗、金額不符、
  `RtnCode` 非 1(不記帳但仍回 `1|OK`)、未知訂單、重複通知(不重複觸發交付)五條分支皆覆蓋,
  簽章用測試自己獨立算的 `CheckMacValue`(不是呼叫 `ecpay.py` 本身),避免測試跟實作抄同一顆
  骰子。
- `GET /ecpay/result` 依 `RtnCode` 顯示對應提示文案。
- 邊界:email 格式錯 → 422;超過 5 檔 / 0 檔 → 422;`checkout` 未知 token → 404。
- `webhook/run_tests.py` **82/82 全過**(66 舊測試 + 15 條新 ECPay 測試 -1 條與舊 LINE Pay
  cancel 頁等價但不再需要單獨測試的頁面測試,無迴歸;另補上此前遺漏的執行期依賴
  `python-multipart`——`request.form()` 解析 ECPay 表單通知需要它,已加進
  `quant-service/requirements.txt`)。

**尚待 Carson 手動做的**(動錢/上架,不在我自主範圍):
1. 向 ECPay 綠界科技申請商家帳號(個人賣家需身分證等 ID 驗證文件,細節與客服電話見上方決策點
   5),取得 `ECPAY_MERCHANT_ID`/`ECPAY_HASH_KEY`/`ECPAY_HASH_IV`。
2. 設定 `PUBLIC_BASE_URL` 指向一個對外可達的 HTTPS 網址(參考 `data_hunter/tunnel.py` 的既有
   慣例:ngrok 固定網域,或 cloudflared 免帳號但每次重啟會換網址),ECPay 的伺服器需要能連到
   `{PUBLIC_BASE_URL}/api/stock-checkup/ecpay/notify` 才能完成背景通知。
3. 確認要正式收款時,設 `ECPAY_ENV=production`(預設 `test`,不會動真錢)。
4. 設 `ECOMMERCE_DL_T3` 與 `ECOMMERCE_DL_T4`(交付信下載連結,5 檔/50 檔方案各一)——這條跟其餘四平台一樣,未改動。

在這些 env 補齊前,頁面會誠實顯示「尚未上架」,`/order` 端點正常記單但無法完成真實收款。
