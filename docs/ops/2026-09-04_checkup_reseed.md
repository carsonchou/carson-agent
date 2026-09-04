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

## (a) 到底掉了幾檔 —— 48 檔(**但那不是缺口總數,真值 172,見第二節**)

> 48 = 那三天本來會處理的量,成因是 `import re` + DNS。
> 172 = 孤兒總數,成因是「先標 done 再種題」的結構。**兩個數字不要合併。**

`STUDIO/stock_checkup_daily_state.json`:
```
last_run_date : 2026-09-01          ← 停在 09-01
history       : 553 筆,最後一筆是 2026-09-01(英濟3294 / 皇昌2543 / 錸寶8104 …)
                09-02、09-03、09-04 三天 **一筆都沒有**
```
每輪 `--count 16` × 3 天 = **48 檔**。（交辦時說的「約 32 檔」是兩天的數,漏了 09-04。）

## (b) ~~補種是自動的 —— 不需要手動觸發~~ 🔴 **這一節整段已被推翻,見下方第二節**

> **不要照這一節動作。** 下面這段是我(督導)09-04 13:20 寫的,**結論是錯的**,
> 保留原文是因為它示範了錯在哪:**我從 traceback 推斷「崩在標記之前」,而沒有去讀
> `done` 是在哪一行設的**。實際順序是 `:449 done=True` → `:451 落盤` → `:452 才種題`,
> 所以每一次崩掉都把那檔**永久**標記成做完了。正確結論在
> 「二、172 和 48 是兩件不同的事」與「三」。

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
~~⇒ 那 48 檔不是永久缺口,是 1309 深佇列裡的三天順延(以 16 檔/日算約 82 天清完,3 天 = 3.7%)。
不需要任何手動動作。~~

🔴 **以上兩句都是錯的。** 那 48 檔**是**永久缺口(已被標 `done`,佇列再也不會挑到),
而且真正的缺口是 **172 檔**(48 只是其中最近三天的部分)。**必須手動補種。**

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

---

# 更正(2026-09-04 13:4x,主頻道線實證)

## 🔴 一、「補種自動、不需手動」**推翻了**

依據不是推論,是原始碼順序:

```
stock_checkup_daily.py:449   cand["done"] = True
                      :450   cand["done_at"] = today
                      :451   _save_backlog(bl)                       ← done 已經落盤
                      :452   n_new_topics = seed_topics_for_code(…)  ← 崩點 :270 在這裡面
```

**標 done 在種題之前,而且中間存過檔。** 所以崩掉的股票已經被標成 done,
backlog 的 `not done and not skip` 佇列**永遠不會再挑到它們**。

實證(不是推論):

```
backlog done = 584    有事實 = 585    topic_bank 有題 = 417
🔴 已標 done + 有事實 + 完全沒有任何題目 = 172 檔
```

名單:`STUDIO/_reseed_orphans.json`(5880 合庫金、2328 廣宇、3693 營邦、8155 博智…)。

`skip = 32` 那組清白:理由是「價格資料抓取失敗或上市未滿最短年限」31 檔 +
「算不出任何事實」1 檔,**沒有一檔是崩在種題**。原本擔心的那件事沒發生,
但真正的洞在另一邊。

## 🔴 二、172 和 48 是**兩件不同的事**,不准合併成一個數字

| | 數字 | 成因 | 性質 |
|---|---|---|---|
| 48 | `--count 16 × 3 天` | `import re` 缺失(09-02/03)+ DNS 斷線(09-04) | **一次性事件**,已修(`eed3ca25`) |
| **172** | `_reseed_orphans.json` 實測 | **「先標 done 再種題」這個結構** | **持續失血**,未修 |

**就算 `import re` 從來沒發生過,這個結構照樣會持續產生孤兒** ——
172 − 48 ≈ 124 檔是更早累積的,而那些日子沒有 NameError。

寫成「172 檔因為 `import re` 而遺失」就是今天一直在犯的那個錯:**兩個獨立原因併成一個因果鏈**。
(同型:09-04 那天就算有 `import re` 也一樣種不成,因為 DNS 掛了 ——
而第二個原因把「第一個修好沒」這件事**遮住了**;網路正常的話今天就知道答案了。)

## 三、結構修法:今晚不動,代價寫明

**不動的理由**:`stock_checkup_daily.py` 明天 05:50 要跑,而且是 `d2020bae`/`7a17bcc7`
三道閘門第一次帶真實資料執行。今晚再動同一支檔 = 把兩個變數混進同一次觀測。

