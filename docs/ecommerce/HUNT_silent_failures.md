# HUNT_silent_failures — 橫向獵殺「靜默失敗」

> 獵殺人:verifier-sku2(fresh-context)｜日期:2026-07-17
> 目標病徵:**程式不壞、不報錯、看起來一切正常 —— 只是沒在做該做的事**。已咬三次(名冊 schema / `.env` 沒人讀 / 看板蓋掉 confirmed),三次全是驗證抓到、沒有一次是測試抓到。
> 排序原則:**發現得多晚 × 代價多大**,不是技術嚴重度。
> 唯讀:未改任何程式、未打外部網路、未動真 .env、未跑全掃描;所有實測都在 tmp + 假密鑰 + in-process ASGI。
> 重現:`scratchpad/hunt_tier_unknown.py`

## 戰果

**已證實 2 個(都能實測重現)｜懷疑但無法證明 2 個｜自己推翻 1 個。**

| # | 發現 | 多久才會被發現 | 代價 |
|---|---|---|---|
| **S1** | 訂閱者 `tier="unknown"` → **兩張寄送名單都排除** | 訂戶抱怨才知道(數週) | 付 149/月**永遠收不到任何一期** |
| **S2** | 商品名對不上 `match` → `sku="unknown"` → 交付信只給 **placeholder(含內部除錯字串)** | 買家抱怨才知道 | 付 990 收到一封工程師訊息 |

---

## 🔴 S1 訂閱者 tier="unknown" → 付了錢,每週報表永遠收不到,全程零錯誤(已證實)

**檔案:行號**
- `quant-service/webhook/config.py:77-88` `classify_tier()` —— 對不上金額/幣別 → 回 `"unknown"`
- `quant-service/webhook/subscribers.py:35` `TIER_RANK = {"basic":1, "full":2, "full_annual":3, "unknown":0}`
- `quant-service/webhook/subscribers.py:126-131` `export_active()` —— `if tier and TIER_RANK.get(entry.tier, 0) < want_rank: continue`

**觸發條件**:`classify_tier` 對不上 → tier="unknown" → rank=0 → **比 basic(1) 小、也比 full(2) 小** → `export_active(tier="basic")` 和 `export_active(tier="full")` **兩邊都把他 continue 掉**。
而 `export_active` 是寄送名單的**單一事實來源**(`weekly_report_v2.load_send_list` 直接呼叫它)。

**實測(in-process ASGI,真的打 `/sale-ping/portaly`)**:

| 情境 | HTTP | 記入名冊 | tier | /health | basic名單 | full名單 | 結果 |
|---|---|---|---|---|---|---|---|
| 149 TWD(對照組) | 200 | 是 | full | 1 | 1 | 1 | ✓ 收得到 |
| **金額以「分」為單位(14900)** | 200 | 是 | **unknown** | 1 | **0** | **0** | 🔴 永遠收不到 |
| **幣別寫 NTD 而非 TWD** | 200 | 是 | **unknown** | 1 | **0** | **0** | 🔴 永遠收不到 |
| **首月促銷價 49** | 200 | 是 | **unknown** | 1 | **0** | **0** | 🔴 永遠收不到 |
| **amount 欄位名不同(Portaly 待校準)** | 200 | 是 | **unknown** | 1 | **0** | **0** | 🔴 永遠收不到 |
| 1290 TWD 年繳 | 200 | 是 | full_annual | 1 | 1 | 1 | ✓ 收得到 |

**為什麼這是「靜默」的教科書案例**:每一個環節都回報成功 ——
webhook 回 **200 accepted** ✓ / 名冊寫入 `status="active"` ✓ / **`/health` 的 `active_subscribers` +1** ✓ / 金流記帳有這筆 ✓ / 開通信也寄出去了 ✓。
**唯獨每週的寄送名單裡沒有他,而且永遠不會有。** 沒有任何一行 log 說「有一位 active 訂閱者被排除在所有名單之外」。

**為什麼很可能發生(不是理論)**:`normalize.py:152-154` 自己寫著 Portaly「**官方無第一手 webhook spec……欄位名皆為暫定,上線前用真實 Portaly 測試 webhook 校準**」。`parse_portaly` 的 amount 是 `_first(d, "amount", "price", "total", default=0)` —— **欄位名猜錯就是 0**,而 0 對不上任何 tier → unknown。也就是說 **#2(`.env` 沒人讀)那個病,在 tier 這條線上又長了一顆**。

**runbook 有沒有救?** §7.2 Day-1 檢查確實叫 Carson 看「`tier` 正確」——**這是唯一的防線,而且是人肉的**。它只保護第一筆測試單;上線後 Portaly 改欄位名/Carson 開促銷價,就再也沒有人看。

