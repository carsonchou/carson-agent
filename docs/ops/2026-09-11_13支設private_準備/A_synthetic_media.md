# containsSyntheticMedia 唯讀調查報告

調查者:唯讀調查 agent。倉庫:`D:\carson-agent`(Git Bash)。HEAD `25bdeb7216b15ce91714d0dcf256934bead7bf3c`(2026-09-11 17:23:09 +0800,分支 `feat/ultimate-uplevel-2026-07`)。
全程零寫入、零 API 呼叫、零 yt-dlp、未讀 `.env`/token/credential 檔。

---

## 一句話結論

**這次寫入(13 支「先 videos.list 讀回整包 status、只換 privacyStatus」的寫法)會不會清掉一個原本有設的 `containsSyntheticMedia`:不會**——因為找不到任何證據顯示這 13 支曾經被任何程式碼設過這個欄位(見 §三 全歷史搜尋 + §一 上傳端逐支核對)。
承重證據:`git log -S containsSyntheticMedia --all` / `git log -S SyntheticMedia --all` 在整個 repo 全部歷史裡,只命中 3 個 commit,而且**這 3 個 commit 全部是 09-11 當次調查自己寫的 docs**(`627a3f4e`、`11f90c70`、`25bdeb72`),不是任何上傳/更新程式碼。上傳端三條路徑(`upload_youtube.py:561-568`、`daily_publish.py:963`、`schedule_publish.py:73-82`)在 13 支實際發布的整個時間窗(2026-08-04~2026-08-11)內,status dict 逐一核對過的版本都只有 `privacyStatus / selfDeclaredMadeForKids / embeddable /(排程時 publishAt)`,沒有 `containsSyntheticMedia` 這個 key。

但這是「沒找到證據它被設過」,不是「證明它在 YouTube 那端是預設值」——`containsSyntheticMedia` 是可寫欄位、`videos.list` 從來不回傳它,所以**這件事本身在唯讀範圍內無法被「證明」到 100%,只能被證明「repo 裡沒有任何程式碼路徑設過它」**。如果 Carson 或協作者曾經在 YouTube Studio 網頁介面手動勾選過(不經過本 repo 任何程式碼),本調查抓不到——這是唯讀調查的天花板,不是漏查。

---

## 二、13 支清單來源

`docs/ops/2026-09-11_13支設private_準備/candidates.json`,`videos` 陣列 13 支,全部 `privacyStatus_at_prep: public`,發布時間跨度 `2026-08-04T08:02:15Z` ~ `2026-08-11T18:01:57Z`。videoId 清單:
`MuXiM5IqVQQ TDbm4XR5pYk cObU5NcFT-I I8F83sPFKWg _Cc49y7ZAeM tN56crKxwJE mvDrUnxEjWs vwEaoo3Txjw UTuMMyvdQ5U DhX2uNzjZ-o OyprNxjrIBQ nHwP_cyy_hc xjQPW3sTY28`。

---

## 三、`containsSyntheticMedia` / `SyntheticMedia` 全 repo 全歷史搜尋

實際跑的指令:
```
git log -S containsSyntheticMedia --all --oneline
git log -S SyntheticMedia --all --oneline
```
兩條指令回傳**完全相同**的 3 個 commit,而且都只是這次(09-11)調查自己產出的 docs/ops 檔案:

| commit | 標題 |
|---|---|
| `627a3f4e` | docs(ops): 已發布壞片母體掃描 |
| `11f90c70` | docs(ops): 13 支設 private 準備與 dry-run |
| `25bdeb72` | docs(ops): 627a3f4e 追記更正 10 處 + 9YbT 另列待 Carson 判(HEAD) |

即:**在這次調查之前,這兩個字串從沒在這個 repo 的任何一次 commit 出現過**——不是被刪掉、不是被改名,是從一開始就不存在。這覆蓋全部分支(`--all`)、全部目錄(含 `quant-service`、`ch3_lab`、`yt_ch2`、`music`、`_archive`、`_v2` 等),因為 `-S` 是對象內容搜尋,不受目錄範圍限制。

`_archive`、`_v2`、`_vid_skills`、頂層 `scripts/`、`quant-service` 另外用 `grep -rl "videos().insert\|videos().update"` 直接掃過,**零命中**——這些目錄裡沒有任何組 YouTube API body 的程式碼。

---

## 四、(a) 上傳端:全 repo 組 `videos().insert` / `videos().update` body 的位置

