# 播放清單/binge_chain 讀者調查 —— 13 支候選設 private 之前的靜態調查

調查時間:2026-09-11。唯讀,未改動任何檔案、未 commit、未執行任何腳本、未打 YouTube API。
範圍:`youtube_channel/scripts/{playlist_engine,build_playlists,binge_chain,channel_storefront,industry_playlists}.py` 全檔 + 各自的 crontab 排程 + 讀寫到的狀態檔。

---

## 0. 候選清單(13 支,全部 slug 開頭 `S_` = Shorts)

| videoId | slug(節錄) |
|---|---|
| MuXiM5IqVQQ | 台積電暴跌35元…0050回測 |
| TDbm4XR5pYk | CPI破254…追高 |
| cObU5NcFT-I | CPI連破3個月…通膨怪獸 |
| I8F83sPFKWg | 非農資料利空…0050定投 |
| _Cc49y7ZAeM | Fed恐慌殺…資金配置 |
| tN56crKxwJE | 台積電飆破800元…網格機器人 |
| mvDrUnxEjWs | 市場狂熱…網格機器人 |
| vwEaoo3Txjw | CPI爆表0050定投vs恐慌殺出 |
| UTuMMyvdQ5U | 0050定期定額…回檔 |
| DhX2uNzjZ-o | 臺股暴漲5000點…0050網格 |
| OyprNxjrIBQ | 市場巨變…自動交易設定 |
| nHwP_cyy_hc | CPI資料一公佈…網格機器人 |
| xjQPW3sTY28 | 升息499…投資組合 |

---

## 1. playlist_engine.py 全檔讀碼結論

- **挑片來源**:`STUDIO/uploaded_ledger.json`(slug→videoId),`playlist_engine.py:69,223-225,356`。**不是** videos.list、**不是**即時查 YouTube,純本機檔案。
- **分類規則**:純字串比對 slug(`classify()` / `PLAYLIST_DEFS`,`playlist_engine.py:102-215`),與 privacyStatus 完全無關。
- **有沒有檢查 privacyStatus**:**沒有**。全檔 grep `privacyStatus` 只出現 3 處,全是「新建播放清單本身」要設 public(`playlist_engine.py:304`),不是檢查影片的 privacyStatus。分類、插入邏輯都不讀影片狀態。
- **冪等判斷**:`--sync` 用 `_playlist_items(yt, plid)` 即時呼叫 `playlistItems.list` 讀回**播放清單真實成員**(`playlist_engine.py:267-288`),不是只信本機狀態檔。已是成員的 vid 在迴圈裡 `if vid in existing: continue`(`playlist_engine.py:422-423`),**不會重複 insert**。
- **會不會移除**:**不會**。全檔沒有任何 `playlistItems().delete` 呼叫(grep 確認 0 命中)。docstring 明講「只會建立播放清單／加入影片,絕不刪除、絕不改動影片本身」(`playlist_engine.py:45`)。
- **結論**:已經是清單成員的私有化影片 → 下次 `--sync` 跑,`playlistItems.list` 讀回時如果 YouTube 仍把它算作成員(見下方「無法判定」條目),`vid in existing` 為真 → **不會被重新 insert**(因為根本沒被移除過,一直都在);但也**永遠不會被移除**,會無限期留在公開清單的成員列表裡。
- **掛勾點**(`add_to_playlists()`,`playlist_engine.py:467-509`):只在 `daily_publish.py` 的 `upload_one()` **新上傳成功後**呼叫一次(`daily_publish.py:1464-1470`,呼叫點 `daily_publish.py:1466`)。設 private 的舊片不會觸發這條路徑(它們早就上傳過,不會再跑一次 upload_one)。

## 2. 其他讀寫這兩個狀態檔的程式

