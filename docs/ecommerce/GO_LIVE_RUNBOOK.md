# 量化阿森電商 v2 — 上線手冊(GO-LIVE RUNBOOK)

> 給 Carson 本人照著做就能上線。每一步標了 **⏱ 預估耗時**、**依賴**、以及要去哪個網址、把什麼值貼到哪個檔的哪一行。
> 系統側(週報引擎 / 金流 webhook / 漏斗)已完工;這份手冊全是**只有你本人能做**的動作(開帳號 / KYC / 綁收款 / 設密鑰 / 上架 / 換連結 / 送聯盟)。
> 撰寫依據:商業規格 `docs/ecommerce/REDESIGN_SPEC_business.md` §5 上線順序 + §4 定價。所有變數名 / 路徑 / 行號都對著 repo 程式碼實掃過(2026-07-16)。
>
> **看不到官方後台長怎樣的地方,一律寫「以官方後台實際欄位為準」——不腦補。標「(待確認)」的請上線時補。**

---

## 0. 開工前(必讀)

- **這是設定工作,不是寫程式**:你只需要在網頁後台點選、複製貼上密鑰/連結。
- **紅線**:任何「動錢/對外發送」動作(綁收款、開訂閱牆、發第一封信)請本人親手做;系統預設 `dry_run`(不會自動寄信/自動收款),要你手動關掉才會真跑。
- **兩個 .env 檔**(密鑰貼這裡,**不要 commit、不要外流**)。兩個都是**逐行 `KEY=VALUE`**,程式會自己載,你只要貼值:
  - `quant-service/.env` —— **金流 webhook + SMTP 寄信**。由 `webhook/config.py` 的 `_load_env()` 在 import 時自動載(相對檔案定位,不管你從哪個目錄啟動都讀得到)。
  - `youtube_channel/.env` —— **漏斗/發文/landing** 營運腳本讀這個(各腳本自己的 `_load_env()`;排程下的 job 由 `local_cron.py` 帶入)。
  - **規則:真的環境變數優先,.env 不會覆蓋它**(`os.environ.setdefault`)。所以正式部署可以用系統環境變數蓋過檔案值。
  - **改完 .env 一定要重啟對應程序**(工作室排程器 / webhook 視窗)才生效。
- **起 webhook 就雙擊 `quant-service/啟動webhook.bat`**(§3)。它會自己切到 repo root、載 `.env`、印出**哪把密鑰有讀到(SET)/沒讀到(MISSING)**的啟動摘要。**看到 MISSING 就代表那個平台會回 503、收不到錢**——上線前先把摘要看過一遍。
- **順序原則**(§5):Portaly 訂閱主柱最優先 → 免費磁鐵抓名單 → 訂閱牆+webhook → tripwire/core 上架 → 聯盟 → Whop 國際實驗。

**總覽:約 22 個可執行步驟,估總耗時約 6–9 小時**(不含各平台 KYC 審核等待:蝦皮/通路王審核可拖數天~2 個月,越早送越好)。

---

## 1. 帳號開設順序(⏱ 合計約 2–3 小時 + 審核等待)

> KYC 要備的文件與後台欄位以各平台官方頁面實際為準;下面列註冊入口與「大致要準備什麼」。

### 1.1 Portaly(台灣訂閱主柱,**最先開**) ⏱ 30–45 分
- 註冊:`https://portaly.cc/`(以官方頁面實際為準)。
- 用途:旗艦**訂閱牆**(基礎版 **NT$49** / 完整版 **NT$149**)+ 台灣一次性 SKU(C1/C2)。
  - ⚠️ **只開這兩個方案。年繳暫緩**(2026-07-16 Carson 拍板:續訂殺手會在第 2–3 個月暴露,
    年繳等於把不滿意的客戶鎖 12 個月;等 S7 點播補完、有真實續訂率再開)。
  - 🔴 **價格必須與 `quant-service/ecommerce/config.py` 的 `SUBSCRIPTION` 完全一致**——
    那是全系統唯一的定價事實來源(webhook 的 tier 分類、landing、上架文案、Pinterest pin
    全部從它導出)。**在 Portaly 設錯價 = 訂閱者金額對不上 → tier 判成 unknown**
    (系統會保底寄基礎版並告警,但名冊會是錯的)。設之前先看一眼那個檔。
