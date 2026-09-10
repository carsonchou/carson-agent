# 產線規則強制力清冊 —— 2026-09-10(落檔 09-11)

> 起因:同一天兩條線得同一種病。基建線的業務介紹遵守率連四天低於地板(36%→32%→44%→42%),
> 它自己的診斷是「**那條規則只寫在 prompt 層**」;主頻道線的規則ⓜ寫在
> `produce_batch.py:1275`(LONG_RULES)而真閘門在 `:5287`,09-06 產的片逐字違反ⓜ。
> memory `verification-that-cannot-fail` 把這叫**第零種失效**:
> **規則只寫在 prompt 層 ⇒ 那是期望不是規則,違反時系統不產生任何輸出。**
>
> 🔴 本檔**只清點,不修**。一行產線碼都沒動(`produce_batch.py` md5 開工前後皆為
> `9336a28ee6c22fbbda20742a51d78487`)。改哪些、什麼順序,由總督導和 Carson 決定。

---

## 一、結論:三個數字

> **共 187 條規則 / 其中 86 條只在 prompt 層 / 其中 44 條有閘門但 fail-open。**

拆解(**不要把兩個母體加成一個來用**,它們的「只在 prompt 層」不可比):

| 母體 | 條數 | 只在 prompt 層 | 部分覆蓋 | 有閘門 | 其中 fail-open |
|---|---:|---:|---:|---:|---:|
| **A. 產出端**:`produce_batch.py` 13 個 prompt 常數 | 155 | **86** | 45 | 24 | **26** |
| **B. 守望端**:`*_watch.py` / `*_watchdog.py` 判準 | 32 | 不適用(見下) | — | 29(3 條死碼) | **18** |
| 合計 | **187** | **86** | 45 | 53 | **44** |

- **M=86 全部落在母體 A。** 母體 B 是程式,結構上不可能「只在 prompt 層」;
  它的對應空洞是**死碼 3 條**(`growth_watchdog.py` / `render_watcher.py` /
  `watch_drill_regression.py`)—— 判準寫好了、沒有任何呼叫端或排程,違反時同樣零輸出。
- **K=44 = 母體A 26 + 母體B 18。** 母體A 的 26 逐條可數:
  **fail-open(靜默)14 條**(`HOOK-10/14/16/17/22/23/24/25/26/27/34/36/37/46` —— 判斷式掛在
  `:6020-6029` 的 while 條件裡,命中、重生用盡後**一行都不寫**,見第三節(1))
  + **重生耗盡後放行 6 條**(`HOOK-11/15/29`、`LONG-11`、`ABB-01`、**`CHECKUP-18`**)
  + **路徑相依 5 條**(`LONG-12/13`、`ABB-02/03/04`)+ **有聲 1 條**(`CHECKUP-11`)。
  換一種切法同樣是 26:判「有閘門」的 11 條 + 判「部分覆蓋」的 15 條。
  母體B 的 18 = 有聲 10 / 靜默 8(另有 1 條死碼 `WATCH-22` 其判準若被執行也是 fail-open,**未計入 K**)。
  ⚠️ 「路徑相依」那 5 條在 A4 路徑是 fail-closed、在 checkup 路徑是重生耗盡後放行;
  **我把它們計進 K**,理由是 checkup 佔長片產出 93%。改用「兩條路徑都 fail-open 才算」的口徑則 K=39。
- 🔴 **K 從 43 改成 44 是覆核翻案,不是重數**:`CHECKUP-18`(誠信類「財報數字不准自己換算估計」)
  初稿判 fail-closed 是錯的 —— 它的原因字串「同句數字自相矛盾」正落在 `:6335-6336` 的白名單裡,
  checkup 路徑重生用盡會**放行並記一行警告**,而那行警告還寫錯名字。見第三節(6)。
- 母體 A 另有 **45 條「部分覆蓋」**:有閘門,但閘門查的東西比規則窄(窄化的形狀逐條寫在表裡)。
  **這 45 條不算進 M**(它們不是「只寫在 prompt 層」)。
  🔴 **但其中 15 條要算進 K** —— 「部分覆蓋」不等於「沒閘門」,那個窄閘門自己照樣可以 fail-open。
  母體A 的 K=26 正是「有閘門」11 條 + 「部分覆蓋」15 條。
  **本行初稿寫成「也不算進 K」,與下面兩張表直接打架,已更正。**

---

## 二、判準:什麼才算「有閘門」

預設答案是**「只在 prompt 層」**。要翻成「有閘門」,必須同時舉得出三樣:

1. **檔:行號**(定義處)
2. **判斷式原文**(那一行程式碼在比什麼)
3. **違規時產生什麼輸出**:拋錯 / 回 False / 印警告 / **什麼都沒有**

🔴「有一個函式名字看起來對」**不算**。本清冊裡每一條判「有閘門」的都附了呼叫端行號。

**fail 分類(四格,後兩格是本次新增)**

| 分類 | 定義 | 為什麼要分出來 |
|---|---|---|
| **fail-closed** | 違規→該稿不輸出 / 不上傳 / 被確定性改寫掉 | 唯一真的在擋的 |
| **fail-open(有聲)** | 印警告 / 寫 log / 推播,**流程照走** | 🔴 **最會騙人的一格:它有輸出,所以看起來像有守門** |
| **fail-open(重生耗盡後放行)** | 命中→重生 N 次→仍命中→寫一行 `⚠️…已放行需人工複查`→**照樣輸出** | 🔴 比上一格更會騙人:它連重生迴圈都跑了 |
| **fail-open(靜默)** | 判斷式跑了、命中了,什麼都不產生;或**判斷式所在的分支根本沒被執行** | 與「只在 prompt 層」等價的失效 |

---

## 三、🔴 最會騙人的那幾格(督導點名要單獨標出)

### (1) fail-open(重生耗盡後放行)—— **產線上已經真的放行過 72 次**

六個站點,全在 `produce_batch.py`:`:6046`(A1b 內文/CTA 重複度)、`:6049`(A1c 已知濫用比喻)、
`:6173`(A1b 長片)、`:6176`(A1c 長片)、**`:6189`(A2 疑似捏造績效數字)**、`:6349`(鉤子後仍在鋪陳)。
全部以 `log_ops("補產部門", f"⚠️ …重生{n}次仍命中,已放行需人工複查:…")` 結尾,**然後把稿交出去**。

🔴 **但「有這行警告」只涵蓋這六個站點,不涵蓋同一個重生迴圈裡的其他判斷式。**
`:6020-6029` 的 while 條件掛了 8 個判斷式,迴圈跑完之後只有
`_ending_too_similar`/`_body_too_similar`(`:6044-6046`)與 `_notorious_metaphor_hit`(`:6047-6049`)
會寫 log;`_weak_hook`、`_impact_density`、`_weak_mid_hook`、`_reveals_too_early`、
`_self_repeated_metaphor` **重生兩次仍命中時,一個字都不寫就把稿交出去**
⇒ 那是 **fail-open(靜默)**,不是本格。母體A 有 **14 條 HOOK 規則**落在那一類
(`HOOK-10/14/16/17/22/23/24/25/26/27/34/36/37/46`),表格已逐列改判。
**它們的失效在 ops_log 上連一行都沒有 ⇒ 下面那 72 筆完全看不到它們。**

**這不是理論值。實測 `STUDIO/ops_log.txt`:「已放行需人工複查」共 72 筆。**

| 類別 | 次數 |
|---|---:|
| A1b 長片(內文/CTA 重複度) | 22 |
| A1c 長片『雲霄飛車』 | 15 |
| A4 長片字數不足 | 7 |
| A1b(Shorts) | 7 |
| A1c『賓士』 | 5 |
| A1c『考古題』 | 4 |
| **A2 疑似捏造績效數字** | **3** |
| A1c『雲霄飛車』 | 3 |
| A1c 長片『考古題』 | 2 |
| 雜貨店 / 賓士 / 滾雪球 / 菜市場大媽 各 1 | 4 |

🔴 **A2「疑似捏造績效數字」被放行過 3 次**,分別在 `[08-09 04:01:26]`、`[08-24 22:52:40]`、
**`[09-03 04:02:12]`**。那是誠信類判準,它命中了,然後片子照樣出去。

### (2) 這 72 行警告:**唯一會統計的分析器不認得它**(兩處會原樣印出,但都不是分析器)

`scripts/daily_health.py:140-144` 是產線路徑上唯一讀 `ops_log.txt` 的分析器:

```
if "已備妥待渲染" in _l:   → 成稿
elif "fail-closed" in _l or "⛔" in _l:  → 報廢
```

**它不找「已放行需人工複查」。** 每日健檢只報「成稿 N / fail-closed M」,72 次放行在**健檢報表上**不存在。
全 repo 提到「人工複查」的非程式碼文件只有 2026-07-10~07-18 的 REPORTS,**那個回報早就停了**。

⚠️ **初稿這一節的標題寫「沒有任何消費者」,那句太強,自己覆核時推翻。** 有兩處會讓這些行進到人眼前:
`scripts/control_center.py:2003-2005` 掃 ops_log **最後 80 行**、挑含
`("⚠️","FAIL","失敗","錯誤","FATAL")` 的行顯示;`scripts/cloud_status.py:74` 的 `_ops_tail(14)` 直接印尾 14 行。
**但兩者都只是「把最近幾行原樣貼出來」—— 不分類、不計數、不設門檻、不告警**,而且都只看尾巴,
72 筆裡絕大多數早已滾出視窗。
⇒ 精確的講法是:**「印警告但流程照走」,而唯一會統計 ops_log 的分析器不認得這個字串。**

### (3) 閘門存在,但那條分支對 93% 的長片**從未執行**

`CHECKUP-15/16/17`(雷同度/差異化)與 `TWLABL-06`:GATE-15/16 的函式本體在
`produce_batch.py:765 _ending_too_similar` 與 `:1030 _body_too_similar`,而**呼叫點**整段包在
`not topic_override` 分支裡;而個股體檢(佔長片產出 93%)
與 `--tw-lab`(`:6759-6771`)**永遠帶 topic_override** ⇒ **那個分支根本沒跑**。
🔴 這不是「命中了沒擋」,是「連判斷式都沒被執行」—— 但它 grep 得到、看起來有守門。

⚠️ **更正**:本節初稿寫「GATE-15/16 定義在 `:5754-5768`」是錯的 —— **那一段是註解不是程式碼**,
而註解的內容恰恰在講「個股體檢永遠有 topic_override ⇒ 這五道整組跳過」。函式定義在 `765` / `1030`。
**結論本身(那條分支對 checkup 從未執行)不受影響,是獨立複驗過的。**

### (4) 名字叫「自癒」而實質空轉:`_long_fact_heal`(`produce_batch.py:4637`)

三處主流程呼叫、有 print,但回傳的 `remaining` **從未被任何後續判斷消費**。
函式自己的 docstring 記著一次實測:全域事實池 33,885 個數字之下,
**拿 12 支真稿、共 417 個數字宣稱去驗,判定「無憑據」= 0 個**。

⚠️ **那個 0 的射程只有那 12 支 / 417 個宣稱**,不等於「它永遠抓不到」;而且同一段 docstring
自己接著寫:換成收窄池(`fact_pool_for`)判出 26 個,**「兩邊都不可信」**。
引用這一格時**要連這句一起引** —— 初稿只寫了「= 0」,把射程和作者自己的保留都吃掉了。
(同款:`fact_guard.flags_for` / A2 捏造績效,重生 2 次仍命中只印警告放行。)

### (5) 死碼:寫好了、沒人呼叫

`quality_score.passes_floor`、`attribution_guard.check_text`(全 repo grep 零呼叫端,已排除 ch2/ch3);
守望端 `growth_watchdog.py` / `render_watcher.py` / `watch_drill_regression.py`
(後者 `WATCHDOG.md:195` 明寫「還沒排進任何排程,引信要人按」)。

### (6) 🔴 放行紀錄**掛錯名字**:`:6349` 那行 log 把原因寫死成「鉤子後仍在鋪陳」

`:6335-6336` 的白名單放行**兩種**原因:

```python
if _why2 and (_why2.startswith("鉤子後仍在鋪陳") or _why2.startswith("同句數字自相矛盾")):
```

但 `:6349` 真正寫進 `ops_log` 的那一行,**原因字串是寫死的**:
`log_ops("補產部門", f"⚠️ 鉤子後仍在鋪陳·重生{_t2}次仍命中,已放行需人工複查…")`。
⇒ 只要被放行的是**「同句數字自相矛盾」**(`_long_corrupt_number`,也就是 `CHECKUP-18` 的閘門),
紀錄上會被記成「鉤子後仍在鋪陳」。**任何按類別數放行次數的人,永遠數不到它。**

⚠️ **這是潛在缺陷,不是已發生的事故**:實測 `ops_log.txt`,「鉤子後仍在鋪陳」放行 **0 次**、
「同句數字自相矛盾」放行 **0 次** —— 那條白名單到目前為止一次都沒放行過任何稿。
記在這裡是因為它把**誠信類閘門的放行**寫成別的名字,而誠信類正是最需要能被逐筆點名的一類。