### build_playlists.py(`youtube_channel/scripts/build_playlists.py`)
- 來源同樣是 `uploaded_ledger.json`(`build_playlists.py:39,66-73,95`)。
- 分類規則 `classify()`(`build_playlists.py:56-63`),同樣**不檢查 privacyStatus**(grep 全檔 `privacyStatus` 只在建立新播放清單時出現一次,`build_playlists.py:138`)。
- 冪等:`items_in(plid)` 即時 `playlistItems.list` 讀回真實成員(`build_playlists.py:145-159`),`if vid in existing: continue`(`build_playlists.py:184-185`)。
- **沒有移除邏輯**(grep 0 命中 `delete`)。
- 🔴 **新發現,不在原本 7 支清單裡**:`tN56crKxwJE`(slug 含「台積電」)在 `uploaded_ledger.json` 裡已存在(`STUDIO/uploaded_ledger.json` 確認 1 筆),用 `build_playlists.py:56-63` 的規則跑出來會命中「台股量化」桶(含關鍵字「台積電」),但**目前不在** `STUDIO/playlists.json` 的「台股量化」`video_ids` 裡(grep `tN56crKxwJE` 對 `playlists.json` 是 0 命中)。也就是說它符合分類規則、卻還沒被加進去——原因不明(可能只是這桶還沒輪到它、或某次 `--max` 用罄前沒排到),但**下一次 cron 跑 `build_playlists.py --max 10` 時,腳本會對它呼叫一次 `playlistItems.insert`**,把它**第一次**加進公開播放清單「台股量化」(`PLeVKglwbcJSQ`)——而且完全不會檢查它那時已經是 private。
- **排程**:`youtube_channel/deploy/crontab.txt:423`:`0 22 * * 4 ... scripts/build_playlists.py --max 10`——**每週四 22:00,目前是啟用中的(沒被註解掉)**。

### binge_chain.py(`youtube_channel/scripts/binge_chain.py`)
- 讀 `playlist_engine.json`(`PE`,`binge_chain.py:60`)、`playlists.json`(`BUCKETS`,`binge_chain.py:61`)、`industry_playlists.json`(`IND_PL`,`binge_chain.py:59`)——但只取裡面的 **`playlist_id`**(清單層級),不逐一讀 `video_ids`(`binge_chain.py:170-179`)。
- 建鏈的影片來源是 `uploaded_ledger.json`(`binge_chain.py:164,183`),但 **明確排除 Shorts**:`if not isinstance(vid, str) or not vid or slug.startswith("S_"): continue`(`binge_chain.py:184`,註解在 `binge_chain.py:181`:「只做長片(S_ 開頭是 Shorts…)」)。
- **13 支候選全部 slug 開頭 `S_`** → 全部在 `build_chain()` 的第一關就被濾掉,**永遠不會**被排進任何一支長片描述欄的「▶ 接著看下一集」連結、也不會被設成任何長片的 `next`。這條是**規則保證**,與是否被設 private 無關。
- **沒有移除邏輯**(grep 0 命中 `delete`)。
- **排程狀態**:`youtube_channel/deploy/crontab.txt:667` 該行**已被整行註解掉**,行首寫著「`[2026-08-30 暫停·換發布額度]`」——**binge_chain.py 目前完全沒有在排程裡跑**。即使哪天恢復排程,S_ 過濾規則(`binge_chain.py:184`)仍會擋掉這 13 支。

### channel_storefront.py(`youtube_channel/scripts/channel_storefront.py`)
- `plan_sections()`(`channel_storefront.py:58-81`)只讀 `playlist_engine.json` 和 `industry_playlists.json` 裡的 **`playlist_id`**(清單層級的 ID),組成首頁 `channelSections`(播放清單櫥窗),**完全不觸碰個別 videoId**。跟這 13 支影片本身無直接引用關係——只要它們所屬的播放清單(`etf_dca`＝`PLJp7y2jl2p64`、`台股量化`＝`PLeVKglwbcJSQ`、`AI×交易`＝`PLJ7Vh3Tbtnac`)還在首頁櫥窗裡,理論上私有成員存在其中(見下方「無法判定」)。
- **排程**:全 `crontab.txt` grep 不到 `channel_storefront` 任何一行——**沒有排程**。腳本自己的 docstring 也寫明「一次性重建後不再排程」(`channel_storefront.py:64`)。
- 順帶查了實際每天在跑的門面腳本 `channel_facelift.py`(`crontab.txt:656`,每日 16:05,啟用中):grep 全檔 `playlist_engine|playlists.json|industry_playlists|video_id` 都對不到這 13 支相關內容,它管的是「個股體檢 EP0 trailer + 貨架」單一影片,跟這批 Shorts 無關。

