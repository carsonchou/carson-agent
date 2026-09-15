# `_clean_cut()` 第二輪修正——殘留缺陷登記(2026-09-15)

範圍:`youtube_channel/scripts/make_thumbnails.py:_clean_cut()`,第二輪修正(門檻≤1
字+座標系統一)已通過 §6 fresh-context 對抗式驗證(opus)PASS。本檔僅登記驗證agent
發現、不擋上線但需備查的殘留項目,細節見驗證agent原始報告(未另存檔,見本次herdr
往返紀錄)。全程唯讀分析,未修改任何邏輯,是登記不是修復。

## 5 項殘留缺陷

1. **交叉括號可能使 `cut_point` 作廢已配對括號** — fuzz 才測得到,真實語料 0 次觸發。
2. **連鎖刪到空字串未根治,只是降頻** — 根因是 `cut_point = _oi` 規則本身可遞迴(巢狀
   未配對開括號時逐層退切點)。fuzz 測得非早退案例清空次數由第一輪 662 次降到第二輪
   217 次,是降低不是消除。真實語料(827 支標題+2,700 段落)0 次觸發。徹底根治需在
   `cut_point` 縮到低於一個下限(如 `max(2, limit*0.3)`)時改走只刪括號字元,留給後續。
3. **早退路徑完全繞過括號修正** — `len(s) <= limit` 時直接回傳,不進入括號清除迴圈。
   既有行為,非本輪造成,本輪未觸及。真實呼叫點 3,571 筆中 18 筆(0.5%)落在此路徑。
4. **下游數字守門索引在 `excluded` 非空時可能錯位** — `chapters.py` 等下游用 `len(head)`
   索引,`excluded` 集合非空時該索引與原始字串 `s` 不再一一對應。08-30 既有問題,本輪
   未觸及,未測到真實影響案例。
5. **副頻道分岔實作(新發現)** — `yt_ch2/scripts/make_thumbnails.py:1007` 有一份獨立
   的 `_clean_cut()`,完全沒有括號清除邏輯,停在 07-30 版本。跟主頻道是分岔實作,不在
   本次任務範圍。是否修正待另一個唯讀命中率調查(比照主頻道 827 支標題的方法,抽一批
   ch2 縮圖標題測這個 bug 有沒有實際命中)結果決定。

## Asymmetric safety net(附帶觀察,非缺陷)

`chapters.py:127`(`if _cut and len(_cut) >= 8`)在章節標題表面對 `_clean_cut` 輸出過短
時有靜默 fallback,縮圖表面沒有對應安全網,空結果會落到通用「看完秒懂」文案。非本輪
範圍,未修。

## 聲明

本檔為 scratchpad 性質診斷記錄,對應 commit 已將 `_clean_cut()` 本身的程式碼修正落地
(git 精準 hunk staging,未帶同檔案其他無關 WIP)。未觸碰
`apply_first_batch_guard.py`/`set_private_13.py`/`load_verification()`。