---

## 四、五個獨立發現(不在四個子表裡,是我自己量的)

### A. 🔴 規則ⓜ 和它的閘門**現在講的不是同一件事**

- **prompt 層(`produce_batch.py:1275` LONG_RULES ⓜ-1)**:
  「只要句子裡出現 0050 的對照數字,**同一句**就必須寫出是哪段期間…**年數寫在前一句不算**」。
- **閘門(`:5287` `_long_mixed_period`)**:2026-08-30 重構後改成兩層,而且
  **年數改看「這一句 + 前後各一句」的視窗**(`_win = "".join(sents[max(0, i-1):i+2])`)。

成因寫在該函式自己的註解裡:08-28 餵料端修法後,模型會把期間**自然地分成兩句寫**,
原本的同句判準**幾乎擋掉全部** —— **08-29 整天 17 支被殺、成稿 0**。
⇒ **prompt 說「前一句不算」,閘門說「前一句算」。**規則ⓜ的字面在程式裡已經沒有執行者。

🔴 **更糟的一件,寫在同一段註解裡**:兩層判準中精準的那層(①事實錨定)
「**這道最精準的判準在真實旁白上幾乎從來沒生效過**」—— 它只認阿拉伯數字,
而旁白為了 TTS 幾乎都寫中文(「百分之六百三十八點二」)。
⇒ 實際在跑的只有被放寬過的粗規則②。

**另外**,督導點出的「入口有觸發詞白名單」我複驗屬實:判斷式進入前先要求句中出現
`同期|同時期|同一段期間|相同期間|同樣的時間|這段期間` 其中之一,再要求出現 `0050` 語族詞。
**沒有這些觸發詞的違規句,判斷式連看都不看。**
⇒ 這也是我把 LONG-15/16 從 join-A 的「只在 prompt 層」改判成「**部分覆蓋**」的理由
(見第六節「我推翻了子表的哪一格」)。

### B. 新分類「fail-open(重生耗盡後放行)」原本不在題目給的四格裡 —— 見第三節(1),72 次實測。

### C. 那 72 行警告,唯一會統計 ops_log 的分析器(`daily_health.py`)不認得它 —— 見第三節(2)。
(初稿寫「沒有任何消費者」,覆核時被 `control_center.py:2003-2005` / `cloud_status.py:74` 推翻,已收窄。)

### D. `fact_guard.py` 每天在跑,但它廣告的「攔」**在程式裡不存在**

docstring:「命中→寫 `STUDIO/fact_flags.json` + ntfy 提醒人工複查(**或搭 daily_publish 攔**)。**只旗標不刪**」。
排程在 `deploy/crontab.txt:531`(`30 11 * * *`),而且**確實在跑**(`STUDIO/fact_flags.json`
mtime 09-10 11:30,2 筆)。但 `fact_source_guard.py:16` 自己記著:
「fact_flags——『攔』這個動作**根本不存在**,偵測到也只是記一筆,片照發。」
⇒ **fail-open(有聲)**,而且是「文件承諾了一個沒實作的動作」這種形狀。

⚠️ 這條差點被我報成「沒排程」:`crontab.txt` 裡還是死掉的 droplet 路徑 `/root/yt/run.sh`,
是 `local_cron.py:239 parse_jobs()` 在翻譯。**只讀 crontab 會得到錯的否定。**
(同一個 parse_jobs 只留 python job ⇒ `:555` 那行 `cd /root/yt && …` 的備份**被靜默丟掉**。)

### E. 🔴 事實區塊內部的**算術自洽**:連 prompt 層都沒有(督導 09-11 提供,我複驗)

`docs/ops/2026-09-11_期間偷換_督導獨立複驗.md` 第四節(commit `344ade9f`):
漢磊 3707(08-30 已發布)的事實區塊寫「All-in 總報酬 451.5%(**年化約 6.5%**)」——
451.5% 十年 = 年化 18.6%。同區塊 0050 的 701.9%/22.7% 反推剛好十年 ⇒ **錯的是 6.5%**。
而該稿守則①寫明「你唯一能當事實講的精確數字,只有實證資料區塊給的那幾個」,
**旁白完全照做,照抄了一個自己不成立的『事實』。**

⇒ **這一格比第零種更前面:第零種是「規則只寫在 prompt 層」,這一格是「連 prompt 層都沒有這條規則」。**
誠信守門全線問的是「這個數字**有沒有憑據**」,沒有任何一層問「**憑據自己合不合算術**」。
**本清冊的 187 條裡沒有這一條,因為它不存在** —— 它是清冊之外的洞,獨立記在這裡。

---

## 五、母體 A:`produce_batch.py` prompt 層規則 155 條

13 個常數:`HOOK_RULES:1101`(48)、`LONG_RULES:1221`(17)、`EP_RULES:1298`(9)、
`DEBUNK_RULES:1312`(6)、`CURRICULUM_RULES:1323`(6)、`TW_STOCK_RULES:1334`(11)、
`TW_STOCK_CHECKUP_RULES:1364`(20)、`TW_LAB_RULES:1418`(9)、`TW_LAB_LONG_RULES:1447`(9)、
`NO_FACTS_INTEGRITY_RULES:1475`(4)、`AI_SAVINGS_RULES:1503`(5)、`AI_COMPANY_RULES:1514`(6)、
`_AB_B_RULES:5124`(5)。**全檔沒有 `SHORT_RULES`**(Shorts 走 `HOOK_RULES`)。

⚠️ 另有 7 個常數同樣餵進 prompt 但**未抽條入表**(逐條化了會超出本次範圍,先記名):
`_AMOUNT_DISCIPLINE:76`、`GUARD:86`、`QUANT_STANDARD:98`、`_DEFAULT_PLAYBOOK:112`、
`TITLE_FORMULA:3193`、`WINNING_FORMAT:3362`、`TW_NO_FACTS_OVERRIDE:1492` ——
其中 **GUARD / QUANT_STANDARD / TITLE_FORMULA 是每支片必注入**,不是條件式。
⇒ **N=155 是下界,不是全集。**

### 5-1 HOOK_RULES / LONG_RULES / _AB_B_RULES(70 條)

