# 13 支 public Shorts 設 private —— 準備與 dry-run(🔴 未執行、零 `videos.update`)

> 派工:督導 wF:p5 → w9:p1「(二)」。**Carson 尚未拍板要不要設。** 本檔只做到 dry-run。
> 來源:`627a3f4e` `docs/ops/2026-09-11_已發布壞片_空旁白與自我循環_母體掃描.md`。
> 產物資料夾:`docs/ops/2026-09-11_13支設private_準備/`。

## 結論

**dry-run 13/13 支送出去的 body 只差 `privacyStatus`(public→private)**,其餘 6 個欄位逐欄相同。
檢查器本身**會失敗**:兩列故意寫壞的 body 都被抓到,所以這個 13/13 不是檢查器恆過造成的。
全程零 `videos.update`,API 只讀,本輪共 48 units。

## 零、這份東西**不能**證明什麼

1. **dry-run 用的是 08:49 UTC 的快照。** 真執行時 body 必須從**寫入當下**的 `videos.list` 讀回再組,
   不能拿快照送:快照之後有人改過 status,拿快照送會把他的改動蓋掉。
   dry-run 證明的是「這個組法只換一個欄位」,**不是**「執行那一刻的 status 長這樣」。
2. 🔴 **殘留洞 `containsSyntheticMedia`**:它是可寫欄位,但 `videos.list` 不回傳。
   22 支實測,回傳的 status 欄位只有這 7 個:
   `embeddable, license, madeForKids, privacyStatus, publicStatsViewable, selfDeclaredMadeForKids, uploadStatus`。
   ⇒ 任何「讀回再整包送」的寫法都帶不到它,送出 `part=status` 後它會變成什麼,**本檔沒驗,也無法用唯讀方式驗**。
   全 repo 的上傳腳本 grep 不到任何一支設過它(上傳端只設 `privacyStatus / selfDeclaredMadeForKids / embeddable`),
   ⇒ 目前**應該**是預設值。但這是「沒找到設它的程式」,不是「它是預設值」。
   這個洞對 repo 裡每一支寫 status 的腳本都成立,不是這批獨有。
   `publishAt` 不在回傳裡,因為 13 支都沒有排程,不是被漏掉。
3. body 會帶回兩個唯讀欄位 `madeForKids / uploadStatus`。repo 裡四支寫入腳本都是這個寫法(見 §三),
   但它們在正式機上實際有沒有成功跑過,**本檔沒查**。

## 一、交付物

