# YouTube API 配額提額申請(準備好即貼版)

> 2026-07-15 準備。現況:每日 10,000 units 只夠發 5 支/日(upload=1600/支)。
> 提額到 50,000 units 可支撐 ~25 支/日 + 完整縮圖/播放清單/留言維運。

## 申請入口
**YouTube API Services - Audit and Quota Extension Form**
https://support.google.com/youtube/contact/yt_api_form

(用 crayray86@gmail.com 登入 Google 後填;審核常見 2–4 週,期間現有配額照用)

## 表單欄位對應答案(英文,直接貼)

- **Google Cloud Project ID**: `claude-morning-report-498407`
- **API Client 用途類型**: Internal use only(自有頻道自動化,不服務第三方)
- **YouTube channel**: 量化阿森 Carson Quant(頻道 ID `UCqP5JQXlQR5ZDLtEiBt4kLA`)

**Describe your API Client / use case**(貼這段):

> Our API client is a private, internal-use automation pipeline for managing our own
> YouTube channel "Carson Quant" (UCqP5JQXlQR5ZDLtEiBt4kLA). It is a Python application
> running on our own machine, used exclusively by the channel owner. It does NOT serve
> third-party users and does NOT access any data belonging to other users or channels.
>
> Daily operations: uploading original educational videos about quantitative
> backtesting of Taiwan stock market data (videos.insert), setting custom thumbnails
> (thumbnails.set), organizing videos into playlists (playlistItems.insert), updating
> video descriptions (videos.update), and moderating comments on our own videos.
>
> All content is original and produced by us. We fully comply with YouTube API
> Services Terms of Service and Developer Policies: no artificial engagement, no
> scraped data, no data storage beyond our own channel's metadata, OAuth consent is
> only from the channel owner's own account.

- **Current daily quota**: 10,000 units
- **Requested daily quota**: 50,000 units
- **Justification**(貼這段):

> Current 10,000 units allow only ~5 video uploads/day (1,600 units each) leaving
> almost nothing for thumbnails, playlist management, and comment moderation. Our
> channel publishes original short-form and long-form educational videos daily as a
> series (per-stock fundamental checkup series covering ~1,900 Taiwan-listed
> companies, one episode each). We request 50,000 units/day to support ~25 uploads/day
> plus the accompanying metadata operations, all on our own channel.

## 注意
- 表單會問 API Client demo/影片:內部工具可說明 "internal CLI pipeline, can provide
  source code or screen recording on request"。
- 審核期間**不要**開第二個 Cloud project 分流配額——明確違反 Developer Policies
  (III.D.1c: circumvention),被抓整組 project 停權。
- 送出後把回覆信轉存;若被要求補件(常見:要 screen recording),回信附上即可。
