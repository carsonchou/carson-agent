# ch3 復發測試 6 支 —— 發布前獨立驗證報告(2026-09-09)

> 驗證員:fresh-context subagent(獨立驗證員,非執行線)。
> 紅線第一類(對外發布)。授權已有(Carson「跑那 6 支測試,名字先不要動」),**本報告不判授權,只判「做出來的東西是不是它宣稱的東西」**。
> **全程唯讀**:未改任何檔案、未碰 crontab、未上傳、YouTube 端只發讀取類呼叫(OAuth token 只在記憶體 refresh,未寫回檔案)。本檔是唯一的寫入。
>
> ⚠️ 全文用兩種標記分開:**【實測】**= 我跑過指令/查過 API 得到的;**【判斷】**= 我的推論或建議,可以被推翻。

---

## 0. 🔴 最重要的前提:我驗的物件在驗證中途被換掉兩次

| 時間 | 事件 | `rechecked_episodes.json` 的 blob |
|---|---|---|
| 17:48:05 | `dacddd8e` 事前登記 commit | — |
| 18:12:10 | `9193a63e` 6 支的稿與事實入庫 | — |
| 18:16:37 | `d6377e9e` E2 收束句修正 | **`2e06eebf9c4ba9c322d216cdef202dbc19295e3c`** ← **我的第 1~5 項驗的是這一版** |
| 19:10:17 | 工作區被改稿(當時未 commit) | — |
| 19:11:48 | `6a95dd61`「獨立驗證擋下的四件全修」 | **`289460b6d5bd6b9dcca50ad02aa5f03bfd006eb0`** |
| 19:11:51 | `a96c8f50` 判準修訂 | 同上 |

**讀本檔的人必須先確認手上是哪一顆 blob。** 我對兩個版本都給了結論,分開列。

### 0.1 我自己踩到並修掉的一個方法論錯誤(請具名記住)

我第一次跑閘門實測時,把 **`HEAD` 當成固定點**,用 `git show HEAD:ch3_lab/facts/rechecked_episodes.json` 取「舊語料」。而 HEAD 在那之前已經被另一個 session 推進了兩個 commit ⇒ **它回給我的是已修版**。

症狀:兩個語料輸出**一模一樣**,而陽性對照顯示「真陽性沒抓到」。

**腳本沒壞,壞的是我對「HEAD 指向什麼」的假設。** 改用 `git cat-file -p 2e06eebf…` 以 **blob 指紋**鎖死語料後重跑,真陽性立刻被抓到。

⇒ 這是 memory `parallel-sessions-same-repo`(「報 commit hash 給別人前先 `git status --porcelain`,要對方獨立驗就給 **blob 指紋**」)的一個正面實例。
⇒ **推論給下一個人:任何「拿舊版當對照」的驗證,對照物一律用 blob / sha256 指紋鎖,不要用 `HEAD` / 分支名 / 檔案路徑。** 在多 session 共用 repo 的環境裡,`HEAD` 是一個會自己移動的座標 —— 跟 `051efa79` 記載的「crontab 行號當天就漂了」是同一個形狀,而且失效時**不報錯**,只是安靜地驗了別的東西。

---

## 1. 七項逐項結論

### 對照表(兩個 blob 分開判)

| # | 驗收項 | blob `2e06eebf` | blob `289460b6`(現在) |
|---|---|---|---|
| 1 | 不是舊庫存改標題 | 有條件通過 | 有條件通過(未變) |
| 2 | 登記檔在產製之前 commit | **通過** | 通過(未變) |
| 3 | 兩臂分配 + E 臂真裁決 + 標題措辭 | **通過** | 通過(未變) |
| 4 | 誠信:每個數字/宣稱有來源 | **不通過**(8 條) | **8 條全部已改寫** ✅ |
| 5 | 畫面數字 = 旁白數字 | **不通過**(4 列) | **仍剩 2 列,不通過** 🔴 |
| 6 | 發布路徑不觸發常態排程 | 通過 | **通過**(19:14:38 重驗) |
| 7 | 發完之後量測讀得到 | 部分通過 | **未變 —— 這一項還沒有人動** 🔴 |

---

### 1️⃣ 內容真的是新方向,不是舊庫存改標題 —— **有條件通過**

**【實測】** 5/6 是全新的。`study_techniques` / `focus_techniques` / `if_then_plans` / `how_to_remember_what_you_read` / `pomodoro` 在 `episode_queue.csv`、`domain_episodes.json`、`famous_episodes.json`、`uploaded.json`、`uploaded_shorts.json` **全部零命中**;題材關鍵字(spacing / retrieval practice / implementation intentions / pomodoro / to-do list)在舊題庫也**零命中**。

🔴 **【實測】`learning_styles` 不是新的。ch3 上已經發過兩支同題材的片:**

- 長片 `m14CWlRhpvA`(`ch3_lab/uploaded.json`)
- Short `CJdPBbB-lP0`(`ch3_lab/uploaded_shorts.json`),稿在 `ch3_lab/shorts/learning_styles/narr_*.txt`
- 舊 entry 在 `ch3_lab/facts/domain_episodes.json`,成品在 `ch3_lab/eps_domain/learning_styles/`

