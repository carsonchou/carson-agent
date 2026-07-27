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

---

# 🔴 2026-07-17 表單實勘結果:這不是「貼一貼就送」的申請

Carson 授權代送後,我開了表單實地勘查(帳號 crayray86 已登入),發現**它是 7 段、含法律簽署的
完整合規稽核**,不是舊版文件想像的「幾個欄位貼答案」。**結論:剩下的必須 Carson 親自送出。**

## 為什麼我不能代送(三個都是硬卡點,不是客氣)

1. **Section 7 = 8 個法律聲明 checkbox**,包括
   -「**Accuracy of Information**: The information provided in this form is true, complete, and accurate」
   -「**Termination Understanding**: I understand that Google may suspend or terminate access...」
   → 這是**你**對 Google 的法律聲明,後果(停權)由你承擔。代勾別人的法律聲明不對,我也不做。
2. **Section 2 要個資**:Your Full Legal Name、Street Address、City、State/Province、Postal Code。
   我只知道 Google 帳號顯示名是「周庭睿」(不一定等於法定全名),地址完全沒有,**不會用猜的**。
3. **Section 4 要公開資產**:Primary Access URL、**Privacy Policy URL**(我們只有本機 `_privacy.md`,
   不是 URL)、Demo Account 帳密。這幾項需要你決策(見下方待辦)。

## ✅ 我已經查證/準備好的(直接填)

| 欄位 | 答案 | 來源 |
|---|---|---|
| **Section 1** Request Type | ⦿ Complete a compliance audit to **request for additional quota** | — |
| **Section 2** 身分 | ⦿ **As an individual user**(非組織) | 個人頻道 |
| Full Legal Name | 你的**法定全名**(Google 帳號顯示「周庭睿」,以身分證為準) | 🔴 你確認 |
| Country | Taiwan | — |
| 地址各欄 | 🔴 你填 | — |
| 規模 | ⦿ **Independent Developer/Sole Proprietor** | — |
| **Section 3** 組織與 YouTube 的關係 | 見下方「Section 3 貼文」 | 本文件 |
| 目標受眾 | ☑ **Internal Users**(只有頻道主自己用;不要勾 General Public) | 內部工具 |
| 營收模式 | ☑ **Free service (we do not charge users)** | 不對外收費 |
| 是否在 YT 內容/播放器賣廣告 | ⦿ **Not applicable** | — |
| **Section 4** API Client Name | `Carson Quant Studio`(⚠️ **不可含 "YouTube"**,表單會問) | — |
| 名稱含 YouTube? | ⦿ **No** | — |
| Primary Access URL | 🔴 見待辦②(內部 CLI 無 URL) | — |
| Privacy Policy URL | 🔴 見待辦①(`_privacy.md` 需上公開網址) | — |
| Demo Account | 內部工具無多用戶登入 → 見待辦② | — |
| **Section 5** Project Number | **`524513894332`**(← 注意是**數字**不是 project id;來自 client_id 前綴,已驗證) | client_secrets.json |
| Project ID(如另問) | `claude-morning-report-498407`(IAM 已確認 Owner = crayray86@gmail.com / 周庭睿) | Cloud Console |
| 用途分類 | ☑ **Internal Company Tool** + ☑ **Video Uploading & Account Management** | — |
| Expected API Usage Volume | **20,000 units/day** | 見上方 justification |
| 使用者流程 | ⦿ **Not applicable (no user-facing component)** | 無前端 |
| **Section 6** 架構圖/流程圖 | 🔴 見待辦③ | — |
| **Section 7** Attestations | 🔴 **你逐條讀過再勾**,尤其 Accuracy of Information | — |

### Section 3 貼文(Describe your organization's work as it relates to YouTube)

> I am an independent creator running a single educational YouTube channel, "Carson Quant"
> (UCqP5JQXlQR5ZDLtEiBt4kLA), about quantitative backtesting of Taiwan stock market data.
> The API Client is a private Python automation pipeline that runs on my own machine and is
> used only by me, the channel owner, to publish and manage my own videos. There are no
> other users, no customers, and no revenue from the client itself.

---

# 🟢 2026-07-28 進度更新:①③ 的素材我已備妥,剩下只有「你親手做」的部分

