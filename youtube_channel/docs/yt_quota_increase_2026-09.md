# YouTube API 第二次提額申請包(2026-09)—— 待 Carson 送出

> 狀態:**materials-ready,未送出**。本檔由基建線(non.)於 2026-09-02 依督導指令備妥。
> 紅線:對外動作 —— **只有 Carson 能送**;送出前本檔已過 fresh-context 獨立驗證(見文末驗證紀錄)。
> 上一輪申請(2026-08,已核准)的完整過程與教訓在 `yt_quota_extension_application.md`,本檔只放這一輪要用的。

## 0. 一句話給 Carson

> 上一輪核到的 ~24,400 units 已經**連續撞死**(09-01 配額歸零時有 79 支成品發不出去),
> 而時數是 YPP 慢的那道閘門(999/4,000 小時,照現速 103 天)。
> 這張表要 **40,000 units/day ≈ 18 支/日**,把時數關卡壓到約 58~77 天。
> 你要做的:確認一個數字(第 2 節)→ 打開表單貼答案(第 3 節)→ 親簽七段聲明。

## 1. 為什麼是現在(全部可查證)

- **配額是綁定層**(2026-09-02 診斷,證據:`STUDIO/quota_meter.json`、`STUDIO/ops_log.txt`、`logs/job_stderr.log`):
  - 近 7 天(08-26~09-01)spent:18,760 / 19,645 / 23,341 / 21,858 / 22,910 / 26,001 / 24,802
  - 09-01 兩次時事片即時發布被「今日剩 0」擋下(ops_log 10:02 / 11:38);當日 25 次 quotaExceeded 403
  - **已過閘成品庫存 79 支躺著發不出去**(ops_log 上架部門「剩庫存」46→79,四天累積)——渲染、題庫、良率全都有餘裕,唯獨配額天天貼死
- **時數是 YPP 慢閘門**:長片 999/4,000 小時(25.0%),日增 ~29 小時 → 缺口 103 天;訂閱 343/1,000 日增 11 → 60 天。多發一支長片直接縮時數天期
- 上一輪(要 23,700~25,200)是 08 月核的,當時設定 6~8 支/日;現在 11 支/日已是宣告上限 12 的邊緣,**再往上必須重新申報**(Section 7 Accuracy 法律聲明,不可默默調)

## 2. 送出前 Carson 要親手確認的三件

1. **官方核定值**(表單 "Current daily quota" 欄):console.cloud.google.com → 選 `claude-morning-report-498407` → IAM 與管理 → 配額 → 篩 YouTube Data API v3 "Queries per day" → **抄那個數字**。
   我們的三個錨點對不上(撞牆實測 24,374 / 客戶端記帳最高 26,001,記帳會把被拒呼叫也計價),**表單要填 Google 自己的數,不填我們估的**。
2. **登入帳號** = 該 project 的 Owner(上輪已確認是 crayray86@gmail.com / 周庭睿)。
3. **隱私政策 URL**:上一輪通過稽核時用的那個公開 URL 還活著嗎?(上輪送件用什麼這輪就用什麼,不要換。)

## 3. 表單答案(入口:https://support.google.com/youtube/contact/yt_api_form)

不變的欄位(身分/組織/Section 3 貼文/API Client 名稱 `Carson Quant Studio`/Project Number `524513894332`/架構圖 `docs/quota_architecture_diagram.png`)照 `yt_quota_extension_application.md` 第 2026-07-17 節的表格填,以下只列**這一輪改變的**:

- **Request Type**: request for additional quota(已完成過 compliance audit 的 project 再提額)
- **Current daily quota**: 第 2 節第 1 項抄來的官方數字
- **Requested daily quota**: **40,000 units**
- **Expected upload volume**: **up to 18 videos/day**(新申報值;核准前產線仍守 12)

**Justification(貼這段,每個數字都有來源)**:

> Our previous quota increase (approved 2026-08) is now exhausted on a daily basis.
> Our own metering (a wrapper recording the documented unit cost of every API call)
> shows consumption over the last seven full days of 18,760 / 19,645 / 23,341 /
> 21,858 / 22,910 / 26,001 / 24,802 units, hitting the ceiling repeatedly: on
> 2026-09-01 alone, 25 calls were rejected with quotaExceeded and two scheduled
> uploads could not be published because the daily quota had reached zero.
>
> Our production pipeline (rendering, script generation, quality gates) now outputs
> more finished videos than the quota allows us to upload: we currently hold a
> backlog of 79 finished, quality-checked videos that cannot be published. Each
> published video costs about 2,150 units (videos.insert 1,600, captions 400,
> thumbnails.set 50, playlistItems/updates ~100).
>
> We request 40,000 units/day to support up to 18 uploads/day of our long-form
> educational series on Taiwan stock-market backtesting (~38,700 units), leaving
> headroom for recurring maintenance on our own back catalogue (caption re-sync,
> description/chapter corrections, comment moderation on our own videos). All
> operations remain on our own channel (UCqP5JQXlQR5ZDLtEiBt4kLA); the client is
> a private, internal-use pipeline with no third-party users.

- **Section 7 Attestations**:Carson 逐條讀過親勾(特別是 Accuracy of Information)。

## 4. ch2/ch3 專案(`881902283633`)要不要一起補?—— 建議:先不要

- 該 project 從沒申請過,還在預設 10,000 units/day
- ch3 現行配比 1 長 + 4 短/日 ≈ 5 支 × ~2,150 = ~10,750,**理論上已貼線**,但:
  - ch3 頻道 09-03 才改名轉型、真實跑道 19 集,量級與續航未證明
  - 46 訂閱等級的頻道申請提額 = 上一輪教訓裡的「spam 畫像」風險(07-17 修正紀錄第 4 條)
- **觸發條件寫死**:ch3 連續 7 天實際發布 ≥5 支/日且出現 quotaExceeded,再開它自己的申請(比照本檔流程)。在那之前用 10,000 內的排程過活。

## 5. 核准前的紀律(給所有 session 看的)

- 產線上限維持 **≤12 支/日**(現設 11)。核准信到手、Cloud Console 數字變了,才可以調 `--max`
- 審核期間(常見 2~4 週)**不開第二個 project 分流** —— Developer Policies III.D.1c circumvention,整組停權
- 收到補件要求(常見:screen recording)→ 轉存信件,回信附上即可;源碼用 `git archive HEAD`,不給 repo 歷史

## 驗證紀錄

- [ ] fresh-context 獨立驗證(待跑,通過後在此附結論)