| 規則id | 規則一句話 | 判定 | 閘門(檔:行) | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| HOOK-01 | 標題需含具體標的代碼 | 只在prompt層 | — | （`_TF_A=re.compile(r"[0-9０-９%]｜[十百千萬億兆]")` 只認任意數字，非「代碼」）| — | 無閘門 |
| HOOK-02 | 比較敘事優先，禁教你怎麼做說教框 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-03 | 禁「網格/機器人/派網/比特幣/BTC/爆倉/加密」入Shorts標題 | 只在prompt層 | — | `BANNED_SKELETONS`(studio_common.py:91-104)是特定濫用句型清單(如「爆倉…還活著」)，非關鍵字黑名單 | — | 無閘門 |
| HOOK-04 | 工具詞只能後段當解法出現，永不入標題 | 只在prompt層 | — | 同HOOK-03，無關鍵字禁令機制 | — | 無閘門 |
| HOOK-05 | 標題需標的代碼或「定期定額/定投」動作詞 | 只在prompt層 | — | `_TF_A`同HOOK-01，未鎖定該詞 | — | 無閘門 |
| HOOK-06 | Shorts標題禁「EP數字」 | 只在prompt層 | — | 全檔grep「EP.{0,3}數字」「EP編號」相關字串僅命中prompt文字與checkup系列的CHECKUP-02(不同常數)，Shorts無對應檢查 | — | 無閘門 |
| HOOK-07 | 白話翻譯術語(偏好非硬性) | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-08 | 「我先幫你試」角度(偏好非硬性) | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-09 | 痛點用白話講法 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-10 | 前3秒恐懼/痛點需精確數字 | 部分覆蓋 | produce_batch.py:3446 `_weak_hook` | `has_num = bool(_r.search(r"[0-9０-９]｜[一二三四五六七八九十百千萬兩半倍成]", head))` | 命中弱鉤子條件→計入6020-6029 while迴圈重生 | 只查「有無數字」，不查「精確/丟給陌生人立刻懂」的品質；查不到即fail-open(靜默)見下;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-11 | 數字/情境每支重抽，禁固定套用同一數字 | 部分覆蓋 | produce_batch.py:1030 `_body_too_similar` | `def _body_too_similar(text, recent_texts, thr=0.85, min_len=10)` | 命中→計入6020-6029 while；重生2次仍中→6044-6046只log警告放行 | fail-open(重生耗盡後放行)。只比對「跟近期片相似度」，不是「本支內是否重抽了新數字」 |
| HOOK-12 | 中段留好奇缺口，不給全部答案 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-13 | 工具只當解法步驟，非開頭主題 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-14 | 第一句(前1秒)最驚人數字+直覺衝突，0開場白 | 有閘門 | produce_batch.py:3446 `_weak_hook` | `weak_orig = (not has_conf) and ((not has_num) or (not has_you))` `if weak_orig or _is_preamble_open(head): return True` | True→計入6020-6029 while(_hk<2)重生；仍中→6044/6047只log放行 | fail-open(靜默);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-15 | 數字/動作/情境每支換，嚴禁逐字抄 | 部分覆蓋 | produce_batch.py:1030 `_body_too_similar`(thr=0.85) | 同HOOK-11 | 同HOOK-11 | fail-open(重生耗盡後放行)；只防「跟近期片」逐字抄，不防「本規則要求的換不同數字」本身 |
| HOOK-16 | 第一句必須是結論/最大數字，非暖場鋪陳 | 有閘門 | produce_batch.py:3446 `_weak_hook`／3430 `_is_preamble_open` | `if weak_orig or _is_preamble_open(head): return True` | 同HOOK-14 | fail-open(靜默);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-17 | 禁「你知道嗎」「大家好」等暖場開場 | 有閘門 | produce_batch.py:3421 `_PREAMBLE_OPENERS`／3430 `_is_preamble_open` | `_PREAMBLE_OPENERS=("你知道嗎","你有沒有想過",…,"大家好","各位好","說到","講到",…)`;判斷式**分兩支**(3438-3442):`if len(p) <= 2: if t.startswith(p): return True` / `elif t.startswith(p) or p in t[:10]: return True` —— ≤2 字的短詞(說到/講到)**只認開頭**,不做前 10 字子字串比對,註解說明是為了避免中段鉤子句誤中 | 命中→`_weak_hook`回True→計入6020-6029while | fail-open(靜默);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-18 | 第一句不得與段落1旁白逐字重複 | 只在prompt層 | — | 全檔查無「與段落1本身比對」的函式；`_body_too_similar`只比對「近期已發布其它片」，不是本片內部段落互比 | — | 無閘門 |
| HOOK-19 | 開場前兩句每句需完整句≥15字 | 只在prompt層 | — | 唯一相似函式`_long_fragmented_hook`(5486)docstring明載「長片才有碎句檢查」，其判準是12字/40字3斷點密度法，且**只掛在_long_bad/_uncontroversial_bad**，未掛Shorts重生迴圈 | — | 無閘門(Shorts無此檢查，長片有但邏輯不同、不是逐句15字判準) |
| HOOK-20 | 數字須長在句子裡，不可自成一句 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-21 | 禁中文數字+阿拉伯數字重複講同一組 | 只在prompt層 | — | grep全檔「中文數字」「阿拉伯數字」僅命中prompt文字(1164行)本身，無比對邏輯 | — | 無閘門 |
| HOOK-22 | 禁把新聞事件原封不動當開場句 | 部分覆蓋 | produce_batch.py:3480(`_weak_hook`內) | `if sc.is_liquidation_hijack(head): _compare=_r.search(r"vs\|VS\|你猜\|差[0-9一二三四五六七八九十]\|[0-9一二三四五六七八九十]倍", head); if not has_you and not _compare: return True` | 命中→計入6020-6029while | fail-open(靜默)；**只認`is_liquidation_hijack`定義的加密爆倉/清算類新聞**，其他類型時事新聞裸貼開場不觸發;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-23 | 時事開場須轉譯成反直覺對比 | 部分覆蓋 | 同HOOK-22 | 同上 | 同上 | fail-open(靜默)；同HOOK-22 的加密新聞限定範圍，且只驗證「有無vs/差/倍/你猜字樣」不驗證翻譯品質;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-24 | 痛點句後插「反轉/加碼懸念」承接語 | 有閘門 | produce_batch.py:3520 `_weak_mid_hook` | `window=t[int(n*?):int(n*?)]`(11-20%字元窗) `return not any(m in window for m in _MID_TWIST_MARKERS)` | True→計入6020-6029while(_hk<2) | fail-open(靜默);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-25 | 開頭丟謎題，答案留到最後才揭曉 | 有閘門 | produce_batch.py:3537 `_reveals_too_early` | `cut=int(len(t)*0.30); head=t[:cut]; return any(m in head for m in _REVEAL_MARKERS)` | True→計入6020-6029while | fail-open(靜默);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-26 | 揭曉句型不得出現在前30% | 有閘門 | 同HOOK-25 | 同上 | 同上 | fail-open(靜默)(與HOOK-25同一函式/同一違規判定);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-27 | 全程快節奏不鋪陳 | 有閘門 | produce_batch.py:3489 `_impact_density` | `max_sec_per_beat=7.0`；以「字數/5」估秒數、標點當節拍算間距，超門檻回True | True→計入6020-6029while | fail-open(靜默)；只是節奏密度代理指標，非直接判「有沒有鋪陳繞圈」;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-28 | 結尾反轉/重磅數字收+留言鉤CTA | 只在prompt層 | — | 無檢查「結尾內容類型」的函式；`_ending_too_similar`只查跟近期片的相似度，不查「有沒有反轉/CTA」這個結構要素本身 | — | 無閘門 |
| HOOK-29 | 留言鉤每支換句，禁固定套用同句 | 部分覆蓋 | produce_batch.py:765 `_ending_too_similar` | `def _ending_too_similar(text, recent, thr=0.72, tail_chars=100)` | 命中→計入6020-6029while；重生2次仍中→6044-6046只log放行 | fail-open(重生耗盡後放行)；比對對象是「近期已發布片」不是「留言鉤本身有沒有換句」，且只掃尾100字 |
| HOOK-30 | 訂閱鉤須明講「訂閱」二字 | 有閘門 | produce_batch.py:5923 `_ensure_sub_hook`／5909 `_SUB_CUES` | `if any(c in tail for c in _cues): return text` (`_SUB_CUES` 預設含"訂閱")；未命中則先跑`_CTA_WORD_FIXES`(追蹤→訂閱)、仍未命中則`return text.rstrip()+" "+_pool[i]`強制附加含「訂閱」字樣句子 | 呼叫端 produce_batch.py:6372/6375，確定性補丁，結果保證含「訂閱」二字 | fail-closed（機制:確定性補丁，非拒絕重生——違規版本不會流出，因為函式直接改寫掉） |
| HOOK-31 | 訂閱理由禁「演算法不會再推你」威脅語 | 只在prompt層 | — | `_ensure_sub_hook`/`_SUB_CUES`只驗證是否含「訂閱」二字，不驗證訂閱理由的措辭/語氣本身 | — | 無閘門 |
| HOOK-32 | 訂閱鉤每支換措辭 | 只在prompt層 | — | 無獨立「訂閱鉤本身近期重複度」檢查(不同於HOOK-29的結尾整體檢查) | — | 無閘門 |
| HOOK-33 | 片尾連看鉤指向同類主題另一支 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-34 | 具體數字戳破直覺，個人具體情境 | 部分覆蓋 | produce_batch.py:3446 `_weak_hook` | 同HOOK-14 `has_num`/`has_conf` | 同HOOK-14 | fail-open(靜默)；只驗證「有數字或衝突詞」，不驗證「是否個人具體情境」;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-35 | 開頭禁丟派網設定/參數/小眾術語 | 只在prompt層 | — | `_CRYPTO_FAM`(5776)只用在`_long_opening_bad`(長片開場vs標題錯位檢查)，未掛在Shorts的`_weak_hook`/6020-6029迴圈 | — | 無閘門(Shorts側) |
| HOOK-36 | 懸念缺口，答案壓到最後一秒 | 有閘門 | 同HOOK-25 `_reveals_too_early` | 同上 | 同上 | fail-open(靜默)(與HOOK-25/26同一函式);🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-37 | 第二人稱「你的/你猜/你以為」互動 | 部分覆蓋 | produce_batch.py:3413 `_has_second_person`(經`_weak_hook`調用) | `return ("你" in t) or ("妳" in t)`；但只在`(not has_conf)`時才生效(`weak_orig=(not has_conf) and ((not has_num) or (not has_you))`) | 缺你/妳且缺數字/衝突詞→計入while | fail-open(靜默)；OR邏輯下，只要有衝突詞就完全不檢查有無第二人稱，覆蓋不完整;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-38 | 具體可想像情境，禁抽象術語/公式名 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-39 | loop結尾：最後一句呼應開頭第一句 | 有閘門 | produce_batch.py:5844 `_ensure_loop_hook` | `if check_key in tail: return text` (未呼應)否則 `return text.rstrip()+" "+_LOOP_HOOK_POOL[i].format(hook=hook)` | 呼叫端6368(僅`kind=="short"`且非EP/非tw_lab)，確定性補丁強制附加呼應句 | fail-closed（機制:確定性補丁，非拒絕重生） |
| HOOK-40 | 至少一句對仗/排比金句 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-41 | 目標長度30-45秒/完播率門檻65%·50% | 只在prompt層 | — | 全檔grep長度/秒數判準，Shorts側無`len(voice_text)`或估時長度閘門(`_long_underlength`只掛長片) | — | 無閘門(完播率門檻是事後Analytics回灌診斷用的統計依據，非產出時擋輸出的判準) |
| HOOK-42 | 首選題材清單(定投生活化等) | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-43 | 死亡題材(抽象公式/純蹭新聞等)別碰 | 只在prompt層 | — | 無主題黑名單檢查函式比對這些詞 | — | 無閘門 |
| HOOK-44 | 5大鉤子結構擇一開場 | 只在prompt層 | — | — | — | 無閘門 |
| HOOK-45 | 標題=可搜尋關鍵字 | 只在prompt層 | — | `_title_weak`(3390)只判斷是否有數字(`_TF_A`)+損失框/對比/生活隱喻詞(`_TF_B/C/D`)+`sc.is_banned_skeleton`，不判斷「可搜尋性/是否為觀眾真的會搜的詞」 | — | 無閘門 |
| HOOK-46 | VVSA≥70%鐵律，第一句必須最強 | 有閘門 | 同HOOK-16 `_weak_hook`/`_is_preamble_open` | 同上 | 同上 | fail-open(靜默)；此規則與HOOK-16本質同一失敗長相，共用同一閘門;🔴**改判(靜默)**:`_weak_hook`/`_impact_density`/`_weak_mid_hook`/`_reveals_too_early` 這一類在重生用盡後**不寫任何 log**(6044-6049 只涵蓋 `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`),見第三節(1) |
| HOOK-47 | 誠信不變：不編造損益/不保證收益/不喊單 | 部分覆蓋 | daily_publish.py:1398 `audit_video.audit(slug)`（內含audit_video.py:445/450 `find_banned_hits`/`find_fabricated_stats`） | `ok, reasons = audit_video.audit(slug)` `if not ok: quarantined.append(...); continue`(daily_publish.py:1399-1402) | 命中→加入quarantined，`continue`跳過，不上傳 | fail-closed，但**僅發布端**；`find_candidates`(daily_publish.py:622)`glob("S_*.mp4")+glob("L_*.mp4")`證實Shorts與長片同一份終審，無kind區分。**產出端(6020-6049)沒有對應呼叫**——`_long_opening_bad`的禁語/編造統計委外檢查只掛在`_long_bad`/`_uncontroversial_bad`，Shorts產出當下完全沒過這關，得等到發布前才被攔 |
| HOOK-48 | 講白話去術語，第一次出現當場解釋 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-01 | 前30秒禁專有名詞(卡瑪比率/夏普等) | 只在prompt層 | — | grep「卡瑪比率」「夏普」「標準差」「波動率」「貝塔」「CAGR」全檔僅命中prompt文字(1233行)本身，無比對函式 | — | 無閘門 |
| LONG-02 | 前30秒禁重述鉤子已講數字 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-03 | 前30秒禁「接續上一段/承上/前面提到」接縫語 | 有閘門 | produce_batch.py:5061-5070 `_META_RE` | `_META_RE=re.compile(r"(講完開場鉤子…｜接續上一?段…｜承上…｜如前所述…｜前面提到…｜上一段…)")` 經 `_clean_narration`(5653) `t=_META_RE.sub("",t)` | 呼叫端6430`d["voice_text"]=_clean_narration(...)`，命中字串被**直接剝除**，不會出現在最終稿 | fail-closed（機制:確定性清洗，於gate迴圈6020-6376**之後**才跑，gate本身從未看過「清洗前」版本，不算傳統意義的擋輸出） |
| LONG-04 | 一句話最多一數字；開場兩句不超第3個百分比 | 只在prompt層 | — | 唯一相關函式`_long_no_early_contrast`(5174)docstring明載「⛔實測反向,故意不接進_long_bad」，未被任何呼叫端引用(全檔grep`_long_no_early_contrast\(`僅命中定義處一次) | — | 無閘門(有一支被作者主動棄用的死碼，不算生效閘門) |
| LONG-05 | 開場最好是可代入的具體比較 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-06 | 風險提醒只出現一次於片尾，正文禁散撒hedging | 有閘門 | produce_batch.py:5782 `_long_opening_bad`(5792-5797) | `_hn=sum(_mid.count(h) for h in _HEDGE_BOILER); if _hn>1: return f"正文散撒風險hedging({_hn}句...)"` | 呼叫端6083(`_long_bad`)/6292(`_uncontroversial_bad`)；回原因字串進while，重生用盡後`return None`不產出 | fail-closed（兩路徑皆是，因為此原因字串「正文散撒風險hedging」**不在**6335-6336白名單`("鉤子後仍在鋪陳","同句數字自相矛盾")`內，親自讀6335行確認） |
| LONG-07 | 說教總結句禁，收束用具體數字對比 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-08 | 禁空泛「一定要看到最後」 | 有閘門 | produce_batch.py:5076-5077 `_PLEA_RE` | `_PLEA_RE=re.compile(r"[^。！？!?\n]{0,30}(?:一定要\|記得\|千萬要\|千萬別錯過)[^。！？!?\n]{0,10}(?:看到最後\|看到結尾\|看完(?:這支)?影片\|別走開)[^。！？!?\n]{0,15}[。！？!?]?")` 經`_clean_narration`(5654)`t=_PLEA_RE.sub("",t)` | 呼叫端6430，命中句子被直接剝除 | fail-closed（機制:確定性清洗，gate迴圈之後才跑；且pattern本身錨定「空泛版」，帶具體payoff的版本不受影響，與規則原意精確對齊） |
| LONG-09 | 比喻每片最多一個，不放段落開頭 | 只在prompt層 | — | `_self_repeated_metaphor`(1002)存在且有能力偵測「片內同一比喻重複」，但**只掛在Shorts迴圈**(6028)；長片迴圈(6163-6165: `_ending_too_similar`/`_body_too_similar`/`_notorious_metaphor_hit`)**明確不含**`_self_repeated_metaphor`調用 | — | 無閘門(長片側)——有功能相符的函式但未被接上長片路徑，是可用而未用的缺口 |
| LONG-10 | 猶豫塞道理還是數字時永遠塞數字 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-11 | 禁「今天我將/我們將帶你/看完這支影片」預告句 | 部分覆蓋 | produce_batch.py:5448 `_long_preamble` | `pats=(r"今天[,，]?\s*我(?:將\|要\|會)", r"我們將(?:帶你\|深入\|用)", r"看完這支影片", …); return sum(1 for p in pats if _re.search(p, zone)) >= 2`(`zone=voice_text[60:300]`) | 呼叫端經`_long_opening_bad`→6083/6292，回「鉤子後仍在鋪陳」，見GATE-05路徑相依規則 | 路徑相依：A4(`_long_bad`)路徑fail-closed；checkup(`_uncontroversial_bad`)路徑重生2次仍中→命中6335白名單→fail-open(重生耗盡後放行)。**且需≥2種樣式同時命中，只違反一次不觸發；只掃[60:300]字元區間，該區間外的違規完全抓不到** |
| LONG-12 | 禁頻道自我介紹「量化阿森頻道的目標是」 | 部分覆蓋 | 同LONG-11 `_long_preamble`(含pattern`r"頻道的目標"`/`r"量化阿森(?:頻道\|就用\|將用)"`/`r"本頻道(?:用\|將\|會)"`) | 同上 | 同上 | 同LONG-11：路徑相依+需≥2命中+位置限定[60:300] |
| LONG-13 | 禁「首先，我們來認識一下這次的主角」過場句 | 部分覆蓋 | 同LONG-11 `_long_preamble`(含pattern`r"首先[,，]\s*我們來(?:認識\|看看\|了解)"`) | 同上 | 同上 | 同LONG-11：路徑相依+需≥2命中+位置限定[60:300] |
| LONG-14 | 預告用具體誘餌放鉤子裡，不另開一句 | 只在prompt層 | — | — | — | 無閘門 |
| LONG-15 | 句子出現0050對照數字須同句寫出期間(規則ⓜ-1) | **部分覆蓋**(🔴主對話推翻子表「只在prompt層」) | produce_batch.py:5287 `_long_mixed_period` | 入口先要求句中出現觸發詞 `同期|同時期|同一?段?(?:期間|時間|時期)|相同(?:期間|時間|時期)|同樣的(?:時間|期間)|這段(?:期間|時間)`,再要求出現 `0050|零零五零|台灣50…`;兩者皆中才進入判定 | 呼叫端 6089/6254/6341,回「期間偷換…講0050對照時必須標明年數」;不在 6335/6356 白名單→重生用盡 `return None` | **fail-closed(但射程遠窄於規則)**:①沒有觸發詞的違規句判斷式連看都不看 ②年數改看「本句+前後各一句」視窗(2026-08-30),而規則ⓜ-1 字面寫「年數寫在前一句不算」⇒ **prompt 與閘門已不同義**,見第四節 A |
| LONG-16 | 講20年個股數字整段用20年,不提0050 | **部分覆蓋**(🔴主對話推翻子表「只在prompt層」) | produce_batch.py:5287 `_long_mixed_period` 第①層(事實錨定) | 視窗內是否把 long_horizon 的個股報酬與 three_way 的 0050 報酬並列 | 同 LONG-15 | **fail-closed 但實質空轉**:該函式註解自陳「這道最精準的判準在真實旁白上幾乎從來沒生效過」(只認阿拉伯數字,旁白為 TTS 幾乎都寫中文)⇒ 實際只有粗規則②在跑 |
| LONG-17 | 20年/10年兩組要分開講，不可混用 | 有閘門 | produce_batch.py:5287 `_long_mixed_period` | 依gates_index.md GATE-08：查旁白對比句是否「混用不同期間的兩個數字當同期」 | 呼叫端6089(`_long_bad`)/6254(`_uncontroversial_bad`)，回「期間偷換」；不在6335/6356白名單→重生用盡`return None` | fail-closed(三處呼叫端一致，gates_index.md已核對並spot-check通過，見本檔spot-check第1項複驗) |
| ABB-01 | 鉤子(前兩句)講完後下一句須直接進內容本身 | 有閘門 | produce_batch.py:5448 `_long_preamble`(經`_long_opening_bad`回「鉤子後仍在鋪陳」) | 同LONG-11判斷式 | 呼叫端6083/6292；回「鉤子後仍在鋪陳」 | 路徑相依：A4路徑fail-closed；checkup路徑重生2次仍中→命中6335白名單`_why2.startswith("鉤子後仍在鋪陳")`→fail-open(重生耗盡後放行)，親讀6335-6352確認 |
| ABB-02 | 具體禁「今天我將/我們將帶你體檢」「看完這支影片你會知道」 | 部分覆蓋 | 同ABB-01/LONG-11 `_long_preamble` | 同上 | 同上 | 同ABB-01：路徑相依+需≥2命中+位置限定 |
| ABB-03 | 具體禁「量化阿森頻道的目標是」「本頻道用資料」 | 部分覆蓋 | 同上(含`r"頻道的目標"`/`r"本頻道(?:用\|將\|會)"`) | 同上 | 同上 | 同ABB-01：路徑相依+需≥2命中+位置限定 |
| ABB-04 | 具體禁「首先，我們來認識一下這次的主角」 | 部分覆蓋 | 同上(含`r"首先[,，]\s*我們來(?:認識\|看看\|了解)"`) | 同上 | 同上 | 同ABB-01：路徑相依+需≥2命中+位置限定 |
| ABB-05 | 判準：第3~6句拿掉後資訊不減=該刪的鋪陳 | 只在prompt層 | — | 這是給LLM寫作時自我檢查用的「拿掉測試」，全檔無任何函式做「刪除第N句後比較資訊量」這種操作 | — | 無閘門 |

