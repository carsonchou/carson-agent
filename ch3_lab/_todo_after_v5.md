# 下一批再改(這一批凍結渲染碼)

2026-09-01 督導拍板:修正節奏跑贏了渲染/驗證/發布節奏,今天渲了三小時、
出貨 0 支。閘門要對**出得去的片**生效才有意義。以下全部記著,這批不動。

## 已知但不擋這批
- **backfire_effect**:版面守門擋下(28pt 標題重疊 0.066)。fail-closed 是對的,
  但一支不該拖住十三支 —— 這批跳過它。
- **字幕/表格揭露時間仍偏早 0.3~1.2 秒**(已在 spoken 空間修過一次,殘差)。
  觀眾不會因此看到錯的東西,只是不夠貼。
- **長片沒有滾動字幕**:短片加了,長片沒有。長片段落長、畫面變化少,
  同一個「死時間」問題可能存在,但還沒量過。
- **長片的表格揭露時間仍是均分**(`0.4 + i * step`),沒有走 cue。
  列的順序是對的,所以不會意思顛倒,只是不同步。
- **_do_not_fill 的 forbid 多半是空陣列**:那些數字產線根本算不出來,
  所以沒有東西可禁。真正靠它擋住的只有「溯源放行但不准講」那一類,
  目前全庫只有一個合成測試案例證明過。
- **舊批 54 支已上線的片**帶著舊頁尾(「Nothing is estimated or rounded」)
  與舊配音(數字唸不出小數點)。改說明欄一支 50 配額 × 54 = 2,700;
  音軌不能換,只能下架重傳(不可行)。
- **`_lbl` 的 n_is_floor 只套 n_r**:全庫目前只有 bystander_effect 一處,
  若之後有 original 側的 floor 要另外處理。

## 值得做但不急
- 長片也產縮圖(目前只有短片有)。
- `pin_question.py` 發完之後沒辦法置頂(API 做不到),要 Carson 在 Studio 點。
- `format_ab.py`:新格式上線滿兩週再跑,比較留言/分享/觀看時間。

## 🔴 2026-09-01 發布前查出的根因(下一批的第一優先)

**長片沒有片長閘門,而片長是那份設計文件自己說「唯一完全由我決定的變數」。**

- `make_rechecked.py` 的 docstring 寫著目標 **4~5 分鐘**,理由是 08-30 實測
  「16:9 的片 15 支、總觀看 3 次、中位數 0,因為片長 58 秒~2 分 14 秒,
  卡在一個沒有出口的格式」。
- 今天渲出來的 14 支實際片長 **118~180 秒(2~3 分)**。目標從來沒達成過。
- `make_reel.py` 有 35~50 秒的閘門(我今天為它擋了四輪、改稿五次)。
  `make_rechecked.py` **一道都沒有** —— 同一個形狀:閘門加在我當時
  正在看的那條路上。

**實測佐證(2026-09-01,Analytics + Data API,唯讀)**
- 分格式(08-23~08-31):Shorts 203 觀看 / videoOnDemand **4 觀看**
- 流量來源:SHORTS feed 191、搜尋 6、頻道頁 6、訂閱 1、
  **瀏覽與推薦(首頁 / 相關影片)= 0**
- 22 支長片全部 public + processed + 無 rejectionReason,片長 PT1M×12 / PT2M×9
  → 不是被下架也不是沒處理完,是**這個長度的 16:9 沒有分發管道**
- `impressions` 與 `impressionsClickThroughRate` 這個頻道回 **HTTP 400**,
  拉不到。曝光數字是缺的,上面用流量來源當代理。

**下一批要做的,照順序**
1. `make_rechecked` 加片長閘門(目標帶待定,但至少要 fail-closed 而不是沒有)
2. 稿子長度要真的到 4~5 分鐘 —— 現在每集七段的字數撐不到
3. `make_compilation` 併成 15 分鐘那條路徑重新啟用並實測
4. 在那之前**不要再發 2~3 分鐘的 16:9**