- KYC/收款:綁台灣本人銀行帳戶(自動續訂+自動發票)。要備:身分證、銀行帳戶。以 Portaly 後台實際欄位為準。
- **依賴**:後面「訂閱牆設定 + webhook(§3.4)」「landing/tg 換連結(§4 步驟)」都等這個帳號拿到訂閱連結。

### 1.2 蝦皮賣場(台灣 tripwire) ⏱ 30 分 + 審核
- 註冊:蝦皮賣家中心 `https://seller.shopee.tw/`(以官方為準)。
- 用途:L1 tripwire — T1 定投模板 NT$99、T2 單檔體檢 NT$149(數位商品)。
- **注意**:蝦皮數位商品交付走「買家下單→你發下載連結」;審核可能要幾天,**早點送**。

### 1.3 Gumroad(國際 EN 數據包) ⏱ 30 分
- 註冊:`https://gumroad.com/`(以官方為準)。
- 用途:國際版 C1/C2(EN)+ 收款(綁 PayPal 或信用卡收款,以 Gumroad 後台為準)。
- **關鍵**:上線要拿到兩個東西給 webhook 用 —— **Seller ID**(帳號設定頁)與 **Ping token**(見 §2/§3.1)。

### 1.4 Whop(國際訂閱**實驗**,第二階段,可延後) ⏱ 30 分
- 註冊:`https://whop.com/`(以官方為準)。
- 用途:英文向訂閱週報實驗。**新對外管道**——正式收款前先跟自己確認一次。
- webhook 欄位官方未第一手公開(見 §3.3),**上線前必須用真實測試 webhook 校準**。

### 1.5 收款腿:玉山 + PayPal(TradingView 出金用) ⏱ 30–45 分
- **TradingView 聯盟返佣**(30% 終身)出金走 **PayPal**;PayPal 建議綁**玉山銀行**(台灣提領外幣通路)。
- 步驟:開/確認 PayPal 商業帳戶 → 綁玉山帳戶做提領 → 之後 §6 TradingView 聯盟後台填 PayPal 收款 email。
- 具體提領流程/手續費以 PayPal 與玉山實際為準(待確認)。

---

## 2. env 變數總表(⏱ 30–45 分;拿到值就填)

> **重掃 repo 實況**(2026-07-16 重驗)。填法:webhook/SMTP 系列填 `quant-service/.env`;漏斗/發文/landing 系列填 `youtube_channel/.env`。兩個檔都會被程式自動載(見 §0)。填完**重啟對應程序**。
>
> 「誰在讀」一律標**符號名**(函式/常數)而非行號——行號會隨改動腐爛,符號名不會。要跳到定義處在編輯器搜該符號即可。

### 2.1 金流 webhook 密鑰(填 `quant-service/.env`)

| 變數 | 去哪拿值 | 誰在讀 |
|---|---|---|
| `GUMROAD_SELLER_ID` | Gumroad 帳號設定頁 | `webhook/config.py` → `Settings.from_env()` |
| `GUMROAD_PING_TOKEN` | 你自訂一組隨機字串,Gumroad Ping 設定頁貼同一組(見 §3.1) | 同上 |
| `PORTALY_WEBHOOK_SECRET` | Portaly webhook 設定頁的簽章密鑰(以後台為準) | 同上 |
| `LEMONSQUEEZY_WEBHOOK_SECRET` | (若用 Lemon Squeezy)LS webhook 設定的 signing secret | 同上 |
| `WHOP_WEBHOOK_SECRET` | Whop webhook 設定的 signing secret | 同上 |
| `NTFY_TOPIC` | 已有預設 `carsonquant-hc-9k3x7m2q`(手機 ntfy 訂這個 topic 就會收到成交通知);要換再設 | 同上 |