### 5-2 其餘十個常數(85 條)

⚠️ `TWSTK-03~07` 是一列涵蓋 5 條規則(五種必爆骨架擇一),計數時算 5 條。

#### EP_RULES(9)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| EP-01 | 誠實反差鉤開場,標明是回測、別假稱真錢實盤 | 只在prompt層 | — | 全檔 grep「真錢實盤」「假稱」零命中除 prompt 常數本身 | — | — |
| EP-02 | 前1.5秒必含時間/金錢錨(Day X/本金X萬) | 只在prompt層 | — | 無對應函式;`_bump_ep`(produce_batch.py:5001)只遞增集數計數器,不驗內容 | — | — |
| EP-03 | 世界觀一致:本金/天數/餘額前後連貫 | 只在prompt層 | — | 查無任何跨集一致性比對函式(`_bump_ep` 只寫 season/current_ep,不讀前集金額比對本集) | — | — |
| EP-04 | 結尾續集鉤(cliffhanger)+二選一留言題 | 只在prompt層 | — | 查無 | — | — |
| EP-05 | 訂閱追更鉤合併一句,損失綁「看不到結局」,禁演算法語 | 部分覆蓋 | produce_batch.py:6375 | `else: d["voice_text"] = _ensure_sub_hook(d.get("voice_text",""), d.get("title",""))`(is_ep 走此 else 分支,非 tw_lab 專用池) | 尾段140字內無「訂閱」→補一句 `_SUB_HOOK_POOL` 固定句(含「訂閱」二字) | fail-closed(對「訂閱」二字這件事;是確定性補寫非重生) |
| 備註 | 只保證「訂閱」二字存在,不驗是否合併成一句、是否誤用「演算法不會再推你」語氣、是否綁「看不到結局」——這些都可能違規而不被攔 | | | | | |
| EP-06 | 開頭3秒半句回顧上一集結尾懸念 | 只在prompt層 | — | 查無 | — | — |
| EP-07 | 系列導流(播放清單)不寫進結尾旁白 | 只在prompt層 | — | 查無禁詞/禁片語檢查(非 BANNED 清單項目) | — | — |
| EP-08 | 用回測進度數字當骨架,旁白務必念出這些數字 | 只在prompt層 | — | 查無 | — | — |
| EP-09 | 季線連載感:每集一句點出本季賭注/累計狀態 | 只在prompt層 | — | 查無 | — | — |

#### DEBUNK_RULES(6)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| DEBUNK-01 | 定位:只拆數字/方法,不人身攻擊/不碰瓷/不反過來喊單 | 部分覆蓋 | audit_video.py:26 BANNED(GATE-06) | `BANNED=["保證賺",...,"穩定報酬率"]`;若拆穿內容反過來寫「保證收益」等會被攔,但「喊單/報明牌/目標價」「人身攻擊」字樣本身不在 BANNED 清單 | 命中→`_long_opening_bad`回原因→fail-closed(重生);發布端`audit()`reasons非空→不發布 | fail-closed(僅涵蓋 BANNED 詞族) |
| DEBUNK-02 | 命名格式:短片《拆穿》\|{神話};長片《拆穿》EP{n}\|{神話}——真回測三刀 | 只在prompt層 | — | grep「《拆穿》」全檔僅出現在 prompt 常數(1313-1315)與註解,無任何函式檢查產出標題是否含此前綴 | — | — |
| DEBUNK-03 | 開場逐字骨架:①點名神話+數字②誠實反差鉤 | 只在prompt層 | — | 查無 | — | — |
| DEBUNK-04 | 三幕結構:神話→真回測三刀→避雷結論 | 只在prompt層 | — | 查無段落結構驗證(GATE-01是長度/GATE-04是灌水,均非結構驗證) | — | — |
| DEBUNK-05 | 結尾:留言鉤+訂閱追更鉤+連看鉤,可loop回開頭 | 部分覆蓋 | produce_batch.py:6375 | 同 EP-05,`_ensure_sub_hook` 只保證「訂閱」二字 | 尾段無「訂閱」→補一句固定池句 | fail-closed(僅「訂閱」二字) |
| DEBUNK-06 | 誠信:只拆對手公開數字,自己回測不誇大/不保證/不喊單 | 部分覆蓋 | audit_video.py:26/86(GATE-06/07) | 同 DEBUNK-01 的 BANNED 詞族 + GATE-07 `find_fabricated_stats` 攔「機率/勝率/夏普」等編造統計句(無假設語境時) | 命中→fail-closed(產製端重生用盡不輸出;發布端不發布) | fail-closed(詞族/統計句型窄,不涵蓋「誇大」泛稱) |

#### CURRICULUM_RULES(6)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| CURRIC-01 | 定位:絕不當聖杯,教怎麼看→回測驗證→揭露何時會騙你 | 只在prompt層 | — | 查無 | — | — |
| CURRIC-02 | 命名:標題含指標/策略名+可搜尋詞 | 只在prompt層 | — | `_title_weak`(GATE-19)只驗贏家公式(損失框架/對比懸念),不驗是否含指標名 | — | — |
| CURRIC-03 | 開場前3秒:點名這集教什麼+反差鉤 | 只在prompt層 | — | 查無 | — | — |
| CURRIC-04 | 三段結構:①教學②回測驗證③陷阱 | 只在prompt層 | — | 查無結構驗證 | — | — |
| CURRIC-05 | 誠信:教學用語/公式正確;回測數字用示意/假設不暗示真實獲利 | 部分覆蓋 | audit_video.py:26/86(GATE-06/07) | 同上,BANNED詞族+GATE-07機率/勝率型編造統計句攔截;「公式正確」本身無任何驗證(產線不核對指標公式數學正確性) | 命中→fail-closed | fail-closed(僅涵蓋誇大語/編造統計句,不涵蓋公式正確性) |
| CURRIC-06 | 結尾:留言鉤+訂閱追更鉤+連看鉤 | 部分覆蓋 | produce_batch.py:6375 | 同 EP-05,只保證「訂閱」二字 | 尾段無「訂閱」→補句 | fail-closed(僅「訂閱」二字) |

#### TW_STOCK_RULES(11)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| TWSTK-01 | 定位:只做數據分析,絕不喊單/報明牌/喊目標價/保證會漲 | 部分覆蓋 | audit_video.py:26(GATE-06) | BANNED 清單含「保證賺/穩賺/一定賺」等,但「喊單」「報明牌」「目標價」「保證會漲」字面不在清單內(清單是誇大保證型,非投顧建議型禁語) | 命中 BANNED 詞→fail-closed | fail-closed(僅涵蓋「保證/穩賺」詞族,喊單/明牌/目標價完全未被字面攔截) |
| TWSTK-02 | 開場前3秒:台股具體神話數字+恐懼/反直覺,0開場白 | 只在prompt層 | — | 查無「開場白」/「自我介紹」偵測函式 | — | — |
| TWSTK-03~07 | 五種必爆骨架(回測打臉/爆倉鬼故事/神話三刀拆/反直覺對比/陷阱揭露)擇一 | 只在prompt層 | — | 查無骨架分類/擇一驗證函式 | — | — |
| TWSTK-08 | 數據鐵律:一律用台股歷史回測說話,絕不喊「會漲/快買/目標價X元」 | 部分覆蓋 | audit_video.py:26(GATE-06) | 同 TWSTK-01,「會漲/快買/目標價」字面不在 BANNED 清單 | 僅「保證/穩賺」族命中才攔 | fail-closed(窄) |
| TWSTK-09 | 在地語彙自然帶入(大盤/0050/存股/除權息) | 只在prompt層 | — | 查無關鍵詞覆蓋率檢查 | — | — |
| TWSTK-10 | 避雷收尾+loop呼應開頭+訂閱鉤(留言鉤+追更鉤兩句都要) | 部分覆蓋 | produce_batch.py:6375 | `_ensure_sub_hook` 只保證「訂閱」二字;loop呼應由 `_ensure_loop_hook`(6367)補,但該行排除 `_is_ep`/`_is_tw_lab`,對一般 tw_stock 仍會跑到 | 尾段無「訂閱」→補句;無 loop 呼應→`_ensure_loop_hook` 補一句呼應開頭 | fail-closed(僅「訂閱」二字與 loop 呼應句,不驗「留言鉤+追更鉤兩句都要」的雙句結構) |
| TWSTK-11 | 誠信:回測標「歷史回測非未來保證」;不編造精確數字/不保證/不喊單/不報明牌 | 部分覆蓋 | audit_video.py:26/86(GATE-06/07);daily_publish.py:563(GATE-21) | BANNED詞族+GATE-07編造統計句+GATE-21發布前對績效數字做事實庫溯源(`fact_source_guard.check_slug`,查無來源→擋) | GATE-06/07命中→fail-closed(產製/發布雙層);GATE-21命中→daily_publish候選移除,不發布 | fail-closed(「不編造精確數字」由GATE-21較廣覆蓋;「不保證/喊單/報明牌」字面仍只有保證族被攔;「標歷史回測非未來保證」免責語本身無強制檢查) |

