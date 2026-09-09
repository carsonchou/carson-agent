# 交棒檔 — wB:p1 第四棒(/clear 前)

> 寫這份的理由:context 已到 **~194K**,`dispatch.md` 的線是 **200K**(絕對 token,不是百分比)。
> 交棒優於 compact。監督:wF:p3。
>
> **規格仍以 `docs/ops/2026-09-09_ch3_recurrence_test_spec.md`(`5bab32f6`)為準,不要拿本檔當規格。**
> 本檔只回答:**這一棒做完了什麼、下一棒從哪一步接、有哪些東西只活在逐字稿裡。**

---

## 〇、只活在逐字稿裡的東西:**沒有**

這一棒所有結論都已 commit。下一棒 `/clear` 之後照 §三 的步驟直接接。

---

## 一、任務進度:**卡在回報點 ②(發布前的獨立驗證)之前一步**

三個回報點裡:

| 回報點 | 狀態 |
|---|---|
| ① 事前登記檔 commit 後 | ✅ **已回報**(`dacddd8e`,2026-09-09T17:48:05+08:00) |
| ② 獨立驗證通過、發布之前 | ⬜ **還沒到**。缺:渲染 + 人工看片 + 派獨立驗證員 |
| ③ 發布之後 | ⬜ 還沒到 |

🔴 **到目前為止零對外動作。** 沒有上傳、沒有呼叫過任何 YouTube API、沒有碰 crontab。

---

## 二、這一棒做完的(**全部已 commit,不要重做**)

| commit | 件 |
|---|---|
| `dacddd8e` | **事前登記檔** `docs/ch3_recurrence_test_prereg_2026-09-09.md`(產製之前,blob `0a1b07b1`) |
| `2f7e06dd` | 產線的姿態寫死在兩層 → 副標升格成 `reel.captions.*`(無預設值)+ `reel_gate` 擴成 `papers` 形狀 + 產製前快照 |
| `6bfb7dbd` | 畫面印的數字可以和旁白唸的不一樣而沒人會叫 → 補 orphan 閘門(陰性+陽性對照都在 `ch3_lab/_control_orphan.py`) |
| `9193a63e` | **6 支的 entry 與稿**(全部手寫)+ `_check_claim_values.py`(value 必須在自己那句 verbatim 裡) |

### 2.1 最重要的那一件(引用時請連理由一起帶)

**產線把「裁決」這個姿態寫死在兩層,而兩層都不會報錯。**

1. `make_reel.py` 三張卡的副標原本寫死成
   `you have heard this one` / `so somebody checked` / `what came back`
   —— 那是「有人去把它重測了」的框架。
   **B 臂走同一份程式碼,標題對、旁白對、數字也對,只有畫面上那一行把它講回裁決片。**
   如果沒抓到,這個測試會產出 6 支 E 臂的片,然後把結果讀成「姿態沒有差別」——
   一個看起來完全正常的**空對照**。
2. `publish_shorts.reel_gate()` 的 DOI 那條寫死成「原始 + 重測**兩篇**」,
   方法片套進去兩邊都空、被判「沒有 DOI」擋死。

⚠️ **順帶更正一件我自己先報錯的**:第一版產線測繪回報說「產線寫死只能吃 FReD/名案,
方法形狀完全沒有路徑」。複驗後那是**講太重了** —— `make_reel.py` 只讀 `E["reel"]`
與 `twist_rows(E)`,而 `twist_rows` 是泛用的 `{label, what, es, es_kind}`,
`audit()` 的白名單也是泛用的結構化欄位掃描。真正卡住的只有上面兩層。

### 2.2 6 支的實況(臂別與逐字標題與 `dacddd8e` 一字不差)

| slug | 臂 | 逐字標題 | 估長 |
|---|---|---|---|
| `study_techniques` | B | The Only Study Techniques That Actually Work | 37s |
| `how_to_remember_what_you_read` | B | How to Remember What You Read: 3 Methods That Actually Work | 45s |
| `focus_techniques` | B | Focus Techniques That Actually Work When Your Brain Won't Cooperate | 40s |
| `if_then_plans` | B | Productivity Methods That Actually Work Without a System | 38s |
| `learning_styles` | E | Learning Styles Are Not Real | 42s |
| `pomodoro` | E | The Pomodoro Technique Does Not Do What You Think | 42s |

