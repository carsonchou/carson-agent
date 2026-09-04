# 個股體檢種題:三天零產出的解剖與明天的驗收(2026-09-04)

> 一句話:**三天零種題,三種不同的死法,而修法至今一次都沒在產線執行過。**
> 補種**會自動發生**,不需要手動觸發 —— 但那是查出來的,不是假設的。

## (c) 修法上線後產線執行過了嗎 —— **沒有,而且今天不可能有**

| 日期 | 05:50 那一輪跑的碼 | 死因 | 證據 |
|---|---|---|---|
| 09-02 05:50:00 | 舊碼 | `NameError: name 're' is not defined` | `logs/job_stderr.log:45508`(表頭)/ `:45516`(錯誤) |
| 09-03 05:50:19 | 舊碼 | 同上 | `logs/job_stderr.log:47611` / `:47624` |
| 09-04 05:50:06 | **舊碼** | **網路斷線**,`Could not resolve host: query1.finance.yahoo.com` | `logs/job_stderr.log:49756`~`49795`(40 行,7 個 Error,**無 NameError**) |

```
git log -1 --format=%ad --date=format:"%m-%d %H:%M" eed3ca25   →  09-04 08:15
cron 的 stock_checkup_daily                                     →  每日 05:50
```

**修法 08:15 落地,比今天那一輪晚 2 小時 25 分。** 所以:

- 09-02 / 09-03 的 traceback 一路穿到 `stock_checkup_daily.py:390, in <module>` ——
  **不是某幾檔失敗,是整輪在第一檔就中止**(`--count 16`,一檔都沒種成)。
- 🔴 **09-04 沒有 NameError,不是因為修好了,是因為它在更早的地方就死了。**
  即使當天有 `import re`,DNS 掛掉一樣種不成。
  **所以補種清單要含 09-04,但把 09-04 歸因成「`import re` 造成」是錯的** ——
  兩個獨立原因產生同一個結果,而第二個把第一個是否修好這件事**遮住了**。
  如果今天網路正常,我們現在就已經知道答案。

⇒ **下一次真正執行是 2026-09-05 05:50。那會是這條路徑第一次跑修好的碼。**

## (a) 到底掉了幾檔 —— **48 檔,不是 32**

`STUDIO/stock_checkup_daily_state.json`:
```
last_run_date : 2026-09-01          ← 停在 09-01
history       : 553 筆,最後一筆是 2026-09-01(英濟3294 / 皇昌2543 / 錸寶8104 …)
                09-02、09-03、09-04 三天 **一筆都沒有**
```
每輪 `--count 16` × 3 天 = **48 檔**。（交辦時說的「約 32 檔」是兩天的數,漏了 09-04。）

## (b) 補種是自動的 —— **不需要手動觸發**

`last_run_date` **只是同日重跑守衛**(`stock_checkup_daily.py:416`
`if state.get("last_run_date") == today and not args.force ...`),**它不決定挑哪些股票**。

挑選來自 `STUDIO/stock_checkup_backlog.json`,是一個 **done/skip 工作佇列**:
```python
remaining = [it for i, it in enumerate(items) if i >= idx and not it.get("done") and not it.get("skip")]
```
沒種成的股票**沒有被標記 `done`**(崩在 `seed_topics_for_code:270`,在標記之前),所以還在隊伍裡。

實測(09-04 13:20):
```
backlog 總數 1925  |  done 584  |  skip 32  |  待處理 1309
待處理隊伍前 6 檔:2208 台船 / 6679 鈺太 / 3545 敦泰 / 3528 安馳 / 1595 川寶 / 4968 立積
```
⇒ 那 48 檔**不是永久缺口,是 1309 深佇列裡的三天順延**(以 16 檔/日算約 82 天清完,3 天 = 3.7%)。
**不需要任何手動動作。**

## 🔴 明天早上(09-05)要看的檢查 —— 具體到檔案與行

這條線今天所有的洞都是同一個形狀:**修好 ≠ 開始跑,而中間那一步沒有人回頭確認。**
所以驗收寫成沒有今天脈絡的人也照著跑得出是/否:

```bash
cd D:/carson-agent/youtube_channel
# ① 這一輪到底有沒有跑成
python -c "import json;d=json.load(open('STUDIO/stock_checkup_daily_state.json',encoding='utf-8'));\
print('last_run_date=',d['last_run_date'],' history=',len(d['history']))"
# ② 有沒有再炸一次(基準:目前最後一次 NameError 在 47624 行)
grep -n \"NameError.*'re'\" logs/job_stderr.log | tail -3
# ③ 這一輪的表頭與死因(基準:上一個表頭在 49756)
grep -n "^===== \[.*stock_checkup_daily" logs/job_stderr.log | tail -2
```

| 看到什麼 | 代表 |
|---|---|
| `last_run_date=2026-09-05` 且 `history=569`(553+16) | ✅ **修法第一次成功執行**,收工 |
| `last_run_date=2026-09-01`、history 仍 553 | ❌ 又失敗了 —— 去 ② ③ 看死因 |
| ② 出現行號 **> 47624** 的新 NameError | ❌ **修法沒生效**,`import re` 那條路徑有第二個問題 |
| ② 沒有新 NameError、但 ① 也沒動 | ❌ 死在更早的地方(如今天的 DNS)—— 看 ③ 的區塊內容 |
| history 增加了但**標題壞掉** | ❌ 三道閘門(`d2020bae`)的問題,不是 `import re` 的 |

⚠️ **`history` 沒增加**這個訊號要特別小心:它同時代表「修法失敗」和「整支根本沒跑」,
兩者在這個數字上長得一樣 —— 所以 ③ 是必要的第二條,它才分得開
(有表頭 = 跑了但失敗;沒表頭 = 排程沒觸發)。

## 出處
- 三天死因與行號:本檔上表,`logs/job_stderr.log`(09-04 13:20 的行號,檔案會增長)
- 佇列語意:`scripts/stock_checkup_daily.py:416`(同日守衛)、`main()` 內 `remaining` 那行
- 修法:`eed3ca25`(`import re`);同段的三道標題閘門另見 `d2020bae` / `7a17bcc7`
- 相關 memory:`verification-that-cannot-fail`(第零種:規則沒變成檢查)、
  `verification-claims-in-commit-messages`(把兩件事併成一個因果鏈)
