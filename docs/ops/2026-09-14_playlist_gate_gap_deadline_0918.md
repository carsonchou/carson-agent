# 播放清單閘門缺口 —— 死線 2026-09-18 09:45(主頻道線 w9:p1 執行 / wF:p5 督導)

> 來源:總督導 wF:p1 2026-09-14 09:5x 裁決(Task B 驗證員報告的第二個問題)。
> 本檔存在的理由:跨 session 的死線不准只活在排程裡(排程是提醒,不是紀錄)。督導 session 的排程是 session-only,session 死了就零訊號 —— 觸發時的人**讀本檔**,不要靠排程 prompt 裡的摘要。

## 🔴 第一個會咬人的時刻
**2026-09-18(週五)09:45 `organize_dept.py`**。
09-17(週四)那 5 支設 private 之後,下一次把片插進公開清單的排程就是它。
09-15(週二)13:40 那次 `playlist_engine.py --sync` 跑在設 private 之前,插的仍是 public 片,不構成缺陷。

## 缺口
閘門(insert 前查影片 privacyStatus)目前只裝在 `build_playlists.py`(fc665c34)。另外三支會把片插進清單的排程都沒有:

| deploy/crontab.txt 裡 grep | 時間 | 狀態 |
|---|---|---|
| `build_playlists.py --max 10` | 週四 22:00 | 已有閘門 |
| `organize_dept.py` | 週五 09:45 | 無閘門 |
| `playlist_engine.py --sync` | 週二 13:40 | 無閘門 |
| `industry_playlists.py --apply` | 週五 16:50 | 無閘門 |

(用 grep 錨點,不寫行號 —— 排程檔會增刪行。)
三支的 `videos().list` 呼叫數都是 0;檔案裡唯一的 `privacyStatus` 是建清單時把**清單自己**設成 public,不是檢查影片。

另外,那 5 支裡已有 4 支坐在 `STUDIO/playlist_engine.json` 的公開清單 **PLJp7y2jl2p64**(219 支)裡:
`I8F83sPFKWg` / `vwEaoo3Txjw` / `UTuMMyvdQ5U` / `DhX2uNzjZ-o`。
09-17 一變 private,它們當下就已經在公開清單裡 ⇒ **這部分「不加入」擋不掉,要靠移除**。

## 任務(不擠 09-14 當晚;排在任務 A 與 84 支寫入之後)
- **(a)** 把閘門**抽成共用函式**,補到上面三支。**不准複製三份**(memory `yt-duplicate-impl-gate-bypass` 的形狀;09-14 已在 yt_ch2 那份重複實作碰過一次)。
- **(b)** 一支對帳工具:掃現存公開清單裡的**非 public 項目並列出來**。
  🔴 **只做掃描與列出,不准自動移除。** 移除 = 動線上公開清單內容 ⇒ 紅線流程:**先出清單 → 獨立驗證 → 總督導放行 → 才准執行**。
- **(c)** 潛伏回歸:`candidates` 移到迴圈外算之後,丟失「同一 vid 在帳本出現兩次」的天然防護。現況不觸發(真帳本 1152 筆 / 1152 相異 id / 零重複),不擋上線。
  修的順序寫死:**先加「同一 vid 出現兩次」樣本、證明現在的碼會插兩次(測試翻紅)→ 再補 `if vid in existing: continue`、證明翻綠。** 反過來做 = 沒人證明過它抓得到東西的測試。

## 完成的定義
09-18 09:45 前 (a)(b)(c) **完成並經獨立驗證**。commit / blob 由督導自己 `git rev-parse` 取。
比對「檔案改回去了 / 兩份一樣」一律比**磁碟位元組(sha1sum + size)**,不准只用 `git hash-object`(core.autocrlf=true 時它看不見 LF↔CRLF 變化)。

## 未完成時
09-18 08:43 前若未完成 ⇒ 督導立刻報總督導 wF:p1,由總督導決定處置;督導與執行線**不自行改排程**。

## 追蹤
- 督導排程(session-only,僅提醒):09-17 10:13 查進度、09-18 08:43 死線前核。session 若中斷,以本檔為準。