> 密鑰**未設 → 該平台 webhook 直接 fail-closed 回 503**(不會誤放行未驗簽請求)。所以哪個平台要上線,就先把那個密鑰填好。
> **怎麼確認有讀到**:起 `啟動webhook.bat`,看主控台那行 `[webhook] 平台密鑰: ... =SET/MISSING`(只報有無,不會印出密鑰值)。

### 2.2 交付信下載連結(填 `quant-service/.env`;上架拿到成品下載頁後回填)

| 變數 | 對應 SKU | 誰在讀 |
|---|---|---|
| `ECOMMERCE_DL_T1` | T1 定投模板下載連結 | `webhook/config.py` → `SKU_CATALOG` 的 `dl_env` → `download_url_for()` → `delivery.py` |
| `ECOMMERCE_DL_T2` | T2 單檔體檢 | 同上 |
| `ECOMMERCE_DL_T3` | T3 個股體檢多檔組合(最多5檔,NT$100) | 同上 |
| `ECOMMERCE_DL_T4` | T4 個股體檢多檔組合(最多50檔,NT$500) | 同上 |
| `ECOMMERCE_DL_C1` | C1 全市場回測包 | 同上 |
| `ECOMMERCE_DL_C2` | C2 體檢合輯 | 同上 |

> 未設 → 交付信帶 placeholder(**不寄假連結**),買家不會拿到死連結。訂閱(SUB_weekly)無 dl_env(見 §2.3 週報說明)。
> 啟動摘要那行 `[webhook] 下載連結: ECOMMERCE_DL_T1=SET/MISSING ...` 可一眼確認回填了沒。

### 2.3 交付信寄件(SMTP,填 `quant-service/.env`)

**SMTP 的單一事實來源 = `quant-service/.env`**。理由(2026-07-16 實掃):全 repo 會讀 `SMTP_*` 的**只有 quant-service 底下這幾支**,`youtube_channel` 全樹**零個** SMTP 讀取點——所以不會有「填錯邊」的問題,填這一個檔就對了。

| 變數 | 去哪拿 | 誰在讀 |
|---|---|---|
| `SMTP_USER` | Gmail 帳號(或寄件信箱) | `webhook/delivery.py` → `_smtp_send()`;`webhook/config.py` → `Settings.from_env()`(定 dry_run);`ecommerce/subscription_report.py` → `_send_email()` |
| `SMTP_PASS` | Gmail **應用程式密碼**(非登入密碼) | 同上 |
| `SMTP_HOST` | 預設 `smtp.gmail.com`,用 Gmail 不用改 | 同上 |
| `SMTP_PORT` | 預設 `587`,不用改 | 同上 |

> **重要**:`SMTP_USER` 與 `SMTP_PASS` **兩個都齊** webhook 才會關掉 `dry_run` 真寄信(`Settings.from_env()`)。缺任一 → 強制 dry_run,不會誤寄。
>
> ⚠️ **這條現在是活的**:啟動摘要會直接告訴你 `dry_run=True/False`。看到 **`dry_run=False` 就代表下一筆真成交會真的寄信給買家**——那是對外動作,確定 §2.2 的下載連結都回填好了再開。要暫時關掉真寄信:把 `SMTP_USER`/`SMTP_PASS` 其中一個註解掉再重啟。

**旗艦訂閱週報「不吃」SMTP —— 它目前根本不寄信**(別誤會這裡沒設好):

