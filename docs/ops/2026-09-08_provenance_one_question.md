# 「這句數字哪來的?」—— 現在拿得出什麼(2026-09-08,只列清單不動保存)

> 收窄後的問句(總督導):**明天有人指著一支已發布的片問「這句數字哪來的」,我們現在拿得出什麼?**
> 本頁**只盤點,不做任何保存動作**。要動保存策略會碰正式機,先出清單。

---

## 〇、先用一支真的片走一遍,不要抽象談

實例:`_Jg5RnQlce4`,發布 **2026-09-06**
slug `L_個股體檢致伸49154915抱139年賺3424為何`

被質疑的句子(旁白開頭第一句):
> 「一檔股票,上市將近十四年,**含息總報酬高達百分之三百四十二點四**,**年化報酬率也有百分之十一點三**」

**追得到,而且追得很完整:**

| 欄位 | 值 |
|---|---|
| fact key | `checkup_long_horizon__4915` |
| claim | 上市以來(資料可信區間)約13.9年含息還原總報酬 **342.4%**(年化 **11.3%**、最大回撤 -57.9%、卡瑪比率 0.20) |
| method | 20年(可信資料區間不足20年則用上市至今)含息還原總報酬/年化/最大回撤/卡瑪比率 |
| period | **2012-10-03 ~ 2026-08-19** |
| source | Yahoo Finance(yfinance,`auto_adjust=True` 含息還原收盤價;已過 `_sanitize_series` 清洗) |
| computed_at | **2026-08-20** |

⇒ **對這一支,今天答得出來。** 下面是「靠什麼答得出來」以及「那些東西誰會刪」。

⚠️ 順帶兩個觀察(不是結論,機制我沒查):
- `computed_at` 是 **08-20**,片子 **09-06** 才發布 —— **中間 17 天**。事實與成品之間有時間差,而事實庫沒有記「這支片用的是哪一版」。
- `by_code['4915'].n_facts = 12`,而 `results` 裡實際只有 **11** 條(另有 `skipped` 1 條:
  `checkup_crash__4915__crisis2008` 資料不足)。**照 `merge_and_write` 的寫法 `n_facts` 應該等於產出數**,
  兩者不一致代表某一次寫入只更新了一半。拿「12 條」去對帳的人會找不到第 12 條。

---

## 一、五件東西,各自在不在

| # | 東西 | 現況 | 位置 |
|---|---|---|---|
| 1 | **旁白全文** | ✅ 在 | `output/{slug}.voice.txt`(遷移後長片 256/256);**09-08 起也在 git**(`a4dc9183`) |
| 2 | **事實 sidecar**(一支片一份的溯源檔) | 🔴 **全庫 0 支** | `.facts.json` / `.sources.json` / `.provenance.json` / `.fact.json` / `.evidence.json` **各 0**;`output/` 裡唯一的 `.json` sidecar 是 `.wordtimes.json`(769 個,那是 TTS 時戳不是溯源) |
| 3 | **事實本體** | ✅ 在,但**全域單檔、按股票代號存** | `STUDIO/stock_checkup_facts.json`(16MB / 7,742 組),key = `<factkey>__<code>`,**沒有集數或日期** |
| 4 | **字幕軌(可反抓)** | ✅ 長片 **250/305**(82.0%),已實測抓得回來 | YouTube `captions.download`(250 units/支);⚠️ **Shorts 完全沒有**(產線明文跳過) |
| 5 | **quality_score 稽核憑據** | ✅ 在 | `STUDIO/quality_scores.json`(846KB),`published[]` 內含 slug + videoId + score + 四維度子分 |

🔴 **第 2 項是這張表的重點**:**沒有任何一支片帶著「我用了哪幾條 fact」的紀錄。**
今天能把 342.4% 對回 `checkup_long_horizon__4915`,是靠**我人工比對數字**,
不是靠任何一份檔案記著那個對應關係。⇒ **溯源是重建出來的,不是保存下來的。**

---

