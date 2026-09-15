# 診斷筆記:字幕早3秒 + 章節偏64秒(09-15 重查)

範圍:唯讀,D:\carson-agent\youtube_channel\ 內,20 支主頻道長片抽樣。未碰
apply_first_batch_guard.py / set_private_13.py / load_verification() / 任何隱私狀態寫入程式碼。

## ①字幕(CC)偏移 — 現況:0.00 秒(缺陷已修,產線路徑已確認)
- 20 支中 9 支本機有 .srt(其餘 11 支是 caption_ab.py A/B 實驗的 B 組,本來就不傳字幕,
  不是資料缺失)。
- 量法:讀 `{slug}.wordtimes.json` 第一個非零長度字詞的 t,加上 `INTRO_DURATION`(3.0s)
  當作「應該的」起始秒數;讀 `{slug}.srt` 第一個 `-->` 時間戳當作「實際的」。
- 結果:9/9 offset = 0.00s(全部精確吻合,無需抽換手動覆核 —— 数值本身合理,非極端值)。
- 根因(舊):`make_video.write_srt_for_slug` 曾用 mp4 總長度均分字幕且沒加片頭位移。
  **現況**:scripts/make_video.py:430-519,現在優先吃 `{slug}.wordtimes.json` 真實時戳
  + `INTRO_DURATION` 位移(L482-492);只有沒有 wordtimes 時才退回估算(且改用旁白 mp3
  長度而非 mp4 總長,L495-508)。
- **產線路徑確認**:`daily_publish.py:1015` 在發布時呼叫 `_mv.write_srt_for_slug(slug)`
  (受 `is_short` 與 `caption_ab.should_upload` 兩個開關控制,非死碼)。這是真正在跑的
  那條路徑,不是只有 repo 裡放著沒人呼叫的修復腳本。
- `fix_captions_sync.py`(08-17)、`fix_caption_drift.py`(08-24)是**一次性回填工具**,
  用來把 08-17 修復之前已上傳的舊字幕軌換掉,不是常駐產線的一部分——是否還有殘留
  未回填的舊片未在本次範圍內查(範圍限定抽樣的 20 支近期長片,這些都是修復後產出)。

## ②章節時間戳偏移 — 現況:對得上(≤1秒),失敗時 fail-open 不輸出(不是輸出錯的)
- 20 支中 15/20 `chapters.build()` 成功產出章節(3 支本機無 srt 是因 A/B 實驗跳過字幕,
  與章節無關;5/20 fail-open 沒有章節,是「對不齊時寧可不出」的設計行為,不是輸出錯誤
  時間戳)。
- 獨立覆核(不重用 chapters.py 自己的 align_segment_starts,改用最原始的「段落前 N 字
  在 wordtimes 裡樸素搜尋」交叉驗證,避免自我驗證的問題):抽 3 支,各驗 2 個章節點。
  6 個點全部與 chapters.build() 的輸出對上(誤差 <1 秒),例:
  - 中探針6217 第2章 "1:56"(116s) vs 獨立搜尋 113.086+3.0=116.09s
  - 中探針6217 第3章 "3:39"(219s) vs 獨立搜尋 215.932+3.0=218.93s
  - 金居8358(24倍版) 第2章 "1:57" vs 113.923+3.0=116.92s
  - 金居8358(24倍版) 第3章 "4:10" vs 247.185+3.0=250.19s
  - TPK-KY3673 第2章 "1:56" vs 113.242+3.0=116.24s
- 根因(舊):`chapters.py`/舊版 `build_chapters_block` 漏加 INTRO_DURATION(全體早3秒)
  +對不到句子時用等分估算編時間點(觀眾點章節跳錯,最大偏 -64 秒,90 支已補片裡 63 支錯)。
- **現況**:scripts/chapters.py 全檔(align_segment_starts L45-94、build L138-177)已改為
  單調遞增搜尋真實 wordtimes + INTRO_DURATION 位移(L160-161),且對不齊/不滿足 YouTube
  硬規(第一章 0:00、≥3 章、每章 ≥10 秒)時**整組回空字串**,不輸出編造的時間點
  (fail-open,見 chapters.py L23-26、168-173)。
- **產線路徑確認**:`upload_youtube.py:335` `build_chapters_block()` 內部呼叫
  `from chapters import build`(L356-357),而 `build_chapters_block` 本身在
  `assemble_metadata()`(產線發布時組描述的函式)裡於 `upload_youtube.py:505` 被呼叫。
  確認是真正產線路徑,不是孤兒腳本。
- `desc_chapters_backfill.py --fix-existing` 是**一次性回填工具**,用來把 08-12 那批
  90 支(63 支錯)的線上舊章節換成新算法產出的版本;是否所有 63 支都已回填完畢未在本次
  範圍內逐一核對(本次抽樣的 20 支是近期產出,走的都已經是修復後的產線)。

## 總結
兩個舊缺陷在**目前的產線程式碼與近期實際產出**中都已確認修復且驗證通過:
- 字幕:9/9 抽樣 offset = 0.00s
- 章節:6/6 獨立覆核點 <1s 誤差;fail-open 保證失敗時不輸出錯的而非「輸出稍微不準的」
兩者的修復邏輯都確認位於**真正被產線呼叫**的函式內(daily_publish.py / upload_youtube.py
的呼叫鏈),不是只存在於 repo 裡沒人走到的腳本。

## 範圍外/未查
- 08-17(字幕)、08-12(章節)之前發布的舊片,是否全部已被 fix_caption_drift.py /
  desc_chapters_backfill.py --fix-existing 回填完畢——未查,不在本次「近期 20 支」抽樣
  範圍內,如需要應另開任務對 done 名單(`STUDIO/caption_drift_fixed.json`、
  `STUDIO/desc_chapters_fixed.json`)與應回填母體做對帳。