- 排程跑的是 `ecommerce_weekly.py`(`deploy/crontab.txt` 每週一),它呼叫的週報引擎是 **`weekly_report_v2.py`**,而 `weekly_report_v2` **全檔零個 SMTP 讀取點、也沒有任何寄送函式**——只 `generate_weekly()` 產 PDF/xlsx + `load_send_list()` 列出名單。`ecommerce_weekly._weekly_report_preview()` 的交付結果是**寫死的 `dry_run=True`**,設計上就不寄給任何人(要寄給訂閱者是「對外發布」紅線,留給你本人決定)。
- `ecommerce/subscription_report.py`(有 `_send_email()`)是 **v1 舊引擎,已被 v2 取代**,其 `send_report()` **目前零個呼叫點**。留著是備援(回退方式見該檔 `_weekly_report_preview()` docstring)。
- ⇒ 所以:**填 SMTP 只會讓「交付信」(一次性商品下載信)真寄**;訂閱週報要真寄,是還沒接的一段功能,不是設定問題。

### 2.4 漏斗/發文/週報營運(填 `youtube_channel/.env`)

| 變數 | 去哪拿值 | 誰在讀(檔:行) |
|---|---|---|
| `PORTALY_SUBSCRIPTION_URL` | Portaly 訂閱牆連結(§1.1 拿到後) | `tg_magnet.py:98` |
| `PRODUCT_STORE_URL` | Portaly 商店/訂閱牆連結(發文帶購買連結用) | `autopost.py:54`、`make_landing.py` → 模組層 `PORTALY` |
| `GUMROAD_STORE_URL` | Gumroad 商店連結(國際 EN) | `make_landing.py` → 模組層 `GUMROAD` |
| `WORKSHEET_URL` | tripwire 收款連結(T1 試算表 upsell) | `tg_magnet.py:82` |
| `NEWSLETTER_URL` | 付費電子報收款連結(若開) | `tg_magnet.py:96` |
| `TG_MAGNET_TOKEN` | Telegram bot token(BotFather)——磁鐵/名單機器人 | `tg_magnet.py:46`;`ecommerce/subscription_report.py` → `_send_telegram()`(退回別名 `TELEGRAM_BOT_TOKEN`) |
| `UPLOADPOST_API_KEY` | upload-post 服務 API key(多平台發片) | `autopost.py:43` |
| `UPLOADPOST_USER` | upload-post 使用者 | `autopost.py:44` |

> 週報引擎 `weekly_report_v2.py` **本身不讀任何 env**,且**沒有寄送路徑**(交付走 `load_send_list()` 介面 + dry_run)——詳見 §2.3 末段。

### 2.5 與 team-lead 先前那批清單的**差異**(重掃結果)

- **先前那批已含且確認存在**:`GUMROAD_PING_TOKEN`、`GUMROAD_SELLER_ID`、`PORTALY_WEBHOOK_SECRET`、`WHOP_WEBHOOK_SECRET`、`LEMONSQUEEZY_WEBHOOK_SECRET`、`PORTALY_SUBSCRIPTION_URL`、`PRODUCT_STORE_URL`、`SMTP_*`、`NTFY_TOPIC` —— 全部真的有在讀,無一多餘。
- **重掃**多**找到、先前那批沒列**的:`ECOMMERCE_DL_T1/T2/C1/C2`(交付下載連結)、`GUMROAD_STORE_URL`(landing 國際連結,與 PRODUCT_STORE_URL 不同)、`WORKSHEET_URL`、`NEWSLETTER_URL`、`TG_MAGNET_TOKEN`(/`TELEGRAM_BOT_TOKEN` 為退回別名)、`UPLOADPOST_API_KEY`、`UPLOADPOST_USER`。
- **沒了/已淘汰**:無(先前那批沒有任何一個變數已從程式碼消失)。

---

## 3. webhook 接線(⏱ 45–60 分/平台,真實測試才算完)