用 `type:py` 對整個 repo grep `videos\(\)\.(insert|update)` 找到 56 個檔案,逐一打開讀 status dict 的組法。以下只列**實際組 status/body 的函式**(純呼叫轉發、或 part=snippet 更新——不動 status——的收斂在後面一併說明,不逐支列)。

### (a)-1 `videos().insert`(上傳新片)——3 條路徑,全部只設 3~4 個 status key

| 檔案:行號 | 呼叫方式 | status dict 實際組出的 key |
|---|---|---|
| `youtube_channel/scripts/upload_youtube.py:554-568`(函式 `build_request_body`,docstring 自稱「組裝 YouTube videos.insert 的 request body」) | `videos().insert` 的 body 組裝 | `privacyStatus`、`selfDeclaredMadeForKids`;若 `publish_at` 非空再加 `publishAt`(:566-568)。**沒有** `containsSyntheticMedia`、`embeddable` |
| `youtube_channel/scripts/daily_publish.py:945-964`(上傳函式內組 body,`upload_one` 呼叫鏈上) | `videos().insert` | `privacyStatus`、`selfDeclaredMadeForKids: False`、`embeddable: True`(:963,單行三個 key)。**沒有** `containsSyntheticMedia` |
| `youtube_channel/scripts/schedule_publish.py:73-83`(docstring 明講「上傳時設 status.privacyStatus=private + publishAt」,**不經過** `daily_publish.upload_one`,是第二條旁路——見:84-87 該檔自己的註解「upload_one 那道閘門對這條路完全無效」) | `videos().insert` | `privacyStatus: "private"`、`publishAt`、`selfDeclaredMadeForKids: False`、`embeddable: True`(:78-82)。**沒有** `containsSyntheticMedia` |

`yt_ch2/scripts/` 下同名三個檔案 diff 過確認與 `youtube_channel/` 版本**不是位元相同**(有差異,應是頻道專屬設定),但 `containsSyntheticMedia` 字串的全歷史搜尋(§三)已經覆蓋這些檔案的每一個歷史版本,結論不變:沒有任何版本設過它。13 支本身確定是主頻道(`youtube_channel/`)的片(candidates.json 的 slug 措辭「量化阿森」系列與 `daily_publish.py`/`schedule_publish.py` 的頻道品牌一致),`yt_ch2` 路徑僅供完整性核對,未逐支再讀。

`ch3_lab/upload.py`、`ch3_lab/publish_shorts.py`、`ch3_lab/reupload_shorts.py`、`music/calm/upload.py`、`music/calm/upload3.py` 也各自組自己的 `videos().insert` body,但那些是別的頻道/別的素材(ch3_lab 是實驗室子頻道、music/calm 是音樂帳號),與這 13 支主頻道 Shorts 無關,§三 的全歷史字串搜尋已經覆蓋它們,同樣零命中。

### (a)-2 13 支發布當時(2026-08-04~08-11)實際跑的是哪個版本 —— 用 `git show <commit>:<path>` 讀當時原文,不是讀現在版本

實際指令與結果:

```
# 第 1 支發布(MuXiM5IqVQQ,2026-08-04T08:02:15Z)前最後一次改 daily_publish.py 的 commit
git log --all --oneline --before="2026-08-04T08:02:15Z" -1 -- youtube_channel/scripts/daily_publish.py
→ 8def9b1c perf(產能): 長片產能崩到 1~2 支/日的根因是 LLM 請求塞不進免費層的每分鐘桶

git show 8def9b1c:youtube_channel/scripts/daily_publish.py | grep -n '"status":' -A3
→ 866:        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True},

# 第 13 支發布(xjQPW3sTY28,2026-08-11T18:01:57Z)前最後一次改 daily_publish.py 的 commit
git log --all --oneline --before="2026-08-11T18:01:57Z" -1 -- youtube_channel/scripts/daily_publish.py
→ 8758e2fa feat(節奏): 發布量實驗7→3/天(2長1短)——量與成功反相關的三方證據

git show 8758e2fa:youtube_channel/scripts/daily_publish.py | grep -n '"status":' -A3
→ 905:        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False, "embeddable": True},
```

同樣手法核對 `upload_youtube.py`(08-04 前最後改動 commit `b6f091d4`、08-11 前最後改動 commit `63551453`)與 `schedule_publish.py`(08-04 前最後改動 commit `c7befcc0`),三個時間點的 `status` dict **逐字相同**,都只有 `privacyStatus / selfDeclaredMadeForKids /(embeddable)/(publishAt)`,沒有 `containsSyntheticMedia`。也就是說,整個 08-04~08-11 發布窗口內,這三條上傳路徑都沒有改過 status dict 的組法——不是巧合命中兩端,中間也沒有任何一次改動加過這個欄位(§三 的 `-S` 搜尋已經覆蓋中間所有 commit,不必逐一翻)。