#### TW_STOCK_CHECKUP_RULES(20) ⚠️誠信類·總督導最在意

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| CHECKUP-01 | 只陳述公開數據,不推薦、不喊單——本系列生死線 | 部分覆蓋 | audit_video.py:26(GATE-06) | BANNED詞族攔「保證/穩賺」等,但「推薦性語句」「喊單」字面未列入,且系列自身特有的隱晦推薦用語(如「現在便宜」見CHECKUP-19)完全未攔 | 命中BANNED詞→fail-closed | fail-closed(詞族窄,對本條核心「不推薦」幾乎無覆蓋) |
| CHECKUP-02 | 片頭帶系列名不帶集數;標題/旁白都不得出現EP幾/第幾集 | 部分覆蓋 | daily_publish.py:430-461 `_apply_checkup_ep`/`_strip_checkup_ep` | 先 `_strip_checkup_ep(title)` 剝掉產製端可能殘留的集數字樣,再由發布時依已發布集數 max+1 重新掛號、統一格式 | 產製端標題若含集數→發布時被剝除重寫,不阻擋產出只改標題 | fail-closed(僅**標題**欄位,決定性覆寫);旁白(voice_text)內「第幾集」字樣完全無對應檢查——若LLM在旁白裡講出「這是第3集」不會被攔 |
| CHECKUP-03 | 產業分類用本次注入的FinMind官方分類(非猜測) | 只在prompt層 | — | `_checkup_context`(produce_batch.py:1966,1974)只是把FinMind分類組成prompt文字注入,無任何比對LLM最終產出的產業敘述是否採用注入值 | — | — |
| CHECKUP-04 | 一句話講清楚公司靠賣什麼賺錢 | 只在prompt層 | — | 查無 | — | — |
| CHECKUP-05 | 界線:講做什麼不講好不好,不下「護城河很深」等無憑據評語,不編造產品線 | 只在prompt層 | — | BANNED清單(audit_video.py:26)不含「護城河」字樣;全檔grep「護城河」僅出現在prompt常數與註解,無檢測函式 | — | — |
| CHECKUP-06 | 基本面四項數據:有這項才講,沒有就跳過或老實說沒有 | 只在prompt層 | — | `_checkup_context`只組「【本檔沒有資料的項目】」提示文字,無回頭核對旁白是否真的跳過了這些項目 | — | — |
| CHECKUP-07 | 【本檔沒有資料的項目】列出的每一項,一個數字都不准給 | 只在prompt層 | — | 同上,無post-hoc核對;GATE-21(fact_source_guard)是查「數字在事實庫查無來源」,不是查「數字屬於本檔被標記無資料的項目」——邏輯不同,不能替代 | — | — |
| CHECKUP-08 | 價格體檢沿用TW_STOCK_RULES持有體驗數據(20年報酬/回撤/套牢/腰斬) | 只在prompt層 | — | 查無驗證旁白是否包含這四項持有體驗數據的函式 | — | — |
| CHECKUP-09 | 估值位置只講「本益比在近10年區間第幾百分位」 | 只在prompt層 | — | `_checkup_summary_line`(1720)是**確定性收束句生成器**,只在補寫收束句時用「第P百分位」措辭,不檢查LLM自己寫的其餘旁白是否用了百分位以外的講法 | — | — |
| CHECKUP-10 | 絕對禁止接著評論「現在貴/便宜/該不該買/是不是好買點」 | 只在prompt層 | — | grep「現在貴」「現在便宜」「好買點」「該不該買」「處於高檔」「相對便宜」全檔僅出現在prompt常數(1394/1414)與`_checkup_summary_line`docstring,**零檢測邏輯**;BANNED清單不含這些詞 | — | — 🔴本系列生死線之一,零程式碼防線 |
| CHECKUP-11 | 誠實結尾三件事**順序**:風險揭露→留言互動題→下集點名 | 部分覆蓋 | produce_batch.py:1797 `_checkup_finalize` | 只補「留言」關鍵字缺失(1828-1829)與「下集點名」缺失(1830-1833),**完全不檢查/不補「風險揭露」**,也不驗證三者出現的先後順序 | 缺留言→補「留言告訴我…」;缺下集點名→補「下一集…」;若LLM寫的順序是 c→b→a,本函式不糾正 | fail-open(有聲,僅log,不擋)——且「順序」本身完全未被檢查 |
| CHECKUP-12 | a.風險揭露:數據陳述不構成投資建議 | 部分覆蓋 | GATE-25 `audit_video.audit`;produce_batch.py:3106/6534 | `if "風險" not in _body and "不構成投資建議" not in _body: _body += "...不構成投資建議。"`(3106-3107,寫description);6534同款補在.md檔 | 缺風險聲明→確定性補在**description/.md**;`audit_video.audit`判「缺風險聲明」FAIL→daily_publish不發布 | fail-closed(但只驗**description欄位**,voice_text旁白本身是否講了風險揭露沒有對應檢查——若旁白漏講但description有,仍會通過) |
| CHECKUP-13 | b.留言互動題:問觀眾對數據看法/最意外哪個數字 | 部分覆蓋 | produce_batch.py:1828-1829(`_checkup_finalize`) | `if "留言" not in v: tail_bits.append("留言告訴我，這集哪個數字最讓你意外。")` | 缺「留言」關鍵字→補固定句(內容恰好符合規則字面) | fail-closed(對「留言」二字);但只查關鍵字存在,不查LLM自己寫的留言題是否真的「問數據看法」 |
| CHECKUP-14 | c.下集點名:帶出下一檔,不劇透下一集具體數字 | 部分覆蓋 | produce_batch.py:1810-1821, 1830-1833(`_checkup_finalize`) | 先拆掉「有下集措辭但沒點到真下集標的」的假預告句(1810-1821),再補`f"下一集個股體檢，輪到{nx}上體檢台"`(若缺) | 假預告句→刪除;缺點名→補句 | fail-closed(僅「點名正確下一檔」這件事);「不劇透下一集具體數字」完全無對應檢查——LLM若在點名句外洩露下集數字不會被攔 |
| CHECKUP-15 | 反模板a:開場與敘事主軸由本檔最異常數據決定 | 只在prompt層 | — | GATE-15/16(`_ending_too_similar`/`_notorious_metaphor_hit`)定義在`kind=="long" and not topic_override`分支(6058起),而個股體檢**永遠有topic_override**(見5754-5768註解:「個股體檢永遠有topic_override→佔產出93%的主力產品整組跳過這五道」)——閘門存在但對本系列完全跳過不執行 | — | — (產製端該分支對checkup不執行,非「命中未攔」而是「根本沒跑」) |
| CHECKUP-16 | 反模板b:各段深淺比例隨主軸調整,不逐項唸稿 | 只在prompt層 | — | 查無段落比例/清單體偵測函式 | — | — |
| CHECKUP-17 | 反模板c:開場句式不得與近期片雷同 | 只在prompt層 | — | 同CHECKUP-15,`_ending_too_similar`/`_body_too_similar`(GATE-15)本應是最接近的比對函式,但同樣因`not topic_override`條件而對checkup完全不執行(93%產出跳過) | — | — |
| CHECKUP-18 | 財報數字一律用本次注入真實數據,不准自己換算估計 | 有閘門 | GATE-02 `_long_corrupt_number` | produce_batch.py:~3630 `if not fk.startswith("checkup_"): return ""`(僅checkup生效)+同句內部數字一致性檢查 | 命中→原因字串「同句數字自相矛盾」→列入`_uncontroversial_bad`→重生2次;**仍命中時落在6335-6336白名單**(`_why2.startswith("同句數字自相矛盾")`)→6349寫一行警告後**放行** | 🔴**fail-open(重生耗盡後放行)** —— 覆核翻案:初稿判 fail-closed 是錯的,親讀6335-6352確認白名單含本原因字串;且6349那行log把原因寫死成「鉤子後仍在鋪陳」⇒**放行紀錄掛錯名字**(見第三節(6))。另該函式自身docstring承認判準是「同句內部一致性」啟發式,非100%精確溯源到注入數據 |
| CHECKUP-19 | 「介紹≠推薦」鐵律:不得出現推薦性語句,即使隱晦暗示 | 部分覆蓋 | audit_video.py:26(GATE-06) | BANNED詞族僅「保證/穩賺」型,「隱晦暗示」推薦(如「值得留意」「表現亮眼」)完全不在清單內 | 命中BANNED詞→fail-closed | fail-closed(對本條核心「隱晦暗示」幾乎零覆蓋——這正是本條最容易翻車也最沒被抓到的地方) |
| CHECKUP-20 | 估值位置只講百分位,不判斷貴賤,連中性暗示詞都不用 | 只在prompt層 | — | 同CHECKUP-10,零檢測邏輯,BANNED清單不含「相對便宜/處於高檔」等中性暗示詞 | — | — 🔴與CHECKUP-10同一破口,零程式碼防線 |

#### TW_LAB_RULES(9)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| TWLAB-01 | 命名與集數以【系列連貫設定】注入區塊為準 | 只在prompt層 | — | 查無post-hoc核對標題/集數是否採用注入值(不同於CHECKUP有`_apply_checkup_ep`,tw_lab無對應函式) | — | — |
| TWLAB-02 | 開場「你猜」框題:前2秒丟比較,不要前5秒就爆數字 | 只在prompt層 | — | 查無 | — | — |
| TWLAB-03 | 數字只能用【本集唯一指定實證數據】,不得混用其他標的/期間 | 有閘門 | produce_batch.py:2287 `_fix_tw_lab_title_fabrication`;:2313 `_fix_tw_lab_desc_fabrication`;call site :2957-2958 | `if not _fsg.unsourced_claims(title): return result`(title含查無憑據數字才觸發換安全標題);desc同款 | 命中→確定性換成由真實desc生成的安全標題/描述(零編造);連安全版都命中→fail-open保留原文交GATE-21把關 | fail-closed(title/description兩欄位,確定性重寫不是重生) |
| TWLAB-04 | 差距/差多少必須連原始兩數字一起講,不准裸講差值 | 部分覆蓋 | 同TWLAB-03(title/desc);旁白(voice_text)無對應 | 同上,`unsourced_claims`只掃title/description | 同上 | fail-closed(僅title/description);**voice_text旁白裸講差值完全未被此機制攔**,僅能靠發布端GATE-21(fact_source_guard.check_slug讀`.voice.txt`)兜底,但GATE-21查的是「數字有無來源」不是「裸講差值」這個特定失敗特徵 |
| TWLAB-05 | 結尾三件事都要有(留言題→訂閱鉤→下集預告),不合併敷衍 | 部分覆蓋 | produce_batch.py:6371-6373 `_ensure_sub_hook(pool=_TW_LAB_SUB_HOOK_POOL, cues=_TW_LAB_SUB_CUES)` | 只保證「訂閱」二字存在(`_TW_LAB_SUB_CUES=("訂閱",)`) | 尾140字無「訂閱」→補固定池句 | fail-closed(僅「訂閱」二字);「留言題」「下集預告」兩件事、以及「不合併敷衍」完全無對應檢查,同TWLAB-01無`_checkup_finalize`等價物 |
| TWLAB-06 | 系列訂閱鉤必須明講「訂閱」二字,不是只用「追蹤」 | 有閘門 | produce_batch.py:5909 `_TW_LAB_SUB_CUES=("訂閱",)`;:6371-6373呼叫 | `_ensure_sub_hook`尾段只認「訂閱」為通過,且`_CTA_WORD_FIXES`把「追蹤/關注」類詞面改寫成「訂閱」 | 尾段講「追蹤」未講「訂閱」→詞面替換;都沒講→補固定池句(含「訂閱」) | fail-closed(確定性改寫/補寫,規則字面與程式行為完全對應) |
| TWLAB-07 | 下集預告不洩露具體數字答案 | 只在prompt層 | — | 查無檢查下集預告句是否含數字的函式(不同於CHECKUP-14有假預告句偵測,tw_lab無對應) | — | — |
| TWLAB-08 | 誠信:歷史回測非未來保證;不喊單/報明牌/喊目標價/保證獲利 | 部分覆蓋 | audit_video.py:26(GATE-06);daily_publish.py:563(GATE-21) | BANNED詞族(保證/穩賺族)+GATE-21績效數字溯源 | 命中→fail-closed(雙層) | fail-closed(「喊單/報明牌/目標價」字面仍未被BANNED涵蓋;「歷史回測非未來保證」免責語本身無強制檢查) |
| TWLAB-09 | 不得把「你猜」包裝成保證答案或明牌 | 只在prompt層 | — | 查無 | — | — |