### industry_playlists.py(`youtube_channel/scripts/industry_playlists.py`)
- 來源同為 `uploaded_ledger.json`(`industry_playlists.py:64,118`)。
- 分類規則 `match_stock()`(`industry_playlists.py:97-113`)要求 slug 裡**同時**命中「4-6 位數股票代號」與「該代號對應股名」,且代號要能在 `industry_map.json` 查到(該表只收個股,不收 ETF)。
- **實測跑過規則,13 支全部 `match_stock()` 回傳 `None`**——原因:`0050` 不在 `industry_map.json`(只收 1925 檔個股,ETF 代號查無),其餘 12 支 slug 裡雖有「台積電」等股名字樣,但沒有搭配對應的 4-6 位純代號子字串(例如「800元」「35元」是價格/漲幅數字,長度不合規則,`tN56crKxwJE`/`MuXiM5IqVQQ` 含「台積電」三字但沒有「2330」)。**規則保證這 13 支永遠不會被此腳本歸類、永遠不會被加進任何產業播放清單**,與是否設 private 無關。
- 另外 `industry_playlists.json` 這份狀態檔本身**只存清單層級**(`{"playlists": {產業: {id, title, n, updated}}}`,`industry_playlists.py:254-255`),**不存個別 video_ids**——即使真的命中,也無法從這份狀態檔本身查出哪些片是成員,要驗證只能查即時 API(不在本次唯讀範圍內)。
- **排程**:`crontab.txt:584`:`50 16 * * 5 ... scripts/industry_playlists.py --apply --max 10`——每週五 16:50,**啟用中**,但因規則保證不命中,對這 13 支不構成風險。

### 其他讀寫者(grep 全 `youtube_channel/scripts/` 目錄)
`grep -rl "playlist_engine\.json\|playlists\.json\|industry_playlists\.json" youtube_channel/scripts/*.py` 只命中上述 5 支腳本本身(`.pyc` 快取不計),**沒有其他讀者**。另外 grep `add_to_playlists` 全 repo 只有 `daily_publish.py`(呼叫端,`daily_publish.py:1466`)與 `playlist_engine.py`(定義端)兩處,確認沒有第二條路徑會觸發播放清單 insert。

## 3. crontab 排程總表(`youtube_channel/deploy/crontab.txt`)

| 腳本 | 排程 | 狀態 | 行號 |
|---|---|---|---|
| build_playlists.py --max 10 | 每週四 22:00 | **啟用中** | crontab.txt:423 |
| playlist_engine.py --sync --max 10 | 每週二 13:40 | **啟用中** | crontab.txt:562 |
| industry_playlists.py --apply --max 10 | 每週五 16:50 | **啟用中** | crontab.txt:584 |
| binge_chain.py --apply --max 8 | 每天 17:05 | **已停用**(2026-08-30 整行註解) | crontab.txt:667 |
| channel_storefront.py | 無 | 未排程(一次性工具) | — |
| channel_facelift.py --apply | 每天 16:05 | 啟用中,但不涉及本批 13 支 | crontab.txt:656 |

## 4. 逐支結論