### (a)-3 事後(不經 insert)用 `videos().update(part="status")` 改狀態的腳本 —— 全部列出,逐一讀完整函式

| 檔案:行號 | 寫法 | 有沒有可能清掉 `containsSyntheticMedia` |
|---|---|---|
| `youtube_channel/scripts/zombie_sweep.py:362-383`(逐支清 0 觀看舊片,含 07-15 那批,見 §五) | :362 `videos.list(part="status,statistics")` 讀回 →:370 `status = dict(it.get("status", {}))` 整包複製 →:382 只改 `status["privacyStatus"]` →:383 送出整包 | 結構上**不會清掉已知欄位**(整包帶回),但 `videos.list` 本來就不回傳 `containsSyntheticMedia`,所以這包「整包」永遠缺這一欄——如果 YouTube 那端真的有設,這個寫法一樣會把它清掉,只是這次剛好沒有(§三)證明它原本就沒被設過 |
| `youtube_channel/scripts/zombie_sweep.py:399-418`(`_private_batch_ids.json` 分支) | :403 `fetch_meta_batch`(:254-275,`videos.list(part="snippet,statistics,status")`)同一輪先讀 →:413 `dict(m["status"])` →:414 只改 `privacyStatus` →:415 送出 | 同上一列;⚠️ 讀跟寫之間隔一整個迴圈,不是寫入當下讀的(次要風險,與 `containsSyntheticMedia` 無關) |
| 🔴 `youtube_channel/scripts/set_private_by_ids.py:79` | `body={"id": vid, "status": {"privacyStatus": privacy}}`,**只送一個 key**,不讀回原 status(`_info()`,:38-46,只留 privacyStatus/觀看數/標題) | 🔴 **有結構性缺欄洞**:任何沒被明講的 status 欄位都會被清掉,`containsSyntheticMedia` 若真被設過,這支腳本一定會清掉它。candidates.json 的 note 已經明講「🔴不要把這些 id 放進 `_private_batch_ids.json`——…set_private_by_ids.py 的寫法會重設 status 其他欄位」,目前**沒有**證據這支腳本被用在這 13 支上(見 §六) |
| `youtube_channel/scripts/privatize_fabricated.py:98-107`(主流程) | :99 `videos.list(part="status")` 讀回 →:105 `dict(st)` 整包 →:106 只改 `privacyStatus` →:107 送出 | 同 zombie_sweep,整包但缺 `containsSyntheticMedia` 這一欄(結構性,videos.list 造成) |
| `youtube_channel/scripts/privatize_fabricated.py:58-66`(`--restore`) | 直接把**之前存的舊 status 快照**(`STUDIO/privatize_backup/<vid>.json`)整包送回 | 不同型態的風險:如果快照是舊的,會把「這段期間任何人對 status 的改動」蓋掉,但該快照本身也是來自 `videos.list`,一樣不含 `containsSyntheticMedia`——目前 `STUDIO/privatize_backup/` 目錄不存在(見 §六),這支功能沒有殘留可比對的資料 |
| `youtube_channel/scripts/set_private_leaks.py:194-198` | `dict(info["status"])`(來自 `get_videos_full`:102-118,`videos.list(part="snippet,status,statistics")`)→ 只改 `privacyStatus` →`setdefault("selfDeclaredMadeForKids", False)` | 同 zombie_sweep,整包但結構性缺 `containsSyntheticMedia` |
| `youtube_channel/scripts/set_public.py:69-78` | `items[0]["status"]`(來自 `videos.list(part="status")`)直接整包 → 只改 `privacyStatus` →`setdefault` | 同上 |

`yt_ch2/scripts/` 下同名腳本存在但屬於另一頻道,與這 13 支(主頻道)無關,列出僅供完整性。

**沒有找到**任何其他「事後 update 設 `containsSyntheticMedia`」的腳本——上面這張表已經是 `scripts/` 底下每一個出現 `videos().update(part="status")` 的地方(用同一批 grep 結果逐一核對,見 §四方法論),沒有遺漏的第八支。

---

## 五、07-15 那 17 支(`zombie_sweep.py`)—— 能不能拿「寫入前/寫入後」快照比對

### 5.1 確認「17 支」這個數字

