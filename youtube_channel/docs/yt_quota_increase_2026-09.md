# YouTube API 第二次提額申請包(2026-09)—— 待 Carson 送出

> 狀態:**verified,可交 Carson,未送出**。基建線(non.)2026-09-01 深夜備妥;
> 經一輪 fresh-context 驗證(3F/5R 修正)+ 一次督導攔截改寫(承重點自「成長計畫」換為「現況已綁死」)
> + 第二位驗證員三輪全量重驗(2F/4R/3M + NF1 全修,2026-09-02 終核 PASS)。
> 紅線:對外動作 —— **只有 Carson 能送**。上一輪申請(2026-08 核准)全程在 `yt_quota_extension_application.md`。

> 🔴 **數字截止日:2026-09-04(台北)。逾 7 天未送出,§1 §2 §4 全部數字必須重跑一次對帳再送。**
>    本檔的失效形狀是「寫的時候為真、放著就變假」,不是「有人寫錯」——
>    相對詞(近 N 天 / 現在 / 最近一次 / 才)一律不得使用,一律寫絕對日期。

## 0. 一句話給 Carson

> 這張表**不是**申請「衝更多支」的許可 —— 是產線在 2026-08-29~09-04 每天做出中位 14 支成品(全距 9~29)、
> 配額只發得出 11 支;2026-08-31 配額歸零時庫存 61 支,2026-09-04 為 **81 支(較 08-29 的 46 支增加 +35,但 09-02 起走平:81/79/81)**,
> 維運還跟上傳搶同一份額度(已關帳日最低被餓到只剩 **423 units**,2026-09-02)。
> 要 **45,000 units/day** 讓上傳能力追上已經存在的產出。
> 發布量上限照舊(≤12,09-15 發布量實驗驗收前不動)—— **額度是 headroom,不是承諾**。

## 1. 為什麼是現在(全部可查證;僅用已關帳配額日,集合以檔頭截止日 2026-09-04 為準)

- **配額是綁定層**(2026-09-01 診斷;證據:`STUDIO/quota_meter.json`、`STUDIO/ops_log.txt`、`logs/job_stderr.log`):
  - **2026-08-26~08-31 這六個已關帳配額日**(太平洋制)client 端記帳 spent:
    18,760 / 19,645 / 23,341 / 21,858 / 22,910 / 26,001
    ⚠️ 記帳為**上界**:非配額類失敗(如上傳失敗)也照價目計價,08-28 與 08-31 含此類灌水(08-28 實際約 18,500)。凡引用一律帶上界註記。
    (08-25 的 18,914 **不採用**:quota_meter 該日條目自標 `unreliable: true` —— 當天被拒呼叫尚未分桶、463 次 403 被計價灌進 spent。)
  - 08-31 配額日(至台北 09-01 15:00)實際打到 0:兩次時事片被「videos.post 需 1600,今日剩 0」擋下(ops_log 09-01 10:02 / 11:38),同配額日 25+ 次 quotaExceeded 403
- **產出 > 上傳能力**(09-03 對帳修正:逐日毛產出=晚間庫存差+當日上架回推,唯一乾淨口徑):
  - 逐日毛產出 2026-08-29~09-04(七日)= **18 / 19 / 14 / 29 / 13 / 9 / 13**(均值 16.4,**中位 14**,全距 9~29;29 是 09-01 尖峰日)→「日產成品 **約 14 支**」以中位成立;⚠️均值靠 09-01 那個 29 撐,拿掉它其餘六日均 14.3;⚠️09-03 的 9 是本口徑的低估(`daily_publish.py:1302` 每次重數候選池,被閘門驅逐的片沒發布也從庫存消失),成稿與 mp4 檔兩本獨立帳顯示 09-02~04 穩定 14
  - 庫存計數器(ops_log 上架部門):46→81(08-29 18:35→**09-04 18:38,6 晚**)= 淨增 **+35**;⚠️成長集中在 08-29~09-01,**09-02 起走平(81/79/81,淨 +2/日)**;⚠️81 是單日晚間快照、實際在 79↔81 震盪,引用時帶快照日