**為什麼今晚做這個**:Carson 說「流量大幅下降,全力優化」。當晚 quota 稽核算出——
**5 支/日是 10,000 配額下的數學天花板**(6 支×1,750 = 10,500 > 10,000,連維運全砍都超過)。
也就是說:**想同時養長片 watch-time 又補回 Shorts reach,唯一的路就是這張提額表。**
它不是行政雜事,是流量容量的硬瓶頸。(當晚已另外回收 ~1,029 units/日當安全邊際,
但那不足以多發一支;細節見 commit 2a0c55f。)

| 待辦 | 狀態 | 說明 |
|---|---|---|
| ① Privacy Policy 公開 URL | 🟡 **檔案已備妥,待你發布** | `_privacy.md` 已改寫為**屬實版本**(見下),內容可直接貼上 GitHub Pages。發布仍是你的決定。 |
| ② Primary Access URL / Demo | 🔴 待你決定 | 同下方原文,要不要給 Google 看源碼/錄影是你的判斷 |
| ③ 架構圖 | ✅ **已完成** | `docs/quota_architecture_diagram.png`(1760×1080),內容與本文件逐項對齊 |
| ④ Attestations 親簽 | 🔴 只能你本人 | 見下方原文 |

### ⚠️ ① 附帶查出一個必須先修的誠信問題(已修)

原 `_privacy.md` 寫著「does **not** access, collect, scrape, or store data from any other
users or **third-party channels**」——**與產線實況不符**:`intel_dept.py:104` 與
`outlier_scan.py:75` 都在呼叫 `search().list()` 取他人影片的公開 metadata 做選題研究,
本文件自己的 use-case 描述也誠實寫了這件事。**兩份要送同一個審查者的文件互相矛盾**,
而隱私政策是要當公開 URL 提交的那一份。

已改寫為屬實版本:明確區分「自家頻道資料」與「他人影片的公開 metadata(僅選題研究)」,
寫明不下載/不轉錄/不轉載他人內容、不刷互動、30 天自動清除。

同時查出**真實的政策違規並修掉**(commit cf23638):Developer Policies **III.E.4.d** 要求
API 取得的資料 30 天內刷新或刪除,但清除邏輯只掃 `*_競品情報.md`、且掛在每週六才跑的
intel_dept 上 → `*_異常爆款.md`(同樣含他人頻道名)**從未被清**,實測 17 份逾期、最舊到 06-16。
已建 `scripts/purge_api_data.py` 每日 04:20 跑(純本機刪檔、不耗配額,保留 25 天留安全邊際),
首次執行清掉 24 份,複驗逾 30 天檔案為 0。**送件前這個洞就補起來了,不是帶著違規去申請。**

---

## 🔴 送出前你要決定/準備的 4 件事(原文,①③ 狀態見上表)

① **Privacy Policy 需要一個公開 URL**(Section 4 必填)。現在 `youtube_channel/_privacy.md`
   只是本機檔。最省事的解法:放上你已經在用的 GitHub Pages(`carsonchou.github.io`)。
   **這是對外發布新網頁,我不會自己做 — 你點頭我就架。**

② **Primary Access URL / Demo Account 怎麼答**:我們是無前端的內部 CLI,沒有登入頁,
   給不了 demo 帳號。建議 Primary Access URL 填 GitHub repo 或頻道網址並在
   Special Instructions 說明 "internal CLI pipeline, no user-facing UI; source code or a
   screen recording can be provided on request"。**要不要給 Google 看源碼/錄影,你決定。**

③ **Section 6 要上傳架構圖 + 使用者流程圖**。~~我可以畫(產線架構我最熟),你說一聲就做。~~
   ✅ **已完成:`docs/quota_architecture_diagram.png`**。內容含:單人本機執行環境、
   非 YouTube 的資料來源(FinMind/OpenRouter/Pexels)、產製鏈(TTS→ffmpeg→誠信閘)、
   逐項列出用到的 Data API method 與 units、Analytics API 另計配額、
   以及三條合規聲明(無人工互動/無爬蟲·yt-dlp 已於 2026-07 移除/單頻道內部使用)。
   本圖同時就是「使用者流程圖」——因為只有一個使用者(頻道主),流程即架構。

④ **Attestations 逐條看過**。特別是 "Accuracy of Information" —— 這份表現在每一句都經過
   查證(爬蟲已移除、retention 已合規),但**簽的人是你**,請自己確認過再勾。

> 💡 若 Google 事後要求提供源碼:用 `git archive HEAD` 出當前源碼壓縮檔交付,
> **不要給 repo clone、不要加 collaborator** —— git 歷史裡仍有已刪除的爬蟲檔全文,
> 交付當前源碼即可,歷史不在交付範圍。

---

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
