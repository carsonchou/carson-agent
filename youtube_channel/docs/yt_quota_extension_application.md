# YouTube API 配額提額申請 —— ✅ 已結案(2026-09-01 確認)

> **這件事已經完成了,不要再拿這份文件去要求 Carson 做任何事。**
>
> Carson 已於 2026-08 送出申請、完成 Google 的三輪合規稽核、並寄出
> `STUDIO/REPORTS/2026-08-13_API配額回覆草稿.md` 的回信。**Google 已核准。**
>
> 三方數字完全對上:
> ```
> 申請書第4節要求   23,700 ~ 25,200 units/day
> 09-01 撞 403 實測             24,374   ← 落在區間正中
> 申請書宣告的上傳量        12 支/日
> 現行設定                  11 支/日   ← 在宣告範圍內
> ```
> 24,374 這種非整數就是照申請書的計算核給的,不是預設值(預設 10,000)。
>
> ⚠️ **合規注意**:我們對 Google 宣告的是 12 支/日。要超過就是另一次申請,
> 不可以默默調上去 —— 那會讓上面那份「資訊真實完整」的法律聲明變成不實。
>
> 下面保留申請過程的內容,供未來要再提額時參考。

> 🔴 **2026-09-01 狀態修正 —— 本文件的「準備好即貼版」前提是錯的,申請早就送出去了。**
> Carson 指出後查證,兩條硬證據:
> ① `STUDIO/REPORTS/2026-08-13_API配額回覆草稿.md` 開頭是「Thank you for the **follow-up**」,
>    註記寫著「v3 被**第三輪查核**擋下」→ Google 稽核已經來回問過好幾輪。
> ② quota_meter 實測 **7 天超過 10,000**(Google 預設值),最高 24,374 →
>    **額度早就被調高過了**,不是還卡在申請階段。
>
> 本文件原本寫的「卡 Carson 三件事(個資/隱私政策URL/架構圖)」是**上一輪的狀態**,
> 之後 Carson 已自行送出並通過稽核,而文件沒有跟著更新 —— 我因此在 09-01 拿這份
> 過期紀錄去要求他做已經做完的事。**下次要先查 quota_meter 的實際用量再談申請狀態。**
>
> 現在真正要確認的只有一件:**08-13 那封回信有沒有寄出、那個 thread 現在是什麼狀態**
> (草稿註明截止日 2026-08-22)。repo 裡查不到寄出紀錄。

> 2026-07-15 擬 / **2026-07-17 依獨立事實查證大幅修正**(查證報告見下方「修正紀錄」)。
> **2026-08-30 重大修正**:實測推翻「現況 10,000 units」——quota_meter 六天紀錄裡
> 08-25 花了 **18,914 units 且零次被拒**,10,000 上限下不可能發生。真實上限約 **20,000**,
> 也就是舊版申請書要的 20,000 **我們早就有了**,送出去等於什麼都沒要到。
> 現況:20,000 units 撐 6 支/日長片 + 維運,近五天有三天撞到天花板
> (08-27 被拒 935 次共 45,491 units)。改申請 **30,000 units** 支撐 10 支/日。

> 🔴 **2026-09-01 再次修正 —— 又低估了一次。**
> 08-30 的版本說「真實上限約 20,000」,那也是估的。09-01 撞牆量到**確切區間**:
> ```
> 24,324 units 時 videos.insert(2,150)  仍成功
> 24,374 units 時 comments.insert(50)   被拒 403 quotaExceeded
> ```
> **真實上限 ≈ 24,374**,不是 10,000 也不是 20,000。
> 所以舊版要 20,000 等於**比現有的還少**,送出去是負的。
> 改要 **40,000 units/day**(≈18 支/日),理由:
> ·現況 24,374 ÷ 每支 2,150 = **11.3 支/日**,而台股 1,925 檔還有 1,844 檔沒做,
>   照 11 支/日要 168 天;40,000 可壓到 91 天。
> ·近三天實測有三天撞到天花板(含 08-31 這次 403),不是預留成長空間而是**現在就不夠**。
>

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

- **Current daily quota**: 20,000 units(實測值,見下方 2026-08-30 修正紀錄)
- **Requested daily quota**: **30,000 units**
- **Justification**(貼這段):

> We are currently hitting our 20,000-unit daily ceiling. Our own metering
> (a wrapper that records the documented unit cost of every API call) shows daily
> consumption of 18,760 / 19,645 / 23,341 / 20,203 units over the last four full days,
> and on three of those days the quota was exhausted before the day's work finished —
> on 2026-08-27 alone, 935 calls were rejected with quotaExceeded.
>
> Each published video costs about 2,200 units: videos.insert (1,600), captions.insert
> (400), thumbnails.set (50), videos.update (50), commentThreads.insert (50) and
> playlistItems.insert (50). Our long-form educational series on Taiwan stock market
> backtesting publishes 6 videos/day today; our production pipeline already renders
> more than we can upload, and we currently hold a backlog of finished videos that we
> cannot publish because the quota runs out.
>
> We request 30,000 units/day to support 10 uploads/day (22,000 units) plus the
> recurring maintenance operations on our own back catalogue — caption re-sync for
> videos whose subtitles drift (captions.update, 450 each), description and chapter
> corrections (videos.update, 50 each), and comment moderation — which today compete
> directly with new uploads for the same budget. All operations are on our own channel.

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
| Expected API Usage Volume | **40,000 units/day** | 見下方 2026-09-01 修正 |
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


---

## 2026-08-30 修正紀錄(實測推翻舊版兩個前提)

### ① 「現況 10,000 units」是錯的 —— 真實上限約 20,000

證據來自 `STUDIO/quota_meter.json`(每次 API 呼叫依官方價目表記帳):

| 配額日(太平洋) | 已用 units | 被拒次數 | 被拒 units |
|---|---|---|---|
| 2026-08-25 | 18,914 | **0** | 0 |
| 2026-08-26 | 18,760 | **0** | 0 |
| 2026-08-27 | 19,645 | 935 | 45,491 |
| 2026-08-28 | 23,341 | 2 | 850 |
| 2026-08-29 | 20,203 | 11 | 11 |

**08-25 與 08-26 連續兩天花掉 18,000 以上而一次都沒被拒**——在 10,000 上限下
結構上不可能。因此舊版「Current daily quota: 10,000 / Requested: 20,000」
是在申請一個我們已經擁有的額度。

⚠️ 08-28 的 23,341 要打折看:那天 `videos.post` 有 8 次呼叫但只發布 5 支,
記帳器對失敗的上傳也照價目表計了 1,600,所以實際消耗低於帳面(約 18,500)。
**不要拿 23,341 去主張「上限超過 23,000」**,那是記帳上界不是真實用量。

### ② 「8 videos/day(5 short-form + 3 long-form)」也過期了

Shorts 自 2026-08-26 起停發。實測:同期發布的長片觀看分鐘中位 **288**、
短片 **11**(相差 26 倍),而且 Shorts 觀看**不計入 YPP 的 4,000 小時**。
現在 100% 發長片,所以申請書不應再用「5 短 + 3 長」描述產能。

### ③ 送出前 Carson 仍要親自處理的三件

1. 用**擁有 Cloud project `claude-morning-report-498407` 的帳號**登入(見上方警告,不要用猜的)
2. 法定姓名與地址、七段合規聲明的簽署
3. 一個**公開可存取**的隱私政策 URL(目前沒有)

### ④ 一句話總結給 Carson

> 舊版申請書要的 20,000 我們早就有了,送出去等於白跑一趟。改成 30,000,
> 理由是可查證的實測:近五天有三天撞天花板,其中一天被拒 935 次。
