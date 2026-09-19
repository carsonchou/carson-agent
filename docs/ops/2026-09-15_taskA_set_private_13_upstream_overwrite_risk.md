# 09-15 set_private_13 上游覆寫風險調查(補九條(F)缺口)

w9:p1 落檔,2026-09-15。補的是總督導 13:47:40 裁決點名的(F):「有沒有任何 cron/程序會把這 13 支的
privacyStatus 改回 public,從沒被直接回答過;`B_playlist_readd.md` 答的是播放清單重新上架,不是
privacyStatus 反轉,不算數」。本檔直接回答這個問題,「未知」是可接受答案但要明講——本檔的結論**不是**
「未知」,是有證據支持的具體結論,但同時把證據邊界寫清楚,不誇大成「證明不可能」。

## 一、方法

1. `grep -rn "privacyStatus" youtube_channel/scripts/*.py`:16 支腳本命中(完整清單見附表)。
2. 從 16 支裡再篩出真的會呼叫 `videos().update(part="status", ...)`(能寫 privacyStatus,不是只讀)的:
   `privatize_fabricated.py`、`set_private_by_ids.py`、`set_private_leaks.py`、`set_public.py`、
   `zombie_sweep.py`、`set_private_13.py` 本身,共 6 支。
3. 逐支查 `deploy/crontab.txt` 有沒有排程行呼叫這 6 支腳本(用腳本檔名逐一 grep 整份 crontab.txt)。
4. 查 `zombie_sweep.py`(唯一被排程呼叫的寫入腳本)的原始碼,確認它「寫」的方向與目標母體。
5. 查 `STUDIO/_private_batch_ids.json`(zombie_sweep 其中一條寫入路徑吃的清單)裡有沒有 HARD13 的 id。
6. 逐支對其餘 5 支腳本(含 set_private_13.py 自己)grep `HARD13`/13 支中任一支 id 的字面值,
   確認沒有腳本把這 13 支硬編碼進自己的目標清單裡。

## 二、發現

### (a) 6 支「能寫 privacyStatus」的腳本裡,只有 1 支在 crontab.txt 裡被排程

```
privatize_fabricated.py  → crontab.txt 零命中(手動腳本,無排程)
set_private_by_ids.py    → crontab.txt 零命中(手動腳本,無排程)
set_private_leaks.py     → crontab.txt 零命中(手動腳本,無排程)
set_public.py            → crontab.txt 零命中(手動腳本,無排程)
set_private_13.py        → crontab.txt 零命中(這支本身也是手動腳本,九條全程都是手動 --apply)
zombie_sweep.py          → crontab.txt:570 命中一行:
    20 14 * * 1 YT_QUOTA_RESERVE=23650 /root/yt/run.sh scripts/zombie_sweep.py --apply --max 15 ...
    ↑ 星期欄 "1" = 週一。今天 09-15 是週二,**這行今天不會跑**(套用 local_cron.due() 的 AND 語意,
      同 Task 3 報告已驗證過的那條規則),但下週一會跑,屬於「未來風險」要一併回答。
```

`set_public.py`(唯一能把 privacyStatus 寫成 `"public"` 的通用腳本)完全不在任何排程裡,
只能人工手動指定 id 執行——沒有自動觸發路徑。

### (b) 唯一被排程的寫入腳本 zombie_sweep.py,寫入方向只有「public → private」,沒有反向

原始碼(`zombie_sweep.py:382`、`:414`)兩處 `videos().update` 呼叫,寫入前都是
`status["privacyStatus"] = "private"`——**沒有任何一行把 privacyStatus 設成 `"public"`**。
它是一支「把冷門片收起來」的腳本,不是「把片放出去」的腳本,結構上就不具備反轉本次操作的能力。

它的兩條寫入路徑分別是:
1. **0 觀看+滿 14 天** 的即時掃描結果(`zombie_sweep.py:369-383`)。
2. **`STUDIO/_private_batch_ids.json` 清單裡的 id**(`zombie_sweep.py:405-415`),且該路徑本身在
   `:409` 有一道閘門:`if m["privacyStatus"] != "public": skip`——已經是非 public 的片會被跳過、
   不寫入。也就是說,即使 HARD13 這 13 支被這支腳本盯上,一旦我們先把它們設成 private,
   zombie_sweep 之後撞到它們只會 `[skip]` 不會有任何寫入(不管走哪一條路徑)。

### (c) `_private_batch_ids.json` 清單本身不含 HARD13 任何一支