`youtube_channel/STUDIO/zombie_sweep_state.json`(**不在版控**,見 §六)裡 `done` 物件,依 `date`+`reason` 分組統計(用 python 直接讀):

```
2026-07-15
   already_private 12   ← 當時已是 private/unlisted,跳過,沒有呼叫 update
   0view_14d+      17   ← 真的呼叫了 videos().update(part="status") 寫入 private
```

對應 commit:`581b01ad`(feat,殭屍片大清理引擎首次上線,2026-07-15 00:13:19 +0800)+ `785c0045`(同日 00:20:54,修系列保護漏洞)。17 支 = 這批真正被寫入的數量,與派工描述的「07-15 那 17 支」一致。

### 5.2 有沒有「寫入前 / 寫入後」的完整 status 快照

查過的地方:
1. `youtube_channel/STUDIO/zombie_sweep_state.json`(即時落地,現存活文件)——**每一支 `0view_14d+` 記錄只存**:`slug, date, reason, views_at_time, published_at, age_days, prev_privacy`。`prev_privacy` **只是一個字串**(`"public"`),不是完整 status dict。程式碼本身(`zombie_sweep.py:370` `status = dict(it.get("status", {}))`)確實在記憶體裡組過整包 status,但**沒有**把這包 status 存進 state 檔或任何其他檔案——只存了 `privacyStatus` 這一個衍生欄位。
2. `youtube_channel/STUDIO/zombie_sweep_state.json.bak`、`zombie_sweep_pubdate_cache.json(.bak)`——結構同上,`.bak` 只是同一支程式自己寫的備份,不是「執行前」拍的獨立快照。
3. `youtube_channel/STUDIO/privatize_backup/`——**目錄不存在**(`Glob` 零結果)。這是 `privatize_fabricated.py` 專用的完整 status 備份機制,但它是另一支腳本(對付「捏造統計片」)、另一批清單(`_fabricated_stats_published.json`),不是 07-15 的殭屍片清理批次;而且目前目錄本身不存在,無從得知它有沒有被用過又清空(`--restore` 會 `p.unlink()` 刪掉還原過的備份,見 `privatize_fabricated.py:67`)。
4. `youtube_channel/output/privacy_reports/`——只有一個檔案 `20260709_210921_dryrun.json`(2026-07-09,`set_private_leaks.py` 的 dry-run 輸出),日期早於 07-15 且是另一支腳本、dry-run(零寫入),與 07-15 zombie_sweep 批次無關。
5. `docs/ops/` 全庫 grep `zombie_sweep|殭屍片`,只命中這次(09-11)自己在寫的調查文件與 `candidates.json`/`prep.py`(見 §三 的表),**没有** 07-15 當時或之後產出的獨立報告文件。
6. `git log --all --oneline -- youtube_channel/STUDIO/*`——**零結果**。`.gitignore` 第「STUDIO 自動化執行狀態」段明講 `youtube_channel/STUDIO/` 整個目錄不進版控(執行期資料非程式碼),所以連「這個檔案以前長什麼樣」都問不到 git,只能看現在这一份活文件。

**結論:無法比對。** 沒有找到任何「07-15 寫入前」或「寫入後」的完整 status 快照(不管是 STUDIO 底下的 state/log、`desc_backup`、docs/ops 報告,還是 git 歷史裡的資料檔),只有一個衍生字串欄位 `prev_privacy`。

### 5.3 就算比對得到,能證明什麼、不能證明什麼

**就算真的找到了寫入前/寫入後兩份完整 status dict(例如未來哪天多一份獨立備份),這兩份快照都只可能是透過 `videos.list` 拿到的**——而 `videos.list` 從來不回傳 `containsSyntheticMedia`(§三已核對現行 22 支 status 回傳只有 7 個欄位:`embeddable, license, madeForKids, privacyStatus, publicStatsViewable, selfDeclaredMadeForKids, uploadStatus`,見 `docs/ops/2026-09-11_13支設private_準備與dry-run.md` 零之 2)。所以:
- **能證明**:寫入前後,`videos.list` 看得到的那 7 個欄位有沒有變(除了 `privacyStatus` 以外理論上不該變)。
- **不能證明**:`containsSyntheticMedia` 寫入前是什麼值、寫入後變成什麼值——因為這個欄位從頭到尾都不會出現在任何一份用 `videos.list` 拿到的快照裡,不管快照存不存在都一樣看不到。這個限制**對 repo 裡每一支用 `videos.list` 讀回再整包送出的腳本都成立**(zombie_sweep、privatize_fabricated、set_private_leaks、set_public),不是 07-15 這批獨有。