## 二、刪除者清單 —— **列完再下結論**

總督導點名的那一個是「已知有一個」不是「只有一個」。逐項查:

### 2.1 `output/` 底下的成品與衍生檔

| 刪除者 | 動作 | 對已發布片 | 在排程? |
|---|---|---|---|
| `quality_score._move_slug_files`(`:525-541`) | `shutil.move` 整組 `{slug}.*` 到 `_rejected/` | ⚠️ **只保 `.voice.txt`**(`_AUDIT_KEEP_SUFFIX` 是**單一副檔名**)⇒ `.md`/`.srt`/`.mp4`/`.wordtimes.json`/`.mp3`/`.cover.jpg` **全部搬走** | ❌ 手動(`--reject`/`--tidy`/`--remake-all`、ntfy 指令、web_center 按鈕) |
| `recover_promo_blocked.py:96,115` | 就地覆寫 `.voice.txt`/`.md`、搬走其餘 | ✅ `if slug in led: continue` 跳過已發布 | ❌ 手動 |
| `fix_series_progress_claim.py:124` | 同上 | ✅ 跳過已發布 | ❌ 手動 |
| `redo_defective_unpublished.py:136` | 搬到 `_redo/` | ✅ 跳過已發布 | ❌ 手動 |
| `backfill_tts.py:63` | 刪 `*.part` 暫存 | — 非證據 | ⚠️ 隨主流程 |

⇒ **`output/` 這一層,唯一會碰到已發布證據的是 `_move_slug_files`,而它只留旁白。**
🔴 **後果:稽核憑據(旁白)留在 `output/`,而字幕/逐字時戳/成品被搬到 `_rejected/`
—— 同一支片的證據分家,而分家這件事沒有任何紀錄。**

### 2.2 事實本體 `stock_checkup_facts.json`

| 寫入者 | 機制 | 在排程? |
|---|---|---|
| `stock_checkup_daily.py:441` → `merge_and_write` | 同代號**就地覆寫**(先 `pop` 掉所有 `__{code}` 舊 key 再灌新的) | ✅ **在**(每日產線) |
| `checkup_fundamentals_backfill.py:133` → `merge_and_write` | 同上 | ❌ 手動 |

⇒ **同一檔股票被重新體檢一次,舊那組事實就沒了**,而片子還在線上引用它。
實測覆寫率目前 **1/198 = 0.5%**(低),但那是**現況不是保證** —— key 裡沒有集數/日期,
結構上沒有任何東西阻止它。

🔴 **另一個更大的**:`merge_and_write`(`:573-598`)是 **16MB 整檔 `write_text` 覆寫、無 tmp→replace**,
而讀取端 `_load_existing()` 的 `except: pass` 讀壞就**回空骨架**再寫回去
⇒ **一次失敗 7,742 組剩幾組,而它照樣印「已寫入」。**
(自動備份到 09-08 才補上,見 `341f048b`;在那之前 **64 天零備份**。)

### 2.3 上游原始數列(算出那些事實的輸入)

| 東西 | 保存期 |
|---|---|
| `STUDIO/tw_facts_cache/*.csv`(價格面) | **TTL 20 小時**,`_save_cache` 就地覆寫 ⇒ 產片當時用的價格數列**早就不在了** |
| `twdata/fundamentals_cache/*.json`(FinMind 原始回應) | ~~**TTL 30 天**滾動~~ 🔴 **2026-09-09 更正:不是單一 30 天,是**`stock_fundamentals.py:89` 的 `_TTL_H` **按 dataset 分級** —— 月營收/財報/股利 30 天,**`TaiwanStockPER` 只有 20 小時**,`TaiwanStockInfo` 7 天,而 `.get(dataset, 24)` **預設 24 小時**。⇒ 本益比這類逐日數字的上游輸入,保存期比本文原本寫的**短一個數量級**,而它正是最常進旁白的數字之一。同樣就地覆寫。 |

