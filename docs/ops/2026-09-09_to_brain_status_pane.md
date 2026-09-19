# 給 BRAIN 線 — `status_pane.py` 跑的是 8 天前的 `brain_auto`

> 來源:基建線(wF:p3)2026-09-09 掃「今天改的常駐程式碼有幾件在磁碟上而不在記憶體裡」時掃到的。
> **這不是 BRAIN 線做錯了什麼**,是一個跨線都會中的形狀,只是它在你們這裡潛伏最久。
> ⚠️ 走總督導轉,不直接對線講 —— 09-05 有過兩個 session 各算一遍、一起修一個不存在的問題。

## 事實(可自行複驗)

```powershell
Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
  Sort-Object CreationDate |
  ForEach-Object { "{0,-6} {1:MM-dd HH:mm:ss} {2}" -f $_.ProcessId, $_.CreationDate, $_.CommandLine }
```

| 程序 | 指令 | 啟動時間 |
|---|---|---|
| **PID 35716 / 41704** | `python -u quant-service/brain_alpha/status_pane.py --every 300` | **2026-09-01 21:44:06** |
| PID 59468 / 28456 | `youtube_channel/scripts/brain_alpha_cron.py --run 400` | 2026-09-09 07:40:14 |

`status_pane.py:143` 有 `import brain_auto as B`。Python 的 `sys.modules` 會**快取模組**,
所以 `--every 300` 的迴圈只在**第一圈**載入一次 ⇒ 它手上那份 `brain_auto` 是 **09-01 的**。

`brain_auto.py` 從那之後被改過,光是 09-09 當天就兩次:
- `87605386` 2026-09-09 00:00:39
- `545ed1ce` 2026-09-09 07:04:34(「worker 被連線中斷殺掉,而批次看起來像跑完了」)

對照:`brain_alpha_cron.py`(PID 59468)**啟動於 07:40:14,晚於那兩個 commit** ⇒ **它是新的**。
所以同一台機器上,**同一個 `brain_auto` 有兩個版本同時在跑**。

## 為什麼要講,以及為什麼不急

`status_pane.py` 的檔頭寫「**只讀不寫:兩個 GET**」,我也 grep 過
(`write_text` / `json.dump` / `open(...,"w")` / `POST` / `requests.` **零命中**)
⇒ **它不會毀資料,不會誤交 alpha,不會動帳本。**

但它是那條線**常駐給人看的狀態板**(檔頭:「Carson 掃一眼就知道」)。
⇒ 風險是:**它顯示的數字是 09-01 那版邏輯算出來的,而畫面上看起來完全正常。**
如果 `brain_auto` 這 8 天改過任何「怎麼算當日提交數 / 還剩幾條能交 / 挖礦有沒有在動」的邏輯,
那塊板子就在說一個過時的版本 —— 而且沒有任何訊號會說它過時。

## 建議(不是指令,那條線自己判斷)

1. **先確認值不值得動**:`git log --since=2026-09-01 -p -- quant-service/brain_alpha/brain_auto.py`
   看那 8 天的改動有沒有碰到 `status_pane` 會用到的那幾個函式。**沒碰到就不用重啟**,
   記一筆「已確認不受影響」即可 —— 那本身就是有用的結論。
2. 要重啟就直接重啟(它只讀不寫,沒有鎖、沒有狀態、沒有空窗成本,和 `local_cron` 完全不同)。
3. 🔴 **重啟之後不要用「PID 換新了」當驗收**。那只證明重啟了。
   要證明新碼在跑,得讓一條**只有新碼才會走的路徑**留下痕跡。
   (基建線今天的做法:讓門檻真的被跨過一次,並拿**同一支檔案在舊碼下的真實觸發**當陰性對照。)

## 一般化的那條(已落在 `youtube_channel/deploy/WATCHDOG.md`)

> **「commit 了」和「跑起來的行為變了」,對常駐程序隔著一次重啟。**
> 判準:改的東西是被**每次重讀**的(設定檔/資料檔),還是**啟動時載入一次**的(模組/程式碼)?
> 後者一律要問:**哪個程序在跑它、什麼時候啟動的、那個時間在我的 commit 之前還是之後?**

⚠️ 一個容易誤讀的推論:**排程器載舊碼,不代表它派出去的 job 是舊碼。**
`local_cron.run_job()` 用 `Popen` 每次開新行程 ⇒ job 腳本一律載當下磁碟上的碼。
同理,`brain_alpha_cron.py` 每次由排程重新啟動 ⇒ 它沒有這個問題。**只有真正常駐的那支會卡住。**