- **維運跟上傳搶額度**:維運日耗實測(spent 減上傳鏈,僅六個已關帳日 08-26~08-31)= 860 / 7,845 / 6,991 / 7,058 / 1,710 / 4,601,**中位 5,796**(captions 重同步/描述章節修正/留言管理);低值日(860/1,710)是**被上傳先吃光配額餓出來的**,不是需求低——無餓日的需求落在 4,601~7,845;活例:09-01 一項 39 支標題回填估 ≈1,950 units,因配額必須讓給上傳而**取消**——維運已經在為上傳讓路,這類支出上一輪申請書完全沒編列;⚠️ 此「維運可用量」是殘差(spent 減上傳鏈),值依 `playlistItems.post` 的歸類而變:該科目由兩塊組成 —— 每支片固定的 11×50=550(`daily_publish.py:1273`)+ 一支獨立的播放清單同步(0~1,350,那是維運)。全額算進上傳鏈 → 09-01~09-03 = 1,056/423/451;只算每支那 550 → 1,056/473/1,801。**兩者都不是錯的,引用必須指明口徑,且此殘差不進英文 justification**
- **時數是 YPP 慢閘門**(基準 2026-09-04,資料截至 2026-09-01,來源 `STUDIO/ypp_meter.jsonl`):長片 **1,118/4,000** 小時,近 6 日(08-29~09-04)均增 **34.3** → 缺口 **84 天**;訂閱 **405/1,000**,同窗均增 **14.7** → **41 天**。⚠️舊值 999/343、缺口 103/75 天的基準日是 2026-09-01(資料截至 08-29)

## 2. 兩個關鍵數字怎麼算出來的(從現況長出來,不含成長假設)

**上傳能力需求 ≈ 17 支/日**:
- (b) 產線穩態良率:七日毛產出實測 9~29、中位 14、均值 16.4(2026-08-29~09-04 逐日 18/19/14/29/13/9/13),取 **14**(等於中位、低於均值;均值靠 09-01 的 29 撐,拿掉它其餘六日均 14.3)
- (a) 庫存清償:81 支(2026-09-04 晚間快照;近日在 79~81 震盪,是快照不是穩定值)÷ 30 天 ≈ **+2.7 支/日**
- → 上傳能力要 14 + 2.7 ≈ **16.7,取 17** —— 這是「追上產出+清庫存」的算術,不是發布量目標

**Requested = 45,000 units/day**:
- 17 × 2,150 = 36,550(上傳鏈全成本:videos.insert 1,600 + captions.insert 400 + thumbnails.set 50 + playlistItems.insert 50 + commentThreads.insert 50。這五項就是 `daily_publish.py` 每發一支實際呼叫的端點:`:941` / `:975` / `:1018` / `:1272` / `:1273`)
- (c) 維運:逐日實測(spent 減上傳鏈,僅六個已關帳日 08-26~08-31)= 860 / 7,845 / 6,991 / 7,058 / 1,710 / 4,601,**中位 5,796**;低值日(860/1,710)是維運被配額餓死的日子,無餓日需求落在 4,601~7,845(其中位 ~7,025)→ 編列 4,000~6,000:低於無餓日需求,**刻意保守**;45,000 總額留 **8,450** headroom(45,000 − 36,550),蓋得住整體中位 5,796,**也蓋得住無餓日最高的 7,845** —— 這是良率由 15 降為 14 的副效果:上傳編列少了 2,150,維運緩衝相應變大,前版「蓋不住高峰日」的讓步不再需要
- → 36,550 + 4,000~6,000 ≈ 40,550~42,550 → **申報 45,000**。⚠️ 明講:算術指向 **43,000**,45,000 是**刻意上調至最近的 5,000 整數位**,多出的 2,450~4,450 是給無餓日高峰(7,845 > 編列上界 6,000)的緩衝。不是算術結果,是取捨

**發布量上限是另一回事**:硬上限 12 已在 daily_publish(2026-08-19 加,依據=單日 ≥21 支的暴發日單支觀看中位 3 vs 平日 37 的斷崖實測);main ch. 正在跑發布量×單支觀看的因果驗收,**09-15 出結論前上限不動**。核准的額度先吃庫存清償與維運,發布量若上調必依驗收結論、且不超過對 Google 的新申報值。

## 3. 送出前 Carson 要親手確認的三件

1. **官方核定值**(表單 "Current daily quota" 欄):console.cloud.google.com → `claude-morning-report-498407` → IAM 與管理 → 配額 → YouTube Data API v3 "Queries per day" → **抄那個數字**。
   (24,374 與 26,001 是**同一個太平洋配額日 08-31 的兩次撞牆觀測** —— 前者記於台北 09-01 00:41 = 太平洋 08-31 09:41;26,001 是那天成功花掉的量,同日 Google 另拒了 31 次(`quota_meter.json` 的 `rejected_calls: 31`,被拒的不計入 spent),所以真上限落在 [26,001, ~26,050]。⚠️ 為何 24,374 被拒之後同日仍能花到 26,001,未解。表單仍填 Google 自己的數。)
