# Carson:卡在你手上的動作(2026-09-02,09-03 增補③)

只有你能做的:**① 送 YouTube API 提額表單(約 15 分鐘)、② 下單一條記憶體(約 5 分鐘)、③ 順手重授權 Google 憑證(約 2 分鐘)。**
兩份文件都已過 fresh-context 獨立驗證(配額包三輪、RAM 包一輪找碴視角),這頁只有動作,論證在連結裡。

## ① 送配額提額申請 — 約 15 分鐘

**為什麼急**:配額每天先歸零,**79 支做好的片發不出去**,庫存每天再 +11;審核要 2~4 週,晚一天送晚一天生效。

表單入口:https://support.google.com/youtube/contact/yt_api_form
所有欄位答案照抄:`youtube_channel/docs/yt_quota_increase_2026-09.md` §4(justification 整段直接貼)

送出前三勾(缺一不送):
- [ ] **抄官方核定值**:console.cloud.google.com → 專案 `claude-morning-report-498407`(專案編號應為 **524513894332**;Console 上兩個都看得到,**兩個都對上**才是主頻道那個專案 —— ch2/ch3 是另一個專案 881902283633,別抄錯)→ IAM 與管理 → 配額 → YouTube Data API v3 "Queries per day" → 把 Google 顯示的數字填進表單 "Current daily quota"(不要填我們自己的記帳數)
- [ ] **用 Owner 帳號登入**:crayray86@gmail.com
- [ ] **隱私政策 URL 還活著**:沿用上輪過稽核的那個公開網址,點開確認

## ② 買記憶體 — 約 5 分鐘

**買什麼**:原價屋 → **UMAX DDR5-5600 SO-DIMM 16GB,NT$6,300**(筆電條;千萬別買成桌機 UDIMM)。到手插空著的 ChannelB 槽即可,32GB 對稱雙通道。

**不買會怎樣**:現在 16GB 單通道,可用記憶體**已經在**間歇跌破渲染守門的 2,000MB 門檻(09-02 實測一度只剩 1,207MB)——渲染負載由**日產量**決定(目前毛產出均值 ~19/日、尖峰 29),**不是提額後才會來**,所以這是現在進行式的節流、不是未來風險;而且 DRAM 行情單向上行,再拖一個月估多花 NT$300~700(此為偏高端推估、漲勢在放緩,但方向確定)。

完整論證與比價:`docs/ram-upgrade-decision-2026-09.md`

## ③ 重授權 Google 憑證 — 約 2 分鐘(你人已在機器前,順手)

`scripts/google_token.json` 的 refresh token 已失效(invalid_grant)——**早晨日報(/morning)的 Gmail+行事曆下次跑必炸**,信箱證據查證路也斷了。
在專案目錄跑:`python scripts/google_auth_setup.py` → 瀏覽器跳出 → 用 **crayray86@gmail.com** 點同意即可。

---
三件互不相依,順序隨意。做完任一件跟任一個 session 說一聲即可。
