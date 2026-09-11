# ch3 轉型研究重抽 —— 官方 Data API,7 query × 3 輪(2026-09-12)

> **狀態:判準表與事前登記(看到任何資料之前寫定並 commit)。結果段落在三輪跑完後才填。**
> 派工:sec ch. 督導 wF:p7(派工單 `dispatch_wA2_remeasure.md`,2026-09-12)。
> 起點:`docs/ch3-revival-state-2026-09-09.md`、`docs/ch3-pivot-directions-2026-09-09.md`(下稱「原文件」)。

## 為什麼要重抽
原文件每個數字都是**單次抽樣**,而且產生它們的儀器是爬 YouTube HTML(ToS III.E.6,已停、已刪)。
原文件自己列的限制②是「同 query 半小時就變組成」,它最強的對照(`how to manifest` 和 `is manifestation real`
贏同一支片)也被總督導同日獨立抽樣推翻。**這份文件量的是重現率,不是要證明原文件對或錯。**

## 儀器
- 工具:`scripts/ch3_remeasure.py`。**只用** `search.list` / `videos.list` / `channels.list`;不用 yt-dlp、不抓任何 youtube.com HTML。
- 憑證:`yt_ch2/token.json`(youtube.readonly),程式開頭斷言 client_id 前綴 = `881902283633`,不符就中止。
- 取樣參數(三輪固定,每輪落盤):`type=video`、`order=relevance`、`regionCode=US`、`relevanceLanguage=en`、
  `maxResults=50`、`publishedAfter` = 該輪開跑當下往前 365 天。報表以**前 10 名**對照原文件,另附前 20 / 前 50。
- 判準(照原文件):**訂閱 <150,000 且 v/s ≥3 且 觀看 ≥50,000** = 勝出。分母 = 小頻道(訂閱 <15 萬且可見)。
  `hiddenSubscriberCount=true` **不進分母也不算勝出**,另列;videos.list / channels.list 查不到的列標「缺資料」,也不進分母。
- ⚠️ v/s 用的是**今天的**訂閱數,片發布當時的訂閱更少 ⇒ v/s 是偏低估計(對小頻道勝出是保守方向)。
- ⚠️ API 分不出 Short:長度 ≤60 秒標 Short,61–180 秒標「≤3 分(API 分不出)」,>180 秒標長片。
- 原始資料:`D:\yt_nonauth_data\ch3_remeasure_2026-09-12\r{n}_{YYYYMMDD}T{HHMM}Z.json`(不進 repo)。
  search / videos / channels 的**原始回應原樣保存**;`--report` 每次都從原始回應重算每一列,
  與落盤的列不一致會印警告 ⇒ 第三方可以只靠這些 JSON 從零重算每個勝出判定。

### 每輪都會產生輸出的檢查(不是「有事才響」)
1. 判準對照(任一 FAIL 中止、不打 API):108 訂閱 / 3,542 觀看 **必須被擋**;29,000 / 3,061,295 **必須勝出**;
   hidden **必須不計入**。三條走的是真正計數的那支 `tally()`,不是另寫一份。
2. 分類規則對照(總督導 09-12 指定,任一 FAIL 中止):見下方「規則對照」表,14 條。
3. `publishedAt < publishedAfter` 的違反數(search 與 videos 兩邊任一早於都算;期望 0)。
4. 每個 query 實際回傳筆數(**沒翻到 = 未讀到,不是 0 勝出**)。

### 預算(寫在程式裡)
- 研究帳 `research_ledger.json`:每配額日(太平洋時間;夏令台北 15:00 換日)上限 **2,000**;
  開一輪前要「本日研究已用 + 714 ≤ 2,000」且「共用帳 `quota.remaining()` − 714 ≥ 8,500」,否則拒跑並印原因;
  **每一次呼叫前**再檢查一次硬上限。
- 每次呼叫後 `quota.spend(cost, "research/remeasure r{n} {query}")`;失敗的呼叫照全價記;
  403 quotaExceeded → `quota.note_exhausted()`,停,不重試。
- 🔴 **對帳的權威來源是研究帳**:`quota.spend()` 沒有鎖,和發布端同時寫可能掉一筆。
  每輪落盤前後兩本帳的讀數與 `quota.report()` 原文;兩本對不上會寫在下面「對帳」段。
- 排程:r1 ≈ 台北 09-12 02:30(配額日 09-11)/ r2 ≈ 08:30(配額日 09-11)/ r3 ≈ 15:30(配額日 09-12)。
  程式內建時間閘:距上一輪**結束**(落盤時間戳)<2 小時拒跑。

## 🔴 判準表(分類規則)—— 看到第一輪結果之前寫定
規則只看**標題**(另一需求另看頻道名);**第一條命中即停**;每一列都附命中的規則編號與字詞。
本表與 `scripts/ch3_remeasure.py` 的 `POSTURE_RULES_DOC` / `OTHER_RULES_DOC` 逐字相同,實作是同檔的 regex。
**r1 之後規則一行都不改。** 規則分錯的,另列「人工複核異議」欄,**計數一律照規則**。