**建議修法**(交給實作者,我未代修):
1. `export_active` 遇到 `tier` 不在 `TIER_RANK` 或為 `"unknown"` 的 active 訂閱者 → **print/ntfy 告警**(「有 N 位付費訂閱者因 tier 無法判定而不在任何寄送名單」),絕不無聲 continue。
2. **fail-safe 方向反過來**:tier 判不出來時,寧可**降級成 basic 也要寄**(收了錢就該給東西),而不是靜默排除。少給一段 section 的傷害,遠小於一期都收不到。
3. `classify_tier` 回 unknown 時就在 webhook 層 log 金額/幣別原值,讓校準時看得到。
4. 補整合測試:**tier="unknown" 的 active 訂閱者 → 必須出現在某張名單(或至少有告警)**。

---

## 🔴 S2 商品名對不上 → 買家收到「內部除錯訊息」當交付信(已證實)

**檔案:行號**
- `quant-service/webhook/config.py:33-47` `SKU_CATALOG` 的 `match` 關鍵字
- `quant-service/webhook/config.py:58-74` `resolve_sku()` —— 兩輪都沒命中 → 回 `{"sku_id":"unknown", "dl_env":""}`
- `quant-service/webhook/config.py:91-97` `download_url_for()` —— `dl_env=""` → 回 `None`
- `quant-service/webhook/delivery.py:44-49` `_download_block()` —— url 是 None → 回 placeholder 字串

**實測**(C1 的 match 關鍵字 = `['全市場回測','回測數據包','backtest pack','full-market backtest']`):

| Carson 在平台後台的命名 | resolve_sku | 買家收到什麼 |
|---|---|---|
| `台股全市場回測數據包 1770檔｜自適應+多空+Sharpe(xlsx+摘要)`(listing.json 正式標題) | C1_fullmarket_pack ✓ | 正常 |
| **`台股全市場數據包`**(簡化命名) | **unknown** 🔴 | placeholder |
| **`Taiwan Full-Market Data Pack`**(英文名) | **unknown** 🔴 | placeholder |
| **`【限時】1770檔數據包`**(加促銷前綴) | **unknown** 🔴 | placeholder |

**買家實際收到的信裡會出現這段**:
> （📦 下載連結為 placeholder，正式打包上線後此處帶實際下載連結；**設定環境變數 ECOMMERCE_DL_*** 即可帶入 SKU=unknown 的真連結）

一位付了 NT$990 的買家,收到的是**寫給工程師看的內部訊息**。**Carson 端零告警**(ledger 裡 sku_id 會記成 `unknown`,但沒有人會去看)。

**⚠️ 現況更緊**:我在載入 webhook 模組時,它自己印出 ——
```
[webhook] 下載連結: ECOMMERCE_DL_T1=MISSING  T2=MISSING  C1=MISSING  C2=MISSING
[webhook] dry_run=False (SMTP 齊備 → 交付信會真寄)
```
→ **SMTP 已備妥(會真寄)、但四個下載連結全部 MISSING**。也就是說**現在若真有人下單,他一定會收到 placeholder 信,而且是真的寄出去**。這是 runbook §2.2 要 Carson 填的步驟,但**系統不會攔他**:沒有任何檢查說「DL 沒設就別開賣」。
(公允:`_download_block` 的設計本意是「不寄假連結」,這點是對的——不寄死連結比寄死連結好。問題是**沒告警**、且**內部字串外洩給客戶**。)

**建議修法**:
1. `resolve_sku` 回 unknown 時 → **ntfy 告警 Carson**(「有一筆成交的商品名對不上任何 SKU:『{product}』」),他才能當場改後台命名或補 match。
2. placeholder 文案**改成給客戶看的話**(「你的下載連結我們會在 24 小時內以另一封信寄給你」),別把 `ECOMMERCE_DL_*` 這種內部變數名寄給買家。
3. 開賣前檢查:`ECOMMERCE_DL_*` 未設 → webhook 啟動摘要**升成紅字警告**(現在只是印 MISSING,和其他行長得一樣)。
4. `match` 改成「代號優先」(Gumroad/Portaly 都能設商品代號),別只靠中文標題模糊比對。

---

## 🟡 懷疑但無法證明