```
STUDIO/_private_batch_ids.json 內容:["oq4I_jtEw3Q", "ODN9YzdBopA", "7C79mFmnFrE"]
```
與 HARD13 的 13 支(MuXiM5IqVQQ、TDbm4XR5pYk、cObU5NcFT-I、I8F83sPFKWg、_Cc49y7ZAeM、tN56crKxwJE、
mvDrUnxEjWs、vwEaoo3Txjw、UTuMMyvdQ5U、DhX2uNzjZ-o、OyprNxjrIBQ、nHwP_cyy_hc、xjQPW3sTY28)
**零重疊**。這只排除了 (b) 的第 2 條路徑(清單式),不排除第 1 條路徑(即時 0 觀看掃描)——
但如上段(b)所述,第 1 條路徑寫入方向一樣只有「public → private」,即使掃到 HARD13 也只會是
no-op(已經是 private,被 `:409` 那道閘門跳過),不影響「會不會被改回 public」這個問題的答案。

### (d) 其餘 5 支寫入腳本沒有硬編碼這 13 支 id 中的任何一支

`grep -n "HARD13\|MuXiM5IqVQQ\|TDbm4XR5pYk\|cObU5NcFT-I" privatize_fabricated.py set_private_by_ids.py
set_private_leaks.py set_public.py` → 零命中。這 5 支腳本的目標清單各自來自自己的檔案/參數
(如 `set_private_by_ids.py` 讀的是 `_private_batch_ids.json`,已在(c)排除),不會意外把 HARD13
納入目標。

### (e) 上傳/建清單類腳本結構上不適用

`daily_publish.py`、`upload_youtube.py`、`schedule_publish.py` 寫 `privacyStatus` 只發生在
`videos().insert`(全新上傳)的請求 body 裡,不是對已存在影片下 `videos().update`——不會碰到
HARD13 這種已發布多時的舊片。`playlist_engine.py`、`build_playlists.py`、`industry_playlists.py`
寫 `privacyStatus` 只發生在 `playlists().insert`(建立新播放清單本身的隱私狀態),`build_playlists.py`
對「影片」的 privacyStatus 只有讀(`videos.list`,當作要不要收錄進清單的判斷閘門),沒有寫。

## 三、結論(不是「未知」,是有證據支持的具體結論,附邊界)

**就 `youtube_channel/scripts/` 目錄下的程式碼與 `deploy/crontab.txt` 目前的排程內容而言,
沒有找到任何會把這 13 支影片的 privacyStatus 從 private 改回 public 的自動化路徑。**
唯一被排程呼叫、且具備 privacyStatus 寫入能力的腳本(`zombie_sweep.py`,每週一 14:20)在程式碼層級
就只會往 private 方向寫,結構上不具備反轉能力;唯一能寫出 `"public"` 的通用腳本(`set_public.py`)
沒有任何排程呼叫它。

**這個結論的邊界(誠實揭露,不是完全排除,套用 memory `caveat-needs-a-withdrawal-condition.md` 的
四件套)：**
- **未量到什麼**:本檔是靜態讀碼(grep + 手動看程式邏輯),不是跑一輪實測捕捉到的執行證據
  (memory `static-reading-vs-runtime-behaviour.md`:讀程式碼算的 ≠ 跑起來的行為)。沒有對
  `youtube_channel/scripts/` 以外的目錄(例如是否有其他 repo、其他自動化、人工在 YT Studio 網頁
  介面手動操作)做窮舉,那些管道本檔沒有能力、也沒有被授權去查。
- **量法**:若要把這個邊界收斂,下一步是在 first 批次(1 支)送出後,用九條(E)那份計畫裡的
  T1/T2 兩次獨立回讀(間隔 ≥60 分鐘)直接**實測**有沒有被改回去,那是本檔給不出的「跑起來的證據」,
  是(E)文件負責的部分,兩份文件合起來才構成完整回答。
- **撤銷門檻**:如果(E)的 T2 讀回撞到「翻回 public」,本檔這個結論要立刻撤回,並把撞到的那個
  時間點/腳本補進本檔第二節,不能事後才輕描淡寫。
- **撤掉之後還剩什麼不敢宣稱**:即使 first 批次的 T1/T2 都驗證乾淨,本檔的結論也只到「這一次沒有
  發生」,不能升級成「這 13 支永遠不會被改回 public」——crontab.txt 未來還會被人改動,`zombie_sweep.py`
  未來也可能被改成雙向腳本,那是每次改動排程/腳本前該重新檢查的事,不是本檔一次查完就一勞永逸。

## 四、附表:16 支含 `privacyStatus` 字樣的腳本(第一節第 1 步的完整清單)

build_playlists.py、playlist_engine.py、verify_desc_rewrite.py、fix_period_disclaimer.py、
daily_publish.py、upload_youtube.py、schedule_publish.py、set_public.py、set_private_leaks.py、
set_private_by_ids.py、industry_playlists.py、privatize_fabricated.py、gen_media_kit.py、
winner_amplifier.py、organize_dept.py、zombie_sweep.py
（`verify_desc_rewrite.py`、`gen_media_kit.py`、`winner_amplifier.py`、`organize_dept.py`、
`fix_period_disclaimer.py` 只在註解/日誌欄位裡提到 privacyStatus 字樣或只做唯讀查詢,
沒有 `videos().update(part="status", ...)` 呼叫,不計入第二節的 6 支。）