> **怎麼起**:雙擊 **`quant-service/啟動webhook.bat`**。就這樣,不用開終端機、不用管目錄。
>
> 它做的事:切到 repo root → 載 `quant-service/.env` → 起 `uvicorn quant-service.webhook.app:app --host 0.0.0.0 --port 8021` → 印啟動摘要。
>
> ⚠️ **要手打指令的話,cwd 必須是 repo root(`D:\carson-agent`)**:import 路徑 `quant-service.webhook.app:app` 裡的 `quant-service` 是 namespace package,**只有站在 repo root 才 import 得到**。在 `quant-service/` 裡面跑會直接 `ModuleNotFoundError: No module named 'quant-service'`(實測過)。`.bat` 已經幫你處理掉這件事。
>
> **起來後先自檢**:主控台的 `[webhook] ...` 摘要——密鑰該 SET 的都 SET 了嗎?`dry_run` 是你要的嗎?再打 `http://127.0.0.1:8021/health` 應回 `{"status":"ok",...}`。
>
> **對外**:平台後台要填**公網可達 URL**,不是 localhost —— 本機請開 cloudflared tunnel 指到 `127.0.0.1:8021`。以下用 `https://<你的公網域名>` 代表。四平台各一個路徑。

### 3.1 Gumroad ⏱ 30 分
- 後台 → Settings → Advanced → **Ping URL** 填:`https://<你的公網域名>/sale-ping/gumroad?token=<GUMROAD_PING_TOKEN>`
- **必須帶 `?token=`**:webhook 用 query 的 `token` 或 header `x-ping-token` 驗(`app.py` → `sale_gumroad()`),值要等於 `.env` 的 `GUMROAD_PING_TOKEN`。少了它 → 驗簽失敗。
- 路由:`app.py` → `@api.post("/sale-ping/gumroad")`;欄位對照 `normalize.parse_gumroad`(`normalize.py:46`,已對 Gumroad 官方 Ping 欄位:`product_name/email/price(分)/currency/sale_id/refunded/cancelled/recurrence`)。

### 3.2 Lemon Squeezy(可選) ⏱ 20 分
- 後台 webhook URL:`https://<你的公網域名>/sale-ping/lemonsqueezy`,signing secret 填進 `LEMONSQUEEZY_WEBHOOK_SECRET`。
- 路由 `app.py` → `@api.post("/sale-ping/lemonsqueezy")`;事件對照表 `normalize.py:82 _LS_KIND`(order_created/subscription_* 已對應)。

### 3.3 Whop(⚠️ 需校準) ⏱ 30 分 + 校準
- webhook URL:`https://<你的公網域名>/sale-ping/whop`,signing secret 填 `WHOP_WEBHOOK_SECRET`。路由 `app.py` → `@api.post("/sale-ping/whop")`。
- **⚠️ 欄位待真實 webhook 校準**(`normalize.py:7-11` 校準註記):
  - 事件名→kind 對應表:`normalize.py:118 _WHOP_KIND`(`payment.succeeded→SUB_RENEW`、`membership.went_valid/activated→SUB_NEW`、`membership.went_invalid/cancelled→SUB_CANCEL`、`payment.refunded→REFUND`)。
  - 欄位候選鍵:`normalize.py:140-146`(email 取 `data.email/user_email/user.email`;product 取 `product/plan/product_name`;amount 取 `final_amount/amount/subtotal`;period_end 取 `renewal_period_end/expires_at`)。
  - **怎麼校準**:發一筆真實測試訂閱 → 看 webhook log 印出的原始 payload → 對照上面候選鍵,少哪個 key 就在該 `_first(...)` 補上 → 重跑測試直到 kind/email/amount/tier 都對。

