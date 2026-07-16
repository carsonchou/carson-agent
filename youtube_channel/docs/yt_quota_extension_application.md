# YouTube API 配額提額申請(準備好即貼版)

> 2026-07-15 擬 / **2026-07-17 依獨立事實查證大幅修正**(查證報告見下方「修正紀錄」)。
> 現況:每日 10,000 units 只夠發 5 支/日(upload=1600/支),縮圖/播放清單/留言常被餓死。
> 申請 20,000 units 可支撐真實產能 8 支/日 + 完整維運。

## 申請入口
**YouTube API Services - Audit and Quota Extension Form**
https://support.google.com/youtube/contact/yt_api_form

> 🔴 **送出前必辦**:必須用**擁有 Cloud project `claude-morning-report-498407` 的帳號**登入送出,
> 否則 Google 對不上 project,輕則退件、重則被當可疑。repo 內查無任何檔案記錄擁有者帳號
> (token_manage.json 的 account 欄位是空的,google-auth 結構上不會填)。
> **Carson 請自己開 console.cloud.google.com → 選該 project → IAM → 看 Owner 是哪個帳號。不要用猜的。**
> (舊版此處寫 crayray86@gmail.com,但全 repo 零旁證,不可採信;Carson 主帳號是 moneycometomywallet@gmail.com)

(審核常見 2–4 週,期間現有配額照用)

## 表單欄位對應答案(英文,直接貼)

- **Google Cloud Project ID**: `claude-morning-report-498407`(已查證:client_secrets.json 就是這個,
  名字叫 morning-report 只是當初開來做晨間報告後來沿用,不是誤植)
- **API Client 用途類型**: Internal use only(自有頻道自動化,不服務第三方)
- **YouTube channel**: 量化阿森 Carson Quant(頻道 ID `UCqP5JQXlQR5ZDLtEiBt4kLA`,已查證四處硬編碼一致)

**Describe your API Client / use case**(貼這段):

> Our API client is a private, internal-use automation pipeline for managing our own
> YouTube channel "Carson Quant" (UCqP5JQXlQR5ZDLtEiBt4kLA). It is a Python application
> running on our own machine, used exclusively by the channel owner. It does NOT serve
> third-party users, and it does not access private data belonging to other users.
>
> Daily operations: uploading educational videos about quantitative backtesting of
> Taiwan stock market data (videos.insert), setting custom thumbnails (thumbnails.set),
> organizing videos into playlists (playlistItems.insert), updating video descriptions
> (videos.update), and moderating comments on our own videos (commentThreads.list,
> comments.insert). We also retrieve public metadata (titles, view counts) via
> search.list/videos.list for our own content-planning research; this data is refreshed
> weekly, and stored copies are automatically purged after 30 calendar days in line with
> section III.E.4.d of the Developer Policies.
>
> We comply with the YouTube API Services Terms of Service and Developer Policies: no
> artificial engagement, no scraping (all data is obtained through the official API),
> and OAuth consent is only from the channel owner's own account.

- **Current daily quota**: 10,000 units
- **Requested daily quota**: **20,000 units**
- **Justification**(貼這段):

> Current 10,000 units allow only ~5 video uploads/day (1,600 units each), leaving
> almost nothing for thumbnails, playlist management, and comment moderation — in
> practice our uploads frequently end up without custom thumbnails and our playlist
> organization is skipped once the daily quota is exhausted.
>
> Our production pipeline currently creates up to 8 videos/day (5 short-form + 3
> long-form) of educational content on Taiwan stock market backtesting and per-company
> fundamental analysis. We request 20,000 units/day to reliably upload our daily output
> (8 x 1,600 = 12,800) together with the accompanying metadata operations — thumbnails,
> playlist placement, description updates, and comment moderation (approximately
> 18,000 units total) — all on our own channel.

## 注意
- 表單會問 API Client demo/影片:內部工具可說明 "internal CLI pipeline";**被要求時**再提供
  源碼或螢幕錄影即可(舊版主動寫 "can provide source code on request",在爬蟲移除前等於自曝其短)。
- 審核期間**不要**開第二個 Cloud project 分流配額——明確違反 Developer Policies
  (III.D.1c: circumvention),被抓整組 project 停權。
- 送出後把回覆信轉存;若被要求補件(常見:要 screen recording),回信附上即可。

## 修正紀錄(2026-07-17,獨立事實查證後)

舊版原樣送出 = 對 Google 做至少兩項可當場證偽的不實陳述。逐項:

| 舊版寫法 | 問題 | 現在 |
|---|---|---|
| "no scraped data" | ❌ **不實**:`QuantArsen_IntelLearn` 排程每天 01:30/13:30 用 yt-dlp 下載別人頻道字幕+音訊(intel_dept.py:132/148),已抓 1,074 支 | ✅ Carson 拍板移除爬蟲+清資料後,此句成真,予以保留 |
| "no data storage beyond our own channel's metadata" | ❌ **不實**:即使清掉爬蟲資料,`outliers.json` 仍存別人頻道資料(走官方 API,合法但確實有存) | ✅ 改為誠實描述:公開 metadata 走官方 API 取得、每週刷新不逾期留存 |
| "All content is original and produced by us" | ⚠️ 高風險:內容為 AI 產製(LLM 腳本+TTS+自動渲染),且 playbook 設計上衍生自競品分析。非表單必填,卻扛著雙重不實風險 | ✅ 拿掉(不主動宣稱 = 不製造把柄) |
| 50,000 units / ~25 uploads/day | ❌ 前提造假:真實產能 8 支/日(crontab.txt:31)、實際發布 5 支/日、個股系列受 FinMind 限制每天只做 1 檔。46 訂閱頻道申請 25 支/日 = spam 畫像,恐觸發稽核 | ✅ 改 **20,000 / 8 支/日**,每個數字都可查證;2 倍溫和提額遠比 5 倍容易過 |
| "can provide source code on request" | ❌ 自殺條款:源碼裡就是 yt-dlp,Google 一要就當場自證 | ✅ 改為被動(被要求再給);爬蟲移除後源碼已乾淨 |
| 用 crayray86@gmail.com 登入 | ⚠️ 全 repo 零旁證,不可採信 | 🔴 **待 Carson 到 Cloud Console → IAM 確認 Owner** |

查證通過、原樣保留:Project ID、頻道 ID、"internal use / not serving third parties"
(tg_magnet 服務觀眾但完全不碰 YT API)、"no artificial engagement"(comment_dept 只回自己影片的留言)。
