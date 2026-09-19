# claude 行程盤點 — 2026-09-09 15:5x(交接檔 §三.7,**只列不動手**)

## 🔴 結論先講:交接檔的「11 個孤兒」是錯的,真正對不到帳的是 **3 支**,而且**至少一支現在還在動**

「20 支 claude − 9 個 herdr 窗格 = 11」是**兩本帳相減**,而那兩本帳量的不是同一個東西
(同 memory `yt-quota-is-per-cloud-project` 的形狀)。逐支對過之後:

| 類別 | 支數 | 私有記憶體 | 說明 |
|---|---:|---:|---|
| 桌面版 App 那一叢 | **8** | 683 MB | pid `12980`(父 `sihost.exe`,09-09 03:19)+ 7 個子 claude.exe。**不是 session,不要算進孤兒** |
| herdr 管得到的窗格 | **9** | ~7.3 GB | 全部逐一對到 PID(見下),含我自己 `wF:p3` = pid **53220** |
| **對不到帳的** | **3** | **1,932 MB** | 見第三節 |
| 合計 | 20 | 10,270 MB | 全機 15.7 GB,**free 只剩 0.7 GB** |

## 一、機器狀態(15:45 量)

```
claude  n=20  private= 10,270 MB
node    n=24  private=  3,161 MB
python  n=6   private=    676 MB
Total 15.7 GB / Free 0.7 GB
```

⇒ 交接檔講的「今天兩次背景觀測任務被系統因記憶體不足砍掉」有物理解釋。
🔴 而「觀測工具被砍」和「事情還沒發生」畫面上一模一樣。

## 二、窗格 ↔ PID(`herdr pane process-info --pane <id>`,不是 `--current`)

⚠️ 裸的 `herdr pane process-info` 回**焦點窗格**;而 `herdr pane process-info w1:p1` 會回
`unknown option`,參數名是 `--pane`。

```
w1:p1 → 58860   w9:p1 → 39004   wB:p1 → 37296
wF:p1 → 54144   wF:p3 → 53220(本 session)   wF:p4 → 28916   wF:p5 → 31144
wG:p3 → 58380   wM:p1 → 472
```

⚠️ 這張表和 memory `herdr-pane-session-map` 那張不同:**這張是 PID 對照,不是 session id 對照**。
PID 不會因為 `/clear` 改變,所以它**不會**像 session id 那張表一樣每被 /clear 一次失效一格。

## 三、對不到帳的 3 支 —— 🔴「孤兒」是錯的詞

```
pid=29668  659 MB  起 09-08 13:50(26.0h)  CPU 1,663.2 秒  父 powershell.exe(48084,活著)
pid=54772  625 MB  起 09-08 20:21(19.5h)  CPU 1,323.3 秒  父 powershell.exe(45636,活著)
pid=32904  648 MB  起 09-09 00:32(15.3h)  CPU   601.9 秒  父 cmd.exe(4772,活著)
```

三支都累積了 10~28 分鐘的 CPU ⇒ **都真的做過事**,不是啟動後就閒置的空殼;父 shell 全部還活著
⇒ 是有人在終端機裡直接開的 session,只是沒掛進 herdr。

🔴 **而且至少一支現在還在工作**:同時間 `D:\claude\projects\D--carson-agent\` 下
不屬於那 9 個 herdr session 的逐字稿剛被寫過的有 **3 份** ——
`dd2a020c`(15:50,5.8 MB)、`3d6ce680`(15:32)、`7bdd9937`(15:25)。
`dd2a020c` 的 mtime 距離量測時刻只有 **2 分鐘**。

⚠️ 我一開始數成 4 份,多算的那份是 `2c8bafca`(14:44)—— **那是本 session 自己 /clear 前的逐字稿**
(pid 53220 的 cmdline 是 `--resume 5089f42d-…`,而 `/clear` 換過兩次 id:`5089f42d` → `2c8bafca`
→ 現在的 `618eca5e`,見 memory `herdr-pane-session-map`)。
⇒ **算「對不到帳的逐字稿」時,要先把自己 /clear 前的那些扣掉**,否則每 /clear 一次就多算一份。
扣掉之後:**3 支行程 ↔ 3 份逐字稿,對得起來。**

⇒ **「herdr 帳上沒有」不等於「沒人在用」。** herdr 只是一本帳,不是全機真相。
關掉它們可能毀掉正在跑的工作,以及只活在逐字稿裡的東西(memory `only-what-lands-on-disk-exists`)。

## 三之二、第三本帳:`ListAgents` 的 Peer sessions —— 比行程樹好用

`ListAgents` 會列出**本機所有 Claude session**,不只 herdr 管得到的那些。實測同一時刻:

```
Peer sessions 裡 kind=interactive 的:11 個(carson-agent-ef/1a/90/da/00/61/3b/65/06/54/98)
+ 本 session 自己  = 12
```

**和 12 支 shell 起的 `claude.exe` 逐一對得上**,也和「9 個 herdr 窗格 + 3 支對不到帳」對得上。
三本帳(行程樹 / herdr / ListAgents)互相獨立,結論一致 ⇒ 12 這個數字站得住。

⇒ **下次要盤點 session,先跑 `ListAgents`,不要從 `Get-Process claude` 減起。**
它天生就只數 session,不會把桌面版 App 那 8 支算進來,省掉整個第零節的坑。
⚠️ 但它的 `idle` 只表示「當下沒有在跑一個 turn」,**不等於閒置或可回收** ——
判閒置仍然要看當下 session id 的 jsonl mtime(memory `herdr-pane-session-map`)。

## 四、要動之前必須先做的(留給 Carson / 總督導,**我沒做**)

1. 把那 3 份逐字稿逐一對到 PID(數量對得上了,但**哪一份對哪一支還沒對**),
   並照 memory `herdr-pane-session-map` 的五步查證走 —— 特別是**讀第一則 user 訊息**,
   那句話會直接說出這是誰的對話。
2. 逐一問「它手上有沒有只活在逐字稿裡的東西」,有就先落檔再說。
3. 想省記憶體的話,**收 9 個 herdr 窗格裡真正閒置的**比動這 3 支安全 ——
   那 9 支合計 ~7.3 GB,而且 herdr 讀得到它們的狀態與逐字稿。
   ⚠️ 但 memory `machine-memory-optimization-2026-08`:**關 subagent 幾乎不還記憶體**
   (它跑在 parent 行程裡),要省只能關閒置 **session**。