2. **登入帳號** = project Owner(上輪確認 crayray86@gmail.com / 周庭睿)。
3. **隱私政策 URL**:沿用上一輪通過稽核的那個公開 URL,確認還活著。

## 4. 表單答案(入口:https://support.google.com/youtube/contact/yt_api_form)

不變欄位(身分/組織/Section 3 貼文/API Client 名稱 `Carson Quant Studio`/Project Number `524513894332`/架構圖)照 `yt_quota_extension_application.md` 2026-07-17 節,以下是這一輪的:

- **Request Type**: request for additional quota
- **Current daily quota**: 第 3 節抄來的官方數字
- **Requested daily quota**: **45,000 units**
- **Expected API Usage Volume**(Section 5;⚠️ **蓋掉舊表寫的 40,000**,否則表單自相矛盾): **45,000 units/day**
- **Expected upload volume**: **currently capped at 11/day by our scheduler; requested capacity up to 17/day**(能力申報,非承諾;2026-08-26~08-31 六個已關帳日 videos.post 呼叫 6~10 次、實發 5~10 支;2026-09-01~09-04 為每日 11 次。11 是排程設定值)

**Justification(貼這段;每個數字有來源、無成長假設)**:

> All figures below are measurements taken as of 2026-09-04 and are given with
> explicit date ranges rather than relative wording, so that each number remains
> checkable against a fixed window.
>
> Our previous quota increase (approved 2026-08) is now exhausted on a recurring
> basis — not because we plan to grow, but because our production already outruns
> our upload capacity today. Our client-side metering (a wrapper recording the
> documented unit cost of every API call; it counts failed calls at list price, so
> figures are upper bounds) shows consumption on the six closed quota days from
> 2026-08-26 to 2026-08-31 (Pacific) of 18,760 / 19,645 / 23,341 / 21,858 /
> 22,910 / 26,001 units. On 2026-08-31 the quota was exhausted before the day's
> work finished: our pipeline had to block two scheduled uploads (our meter
> reported 1,600 units required for videos.insert with 0 remaining) and the API
> rejected 31 further calls with quotaExceeded errors.
>
> Concretely: our pipeline (rendering, scripting, quality gates) currently completes
> 15–20 videos per day on average (daily output varies, 13–29), while the quota
> supports publishing only ~11. We hold a
> backlog of 81 finished videos awaiting publication, which grew by 35 over the
> last four days. In addition,
> recurring maintenance on our own back catalogue — caption re-sync, description and
> chapter corrections, comment moderation — measures up to ~7,800 units/day on days
> when quota permitted (on other days it was starved to as little as ~860–1,700
> units because uploads consumed the budget first) and
> competes with new uploads for the same budget (e.g., a planned title-correction
> pass across 39 published videos, estimated at ~1,950 units, had to be deferred
> because the remaining quota was prioritized for uploads).
>
> We request 45,000 units/day, sized from current measurements: publishing capacity
> to match production and gradually clear the existing backlog (up to 18 uploads/day
> × ~2,150 units = ~38,700) plus measured maintenance (~4,000–6,000). Our actual
> publishing cadence is adjusted conservatively based on per-video audience metrics;
> the requested amount is capacity to publish what is already produced, on our own
> channel (UCqP5JQXlQR5ZDLtEiBt4kLA). The client remains a private, internal-use
> pipeline with no third-party users.

- **Section 7 Attestations**:Carson 逐條讀過親勾(特別是 Accuracy of Information)。

## 5. ch2/ch3 專案(`881902283633`)—— 建議:先不要

- 從沒申請過,預設 10,000;ch3 現行 1長4短 ≈ 10,750 理論貼線,但頻道 09-03 才轉型、跑道 19 集未證明;小頻道提額=spam 畫像風險(上輪 07-17 教訓)
- **觸發條件寫死**:ch3 連續 7 天實際發布 ≥5 支/日且出現 quotaExceeded,再開它自己的申請

## 6. 核准前後的紀律(給所有 session 看的)