### 姿態(第一條命中即停)
| 規則 | 類別 | 命中條件 |
|---|---|---|
| P1 | 其他(音訊/冥想/肯定語) | 標題含 affirmation / subliminal / meditation / guided / hypnosis / binaural / Hz / frequency / ASMR / music / playlist / lofi / white noise / sleep sounds |
| P2 | 第一人稱實測 | 主詞是 I(I tried / I tested / I did / I spent / I used / I followed / I read / I quit / I manifested … 等經驗動詞)、my experience / my results / my journey / my N-day、How I、Why I、What happened when I、(it worked) |
| P3 | 迷思清單 | myth(s) / lies / lied to / misconception(s) / wrong about / stop believing / isn't true / not true / overrated |
| P4 | 裁決 | 子句開頭的 is/are/does/do/can… + real/work/true/legit/fake/scam/myth/worth it/effective(排除 do this/these/that);debunk / scam / pseudoscience / the truth about / real or fake / exposed / what science says;或整個標題是 is/are/does/do/can… 開頭、? 結尾的問句 |
| P5 | 篩過的方法 | 證據/篩選詞(that actually work / actually works / backed by science / science-based / evidence-based / proven / scientifically / according to science / neuroscientist / psychologist / Harvard / Stanford / studies show)**且**有方法字(見 P6) |
| P6 | 純方法 | 方法字:how to / ways to / tip(s) / technique(s) / method(s) / strategy / step(s) / hack(s) / habit(s) / trick(s) / guide / system / rule(s) / secret(s) / routine / formula / framework / exercise(s) / do this / try this / rewire / mistake(s) / advice / lesson(s);或標題以祈使動詞開頭(Stop / Do / Try / Use / Learn / Remember / Improve / Rewire / Memorize / Manifest / Never / Don't …);或「to + 目標動詞」(to burn / to remember / to improve / to manifest / to focus …)、like a pro |
| P7 | 未分類(只有證據詞) | 只命中 P5 的證據詞,沒有方法字 —— **不落到任何預設類別**,報表計數,勝出片由人工補判並標明 |
| P8 | 未分類 | 以上皆否 —— 同上 |

### 另一需求(第一條命中即停)
| 規則 | 類別 | 命中條件 |
|---|---|---|
| O1 | 其他(非英語受眾) | 標題字母中非拉丁文字 ≥30%,或標題/頻道名含 Hindi / Urdu / Tamil / Telugu / Bangla / Bengali / Marathi / Español / Português / Tagalog / Arabic |
| O2 | ESL 英語學習 | 標題或頻道名含 English / ESL / IELTS / TOEFL / TOEIC / Graded Reader |
| O3 | 其他(特定考試) | 標題含 SAT / ACT / MCAT / USMLE / GCSE / NEET / JEE / UPSC / CBSE / A-Level(大小寫敏感) |
| O4 | 其他(宗教觀點) | 標題含 Bible / God / Jesus / Christ / Christian / church / pastor / sermon / scripture / Allah / Islam / Quran / sinful / occult / demonic |
| O5 | 其他(音訊/冥想) | 同 P1(需求是『聽』,不是『學怎麼做』) |
| O6 | 單本書摘要 | 標題含 summary / summarized / audiobook / book review / animated book,或點名一本書(Atomic Habits / Deep Work / Think and Grow Rich / The Power of Habit / Thinking Fast and Slow / How to Win Friends / Psychology of Money / Make It Stick / Moonwalking with Einstein / Ultralearning / 7 Habits / Can't Hurt Me / Power of Your Subconscious Mind / Feeling Is the Secret / Dopamine Nation / The Magic of Thinking Big);或頻道名含 book / summar / audiobook |
| O7 | 產品廣告 | 標題含 preview / app / course / masterclass / free trial / use code / coupon / webinar / sponsored / free pdf / download |
| O8 | 不確定 | 頻道名(≥4 字元)原樣出現在標題裡(可能是自家產品,也可能只是署名 —— 不猜);或標題缺漏 |
| O9 | 未分類(無需求字詞命中) | 以上皆否。**沒命中不等於「無」**(沒看到證據≠證明沒有)⇒ 不落到「無」這個預設類別;報表計數,勝出片由人工讀標題/頻道名補判(無 或其他)並標明是人工判的 |

### 規則對照(每輪開跑前印 PASS/FAIL,任一 FAIL 中止)
commit 前實跑 `--check`:**14/14 PASS**(第一版規則下「Simple Science to Burn Fat Like a Pro」落到未分類 → 加了 P6 的「to + 目標動詞 / like a pro」後才過;這是 r1 之前唯一一次改規則)。

| 欄位 | 標題(/頻道) | 期望 |
|---|---|---|
| 姿態 | I Tried the World's Simplest Productivity Hack for 1 Year | 第一人稱實測 |
| 姿態 | Simple Science to Burn Fat Like a Pro | 純方法 |
| 姿態 | 30 Years Of Law Of Attraction Advice In 15 Minutes | 純方法 |
| 姿態 | How to REMEMBER Absolutely Everything | 純方法 |
| 姿態 | Dopamine Detox: Cure or Scam? / Manifestation: cure or scam? / Cold Showers: Cure or Scam? | 裁決 |
| 另一需求 | Learn English Through Story - Graded Reader;Learn English with a Short Story(/Story Time);Graded Reader Level 2: The Memory Palace(/Stories Channel) | ESL 英語學習 |
| 另一需求 | Memory palace training with memoryOS preview(頻道空白 / memoryOS 各一次) | 產品廣告 |
| 姿態 | A Quiet Afternoon in Kyoto | 未分類(未分類那條路的陽性對照) |
| 另一需求 | How to REMEMBER Absolutely Everything(/Some Channel) | 未分類(無需求字詞命中) |

📌 已知的規則邊界(事前寫下,不事後修):「I'm begging you to manage your time」在 P2 **不**算第一人稱實測
(I'm begging 不是經驗動詞),會落到 P6 純方法;總督導 09-09 把它算成第一人稱。① 的答案會把兩種算法並列。

## 事前登記:每個結論怎樣算重現
每一條在每一輪各判一次(前 10 名、規則分類);**3/3 輪成立 = 3 次都重現;1–2 輪 = 部分重現;0 輪 = 未重現**。
某輪無法判(例如該輪沒有勝出片可算比例)記「不可判」,不算重現,另註。強度數字(最佳 v/s、中位數)**只並列不判**。

| # | 原文件結論 | 原報告 | 總督導複驗 | 本次每輪的成立條件 |
|---|---|---|---|---|
| C1 | `dopamine detox` 小頻道勝出 | 3/3 勝出,105.6× | — | 前 10 勝出 ≥1 |
| C2 | `productivity methods that actually work` 小頻道普遍勝出 | — | 7 小 / **6 勝**,46.0×(1,495,249) | 前 10 勝出 ≥3 且 ≥ 小頻道數的一半 |
| C3 | `study tips backed by science` 0 勝出 | — | 9 小 / **0 勝** | 前 10 勝出 = 0 |
| C4 | 措辭層級:「that actually work」≫「backed by science」 | — | 6 vs 0 | 同輪 C2 勝出 − C3 勝出 ≥3 |
| C5 | `how to remember what i read` 有小頻道勝出 | 5 小 / 4 勝,最佳 27.0×,勝出中位 1,009,627 | 最佳 12.3×,中位約 57 萬(前 12) | 前 10 勝出 ≥1(最佳 v/s、中位並列) |
| C6 | 同上那組有 ESL 混淆 | 未提 | 4 勝裡 2 個 ESL | 前 10 勝出裡 O2(ESL)≥1 |
| C7 | `is manifestation real` 的勝出者是方法形狀 | 有勝出(rxchelle) | 1 勝:27,200 → 297,315《30 Years Of Law Of Attraction Advice…》 | 前 10 勝出 ≥1 且其中 0 支是 P4 裁決 |
| C8 | 兩個 manifest query 贏同一支(rxchelle 1,103,741) | 是 | **否**,0 重疊 | 前 10 勝出交集 ≥1;另報 rxchelle 是否同時在兩邊前 10 |
| C9 | `how to manifest` 有小頻道勝出 | 是 | **0 勝** | 前 10 勝出 ≥1 |
| C10 | 姿態階梯的承重部分:方法贏、裁決不贏 | E 格 14 query / 41 小頻道 / 0 勝 | — | 七個 query 前 10 勝出合計:裁決(P4)= 0 且 純方法+篩過的方法 ≥1;A/B/C/D 各格最佳 v/s 並列 |
| C11 | `productivity…` 勝出約一半是第一人稱 | — | 6 勝中至少 3 | 第一人稱(P2)/ 勝出 ≥ 40% |
| — | `how to improve memory` | 從未量過 | — | 首次讀數,不判重現 |

## ⚠️ 不可比之處(先寫)
- 原儀器是 **HTML 排序**(地區、登入狀態、個人化都未知);總督導複驗是官方 API 前 12;本次是 **API relevance + regionCode=US + relevanceLanguage=en、前 10**。
  ⇒ 本次和原報告之間的差異**可能是儀器差異,不是時間差異**;三輪之間的差異才是同一儀器下的時間差異。
- 原報告與總督導複驗的「近一年」起點不同(各自以抓取當天往前算),本次每輪也各自往前 365 天。

## 資料保存
🔴 **競品資料屬 Non-Authorized Data(ToS III.E.4.d),保存上限 30 天,2026-10-12 前要刪或重抓。**
原始 JSON 在 `D:\yt_nonauth_data\ch3_remeasure_2026-09-12\`(同目錄 README 寫同一個期限),不進 repo。

## 結果
(三輪跑完後填:輪次與對帳、每個 query × 每輪、C1–C11 重現標記、①–⑤ 的答案、兩處分歧的直接回答、未分類勝出片的人工補判。)