⚠️ **估長是字數 ÷ 2.6,不是量出來的。** `make_reel.one()` 渲完會量實際值,
**不在 35~50 秒就回非零並要求改稿重渲**。`how_to_remember_what_you_read` 估 45s
是六支裡最貼近上界的,**它最可能是那個要改稿的**。

**兩臂的資訊架構刻意做成一模一樣**(主張 → 誰量的 → 量到多少 → 收束 → 提問),
差別只在三張卡的副標與措辭。⇒ 姿態是唯一被操縱的變數;若兩臂連版面都不同,
結果就分不出是姿態還是版面。

---

## 三、下一棒從這裡接(順序不可換)

```
cd D:\carson-agent\ch3_lab
# 1) 渲染六支。一支約 3.5 分鐘,共約 21 分鐘。TTS 是本機 Kokoro,不需外部 key。
python make_reel.py --slug study_techniques
python make_reel.py --slug how_to_remember_what_you_read
python make_reel.py --slug focus_techniques
python make_reel.py --slug if_then_plans
python make_reel.py --slug learning_styles
python make_reel.py --slug pomodoro
#    🔴 每一支都要看 rc。片長不在 35~50 秒會印 ⛔ 並回 1 —— 那是要改稿重渲,不是警告。

# 2) 🔴 **真的把畫面開起來看過六支**(ch3_lab/README.md 付過學費的那條:
#    曾經整批渲染成功、時長正確、mp4 產得出來,而畫面上一個字都沒有)。
#    每支至少看:第 0 幀(它就是縮圖)、turn 那段的表格、verdict 卡。

# 3) 補上還沒做的那個陽性對照(**沒補之前不准發**):
#    故意從某一支的說明欄刪掉一個 DOI,確認 reel_gate 會擋。
python publish_shorts.py --list          # 唯讀,不連網(yt=svc() 建在 --list 分支之後)
python publish_shorts.py --dry-run       # 唯讀,不連網(此分支在建 OAuth client 之前就 return)

# 4) 人工看過之後才標 VERIFIED(沒這步,那六支不會進發布清單)
python mark_verified.py <slug>

# 5) 🔴 派 fresh-context 獨立驗證員(找碴視角),過了才回報點 ②
# 6) 發布(見 §四,**一發就是公開,沒有兩段式**)
```

---

## 四、🔴 發布前必須先知道的三件

1. **`publish_shorts.py` 沒有 `--privacy` 也沒有 `--flip`。**
   `insert_one()` 把 `privacyStatus` 寫死成 `"public"`(`ch3_lab/publish_shorts.py:844`,已自己複驗)。
   **沒有 unlisted 過渡,一發就是公開。** README 那句「`upload.py --flip public`」
   講的是**長片線**,對 Shorts 不適用。
   ⇒ 這正是「有授權也不免驗」為什麼在這件事上是硬的:發出去就回不來了。
2. **指名發,不要用 `--limit`。**
   `python publish_shorts.py --only <key1>,...,<key6>` ——
   `--limit 6` 取的是排序後前 N 支,**不保證是你驗過的那六支**,而 `reels/` 裡另有 14 支舊片。
3. **配額**:`python quota.py` 實測 2026-09-09 已用 **0 / 可用 20,500**;
   6 支 Short 約 **9,636~9,936**(約 47%)。吃的是 ch2/ch3 那本帳(專案 **881902283633**),
   **不影響主頻道**(524513894332)。

---

## 五、給獨立驗證員的驗收條件(規格 §6 的三件,加上這一棒新增的兩件)

規格原本要求的三件:

1. **6 支是新產的,不是舊庫存改標題。**
   機械查證法:`ch3_lab/facts/_prereg_before_snapshot.json` 是**產製前**的快照
   (14 支 reels + 33 支 shorts,逐支 sha256 + mtime)。新片不在名單裡;舊片的 sha256 不該變。
