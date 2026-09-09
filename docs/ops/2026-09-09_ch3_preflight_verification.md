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