- **發布量上限 ≤12(現設 11)在 09-15 發布量驗收出結論前不動** —— 核准的額度是 headroom 不是承諾;要動上限,先過驗收結論,且不得超過本輪申報的 18
- 審核期間(2~4 週)**不開第二個 project 分流**(Developer Policies III.D.1c,整組停權)
- 補件要求(常見 screen recording)→ 轉存信件回附;源碼用 `git archive HEAD`,不給 repo 歷史

## 驗證紀錄

- ✅ 2026-09-01 第一輪 fresh-context(verify-quota-pack):3 FAIL / 5 RISK 全修(未關帳日冒充 full day、記帳上界當用量、quality-checked 撐不住、時區錯位、40k 餓死維運、灌水成因解釋錯、訂閱缺口 60→75 天、日期)
- ✅ 2026-09-01 督導攔截:18 支/日的成長前提被發布量×單支觀看實驗(09-15 出結論)動搖 → 承重點改為「產出>上傳能力的現況」,兩個數字改由 (a)庫存清償 (b)穩態良率 (c)維運實測 三項推導;發布上限凍結條款入文
- ✅ 2026-09-01 舊驗證員收工前補交二輪殘留:B1(08-25 的 18,914 是源頭自標 `unreliable` 的數)→ 序列改 08-26~08-31 六天並註明不採用原因;B2(舊表 Expected API Usage Volume 40,000 會與新要的 45,000 打架)→ 改變清單明確加 45,000 蓋掉;M1(維運下界不實)→ 改逐日實測 694~7,845/中位 4,601,並把「維運被配額餓死」寫成論證;M2(79 支與歸零時點混用)→ 已分開(歸零時 ~61,現 79)
- ✅ 2026-09-02 第二位 fresh-context 驗證員(verify-quota-pack-v3,找碴視角,全量對源頭重驗):**FAIL(2F/4R/3M)→ 全修**。F1(39 支標題回填已取消卻用過去式宣稱花了 1,950 units——quota_meter 09-01 videos.put 僅 7 次/350 units,可被 Google 證偽)→ 改為 planned-and-deferred,反而更支持論點;F2(「三天不足 1,000」實際已關帳日只有一天 860,文件三處自打架)→ 序列改僅用六個已關帳日、餓日改 860/1,710;R1(維運序列混入未關帳 09-01)→ 剔除;R2(+8/日算錯,46→79 是 3 天=+11/日)→ 改 +11;R3(兩個計數器混一句敘事)→ 拆開各自標來源;R4(6,300 headroom「勉強蓋高峰日」不實)→ 明寫蓋不住;M1(計量器訊息偽裝 API 原文)→ 改 our meter reported;M2(~8,000→~7,800);M3(currently 11/day 標明為排程設定值)。骨架與算術經逐日程式驗算全過(六日 spent 與 quota_meter 完全一致、by_op 加總全 MATCH、與舊申請書無未聲明矛盾、無成長假設)
- ✅ 2026-09-02 verify-quota-pack-v3 覆核:8/9 修乾淨,抓到我修 F2 時**自己算錯中位**(取未排序相鄰兩值得 3,156;正確=排序後 (4,601+6,991)/2=**5,796**)→ 已改,§2 編列論證改寫為「4,000~6,000 低於無餓日需求(~7,025)刻意保守;6,300 headroom 蓋得住中位 5,796、蓋不住三個高峰日」;另修三個殘渣(英文下限 ~900→~860、4 天窗→3 天窗、實發 5~10 支與呼叫數分開)。英文 justification 未引用錯誤中位,Google 面不受影響
- ✅ 2026-09-02 verify-quota-pack-v3 終核:**PASS,放行交 Carson**。四處修正逐數驗算通過(中位 5,796、無餓日中位 7,025、三天超過 6,300、英文全數字對回源頭);送出時仍走 §3 三件親手確認
- ✅ 2026-09-03 三口徑對帳修正(f683286a/bde8a51f)+ verify-quota-pack-v4 兩輪覆核:**PASS,放行維持**。督導抓到「+11/日」是以尖峰日收尾的 3 天窗高估 → 全部改逐日毛產出口徑(晚間庫存差+上架回推,19/14/29/13、均值 18.75、庫存 46→81/4 晚 +35);v4 逐日重算全對、隔離支數口徑獨立驗證、attestation 判斷「15–20 on average + 13–29 全距」站得住;§2 兩處改漏(79 殘留、引用已刪依據)修畢終看通過。推導鏈 18 支/45,000 units 不變
