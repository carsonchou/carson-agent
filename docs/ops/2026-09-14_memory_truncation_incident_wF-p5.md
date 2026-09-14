# 2026-09-14 memory/detector-failure-shapes-2026-09.md 截斷事故 —— 誠實界線(caveat 四件套)

- 記錄人:wF:p5(main ch. 督導)。位置由總督導 wF:p1 09-14 14:20 裁決 §三 指定。
- 本檔是給查的人看的。memory 檔本體不背這一段;快照 A manifest 那一列上方的貼身註記只當指路標,指向本檔(改註記是建置員的任務)。
- 所有數字都附量測時間,都是當時的歷史值,不是現況。

## 事故(已對 w9 transcript efac2502 核過)
- 09-14 10:09:06:w9 用一行 python -c 改 memory/detector-failure-shapes-2026-09.md,寫法是 open(p,'w') 直接覆寫。字串裡有 surrogate 逃逸,丟出 UnicodeEncodeError,這時檔案已經被截成 0 bytes(transcript 7516 / 7518 / 7524 行)。
- memory/ 沒有版控,也沒有備份。
- 10:09–10:13:w9 在救(從 jsonl 找原文)。
- 10:13:41:撞 session limit(7608 行)。10:22:21 背景指令完成的通知把它叫醒,10:22:22 又撞一次(7619 行)。之後停擺到 13:38:50,約 205 分鐘。
- 13:49:40:w9 從 transcript 考古復原。13:51 回報。
- 空窗期間有沒有人讀到空檔:我掃了本專案 10:00 之後有寫入的 jsonl,找 10:09–13:52 之間輸入含這個檔名的 tool_use。除了 w9,沒有任何線 Read 或 cat 這個檔。
  界線:只查得到 tool_use 輸入;另一台 Mac 和其他專案目錄不在範圍內 ⇒ 結論是「查得到的範圍內沒人讀到」,不是「沒人讀到」。

## 參考本
- 建置員 09-14 13:54 完成 memory/ pristine 快照 A:D:\claude\projects\D--carson-agent\_pristine_20260914\memory\。
- 引用寫法(總督導 14:20):**203 檔 / 1,194,197 bytes / 13:54,錨點待補**。
  MANIFEST_sha256.txt 是會被追加的帳本,它的 sha256 不是錨點。錨點等建置員交回 MANIFEST_snapshotA_FROZEN.txt 的 sha256 後再補。

## caveat 四件套(對象:memory/detector-failure-shapes-2026-09.md)

### 已縮小的部分(wF:p5 09-14 14:09:34 自量)
- 現檔 sha256 b8d59611432b1fa8353befbab06b69064955317f0ff6ff128531abd8ecc3a9c4,19438 bytes,mtime 13:49:40。
- 快照 A 裡那一份:sha256 相同、19438 bytes、mtime 13:49:40。manifest 那一列(14:09:34 時為第 45 行)的 sha256 也相同。
- ⇒ 13:54 到 14:09:34 之間,這個檔沒有被改過。13:54 之後的任何缺漏,現在都查得出來。
- 指令(可重跑):
  sha256sum memory/detector-failure-shapes-2026-09.md _pristine_20260914/memory/detector-failure-shapes-2026-09.md
  stat -c '%s %y' 同上兩檔
  (工作目錄 D:\claude\projects\D--carson-agent,Git Bash)

### 1. 未量什麼
13:49 復原版(19438 bytes / sha1 2e12a676e9b323fd29cd8b8502228aa748c0075c)是否等於 09-14 10:09:06 被截斷前的原件。從來沒比過。**13:54 以前的缺漏仍然查不出來。**

### 2. 量法
1. 在所有 session 的 transcript 裡,找 10:09:06 之前**最後一次完整**讀這個檔的 Read 或 cat 輸出。要全部行,不帶 offset/limit,沒有被截斷。
2. 從那份輸出重建全文。
3. 確認那次讀之後、10:09:06 之前沒有別的成功寫入;有的話,依序把那些寫入套上去。
4. 和復原版逐行比:每一行、順序都要相同。

### 3. 撤銷門檻
- 由 **wF:p5 自己**重跑上面的量法。「別人說對過了」不算。
- 重建版和復原版每一行、順序都相同。
- 結果落進磁碟紀錄(本檔追加一節 + 一封回報),不能只在對話裡講。

### 4. 撤掉後還剩什麼不敢宣稱
- 撤得掉「本檔內容可能有缺漏」,**撤不掉**「09-14 那段期間讀過本檔的人可能讀到 0 bytes 或殘缺版」。那已經發生過,不可撤。(總督導 14:10 原句)
- Read 的輸出不保留行尾(CRLF/LF)和檔尾換行 ⇒ 就算比對通過,也只能撤到「**文字行層級相同**」,撤不到「逐位元組相同」。用一把看不見行尾的儀器去證明「兩份一樣」,證出來的東西比以為的弱一級(同 memory git-hash-object-hides-crlf)。
- w9 10:09 原本想加的內容有沒有被併進復原版,是另一個問題,本 caveat 不涵蓋。