#### TW_LAB_LONG_RULES(9)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| TWLABL-01 | 系列連貫設定(上集回顧/本集定位/下集懸念/訂閱鉤)以注入區塊為準 | 只在prompt層 | — | 同TWLAB-01,查無post-hoc核對 | — | — |
| TWLABL-02 | 脊椎=標題比較,整支片圍繞標題主軸比較展開 | 只在prompt層 | — | 查無「內文是否圍繞標題主軸」的結構驗證(GATE-08`_long_mixed_period`是查期間混用,非主軸圍繞度) | — | — |
| TWLABL-03 | 數字硬規:具體績效數字一律只能出自注入區塊,絕不自編/換算/估 | 有閘門 | 同TWLAB-03(GATE同機制);另GATE-08`_long_mixed_period`(produce_batch.py:5287)在`_uncontroversial_bad`路徑(:6254)也對tw_lab_long生效(因`--tw-lab`CLI固定帶`topic_override`,見6759-6771,tw_lab長片必走此路徑) | `_fix_tw_lab_title/desc_fabrication`同上;GATE-08:期間偷換句型比對(僅0050相關硬編碼比較) | title/desc命中→確定性重寫;GATE-08命中→重生用盡fail-closed不輸出 | fail-closed(title/desc確定性;GATE-08真重生擋);**voice_text一般性編數字仍無title/desc那層確定性防線,僅GATE-08涵蓋0050特定期間混用**,靠GATE-21兜底但判準不同(有無來源≠有無自編換算) |
| TWLABL-04 | 差距數字只能是兩原始數字實際算出,嚴禁湊沒算過的整數 | 有閘門 | 同TWLABL-03,`_fix_tw_lab_title_fabrication` docstring明確舉例(dca_vs_allin「少賺430%」真值321.7分點) | 同上`unsourced_claims`判準 | 同上 | fail-closed(title/desc);voice_text無對應,同TWLABL-03備註 |
| TWLABL-05 | 講差多少必須連兩邊原始數字一起講,不准裸講差值 | 部分覆蓋 | 同TWLAB-04 | 同上 | 同上 | fail-closed(僅title/desc) |
| TWLABL-06 | 深段結構沿用A4 LONG_RULES,4-5個深段各一子面向,禁清單體 | 只在prompt層 | — | GATE-01(段數)/GATE-04(灌水/清單體偵測)定義在`kind=="long" and not topic_override`分支(6058);`--tw-lab`CLI(6759-6771)固定帶`topic_override=_tov`→tw_lab長片必走`_uncontroversial_bad`(6236起)簡版路徑,**不含GATE-01/GATE-04** | — | — (同CHECKUP-15/17,閘門存在但對本系列的實際production path完全跳過) |
| TWLABL-07 | 結尾三件事都要有(留言題→系列訂閱鉤→下集預告),各一句不敷衍 | 部分覆蓋 | produce_batch.py:6371-6373 | 同TWLAB-05,只保證「訂閱」二字 | 尾段無「訂閱」→補句 | fail-closed(僅「訂閱」二字) |
| TWLABL-08 | 明確出現「訂閱」二字,不是只用「追蹤」 | 有閘門 | 同TWLAB-06 | `_TW_LAB_SUB_CUES=("訂閱",)`+`_CTA_WORD_FIXES`詞面替換 | 同TWLAB-06 | fail-closed |
| TWLABL-09 | 誠信:歷史回測非未來保證;不喊單/報明牌/喊目標價/保證獲利 | 部分覆蓋 | 同TWLAB-08 | BANNED詞族+GATE-21 | 同TWLAB-08 | fail-closed(窄,同TWLAB-08備註) |

#### NO_FACTS_INTEGRITY_RULES(4) ⚠️誠信類·總督導最在意

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| NOFACT-01 | 嚴禁把任何具體精確績效數字講成「真的測過的歷史事實」 | 部分覆蓋 | audit_video.py:86(GATE-07);daily_publish.py:563(GATE-21) | GATE-07窄:只攔「機率/勝率/研究顯示/夏普/散戶統計」句型;GATE-21廣:對**所有**績效數字做事實庫溯源,查無來源即擋 | GATE-07命中→產製fail-closed;GATE-21命中→發布不上傳 | fail-closed;⚠️GATE-21的真實有效性受制頻道自有已知病灶(memory `yt-fact-guard-pool-saturation`:全域數字池數萬個數字，`unsourced_claims`對已發布稿常判「查無憑據=0個」)——**這條code層面存在，但實際攔截力可能遠低於表面**,不敢用「有閘門」蓋章 |
| NOFACT-02 | 用數字說服力一律搭配「假設/示意/打個比方/模擬情境」語氣 | 部分覆蓋 | audit_video.py:86(GATE-07) `QUOTE`元組 | `QUOTE=("號稱","宣稱",...,"假設","如果","舉例","即使","就算","假如",...)`——句子含這些hedge詞即豁免GATE-07判定 | 統計句型(機率/勝率等)無hedge詞→命中→fail-closed;有hedge詞→放行(與本規則要求方向一致) | fail-closed(但**僅對GATE-07鎖定的窄統計句型**生效,一般性能數字「23%報酬率」沒有hedge詞不會被這條攔——判準對象是GATE-07的PATS清單,不是NOFACT-02講的「任何數字」) |
| NOFACT-03 | 只講原理、不給精確數字也完全可以 | 只在prompt層 | — | 本條是許可性(permissive)條款,不存在「違反」這個失敗特徵可被偵測——沒有輸出精確數字不會觸發任何檢查,邏輯上不可能有對應閘門 | — | — (性質上不可閘門化,非漏檢) |
| NOFACT-04 | 例外:回測EP系列第一人稱模擬實驗維持語氣不算違反 | 有閘門 | produce_batch.py:6181 GATE-14呼叫式 | `if not d.get("_is_tw_stock",False) and not d.get("_is_ep",False) and not d.get("_is_flagship",False):`——`_is_ep`在此被排除,即GATE-14(`_fabricated_perf_claim_d`,捏造績效數字重生)完全不對EP系列生效 | EP系列不進入此while迴圈,不會因此被重生/放行標記 | — (排除性設計,程式碼排除條件與規則文字例外精準對應) |

#### AI_SAVINGS_RULES(5)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| AISAVE-01 | 定位:誠實比較拆穿省錢法真實成本與風險,是資訊比較不是推銷 | 只在prompt層 | — | 查無 | — | — |
| AISAVE-02 | 開場前3秒:砸痛點/反直覺,0開場白 | 只在prompt層 | — | 查無 | — | — |
| AISAVE-03 | 核心必講各方法成本+風險;第三方共享務必明講非官方可能被停用 | 只在prompt層 | — | grep「第三方」「非官方」「可能被停用」全檔僅出現於prompt常數1507-1508,無任何post-hoc關鍵字存在檢查(不同於`_ensure_sub_hook`模式,此條無對應fixer) | — | — |
| AISAVE-04 | 誠信鐵律:絕不說快去買/最划算快搶/穩賺/一定能用 | 部分覆蓋 | audit_video.py:26(GATE-06) | BANNED含「穩賺」;但「快去買」「最划算快搶」「一定能用」字面不在清單(清單無此三項) | 僅「穩賺」族命中→fail-closed | fail-closed(4個禁語中僅1個被字面涵蓋) |
| AISAVE-05 | 收尾:中性建議+訂閱鉤+導TG「打省AI領便宜用AI全攻略」 | 部分覆蓋 | produce_batch.py:6375(`_ensure_sub_hook`);:2976-2977(TG導流塊) | `_ensure_sub_hook`保證「訂閱」;`if is_ai_savings: ...`(2976-2977)另有確定性附加TG導流描述段(同`_ai_savings_desc_block`「確定性附加保證不被LLM吞」慣例,見_checkup_finalize docstring引用) | 訂閱缺→補句;TG導流段由確定性附加,不依賴LLM | fail-closed(「訂閱」二字+TG導流段兩件事都有確定性保底);「中性建議」內容本身未被驗證 |

#### AI_COMPANY_RULES(6)

| 規則id | 規則一句話 | 判定 | 閘門 | 判斷式節錄 | 違規時輸出 | fail分類 |
|---|---|---|---|---|---|---|
| AICO-01 | 開場前3秒:丟本系統真實反直覺數字(從【本系統真實數據】拿) | 只在prompt層 | — | `_system_facts`類注入函式(~1526)只組prompt文字,無檢查LLM開場是否真的採用注入數字、或是否編了新數字(GATE-21查一般績效數字溯源,而本系統真實數據是頻道營運統計,不在GATE-21掃描的backtest事實庫池內,判準對象不同) | — | — |
| AICO-02 | 核心:誠實揭運作+誠實揭限制/翻車,反造神不吹「AI全自動躺賺」 | 只在prompt層 | — | BANNED清單含「躺著就能賺」但不含「躺賺」/「AI全自動躺賺」——字面不匹配;grep全檔確認此片語僅出現在prompt常數1518 | — | — |
| AICO-03 | 誠信鐵律:不喊單/報明牌/不保證收益/不誇大頻道規模 | 部分覆蓋 | audit_video.py:26(GATE-06) | BANNED含「保證收益」,「喊單」「報明牌」「誇大頻道規模」不在清單 | 「保證收益」命中→fail-closed | fail-closed(4項中僅1項被涵蓋) |
| AICO-04 | 收尾訂閱鉤明講「訂閱」二字,別用「追蹤」 | 有閘門 | produce_batch.py:6375(`_ensure_sub_hook`,一般池`_SUB_CUES=("訂閱",)`)+`_CTA_WORD_FIXES` | `if any(c in tail for c in _cues): return text`(只認「訂閱」通過);`_CTA_WORD_FIXES`把「追蹤我/記得追蹤」等詞面改寫成「訂閱我/記得訂閱」 | 講「追蹤」未講「訂閱」→詞面替換;都沒講→補固定池句 | fail-closed(規則字面與程式判準完全對應,同TWLAB-06/TWLABL-08) |
| AICO-05 | ①只講本題故事,不硬塞無關避雷內容湊字數 | 只在prompt層 | — | 查無「本題聚焦度」偵測(GATE-15/16是雷同度/濫用比喻,非主題離題偵測) | — | — |
| AICO-06 | ②數字只能用【本系統真實數據】給的,沒給寧可不講不編造 | 只在prompt層 | — | 同AICO-01,本系統真實數據(頻道營運統計如訂閱數/產出支數)不在GATE-21的backtest事實庫池比對範圍,GATE-21查無此類數字的來源池,故無法對這類編造生效;全檔查無其他對應檢查 | — | — |

---


---

## 六、母體 B:守望端判準 32 條