| videoId | 目前狀態檔位置 | 會被重新加回? | 會被繼續引用? | 承重依據(檔案:行號) |
|---|---|---|---|---|
| MuXiM5IqVQQ | playlists.json(台股量化)+ playlist_engine.json(etf_dca) | 不會重新 insert(本來就是成員,腳本無移除邏輯,不會消失也不會被清點兩次) | **會**——會無限期留在兩個公開播放清單的成員列表裡(build_playlists.py:184-185、playlist_engine.py:422-423 的冪等判斷只跳過已存在者,從不移除) | build_playlists.py:145-185;playlist_engine.py:267-288,406-423,45 |
| OyprNxjrIBQ | playlists.json(AI×交易) | 不會重新 insert | **會**——同上,留在「AI×交易」清單成員列表裡 | build_playlists.py:184-185(同上邏輯) |
| I8F83sPFKWg | playlist_engine.json(etf_dca) | 不會重新 insert | **會**——留在「0050/ETF 定期定額實驗」清單成員列表裡 | playlist_engine.py:422-423 |
| vwEaoo3Txjw | playlist_engine.json(etf_dca) | 不會重新 insert | **會**——同上 | playlist_engine.py:422-423 |
| UTuMMyvdQ5U | playlist_engine.json(etf_dca) | 不會重新 insert | **會**——同上 | playlist_engine.py:422-423 |
| DhX2uNzjZ-o | playlist_engine.json(etf_dca) | 不會重新 insert | **會**——同上 | playlist_engine.py:422-423 |
| tN56crKxwJE | **不在任何狀態檔**,但在 uploaded_ledger.json | 🔴 **會被首次 insert**——符合 build_playlists.py 分類規則(含「台積電」→台股量化桶),尚未被加入,下週四 cron 會嘗試 `playlistItems.insert`,不檢查 privacyStatus | 若 insert 成功,會**首次**變成「台股量化」公開清單成員 | build_playlists.py:56-63(classify),423(crontab 排程);uploaded_ledger.json 內確認 1 筆 slug→tN56crKxwJE |
| TDbm4XR5pYk / cObU5NcFT-I / _Cc49y7ZAeM / mvDrUnxEjWs / nHwP_cyy_hc / xjQPW3sTY28(共 6 支) | 不在任何狀態檔 | 不會——build_playlists.py / playlist_engine.py / industry_playlists.py 三套分類規則跑過,全部 0 命中(見第 2 節實測結果) | 不會——同理,且全部 slug 開頭 `S_`,binge_chain.py 直接濾掉(binge_chain.py:184) | build_playlists.py:56-63;playlist_engine.py:102-215;industry_playlists.py:97-113(三套規則實測跑過 13 支 slug,結果見上方表格) |

補充:candidates.json 13 支裡,原本使用者指出「出現在狀態檔裡的 7 支」實際上是 **6 個不重複 videoId**(MuXiM5IqVQQ 同時出現在兩個狀態檔,只算一次);扣掉這 6 支,剩 7 支不在狀態檔裡,其中 6 支(TDbm4XR5pYk 等)三套分類規則都不命中、確定安全,但**第 7 支 `tN56crKxwJE` 其實命中 build_playlists.py 的分類規則,只是還沒被排進清單**——這是本次調查唯一發現的「新增風險」,不在原本盤點的 7 支名單裡。

## 5. 無法靜態判定的部分(需要執行期資料,本次未查)

1. **私有影片是否仍會出現在 `playlistItems.list` 的回讀結果裡**(進而讓 `vid in existing` 判斷為真、觸發或不觸發 insert)——這是 YouTube API 執行期行為(以頻道擁有者身分呼叫 `playlistItems.list` 讀自己的清單,私有影片理論上仍算成員,但本次規則禁止打 API,無法用官方文件以外的方式實測驗證)。**無法判定,需要執行期驗證**。
2. **對已是 private 的影片呼叫 `playlistItems.insert` 會不會成功**(這會決定 `tN56crKxwJE` 一旦被排程處理時,是否真的能被加進公開清單,還是被 API 拒絕)。**無法判定,需要執行期驗證**。
3. **非訂閱者/一般觀眾在瀏覽公開播放清單頁面或首頁櫥窗時,是否看得到清單裡的私有影片項目**(YouTube 前端通常會隱藏,但這是產品行為,不是本次讀碼範圍能確認的)。**無法判定,需要執行期驗證**。
4. **`industry_playlists.json` 若真有命中(本次確認 13 支全部 0 命中,故此點只是理論上的方法論限制)**,該檔案結構不存個別 video_ids,單靠本機檔案無法查某支影片是否為某產業清單成員,需即時 API 查詢。

## 6. 硬規則遵守聲明

本次調查全程唯讀:未修改、未 `git add/commit/checkout/stash` 任何檔案;未執行 `playlist_engine.py`/`build_playlists.py`/`binge_chain.py`/`channel_storefront.py`/`industry_playlists.py` 或任何會打 YouTube API 的腳本;未呼叫 YouTube API、未用 yt-dlp、未抓網頁、未讀取 `.env` 或任何金鑰/token 檔(`token_manage.json` 等一律未讀取內容)。