⇒ **能證明「我們算出 342.4%」,不能重算證明「342.4% 算得對」** —— 輸入沒留。
(有 `method` + `period` + `source`,理論上可重算,但要重抓資料,而財報數字會被追溯修正。)

### 2.4 YouTube 字幕軌(唯一一份不在我們磁碟上的副本)

| 刪除/覆寫者 | 動作 | 在排程? |
|---|---|---|
| `fix_captions_sync.py:122` | `yt.captions().update()` **取代**既有軌 | ❌ 手動 |
| `fix_caption_drift.py:165` | 同上 | ❌ 手動 |
| `zombie_sweep.py` | 只改 `privacyStatus`,**不動字幕** | ✅ 在排程,無害 |

⚠️ 而**取回**這條路目前**在程式碼裡不存在**:`upload_youtube.py:155` 的 `SCOPES` 沒有 `force-ssl`,
走 `get_authenticated_service()` 打 `captions.list` 回 **403**;全 repo 只有 `insert`/`update`,沒有讀回。

### 2.5 `quality_scores.json`

| 風險 | 說明 |
|---|---|
| `scan()` 整檔重寫 | 09-06 曾被一次**測試沙箱沒導 `STUDIO`** 的重掃覆寫,`pending` 148 → 0(`web-center-test-prod-misfire`) |
| 備份 | ✅ 在 `snapshot_studio.py` 的 7 檔清單裡,**回溯 7 天** |

---

## 三、結論(收窄後的問句,直接回答)

**「這句數字哪來的」現在答得出來,但答得出來的方式是脆的,脆在三個不同的地方:**

1. **沒有 sidecar** ⇒ 對應關係是**每次重建**的(人工比對數字),不是保存的。
   重建成功的前提是那組 fact 還在事實庫裡、而且數字沒被四捨五入到對不上。
2. **事實按代號存、不按集數** ⇒ 重新體檢一次就覆蓋。現在 0.5%,結構上無上限。
3. **輸入沒留** ⇒ 只證得了「我們算了什麼」,證不了「算得對」。

**而刪除者列完之後,最該注意的不是刪除,是分家**:
`_move_slug_files` 只保 `.voice.txt` ⇒ 一支已發布片被退件之後,
**旁白留在 `output/`、字幕與逐字時戳在 `_rejected/`,而沒有任何紀錄說它們是同一支片的。**
下一個人看 `output/` 會以為那支片的證據不完整。

## 四、沒做(等裁示)

- **不做**任何保存動作(建 sidecar、改保留策略、動 `_AUDIT_KEEP_SUFFIX`)—— 都會碰正式機。
- 若要動,**最小且不碰產線邏輯的一步**是:產稿時把「本支用到的 fact keys + computed_at」
  寫成一個 `{slug}.facts.json` sidecar。它**只新增檔案、不改任何既有行為**,
  而它解掉的是第 1 項(對應關係不再需要重建)。⚠️ 這只是建議,**我沒有做**。

---

## 五、🔴 sidecar 不用我做了 —— 主頻道線今天已經做完(`cb52ae03`)

交辦「做那個 sidecar」之後我先去看插入點,發現 `produce_batch.py:6455` 已經有一整段
**2026-09-08 的事實溯源 sidecar 實作**。`git log` 確認是 `cb52ae03`
(`feat(誠信·產製端): 落盤「這支片是從哪些 fact 寫出來的」`),落在我上一個 commit 之後。

⚠️ **我應該先跑 `git log` 再動手的**(memory `parallel-sessions-same-repo`:那是唯一看得到
別的 session 做了什麼的窗口)。差一點做出第二份。

**它的設計比我提的完整**:`tmp → os.replace`(避開 `write_text` 先截斷後拋例外留 0 bytes 的事故)、
整段 fail-open 且失敗記一行 ops、插入點選在「slug 已定案 + 旁白已落盤 + TTS 之前」並把三個理由寫在註解裡。

⇒ **我改成驗它,而不是再做一份。**

### 為什麼需要驗:`output/*.facts.json` 現在是 0