**不動的代價(要的是數字不是感覺)**:明天 `--count 16`,每失敗一檔就再永久掉一檔。
歷史失敗率估法:584 done 裡 172 沒種成 = **29.5%**,但那個分母混了 `import re` 那三天;
扣掉那 48 檔後是 `124 / 536 = 23.1%`。→ **明天預期新增孤兒 16 × 23% ≈ 3.7 檔**。
可用 orphans 名單救回(facts 已存在,不必重抓),所以我判**代價可接受,同意不動**。

**兩種修法,留給後面的人選(今晚不實作)**:
- (a) 把 `cand["done"] = True` 移到 `seed_topics_for_code` 回傳成功之後
  —— 風險:種題中途崩掉會讓那檔永遠重試,要確認 `MAX_FAILS` 接得住
- (b) 種題失敗(例外或回傳 0)時回滾 `done`
  —— 風險較低,但要定義「失敗」:回傳 0 到底是「沒新題」還是「種不進去」

督導偏好 (b)。屬產線結構改動,要獨立驗證。

## 四、172 檔補種:可做,但 **dry-run 不是零成本**

走 `topics_from_facts.py` / `seed_topics_for_code()`,**不是**排程那支的主流程,
事實都已在 `stock_checkup_facts.json`,不必重抓 FinMind/yfinance,也碰不到明天的觀測。

⚠️ 但 `--dry-run` 只是**不寫檔**,LLM 照打(`seed_topics_for_code` 亦同,
`dry_run` 參數不影響 `sc.has_llm_key()` 之後那段)。
所以 **dry-run 的 LLM 成本 == apply 的成本**,「先 dry-run 看幾題」在這裡買不到資訊。

可analytically 給的數字:`MAX_TOPICS_PER_CODE = 1` → **上限 172 題,一檔一題**;
成本 = **172 次 LLM 呼叫**。建議直接 apply 並分批(例如一次 30 檔),
每批之後看 `topic_bank` 實增數;要 dry-run 的話只對前 5 檔做,確認品質就好。

`topics_from_facts.py` 目前**沒有「只處理這些代號」的參數**(只有 `--limit-facts N` 取前 N 組),
所以要嘛加一個 filter,要嘛寫一支小 driver 逐檔呼叫 `seed_topics_for_code(code, name)`
—— 後者是新檔案,不動排程那支。

## 五、明天早上的驗收表:再找出一個同形格子

已知並已配對第二訊號的:
- `history` 沒增加 → 同時代表「修法失敗」與「整支根本沒跑」→ 配 `job_stderr` 有無新表頭

**本次新增(第二個同形格子)**:
🔴 **`backlog` 待處理數減少 → 同時代表「種題成功」與「標了 done 但種題崩了」**
—— 因為 done 在種題之前就落盤。09-02/03 那兩天待處理數**照樣在掉**,而那兩天種了 0 題。
→ 正確訊號:**看 `topic_bank.json` 有沒有多出對應 `fact_key` 的題**,不要看 backlog。

**第三個(本次再找到的)**:
🔴 **`seed_topics_for_code` 回傳 0 → 同時代表「LLM 生的題全被閘門擋下」與「根本沒呼叫 LLM」**
(`:158` 無 LLM key 時直接 `return 0`,而那條路徑只 print 不記 ops_log)。
→ 明天要看的不是回傳值,是 ops_log 有沒有
`[09-05 05:5x] …` 的種題成功行 **與** `topic_bank` 的實際增量,兩者都要。

### 明天 05:50 之後具體要看什麼

| 看哪裡 | 預期看到 | 看不到代表什麼 |
|---|---|---|
| `logs/job_stderr.log` 找 `[2026-09-05 05:5x] scripts/stock_checkup_daily.py` | **有表頭** | 沒表頭 = 排程沒觸發(不是修法失敗) |
| 同上,往下 20 行 | **沒有** `NameError: name 're'` | 還有 = `eed3ca25` 沒生效 |
| `stock_checkup_daily_state.json` 的 `history` | 多出 09-05 的筆數 | 沒多 = 整支沒跑完 |
| **`topic_bank.json` 中 `source=stock_checkup_daily` 的筆數** | 從 **407** 往上增 | 沒增 = 種題仍然失敗(這是唯一能單獨判定的訊號) |
| `STUDIO/stock_checkup_backlog.json` 待處理數 | 從 **1309** 往下掉 | ⚠️ **掉了也不代表成功**,見上面第二個同形格子 |