- **Gumroad 訂閱首期 vs 續期判錯**:`normalize.py:62` `first = str(form.get("is_recurring_charge","")).lower() in ("", "false")` —— **欄位缺席時 `""` 也算 first** → 每次續扣都可能被判成 `SUB_NEW`。程式自己註解承認「Gumroad 對訂閱首期 vs 續期無獨立旗標……**暫無官方鍵 → 待校準**」。後果:續訂被當新訂(名冊重複開通事件、營運數字失真),但**不影響交付**故較輕。**無法證明**:我沒有真實 Gumroad 訂閱 payload,不能確認該欄位是否存在。
- **`load_send_list` 的 import fallback 分歧**:`weekly_report_v2.py:1404-1409` 優先用 `webhook.subscribers.export_active`,import 失敗才走「等價的本地讀取」。兩份實作若日後分歧(例如只改了 webhook 那邊的 TIER_RANK),fallback 會**靜默地用舊語意**。已有整合測試 `test_integration_send_list.py` 釘住主路徑,但**沒有測試釘住「fallback 路徑與主路徑等價」**。**無法證明**:目前兩者行為一致,這是未來的腐爛風險而非現有 bug。

## ⚪ 我自己推翻的(誠實列出,避免製造發現數)

- **「週報從來沒有真的寄給訂閱者」**:`ecommerce_weekly.py:220` 確實硬寫 `{"sent": False, "dry_run": True}`,全 repo 也**沒有任何路徑**真的把週報寄給訂閱者。我一度要報成最毒的一個 —— **但它不是靜默失敗**:`ecommerce_weekly.py:260` 的摘要明寫「**旗艦週報 v2(交付 dry_run,**未真寄**)**」,Carson 每週收到的 ntfy 都會看到這句。這是**誠實揭露的已知缺口**,不是病徵。
  (但有個相鄰問題屬於 runbook 而非程式碼:GO_LIVE_RUNBOOK §7.2 叫 Carson 用「週報段『寄送名單』人數 +1」當交付驗證 —— 那個檢查會過,而交付是 no-op。已在 `VERIFY_REPORT_runbook.md` 反映。)

---

## 第 6 條:「只測有利方向」的測試清單

這條果然最肥 —— **不是測試沒寫,是兩端各自測對了、中間的縫沒人測**:

| 測試 | 測了什麼 | 沒測什麼(壞的那個方向) |
|---|---|---|
| `test_normalize.py:103-108` `test_classify_tier` | `classify_tier(500,"TWD") == "unknown"` ✓ **有測 unknown 會產生** | **產生 unknown 之後會怎樣**——沒有任何測試接下去問「這位訂閱者還收得到報表嗎」 |
| `test_subscribers.py:59-61` `export_active` 分層 | basic/full/全 active 的過濾 ✓ | **名冊裡有 tier="unknown" 的 active 訂閱者時**,他被兩張名單都排除 → 無測試 |
| `test_integration_send_list.py` | export→load 形狀對得上 ✓(#1 的補丁) | 只釘 schema,**沒釘「所有付費 active 訂閱者都在某張名單裡」這個業務不變量** |
| `test_gauge_history.py` `test_intraday_then_confirmed_keeps_confirmed` | 盤中→收盤 保留 confirmed ✓ | **收盤→盤中**(會壞的反方向)—— 這就是 #3 漏掉的原因(已回報) |
| webhook `test_app.py` 各平台成交 | 商品名用 `台股定投追蹤模板`(**剛好命中 match**) | **商品名對不上時** sku=unknown → placeholder 信 → 無測試 |

**共同形狀**:每個測試都用「會過的那組輸入」。`classify_tier` 那個甚至**測到了 unknown**,但測試在產生 unknown 的那一刻就停了 —— **沒有人問「然後呢」**。#1/#3/S1 全是死在這個「然後呢」。

---

## 根因(一句話)

**這個 codebase 把「查不到 / 對不上 / 沒設定」一律當成合法的空值往下傳(`unknown` / `[]` / `None` / placeholder / dry_run),而不是當成需要有人知道的異常 —— 每一層都盡責地 fail-safe 不炸,於是整條鏈路一路綠燈地什麼都沒做。**

fail-safe 是對的(掃描器不該因為記 log 失敗而掛掉);錯的是 **fail-safe 沒有配一個「告訴人類」的出口**。三次被咬 + 這次抓到的兩個,全部符合這個公式:

> **靜默失敗 = fail-safe(對的) + 零告警(錯的) + 只測有利方向(所以沒人發現)**

**制度上的建議(比修這兩個 bug 更重要)**:立一條規矩 ——
**任何 `except` / 預設值 / `unknown` / 空清單的分支,如果它代表「本來該做的事沒做成」,就必須留下一個人看得到的痕跡**(print 至少,涉及錢/交付的一律 ntfy)。
現有程式碼裡「靜默」與「有 log」的比例大約是:`weekly_report_v2` 的降級**有** degrade 卡(對 ✓)、`append_gauge_history` 失敗**有** print(對 ✓)、但 **tier=unknown 排除訂閱者(S1)、sku=unknown 發 placeholder(S2)這兩個直接關係到「收了錢有沒有給東西」的,反而完全無聲**。