範圍比原本點名的四支多。原點名:`brain_score_watch` / `brain_submit_watch` /
`llm_credit_watch` / `numerus_watch`;另外掃出同目錄的 watchdog 家族
(`brain_miner_watchdog` / `comment_watchdog` / `growth_watchdog` / `stall_watchdog` /
`local_cron_watchdog` / `render_watcher`),以及**另一個目錄家族** `D:\carson-agent\scripts\`
的四支(`quota_ceiling_watch` 15:20 / `seeding_watch` 07:00 / `narration_compliance_watch` 07:10 /
`watch_drill_regression`)—— 這一族走 **Windows 工作排程器**,不在 `deploy/crontab.txt` 裡,
⇒ **只查 crontab 會漏掉整整一族。**

**分佈:fail-closed 11 / fail-open(有聲) 10 / fail-open(靜默) 8 / 死碼 3。**


| id | 腳本 | 判準(在斷言什麼) | 定義處(檔:行) | 呼叫端(檔:行,或「無呼叫端」) | 違規時的輸出(具體) | 分類 |
|---|---|---|---|---|---|---|
| WATCH-01 | brain_score_watch.py | score/level/submitted_total/看板出現變動才推播(D3 edge-trigger,只在 changed vs base 才觸發) | quant-service/brain_alpha/brain_auto.py:795(`_sentinel`定義) | brain_auto.py:984(`track_score`內呼叫,包在 try/except)← youtube_channel/scripts/brain_score_watch.py:51(`main`呼叫`track_score`) | `_sentinel`本身拋例外時:brain_auto.py:867/989 設 `rec["notify_failed"]=True`,**無 print、無 raise、無通知**,僅內部旗標防止壞紀錄變未來 base | fail-open(靜默) |
| WATCH-02 | brain_score_watch.py | track_score 4 支 API 呼叫各自 try/except,失敗要記 `errors` 而非假造正常值 | brain_auto.py:871(`track_score`定義) | brain_score_watch.py:51(呼叫)+60-61(讀`rec['errors']`) | main() 若 `rec.get("errors")` 有內容:print(60-61行);**但這不影響 return code**,main() 固定 `return 0`(brain_score_watch.py:62) | fail-open(有聲) |
| WATCH-03 | brain_submit_watch.py | 必須能成功查到 BRAIN 提交紀錄,否則無法確認今天交了沒 | brain_submit_watch.py:85-93 | crontab.txt:853/854/855/856(排程即入口) | notify()(88行,經85-88定義的 lambda 或 `B.notify`)+ `return 1`(93行) | fail-closed |
| WATCH-04 | brain_submit_watch.py | 每日達成 TARGET=2 篇(47行) | brain_submit_watch.py:98-118 | crontab.txt:853/854/855/856 | `done<target`分支:依剩餘時間分級 notify(111行),**notify() 的回傳值(送達管道字串,失敗回 `""`)在 118 行 print 前完全沒被檢查**,無條件印「已推播」;main() 固定 `return 0`(118行,不管有沒有真的送達、也不管是否達標) | fail-open(有聲) |
| WATCH-05 | llm_credit_watch.py | 必須能查到 OpenRouter 餘額(API key 存在且 request/parse 成功) | llm_credit_watch.py:44-63(`balance`) | llm_credit_watch.py:66-96(`main`)← crontab.txt:828(`--notify`) | `bal is None`(72行):**只 print,完全沒有呼叫任何 notify/push**,`return 0`(74行) | fail-open(靜默) |
| WATCH-06 | llm_credit_watch.py | 餘額 `bal<=0`(見底) | llm_credit_watch.py:79 | 同上 | 只 print 🔴 警告,`return 0` | fail-open(有聲) |
| WATCH-07 | llm_credit_watch.py | `vids<WARN_VIDEOS(120)` 且帶 `--notify` 時要推播 | llm_credit_watch.py:81(`elif vids < WARN_VIDEOS`) | 同上 | `push()`(86行)**回傳值(bool)完全沒被檢查**,87行無條件 print「已推 ntfy」(即使 push 內部因 HTTP 非 2xx 回 False 也照樣印成功);`except Exception`(90行)才會印「[warn] 推播失敗」,無重試、無升級;main 仍 `return 0` | fail-open(有聲) |
| WATCH-08 | numerus_watch.py | 同段旁白自報金額與自己給的數字算出結果要一致(`CONTRADICTED` 且 `first_context=="PASSING"`) | numerus_watch.py:79(過濾條件) | numerus_watch.py:54-106(`main`)← crontab.txt:873 | 寫入 STUDIO/numerus_flags.json(92-99行,`save_atomic`)+ print `[ok]` 摘要(104行)。**docstring 明載「不擋任何東西、不搬任何檔、永遠 exit 0」——這是刻意設計,不是漏洞**;升級成阻斷的判準寫在 solo_saas/GATE_UPGRADE_CRITERIA.md,尚未觸發 | fail-open(有聲)(刻意設計) |
| WATCH-09 | numerus_watch.py | `solo_saas` 目錄與 `numerus`/`watch` 模組必須存在且可載入 | numerus_watch.py:55-64 | 同上 | print `[warn]`,`return 0`(64行,註解明講「只報告的東西壞掉不可以害到產線」) | fail-open(有聲) |
| WATCH-10 | numerus_watch.py | 核心掃描/寫檔不可拋例外 | numerus_watch.py:70-102(try/except 包住) | 同上 | print `[warn]`,`return 0`(101-102行)。**此 try/except 是獨立驗證員發現原本有兩種輸入會真的 exit 1(KeyError 缺 `closest`/`gate_context` 舊紀錄、FileNotFoundError 缺 STUDIO/)之後才補上的**——補上前,docstring「永遠 exit 0」那句話是假的 | fail-open(有聲) |
| WATCH-11 | brain_miner_watchdog.py | 挖礦程序必須持續在跑(用 `MINER_PATTERNS` 比對 wmic 抓到的命令列) | brain_miner_watchdog.py:41-49(`miner_running`) | brain_miner_watchdog.py:53-70(`main`)← crontab.txt:832 | 查詢例外(47行):print 到 stderr,`return True`(49行,fail-safe 視為有在跑、不重啟)。**此腳本走 `/root/yt/run.sh`(非 Windows pythonw),不受 WATCHDOG.md 記載的 stdout/stderr=None 問題影響** | fail-open(靜默) |
| WATCH-12 | brain_miner_watchdog.py | 沒偵測到挖礦程序時要重新拉起 | brain_miner_watchdog.py:60-69 | 同上 | print(66/69行)+ `Popen` 重啟並把 stdout 導向 `watchdog_restart.log`(64-67行)。**Popen 後不 verify 新程序是否真的活起來**,與 local_cron_watchdog.py 的 `VERIFY_SEC=45` 驗證機制形成對比——重啟「有沒有成功」本身零訊號 | fail-open(靜默) |
| WATCH-13 | comment_watchdog.py | 有未回覆的觀眾留言(以 `authorChannelId` 自我識別,displayName 為 fallback)要推播 | comment_watchdog.py:50(識別)+84(push 呼叫) | comment_watchdog.py:32(`main`)← crontab.txt:688 | `notify.push(...)`(84行)包在 `try/except Exception: pass`(86-87行),**push 的回傳值(bool)完全沒被檢查,例外發生時也完全沒有 print/log——是本次盤點中唯一一支推播失敗零留痕的腳本** | fail-open(靜默) |
| WATCH-14 | comment_watchdog.py | 已讀留言狀態(`STUDIO/comment_watchdog_seen.json`)必須持久化,避免每天重複推播 | comment_watchdog.py:91(`_sf.write_text`) | 同上 | **這行沒有任何 try/except 保護**,寫入失敗會直接向上拋例外、整支腳本以非零狀態碼中止(未被 main 捕捉)。這是本次盤點中唯一「未設計、意外會 fail-closed」的一格——沒有註解討論這個風險,和本專案其他地方每個 fail 分支都寫明理由的風格不一致;是否有人監看 `cron.log` 的非零退出未查證 | fail-closed(未設計/意外) |
| WATCH-15 | growth_watchdog.py | 7 日滾動觀看跌幅超過 `DECLINE_7D_PCT(-10.0%)` 或待發庫存 `<=QUEUE_FLOOR(3)` 時要出手補題+推播 | youtube_channel/scripts/growth_watchdog.py:65-108(`main`) | **無呼叫端**——crontab.txt 全文搜尋無此腳本;repo 全文搜尋(`growth_agent.py:12/123`、`topic_bank.py:332`)只找到**註解/docstring 提及**「同 growth_watchdog」,沒有任何 `import`/`subprocess`/`Popen` 實際呼叫 | 若真的被觸發:seed 6 個關鍵字題目進 topic_bank + push;但因無呼叫端,此判準**不會被執行到** | 死碼 |
| WATCH-16 | stall_watchdog.py | 7 條 `CHECKS`(短片腳本20h/短片渲染22h/長片腳本30h/長片渲染30h/YT發布30h/TikTok30h/IG40h,定義於36-49行)最後活動時間 `age_h<=thr_h` | stall_watchdog.py:99(`ok = age_h <= thr_h`) | stall_watchdog.py:91-140(`main`)← crontab.txt:557 | print `[ALERT]`(132行)+ `push(...)`(137行,回傳值未檢查)包在 try/except(138行,失敗印`[warn]`);**main() 固定 `return 0`(140行),不管有沒有 stall 都一樣**——退出碼從不反映結果,只有 push 是唯一訊號來源 | fail-open(有聲) |
| WATCH-17 | stall_watchdog.py | `audit_truncation.audit_all()` 找已發布但音檔/渲染長度不符的影片 | stall_watchdog.py:82(呼叫) | 同上 | `except Exception`(83行):print `[warn]`,soft-fail 回傳空 list,不影響其餘 CHECKS 流程 | fail-open(靜默) |
| WATCH-18 | local_cron_watchdog.py | `local_cron.lock` 心跳(mtime)必須在 `STALE_SEC=180` 秒內更新;心跳停但程序還在(`hung`) | local_cron_watchdog.py:69(STALE_SEC)+97-100(`_fresh`)+220-243(`decide`) | local_cron_watchdog.py:314-351(呼叫`decide`)——本身是 Windows 工作排程器「LocalCronWatchdog」的入口(不在 crontab.txt,WATCHDOG.md 記載,登入+每5分鐘觸發) | 寫 alert(326行)+ `_push("hung",...)`(327行)+ `return 2`(331行)。**刻意不自動重啟**(避免雙重發布) | fail-closed |
| WATCH-19 | local_cron_watchdog.py | 查詢 local_cron 程序(wmic 優先、CIM fallback)必須至少看到一行含 python 的輸出 | local_cron_watchdog.py:103(`cron_procs`) | 同上 | 兩管道都查詢失敗(238行 `return "unknown"`):**不寫 alert、不 push**,fail-safe 視為「有在跑,不動作」,`return 0`(321行) | fail-open(靜默) |
| WATCH-20 | local_cron_watchdog.py | 心跳 stale 且程序不在(`start`)→ 要重啟並確認心跳在 `VERIFY_SEC=45` 秒內恢復 | local_cron_watchdog.py:246-351 | 同上 | `Popen` 重啟 + 寫 alert + `_push("restarted",...)`(346-347行,**這條無論後面 45 秒內有沒有恢復都會送出**)→ 依恢復與否 `return 1`(343行,未恢復)或 `return 0`(351行,恢復) | fail-closed |
| WATCH-21 | local_cron_watchdog.py | `_push()` 推播要走 doubling-ladder(n=2,4,8,16…)冷卻,避免連環崩潰時炸手機 | local_cron_watchdog.py:128-198(`_push`) | 同上 | 被冷卻抑制時(未達 n=2^k 門檻):**不送 push,但仍寫 log**(非完全沉默,但對 Carson 的手機而言等同靜默——只有主動去看 log 檔的人看得到) | fail-open(靜默)(對外部觀察者而言) |
| WATCH-22 | render_watcher.py | 鎖模組(`studio_common.claim_render`)必須可用 | render_watcher.py:100-104 | **repo 全文搜尋(`grep -rn render_watcher`)只找到 produce_batch.py/hybrid_render.py/render_ffmpeg.py/studio_common.py 裡的註解或 docstring 提及「渲染交給 PC 端 render_watcher」,沒有任何實際 `import`/`Popen`/排程呼叫;不在 crontab.txt,也不在 WATCHDOG.md 的 Windows 工作清單裡;腳本自身註解也承認「這支目前沒在排程裡」** | 鎖模組壞掉(104行):`_sc=None`,**直接放行不擋渲染**,腳本自己註解寫「fail-open:寧可偶爾重工,不要整條停產」——但因無呼叫端,此判準目前不會被執行到 | 死碼(此判準本身若被執行,設計上是 fail-open(靜默)) |
| WATCH-23 | seeding_watch.py | state 讀取失敗 / history 為空 / 當天有零筆紀錄(staleness) | scripts/seeding_watch.py:401-413(`main`前段) | 「carson-seeding-watch」Windows 工作排程器,07:00 每日(WATCHDOG.md 記載,非 crontab.txt) | `record`+`alert`+`return 1`(408/413行) | fail-closed |
| WATCH-24 | seeding_watch.py | 連續 `run0>=K_ZERO(5)` 次零題種出 | seeding_watch.py:464(`if run0 >= K_ZERO`) | 同上 | 同上,`return 1`(504行) | fail-closed |
| WATCH-25 | seeding_watch.py | 連續 `bad_days>=2` 天,上游基本面缺項比例 `>UPSTREAM_FLOOR(0.50)` 且樣本數 `n>=UPSTREAM_MIN_N(5)` | seeding_watch.py:492-493 | 同上 | 同上,`return 1`(504行) | fail-closed |
| WATCH-26 | seeding_watch.py | 推播(ntfy)必須真的送達 | seeding_watch.py:191-198(`_push_and_trace`)+220-237(`alert`) | 同上 | **這是本次盤點裡對「回傳值被吃掉」修得最徹底的一個**:`_push_and_trace` 顯式檢查 `push()` 回傳的 bool(191行 `if not pusher(...)`),失敗時呼叫 `swallowed()`(117-135行)寫入 log 檔(留痕,非完全靜默)。但程式碼自己的註解明講:這**不影響判準與 exit code**,「手機不會響,log 這行是唯一痕跡」(seeding_watch.py:198/232行附近註解) | fail-open(有聲)(留痕但不通知) |
| WATCH-27 | quota_ceiling_watch.py | `assert_project()` 回傳非空警告字串(帳本可能換了專案) | scripts/quota_ceiling_watch.py:227(呼叫) | 「carson-quota-ceiling-watch」Windows 工作排程器,15:20 每日(WATCHDOG.md 記載) | `return 1`(231行) | fail-closed |
| WATCH-28 | quota_ceiling_watch.py | state 檔存在但無法解析、或解析出來缺 `effective` 鍵/值為 `null`(「基準遺失」,歷史上修過兩次的 bug) | quota_ceiling_watch.py:272(讀 `prev.get("effective")`)+297/304/312(強制 `changed=True`) | 同上 | 強制 `changed=True` 觸發 alert(而非舊版靜默當成「第一次跑」永久丟失真正基準) | fail-closed |
| WATCH-29 | narration_compliance_watch.py | 自我體檢(`_biz_selfcheck`,用已知案例驗證判準本身還抓得到) | scripts/narration_compliance_watch.py:114(定義)+297(呼叫) | 「carson-narration-compliance-watch」Windows 工作排程器,07:10 每日(WATCHDOG.md 記載) | 自我體檢失敗直接判 fail-closed(檢測器對自己失效的正控制;明載理由是 2026-08-25~09-03 的閘門靜默漂移事故) | fail-closed |
| WATCH-30 | narration_compliance_watch.py | 樣本數 `n<MIN_N(8)` 時只報數字不判定 | narration_compliance_watch.py:320-326 | 同上 | `record(...)`(325行,寫「⏳ 樣本不足只報不判」)+ `return 0`(326行),**全程沒有呼叫 `alert()`**——這句「樣本不足」和「讀檔失敗導致樣本變小」長得一模一樣,程式碼自己在 271-273/321-323 行的註解點名了這個風險 | fail-open(有聲) |
| WATCH-31 | narration_compliance_watch.py | 旁白收束句比例 `r_sum<FLOOR_SUMMARY(0.50)` 或業務介紹比例 `r_biz<FLOOR_BIZ(0.50)` | narration_compliance_watch.py:329/332 | 同上 | `alert(...)`+`return 1`(338行「1 = 產線違規,哨是好的」) | fail-closed |
| WATCH-32 | watch_drill_regression.py | 12 案例(9 正控制+3 負控制)驗證 seeding_watch / quota_ceiling_watch / narration_compliance_watch 三支的 `--selftest` 輸出是否含/不含指定字串 | scripts/watch_drill_regression.py:94(`run_case`)+120(`main`) | **無呼叫端**——WATCHDOG.md:195 標題就寫「引信是誰在按」,docs/ops/2026-09-09_pythonw_stdio_correction.md:395 與 docs/ops/2026-09-09_handoff_wB-p1_third-leg.md:109 都明載「還沒有被排進任何排程 —— 引信仍要人按」 | 任一案例失敗:`rc=1` 並寫入 `docs/ops/watch-drill-regression.log`(全過也寫,讓「沒有 log」本身變成異常訊號) | 死碼(內部邏輯本身 fail-closed,但從未被自動觸發) |

---

### 6-1 額外發現:原表沒點名的守望類腳本

除了原表 4 支,我在 `youtube_channel/scripts/` glob 到並深挖了 6 支 watchdog 家族腳本
(brain_miner_watchdog / comment_watchdog / growth_watchdog / stall_watchdog /
local_cron_watchdog / render_watcher)+ 1 支非閘門分析腳本(watchtime_lever)。

**另外發現一整個不在指定目錄的家族**:`D:\carson-agent\scripts\`(repo 根目錄,非
`youtube_channel\scripts\`)有 4 支同樣命名成 `*_watch.py`/`watch_drill_*.py` 的腳本
(quota_ceiling_watch.py / seeding_watch.py / narration_compliance_watch.py /
watch_drill_regression.py),透過 Windows 工作排程器(而非 crontab.txt)執行,理由記在
WATCHDOG.md:這三支watch若放進 crontab.txt,`local_cron.py:275` 的路徑解析器 + `cwd=youtube_channel`
會讓它們解到錯的目錄、註冊成功但永久靜默失敗;且它們的存在目的就是要獨立於
`local_cron` 之外運作(local_cron 死掉正是它們要偵測的對象之一)。已全部深挖並列入上表
WATCH-23~32。

**未深挖、僅 name-list 的 guard/audit 家族**(命名符合更廣的 watch/monitor/guard/audit/
sentry/patrol 關鍵字,但判斷應歸另一位審查 guard/audit 欄位的同僚,本次只列名不佔表格列):
`attribution_guard.py`、`audit_funnel_shorts.py`、`audit_live_thumbs.py`、
`audit_per_stock_facts.py`、`audit_sidecar_consistency.py`、`audit_truncation.py`
(注:此檔內容已被 stall_watchdog.py 呼叫,見 WATCH-17,但檔案本身未逐行深挖)、
`audit_video.py`、`auditability_coverage.py`(已排程 crontab.txt:864)、`fact_guard.py`
(已排程 crontab.txt:531 `--notify`)、`fact_source_guard.py`。這是我自己的取捨,未經
team-lead 驗證,若判斷錯了請糾正。

### 6-2 排程狀態(逐腳本一行)

- brain_score_watch.py:**已排程**,crontab.txt:814/822/823(每日 15:15/16:10/17:10)
- brain_submit_watch.py:**已排程**,crontab.txt:853/854/855/856(每日 18:00/22:00/09:00/11:00,4 次/日)
- llm_credit_watch.py:**已排程**,crontab.txt:828(每日 08:40,帶 `--notify`)
- numerus_watch.py:**已排程**,crontab.txt:873(每日 11:45)
- brain_miner_watchdog.py:**已排程**,crontab.txt:832(每 20 分鐘)
- comment_watchdog.py:**已排程**,crontab.txt:688(每日 15:33)
- growth_watchdog.py:**未排程**——crontab.txt 無此腳本,repo 全文搜尋也找不到任何實際呼叫端,只有 growth_agent.py(crontab.txt:522,每 2 小時)docstring 提及「同 growth_watchdog」邏輯
- stall_watchdog.py:**已排程**,crontab.txt:557(每日 10:12)
- local_cron_watchdog.py:**已排程**,但走 Windows 工作排程器「LocalCronWatchdog」(不在 crontab.txt——WATCHDOG.md 記載,登入觸發+每 5 分鐘;`ExecutionTimeLimit` 15 分鐘)
- render_watcher.py:**未排程**——不在 crontab.txt,不在 WATCHDOG.md 的 Windows 工作清單,repo 內找不到任何自動呼叫端;腳本自身設計是手動/常駐 `--loop --interval 900` 模式,「未排程」不等於「沒人用」,只是沒有自動化觸發
- watchtime_lever.py:非判準腳本,不判定排程狀態
- seeding_watch.py:**已排程**,Windows 工作排程器「carson-seeding-watch」,07:00 每日
- quota_ceiling_watch.py:**已排程**,Windows 工作排程器「carson-quota-ceiling-watch」,15:20 每日
- narration_compliance_watch.py:**已排程**,Windows 工作排程器「carson-narration-compliance-watch」,07:10 每日
- watch_drill_regression.py:**未排程**——WATCHDOG.md:195 及兩份 docs/ops 交接文件都明載「還沒有被排進任何排程,引信仍要人按」


---

## 七、口徑不一致、我推翻的格、與能力邊界

### 7-1 🔴 兩份子表各自內部的計數打架 —— **兩個數字都寫在這裡,不併成一個**

| 子表 | 檔內自報 | 我逐列機械重數(以表格列為準) | 採用 |
|---|---|---|---|
| join_A(70) | 檔尾先寫「有閘門=12」,再寫「以本段明細覆核為準:14/15/41」 | **有閘門 16 / 部分覆蓋 15 / 只在prompt層 39**(16+15+39=70) | **用我的 16/15/39** |
| join_B(85) | 219 行寫「有閘門=13」,同檔 231 行自己重新核計成「8/28/49」 | **有閘門 8 / 部分覆蓋 28 / 只在prompt層 49**(含 DEBUNK-02 與 TWSTK-03~07 那 5 條)=85 | **用 8/28/49**(與該檔自己的重核一致) |

- join_A 差在**兩條沒被列進明細**:`LONG-03`(`_META_RE`)與 `LONG-08`(`_PLEA_RE`)在表格列裡判「有閘門
  (機制:確定性清洗)」,但檔尾的逐條列舉把它們漏掉了。⇒ 表格列是母體,檔尾摘要不是。
- join_B 的 13 是第一版、8 是它自己發現手滑後的重核;我獨立機械重數的結果**與 8/28/49 一致**。
- 記在這裡是因為 memory 的「44 vs 57」教訓:**被標成「兩個數字不一致」的值,不准在下游被靜默收斂成一個。**

### 7-2 我推翻了子表的哪一格

`LONG-15` / `LONG-16`(規則ⓜ)join-A 判「只在 prompt 層」,並自陳
「我沒逐行讀完 `_long_mixed_period` 本體,只信 gates_index 轉述」。
**我讀了本體,結論相反**:那個閘門**確實**針對ⓜ,但只覆蓋一個窄子集
(觸發詞白名單 + 08-30 放寬成 ±1 句視窗 + 精準層對中文數字失效)。
⇒ 改判**部分覆蓋**,理由逐條寫在第四節 A 與表格列裡。
**同一件事的另一面:join-A 判 `LONG-17` 為 fail-closed 我維持不動** —— 對它擋得到的那一類,
三個呼叫端一致、不在白名單、重生用盡即 `return None`,那是真的 fail-closed。

### 7-2b 🔴 交件前的獨立覆核推翻了我自己的四格(fresh-context 找碴 agent + 我逐條回源複驗)

| 原本寫的 | 改成 | 依據 |
|---|---|---|
| `CHECKUP-18` = fail-closed | **fail-open(重生耗盡後放行)**,K 43→**44** | 6335-6336 白名單含「同句數字自相矛盾」,親讀 6335-6352 |
| 14 條 HOOK = 重生耗盡後放行 | **fail-open(靜默)** | 6044-6049 只對三個判斷式寫 log,其餘重生用盡零輸出(K 總數不變) |
| 「這 45 條不算進 K」 | **其中 15 條算進 K** | 與同檔兩張表直接打架 |
| 「那 72 行沒有任何消費者」 | **`daily_health` 不讀它**(另兩處只原樣印尾巴) | `control_center.py:2003-2005`、`cloud_status.py:74` |
| 「GATE-15/16 定義在 5754-5768」 | 函式在 **765 / 1030**,5754-5768 是**註解** | 註解內容本身講的是 topic_override 跳過 |
| `_long_fact_heal`「判出 0」 | 補回射程 **12 支 / 417 個宣稱** 與作者自陳「**兩邊都不可信**」 | 該函式 docstring |

⚠️ 另外一件**沒改**的:我一度以為 §3(1) 那張 72 筆分類表數不出來(某次 grep 只吐 16 列),
重新用 `sed` 去頭去尾後**逐類加總回到 72**,表原封不動。**那次是我的過濾式壞掉,不是表錯。**

### 7-3 N=155 是**下界**,不是全集

- 7 個確認會餵進 prompt 的常數**沒有抽條**(第五節開頭已列名,其中 3 個是每片必注入)。
- `produce_batch.py` 還有約 25+ 個 `= (...)` tuple 常數,是用「有沒有接到 prompt 變數」這個判準
  grep 篩掉的,**沒有對每一個做逐字確認** ⇒ 不排除有漏網的 prompt 文字。
- `gates_index.md` 只覆蓋約 20 個直接落在「長片產出→發布」路徑上的函式,
  全檔 150+ 個 `_` 函式其餘未收錄;**它整份漏掉 `produce_batch.py:6020-6049` 那段 Shorts 專屬重生迴圈**
  (48 條 HOOK_RULES 在產出端唯一的閘門群),是 join-A 自己 grep 補回來的。

### 7-4 沒查到 / 查不動的(不用「應該」矇混)

- `GATE-18` 的 `sc.skeleton_dup_any` / `check_skeleton_frequency` 只核對呼叫端行為,**未展開模組本體**。
- `GATE-15` 的 A4 長片版(`:6163-6172`)是照同款 risk-tier 模式**推斷**為 fail-open(有聲),未逐行讀完。
- `GATE-28` `auto_reject`:**沒查排程是否真的掛著 `--auto-reject`**。
- `growth_watchdog.py` 判死碼靠全 repo grep 零呼叫 + `growth_agent.py` docstring 提「同邏輯」**推論被取代**,
  未逐行比對兩支邏輯是否等價;`render_watcher.py` 有沒有人手動長駐 `--loop` **查不到**。
- `WATCH-21`(local_cron_watchdog 冷卻抑制)歸「靜默」是站在「Carson 手機會不會響」;
  若判準改成「有沒有留痕」則應歸有聲。**這一格有主觀成分,標在這裡。**
- 🔴 **本清冊除了三件事之外全是靜態讀碼**(memory `static-reading-vs-runtime-behaviour`:讀程式碼算的 ≠ 跑起來的行為)。
  三件有 runtime 證據的是:①`ops_log.txt` 的 72 次實際放行 ②`fact_flags.json` 09-10 11:30 的 mtime
  ③`produce_batch.py` md5 全程未變。**其餘每一格都可能因為執行期分支而與實際不同。**
- **沒有追 09-06 安勤 3479** —— 那是 w9:p1 的單點深挖,兩件不重疊。

---

## 八、如果只能改三件

**不是處方,是清冊落在哪裡最痛的排序;改什麼、什麼順序由總督導和 Carson 決定。**

1. **規則ⓜ 的字面與閘門對齊**(第四節 A):現在 prompt 說「前一句不算」、閘門說「算」。
   兩邊哪一邊是對的要先裁決,**不要各自再漂**。⚠️ 收緊那一側的成本已經有實測:08-29 十七支全滅、成稿 0
   —— memory `yt-period-swap-integrity`:**加閘門的成本要用接近 r 估,不是 r^n**。
2. **給那 72 行「已放行需人工複查」一個消費者**(第三節 2)。這件最便宜:`daily_health.py:140-144`
   已經在逐行掃 ops_log,少的是一個字串。**在那之前,A2 誠信放行等於沒發生過。**
   ⚠️ 但**它只救得到有寫 log 的那 6 個站點**:第三節(1)那 14 條靜默的 HOOK 規則**連一行都沒有**,
   再怎麼加字串也數不到;而 `:6349` 那行還把「同句數字自相矛盾」的放行記成「鉤子後仍在鋪陳」
   (第三節 6)⇒ **加消費者之前,先讓被消費的那行寫對名字。**
3. **事實區塊的算術自洽**(第四節 E):目前**零層**。它比第零種更前面 ——
   連 prompt 層都沒有這條規則,而旁白照守則抄了一個不成立的「事實」。