| 檔 | 內容 |
|---|---|
| `candidates.json` | 13 支清單:slug、videoId、prep 時的 privacyStatus 與觀看數、掃描時觀看數、片長、判定依據一行、`proposed_privacyStatus`。另附三組對照(public 3、unlisted 3、儀器 2 陽性 3)。`status: PROPOSAL_ONLY_NOT_EXECUTED` |
| `snapshot.json` | 22 支完整 `snippet,status,statistics,contentDetails`,外加儀器 2 的 T0 結果 |
| `snapshot.md5` | 三份副本的 md5,**全部 `01252d371d2572e7cc243d87e8d1c3b2`**:① 本資料夾 ② `youtube_channel/STUDIO/desc_backup/private_prep_2026-09-11/`(gitignored)③ **repo 外** `D:\carson-agent-backups\private_prep_2026-09-11\` |
| `dryrun.py` → `dryrun_output.txt` | 離線、零 API。13 支完整 body + diff + 自我檢查,結尾 `DRYRUN_RESULT: PASS` |
| `prep.py` → `prep_output.txt` | 產生清單與快照(唯讀,24 units) |
| `preflight_inst2.py` → `preflight_inst2_output.txt`、`instrument2_preflight.json` | 第二儀器 T0 預檢(唯讀,23 units) |

🔴 **13 支不要放進 `STUDIO/_private_batch_ids.json`。** 那個檔同時被兩支腳本讀:
`zombie_sweep.py`(:399-417,會直接照檔寫 private)和 `set_private_by_ids.py`(有洞,見 §三)。
放進去等於在沒人拍板的情況下接上自動執行。那個檔目前是 3 支已經 private 的舊片,本次只讀,拿來當儀器 2 的陽性對照。

## 二、13 支清單(全部 public,合計 **5,516 觀看**,prep 時讀回,與 627a3f4e 掃描時逐支相同)

| # | videoId | slug | 現況 | 觀看(掃描→prep) | 判定依據 |
|---|---|---|---|---|---|
| 1 | `MuXiM5IqVQQ` | S_台積電暴跌35元你恐慌殺出會少賺多少0050回測嚇壞 | public | 702 → 702 | 尺A 零主體(有效主體 0 ≤ 28)+ 尺B 自我循環(回聲餘 0 ≤ 2) |
| 2 | `TDbm4XR5pYk` | S_CPI破254你該追高我用回測資料打臉這句通膨追高網 | public | 183 → 183 | 尺A(0)+ 尺B(0) |
| 3 | `cObU5NcFT-I` | S_CPI連破3個月你的投資組合正在被通膨怪獸悄悄吃掉多 | public | 91 → 91 | 尺A(0)+ 尺B(0) |
| 4 | `I8F83sPFKWg` | S_非農資料利空臺股恐慌殺出0050定投竟多賺23倍 | public | 741 → 741 | 尺A(0)+ 尺B(0) |
| 5 | `_Cc49y7ZAeM` | S_Fed恐慌殺你的資產會少幾成這招資金配置避開大虧 | public | 220 → 220 | 尺A(5) |
| 6 | `tN56crKxwJE` | S_台積電飆破800元你的網格機器人是賺翻還是慘賠 | public | 718 → 718 | 尺A(13)+ 尺B(0) —— 退化旁白那支 |
| 7 | `mvDrUnxEjWs` | S_市場狂熱你的網格機器人是賺翻還是清零 | public | 204 → 204 | 尺A(0)+ 尺B(0) |
| 8 | `vwEaoo3Txjw` | S_CPI爆表0050定投vs恐慌殺出十年報酬竟差一倍 | public | 290 → 290 | 尺A(0)+ 尺B(0) |
| 9 | `UTuMMyvdQ5U` | S_0050定期定額臺股回檔竟比一次全押少賺一半 | public | 898 → 898 | 尺A(0)+ 尺B(0) |
| 10 | `DhX2uNzjZ-o` | S_臺股暴漲5000點你的0050網格反而少賺一臺賓士 | public | 866 → 866 | 尺A(0)+ 尺B(0) |
| 11 | `OyprNxjrIBQ` | S_市場巨變你的自動交易設定會讓你多賠一輛車 | public | 89 → 89 | 尺A(28,剛好壓線)+ 尺B(2,剛好壓線) |
| 12 | `nHwP_cyy_hc` | S_CPI資料一公佈你的網格機器人會不會被套到歸零 | public | 328 → 328 | 尺A(0)+ 尺B(0) |
| 13 | `xjQPW3sTY28` | S_升息499你的投資組合會被這盲點多咬掉多少 | public | 186 → 186 | 尺A(19) |

3 支 unlisted(`nrIYmQgjHFs` / `h4vTXYtlQ7I` / `rgeDJ3vxlxI`)**不在這批,維持不動**,在本檔只當對照組。

## 三、`zombie_sweep.py` 有沒有那個洞 —— **沒有**(對 API 會回傳的欄位而言);**`set_private_by_ids.py` 有**

派工只要求看 zombie_sweep,我把 `scripts/` 裡**所有** `videos().update(part="status")` 都列出來,因為它們會碰到同一個清單檔:

| 位置 | 寫法 | 判定 |
|---|---|---|
| `zombie_sweep.py:362→370→382-383` | 寫入前 `videos.list` 讀回,`dict(status)` 整包帶回,只換 privacyStatus | ✅ 無缺欄位 |
| `zombie_sweep.py:403→413-415`(`_private_batch_ids` 分支) | `fetch_meta_batch`(:254-275)在同一輪先讀,整包帶回 | ✅ 無缺欄位;⚠️ 讀跟寫之間隔一整個迴圈,不是寫入當下讀的 |
| 🔴 **`set_private_by_ids.py:79`** | `body={"id": vid, "status": {"privacyStatus": privacy}}`,**只送一個欄位** | 🔴 **有洞**:`embeddable / license / publicStatsViewable / selfDeclaredMadeForKids` 都沒帶。而且它的 `_info()`(:38-46)只保留 privacyStatus、觀看數、標題,**結構上就拿不到整包 status**。docstring 寫「預設 dry-run,全程讀回驗證」,但它讀回驗的只有 privacyStatus 一欄,看不到被重設的其他欄位 |
| `privatize_fabricated.py:99-107` | 寫入前讀回整包 | ✅ |
| `privatize_fabricated.py:58-66`(`--restore`) | 送的是設 private 那時存下的舊 status 檔 | 缺欄位的洞它沒有,但有另一型:**拿舊快照整包送回去**,會蓋掉這段期間任何人對 status 的改動 |
| `set_private_leaks.py:194-198` | `dict(info["status"])`,再 `setdefault` | ✅ 形狀正確(`info` 的來源我沒追到底) |
| `set_public.py:74-78` | `items[0]["status"]` 整包 | ✅ |

**以上都只點名,一支都沒改。** dry-run 的自我檢查 N1 就是拿 `set_private_by_ids.py:79` 的寫法去組 body:
6 個欄位全部被判成「缺」(見 §五),等於把這個洞實際跑出來看過一次。

## 四、寫入前快照

- **送出 24 個 id,回來 23 個**:`kk893Wva6c4` 沒回來。`videos.list` 對讀不到的 id 是**靜默省略**,不報錯。
  它原本排第一個陰性對照候選,改用下一支。13 支全數都有回來。
- 快照範圍 22 支 = 13 支 + public 陰性對照 3(`fYTywq3Ah1c`、`s4jROPETmlE`、`Xmc_qtMqPhk`)
  + unlisted 3 + 儀器 2 陽性對照 3(`oq4I_jtEw3Q`、`ODN9YzdBopA`、`7C79mFmnFrE`,都是 private)。
- **public 陰性對照的挑法**:627a3f4e 判得動、尺A 尺B 都沒命中、沒被截斷的 public Shorts,
  而且 id 不出現在任何 `docs/ops/2026-09-1*.md`、`_private_batch_ids.json`、`STUDIO/*private*|*zombie*` 裡
  (=其他線不太可能去動它)。
- **換過一次對照組**:第一次跑(04:32 UTC)用的是 72 次報告 A4 標出的三支假長片
  `ydjxUdBRaIk / JUUw7eqJR-o / crGXzOcOYOw`。它們是被別條線標成缺陷的片,可能被別條線處理掉,
  到時對照組變了,就分不出是誰動的,所以換掉。那份快照已被本次覆寫,舊的 candidates json 已刪除。

## 五、dry-run 結果(`dryrun_output.txt`)

每支都印出完整 body、status diff、不變欄位。第 1 支原樣:

```
[01] MuXiM5IqVQQ  台積電暴跌35元，你恐慌殺出會少賺多少？0050回測嚇壞你 #Shorts
  送出 body = videos().update(part="status", body={"id": "MuXiM5IqVQQ", "status": {"embeddable": true, "license": "youtube", "madeForKids": false, "privacyStatus": "private", "publicStatsViewable": true, "selfDeclaredMadeForKids": false, "uploadStatus": "processed"}})
  diff  privacyStatus            'public' → 'private'
  不變  embeddable=True, license='youtube', madeForKids=False, publicStatsViewable=True, selfDeclaredMadeForKids=False, uploadStatus='processed'
  判定  ✅ 只差 privacyStatus
```

- **13/13 只差 privacyStatus(public→private)。** 13 支改前的 status 除 privacyStatus 外完全相同:
  `embeddable=True, license=youtube, madeForKids=False, publicStatsViewable=True, selfDeclaredMadeForKids=False, uploadStatus=processed`。
- **自我檢查**(證明檢查器會失敗):
  - N1 照 `set_private_by_ids.py:79` 的寫法只送 privacyStatus → **被抓出**,6 個欄位全部判「缺」
  - N2 突變:把 embeddable 翻面 → **被抓出** `{'embeddable': (True, False)}`
- 三支腳本裡唯一出現 `update(` 的是 `dryrun.py:69`,那是一個 print 字串,不是呼叫。

## 六、回讀計畫

依 memory `yt-readback-stale-cache`(30 秒後回讀 9/9,50 分鐘後有兩支變回 public):
**同一個儀器重複問不算驗證**;要換一個獨立儀器,還要帶陰性對照。

### 儀器預檢(T0,已跑)

| 儀器 | 結果 | 能不能用 |
|---|---|---|
| ① `videos.list part=status`(寫入用的同一個) | 22 支都回來,欄位 7 個 | 可用,但它是寫入端,單獨用不算驗證 |
| ② 候選 A:`playlistItems.list` 加 `videoId=` 過濾 | ❌ **22 支只回 1 支**(`rgeDJ3vxlxI`),另外 21 支是 0 筆、無錯誤 | **不能用**:它**靜默回 0**。先預檢才抓到;要是回讀當天才用,「0 筆」會被讀成什麼都有可能 |
| ② 候選 B:uploads 播放清單 `UUqP5JQXlQR5ZDLtEiBt4kLA` 整份翻頁 `part=status` | ✅ 23 頁 / 23 units;**22/22 與儀器 ① 一致**;非 public 的陽性對照 **6/6 讀得出**(3 private + 3 unlisted),所以它不是恆回 public 的壞尺 | **可用**。⚠️ **1,132 列只有 1,100 個唯一 id**:分頁 bug 還在(memory `yt-playlistitems-pagination-bug`),這次 22 支剛好都翻到,下次未必 ⇒ **沒翻到的一律算「未讀到」,不算通過** |

⚠️ ① 和 ② 是同一個 Data API、同一組 OAuth 的兩個不同端點。如果 Google 的快取在更下層共用,兩個可能一起舊,
所以 T2 要等 ≥24 小時,不能拿 T1 兩個儀器一致就收工。

### 時程與通過條件

| 時點 | 儀器 | 對象 | 通過條件 |
|---|---|---|---|
| **T0 寫入前,每支** | ① | 13 支 | 當場讀回整包,只換 privacyStatus 就送(§五的組法);讀回不是 public 就跳過並記錄,**不送** |
| T0 寫完即時 | ① | 13 支 | **只記錄,不算驗證** |
| **T1 ≥ 60 分鐘** | ① + ② | 13 支 + 6 對照 | 13 支在兩個儀器上都是 private,且其他 6 欄與 T0 讀回的逐欄相同;3 支 public 對照仍 public,且逐欄同快照;3 支 unlisted 仍 unlisted |
| **T2 ≥ 24 小時** | ① + ② | 同上 | 同上 |

- 任一支回到 public、任一欄位變了、或 ② 沒翻到 → **停,不重送,回報督導**,不自己補寫。
- 執行後 **T1、T2 各再 commit 一次回讀結果**(memory:對外動作的證據要在執行**之後**)。
- 配額估計:寫入 13 × 50 = 650;T0 讀 13;T1、T2 各 1 + 23 = 24 ⇒ 約 **711 units**。
- 3 支 unlisted 在整個流程中只被讀,不被寫。

## 七、同一輪的另一件:(一)更正已落地

`docs/ops/2026-09-11_72次fail-open_是否真的放出缺陷.md`:**+45 / −0**,原文一個字沒動。
- **1 處更正**:§「手開原檔才看到」第 2 點(`L_財報選股…` 旁白 0 字)。證據在 `627a3f4e` §零「更正 ①」,
  該檔在 `output/_redo/`,3,069 字 / 71 句。錯的原因是定位器只掃了 `output/` 根目錄。
  所以第 106、204 行,以及附錄同一筆(原第 327 行,插入後第 372 行)的依據一併不成立;反向也寫明:**推翻「它是空檔」不等於推翻「它是缺陷」**,那支的 A1c 判定從來沒做過,結論回到不可知。
- **同因可疑,只標不重算**:3 個位置(共 4 筆):
  - S_EP8:依據已推翻,檔在 `_husk_bak`,447 bytes
  - 附錄兩筆無 slug 的 A1c:不可查
  - 第 25 行的 2 筆 GONE:未定

  第 28 行的承重結論「存活者偏差 2/72」也站在這把尺上,一併標註。
- ⚠️ 追記裡引用的原檔行號,commit 前逐行對過 `git show HEAD:` 原文。初稿有三處寫錯:第 27→25 行、第 29→28 行,附錄第 327 行插入後移到第 372 行。已在追記內改正;原文仍一字未動。