### 3.4 Portaly(⚠️ 需校準,台灣主柱) ⏱ 30 分 + 校準
- webhook URL:`https://<你的公網域名>/sale-ping/portaly`,簽章密鑰填 `PORTALY_WEBHOOK_SECRET`。路由 `app.py` → `@api.post("/sale-ping/portaly")`。
- **⚠️ 官方無第一手 webhook spec,全為暫定**(`normalize.py:152-154`):
  - status→kind 對應:`normalize.py:155 _PORTALY_STATUS_KIND`(`subscription_created/subscribed→SUB_NEW`、`renewed→SUB_RENEW`、`cancelled/unsubscribed→SUB_CANCEL`、`refunded→REFUND`)。
  - 欄位候選鍵:`normalize.py:181-187`(email 取 `email/buyer_email/customer_email`;name 取 `name/buyer_name/姓名`;amount 取 `amount/price/total`;period_end 取 `period_end/next_billing_at`)。
  - **怎麼校準**:同 Whop —— 拿第一筆真實 Portaly 測試 webhook 的 payload,對照候選鍵補齊/改名,重測到 tier 分層(basic/full;年繳暫緩故不在分類表內)正確。⚠️ `SUBSCRIPTION_TIERS` 已改為**從 `ecommerce/config.py` 的 `SUBSCRIPTION` 自動導出**,不要去手改它——改價一律改 config 那一處。
- **驗證通了沒**:打 `GET https://<你的公網域名>/health`(`app.py` → `@api.get("/health")`)回 `active_subscribers` 有跟著測試單增加,就是名冊有接上。

---

## 4. placeholder 替換點(⏱ 20 分;上架/開牆拿到真連結後逐一換)

> 拿到 Portaly / Gumroad 真連結後,**優先用 .env 設變數**(不用改檔);landing 靜態頁若是已產出的成品,需重跑產生器或直接改檔。

| 檔案:行 | placeholder | 換成 | 換法 |
|---|---|---|---|
| `youtube_channel/scripts/tg_magnet.py:98` | `[PORTALY_URL_PLACEHOLDER]` | Portaly 訂閱連結 | 設 `.env` 的 `PORTALY_SUBSCRIPTION_URL`(不改檔) |
| `youtube_channel/scripts/autopost.py:54` | `[PORTALY_URL_PLACEHOLDER]` | Portaly 商店連結 | 設 `.env` 的 `PRODUCT_STORE_URL` |
| `youtube_channel/scripts/make_landing.py` → 模組層 `PORTALY` | `[PORTALY_URL_PLACEHOLDER]` | Portaly 連結 | 設 `youtube_channel/.env` 的 `PRODUCT_STORE_URL` 後**重跑** `python youtube_channel/scripts/make_landing.py` |
| `youtube_channel/scripts/make_landing.py` → 模組層 `GUMROAD` | `[GUMROAD_URL_PLACEHOLDER]` | Gumroad 商店連結 | 設 `youtube_channel/.env` 的 `GUMROAD_STORE_URL` 後**重跑**(同上,一次全換) |
| `youtube_channel/assets/landing/index.html:115,142,148` | `[PORTALY_URL_PLACEHOLDER]` | Portaly 連結 | 由 `make_landing.py` 重新產生覆蓋(或手動改這 3 行) |
| `youtube_channel/assets/landing/index.html:154` | `[GUMROAD_URL_PLACEHOLDER]` | Gumroad 連結 | 同上 |

> **重跑真的會生效**(2026-07-16 修+實測):`make_landing.py` 現在自己會載 `youtube_channel/.env`。修之前它不載、又不在排程裡,手動重跑吃不到 `.env`,會靜默落回 placeholder → 買鈕全是死連結。
> 實測:設好兩個變數重跑 → 產出 0 個 placeholder、4 個購買按鈕(3 Portaly + 1 Gumroad)全是真連結;沒設 → 仍正確落回 placeholder(不外發死連結的紀律沒破)。
>
> 換完檢查:landing 頁四個購買按鈕都不再是 placeholder;`autopost` 發文尾巴的購買連結(`autopost.py:145`)是真連結。
> 產出的 `index.html` 要部署才會對外生效(覆蓋到 `carsonchou/carson-quant-link` repo 再 push,見 `make_landing.py` docstring)。
>
> **`gen_media_kit.py` 不在這張表**(先前列它是誤植):它全檔**沒有**商店連結 placeholder;它的 `PLACEHOLDER = "〔待補：Carson 從 YouTube Studio 後台填〕"` 是**YT 後台數據佔位**(訂閱總數/聯絡窗口),跟 Portaly/Gumroad 連結無關,也不走 env。別去那裡找連結。