## 🔴 stanford_prison 的 es_is_max 在三條路上各自掉一次(渲染碼,凍結中)

原文是 **less than 15%**,而三個表面印成裸的 `15%`、兩個表面印對:

| 表面 | 顯示 | 根因 |
|---|---|---|
| 時間軸卡 | `15%` ❌ | `make_rechecked.py:257-264` `timeline_rows()` 重建 dict 時只複製五個 key,`es_is_max` 掉了 |
| 旁白 | 「15 percent」 ❌ | `make_rechecked.py:153` `say_es()` **根本沒有 `is_max` 參數** —— 畫面那道補了,出聲那份沒補 |
| 說明欄 | `15%` ❌ | `publish_meta.py` 沒往下傳 |
| 轉折卡 | `<15%` ✅ | `twist_rows()` 原封轉發,所以同一支片兩種結果 |
| 判決卡 | `less than 15%` ✅ | 走逐字引文 |

**說明欄那兩處已修(2026-09-01,不影響成片)。渲染那兩處凍結中,下一批修。**
在修好之前 **stanford_prison 長片不發**。

順帶:`publish_meta.py` 的「The retest」寫死有**兩處**,我修第一處之後第二處
還在(引文區塊標題)。已一起修成跟著 `test.kind` 走 —— stanford_prison 的
kind 是 `archival reinvestigation`,而旁白明說「Not a retest」。

## 🔴 四條 insert 路徑,配比閘門只裝在一條(督導指派,出貨後做)

`publish_shorts.py:840` / `publish_comp.py:314` / `upload.py:363`,
加上排程的 `ch3_publish.py`,而 `DAILY_LONG=1` **只寫在最後那支裡**。
今天我差點手動發 11 支長片走的就是沒閘那條。

改法:新增 `ch3_lab/publish_gate.py` 的 `assert_may_publish(kind)`,
上限只從 `ch3_publish.py` import(不複製數字)、日界用 `quota._pacific_date`
(不另寫一份)、fail-closed、三個 insert 站點各自呼叫。
驗收要派 agent **試圖繞過它**發第 2 支,四條路各自回報被擋在哪一行 ——
任何一條沒被擋就是沒做完。用 dry-run,不准真的多發一支上去測。

## ⬇️ publish_gate.py — 降級為「不急」(2026-09-02 重新判定,不要實作)

原本記成「四條 insert 路徑只有一條有配比閘門」的急件。**獨立驗證之後急迫性降到最低**,
撿起來的人先讀這段再決定要不要做:

- fresh-context agent 查證:`publish_comp.py:314` / `publish_shorts.py:840` /
  `upload.py:363` 三個 insert 點**只被 `ch3_publish.py` 以 subprocess 呼叫**
  (`ch3_publish.py:102/118/132`),全庫沒有第二個呼叫點。
- 而 `ch3_publish.py` 的三個 cron 時段(732/733/734)已於 09-02 註解掉。
- `Get-ScheduledTask` 篩過只有 `CarsonQuant_PCRender`(純渲染,不上傳);
  開機的 `run_studio_bg.vbs` 也不會單獨觸發 ch3_publish。

**所以這道閘門現在防的不是「自動發布繞過配比」——那條路已經停了——而是
「人工繞過」**,也就是我 09-01 差點做的那件事(手動 `--only` 一次發 11 支長片,
走的正是沒有 `DAILY_LONG` 限制的那條)。

要做的時機:**ch3 恢復發布之前**。在那之前做等於替一條停著的線裝閘門。
設計仍照原案:`assert_may_publish(kind)`、上限只從 `ch3_publish.py` import
(不複製數字)、日界用 `quota._pacific_date`(不另寫一份)、fail-closed、
三個 insert 站點各自呼叫;驗收要派 agent **試圖繞過它**,四條路各自回報被擋在
哪一行,用 dry-run 不准真的多發。
