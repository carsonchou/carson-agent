# 紀錄:「crontab 本體不在 repo 裡」這條 caveat —— 已撤,附證據

落檔人:sec ch. 督導 `wF:p8`(session 818543e1)。量測時間:台北 **2026-09-14 13:51–13:55**(`date` 取得)。
起因:總督導 wF:p1 指派 (a)~(d);wF:p5 13:43 已獨立查出方向,但**撤 caveat 的條件是「我量過了」,不是「別人說它在」**,所以下面每一項都是我自己跑的。

## (a) 路徑常數怎麼算出來的(引原文)
`youtube_channel/scripts/local_cron.py`
```
49: ROOT = Path(__file__).resolve().parent.parent
59: CRONTAB = ROOT / "deploy" / "crontab.txt"
```
`__file__` = `youtube_channel/scripts/local_cron.py` ⇒ `parent.parent` = `youtube_channel` ⇒
`CRONTAB` = `youtube_channel/deploy/crontab.txt`。
重讀頻率(`:484` 原文):`jobs = parse_jobs()  # 每分鐘重讀 crontab.txt(排程改動免重啟即生效)`。
`:7` 原文:把 `/root/yt/run.sh scripts/X.py args` **翻譯成本機 `.venv python scripts/X.py args`**;
`:63` 把 `>> /root/yt/logs/cron.log 2>&1` 切掉忽略(droplet 時代的路徑)。
⇒ **crontab.txt 裡那些 `/root/yt/...` 的行,在本機是真的會跑的。**

## (b) 絕對路徑與現況
`D:\carson-agent\youtube_channel\deploy\crontab.txt`
**85,682 bytes**,mtime **2026-09-09 23:27:37 +0800**,873 行。

## (c) 在不在 repo 根遞迴 grep 的覆蓋範圍內
在。`D:\carson-agent\` 之下 ⇒ 早上那支 `grep -rn` 已經掃過它。

## (d) 結論
🔴 **caveat 撤銷:「repo 內以檔名呼叫 `fix_binge_split_disclaimer` 的路徑零命中」現在包含排程那一塊。**
補做的單獨掃描(三條件齊全):
- 範圍:`youtube_channel/deploy/crontab.txt`(路徑存在,已 ls)
- 指令原文:`grep -n "fix_binge_split_disclaimer\|period_disclaimer" youtube_channel/deploy/crontab.txt`
- 退出碼:**0**(有命中,但命中的不是它)
- 逾時:無
- 結果:`fix_binge_split_disclaimer` **零命中**;命中的四行全是**另一支** `fix_period_disclaimer`
  (`:27`、`:47`、`:280` 是註解,`:644` 是活的排程行)。

仍然成立的殘留(不追,已知):動態呼叫(importlib / 變數組檔名 / `.bat`·`.ps1` 包一層)特徵字串掃不到。
總督導 09-14 裁決:**不必為它再開一輪掃描** —— 今晚的防線不靠「證明沒有人會呼叫它」,
而靠「檔案凍結 + 還原後比磁碟位元組」,動態呼叫就算存在也會在 sha256 上現形。

---

# 🔴 同一輪掃到的另一件事:排程每天 15:05 會覆寫今晚要凍結的那個檔

這不是我被指派的題目,是掃 crontab 時掉出來的,而且**打到今晚凍結的承重點**,所以寫在這裡。

## 證據(全部是我自己量的,13:5x)
1. `youtube_channel/deploy/crontab.txt:644` 原文:
   `5 15 * * * YT_QUOTA_RESERVE=23650 /root/yt/run.sh scripts/fix_period_disclaimer.py --apply --max 15 >> /root/yt/logs/cron.log 2>&1`
   ⇒ 每天 **15:05**,經 local_cron 翻譯後在本機跑 `scripts/fix_period_disclaimer.py --apply --max 15`。
2. `youtube_channel/scripts/fix_period_disclaimer.py:49`:`DONE = ROOT / "STUDIO" / "period_disclaimer_done.json"`
   —— **就是今晚要凍結的那個檔**,這支是它的擁有者。
3. 寫入路徑(`:1049-1062`)在 `if args.apply:` 之下,**無條件**執行:
   `payload = json.dumps(sorted(done))` → 寫 tmp → 回讀比對 → `os.replace(tmp, DONE)`。
   **不是「有變才寫」** ⇒ 每天 15:05 一定 replace 一次;`done` 一旦多一支(`:980` 起的 `cands` 迴圈會 `done.add`),
   內容就變,**sha256 與 size 一起變**。
4. `period_disclaimer_done.json` 現況 mtime = **2026-09-13 15:05:48** —— 和 15:05 那格逐分對上,
   而今天的 15:05 **還沒到**(量測時 13:5x)。

## 這對今晚凍結的意義
wF:p3 給的還原基準是 **sha256 `ae76d5af…` / 1275 bytes**(我 10:02 獨立量過,當時相符)。
**今天 15:05 之後這個基準可能就不成立了** —— 還原成 `ae76d5af…` 會把檔案還原成**昨天**的母體,
而不是「凍結前那一刻」的母體。

這正是 memory `criteria-anchored-to-mutable-property` 09-14 那條記過的形狀:
**釘 sha1 的閘門,對手是排程不是人;日排程重算母體 84→85,兩個 sha1 全變。**
⇒ 我不是發現新病,是量到**它今天會再發作一次,而且就在凍結之前 70 分鐘**。

## 我沒有做、也不打算做的事
不動 crontab(775~777 及任何一行)、不動 `period_disclaimer_done.json`、不跑那兩支腳本、
不判斷「還原會不會讓片子回到觸發條件成立的狀態」(總督導 13:55 明說 r3 優先,那題等 r3 收工後正式派工)。
**已把上面的量測原樣送給 wF:p3(凍結的執行/覆核者)與總督導 wF:p1,由他們決定基準要不要重取。**

---

## 撤銷紀錄(總督導要求:不要只在對話裡講)

**已撤:免責第 2 條「crontab 本體不在 repo 裡,所以 775~777 未量到」。**
**證據 X** = 本檔 (a)(b)(c)(d) 四段,全部由 `wF:p8` 於 2026-09-14 13:51–13:56 自行量測:
`local_cron.py:49/:59` 解析出的絕對路徑落在 repo 內 ⇒ 早上那支 repo 根遞迴 grep 已覆蓋它;
補做的單檔掃描退出碼 0、無逾時、路徑存在,`fix_binge_split_disclaimer` 零命中;
775~777 經實讀為配額註解,不是排程行。

### 附帶(新全線規則,總督導 2026-09-14 13:55):caveat 要附「怎麼樣才能把它撤掉」
只寫「這塊未量」= 把問題丟給下一個人;寫「未量,量法是 X,量到 Y 就可以撤」= 把問題**交給**下一個人。
本檔仍然成立的那條殘留(動態呼叫)照這條規則補上撤銷條件:

> **殘留**:以 importlib / 變數組出檔名 / `.bat`·`.ps1` 包一層的方式呼叫 `fix_binge_split_disclaimer.py`,特徵字串掃不到。
> **撤銷條件**:凍結時窗全程結束後,比對 `period_disclaimer_done.json` 的磁碟位元組 sha256 **+ size** 兩項,
> 與凍結前那一刻(不是早上)重取的基準一致 ⇒ 該時窗內沒有任何路徑寫過它,殘留對本次凍結不成立。
> **注意**:這只撤得掉「本次凍結期間」,撤不掉「這支程式永遠不會被動態呼叫」—— 後者本檔不宣稱。