2. **事前登記檔在產製之前 commit。**
   `git log --format=%aI -1 dacddd8e -- docs/ch3_recurrence_test_prereg_2026-09-09.md`
   → `2026-09-09T17:48:05+08:00`,拿去對六支 mp4 的 mtime。
3. **常態排程仍是註解狀態。**
   `youtube_channel/deploy/crontab.txt` 第 775/776/777 行,三行都要以 `# ` 開頭。
   (開工前與這一棒結束時都逐字驗過;唯一未註解的 ch3 行是 `:784` 的 `ch3_health.py`,唯讀健檢。)

這一棒新增、**必須一起驗**的兩件:

4. **`reel_gate` 的 `papers` 分支有陽性對照。**
   我改了一道會擋產出的閘門,而**改動的差集不是閘門的定義域**
   (memory `gate-verification-population`)。要驗的母體是**全部 20 集**,不是新增的 6 集。
   已做:14 集 `--script-only` 全過(零誤擋);orphan 閘門陰性+陽性對照在 `_control_orphan.py`。
   **還沒做**:`reel_gate` 的 `papers` 分支要有一次「刪掉一個 DOI 就會擋」的實證。
5. **`_check_claim_values.py` 的逃生門有沒有被濫用。**
   🔴 **這道閘門自己有一個洞,我講在前面**:一旦某條 claim 用了 `value_in_verbatim_as`,
   **value 本身就不再被機械檢查**(實測把 value 從 1 改成 7、字串仍對得上,它不會叫)。
   目前有兩條用了(E1.c1 `only one study`、E2.c1 `Ninety-four`),**那兩條要人看**。
   另有一條 `value_is_derived` 的(E2.c3 = 0),已標 `do_not_speak`,
   **確認旁白裡沒有唸到它**。

驗證員的 prompt 要用**找碴視角**:「試圖證明這 6 支是舊庫存 / 登記是事後補的 /
常態排程被打開了 / 旁白裡有一個數字是查不到的 / 兩臂的差別不只有姿態」,
不是「確認做完了」。

---

## 六、還沒動、需要拍板或等回覆的

1. 🔴 **§0.3 那份轉抄進來的核准(`drill regression 那支排進排程`)——沒動,連準備都沒做。**
   wF:p3 已去問 Carson 本人,**還沒回**。原文逐字保存在規格檔 §0.3。**它只是暫緩,不是取消。**
2. **`publish_shorts.py` 一發就公開這件事**,如果 wF:p3 或 Carson 想要先 unlisted 再放行,
   那需要改程式(加 `--privacy`),**而那是另一件事,不要順手做進這一棒**。
   我的判斷:測量窗要乾淨,unlisted → public 的翻轉本身可能影響分發,**直接公開是對的**;
   但這一句是判斷,不是實測。

---

## 七、方法論(這一棒付過學費的)

1. **subagent 的回報要複驗。** 第一版產線測繪把封鎖程度講重了一級
   (「完全沒有路徑」其實只有兩層卡住),我照它的結論會多做好幾小時不必要的事。
   ⇒ **承重的回報,自己去看那幾行。**
2. **heredoc 吃掉 `\n`,第七次。** 同一個修改用 heredoc 送,寫出語法壞掉的檔案;
   改成**先寫檔再執行**就過。這一棒之後所有 patch 都走檔案。
3. **「全綠」有可能是「什麼都沒跑」。** 我用 `for ... | grep -E "⛔|溯源"` 掃 14 集,
   輸出是 14 行空白 —— 看起來像全過,實際是每一支都在 import 期就炸了。
   ⇒ **迴圈式檢查要印出「有跑到」的正向證據**,不要只印匹配到的東西。
4. **閘門要有陽性對照,而且陽性對照要用真案例。** 這一棒每道新閘門都補了
   「把被測的機制弄壞,對照會不會跟著失敗」,答案都是「會」。
5. **多 session 同 repo**:這一棒進行中另外三個 session 也在 commit
   (`d07c9bb2` / `f358a4b6` / `4aa5b4eb`)。**HEAD 不是我的**,報 hash 給別人前先確認。