---

## 5. SKU 上架對照表(⏱ 1.5–2 小時,8 個 SKU)

> 成品在 Task #4 產物目錄 `quant-service/output/ecommerce_ready/v2/`(已驗證存在)。每個 SKU 資料夾內含 `listing.json`(標題/描述/tags/定價)、`listing.md`、成品 PDF、`_provenance.json`;文案另有 `v2/listings_copy/<平台>/*.md`。
>
> **注意**:Task #4(product_factory v2)標記 in_progress。下列路徑以目前 `v2/` 結構為準;若 Task #4 收尾後檔名微調,以該任務最終產物為準(待 Task #4 確認最終檔名)。

| SKU | 平台 | 成品路徑 | listing 文案 | 定價 |
|---|---|---|---|---|
| M1 免費磁鐵(當沖清單) | 落地頁抓名單 | `v2/magnet/M1_zh/` | — | 免費 |
| M2 免費磁鐵(台積電體檢) | 落地頁抓名單 | `v2/magnet/M2_zh/`(`台積電體檢報告.pdf`) | — | 免費 |
| T1 定投追蹤模板 | 蝦皮 | `v2/shopee/T1_zh/`(`台股定投追蹤模板.xlsx` + `_導引.pdf`) | `v2/listings_copy/shopee/` | NT$99 |
| T2 單檔體檢 | 蝦皮 | `v2/shopee/T2_zh/` | `v2/listings_copy/shopee/` | NT$149 |
| C1 全市場回測包 | Portaly | `v2/portaly/C1_zh/`(`台股全市場回測_1770檔.xlsx` + `_摘要.pdf`) | `v2/listings_copy/portaly/C1_fullmarket_backtest.md` | NT$990 |
| C2 體檢合輯 | Portaly | `v2/portaly/C2_zh/` | `v2/listings_copy/portaly/C2_bluechip_checkup.md` | NT$1280 |
| C1 EN | Gumroad | `v2/gumroad/C1_en/` | `v2/listings_copy/gumroad/` | US$35 |
| C2 EN | Gumroad | `v2/gumroad/C2_en/` | `v2/listings_copy/gumroad/` | US$39 |
| 旗艦訂閱週報 | Portaly 訂閱牆 | 週報引擎即時產(`weekly_report_v2.py`) | `v2/listings_copy/portaly/subscription_weekly.md` | NT$99/149/1290 |

- 上架步驟(每個 SKU):平台後台新增商品 → 複製 listing 文案(標題/描述/tags 從 `listing.json`)→ 上傳成品 PDF/xlsx(或設下載連結)→ 定價照上表 → 發佈。
- **上架後**:把該商品的**下載連結**回填到 §2.2 對應 `ECOMMERCE_DL_*`(webhook 交付信才寄得出真連結)。
- **依賴**:C1/C2/T1/T2 上架依賴 §1 帳號 + §4 placeholder;M1/M2 依賴落地頁(§4)上線。

---

## 6. 聯盟申請(⏱ 30–45 分;越慢審的越早送)

> 4 份一鍵 checklist 在 `quant-service/output/ecommerce_ready/affiliate_checklists/`。優先序:TradingView(主力)> ClickBank / 蝦皮分潤 > 通路王(最慢,最早送卡位)。

| 聯盟 | checklist | 一句話 | 送件入口(以官方為準) |
|---|---|---|---|
| **TradingView**(第二腿主力,**先送**) | `tradingview_affiliate_checklist.md` | 30% recurring **終身制**、與看盤頻道完美對口、多為秒過 | `https://www.tradingview.com/affiliate/`;出金綁 §1.5 PayPal |
| ClickBank(國際數位) | `clickbank_affiliate_checklist.md` | 秒批、官方鼓勵 AI 內容、cookie 60 天;搭 EN 影片 + Gumroad | `https://www.clickbank.com/` |
| 蝦皮分潤(台灣站內) | `shopee_affiliate_checklist.md` | 站內流量實證、出金門檻 NT$500、cookie 7 天;被拒不影響主軸 | 蝦皮分潤計畫頁 |
| 通路王 iChannels(台灣長線,**最早送卡位**) | `ichannels_affiliate_checklist.md` | 審核可拖近 2 個月、佣金不高但因慢要最早送 | `https://www.ichannels.com.tw/` |