**「還沒產片」和「這條路是壞的」在觀測上一模一樣** —— 那正是本文件與閘門盤點整天的主題。
(今天已經有一個實例:watchdog 的救援路徑裝了五天沒被走過,一走就發現它會生出一個開跑就死的排程器。)

### 驗到的(執行期,不是讀碼)

鏈路:`_record_fact_keys`(:2148)→ `_LAST_FACT_KEYS`(:2167)→ `call_claude` pop(:2842)
→ `result["_fact_record"]`(:3026)→ `make_one` 寫 `{slug}.facts.json`(:6466-6483)。

| 檢查 | 結果 |
|---|---|
| `_fact_record_key(topic)` 是否穩定(同 topic 兩次同鍵) | ✅ `True`(`'id:checkup_4915'`) |
| 記進去拿得回來 | ✅ 內容完整:`topic_id` / `topic_fact_key` / `facts_as_of` / `fact_keys` / `n_facts` / `selection` |
| 🔴 **陰性對照**:別的 topic 拿不到這一筆 | ✅ `None` —— 沒有這個對照,「拿得回來」和「對誰都回同一筆」分不開 |

### 兩個角落(**是銳角不是活 bug**,講清楚免得被當警報)

`_fact_record_key`(:2137-2146)沒有 `id` 時**退回 `"title:" + title[:160]`**:

- 兩個**都沒有 id 且標題相同**的 topic 會撞同一把鑰匙;`{}` 空 topic 退回 `'title:'`,多個空 topic 全部同鍵。
- **為什麼目前不是活 bug**:`call_claude` 是**記錄完隨即 pop**(:2842),同一支流程內
  record→pop 是連續的;而平行跑是**不同 process、不共用模組狀態**。
  ⇒ 要撞到需要**同一個 process 內交錯**兩支無 id 同標題的產製。
- 同理 `if len(_LAST_FACT_KEYS) > 64: clear()`(:2165)會清掉**全部**,理論上能清掉一筆
  正在飛的記錄 —— 同樣需要交錯才會發生。
- ⇒ **不建議現在改**。要防的話最小改法是 key 併入 `fact_key`(那是每支片唯一的),
  但那要主頻道線自己決定,而且改 key 就要重驗上面那張表。

### 可證偽的期望(給下一個人對答案)

**下一輪產製跑完之後,`output/` 應該出現 `*.facts.json`,數量 = 那一輪產出的個股體檢片數。**
- 對得上 ⇒ 這條路是通的。
- **產了片而 sidecar 是 0** ⇒ 鏈路在 `:2842`~`:6466` 之間斷掉,去看 `ops_log` 有沒有
  「補產·事實溯源 ⚠️ … sidecar 寫入失敗」那一行(它是 fail-open 的,所以**不會有別的訊號**)。
- 查法零成本:`ls youtube_channel/output/*.facts.json | wc -l`。

---

# 🔴 補記(2026-09-09):上面那份清單漏了 19 條,其中 16 條在排程上

> 本節由一支 fresh-context agent 以「**試圖證明上面那份清單不完整**」為題掃出來,
> 再由 wF:p3 逐條複驗(標「已複驗」的是我自己查過原始碼/檔案系統,不是轉述)。
> ⚠️ **上面 §二 那份不是錯的,是「已知有這些」**。本節補的是「還有這些」。

## 〇、先對齊主頻道那一半的答案

`scripts/auditability_coverage.py` 的結論:**遷移後 234/234 = 100.0%**;
**07-06 以前的 47 支結構上永遠查不了**(2026-07-05 droplet 停權,`output/` 從來沒被複製到本機)。
⇒ 那 47 支不是「還沒查」是「查不了」,不要再排進待辦。

## 一、🔴 最高風險:`snapshot_studio.py:109` —— 本文引用了保護,沒引用執行保護的那把刀