新 E1 的**稿確實是新寫的**(用 Pashler 2008 / Rogowsky 2015 / Husmann & O'Loughlin 2019 / Howard-Jones 2014;舊的用 Rogowsky 2020 Frontiers n=125,對照組結論也不同)⇒ **不是「改標題」**。

**【判斷】** 但它會是這個頻道上第三支 learning styles。對 E 臂特別要緊:**E 臂只有 2 支,其中 1 支的題材頻道上已有存貨** ⇒ 量到的東西會混進同題材舊片的既有訊號,而事前登記檔的七條干擾項清單裡**沒有這一條**。建議補進登記檔當第八條替代解釋(或換題)。

---

### 2️⃣ 事前登記檔在產製之前 commit —— **通過**

**【實測】** 用 `git log` 時間序,不看檔案內容宣稱:

| 時間 | 事件 |
|---|---|
| **17:48:05** | `dacddd8e` 事前登記 commit |
| 17:56:30 | `facts/method_claims_b1b2.json` 建檔 |
| 17:57:15 | `facts/_prereg_before_snapshot.json`(記下當時 `reels/` 只有 14 支 + 逐檔 sha256) |
| 17:58:21 | `facts/method_claims_b3b4.json` |
| 18:06:43 | `facts/verdict_claims_e1e2.json` |
| 18:09:37 | `facts/method_claims_round2.json` |
| 18:12:10 | `9193a63e` 6 支的稿與事實入庫 |

**所有產製痕跡都晚於登記 commit。** 當時 `git status --porcelain` 對這些路徑是乾淨的 ⇒ 我驗的東西 = commit 裡的東西。

**【判斷】** 那份 17:57 的 `_prereg_before_snapshot.json`(14 支舊 reel 的逐檔 sha256)是**比 commit 時序更硬的證據** —— commit 時間可以造假,一份「這 6 個目錄當時不存在」的雜湊快照不行。這個做法值得變成常規。

---

### 3️⃣ 兩臂分配正確、E 臂真的是裁決、標題措辭 —— **通過**

**【實測】臂別**:照 `arm` 欄位機械比對,4 B / 2 E。
- B:`study_techniques` / `how_to_remember_what_you_read` / `focus_techniques` / `if_then_plans`
- E:`learning_styles` / `pomodoro`

**【實測】標題**:6 支的 `prereg_title` 與登記檔表格中的逐字標題**逐字元完全相同**(byte 比對,含 `Won't` 的撇號字元),零個字被改。

**【實測】措辭禁令**:`backed by science` 在 `ch3_lab/` 與 6 支稿裡**零命中**,只出現在三份文件的「禁用」句本身。4 支 B 臂全部用 `that actually work`,且句構確實各不相同(定冠詞句 / 冒號句 / 從屬子句 / 介系詞片語)—— 這一點對 `yt-inauthentic-template-risk-2026-08` 有意義。

**【實測】E 臂收束句**(我自己重讀原文,不看 `d6377e9e` 的宣稱):
- E1:「Rogowsky ran the experiment directly, audiobook against e-text. **No interaction. What failed is the matching** — having a preference was never the claim.」
- E2:「One trial tested that exact recipe, against letting people pick their own breaks. **It found no benefit. The 25 and the 5 are not the part that was working.**」

兩句都下了判斷,沒有「證據不足 / 幾乎沒被測過」那種不可知論語氣,也沒有反向過度宣稱。**`d6377e9e` 的修是有效的。**

---

### 4️⃣ 🔴 誠信:每個數字都要有來源 —— **blob `2e06eebf` 不通過(8 條);blob `289460b6` 已全部改寫**

#### 4-0. 通過的那一半(兩版皆然)

**【實測】**
- 20 條 claim 逐條對過 verbatim,`_check_claim_values.py` 回「每一條的 value 都在自己的 verbatim 裡出現過」。
- 4 條轉引自 Dunlosky 2013 的 secondhand 數字(47/37、72/37、r=−0.29、80/36)**一條都沒進旁白** —— 我逐字掃過 6 支的 `turn`,零命中。commit 講的這件事是真的。這件事要緊,因為說明欄樣板會印「The numbers are read from them directly, not from a summary.」,用轉引數字會讓那句話變假(memory `yt-integrity-methodology-claims-blindspot`)。
- 推導值(Ariga & Lleras 的 `0`)標了 `value_is_derived` + `do_not_speak`,旁白確實沒把它當量測值唸。
- 每個唸出來的數字我都能指回一句原文:74/42(Rohrer 2015)、61/40(Roediger & Karpicke 2006)、69 + 0.55(Bisra 2018)、56/42(Roediger & Karpicke 2006 Exp 1)、101/120 + 84%(Karpicke & Blunt 2011)、64%(Cepeda 2008)、0.63(Scullin 2018)、94 + 0.65(Gollwitzer & Sheeran 2006)、0.31(Bélanger-Gravel 2013)、28 + 0.99(Toli 2016)、426(Husmann & O'Loughlin 2019)、93%(Howard-Jones 2014)、94 + 25/5(Smits 2025)、24/6(Biwer 2023)。**沒有一個數字是憑空的。**

#### 4a. 🔴 與**自家事實庫直接矛盾**的宣稱(1 條)

**`focus_techniques` weight(blob `2e06eebf`)**:

> "Both of these were measured against **doing nothing**, and both of them are things you do to the room."

**【實測】兩支都不是對照「什麼都不做」:**
- **Scullin 2018** 的 verbatim 逐字寫著:「Participants who wrote a To-Do List fell asleep significantly more quickly than **those who wrote a Completed List**」。同一個 JSON 檔的 `what_it_means` 也寫著「either writing a to-do list of upcoming tasks **or journaling about tasks they'd already completed**」—— active control。
- **Ward 2017** 對照的是**手機放哪裡**(desk / pocket-bag / other room),不是「不做事」。

**這句話在同一個檔案裡就被自己的 verbatim 推翻了,而三道閘門全綠。**

✅ **blob `289460b6` 已修**:weight 改為「Each one is a comparison somebody actually ran, against a real alternative.」,turn 也把 Scullin 的對照組講對了(「fell asleep faster than people who wrote down what they had already finished」)。

#### 4b. 🔴 與**同一支影片自己印出來的數字**矛盾(2 條)

**`how_to_remember_what_you_read`(blob `2e06eebf`)**:

- belief:「You just read something. In a week you will remember **almost none** of it.」
- 三十秒後 turn:「56 percent a week later, **against 42**.」

**【實測】** 照它自己的證據,重讀組一週後記得 **42%**。「almost none」不是 42%。開場句沒有來源,且被同一支片畫面上的數字打臉。

- verdict:「Not one of them is reading it again. That is the one thing that **does not work**.」
  42% 不是「不管用」,是「比較差」。過度宣稱,而守門只驗數字。

✅ **blob `289460b6` 已修**:belief →「Read it again and nothing else, and in a week **more than half of it is gone**.」(與 42% 一致);verdict →「When rereading was tested head to head, **it lost**.」(準確)。

#### 4c. 🔴 掛名 / 無對應來源的宣稱(5 條)—— **這是今天才發現的漏抓類型**

判準只問「這個數字有沒有來源」,問不到「這句話有沒有來源」。

| 支 | 逐字句子(blob `2e06eebf`) | 為什麼是掛名而沒有來源 |
|---|---|---|
| `pomodoro` weight | "It came from **one student's own method**, not from a study." | 起源宣稱。事實庫 3 篇論文沒有任何一篇講這件事,零來源 |
| `pomodoro` turn | "the paper **most often cited as proof** is a vigilance experiment…" | 引用頻率宣稱。沒有任何引文統計來源 |
| `pomodoro` turn | "**One randomised trial** has: 94 university students…" | ①「randomised」不在 Smits 2025 的 verbatim 裡(原文是 "online intervention",條件 n=25/36/33);②「只有一支」是**團隊自己文獻搜尋的結果**,不是任何來源說的 —— 而唯一性正是這支片的支點 |
| `study_techniques` belief | "**Most study advice has never been tested.** These three have." | 對整個文獻的全稱宣稱,零來源 |
| `study_techniques` verdict | "All three **feel worse while you are studying**. That is the trade, and **it is the whole finding**." | desirable difficulties 的**主觀成本**宣稱。三篇量的全是**表現**(答對率、回憶量、效果量),三條 verbatim 裡沒有 effort / difficulty / subjective / perceived 任何一個字。而它被寫成「it is the whole finding」= 這支片自己宣告的重點,而那個重點沒有來源 |

🔴 **共同形狀(這是本輪最可複用的一條):五條全都是「聽起來像有人量過」的句子,而句子裡沒有數字。**
`make_reel.audit()` 的 `NUM_RE` 掃不到它,`_check_claim_values.py` 也掃不到它 —— **兩道閘門的定義域都是「數字」,而這五條的風險載體是「動詞」**(came from / cited as / randomised / never been tested / feel worse)。

✅ **blob `289460b6` 已修**:五條全部改寫。
- pomodoro belief/weight 拿掉起源宣稱,改成「You have probably tried it.」/「So here is the question: has anyone actually tested that exact recipe?」
- 「One randomised trial」→「**In our own search, we found one**」
- 「most often cited as proof」→「**a study that kept coming up in that search**」
- study_techniques belief →「Three study methods that beat what you are probably doing instead.」
- study_techniques verdict →「Two of these were scored a week and a month after the studying stopped.」(可查證:Rohrer 30 天、Roediger 1 週)

⚠️ **【判斷】新版留下一個守門看不到的東西:** pomodoro 現在講的是**關於我們自己方法的宣稱**(「In our own search」/「that kept coming up in that search」)。這比原本誠實得多(它明說唯一性來自我們的搜尋,不是文獻的性質),但觀眾**無法查證**,而且沒有任何閘門看得到這一類 —— 正是 memory `yt-integrity-methodology-claims-blindspot` 那一格。不擋,但要知道。

#### 4d. 較輕的一條(記錄,不擋)

**【實測】** `study_techniques` weight(舊版)「measured against the way students normally study: rereading, and doing one topic at a time」—— 對 interleaving(vs blocked)、testing(vs rereading)成立,但 **Bisra 2018 的 self-explanation meta-analysis 對照的是「無 self-explanation prompt」**,不是重讀也不是單一主題。三分之一不成立。
✅ 新版改為「compared with what students do by default: blocking one topic, rereading, and **just reading on**」,三個對照組都對得上了。

**【實測】反向的一條(這條是好的)**:`if_then_plans` turn 唸 0.99 時沒提 Toli 2016 verbatim 裡的「Excluding one outlying (very large) effect」—— 但 0.99 **就是**排除離群值後的保守值,所以這是誠實的選擇,不是遺漏。

#### 4e. 🔴 我讀漏、被機械規則抓到的一條

**【實測】** `how_to_remember` weight(舊版)「Three things change that. **All three were measured against just reading it again.**」
—— Karpicke & Blunt 的對照是 **concept mapping**、Cepeda 的對照是 **zero-day gap**,**三分之二不是 rereading**。
**我自己逐句讀沒抓到,是後面那支試跑的機械規則抓到的。**(詳見 §3)
✅ 新版已修:「each was compared with a different thing people do instead」。

---

### 5️⃣ 🔴 畫面印的數字 = 旁白唸的數字 —— **兩版都不通過**

**驗證範圍:6 支全驗、18 列全比(每支 3 列 `twist_rows`),不是抽驗。**

⚠️ **層次先講清楚:6 支仍未渲染**(`ch3_lab/reels/` 只有舊的 14 個目錄、零 mp4)。我比的是「事實庫的 `es`」×「`make_rechecked.val_str()` 實際產生的字串」×「`turn` 旁白逐字」—— **不是逐格抽幀**。抽幀那一層我沒碰到,見 §5.4。

#### 5.1 blob `2e06eebf`:18 列裡 4 列不一致

| 支 | 畫面實際印出 | 問題 |
|---|---|---|
| `focus_techniques` 列 1 | `η² = 0.01` | 事實庫 **0.014**,被 `.2f` 捨成 0.01(−29%),旁白沒唸 |
| `focus_techniques` 列 2 | `η² = 0.03` | 事實庫 **0.026**,捨成 0.03(**+15%,往上**),旁白沒唸 |
| `focus_techniques` 列 2 的 `what` | `independent replication` | Ward 2017 Exp 2 是**同一篇論文、同一組作者**。觀眾的自然讀法是「另一個團隊獨立重做」—— 那不是事實 |
| `how_to_remember` 列 3 | `d = 1.10` | 旁白同一刻唸「64 percent increase」。**同一列、同一個比較、兩個不同的量**(兩者都在 Cepeda 2008 同一句裡,不是捏造,但觀眾同時聽到 64、看到 1.10) |

(`learning_styles` / `pomodoro` 各有一列畫面印 `1`,旁白唸 "only one study" / "One randomised trial" —— 只是拼成字,**這兩列沒問題**。)

#### 5.2 blob `289460b6`:修了 2 件,**仍剩 2 件**

✅ 已修:兩列 η² 併成一列;`independent replication` 改成 `working memory, replication`。

🔴 **【實測】沒修的兩件:**

| 支 | 畫面 | 旁白同一刻 |
|---|---|---|
| `focus_techniques` 列 1 | **`η² = 0.03`** | 「Both effects were small」(**這個數旁白從頭到尾沒唸**) |
| `how_to_remember` 列 3 | **`d = 1.10`** | 「the best gap gave **64 percent** more recall」 |

#### 5.3 根因:兩道閘門各差一步,而且是同一種差法

🔴 **【實測】捨入的根因**:`ch3_lab/make_rechecked.py:214` 的 `val_str()` 對 `eta2` **寫死 `.2f`**:

```python
if kind == "eta2":
    return f"η² = {v:.2f}"
```

而**同一個函式的 docstring 自己寫著「精度跟著存的值」**,一般分支確實是 `max(2, min(dec, 3))`(保留到 3 位)—— `eta2` 是唯一違反它的分支。

`focus_techniques` 是**全 20 集裡唯一用 `eta2` 的**(我掃過全部 `twist_rows`)⇒ 這條路徑從來沒被跑過,是這一批新開的。

⚠️ 偏誤方向:0.026 → 0.03 是**往上**,也就是往「這個方法比較有效」的方向。這支程式自己的 `is_max` 註解就寫著「偏誤方向剛好往我想要的方向走,那是最該擋的一種」。

🔴 **【實測】為什麼新閘門看不到它**:`6bfb7dbd` 加的孤兒閘門(`make_reel.py:205-208`)比的是

```python
f"{x['es']:g}" not in ok
```

—— **原始值**,不是 `val_str(...)` 的**輸出字串**。閘門本身是好的(我跑 `_control_orphan.py`:陰性 `hot_hand` 安靜通過、77.7 / 0.4242 / −1234 三種陽性全擋下,**會叫而且不誤叫**),它只是**量錯對象**:白名單驗「事實庫裡有沒有這個值」,而觀眾看到的是「渲染後那串字」。

**【判斷】修法**:把孤兒閘門的比對對象從 `f"{x['es']:g}"` 換成 `val_str(...)` 產出的字串裡的數字部分,或直接讓 `val_str` 的 `eta2` 分支跟其他分支一樣走 `max(2, min(dec, 3))`。後者較小,但前者才堵住整類(下一個新 `es_kind` 還會再犯)。

#### 5.4 新版新增一件要注意的(不是缺陷)

**【實測】** `focus_techniques` 現在有一列 **`es = None` / `es_kind = None`**(Ariga & Lleras 那列,label `a brief switch away`、what `no decline across the task`)。`make_reel.py:480` 的守衛是 `if x.get("es") is not None and x.get("es_kind")`,所以那一列會印文字、不印數字。

**【判斷】這是對的,而且比硬湊一個數字誠實。** 但它讓「畫面三列只有兩個數字」,渲出來的版面沒人看過 —— 抽幀時要特別看這一格(欄寬是從有值的列倒推的,`make_reel.py:344` `vals = [...] or ["x"]`)。

#### 5.5 片長逼近硬帶上界

**【實測】** blob `289460b6` 的 `--script-only` 估算:`focus_techniques` **46 秒**、`how_to_remember_what_you_read` **47 秒**,硬帶 35~50。**兩支都貼上界**,渲完量實際值很可能要改稿重渲(`make_reel.py` 會印 ⛔ 並回非零)。交棒檔原本只點名了 `how_to_remember`,現在 `focus_techniques` 也進來了(它加了第三個來源,字數從 100 增到 120)。

---

### 6️⃣ 發布路徑不會順手觸發常態排程 —— **通過**

**【實測】用內容查,不用行號。重驗時間 2026-09-09 19:14:38。**

```
$ grep -n "ch3_publish" youtube_channel/deploy/crontab.txt
784:# [ch3 收線 2026-09-02] 25 8  * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> ...
785:# [ch3 收線 2026-09-02] 25 14 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> ...
786:# [ch3 收線 2026-09-02] 25 20 * * * /root/yt/run.sh scripts/ch3_publish.py --limit 1 --shorts 1 >> ...

$ grep -n "ch3" youtube_channel/deploy/crontab.txt | grep -v "^[0-9]*:#"
793:30 9 * * * /root/yt/run.sh scripts/ch3_health.py >> /root/yt/logs/cron.log 2>&1
```

三行全部以 `# [ch3 收線 2026-09-02]` 開頭;反向查(排除註解)**只回一行**,就是唯讀健檢。行號現在是 784~786,與 `051efa79` 的更正一致 —— **但我沒依賴那個數字**。

🔑 **`youtube_channel/deploy/crontab.txt` 的 blob = `201809f542b2f7a5770f7741337727f81a897eda`**,`git status --porcelain` 對它是空的(今晚這一連串 commit 沒有碰它)。下一個人可以拿這顆指紋獨立比對是不是同一份。

**只讀 crontab 不夠,另外驗了四件:**

1. **【實測】解析器真的會跳過**:`youtube_channel/scripts/local_cron.py:246` 是 `if not s or s.startswith("#") or s.startswith("SHELL") or s.startswith("PATH"): continue`。
   *為什麼這步有必要*:那三行的註解前綴後面接的是**完整 cron 欄位**(`# [ch3 收線 2026-09-02] 25 8 * * * …`)。若解析器是先抓 5 欄再判註解,行為會不一樣。它不是。
2. **【實測】這份檔案是活的,不是紀錄檔**:`local_cron.py` **正在跑**(Win32_Process 命中),而 `:484` 每分鐘連同 `.env` 重讀一次 crontab ⇒ 我驗的是**生效中的排程**。
3. **【實測】`ch3_health.py` 真的唯讀**:整支讀過,只做兩件事 —— 跑 `ch3_lab/health.py`(有事才推播)、`shutil.copy` 備份 `uploaded*.json` / `publish_meta.json`。**零 insert / upload / videos() 呼叫。**
4. **【實測】Windows 排程沒有第二條路**:`QuantArsen_DailyPublish` / `QuantArsen_DailyThumbnail` / `QuantArsen_WeeklyTopics` 全部 **Disabled**,無任何 ch3 發布工作。
   *為什麼這步有必要*:`deploy/WATCHDOG.md:215` 記載三支哨是 Windows 排程工作而**不在** `crontab.txt` 裡 ⇒ 這一格不能只查 crontab。

**【實測】發布路徑本身也不會誤觸舊庫存**:`--only` 對不上就 `SystemExit`(「不猜、不改發別的,指名什麼就只發什麼」),且用了 `--only` 之後 `rest` 為空,補件迴圈 `while len(todo) < a.limit and rest` 補不進 `ch3_lab/shorts/` 底下那 33 個舊目錄。

---

### 7️⃣ 🔴 這 6 支發出去之後,量測拿得到嗎 —— **儀器可用,但兩條通過判準在這個量級上算不出來**

**這一項到現在還沒有人動。它決定測試要不要重新設計。**

#### 7.1 ✅ 【實測】`engagedViews` 對這個頻道查得到 —— 不是「API 支援」,是實查

用 `D:\carson-agent\yt_ch2\token_analytics.json`(過期但 refresh 成功;scope 含 `yt-analytics.readonly` + `youtube.force-ssl`)對 `channel==UCbo4EytWhZ7zAGSoIPioJ5g`:

```
channels.list(mine=True) → id=UCbo4EytWhZ7zAGSoIPioJ5g
                           title='One Quiet Hour'   ← 名字沒動 ✓
                           subs=1  views=320  videos=44

reports.query 生涯總計 → engagedViews 77 / views 375 / estimatedMinutesWatched 32
  dimensions=video                    ✓
  dimensions=day                      ✓
  dimensions=insightTrafficSourceType ✓
```

⇒ **幣別(engagedViews + 觀看分鐘)不用換。**

#### 7.2 ⚠️【實測】更正一條被誤歸因的限制

先前轉述的說法是「`engagedViews` 吃 dimensions 但不吃 filters」。實測結果**不是這樣**:

| 查法 | 結果 |
|---|---|
| `metrics=engagedViews` + `filters=video==bB-ZdA-v8Gs` | ✅ 回 `[[8]]` |
| `metrics=engagedViews` + `filters=insightTrafficSourceType==YT_SEARCH` | ❌ 400 `badRequest — The query is not supported.` |
| **`metrics=views,estimatedMinutesWatched`**(拿掉 engagedViews)+ 同一個 filter | ❌ **同樣 400,同樣訊息** |
| `dimensions=video,insightTrafficSourceType`(雙維度) | ❌ 400,**兩種 metric 組合都一樣** |

🔑 **陰性對照告訴我們的**:拿掉 `engagedViews` 只查 `views` + `estimatedMinutesWatched`,那個 400 **照樣出現** ⇒ 這不是 `engagedViews` 的限制,是 **YouTube Analytics 的 channel report 裡「流量來源」只能當維度、不能當篩選,且不能與 `video` 併成雙維度**。

⇒ memory `filter-accepted-is-not-filter-applied` 的反向用法:**宣稱「API 不支援某篩選」也要陽性對照**,否則會把「整類查法不支援」誤歸因給「某個 metric 不支援」。

#### 7.3 ✅ 【實測】「搜尋+推薦 ≥25% 觀看分鐘」的可行算法

唯一走得通的組合是 **`filters=video==<id>` + `dimensions=insightTrafficSourceType`**:

```
✅ filters=video==bB-ZdA-v8Gs + dimensions=insightTrafficSourceType
   cols=[insightTrafficSourceType, views, estimatedMinutesWatched, engagedViews]
   rows=[['NO_LINK_OTHER',0,0,0], ['YT_SEARCH',1,0,0], ['SHORTS',106,4,8]]
```

⇒ **6 支要發 6 次查詢,不能一次拿全表。** 寫進讀數腳本即可,不影響設計。

#### 7.4 🔴【實測】分母會跟著查法一起動

同一支片、同一個窗(2026-08-01 ~ 2026-09-06):

| 查法 | views | 分鐘 |
|---|---|---|
| `filters=video` 無維度 | **102** | **3** |
| `dimensions=video`(全頻道排行) | **102** | **3** |
| `filters=video` + `dimensions=insightTrafficSourceType` 加總 | **107**(106+1+0) | **4**(4+0+0) |

**差 5%(views)/ 33%(分鐘),而「搜尋+推薦 ≥25% 觀看分鐘」是一個比值。**
這是 memory `verification-that-cannot-fail` 清單裡「**分母跟著處置一起動**」那一格。

**【判斷】** 判準要現在寫死用哪一條。建議用**有維度那條的加總當分母**,因為分子只能從那條拿,兩邊同源才不會混口徑。

#### 7.5 🔴🔴【實測】更硬的一件:分鐘在這個量級被整數化,25% 這個門檻**物理上量不出來**

上面那支片的來源拆解是 `SHORTS 4 分鐘 / YT_SEARCH 0 分鐘` —— YT_SEARCH 明明有 1 次觀看,但分鐘被捨成 **0**。

ch3 逐支生涯分鐘數(`dimensions=video`):`3 / 2 / 1 / 7 / 1 / 2 / 1 / 1 / 0 / 1`,**最高一支 7 分鐘**;全頻道 44 支合計 **32 分鐘**。

⇒ 在總分鐘 0~7 的量級上,每個來源的分鐘只有 0、1、2 幾個離散值,**一列進位或捨位就會把比值從 0% 跳到 33%**。
**【判斷】** 要讓 25% 這個門檻不被量化雜訊主導,單支大概需要累積到 **≥40 分鐘**。

#### 7.6 🔴【實測】兩條 B 臂通過判準,在這個頻道的量級上都不可達也不可測

生涯逐支 engagedViews 排行:

```
bB-ZdA-v8Gs  views=102  engagedViews= 8
6veI2gvZARI  views= 36  engagedViews=10
_jSrEYCgU8E  views= 32  engagedViews= 5
bvU1mY4bzX0  views= 30  engagedViews= 7
0E6LOVYAKZ0  views= 27  engagedViews= 5
```

| 登記檔的判準 | 這個頻道的實況 | 差距 |
|---|---|---|
| 單支 **≥500 engagedViews** | **史上最高單支 10** | **50 倍** |
| 單支 **搜尋+推薦 ≥25% 觀看分鐘** | 單支分鐘 0~7,分來源後整數化成 0/1/2 | **量化雜訊 > 訊號** |
| 「整體無資訊」地板:engagedViews 中位數 <100 | 史上最高 10 | **10 倍** |

**【判斷】結論**:除非發生數量級躍遷,**兩週後的讀數會落在「整體無資訊 ⇒ 不准對姿態下任何結論」那一格,而且是被門檻設定決定的,不是被內容決定的。**
登記檔有那條保護是對的(它防止過度解讀),但意思是:這 6 支發出去,最可能的結果是花掉 9,636 配額換到一個「量不到」。

**一句話**:**儀器沒壞,壞的是門檻的量級 —— 判準的單位選對了(engagedViews + 分鐘),數值選在一個這條管道從沒到過的地方。**

#### 7.7 🔴【實測】登記檔「搜尋佔比是乾淨的 0」現在不成立,而且既有趨勢與測試預測同方向

| 期間 | SHORTS | **YT_SEARCH** | 其他 |
|---|---|---|---|
| 2026-08 整月 | 263 views / 18 min | **29 / 2** | 22 / 2 |
| **2026-09-01 ~ 09-06** | 31 / 3 | **32 / 3** | 1 / 0 |

**過去六天,搜尋已經是 ch3 的第一大流量來源(≈50% 觀看、≈50% 分鐘),而這段期間一支新片都沒發**(ch3 線 09-02 收線)。

生涯累計:YT_SEARCH 61 views / 5 min / 19 engagedViews = **15.6% 觀看分鐘、24.7% engagedViews**。
登記檔寫的「131/141 來自 Shorts feed」是頻道還只有 141 觀看時的快照,現在是 375。

**【判斷】兩個後果:**
1. 「整體無資訊」的另一半判準(搜尋來源 <10% 觀看分鐘)**基線就已經 15.6%**,不管測試成不成功都不會觸發。
2. **如果發完之後搜尋佔比高,那不能算成測試的功勞** —— 它在測試開始之前就已經在漲了。這條「乾淨的儀器」現在有一個與測試同方向的既有趨勢,而登記檔把它當成零基線寫進了讀法。

⇒ memory `gate-blind-while-target-evolves` 的形狀:承重的基線是**舊快照當現況**,而它會自己移動,移動時**不報錯**。

#### 7.8 配額(這一格沒問題)

**【實測】** `ch3_lab/quota.py:81` `DAILY = 20800`;`SHORT = 1600 + 6 = 1606`。6 支 = **9,636**,一天發得完。`quota.json` 停在 2026-09-02 / spent 150,今天會重置。配額吃 ch2/ch3 那本帳(Cloud 專案 881902283633),不影響主頻道。

---

## 2. 發布路徑的三個擋路件 —— 已修,我重驗過

這三件不在七項驗收裡,是我驗七項的路上撞到的。**它們在 blob `2e06eebf` 時代會讓 6 支一支都發不出去,或發出錯的東西。**

### A. `publish_shorts.py` 讀不了新 entry 的形狀 —— 會 KeyError 整批中止

**【實測·舊】** `ch3_lab/publish_shorts.py:645` 是 `T, O = E["test"], E["original"]`,而 6 支新 entry 的 key 只有 `['arm','evidence','papers','prereg_title','reel','slug','story_type_short','twist_rows']` —— **沒有 `test`、沒有 `original`**。`build_meta()` 走到第一支就 `KeyError`,`main()` 沒有 try,整批中止。

當時不會炸,只因為 `reels/` 底下還沒有這 6 個目錄(`mp4.exists()` 為 False 先 continue)。**這個地雷的引信是「渲染完成」。**

✅ **【實測·現在】已修**:硬取移除,改成 `_pp = E.get("papers")` 分流(`:651`)。

### B. 🔴 事前登記的逐字標題,沒有任何程式讀得到它

**【實測·舊】** `:650` 是 `title = f"{E['popular_name']}: {E['story_type_short']}"`,而 6 支新 entry **沒有 `popular_name`**,有的是 `prereg_title`。我掃過全 repo 的 `.py`:**`prereg_title` 的讀取者是零。**

⇒ 就算把 A 修掉,YouTube 上出現的標題也不會是登記的那一個。**而「標題措辭」正是這整個實驗唯一被操縱的變數。**
⇒ memory `verification-that-cannot-fail` 第零種:**規則只寫在文件層 = 期望不是規則**,而且失效**完全靜默**(片子照發、標題照有、只是換了一個)。

✅ **【實測·現在】已修,而且修得比我要求的多**:
- `reel_title()`(`:833`)真的讀 `prereg_title`,超過 95 字元 **fail-closed 不准截**(截掉的正好是被操縱的變數)
- 新增 `prereg_title_gate()`(`:855`):送出去的標題必須**逐字等於**登記檔上的那一個,並擋「兩支搶同一個登記標題」
- 新增對照 `ch3_lab/_control_prereg_title.py`。**我跑過**:陰性(六支全用登記標題)安靜通過;**五種陽性全部擋下** —— 尾巴多一個空格、少了 The Only、換成 `backed by science`、舊 `popular_name` 組法、兩支搶同一個標題。**這道是會叫的。**

#### 🔴 B 殘留的洞(團隊要求升一級記錄)

**【實測】** `prereg_title_gate()` 的第一行是:

```python
for o in batch:
    if not o.get("is_prereg"):
        continue
```

而 `is_prereg` 在 `:704` 被設成 `bool(E.get("prereg_title"))`。

⇒ **閘門的觸發條件由被監控物自己提供。** 欄位被拿掉、改名、打錯字(`prereg_titles` / `preregTitle` / 少一個底線),`is_prereg` 就是 `False`,**閘門整支跳過,而且不會叫** —— 它連被觸發的機會都沒有。

這是「閘門不會叫」那一類裡**最難發現的一種**:一般的失效至少會留下一次「檢查跑了但結論錯了」的痕跡,這種連痕跡都沒有。同一個形狀在這條線上出現過(`yt-duplicate-impl-gate-bypass`:閘門只在其中一份實作裡,產線走沒閘門那份)。

**【判斷】建議修法(三選一,由強到弱):**
1. **最強**:所有進候選池的 reel entry **一律**要有明示的 `is_prereg: true/false` 欄位,**缺欄位本身就是錯誤**(`_need()` fail-closed)。這樣「忘了填」和「填 false」在機械上可分辨。
2. **中**:`prereg_title_gate` 不看 `is_prereg`,改成看**登記檔**:登記檔解析出 6 個 slug,那 6 個 slug 只要出現在 batch 裡就必須過閘門(判準來源從被監控物移到登記檔本身)。
3. **弱**:保留現狀但加一條斷言 —— batch 裡 `is_prereg` 為 True 的數量必須等於登記檔的 6,不等就中止。

**【判斷】我推薦 ②**:它把判準的來源從「被檢查的東西」搬到「登記檔」,而登記檔是這個實驗的憲法,不會為了方便被改。①要動 20 集的 schema,③只擋得住「全缺」擋不住「缺一支」。

### C. `focus_techniques` 只有 2 篇論文,會被自家閘門擋掉 ⇒ B 臂剩 3 支

**【實測·舊】** `reel_gate()`(`:1060`)對 `papers` 型 entry 要求 **≥3 篇**,而 `focus_techniques` 只有 2 篇(Ward 2017、Scullin 2018)⇒ B 臂會從 4 支變 3 支,而登記檔的門檻(4 支裡 ≥2 支)是照 4 寫的。

✅ **【實測·現在】已修**:補進 Ariga & Lleras 2011(vigilance),papers **2→3**。旁白也加了對應的一段,並多出一列無數值的 twist_row(見 §5.4)。

### ⚠️ 交棒檔的一條指示是反的(這條還在)

**【實測】** 交棒檔寫「指名發不要用 `--limit`」。**這是反的。**

```python
# ch3_lab/publish_shorts.py:1064
pool = todo
todo, rest = pool[:a.limit], pool[a.limit:]
```

`--limit` 預設 **2**,而且這一刀切在 `--only` **之後**。照交棒檔跑 `--only <6 個 key>`,`reels/` 照字母序 ⇒ 只會發 `reel_focus_techniques` + `reel_how_to_remember_what_you_read`,**兩支都是 B 臂,E 臂 0 支**,而且畫面上會印「要上傳 2 支」看起來很正常。

⇒ **指名發必須帶 `--limit 6`。**

### ⚠️ 路徑更正

交棒檔與任務書寫的 `youtube_channel/scripts/publish_shorts.py` **不存在**。真檔是 **`D:\carson-agent\ch3_lab\publish_shorts.py`**。
`privacyStatus` 寫死 `"public"` 在 **`:844`**,無 `--privacy` 也無 `--flip` —— **執行線的結論是對的,只有路徑錯了**(那個錯路徑是團隊轉述時未查證帶進來的)。
⇒ **一發就是公開,沒有兩段式**,而下架後回讀有數小時快取延遲(memory `yt-readback-stale-cache`)。

---

## 3. 🔬 一個機械閘門提案的實測:「旁白的對照組宣稱 vs 論文 verbatim」

**動機**:§4a 那條(「measured against doing nothing」而自家 verbatim 寫著 active control)是不是可以做成閘門?

### 3.1 規則(受測的那一版)

> 旁白只要出現對照組句型(`measured against X` / `compared to|with X` / `versus X` / `vs X` / `instead of X` / `rather than X` / `against X`),**X 就必須在這一集某條來源紀錄裡逐字找得到**。

白名單放寬到四個欄位(`verbatim` + `what_it_means` + `unit` + `label`),給它最有利的條件。腳本:
`C:\Users\User\AppData\Local\Temp\claude\D--carson-agent\ee3f1512-e494-4633-bf37-7315958220ae\scratchpad\gate_trial2.py`(兩個語料都用 blob 寫死,可重跑)

### 3.2 【實測】語料 A = blob `2e06eebf`(含真陽性)—— 13 處觸發、9 處告警

去掉重複計算(`\bagainst ` 會在 `measured against ` 裡再命中一次,3 條重複)後 **6 條不重複告警**:

| # | 告警 | 判定 |
|---|---|---|
| 1 | 🎯 `focus_techniques` → `'doing nothing'` | **真陽性。就是 §4a,規則抓到了** |
| 2 | 🎯 `how_to_remember` → `'just reading it again'` | **真陽性,而且是我讀漏的**(§4e:三分之二的對照組不是 rereading) |
| 3 | `study_techniques` → `'the way students normally study'` | 弱真陽性(= §4d) |
| 4 | `study_techniques` → `'doing one at a time'` | **假陽性**(blocked practice 的白話) |
| 5 | `pomodoro` → `'letting people pick their own breaks'` | **假陽性**(self-regulated break condition 的白話) |
| 6 | `how_to_remember` → `'building a concept map'` | **假陽性**(elaborative studying with concept mapping 的白話) |

**精確率 2/6 = 33%(算弱真陽性則 50%)。**

### 3.3 【實測】語料 B = blob `289460b6`(已修版)—— 10 處觸發、6 處告警、**0 真陽性**

```
🔔 study_techniques  「compared with」→ 'what students do by default'
🔔 study_techniques  「instead of」   → 'doing one at a time'
🔔 focus_techniques  「against」      → 'a real alternative'
🔔 pomodoro          「against」      → 'letting people pick their own breaks'
🔔 how_to_remember   「compared with」→ 'a different thing people do instead'
🔔 how_to_remember   「instead of」   → 'building a concept map'
```

**精確率 0%。** 其中兩條(`a real alternative`、`a different thing people do instead`)是**後設句** —— 旁白在說「每一條都有對照組」而不是說對照組是什麼。這種句子會永遠叫,調不掉。

### 3.4 三個實測到的結構性失效點

1. **【實測】句型清單追不上被監控物。** 這一輪就當場示範了:我列的 `measured against` 在 19:10 那版全被改寫成 `compared with` / `is a comparison somebody actually ran, against` —— 改稿的人不是為了躲閘門,只是在改文筆,而清單就已經對不上了。失效時**不報錯**(`gate-blind-while-target-evolves`)。
   ⇒ 若真要做,語料必須是**全部 20 集的真旁白**,陽性對照必須用**真案例**(`doing nothing` 那句),不要用合成 fixture。
2. **【實測】它證不了「找到的是對的那一條」。** entry 沒有「這句旁白對應哪一條 claim」的連結(`papers` 是 list、`twist_rows` 是另一個 list、旁白是自由文字)⇒「X 在某條 verbatim 裡出現過」可以是**別篇論文的對照組**。
   **實測直接撞到**:`instead of rereading` 這同一個字串,在 `study_techniques` 被擋下、在 `how_to_remember` 通過 —— 差別只在後者剛好有一條 verbatim 出現過 rereading 這個字。**同一句話,兩集兩種判決,而兩集都沒錯。**(`flattened-key-hides-evidence` 的形狀)
3. **【實測】一半的 verbatim 根本沒存對照組。** Bisra 2018 存的是「identified 69 effect sizes … g = .55」,沒有任何對照組描述 ⇒ 這條規則會對它**誤擋**;若為它開「verbatim 沒寫對照組就放行」的例外,`doing nothing` 那一類就從那個例外走掉了。

### 3.5 🔴 結論:**不要建這一版,但不要丟掉這個方向**

**【判斷】為什麼誤報率不會下降**:三條假陽性來源只有一個 —— **旁白用白話講對照組,論文用術語寫**。而那正是這個頻道**存在的理由**(它的工作就是把 technical language 翻成 plain English)。所以這條規則跟產品本身打架,**調參數調不掉;它的誤報率不會隨時間下降,只會隨旁白寫得更好而上升。**

跟早上主頻道那個假掛名閘門是同一個形狀但方向相反:那次是**判準太鬆**(數字撞到池裡鄰居,真陽性被跳過);這次是**判準太硬**(要求逐字,而產品的價值就在不逐字)。

**【實測】但它有真訊號**:6 條裡 2 條真的,**其中 1 條是人讀漏的**(§4e)。**規則抓到了人沒抓到的東西。** ⇒ 結論是「換形狀」不是「丟掉」。

### 3.6 ✅ 建議的工程項目:**登記對照組**(把「解析散文」換成「產製端申報」)

這是本輪唯一一個可以直接變成工程項目的東西。

**規格:**

1. **每條 claim 加必填 `control` 欄位** —— 論文的對照組,**值必須在它自己那條 `verbatim` 裡逐字出現**(與現在 `value` 的規則一模一樣,機械可驗、可加陰性/陽性對照)。
   - 例:Scullin 2018 → `"control": "those who wrote a Completed List"`
   - 例:Karpicke & Blunt 2011 → `"control": "elaborative studying with concept mapping"`
2. **加 `control_said_as`(白話講法)** —— **就是已經在用的 `value_in_verbatim_as` 那個逃生門**。
   - 例:`"control_said_as": ["building a concept map", "making a concept map"]`
3. **旁白裡任何對照組宣稱,必須命中某個已登記的 `control` 或 `control_said_as`。** 命中不到就 fail-closed。
4. **`control` 缺欄位本身就是錯誤**(走 `_need()`),不可以用「這篇沒有對照組」靜默跳過 —— 真的沒有對照組(如 Bisra 那種 meta-analysis)要明寫 `"control": null` + `"control_note": "…"`,**讓「沒填」和「沒有」在機械上可分辨**。

**為什麼這個形狀比較好(【判斷】):**

- 三條結構性假陽性全部變成**一次性登記同義詞**,不是每次渲染都吵。
- 兩條真陽性留著。
- Bisra 那種沒對照組的論文會在**填欄位那一步**被人看到,不是在閘門那一步被誤擋。
- **失效方式從「靜默漏抓」變成「缺欄位就不出片」** —— 判準來源從「解析散文」搬到「產製端必須申報」,而申報缺漏**會產生輸出**(`verification-that-cannot-fail` 的判準:「沒被遵守時會不會產生輸出」)。

⚠️ **代價要講在前面,不要讓下一個人以為它比實際強:**

- 逃生門一旦用上,那條的對照組就**不再被機械檢查** —— 跟 `value_in_verbatim_as` 現在那個洞**完全一樣**(已記錄:value 從 1 改成 7 而字串仍對得上,它不會叫)。它是把「閘門亂叫」換成「**有逃生門的那幾條要人看**」。這個取捨團隊已經接受過一次。
- **20 條 claim 要回頭補 `control`**,補的人得重讀 verbatim。**這一步沒有機械捷徑。**
- 它擋的是「對照組講錯」這一類,**擋不到** §4c 那五條(掛名而沒有來源的**非對照組**宣稱:起源、引用頻率、randomised、全稱宣稱、主觀成本)。那五條目前仍然只能靠人讀。

---

## 4. 發布前還沒做、必須有人補的一步

🔴 **6 支渲完之後逐格抽幀看畫面。**

我驗的是「程式碼會印什麼」,不是「畫面上有什麼」。這條線出過的三類錯**只有看片抓得到**,靜態讀碼看不到:

- **版面重疊** —— 守門逐元素驗四個邊全綠,而兩欄合起來撞 22×10 畫素
- **黑底黑字** —— 色塊高度寫死 0.30,行數 ≥6 時首尾兩行落到色塊外,文字顏色恰等於背景色,**直接消失**(grit 的判決卡少了主詞)
- **揭露時序偏移** —— 旁白唸 A 而畫面正在顯示 B,獨立驗證量到最大 1.5 秒;已上線的 Dunning-Kruger 在 t≈26~35 秒畫面只有 `r = 0.28` 而旁白正在唸「minus 0.05」

§5 抓到的那幾列是抽幀**之前**就看得到的那一層;抽幀那一層我沒碰到。

**另外**:`focus_techniques`(46s)與 `how_to_remember_what_you_read`(47s)估算都貼 35~50 的上界,渲完要量實際值,很可能要改稿重渲。

---

## 5. 複驗指令

```bash
# 0. 鎖語料(多 session 環境一律用 blob,不要用 HEAD)
git rev-parse d6377e9e:ch3_lab/facts/rechecked_episodes.json   # 2e06eebf…(我驗第1~5項的版本)
git hash-object ch3_lab/facts/rechecked_episodes.json          # 現在的
git hash-object youtube_channel/deploy/crontab.txt             # 201809f5…

# 1. 舊庫存比對
python -c "import json;print(sorted(json.load(open('ch3_lab/uploaded.json',encoding='utf-8'))))"
python -c "import json;print(sorted(json.load(open('ch3_lab/uploaded_shorts.json',encoding='utf-8'))))"
grep -rn "study_techniques\|if_then_plans\|pomodoro\|learning_styles\|focus_techniques\|how_to_remember" \
  ch3_lab/facts/episode_queue.csv ch3_lab/facts/domain_episodes.json ch3_lab/facts/famous_episodes.json

# 2. 時間序
git log --format='%h %aI %s' -- docs/ch3_recurrence_test_prereg_2026-09-09.md
git log --format='%h %aI %s' -8 -- ch3_lab/facts/rechecked_episodes.json
stat -c '%y %n' ch3_lab/facts/method_claims_*.json ch3_lab/facts/verdict_claims_e1e2.json

# 3/4/5. 閘門與稿
cd ch3_lab && python make_reel.py --all --script-only     # 20/20 通過
cd ch3_lab && python _check_claim_values.py               # 25 條,1 條推導值警告
cd ch3_lab && python _control_orphan.py                   # 陰性安靜 / 三種陽性擋下
cd ch3_lab && python _control_prereg_title.py             # 陰性安靜 / 五種陽性擋下

# 6. 排程(用內容,不用行號)
grep -n "ch3_publish" youtube_channel/deploy/crontab.txt              # 三行都要以 # 開頭
grep -n "ch3" youtube_channel/deploy/crontab.txt | grep -v "^[0-9]*:#" # 只該回 ch3_health.py
sed -n '240,250p' youtube_channel/scripts/local_cron.py               # startswith("#") 跳過
powershell -NoProfile -Command "Get-ScheduledTask | Where-Object { $_.TaskName -match 'ch3|yt|publish|short' }"

# 7. Analytics(唯讀;token 只在記憶體 refresh,不寫回)
#    scratchpad/probe_ch3_analytics.py / probe2.py / probe4.py / probe5.py / probe6.py
#    channels.list(mine=True) → UCbo4EytWhZ7zAGSoIPioJ5g / One Quiet Hour
#    reports.query metrics=engagedViews,views,estimatedMinutesWatched
#      dimensions=video / day / insightTrafficSourceType
#      filters=video==<id> + dimensions=insightTrafficSourceType   ← 逐支拆來源的唯一走法
#      filters=insightTrafficSourceType==…                          ← 400,且與 engagedViews 無關

# A/B/C
sed -n '645,660p'   ch3_lab/publish_shorts.py   # papers 分流(舊版是 E["test"], E["original"])
sed -n '833,880p'   ch3_lab/publish_shorts.py   # reel_title + prereg_title_gate
sed -n '1055,1070p' ch3_lab/publish_shorts.py   # papers ≥3 篇
sed -n '1060,1070p' ch3_lab/publish_shorts.py   # pool[:a.limit],--limit 預設 2

# 3. 閘門提案實測
python "<scratchpad>/gate_trial2.py"            # 兩個語料都用 blob 寫死
```

**相關檔案(絕對路徑):**

- `D:\carson-agent\ch3_lab\facts\rechecked_episodes.json` —— 6 支的稿與 twist_rows
- `D:\carson-agent\ch3_lab\publish_shorts.py` —— `:651` papers 分流、`:704` is_prereg、`:833` reel_title、`:855` prereg_title_gate、`:844` privacyStatus、`:1060` papers≥3、`:1064` limit
- `D:\carson-agent\ch3_lab\make_rechecked.py:204` —— `val_str()`,`eta2` 寫死 `.2f`(🔴 未修)
- `D:\carson-agent\ch3_lab\make_reel.py:205` —— 孤兒閘門,比原始值不比輸出字串(🔴 未修)
- `D:\carson-agent\ch3_lab\_control_orphan.py` / `_control_prereg_title.py` —— 兩支對照,都跑過
- `D:\carson-agent\docs\ch3_recurrence_test_prereg_2026-09-09.md` —— 事前登記
- `D:\carson-agent\youtube_channel\deploy\crontab.txt` —— `:784-786` 註解、`:793` 唯讀健檢

---

## 6. 一句話總結

**產製端的誠信問題已經修完(4a~4e 八條全數改寫,A/B/C 三個擋路件已修並有對照),但兩件仍然不通過:畫面上的 `η² = 0.03`(存的是 0.026,往上捨,旁白沒唸)與 `d = 1.10`(旁白同刻唸 64 percent);而更要緊的是第 7 項 —— 儀器是好的,門檻不是:`≥500 engagedViews` 是這個頻道史上最佳單支的 50 倍,`≥25% 觀看分鐘` 在單支 0~7 分鐘的量級上被整數化吃掉。這 6 支照現在的判準發出去,兩週後的讀數會是「整體無資訊」,而那是門檻決定的,不是內容決定的。**

---
---

# 第二輪驗證(2026-09-09 23:41 起)—— **追加,不覆蓋上面第一輪**

> 驗證員:同一個 fresh-context subagent。**全程唯讀**,未改任何檔案、未碰 crontab、未上傳、YouTube 端只發讀取類呼叫。本節是唯一的寫入。
> ⚠️ 標記沿用:**【實測】**= 跑過指令/查過 API;**【判斷】**= 推論或建議。

## 2-0. 🔒 本輪鎖定的 blob(第一輪教訓的直接應用)

第一輪我把 `HEAD` 當固定點而被換掉兩次(§0.1)。**這一輪開工第一件事就是鎖 blob。**

| 檔案 | blob(本輪驗的) |
|---|---|
| `ch3_lab/facts/rechecked_episodes.json` | `6e6fdf2d6c64948bf103e4af72b56465baeca176` |
| `ch3_lab/publish_shorts.py` | `090b6b21c989498e9e1268b232e9599ac063a042` |
| `ch3_lab/make_reel.py` | `33c9b1ea0704e044e027eec76cc1233d7a82ed94` |
| `ch3_lab/make_rechecked.py` | `3e1f07936f81cc8e6ececbe36a7fa6edbde15e90` |
| `youtube_channel/deploy/crontab.txt` | `1ac320e0fafbad9ea8b4ea710e6b9f399679ef14` |
| `docs/ch3_recurrence_test_prereg_2026-09-09.md` | `9eafc8c7a55ecbb4c376d9576b6107320beffb95` |

HEAD = `bf85a1e8`。上述路徑 `git status --porcelain` 全部乾淨(工作區 == commit)。
第一輪的參照 blob:`rechecked_episodes.json` = `2e06eebf…`、`crontab.txt` = `201809f5…`。

---

## 2-1. 一句話結論

# 🔴 不可以發。剩一件擋路(判準 C 的對照窗少了 3 天),外加一件建議同時修的一行洞。

**第一輪擋下的六件(①~⑥)全部修好,而且我逐件獨立重驗過,不是讀 commit 訊息。**
其中兩件修得比我報的更深(§2-7、§2-3)。擋路的是**這一輪新發現的**。

---

## 2-2. 重驗第一輪「通過」的三項(理由:被驗物在我手上換過兩次,之後又改了七次)

### 第 2 項(登記檔早於產製 + 判準修訂零資料)—— **通過**

**【實測】沒有任何一支已經發出去**,所以「零資料修正」成立:

- `ch3_lab/reels/` 仍只有**舊的 14 個目錄**,6 支新 slug 一個目錄都沒有,無 VERIFIED 標記
- `uploaded_shorts.json` 37 筆、`uploaded.json` 22 筆,**與第一輪相同**;6 支新 slug 與 `reel_<slug>` 全部查無
- 唯一命中的 `learning_styles`(`CJdPBbB-lP0` / `m14CWlRhpvA`)是**舊片**,第一輪已記錄

**【實測】時間序**(全部早於任何發布動作,而發布動作至今為零):

| 時間 | 事件 |
|---|---|
| 2026-09-09 17:48:05 | `dacddd8e` 事前登記 |
| 19:11:51 | `a96c8f50` 判準修訂 |
| **19:17:27.793** | `_baseline_frozen_2026-09-09.json` 的 `frozen_at` |
| 19:18:44 | `21b77faf` 基線 commit |

⇒ **判準修訂與基線凍結都在發布之前、且零資料。這不是移動球門。**

### 第 3 項(兩臂分配 / 標題逐字 / 措辭)—— **通過,標題沒有被順手改到**

8 條宣稱改寫動了 `belief` / `weight` / `turn` / `verdict`,所以必須確認標題沒被波及。

**【實測】對第一輪 blob `2e06eebf` 逐字元比對:**

| slug | 標題與第一輪相同 | 在登記檔內逐字 | 臂別未動 |
|---|---|---|---|
| study_techniques | ✅ | ✅ | ✅ B |
| how_to_remember_what_you_read | ✅ | ✅ | ✅ B |
| focus_techniques | ✅ | ✅ | ✅ B |
| if_then_plans | ✅ | ✅ | ✅ B |
| learning_styles | ✅ | ✅ | ✅ E |
| pomodoro | ✅ | ✅ | ✅ E |

B/E = **4/2**;`backed by science` 零命中。

### 第 6 項(那三行仍註解掉)—— **通過**

🔴 **`crontab.txt` 的 blob 變了**:`201809f5…` → `1ac320e0…`。查過:**與 ch3 無關** ——
`1a51642e` / `bf85a1e8` 在**檔尾追加** numerus(solo-saas 線)的 `45 11 * * *` 排程與註解,共 9 行。

**【實測】用第一輪 blob 直接對 ch3 相關行做定向 diff:**

    diff <(git cat-file -p 201809f542b2f7a5770f7741337727f81a897eda | grep "ch3") \
         <(grep "ch3" youtube_channel/deploy/crontab.txt)
    → 無差異

⇒ **ch3 的四行(三行註解掉的 `ch3_publish.py` + 一行唯讀 `ch3_health.py`)與第一輪逐字元完全相同。**
非註解的 ch3 行仍然只有 `:793 ch3_health.py`。

📌 **【判斷】方法上的一點**:blob 變了**不等於**我關心的東西變了。看到 blob 不同就重驗全部是浪費;
看到 blob 不同就報「排程被動過」是錯報。**正確動作是拿舊 blob 對新檔做定向 diff** ——
這比重新 grep 更強,因為它連「有沒有被偷偷加回一行沒有 `#` 的」都一起答了。

---

## 2-3. ① `prereg_title` 有沒有真的被讀到 —— **修好了,而且把我點的洞一起補了**

**【實測】** `ch3_lab/publish_shorts.py` 現在有 `reel_title()`(讀 `prereg_title`,>95 字元 fail-closed **不准截**)與 `prereg_title_gate()`。

重跑 `python ch3_lab/_control_prereg_title.py`:

    陰性:六支全用登記的逐字標題            → 通過(安靜)
    陰性:舊片明示 is_prereg=False           → 通過(不該被這道閘門管)
    陽性:尾巴多一個空格                     → 擋下
    陽性:少了 The Only                      → 擋下
    陽性:換成實測 0 勝出的那個措辭          → 擋下
    陽性:舊產線 popular_name 組出來的標題   → 擋下
    陽性:兩支搶同一個登記標題               → 擋下
    陽性:① is_prereg 欄位整個拿掉           → 擋下
    陽性:② 欄位名打錯一個字母               → 擋下
    陽性:③ 值填成字串 "false"(truthy)      → 擋下
    陽性:④ 產線帶過來的 <MISSING> 哨兵       → 擋下

⇒ 我第一輪報的「**閘門觸發條件由被監控物自己提供**」(`is_prereg = bool(E.get("prereg_title"))`)
**已修,而且四種缺漏形狀都有陽性對照**,含最會騙人的字串 `"false"`(truthy)。

**【判斷】** 這一格現在比我建議的三個修法都紮實 —— 它同時做到了①(明示欄位)與③(數量斷言)的效果。

## 2-4. ② `E["test"]/E["original"]` 的 KeyError —— **修好了**

**【實測】** `publish_shorts.py:645` 現在是 `T, O = E.get("test") or {}, E.get("original") or {}`,
接著按 `papers` 是不是非空 list 分流:是就逐篇檢查 DOI,否則走舊的 original/test 兩篇檢查,
**兩種形狀都沒有的 fail-closed**。標題改由 `reel_title(E, d.name)` 產生。

⇒ 硬取沒了,「渲染完成」那個引信拆掉了。

## 2-5. ③ `focus_techniques` 補的第 3 篇 —— **不是湊數,內容檢查通過**

**【實測】** 補的是 Ariga & Lleras 2011(`10.1016/j.cognition.2010.12.007`)。逐句對:

| 旁白 | 論文 verbatim |
|---|---|
| "the group that briefly switched away **did not decline at all**" | "sensitivity in the **Switch** condition **did not decrease** as a function of experimental block [F(3, 240) = **0.89**, ns.]" |
| "**the three groups** that worked straight through **all did**" | "Simple main effects of Block were significant for **Control, No-switch, and Digit-ignored** conditions [Fs(3, 240) > 4.62, p < .005]" |

⇒ **「三個組」是逐字對得上的**(Control / No-switch / Digit-ignored 剛好三個),不是概數。
⇒ 而且它是真的專注技巧(短暫切換),與這一集主題一致,不是為了過 `papers ≥ 3` 而塞。

⚠️ **【判斷】一件值得刻意處理的事(不是缺陷)**:
**同一篇 Ariga & Lleras 同時出現在兩集,而且角色相反** ——

- `focus_techniques`(B 臂):當**正面證據**「短暫切換的那組完全沒有下滑」
- `pomodoro`(E 臂):當**被誤引的那篇**「a study that kept coming up in that search **never used work blocks or break blocks at all**」

兩邊各自都準確,而且**彼此不矛盾**(短暫切換有效;25/5 這個比例不是有作用的那部分)。
但兩支會在同一個頻道幾天內發出,**同一篇論文一次拿來背書、一次拿來打臉**。
處理得好這是這一批最有意思的東西;處理不好會被讀成前後矛盾。
⇒ 建議寫進發布後的敘事,不要讓它自己撞上。

## 2-6. ④ 8 條宣稱 —— **全部有來源了,而且他們自己多抓到 4 條**

**【實測】** `docs/ch3_recurrence_test_claim_sourcing_2026-09-09.md` 逐條列「原句 / 新句 / 來源」,我逐條核對旁白現況:

| # | 我報的 | 現在 | 來源核對 |
|---|---|---|---|
| 4a-1 | "measured against **doing nothing**" | "against a real alternative"(具體對照組移到 turn 逐個講明) | ✅ |
| 4a-2 | 睡前清單沒說比誰快 | "fell asleep faster than **people who wrote down what they had already finished**" | ✅ 對得上 Scullin verbatim 的 Completed List |
| 4b-1 | "remember **almost none** of it" | "**more than half of it is gone**" | ✅ 42% 回憶 ⇒ 失去 58%,對已引用數字做算術 |
| 4b-2 | "the one thing that **does not work**" | "When rereading was tested head to head, **it lost**" | ✅ 56 vs 42,單一研究直接對比,沒宣稱它到處都墊底 |
| 4c-1 | "came from **one student's own method**" | 整句拿掉,改成提問 | ✅ 不帶來源宣稱 |
| 4c-2 | "**most often cited as proof**" | "a study that **kept coming up in that search**" | ✅ 主詞改成我們自己的搜尋 |
| 4c-3 | "**One randomised trial** has" | "**In our own search, we found one**" | ✅ 見下 |
| 4c-4 | "**Most study advice has never been tested**" | "Three study methods that beat what you are probably doing instead" | ✅ |
| 4c-5 | "All three **feel worse while you are studying**" | "**Two** of these were scored a week and a month after the studying stopped" | ✅ 明說「兩個」不是三個(Bisra 沒有統一延遲測驗) |

**【實測】團隊自己照「族」去掃,多抓到 4 條**,其中一條正是我第一輪讀漏、被機械規則抓到的那條(§4e):
`how_to_remember` weight「All three were measured against just reading it again」→「each was compared with a different thing people do instead」。
另三條:`study_techniques` weight 兩對照配三方法 → 三配三;
`learning_styles` verdict 的 "Preferences are real."(無來源的獨立正面宣稱)→ "having a preference was never the claim"
(對得上 `E1.c1` 的 `what_it_does_not_say`,我查過該欄位存在且逐字支持)。

### 🔴 團隊點名要我特別看的「唯一性宣稱」—— **通過,而且兩個表面一起改了**

**【實測】**

- 旁白:`In our own search, we found one: 94 university students, one two-hour session.` —— `randomised` 已拿掉
- **畫面那一列的 `what` 也改了**:`found in the literature` → **`that our search found`**
  ⇒ 這點要緊:第一輪的教訓就是「旁白改了畫面沒改」。這次兩個表面同步。
- **來源有落檔**:`verdict_claims_e1e2.json` 的 `E2.search_log` **7 筆真實紀錄**(查了哪些庫、得到什麼),
  含陰性結果(多個 SEO 部落格重複同一句無來源的「94 students / 20% lower fatigue」)。
  ⇒ 「我們自己的搜尋」這個主詞**有東西撐**,不是修辭。

**【實測】沒有改而我確認過是對的**:`learning_styles` 的 "found only one study" 保留 ——
那句唯一性是 **Pashler 等人自己說的**(verbatim 逐字有),而旁白指名了主詞
「Pashler and colleagues found」。形狀正確。

⚠️ **【判斷】殘留(不擋)**:`pomodoro` 現在的唯一性與「常被引用」都是**關於我們自己方法的宣稱**。
比原本誠實得多(明說主詞是我們的搜尋),但**觀眾無法查證,而且沒有任何閘門看得到這一類**
(memory `yt-integrity-methodology-claims-blindspot`)。`search_log` 是好的補救,但它在 repo 裡、不在說明欄裡。

## 2-7. ⑤ 第 5 項那兩列 + 閘門本身 —— **修好了,而且比我報的深一層**

### 兩列都修了

**【實測】我自己重算 18 列(不看他們的對照)**:

| 支 | 畫面 | 旁白唸到 |
|---|---|---|
| `how_to_remember` 列 3 | **`64%`** | ✅ 64(第一輪是 `d = 1.10` vs 旁白 64 percent) |
| `focus_techniques` 列 1 | **`η² = 0.026`** | ❌ 未唸(但已明示 `display_only`,見 §2-10) |

⇒ **捨入沒了**:`val_str('eta2', 0.026)` 現在回 `η² = 0.026`(第一輪是 `η² = 0.03`,而且往上捨)。

### 閘門的比對對象換成格式化後的輸出了 —— **是**

**【實測】** `make_reel.py` 現在先算 `disp = val_str(...)`,再取 `disp.split(" = ")[-1]` 跑 `NUM_RE`
(只取等號右邊,因為**單位符號裡也有數字**:`pts/10`、`pts/7` 曾對 facial_feedback 誤擋四列),
並新增第三格:**畫面印的數字,`turn` 旁白同一段要唸得到**;不唸就要在那一列明示 `display_only`。

### 🔴 他們找到一層我沒找到的根因(這一條要記下來)

**【實測】白名單自己就收了四捨五入後的寫法。** `_collect()` 原本有
`for dp in (2, 3): out.add(f"{node:.{dp}f}")`,註解寫著「補的是同一個值的格式變體,不是新的值」——
**那句話對小數多的值是假的**:`0.026` 補到 2 位就是 `0.03`,那是另一個數字,而且是往上的那個。

⇒ 後果:「事實庫存 0.026、畫面印 0.03」在溯源上**恆為合法** ——
**這就是為什麼只把比對對象換成 `val_str()` 輸出,閘門還是不會叫。尺自己有刻度誤差。**

**【實測】我獨立驗過收緊有效**(直接呼叫 `_collect()` 探白名單):

    '0.026' 在白名單 = True     '0.03'  在白名單 = False
    '0.014' 在白名單 = True     '0.01'  在白名單 = False
    '0.63'  在白名單 = True     '0.630' 在白名單 = True(無損補零,留著)
                                '0.6'   在白名單 = False

⇒ **這是收緊,不是放寬。** 而且 20 集 `--script-only` 全過 ⇒ 沒有任何一支既有旁白靠捨入後的數字過關。

**這一層我第一輪沒看到。** 我報的是「閘門量錯對象」,而真正的底是「白名單先被污染了」——
換再多比對對象都量不出來。
⇒ **教訓:報「閘門量錯對象」之前,先問「它拿來比對的那份名單本身乾不乾淨」。**

### 陽性對照用了真案例 —— **是**

**【實測】重跑 `_control_display_vs_facts.py`:**

    真案例 1  val_str('eta2', 0.026) = 'η² = 0.026'(修好前 'η² = 0.03')      ✓
    真案例 1b 把 val_str 換回舊 .2f 行為 → focus_techniques 被擋下              ✓
    真案例 1c 修好之後 focus_techniques 安靜(不誤擋)                          ✓
    真案例 2  把 how_to_remember 列 3 改回 d = 1.10 → 擋下                      ✓
    單位符號  facial_feedback(pts/10、pts/7 曾被誤擋四列)安靜                  ✓

⇒ 沒有合成 fixture,全部是真案例,含**曾經真的誤擋過**的那一支當陰性對照。

---

## 2-8. ⑥ 新判準在這個量級上算不算得出來 —— **三格算得出,一格分母錯**

### 基線我獨立重算,**逐位完全吻合**

**【實測】** 我把 `_baseline_frozen_2026-09-09.json` 的 `per_video` 與
`_baseline_population_2026-09-09.json` 的 `status`(逐支 privacy)join 起來,自己算最近秩百分位:

| 母體 | n | engagedViews P50/P75/**P90**/max | views P50/P75/**P90**/max |
|---|---|---|---|
| 全部帳本 | 60 | 0 / 1 / **5** / 10 | 1 / 5 / **14** / 107 |
| 只算 public | 57 | 0 / 1 / **6** / 10 | 1 / 5 / **20** / 107 |

**與判準檔宣稱的一字不差。** privacy 分佈 public 57 / unlisted 3,也對得上。
`engagedViews ≥ 6` 的支數 = **6**(判準檔說「約等於進到史上前 6 名」,正確)。

✅ **他們選了比較難過的那個母體**(public-only P90 = 6,而非全帳本的 5),
而且把被否決的那個一起留在檔案裡。**偏誤方向是往「更難通過」走。**

⚠️ **【判斷】一個可重現性缺口**:`_baseline_frozen_*.json` 的 `per_video` **沒有存 privacy**,
所以**光憑凍結檔算不出 public-only 的 P90** —— 必須同時有 `_baseline_population_*.json`。
兩個檔要一起引用、一起保存;少一個,判準 A 的門檻 6 就無法重算。

### 逐格可行性

| 判準 | 門檻 | 這個量級算不算得出 | 判定 |
|---|---|---|---|
| **閘門 0** | ≥1 支 engagedViews ≥ 10 | 史上最高單支就是 10(`6veI2gvZARI`,36 views 換到 10 eV)⇒ 落在觀測過的範圍內 | ✅ 算得出 |
| **A** | 4 支裡 ≥2 支 eV ≥ 6 | 57 支 public 裡只有 6 支達標(10.5%)⇒ 要求 2/4 = 50% 擠進前 10%,是真訊號;門檻 6 在觀測範圍(0~10)內 | ✅ 算得出 |
| **B** | median(B)/median(E) ≥ 3(退化時:B 中位 ≥3 且 E 兩支 ≤1) | 算得出,但見下方警語 | ✅ 算得出(有殘留敏感度) |
| **C** | 發布後 14 天窗 YT_SEARCH ≥ 122 | 🔴 **分母錯** | ❌ 見 §2-9 |

⚠️ **【判斷】判準 B 的殘留單點敏感度**:E 臂 n=2,計數落在 0~10 的整數上。
E 其中一支從 0 變 2,E 中位就從(例)0.5 變 1.5,ratio 從 6 掉到 2 —— **一支片、兩次 engaged view 就翻盤。**
判準檔選 3 倍而非 2 倍是對的方向(「2 倍可以由單一支片造成」),但 3 倍**沒有消除**這個性質,只是抬高了一點。
判準檔 §5.1 已寫明「這是描述性讀數,不是統計推論」
⇒ **可接受,但結論裡必須把那句話一起寫出去,不要只報 ratio。**

---

## 2-9. 🔴 擋路件 1(本輪新發現):判準 C 的對照窗只有 11 天資料,卻當成 14 天

### 【實測】

判準 C:**發布後 14 天窗 `YT_SEARCH` views ≥ 發布前 14 天窗 × 2 = ≥ 122**,
發布前窗凍結為 `2026-08-27 ~ 2026-09-09` = **61 views**。

我用 `dimensions=day` 查同一個窗,**API 回應裡只有 11 天**:

    2026-08-27  1     2026-09-01  43
    2026-08-28  128   2026-09-02  11
    2026-08-29  67    2026-09-03   3
    2026-08-30  94    2026-09-04   1
    2026-08-31  15    2026-09-05   4
                      2026-09-06   2
      ← 2026-09-07 / 09-08 / 09-09 三天**完全不存在**(不是 0 列,是沒有這幾列)

YouTube Analytics 有 **2~4 天延遲**(memory `yt-analytics-lag-false-alarm`:
「延遲 2~4 天,錨在 today 做週對週 = 拿 4 天比 7 天」)。

### 後果

- **發布前窗**:名義 14 天,**實得 11 天**,凍結值 61
- **發布後窗**:14 天後讀,屆時資料已沉澱 ⇒ **實得 14 天**
- ⇒ **11 天 vs 14 天的比較。門檻偏鬆約 14/11 ≈ 1.27 倍。**

近期 `YT_SEARCH` 約 4.4~5.3 views/日 ⇒ 缺的三天約 **13~16 views**
⇒ 發布前窗真值應該是 **74~77**,×2 應為 **≈148~154**,而不是 **122**。**門檻低了約 20%。**

🔴 **為什麼這是發布前必須修、不能發完再修**:
現在改它是「零資料修正」;**一旦發出去,任何對這個門檻的更動都不再是零資料**,
而是在有結果的情況下動球門 —— 即使動機純正,它在紀錄上也和移動球門長得一模一樣。
判準檔 §0 自己寫著「發布前改 = 修好一把量不到東西的尺;看到結果才改 = 移動球門」。
**這一格現在還在前者那一側,發出去就不是了。**

### 【判斷】修法(擇一,都是零資料)

1. **重凍發布前窗,結束日改成有完整資料的那天**:`2026-08-24 ~ 2026-09-06`(14 天,全部落在延遲之外),重新算門檻。
2. 保持窗不動,但**在讀數時同步重測發布前窗**(屆時已沉澱),兩邊都用 14 天完整資料 ——
   **並且現在就把這條規則寫死進判準檔**,否則到時候重測看起來就像事後調整。
3. 最保守:兩者都做,並把 61(凍結時)與重測值都留在檔案裡,像 §2 對 44/60 支那樣兩個都列。

**【判斷】我推薦 ①** —— 它讓門檻現在就定案,不需要在讀數時再做任何動作;
而「讀數時還要重測一次基線」這種規則在兩週後很容易被忘記,**而忘記時不會有任何訊號**。

---

## 2-10. 🔴 擋路件 2(本輪新發現,一行可修):`display_only` 逃生門不要求理由

### 【實測】

新的第三格閘門:畫面印的數字旁白要唸得到,不唸就要在那一列明示 `display_only`。
錯誤訊息寫著:

    "真的要印一個不唸的數字,就在那一列寫 display_only=true 並附 display_only_why —— 靠沉默不算。"

**但程式只檢查 `display_only`,從來沒有檢查 `display_only_why`**(`make_reel.py:239`):

    if (n not in turn_txt and not x.get('display_only') and not at_start):

我實測(拿 `how_to_remember` 列 3 改回 `d = 1.10` 當基底):

| 情境 | 結果 |
|---|---|
| 無宣告 | ✅ 擋下 |
| `display_only=true`,**不附 why** | 🔴 **通過(閘門沒叫)** |
| `display_only=true` + why | 通過 |
| `display_only=true` + why 是**空字串** | 🔴 **通過** |

⇒ **規則只寫在錯誤訊息裡,而錯誤訊息是提示層不是規則層** ——
正是 memory `verification-that-cannot-fail` 第零種,也正是他們今晚剛在 `is_prereg` 那格修掉的同一個形狀。

### 影響範圍與嚴重度

**【實測】目前 7 條 `display_only` 全部都附了理由**,所以**這 6 支不受影響**:

| 集 | 列 | 理由是否成立 |
|---|---|---|
| facial_feedback ×3 | 舊已發布片 | ✅ 且明講「不要把宣告讀成已確認沒問題」 |
| sugar_hyperactivity | 畫面 0 / 旁白 "none" | ✅ 同一個值的兩種寫法 |
| learning_styles | 畫面 1 / 旁白 "one" | ✅ |
| pomodoro | 畫面 1 / 旁白 "one" | ✅ |
| **focus_techniques** | 畫面 `η² = 0.026` / 旁白不唸 | ⚠️ 見下 |

⚠️ **【判斷】`focus_techniques` 那條理由本身不精確**:
它寫「旁白**不對它做任何量級宣稱**」,而旁白說的是 "**Both effects were small**" ——
**"small" 就是一個量級宣稱。** 這不影響影片的正確性(η² = 0.026 確實小),
但**宣告的內容與事實不符**,而這條線最在意的就是「宣告本身要是真的」。
建議把理由改成「旁白只做定性描述(small),不唸數值;數值留在畫面上供查證」。

### 【判斷】修法(一行)

把條件改成
`not (x.get('display_only') and (x.get('display_only_why') or '').strip())`,
並在 `_control_display_vs_facts.py` 補三個陽性對照:**缺 why / why 空字串 / why 只有空白**。

⇒ 這一格**不阻擋這 6 支**(7 條宣告都有理由),但它是下一個人會用的逃生門,
而現在**跳過理由不會產生任何輸出**。一行的成本,建議與擋路件 1 一起修。

---

## 2-11. 仍然沒做、發布前必須補的(與第一輪相同,未變)

1. 🔴 **渲染 → 逐格抽幀**。我驗的仍是「程式碼會印什麼」,不是「畫面上有什麼」。
   版面重疊、黑底黑字、揭露時序偏移這三類只有看片抓得到。
2. **量實際片長**。`--script-only` 估算:`focus_techniques` **46 秒**、
   `how_to_remember_what_you_read` **47 秒**,硬帶 35~50 ⇒ **兩支都貼上界**,很可能要改稿重渲。
   (`focus_techniques` 是因為加了第三個來源,字數 100 → 120。)
3. **`--only` 必須帶 `--limit 6`**(`--limit` 預設 2 且切在 `--only` 之後)。
4. **發布沒有兩段式**:`publish_shorts.py:844` `privacyStatus` 寫死 `public`,一上傳就是公開;
   下架後回讀有數小時快取延遲。

---

## 2-12. 第二輪複驗指令

    # 鎖 blob(先做這件)
    git rev-parse HEAD
    for f in ch3_lab/facts/rechecked_episodes.json ch3_lab/publish_shorts.py \
             ch3_lab/make_reel.py ch3_lab/make_rechecked.py \
             youtube_channel/deploy/crontab.txt; do git hash-object $f; done

    # 第 6 項:拿第一輪 blob 做定向 diff,而不是重新 grep
    diff <(git cat-file -p 201809f542b2f7a5770f7741337727f81a897eda | grep "ch3") \
         <(grep "ch3" youtube_channel/deploy/crontab.txt)

    # ①⑤ 兩支對照 + 兩道既有閘門
    cd ch3_lab && python _control_prereg_title.py
    cd ch3_lab && python _control_display_vs_facts.py
    cd ch3_lab && python make_reel.py --all --script-only      # 20/20 全過
    cd ch3_lab && python _check_claim_values.py

    # ⑤ 獨立驗白名單收緊(不看對照,直接探 _collect)
    #   探 '0.026' '0.03' '0.014' '0.01' '0.63' '0.630' '0.6'
    #   期望:0.03 / 0.01 / 0.6 為 False,其餘 True

    # 2-10 的洞:把 how_to_remember 列3 改回 es=1.1/d,
    #   加 display_only=True 但不加 display_only_why → 實測「通過」(應該要擋)

    # ⑥ 基線獨立重算:join frozen.per_video × population.status 的 privacy,算最近秩
    #   all_ledger n=60 → eV P90=5;public_only n=57 → eV P90=6;max=10;eV>=6 共 6 支

    # 2-9 的擋路件:資料到哪一天
    #   reports.query startDate=2026-08-27 endDate=2026-09-09 dimensions=day
    #   → 只回 08-27~09-06 共 11 列,09-07/08/09 不存在

---

## 2-13. 第二輪一句話總結

**第一輪擋下的六件全部修好、我逐件獨立重驗過,其中兩件(白名單先收了捨入值、`is_prereg` 四種缺漏形狀)修得比我報的更深;第 2、3、6 項重驗仍然通過,標題逐字未動、ch3 那三行與第一輪 blob 逐字元相同。剩下不能發的理由只有一個:判準 C 的「發布前 14 天窗」實際只有 11 天資料(Analytics 延遲,09-07~09-09 在 API 裡不存在),門檻 122 偏鬆約 20% —— 而這件事現在改叫零資料修正,發出去之後再改就叫移動球門。外加一行的 `display_only_why` 沒被檢查,不影響這 6 支,但建議一起修。**

---
---

# 第三輪驗證(2026-09-10 00:42 起)—— **追加,不覆蓋前兩輪**

> 同一個 fresh-context 驗證員。**全程唯讀**:未改任何檔案、未碰 crontab、未上傳;
> YouTube 端只發讀取類呼叫,OAuth token 只在記憶體 refresh、未寫回。本節是唯一的寫入。
> 標記沿用:**【實測】** / **【判斷】**。

## 3-0. 🔒 本輪鎖定的 blob

HEAD = `593008c4`。

| 檔案 | 本輪 blob | 對第二輪 |
|---|---|---|
| `ch3_lab/facts/rechecked_episodes.json` | `d332fac5…` | 變(第二輪 `6e6fdf2d…`) |
| `ch3_lab/make_reel.py` | `816e0cfd…` | 變(第二輪 `33c9b1ea…`) |
| `docs/ops/2026-09-09_ch3_criteria_revision.md` | `97319cc2…` | 變 |
| `ch3_lab/publish_shorts.py` | `090b6b21…` | **未變** |
| `ch3_lab/make_rechecked.py` | `3e1f0793…` | **未變** |
| `youtube_channel/deploy/crontab.txt` | `1ac320e0…` | **未變** |
| `docs/ch3_recurrence_test_prereg_2026-09-09.md` | `9eafc8c7…` | **未變** |
| `ch3_lab/facts/_baseline_frozen_2026-09-09.json` | `09ee0453…` | — |

---

## 3-1. 🔴 先更正我自己第二輪的一個數字

第二輪我報:「缺三天約 13~16 views ⇒ 發布前窗真值應是 74~77 ⇒ 門檻應是 **≈148~154**,而不是 122。」

**那個外推是錯的。** 我假設修法是「把缺的尾巴三天補回來」,而正確的修法是**整段平移窗**——
平移會補進開頭三天、同時**丟掉結尾三天**。而補進來的 `08-24 / 08-25` 是**零觀看日**、`08-26` 只有 2 views。

**【實測】重凍窗 `2026-08-24 ~ 2026-09-06` 的 `YT_SEARCH` = 61**,與舊窗**一模一樣**。

⇒ **門檻仍然是 122,沒有變。**

**我第二輪那件事的結構判斷是對的(11 天窗對 14 天窗是無效比較,而且必須發布前修),
但我給的數字是錯的。** 執行線沒有照我的估算走,而是去量,然後把外推值排除在判準之外 ——
那個處理是對的:**量得到就不要用估的。**

---

## 3-2. ① 重凍後的窗真的都有資料嗎 —— **是,而且我原本的查法本身有瑕疵**

**【實測】** `dimensions=day` 查 `2026-08-24 ~ 2026-09-06`(窗長 14 天):

    2026-08-24  ❌ 無此列        2026-08-31  15
    2026-08-25  ❌ 無此列        2026-09-01  43
    2026-08-26  2                2026-09-02  11
    2026-08-27  1                2026-09-03   3
    2026-08-28  128              2026-09-04   1
    2026-08-29  67               2026-09-05   4
    2026-08-30  94               2026-09-06   2
    → 回傳 12 列

🔴 **這一格是本輪最值得記的一件:缺的兩天在「開頭」,不在結尾。**

第二輪我用的判準是「數列數」——**那個判準會把這個正確的窗判成不完整**,
而它給出的錯誤訊息會是「資料還沒進來」:**一個很有說服力的錯誤診斷**。

**【實測】零觀看日確實不回列**:查 `08-13 ~ 08-20` 只回 `['2026-08-19', 1]` 一列 ——
八天裡七天沒有列,因為那七天觀看數是 0。在這個量級的頻道上零觀看日是常態。

⇒ 分得開「真的零」與「還沒進來」的**不是列數,是資料視界**。

**【實測】資料視界**:往今天查一段,最後一個有列的日期 = **`2026-09-06`**;今天 = `2026-09-10`
⇒ 延遲 **4 天**,而窗結束日 = `09-06` ≤ 視界 ⇒ **這個窗已經完全落地**。

**【判斷】我第二輪的方法有一半是對的**:用 `dimensions=day` 去看「API 到底回幾列」比相信窗的定義強,
這一點成立(它抓到了 09-07~09-09 不存在)。**但把「列數 == 窗長」升級成完整性判準是錯的** ——
它會在零觀看日常態的頻道上產生假陽性,而假陽性的表現形式是「拒絕輸出 + 一個錯誤的原因」。
執行線把它改成資料視界是**比我提的更正確的修法**。

## 3-3. ② 重算後的門檻 —— **仍是 122,而且理由換成實測**

**【實測】** 重凍窗 `08-24~09-06` 的來源拆解(我自己查,不看凍結檔):

| 來源 | views | engagedViews |
|---|---|---|
| SHORTS | 294 | 46 |
| **YT_SEARCH** | **61** | 19 |
| YT_OTHER_PAGE | 14 | 6 |
| SUBSCRIBER | 3 | 1 |
| NO_LINK_OTHER | 2 | 2 |
| **合計** | **374** | — |

**【實測】** 落檔的 `ch3_lab/facts/_baseline_prewindow_2026-09-09.json` 與我的量測**逐位吻合**:
`expected_days 14 / rows_returned 12 / data_horizon 2026-09-06 / truncated_by_lag false /
zero_view_days ["2026-08-24","2026-08-25"] / YT_SEARCH 61 / total_views 374`。

⇒ **門檻 = 61 × 2 = 122,不變,但現在站在一個完整的 14 天窗上。**
判準檔就地記下「外推值 148~154 不寫進判準」,並註明理由。**這是對的做法。**

### ✅ 他們補了一件我沒提的對稱面

我只看了**對照窗讀太晚**(尾巴沒進來 ⇒ 分母偏小 ⇒ 門檻偏鬆)。
他們補上**量測窗讀太早**(尾巴沒進來 ⇒ 新片被低估 ⇒ **測試假性失敗**)——
方向相反,而且**更難發現**,因為失敗看起來像結果。

**【實測】** `ch3_lab/window_readout.py`:
- `--measurement` 時,讀數不得早於「窗結束日 + `LAG_DAYS`(4)」,**明示旗標,不從窗長推論**
- 資料視界 < 窗結束日 ⇒ `SystemExit`,**不輸出任何讀數**(fail-closed)
- 我讀過實作:**視界檢查是真正的閘門**,而且它是 raise 不是 print

## 3-4. ③ `display_only_why` 與那條不真的宣告 —— **兩件都修了**

**【實測】我自己造陽性(不看他們的對照),拿 `how_to_remember` 列 3 改回 `d = 1.10` 當基底:**

| 情境 | 結果 |
|---|---|
| 無宣告 | ✅ 擋下(畫面印、旁白沒唸) |
| `display_only=true`,**不附 why** | ✅ **擋下** —— 「這幾列用了 display_only 卻沒寫理由」 |
| why 是**空字串** | ✅ **擋下** |
| why **只有空白** | ✅ **擋下** |
| why 有實質內容 | 通過 |

⇒ 第二輪那個「規則只寫在錯誤訊息裡」的洞**已升為 fail-closed**,三種缺漏形狀都會叫。

**【實測】那條不真的宣告也改了**(`git diff` 顯示這是 `rechecked_episodes.json` 本輪**唯一**的改動,一行):

- 舊:「…而**旁白不對它做任何量級宣稱**。」← 不真,旁白說的是 "Both effects were small"
- 新:「…⚠️ 旁白對它做的宣稱是「Both effects were small」——**那是一個量級宣稱**,
  而它由存下來的值本身支撐(0.014 與 0.026,partial η²,兩個都小)。
  原本這條理由寫「旁白不對它做任何量級宣稱」,那句話**不真**…
  **宣告不真比影片錯更難發現,因為沒有人會去查宣告。**」

⇒ 改成據實描述,**並且就地留下自己的更正紀錄**。這比默默改掉好。

## 3-5. ④ 重驗前兩輪通過的項目 —— **沒有被這次修動壞**

| 項 | 判定 | 【實測】 |
|---|---|---|
| **第 2 項**(登記早於產製、零資料) | ✅ | `reels/` 仍是**舊的 14 個目錄**;`uploaded_shorts` 37 筆 / `uploaded` 22 筆,**與前兩輪相同**;6 支新 slug 與 `reel_<slug>` **全部查無** ⇒ **至今零發布,所以判準檔這次改動仍是零資料修正**。登記檔本身 blob **未變**(`9eafc8c7…`)。判準檔三次改動全在 09-09 19:18 / 19:24 與 09-10 00:02,**全部早於任何發布動作** |
| **第 3 項**(兩臂 / 標題 / 措辭) | ✅ | 6 支標題對**第一輪 blob `2e06eebf`** 逐字元相同、6 支全在登記檔內逐字、臂別未動;B/E = **4/2**;`backed by science` 零命中 |
| **第 5 項**(畫面 = 旁白) | ✅ | 18 列重算:**14 列旁白唸得到、3 列明示 `display_only`(理由皆有實質內容)、1 列無數值** ⇒ **零列是「未唸且未宣告」** |
| **第 6 項**(排程仍註解) | ✅ | crontab blob 未變(`1ac320e0…`);對第一輪 blob `201809f5…` 做 ch3 定向 diff → **無差異**;非註解的 ch3 行仍只有 `:793 ch3_health.py` |
| 閘門與對照 | ✅ | `make_reel.py --all --script-only` **20/20 全過,EXIT=0**;`_check_claim_values.py` 25 條全過;**三份對照套件全綠**(`_control_prereg_title` / `_control_display_vs_facts` / `_control_orphan`) |

---

## 3-6. 本輪唯一新長出來的問題:`window_readout.py` 的**說明與實作不一致**

**不擋發布**(它是 14 天後讀數用的),但**必須在引用它的輸出之前修**。

### 【實測】三處

1. **模組 docstring 描述的是一個被放棄的設計**:

       ⇒ 唯一可靠的判準是**數列數**:用 `dimensions=day` 查同一個窗,
         回的列數必須等於窗長。不足就 `SystemExit`,不印任何讀數。

   而 `assert_complete()` 裡的註解明寫「**列數不是判準**」,實作用的是資料視界。
   `want` / `absent` 算了,但**從來沒有拿來擋**。
   ⇒ 讀模組開頭的人會以為閘門在數列數 —— 而這正是他們自己在下面 20 行寫的
   「一個很有說服力的錯誤診斷」。

2. **`main()` 的執行時訊息宣稱了一個不存在的檢查**:

       ⚠️ 比名目延遲(…)早讀,但**列數檢查通過**(資料視界 … >= 窗結束)——以列數為準…

   **沒有列數檢查。** 而這一行會被抄進讀數紀錄(`_baseline_prewindow_*.json` 的
   `read_before_nominal_lag: true` 就是它印的那一次)。
   同一段的內嵌註解也寫著「**列數檢查是直接量測**」——同樣不成立。

3. `svc()` 會 `tok.write_text(cr.to_json())` **把 token 寫回檔案**,而 docstring 寫著「唯讀」。
   (功能上沒問題:`yt_ch2/token.json` 的 scopes = `yt-analytics.readonly` + `youtube.readonly`,
   **我查過,與 `svc()` 要求的一致**,14 天後讀得動。)

### 【判斷】為什麼這件值得寫下來而不是順手帶過

它和前兩輪擋下的東西是**同一個形狀**:
R1 的 `prereg_title` 存進沒人讀的欄位、R1 的閘門比錯對象、R2 的 `display_only_why` 只寫在錯誤訊息裡、
本輪的「列數判準只寫在 docstring 與執行訊息裡」——
**都是「宣稱存在於一個不會產生輸出的位置」。**
差別是這一次的宣稱**不影響任何數字**,只影響下一個人的理解。

⇒ 修法:docstring 與那句執行訊息改成描述**資料視界**;或更好 ——
把 `rows_returned` / `expected_days` 從輸出裡拿掉或改名為 `zero_view_day_count`,
**讓那個會誤導的數字不要出現在紀錄裡**。

### 其餘兩件小的(記錄,不擋)

- **`LAG_DAYS = 4` 正好貼在今天的實測延遲上**(視界 09-06、今天 09-10 = 落後 4 天;昨天是 3 天)。
  延遲若擴到 5 天,`+4` 這條名目規則就會放行一個不完整的量測窗 ——
  **還好真正的閘門是資料視界而不是這條規則**,所以它 fail-closed。不需要改,但別把 `+4` 當保護。
- **`yt_ch2/token_analytics.json` 的 scopes 變窄了**(第一輪我讀到 `force-ssl` + `yt-analytics.readonly`,
  現在只剩後者)—— 有腳本 refresh 之後把它寫回去了。目前沒有東西因此壞掉,
  但**憑證檔正在被這些讀數腳本改動**,值得知道。

---

## 3-7. 三輪對照:擋下的東西在收斂還是原地打轉

### 【實測】嚴重度軌跡

| 輪 | 擋下的 | 若照發會怎樣 |
|---|---|---|
| **一** | `publish_shorts` KeyError 整批中止 | **一支都發不出去** |
| **一** | 🔴 事前登記的逐字標題存進**沒人讀的欄位** | **實驗唯一被操縱的變數不會出現在 YouTube 上,而且完全靜默** |
| **一** | `focus_techniques` 只有 2 篇被自家閘門擋 | B 臂 4→3,分母與登記檔不符 |
| **一** | 8 條宣稱無來源(含 1 條被自家 verbatim 推翻) | 誠信事故,前科同類 09-06 才復發過 |
| **一** | 4 列畫面≠旁白(含**往上捨**的 0.026→0.03) | 觀眾同時聽到和看到兩個不同的東西 |
| **一** | 兩條通過判準差 50 倍 / 被整數化吃掉 | **測試必然無資訊,而且是門檻決定的** |
| **二** | 對照窗 11 天當 14 天 | 比較結構無效(實測門檻恰好沒變) |
| **二** | `display_only_why` 不強制 | 逃生門可以無理由使用,且無輸出 |
| **三** | docstring / 執行訊息描述了一個不存在的檢查 | **不影響任何數字**,只誤導下一個讀的人 |

**嚴重度:發不出去 / 靜默毀掉實驗 → 數字結構錯 → 只影響理解。**
**每一輪新問題的影響半徑都比前一輪小一個層級。**

### 【判斷】結論:**收斂中,但收斂的是嚴重度,不是類型**

🔴 **同一個形狀每一輪都再出現一次**:
「**規則寫在一個不會產生輸出的位置**」——
R1 存進沒人讀的欄位 / 閘門比錯對象;R2 只寫在錯誤訊息裡;R3 只寫在 docstring 與執行訊息裡。
**三輪三次,類型零收斂。**

那為什麼嚴重度還是掉得這麼快?因為**每一輪他們都留下一支帶真案例的對照腳本**
(`_control_prereg_title` / `_control_display_vs_facts` / `_control_orphan`),而那些對照會累積。
**在收斂的是「同一個錯誤下次會被自家對照抓到」的覆蓋率,不是「不再犯這個錯」。**

⇒ **【判斷】我認為現在不需要結構性改動,再修一輪就好** —— 但理由要講清楚,不是因為它變乾淨了,
而是因為**剩下的那一件不影響任何數字**,而累積的對照套件已經接得住這一類的下一次。

**如果要做一件結構性的,只值得做這一件**:
**任何描述閘門行為的文字(docstring / 錯誤訊息 / 判準檔),必須指名它的對照腳本;
而對照腳本的案例清單就是那個規則的唯一定義。** 這會把「宣稱與程式不同步」從一個
每輪重犯的類型,變成一個**缺漏時會產生輸出**的東西 —— 也就是這條線一整晚在對別的東西做的事,
只是還沒對「宣稱」本身做。

### ⚠️ 但這個「收斂」只涵蓋一層,而那不是歷史事故最多的那層

**三輪全部驗的是稿、事實、判準、發布路徑、量測 —— 沒有一輪碰到影像。**
6 支至今**未渲染**(`reels/` 仍是舊的 14 個目錄)。

而這條線在**影像層**的歷史事故清單是三輪裡最長的:版面重疊(逐元素驗四邊全綠而兩欄相撞 22×10 畫素)、
黑底黑字(色塊高度寫死,行數 ≥6 首尾兩行消失,grit 的判決卡少了主詞)、
揭露時序偏移(已上線的 Dunning-Kruger 畫面 `r = 0.28` 而旁白正唸「minus 0.05」,六支中招)。

⇒ **不要把「三輪收斂」讀成「快好了」。收斂的是已經看過三遍的那一層;
從沒被看過的那一層,歷史命中率是三類全中。**

---

## 3-8. 一句話結論

# 我這一關通過了。不能發,是因為片子還不存在。

**擋路件:零。** 前兩輪擋下的八件全部修好,我逐件獨立重驗;本輪新長出來的一件
(`window_readout.py` 的說明與實作不一致)**不影響任何數字、不擋發布**,但要在引用它的讀數之前修。

**新長出來的 vs 舊的沒修好 —— 對執行線的區分:**

- **舊的沒修好:0 件。** ①②③④⑤⑥ 六件加第二輪兩件,全部驗過修好,含我自己造的陽性對照。
- **新長出來的:1 件**,且是三輪以來第一件**不影響任何輸出數字**的。

**發布前仍缺、而且從沒做過的兩步:**

1. 🔴 **渲染 → 逐格抽幀人工看片**。這一層零輪驗證,而它是歷史事故最密的一層。
2. **量實際片長**:`focus_techniques` 46 秒 / `how_to_remember_what_you_read` 47 秒,
   硬帶 35~50,**兩支都貼上界**,很可能要改稿重渲(改了就要重跑本輪全部閘門)。

執行時的兩條硬提醒不變:**`--only` 必須帶 `--limit 6`**;
**`publish_shorts.py:844` `privacyStatus` 寫死 `public`,一上傳就是公開,沒有兩段式。**
