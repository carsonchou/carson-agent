# Pinterest 電商引流設定指南(Carson 親手照做版)

> 目的:把 `pinterest_pin_generator.py` 產出的 pin 圖,透過 Pinterest 這個「數位商品最大免費站內流量管道」導向電商商品(S1-S3)。
> **這份是給 Carson 照著做的步驟,不是自動化腳本。** Pinterest 是**新的對外發布管道**,依 CLAUDE.md 紅線:任何實際發布、連帳號、設排程工具帳密 → **一律 Carson 親手**,agent 只做到「產圖 + 這份指南」為止。

Pin 圖成品目錄:`quant-service/output/ecommerce_ready/pinterest/`

---

## 為什麼是 Pinterest(一句話定位)
Pinterest 是**視覺搜尋引擎**,不是追蹤者 feed。一支 pin 靠 SEO 關鍵字被搜到,可以在發佈後**數週到數月持續**帶流量(長尾),對「30 訂閱、無現成流量」的起步階段最划算——這是它勝過 IG/Threads 的關鍵差異。

---

## 步驟 0:帳號申請(免費,約 15 分鐘)
1. 到 pinterest.com 註冊,或把個人帳號在設定裡**轉成 Business 帳號**(免費,解鎖 Analytics 與廣告後台,不轉就沒數據可看)。
2. **Claim your website(認領網站)**:設定 → Claimed accounts → 貼上你的商品落地頁網域(Portaly/Gumroad 個人頁或自架 landing 都可),照它給的 meta tag / HTML 檔驗證。認領後你的 pin 會掛上你的品牌、流量歸戶。
3. **開啟 Rich Pins**:認領網站後,商品頁若有 Open Graph meta,Pinterest 會自動抓標題/價格顯示成 Product Rich Pin(更可信、CTR 更高)。用 Rich Pin Validator 驗一次即可。
4. 建 3-5 個**主題板(Boards)**,別全丟一個板。建議:
   - 「台股定投 / 存股」
   - 「量化投資入門」
   - 「個股體檢報告」
   - 「投資避雷 / 新手常見錯誤」
   - 每個板寫**含關鍵字的板描述**(Pinterest 靠這個判定板主題)。

---

## 步驟 1:排程工具怎麼選

### 選項 A(推薦起步):Pinterest 原生排程器 — 免費
- 建立 pin 時可選「**Publish later**」,一次最多排到 **30 天內**、**一次一支**。
- 優點:零成本、零第三方風險、最不會被判 spam(官方自家管道)。
- 缺點:一次只能排一支、要手動,量大時累。
- **起步(前 4-8 週)就用這個**,先養帳號權重。

### 選項 B(規模化後):Tailwind — Pinterest 官方 Marketing Partner
- Tailwind 是 Pinterest **官方認證**的排程夥伴(不是第三方灰色工具),被判 spam 的風險低。
- 核心功能:**SmartSchedule**(自動排在你受眾最活躍的時段)、**Interval Pinning**(同一支 pin 隔數天才發到不同板,而非一次全發 → 這正是避免 spam 誤判的關鍵設計)、批次上傳。
- 免費方案有額度(足夠起步驗證),量大再升月費方案。
- **KYC/帳密由 Carson 本人綁**,agent 不碰。

> 不要用來路不明的「免費自動發文機器人」:Pinterest 對非官方 API 的自動化查得嚴,新帳號被封等於前功盡棄。要嘛原生、要嘛 Tailwind。

---

## 步驟 2:避免被判 spam 的節奏鐵律(新帳號尤其重要)

Pinterest 對「短時間狂發、同圖洗版、連結全指同一頁」最敏感。照這些做:

1. **暖機期(前 2-4 週)**:每天 **1-3 支** pin 就好,別衝量。新帳號一開就每天 20 支 = 高風險。
2. **穩定期**:每天 **5-15 支**,**分散整天**發(用排程器攤開,不要同一分鐘連發)。
3. **一支 pin 不要同時發到多個板**:要跨板就**隔 3-7 天**再發到下一個板(Tailwind Interval 就是做這個)。
4. **多做 Fresh Pin**:Pinterest 現在偏好「新圖」。`pinterest_pin_generator.py` 對每個 SKU 產不同視覺,**同一商品可以換 headline/配色多產幾版**當不同 fresh pin,勝過重複發同一張。
5. **連結別全部指同一頁**:混搭「免費工具落地頁 / 免費 YT 影片 / 商品頁」,不要每支 pin 都硬導購買頁,否則像廣告農場。導購與免費內容比例抓 **1:2 到 1:3**。
6. **描述寫給人看、不要塞滿 hashtag**:2-3 個相關 hashtag 就好,關鍵字自然融進句子。
7. **禁**:買讚/買追蹤、同帳號多開互導、把別人的圖改一改當自己的。這些一旦被抓,整個網域可能被降權。

---

## 步驟 3:pin 的 SEO(讓它被搜到,這才是流量來源)

Pinterest = 搜尋引擎,標題與描述的**關鍵字**決定曝光:

- **Pin 標題(≤100 字)**:放使用者會搜的詞。例:「台股全市場每週掃描|新手定投該看哪些數據」。
- **Pin 描述(200-500 字佳)**:自然寫出「台股、定期定額、0050、個股體檢、回測、存股」等長尾關鍵字 + 一句 CTA(「免費領檢查表,連結在下方」)。
- **誠信鐵則(承襲產線)**:描述**不准**出現捏造的報酬率/勝率/轉換率,不用「穩賺/保證/必賺」。守「介紹 ≠ 推薦」。pin 上的價格是真實售價,可以放。
- Alt text 也填關鍵字(無障礙 + SEO 雙贏)。

---

## 步驟 4:發佈流程(Carson 每次照做)

1. 跑產生器產最新 pin:`python youtube_channel/scripts/pinterest_pin_generator.py`
2. 到 `quant-service/output/ecommerce_ready/pinterest/` 取圖。
3. 在 Pinterest(或 Tailwind)建 pin:上傳圖 → 填**標題/描述(照步驟 3 的關鍵字)** → 貼**目標連結**(該 SKU 的 Portaly/Gumroad 商品頁,或免費工具落地頁)→ 選對應主題板 → 選 Publish later 排程。
4. 一支 pin 只填一個連結。跨板隔幾天再發。
5. 兩週後看 Business Analytics 的 impressions / outbound clicks,把表現好的主題多產幾版 fresh pin,墊底的淘汰。

---

## 對照電商計畫的 pin → 連結去向

| Pin | 商品 | 連結去向(Carson 綁) |
|-----|------|----------------------|
| `pin_S1_台股訂閱週報` | S1 台股掃描+體檢週報訂閱 | Portaly 訂閱頁 / 免費工具落地頁 |
| `pin_S2_回測數據包` | S2 全市場回測數據包 | 蝦皮 / Portaly 商品頁 |
| `pin_S3_intl_workbook` | S3 國際英文數據包 | Gumroad 商品頁 |
| `pin_T1_個股體檢系列` | 頻道磁鐵(導 YT+訂閱) | YT 影片 / 訂閱落地頁 |
| `pin_T2_定投脈絡` | 頻道磁鐵(免費檢查表) | 免費檢查表落地頁 |

---

## 紅線提醒(agent 不做、Carson 親手)
- 開通 Pinterest 帳號、認領網站、綁 Tailwind 帳密 KYC。
- **首次實際發佈前,Carson 拍板**(新對外管道)。
- agent 只負責:持續產 fresh pin 圖 + 維護這份指南。發佈與帳號操作**全程人工**。
