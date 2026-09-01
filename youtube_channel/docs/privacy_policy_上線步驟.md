# 隱私政策上線步驟(Carson 親手,約 5 分鐘)

## 為什麼需要這個

YouTube API 提額申請表有一格要求 **公開可存取的隱私政策 URL**。
這是 `docs/yt_quota_extension_application.md` 裡三個「卡 Carson」項目之一,
也是目前唯一能讓每日發布量突破 7 支的路徑
(配額實測上限約 20,000 units、每支片成本 2,200,見 memory `yt-marginal-value-per-video`)。

## 檔案

`youtube_channel/docs/privacy_policy.html` —— 已寫好,單一 HTML 檔、無外部相依。

**內容是照產線實況寫的,不是罐頭範本。** 每一條都可以對到程式碼:

| 政策寫的 | 對應事實 |
|---|---|
| 他人資料 25 天自動刪除 | `scripts/purge_api_data.py` `RETENTION_DAYS = 25`,排程 04:20 |
| 留言者名稱/頻道 ID 不落檔 | `STUDIO/comment_replied.json`、`comment_watchdog_seen.json` 實查:**只有留言 ID**;`authorDisplayName` 只在 `comment_dept.py` / `comment_watchdog.py` 記憶體內用 |
| 不做爬蟲 | 2026-07 已全面移除 yt-dlp 抓競品字幕(memory `yt-scraper-tos-removal-2026-07`) |
| 不送 YouTube 使用者資料給 LLM | 送給 LLM 的是選題說明 + 台股行情,不含留言內容 |
| 不製造虛假互動 | 誠信紅線,memory `max-ambition-money-mode` |

## 送出前必填(只有一處)

第 8 節 **Contact** 目前寫著 `[Carson 請填入要公開的聯絡信箱]`。
**要填一個你願意公開的信箱** —— 這個頁面是公開的,Google 稽核員與任何人都看得到。
建議用 `moneycometomywallet@gmail.com` 之外的對外信箱,或開一個 `contact@` 轉寄。

## 上線(擇一)

### A. 放進既有的 GitHub Pages(推薦,你已經有 carsonchou.github.io)

```bash
# 到你的 pages repo(GymLog 部署的那個)
cp /d/carson-agent/youtube_channel/docs/privacy_policy.html <pages-repo>/privacy.html
cd <pages-repo>
git add privacy.html
git commit -m "add privacy policy for YouTube API audit"
git push
```
上線後的 URL:`https://carsonchou.github.io/privacy.html`
(若 pages repo 是 project pages 而非 user pages,URL 會多一層 repo 名,以實際為準)

### B. 開一個新的 public repo 走 Pages

新建 public repo → 上傳這個檔改名 `index.html` → Settings → Pages → Source 選 `main` / root。

## 上線後要做的驗證(不要跳過)

1. **用無痕視窗**開那個 URL —— 確認未登入也看得到(Google 稽核員是外人)
2. 確認頁面標題與「Last updated」正確顯示
3. 把 URL 貼回 `docs/yt_quota_extension_application.md` 的表單欄位區

## 還卡著的另外兩件

1. **登入帳號**:必須用擁有 Cloud project `claude-morning-report-498407` 的帳號送出。
   到 console.cloud.google.com → 選該 project → IAM → 看 Owner 是誰。**不要用猜的**
   (舊版文件曾寫 crayray86@gmail.com,但全 repo 零旁證)。
2. **法定姓名、地址與七段合規簽署**:只有本人能簽。

## 一句話

隱私政策這一格我已經備好,你只要填一個公開信箱 + push,三個卡點就剩兩個。
