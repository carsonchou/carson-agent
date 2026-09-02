# Carson:卡在你手上的兩個動作(2026-09-02)

只有你能做的兩件:**① 送 YouTube API 提額表單(約 15 分鐘)、② 下單一條記憶體(約 5 分鐘)。**
兩份文件都已過 fresh-context 獨立驗證(配額包三輪、RAM 包一輪找碴視角),這頁只有動作,論證在連結裡。

## ① 送配額提額申請 — 約 15 分鐘

**為什麼急**:配額每天先歸零,**79 支做好的片發不出去**,庫存每天再 +11;審核要 2~4 週,晚一天送晚一天生效。

表單入口:https://support.google.com/youtube/contact/yt_api_form
所有欄位答案照抄:`youtube_channel/docs/yt_quota_increase_2026-09.md` §4(justification 整段直接貼)

送出前三勾(缺一不送):
- [ ] **抄官方核定值**:console.cloud.google.com → 專案 `claude-morning-report-498407` → IAM 與管理 → 配額 → YouTube Data API v3 "Queries per day" → 把 Google 顯示的數字填進表單 "Current daily quota"(不要填我們自己的記帳數)
- [ ] **用 Owner 帳號登入**:crayray86@gmail.com
- [ ] **隱私政策 URL 還活著**:沿用上輪過稽核的那個公開網址,點開確認

## ② 買記憶體 — 約 5 分鐘

**買什麼**:原價屋 → **UMAX DDR5-5600 SO-DIMM 16GB,NT$6,300**(筆電條;千萬別買成桌機 UDIMM)。到手插空著的 ChannelB 槽即可,32GB 對稱雙通道。

**不買會怎樣**:現在 16GB 單通道,可用記憶體會間歇跌破渲染守門的 2,000MB 門檻——配額一核准、產線上到 18 支/日時,渲染量近乎翻倍,**記憶體就是下一個卡住產線的東西**;而且 DRAM 行情單向上行,再拖一個月估多花 NT$300~700(此為偏高端推估、漲勢在放緩,但方向確定)。

完整論證與比價:`docs/ram-upgrade-decision-2026-09.md`

---
兩件互不相依,順序隨意。做完任一件跟任一個 session 說一聲即可。
