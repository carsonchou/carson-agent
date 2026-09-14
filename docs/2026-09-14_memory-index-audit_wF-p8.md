# MEMORY.md 索引核對(唯讀)—— wF:p8 執行,2026-09-14 14:05–14:12

全程唯讀,**沒有修改 `MEMORY.md`,沒有修改 `memory/` 任何檔案**。
量測對象:`D:\claude\projects\D--carson-agent\memory\MEMORY.md`
現況(14:05:29 量):**31,713 bytes**,**140 行**,mtime **2026-09-14 13:59:56**,
sha256 `2acb431a843183296c677ae104faa1f7779bc279dd1eff6d76bf140cfb85c569`。
(31,713 與 wF:p5 14:0x 的數字相同;mtime 13:59:56 是**我自己那次寫入**。)

## 一、三筆點名的索引行 —— 三筆都在(獨立重量,沒有引用 wF:p5)
指令:`grep -c "(<slug>.md)" MEMORY.md` 與 `grep -n`,逐筆分開跑,退出碼 0,無逾時。

| 索引行 | 命中數 | 行號 |
|---|---|---|
| `rule-scope-not-narrowed-by-the-bound.md`(w9) | 1 | **71** |
| `restore-recreates-the-trigger-condition.md`(總督導) | 1 | **80** |
| `caveat-needs-a-withdrawal-condition.md`(wF:p8) | 1 | **140** |

## 二、孤兒清單(只列清單,不下結論)
- `memory/*.md` 檔案數(不含 `MEMORY.md`):**203**
- `MEMORY.md` 內出現的連結目標(去重):**162**
- **A. 有檔案、索引裡沒有 = 41 個**(203 − 162 = 41,數目自洽)
- **B. 索引指得到、磁碟上沒有 = 0 個**(沒有斷鏈)

抽取法的陰性對照:另用較寬的樣式 `](...)` 再抽一次,同樣得到 **162**,兩種抽法差集為空
⇒ 抽取沒有因為樣式寫太窄而漏掉目標。

**A 的 41 個**(`_index_backup_2026-09-01.md` 除外的 40 個,見下節):
```
_index_backup_2026-09-01.md            carson-trip-2026-06.md
carson-triple-supertrend-strategy.md   cs2-dx11-render-device-troubleshoot.md
cs2-inventory-context16-gotcha.md      docker-dead-end-go-dockerfree.md
droplet-false-alarm-cloud-routine.md   droplet-upgrade-deferred.md
evolution-command-pattern.md           ig-black-thumbnail-fix.md
krypt-trader-audit-2026-07.md          opire-bounty-liquidity-2026-08.md
oss-tools-install-2026-06-27.md        proactive-skill-use.md
ruflo-claude-detect-windows-fix.md     skills-toolkit-map.md
skinclub-case-ev-2026-08.md            standing-on-skills.md
studio-black-window-popups-fix.md      tradingview-scraper-state.md
web-center-analytics-tab.md            web-center-orb-plasma-bloom.md
youtube-shorts-algorithm-2026-research.md   yt-binge-breakout-2026-08-21.md
yt-breakout-execution-2026-07.md       yt-cadence-experiment-2026-08.md
yt-ch2-first-publish-2026-08.md        yt-ch2-fluid-ambient-2026-08-22.md
yt-debunk-short-vida-2026-07.md        yt-endscreen-ui-automation.md
yt-growth-sprint-2026-07-12.md         yt-healthcheck-concurrency-2026-07.md
yt-long-thumbnail-aspect-bug.md        yt-niche-scan-tool-2026-08.md
yt-optimization-sweep-2026-07.md       yt-premlogin-monetization-2026-07.md
yt-quota-form-blocked-on-carson.md     yt-second-channel-ai-money-2026-07.md
yt-second-channel-prediction-arena.md  yt-studio-2026-06-25-upgrades.md
yt-viral-experiment-series-strategy.md
```
⚠️ 照你的話:**孤兒不一定是 lost update**,我不判。

## 三、順手量到的一個基準(不在派工範圍內,但它是唯一存在的歷史比較點)
孤兒之一 `_index_backup_2026-09-01.md` 是**一份 09-01 01:17 的舊索引快照**
(45,237 bytes、159 行、154 個連結目標)。它是目前磁碟上**唯一**能拿來跟今天對照的東西。

**C. 09-01 索引裡有、今天索引裡沒有的連結目標 = 40 個,而且這 40 個檔案全部仍在磁碟上。**
這 40 個正好等於「A 的 41 個扣掉快照檔本身」⇒ **今天的孤兒,全部都曾經在 09-01 的索引裡。**

對照數字:09-01 = 159 行 / 154 個目標;今天 = 140 行 / 162 個目標。
⇒ 行數少了 19,目標多了 8;期間掉了 40 個舊目標、加了 48 個新目標。

⚠️ **我不判斷這 40 個是被誰、在什麼時候、有意還是無意弄掉的。** 可能的解釋至少三種
(有人刻意精簡索引 / 多次 lost update 累積 / 改寫時整段被覆蓋),**我沒有證據分辨,判斷交給總督導。**

## 四、⚠️ 量不到的部分(限制要有輸出,不靜默)
1. ⚠️ **「今天有沒有發生 lost update」量不到。** `MEMORY.md` 沒有版控、沒有逐次備份,
   我只看得到**現在這一版**。三筆點名的行現在都在,這只證明**那三筆**沒被吃掉,
   **不能**推論「今天沒有任何一行被吃掉」—— 受害者可能是別的行,而它現在長得跟從來沒存在過一樣。
   **撤銷條件**:把 `memory/` 納入版控(或每次寫入前留一份帶時間戳的副本),之後才量得到。
2. ⚠️ **09-01 到今天之間的中間版本量不到**,所以第三節那 40 個的**發生時間**無法定位。
   **撤銷條件**:同上;或有人能提供 09-01 之後的另一份快照。
3. ⚠️ **各條線「我加了索引行 X」的完整清單我手上沒有**,我只核了你點名的三筆。
   若還有第四、第五筆,請給 slug,我可以用同一支指令補核(每筆 1 秒)。
   **撤銷條件**:拿到完整清單並逐筆 grep。
4. ⚠️ 本次全部用 `grep` 做**字串比對**:它量得到「這個 slug 出現在檔裡」,
   量不到「那一行的敘述文字有沒有被別人改壞」。**撤銷條件**:對每一行做內容比對,需要基準版本(見 1)。

## 五、我自己的自查(照新規則二:附可重跑的檢索指令,不憑記憶)
宣稱:**我今天對 `MEMORY.md` 只做過一次「純附加一行」,沒有整檔重寫。**
可重跑的檢索:本 session transcript
`D:\claude\projects\D--carson-agent\818543e1-d51c-4902-b6ed-bcbcf3d20af1.jsonl`,
搜 `MEMORY.md.new` —— 唯一一次寫入的指令原文是
`cat "$MEM/MEMORY.md" "$TMP/idx.line" > "$TMP/MEMORY.md.new"` 後接前綴 sha256 比對再 `mv -f`。
⚠️ **但這條自查只涵蓋本 session(818543e1)**;09-12 之前的舊 session 我查不到,那部分寫「未查」不寫「否」。