---

## 六、STUDIO/_private_batch_ids.json 與這 13 支有沒有交集

`youtube_channel/STUDIO/_private_batch_ids.json`(現存活文件,不在版控)目前內容:
```
["oq4I_jtEw3Q", "ODN9YzdBopA", "7C79mFmnFrE"]
```
與 13 支清單(§二)**無交集**。因為該檔不在版控(§五.2 第 6 點同理),無法用 git 查它「以前」有沒有列過這 13 支中的任何一支;只能確認**現在**沒有。`candidates.json` 的 note 本身已經明講「🔴 不要把這些 id 放進去」,目前看起來這個提醒有被遵守。

另外用 `git log --all -S<videoId> --oneline` 逐支查這 13 個 videoId 字串在全 repo 歷史的哪些 commit 出現過(用意:如果曾被任何追蹤中的程式/資料檔硬編碼過,會留痕)。**13 支全部查完**:12 支各命中 3 個 commit,`tN56crKxwJE` 命中 4 個。經核對,這些 commit **清一色只有這次調查自己寫的 docs/ops commit**:`627a3f4e`(母體掃描)、`11f90c70`(13 支準備與 dry-run)、`25bdeb72`(追記更正,即本次調查開始前的 HEAD),`tN56crKxwJE` 多一個 `46da06e0`(docs:那 72 次 fail-open 真的放出了什麼——它是 627a3f4e 引用的上游報告,提過這支「退化旁白」片當例子)。**沒有任何一個 code commit** 提過這 13 個 videoId 中的任何一支——符合預期,因為會操作這些 videoId 的 STUDIO 執行期資料本來就不進版控,git 這條路在這裡結構性看不到東西,不是「查了沒有」而是「這個問題 git 答不出來」。

---

## 七、方法論 / 已跑指令清單(供覆核)

```
git log -S containsSyntheticMedia --all --oneline
git log -S SyntheticMedia --all --oneline
grep -rE "videos\(\)\.(insert|update)" --include=*.py -l   (type:py, 全 repo, 56 個檔案)
grep -rE "privacyStatus" --include=*.py -l                  (type:py, 全 repo, 48 個檔案)
grep -n "privacyStatus" -C8  youtube_channel/scripts/*.py    (逐一讀 status dict 組法)
grep -n "videos().update\|videos().insert\|status\[" <15 支非 status 更新腳本>  → 全部只 part="snippet"，不動 status
git log --all --oneline --before="2026-08-04T08:02:15Z" -1 -- youtube_channel/scripts/{daily_publish,upload_youtube,schedule_publish}.py
git show <commit>:<path> | grep -n '"status":\|"privacyStatus":' -A5   （08-04 端点)
git log --all --oneline --before="2026-08-11T18:01:57Z" -1 -- 同上三檔
git show <commit>:<path> ...   （08-11 端点)
git log --all --oneline --since=2026-07-01 --until=2026-08-12 -- youtube_channel/scripts/daily_publish.py   （確認窗口內有哪些改動,逐一看 commit 訊息無一涉及 status/containsSyntheticMedia）
git log --all --oneline -- youtube_channel/STUDIO/_private_batch_ids.json      → 零結果(gitignored)
git log --all --oneline -- "youtube_channel/STUDIO/privatize_backup/*"        → 零結果
git log --all --oneline --follow -- youtube_channel/STUDIO/zombie_sweep_state.json  → 零結果(gitignored)
find youtube_channel/output/privacy_reports -maxdepth 1
grep -rl "containsSyntheticMedia\|SyntheticMedia|zombie_sweep|殭屍片" docs/ops
diff -q youtube_channel/scripts/{daily_publish,upload_youtube,zombie_sweep,set_private_by_ids,set_private_leaks,set_public,schedule_publish}.py yt_ch2/scripts/同名檔  （確認 ch2 是獨立副本,不是同一份檔案)
python3 -c "... json.load(zombie_sweep_state.json) 按 date+reason 分組統計 ..."  → 07-15: already_private 12, 0view_14d+ 17
for id in <13支videoId>; do git log --all -S"$id" --oneline; done   （逐支查 git 有沒有留痕，全數只命中本次調查的 3 個 docs commit）
```

未做(依硬規則):任何 `videos.list`/`videos.update` 等 YouTube API 呼叫、yt-dlp、抓網頁、讀 `.env`/token/credential 檔、任何 git write 操作(add/commit/checkout/stash)。