**已複驗**。`shutil.rmtree` 掉 `STUDIO/_snapshots/YYYY-MM-DD/`,`KEEP_DAYS = 7`,
排程 `5 4 * * *`(`crontab.txt:333`),**無例外清單**。

本文 §2.5 說 `quality_scores.json` 的備份「回溯 7 天」—— **那 7 天就是 `KEEP_DAYS=7`,由 `:109` 執行**。
本文引用了那個安全網,卻沒把執行它的那把刀列進刪除者。

🔴 **而實測的復原深度比 7 天短得多**(2026-09-09 直接數檔案):

| 快照夾 | 有 `stock_checkup_facts.json` 嗎 |
|---|---|
| 09-03 ~ 09-07(5 天) | ❌ **沒有** |
| 09-08 | ✅ 17,037,478 bytes |
| 09-09 | ✅ 17,483,619 bytes |

⇒ **事實庫的復原窗口是 2 天,不是 7 天**(它 09-07 才進 `KEY_FILES`;
`snapshot_studio.py:28-40` 的註解自己寫著「07-05 起事實庫零自動備份,零訊號」)。

配上本文 §2.2 已經查到的那條鏈 —— 16MB `write_text` **無 tmp**、讀取端 `except: pass` 退成空骨架、
**壞掉照樣印「已寫入」** —— 完整的失敗形態是:
**靜默寫壞 → 零訊號 → 沒人發現 → `:109` 在第 3 天刪掉最後一份好的 → 198 支已發布片的「這句數字哪來的」永久答不出來。**
這條鏈上每一環本文都寫到了,**唯獨沒寫那個把窗口關上的動作**。

## 二、🔴 第二名:`local_cron.py:313` —— 觸發在即,而且它動手時不會出聲

**已複驗**:`if ERRLOG.stat().st_size > 5_000_000: ERRLOG.write_text("")`,
在**每 60 秒的派工迴圈**裡,整段包在 `except: pass` 內。
**現況 `logs/job_stderr.log` = 4,417,756 bytes = 88.4%**,近期必觸發。
它銷毀的是「憑據寫入失敗時唯一會落地的那行字」——全機排程 job 的 traceback 就這一份。
`:328` 對 `logs/jobout/<腳本>.log` 同形狀(門檻 `2_000_000`,一支一個檔各自算)。
(`ops.py:17` 是 `OPS.open("a")` **純附加無輪替** ⇒ ops_log 安全,本文第五節那個可證偽期望站得住;
但 `produce_batch` 的 stdout 只落在 `jobout/produce_batch.log`,那份會被歸零。)

## 三、補充清單(19 條,依現有文件**沒有**的列)

### A. 銷毀「稽核憑據的備份」——本文一條都沒有(4 條,全在排程)
`snapshot_studio.py:109`(見上)/ `ch3_health.py:47` `rmtree` `ch3_lab/_backup/`(`30 9 * * *`)/
`local_cron.py:313`、`:328`(見上)。

### B. 覆寫「線上那一份」——§2.4 只查了字幕軌,沒查描述(6 條,全在排程)
`desc_backfill.py:262`(`0 14 * * 3`,先讀現行 snippet、`len(new)<len(old)` 跳過 ⇒ 相對安全)/
`fix_period_disclaimer.py:176`(`5 15 * * *`,**有**逐片備份 `:169`)/
`ab_title.py:267`(`0 3 * * 1`,改**標題** ⇒ slug↔videoId 的人工比對線索斷一截)/
`ab_thumbnail.py:370`(`20 3 * * 5`)/ `channel_facelift.py`(`5 16 * * *`,不動單片)/
`fix_audio_language.py:99`(`25 15 * * *`)。

⚠️ **§2.4 的「取回這條路不存在(`captions.list` 403)」只適用字幕軌** ——
描述側 `desc_backfill.py:239` 用 `videos().list(part="snippet")` 讀得回來。

### C. TTL(2 條)
`hidiv_showdown_facts.py:103`/`:118`(TTL 20h)、`stock_fundamentals.py:118`(分級,見上面對 §2.3 的更正)。

