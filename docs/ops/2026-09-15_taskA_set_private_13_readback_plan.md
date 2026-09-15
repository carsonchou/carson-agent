# 09-15 set_private_13 讀回計畫(補九條(E)缺口)

w9:p1 落檔,2026-09-15。補的是總督導 13:47:40 裁決點名的(E):「既有 dry-run/self-test 輸出是 09-11 的,
不構成這次 09-15 執行的回讀計畫」。本檔只寫**這次要怎麼驗**,不涉及裁決是否放行、不碰 crontab.txt、
不跑 set_private_13.py --apply 任何一輪。

## 一、獨立儀器(不是同一支腳本重跑)

用 `preflight_inst2.py`(09-11 16:50 已落檔,同目錄)裡驗證過的方法,不是重新設計:

- API 呼叫:`playlistItems().list(part="status,contentDetails", playlistId=<uploads 播放清單>)`,
  翻整份 uploads 播放清單,從裡面撈目標 id 的 `status.privacyStatus`。
- 這**不是** set_private_13.py 讀回用的 `videos().list(part="status,snippet", id=...)` —— 兩支不同
  API 端點(playlistItems vs videos),不共用同一次呼叫、不共用同一支腳本,符合「換獨立儀器」
  (memory `yt-readback-stale-cache.md`:「同一儀器問三次不算驗證」)。
- 09-11 已對這支儀器做過陽性對照:3 支已知 private(`_private_batch_ids.json` 那 3 支)、3 支已知
  unlisted,這支儀器全部讀對(見 `instrument2_preflight.json` 的 `verdict: 一致`,6/6)。不是這次臨時
  現想的方法,是有前科驗證過的儀器。

本次執行只需重跑 `preflight_inst2.py` 的讀取邏輯(或等價的一次性腳本,呼叫同一組 API),鎖定目標
id 換成本輪第一批的 `MuXiM5IqVQQ` + 陰性對照,不需要重寫。

## 二、範圍聲明:本計畫只涵蓋「第一批(1 支)」,不涵蓋剩下 12 支

九條(D)的呼叫層修法(`apply_first_batch_guard.py`,同批落檔)把 09-15 --apply 切成兩批:

- **first 批次**:只送 `HARD13[0]` = `MuXiM5IqVQQ`,1 支。
- **rest 批次**:剩下 12 支,**必須**有合法的 `first_batch_verified.json`(本檔規定的內容,見下)才放行,
  且該檔的 `readback_ts` 兩個時間戳間隔必須 ≥3600 秒,由程式碼硬擋,不是口頭約定。

因此本計畫回答的是「first 批次怎麼驗」。**rest 批次(12 支)是否要接著在同一個 21:05–22:45 窗口內送出,
本檔不擅自認定要,留給總督導在看到 first 批次的實際讀回結果後另外裁決** —— 這是刻意的,呼應總督導
自己在(D)裡要求的「先把第一次母體壓到 1,中間插閘門」的精神;窗口核准(H)當時的內部結構假設的是
「一次寫入」,現在多了 first/rest 兩批,兩者不必然能塞進同一個 90 分鐘窗口內完成,不應該为了塞進去
而縮短 60 分鐘回讀間隔。

## 三、時間戳(兩個,間隔 ≥60 分鐘,寫死在計畫裡,不是事後找的)

在總督導已核准的 09-15 21:05–22:45(台北)窗口內:

| 步驟 | 時間(台北) | 動作 |
|---|---|---|
| 寫入 | 21:05–21:15 | `apply_first_batch_guard.py --batch first --apply`,只送 `MuXiM5IqVQQ` |
| **T1(第一次獨立回讀)** | **21:16** | 用 preflight_inst2 方法讀 `MuXiM5IqVQQ` + 陰性對照,兩支都要記錄結果 |
| **T2(第二次獨立回讀)** | **22:16**(與 T1 相距 60 分鐘) | 同一支儀器再讀一次同兩支 id,確認 T1 的結果沒有被之後的任何程序(排程/快取過期後的真值)翻回去 —— 這是 09-11 事故的直接教訓(memory `yt-readback-stale-cache.md`:30 秒回讀 9/9 private,50 分鐘後兩支變回 public) |
| 落檔 + 裁決點 | 22:16 之後 | 把 T1、T2 結果寫進 `first_batch_verified.json`;是否接著跑 rest 批次,等這份結果送給總督導看過 |

T1/T2 都要落在 `first_batch_verified.json` 的 `readback_ts` 陣列裡(ISO8601,含 `+08:00` 時區),
`apply_first_batch_guard.py` 的 `load_verification()` 會用程式碼核對兩者相差 ≥3600 秒,不是文件裡寫寫而已。

## 四、陰性對照(從既有 `candidates.json.negative_controls_public` 挑,不臨時另找)

用第一支:`fYTywq3Ah1c`(2022臺股熊市 EP1 #Shorts,`must_remain: "public"`)。理由:
- 09-11 `instrument2_preflight.json` 已經證明這支儀器對它讀得出正確的 `public`(group=ctrl,一致)。
- T1、T2 兩次都要一併讀它,若這支陰性對照在任一次讀出非 public,代表儀器本身或帳號權限出了系統性問題
  (不是 HARD13 那支個別出錯),要整批停下人工看,不能只看 MuXiM5IqVQQ 一支就下結論。

## 五、失敗判準(先寫在事前,不是事後找理由)

- T1 讀到 `MuXiM5IqVQQ` != private,或陰性對照 != public → 不寫 `first_batch_verified.json`,整批停,
  回報總督導,不得憑口頭「應該沒事」續跑 rest 批次。
- T1 通過但 T2 讀到翻回去(不管是 `MuXiM5IqVQQ` 變回 public,還是陰性對照變成非 public)→ 同上,
  停、記錄、回報,不寫驗證檔;這正是九條(F)要問的「有沒有東西把它改回去」的實測版本,一旦真的翻回去,
  要立刻併入(F)的調查(見同批送出的 `..._upstream_overwrite_risk.md`)。
- 兩次都過 → 才允許把 `first_batch_verified.json` 寫成合法檔,而是否接著跑 rest 批次仍要等總督導看過
  這份實測結果再裁決,不是自動接著跑。

## 六、本計畫不涵蓋的部分

- (G)寫入前 local_cron 存活即時檢查:另外在 21:05 動手前做,不是本檔範圍。
- (C)fresh-context 獨立驗證:總督導裁決要求先於本輪任何 --apply 之前通過,本檔只是三缺口之一,
  不取代(C)。
- rest 批次(12 支)的讀回細節:等 first 批次的實測結果出來、總督導裁決是否接著跑之後,若要跑,
  由那時再另外確認是否沿用同一組時間戳結構或另訂——不在本檔內先斬先定。