---

## 7. 上線後 Day-1 驗證清單(⏱ 30–45 分)

> 每個平台發**一筆最小額真實測試單**,確認全鏈路有動。做完把測試單退款。

1. **Gumroad**:買自己一個最低價 SKU(或用 Gumroad 測試模式)→ 檢查:
   - 手機 ntfy(topic `NTFY_TOPIC`)有沒有跳成交通知;
   - `youtube_channel/STUDIO/ecommerce_sales.json`(記帳簿)有沒有新增一筆;
   - 買家信箱有沒有收到交付信(含真下載連結,若已設 `ECOMMERCE_DL_*` + SMTP)。
2. **Portaly 訂閱**:訂一筆基礎版 → 檢查:
   - `GET /health` 的 `active_subscribers` +1;
   - `youtube_channel/STUDIO/ecommerce_subscribers.json` 出現該 email、`status=active`、`tier` 正確(這步同時驗 §3.4 校準對不對);
   - 跑 `python youtube_channel/scripts/ecommerce_weekly.py`(不帶 `--notify`)→ 週報段「寄送名單」人數應 +1(這步只驗名單接上了,**它不會寄任何東西**,見 §2.3 末段)。
3. **退款測試**:對上面測試單發退款 → 檢查名冊 `status` 變 `cancelled`、`active_subscribers` -1、記帳簿有負值沖銷。
4. **交付信真寄**:起 webhook 時看啟動摘要那行 `dry_run=False`(= `SMTP_USER`+`SMTP_PASS` 都讀到了;任一缺就是 `dry_run=True` 永遠不寄)——再用一筆測試單確認信真的寄達。
5. **金額怎麼退**:各平台後台「訂單→退款」;webhook 收到退款事件會自動把訂閱者移出名單 + 記帳沖銷(`subscribers.py` / `revenue.py`),你只需在平台按退款。

---

## 8. 依賴速查(哪步不做會卡哪步)

- §1.1 Portaly 帳號 ❌ → §2.4 `PORTALY_SUBSCRIPTION_URL`/§3.4 webhook/§4 換連結/§5 C1・C2・訂閱 全卡。
- §2.1 webhook 密鑰 ❌ → §3 對應平台 webhook 回 503,收不到成交。**起 webhook 時看啟動摘要有沒有 MISSING 就能提前抓到。**
- §2.3 SMTP ❌ → 交付信永遠 dry_run,買家收不到下載信(名冊/記帳仍會動)。**反過來:SMTP 齊備 = `dry_run=False` = 真成交會真寄信,這是對外動作。**
- (訂閱週報寄送:目前**沒有**寄送路徑,與 SMTP 無關,見 §2.3 末段——不是你哪裡沒設好。)
- §2.2 `ECOMMERCE_DL_*` ❌ → 交付信帶 placeholder(不寄假連結,但買家拿不到檔)。
- §4 placeholder 沒換 → landing/發文的購買按鈕是死連結,流量進來買不了。
- §3.3/§3.4 沒校準 → Whop/Portaly 可能把事件歸錯類(tier 錯 / 名冊沒進),**務必用真實測試單驗過再開放**。
- §1.5 PayPal/玉山 ❌ → §6 TradingView 聯盟出不了金。

---

> **收尾自檢**:§7 五項全綠 = 系統端上線完成。之後對外開放(公開訂閱牆連結、正式發文導流)屬「對外發布」紅線,建議先跑一次 fresh-context 誠信驗證(Phase 3 / Task #10)再全面放量。