### D. `output/` 這一層(4 條)——§2.1 的「唯一」是對的,但理由不是它以為的那個
`produce_batch.py:6524` `unlink(missing_ok=True)` 會刪 `.mp4`/`.mp3`/**`.voice.txt`**,
🔴 **而它不碰已發布片靠的不是檢查**:程式碼裡**沒有任何 `slug in led` 已發布判斷**,
靠的是「它跑在產製當下」這個時序巧合。相對地 `:6671` 的 `rename` **有**明寫保護(`if _old in _led: continue`)。
⇒ **同一支檔案裡,一條靠不變式、一條靠巧合。** 另:`tts_edge.py:179`、`refresh_backlog_hooks.py:157/:171/:175`(❌手動)。

### E. 合規性刪除(3 條,定義邊緣但都在排程)
`purge_api_data.py:102`(`20 4 * * *`,保留 25 天)/ `intel_dept.py:70`(`30 13 * * 6`)/
`daily_publish.py:811` `write_text(json.dumps(...))` **整檔覆寫無 tmp→replace**,
對象是 `ig/fb/threads_ledger.json`,讀取端 `except: led={}`
⇒ **與 §2.2 的 `merge_and_write` 同一形狀**(主帳本 `:307` 走 `save_json_atomic`,安全)。

## 四、對本文的兩條更正

1. **§2.3 的「`fundamentals_cache` TTL 30 天」是錯的** —— 已在原處加撤回標記(見上)。
2. ⚠️ **降級 `fix_audio_language.py:99`**:掃查初稿把它排第二名,理由是「body 從 6 欄白名單**重組**」。
   **已複驗:那 6 欄(`title`/`description`/`categoryId`/`tags`/`defaultLanguage`/`defaultAudioLanguage`)
   就是 `videos.update` 能寫的 snippet 全集**,而 `sn` 是**同一輪** `videos().list` 讀回來的原值
   ⇒ **四個關鍵欄位都在,線上沒有被清空。** 掃查員收到質疑後自行更正,並主動聲明那格是讀碼不是實跑。
   殘留風險只剩三個小的:①零備份(對比 `fix_period_disclaimer:169` 有)②`if v is not None` 只擋 None,
   `videos().list` 回殘缺 snippet 就照樣送出 ③白名單**寫死六欄**,YouTube 日後新增可寫欄位會被靜默丟掉且不報錯。

## 五、⚠️ 這份清單的邊界(沒有這一格,「我沒找到」不可判斷)

- 🔴 **執行期行為完全沒驗**:全部是讀碼 + 排程表比對,「觸發條件」欄是**讀出來的不是看到的**。
- **雲端那份沒查**:`crontab.txt` 自稱是雲端 `crontab -l` 的同步版,而 droplet 07-05 已停權
  ⇒ 查的是本機 `local_cron` 對它的解析結果;雲端若有此檔沒有的行,看不到。
- `quant-service/` 只過 pattern 沒逐檔讀;`ch3_lab/` 只查了與主線共用的憑據 ——
  **ch3 自己的旁白/字幕保存策略要另一份清單**。
- `_archive/`/`_v2/`/`_baseline/`/`_ttslab311/`/`.claude/worktrees/` 沒掃
  (worktrees 下有 3 份 `quality_score.py` 副本,不在任何排程上)。
- **Windows 排程以外的常駐程序沒逐一清點**(當時 8 個 python/pythonw 在跑)。
- ⚠️ 那 3 條標 `Disabled` 的 `QuantArsen_*` Windows 任務**不代表沒在跑** ——
  它們同時在 `crontab.txt` 上,實際派工的是 `local_cron.py`。**Disabled 的是重複入口,不是那條路。**

掃描用的 pattern 與目錄清單、以及 `sitecustomize` 會把 `youtube_channel\scripts` 插到 `sys.path[0]` 的實地確認,
見本次掃查回報(逐字保留在 wF:p3 的 session 逐字稿)。
