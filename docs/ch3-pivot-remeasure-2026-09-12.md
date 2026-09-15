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
(I'm begging 不是經驗動詞),會落到 P6 純方法;總督導 09-09 把它算成第一人稱。

### 🔴 規則姿態 vs 人工姿態 —— 兩欄並列(總督導 09-12 追加,規則不動)
P2 只認「I + 經驗動詞清單」,偏誤方向是**少算第一人稱 ⇒ 高估無臉頻道拿得到的份額**,正好是方向 1 預期值那題的危險方向。
所以結果段的每一支勝出片都並列兩欄:

- **規則姿態**:上表 P1–P8 的輸出,原樣,**所有計數(C1–C11)照這欄**。
- **人工姿態**(我讀標題與頻道名判,標題下方寫一句理由)。判準一句話:
  **標題的主詞或說話者是創作者本人 —— 講自己的經驗、試驗、結果、懇求或告白(I tried / I'm begging you / my … / how I …)= 第一人稱;
  其餘照 P3–P6 各類的定義讀語意判,不看字詞清單;讀不出來寫「不確定」。**
- 問題 ①(`productivity methods that actually work` 勝出片裡第一人稱佔幾支)**兩種數都報**,
  並附七個 query 全部勝出片的「規則 vs 人工」**一致率與不一致清單**。
- 人工欄只是第二種讀法,不回頭改規則;總督導另派 fresh-context 查證員獨立人工標註同一批做第二意見。

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
🔴 **競品資料屬 Non-Authorized Data(ToS III.E.4.d),保存上限 30 天 ⇒ 2026-10-12 到期。**
原始資料在 `D:\yt_nonauth_data\ch3_remeasure_2026-09-12\`(不進 repo;同目錄 README 寫同一份規則)。

到期時**分兩類處理,不是整個目錄刪掉**。理由一併寫在這裡 —— 30 天後動手的人不會記得今天的討論,只會照字面做:

| 檔案 | 到期動作 | 為什麼 |
|---|---|---|
| `r1_*.json`、`r2_*.json`、`r3_*.json` | **刪除**,或用同一支工具重抓(重抓就重新起算 30 天) | 內容是他人的公開資料(影片標題、頻道名、訂閱數、觀看數)= Non-Authorized Data,受 30 天上限 |
| `run_r*.log` | **刪除** | log 逐行印了競品影片標題與頻道名,同樣是他人資料 |
| `research_ledger.json` | **保留** | 我們自己的配額帳,不含任何第三方資料;刪掉會毀掉本文件數字的稽核軌跡 |
| `README.md` | **保留** | 我們自己寫的說明,不含第三方資料 |

原始資料一刪,本文件的數字就再也重算不出來。所以結果段裡留一張**三個 `r*.json` 的檔名 + sha256 + 位元組大小 + 抓取時間**指紋表:資料依 ToS 刪除之後,後人仍驗得出當時算的是哪一批檔(也接得上驗證員那條指紋鏈)。

## 結果

> 填寫:wA:p2,2026-09-15 台北 15:44(`date` 取得)起,三輪都落盤之後才寫。所有數字出自 `python scripts/ch3_remeasure.py --report`(從原始回應重算、exit 0、stderr 除 Python 3.9 FutureWarning 外無輸出)與下方各處註明的指令;姿態「人工」欄是我讀標題判的,**計數一律照規則欄**。
> 🔴 本段在 fresh-context 驗證員複算之前**不是結論**;在那之前不對外引用任何數字。

### 0. 先講清楚這次量到的是什麼(判準替換,commit `95d134fb`)

r3 原定 2026-09-14 15:34(配額日 09-14)沒跑成(session-only 排程隨 session 停擺消失),觸發事前落檔的判準替換版本
`docs/ch3-remeasure-criterion-replacement-2026-09-14.md`(commit `95d134fb`,寫於 09-14 10:1x,早於知道 r3 跑不跑得成)的**分支 B**:
r3 唯一一次順延到 2026-09-15 15:34(配額日 09-15),工具、判準、規則都不動。

**本次量到的是日間變異。**
**同日內的儀器噪音未測。**(這是空缺,不是零:沒有任何一對樣本落在同一配額日內,所以「儀器本身同一天抽兩次會差多少」這個數不存在,不能讀成 0。)

- **取樣間隔偏離(單獨一行)**:原設計間隔 6 小時;實際 r1→r2 為 2 天 6 小時 41 分(約 2 天 7 小時,09-11T18:30:06Z → 09-14T01:11:11Z),r2→r3 為 1 天 6 小時 23 分(09-14T01:11:17Z → 09-15T07:34:10Z)。09-14 裁決文字裡的「r2→r3 約 6 小時」是以分支 A 為前提寫的,分支 B 啟用後**不成立**,這裡照實際寫。
- 三輪配額日:**09-11 / 09-13 / 09-15**。
- 🔴 **不可歸因**:r1→r2 相隔 2 天 7 小時,兩輪之間的差異分不出是「儀器本身不穩」還是「搜尋結果真的換了」⇒ r1/r2 這一對只能當**保守下界**。原裁決「穩定度宣稱只准掛 r2/r3」的前提是 r2/r3 相隔約 6 小時;分支 B 下 r2/r3 也相隔 1 天 6 小時,**同樣不可歸因** ⇒ 本文件**不做任何「儀器穩不穩 / 漂移多少」的宣稱**,三輪之間的差異一律讀成「日尺度變異的上界(含儀器噪音 + 結果集漂移,兩者分不開)」。
- **不准**把 r1/r2 或 r2/r3 任一對稱為原設計的短間隔對;原設計的短間隔對**沒有被量到**。
- 間隔拉長只會讓結果集漂移更大 ⇒ 重現率只會偏低 ⇒ 下面每一個「部分重現」都**同時受時間漂移影響**,**低重現率不能直接讀成原結論是錯的**。

### 1. 輪次與對帳

| 輪 | 台北開始 | 台北結束 | 配額日 | units | 判準對照 | 分類規則對照 | publishedAt 違反 | 工具 sha256 前 12 | status |
|---|---|---|---|---|---|---|---|---|---|
| r1 | 2026-09-12 02:30:00 | 02:30:06 | 2026-09-11 | 714 | 3/3 PASS | 14/14 PASS | 0 | `4cb942182837` | complete |
| r2 | 2026-09-14 09:11:11 | 09:11:17 | 2026-09-13 | 714 | 3/3 PASS | 14/14 PASS | 0 | `4cb942182837` | complete |
| r3 | 2026-09-15 15:34:10 | 15:34:16 | 2026-09-15 | 714 | 3/3 PASS | 14/14 PASS | 0 | `4cb942182837` | complete |

工具版本數 = 1(三輪同一支,sha256 `4cb942182837837db76c6c87e03efc5a49c805f648b7bcb9b5a44f3d0d7327de`;r3 開跑前 `git diff --stat 24749aa7 -- scripts/ch3_remeasure.py` 零 diff,blob `41625a1a7554fd42c368defb7aea6ec901f13f1d`)。每個 query 每輪都回傳 50 筆(沒有「未讀到」)。

| 輪 | 研究帳 前→後 | 共用帳 remaining 前→後 | 本輪 units | 一致? |
|---|---|---|---|---|
| r1 | 0→714 | 20,500→19,786 | 714 | 是 |
| r2 | 0→714 | 20,500→19,786 | 714 | 是 |
| r3 | 0→714 | 20,500→19,786 | 714 | 是 |

研究帳(權威)`research_ledger.json` 讀回:`{'2026-09-11': 714, '2026-09-13': 714, '2026-09-15': 714}`,合計 2,142 units,每配額日都 ≤2,000、跑後共用帳都 ≥8,500。兩本帳三輪都對得上,無不一致需要記。

### 2. 原始檔指紋表

原始資料依 ToS 於 2026-10-12 刪除後,用這張表驗「當時算的是哪一批檔」。指令:`sha256sum r1_*.json r2_*.json r3_*.json`、`stat -c '%n %s' …`(在 `D:\yt_nonauth_data\ch3_remeasure_2026-09-12\`);抓取時間取 JSON 內 `fetched_utc_start` / `fetched_utc_end`。

| 檔名 | sha256 | 位元組 | 抓取時間(UTC) |
|---|---|---|---|
| `r1_20260911T1830Z.json` | `ae1cc9037d27a14fbbda2fb7aa793790729679a50677b29365ac1e671a1bbe15` | 3,260,583 | 2026-09-11T18:30:00Z → 18:30:06Z |
| `r2_20260914T0111Z.json` | `d52b407cd61eea28d7e53b218646c5e69c4f2cf0461af07e561b8ba2a87ff231` | 3,282,236 | 2026-09-14T01:11:11Z → 01:11:17Z |
| `r3_20260915T0734Z.json` | `160bdda16f8c1aeac985271f37f05aae39c471a3c58498ca2ce9de7550f59241` | 3,386,971 | 2026-09-15T07:34:10Z → 07:34:16Z |

### 3. 每個 query × 每輪(前 10;括號是前 20 / 前 50 的 小頻道/勝出)

| query | r1 小/勝 | r2 小/勝 | r3 小/勝 | 最佳 v/s(觀看)r1 / r2 / r3 | 勝出觀看中位 r1 / r2 / r3 | 前 10 跨輪交集(Jaccard)r1–r2 / r1–r3 / r2–r3 |
|---|---|---|---|---|---|---|
| productivity methods that actually work | 6/4(10/8,30/15) | 5/5(9/8,23/17) | 5/4(11/8,28/15) | 40.57×(177,680) / 134.93×(8,945,628) / 40.85×(178,519) | 679,505 / 1,186,118 / 683,787 | 8(0.667) / 9(0.818) / 9(0.818) |
| study tips backed by science | 8/0(17/2,36/7) | 7/0(17/1,38/2) | 7/0(17/1,40/3) | 小頻道最佳 54.38×(8,048)/ 55.41×(8,200)/ 56.28×(8,330),觀看都 <50,000 | — | 8(0.667) / 7(0.538) / 9(0.818) |
| how to remember what i read | 6/4(12/6,32/10) | 6/4(13/6,31/10) | 5/4(13/6,34/11) | 12.4×(1,574,748) / 12.6×(1,600,254) / 12.7×(1,613,097) | 571,896 / 575,187 / 577,170 | 9(0.818) / 9(0.818) / 9(0.818) |
| how to manifest | 3/2(6/3,17/6) | 3/2(5/3,18/7) | 3/2(5/3,18/7) | 10.48×(127,910) / 10.79×(132,753) / 11.03×(135,681) | 168,903 / 171,489 / 173,016 | 9(0.818) / 9(0.818) / 10(1.0) |
| is manifestation real | 3/1(9/1,28/5) | 3/1(10/2,29/6) | 3/0(11/1,28/5) | 10.96×(297,987) / 10.98×(298,532) / 前 10 無勝出(小頻道最佳 0.21×) | 297,987 / 298,532 / — | 8(0.667) / 9(0.818) / 8(0.667) |
| how to improve memory | 1/1(2/2,14/7) | 2/2(2/2,13/7) | 2/2(3/2,14/8) | 3.61×(498,764) / 11.02×(207,269) / 11.44×(217,339) | 498,764 / 353,904 / 359,546 | 9(0.818) / 9(0.818) / 10(1.0) |
| dopamine detox | 5/1(9/2,25/5) | 5/2(9/2,24/7) | 5/1(9/2,26/5) | 105.68×(3,075,308) / 106.0×(3,084,513) / 106.17×(3,089,689) | 3,075,308 / 1,826,872 / 3,089,689 | 8(0.667) / 10(1.0) / 8(0.667) |

hidden 訂閱:七個 query × 三輪皆 0(報表 hidden 欄)。搜尋參數三輪相同:`part=snippet, type=video, order=relevance, regionCode=US, relevanceLanguage=en, maxResults=50`(三檔 `search_params` 逐一比對相等)。

**在前 10 邊界進出、造成跨輪數字變動的列**(從原始 JSON 的 `rows[].rank` 讀出,判定三輪都是 win,變的只有名次):

| query | videoId(頻道) | r1 名次 | r2 名次 | r3 名次 | 影響 |
|---|---|---|---|---|---|
| productivity… | `h0FzoGEbMQA`(Charlene Ng,17s Short,134.9×) | 11 | 8 | 11 | r2 勝出 5、最佳 v/s 134.93× 全靠這一支 |
| is manifestation real | `fdwtHabUirM`(Trevor Emdon,10.96–10.99×) | 10 | 4 | 11 | r3 前 10 勝出 1→0 ⇒ C7 變號 |
| how to improve memory | `QbOrby9YFFI`(Dr. Sikandar Adwani,10.4–11.4×) | 18 | 9 | 9 | r1 前 10 只剩 ESL 那支 |
| dopamine detox | `w-vBOi8rmZI`(Easton Simpson,7.6–8.1×) | 19 | 10 | 19 | r2 勝出 2、第一人稱 1 |

### 4. 勝出片:規則姿態 vs 人工姿態(七個 query 三輪合併,同一支列一次;共 15 支)

**人工姿態判準(一句話)**:標題的主詞或說話者是創作者本人 —— 講自己的經驗、試驗、結果、懇求或告白 = 第一人稱;其餘照 P3–P6 各類定義讀語意判,不看字詞清單;讀不出來寫「不確定」。
**人工另一需求**:規則輸出 O9(未分類)的,人工讀標題與頻道名補判「無 / 其他(寫明)」;規則有命中的,人工只核對。

| videoId | query | 標題(節錄) | 頻道 | 勝出於(前 10) | 規則姿態 | 人工姿態 | 規則另一需求 | 人工另一需求 | 一致? |
|---|---|---|---|---|---|---|---|---|---|
| `UFidZJhxz84` | productivity | The BEST Productivity Method Ever for ADHD | Novie by the Sea | r1 r2 r3 | 純方法(P6) | 純方法 | O9 未分類 | 人工:無(ADHD 是同一需求的子受眾,不是另一需求) | 是 |
| `RYOnq73XSbo` | productivity | Best ADHD Productivity Method(33s Short) | Novie by the Sea | r1 r2 r3 | 純方法(P6) | 純方法 | O9 | 人工:無(同上) | 是 |
| `NZD5IFpyDcE` | productivity | I Tried the World's Simplest Productivity Trick (it worked) | Simple Lucas | r1 r2 r3 | 第一人稱(P2) | 第一人稱 | O9 | 人工:無 | 是 |
| `sPYxSrsH04I` | productivity | I Tried the World's Simplest Productivity Hack for 1 Year (it worked) | Cormac Taylor | r1 r2 r3 | 第一人稱(P2) | 第一人稱 | O9 | 人工:無 | 是 |
| `h0FzoGEbMQA` | productivity | 4 AM PRODUCTIVE morning routine before the work day(17s Short) | Charlene Ng | r2 | 純方法(P6:routine) | **不確定** —— routine 類短片常是創作者自己的日常,但標題沒有主詞,讀不出是在示範自己還是教方法 | O9 | 人工:無 | 否 |
| `zYr2XZcpNhM` | remember | How to Remember Everything You READ (For Life) — In 2 Minutes | BeyondBeing | r1 r2 r3 | 純方法(P6) | 純方法 | O9 | 人工:無 | 是 |
| `nbxi7_I09fI` | remember | Memorize Anything So Fast It's Almost Unfair | BetterU | r1 r2 r3 | 純方法(P6) | 純方法 | O9 | 人工:無 | 是 |
| `mzQlJSn3Q80` | remember + improve memory | How to Remember Everything / Graded Reader / Learning & Memory Skills | English With Ethan | r1 r2 r3(兩個 query 都有) | 純方法(P6:How to) | **不確定** —— 標題同時帶方法字與「Graded Reader」教材標記,讀不出是在教記憶方法還是英語分級讀物 | ESL(O2) | 核對:ESL,同意 | 否(姿態) |
| `HTV1_gIfRDM` | remember | Why You Don't Remember What You Read | Closed Stacks | r1 r2 r3 | **未分類(P8)** | **人工補判:不確定** —— 「為什麼你記不住」是原因解說,不是方法、不是迷思清單、也不是裁決,P3–P6 無一類對得上 | O9 | 人工:無 | 不可比(規則未分類) |
| `2tON1mv77Sk` | how to manifest | How to manifest your desires TONIGHT | Peyton is Magnetic | r1 r2 r3 | 純方法(P6) | 純方法 | O9 | 人工:無 | 是 |
| `L8OYTCRbKgA` | how to manifest | How I Manifested The Impossible... Even with doubt. | Cristina Bold | r1 r2 r3 | 第一人稱(P2) | 第一人稱 | O9 | 人工:無 | 是 |
| `fdwtHabUirM` | is manifestation real | 30 Years Of Law Of Attraction Advice In 15 Minutes (I Wish I'd Known This Then) | Trevor Emdon | r1 r2 | 純方法(P6:Advice) | **第一人稱** —— 括號「I Wish I'd Known This Then」是創作者對自己 30 年經驗的告白,說話者是本人 | O9 | 人工:無 | 否 |
| `QbOrby9YFFI` | improve memory | 7 Brain Exercises to Improve Memory, Balance & Focus / Neurologist Explains | Dr. Sikandar Adwani | r2 r3 | 純方法(P6:Exercises) | **篩過的方法** —— 「Neurologist Explains」是權威/證據背書;P5 字詞清單只有 neuroscientist 沒有 neurologist,規則因此落到 P6 | O9 | 人工:無 | 否 |
| `KXvyd-tkrmc` | dopamine detox | How to Rewire Your Brain to Enjoy Discipline (Dopamine Detox Explained) | HustleCore | r1 r2 r3 | 純方法(P6) | 純方法 | O9 | 人工:無 | 是 |
| `w-vBOi8rmZI` | dopamine detox | I Did A Dopamine Detox For 30 Days... It Fixed My Brain | Easton Simpson | r2 | 第一人稱(P2) | 第一人稱 | O9 | 人工:無 | 是 |

**一致率**:15 支中 10 支一致 = **10/15(66.7%)**;排除規則輸出未分類的 `HTV1_gIfRDM` 後 **10/14(71.4%)**。
**不一致清單**:`h0FzoGEbMQA`(純方法 vs 不確定)、`mzQlJSn3Q80`(純方法 vs 不確定)、`fdwtHabUirM`(純方法 vs 第一人稱)、`QbOrby9YFFI`(純方法 vs 篩過的方法);另 `HTV1_gIfRDM` 規則未分類、人工不確定。
偏誤方向:4 支不一致全是規則判「純方法」、人工判成別的(1 支第一人稱、1 支篩過的方法、2 支不確定)⇒ 規則姿態**偏向多算純方法**,和事前登記預期的「P2 少算第一人稱」同方向。
另一需求:規則 O9 的 14 支,人工補判全為「無」;規則 O2(ESL)的 1 支,人工核對同意。

### 5. C1–C11 重現標記

判法照事前登記:每輪前 10、規則分類;3/3 = 3 次都重現,1–2 = 部分重現,0 = 未重現。強度數字只並列不判。

| # | 原文件結論 | 原報告 | 總督導複驗 | r1 | r2 | r3 | 標記 |
|---|---|---|---|---|---|---|---|
| C1 | `dopamine detox` 小頻道勝出 | 3/3 勝出,105.6× | — | 5 小/1 勝,105.68× | 5/2,106.0× | 5/1,106.17× | **3 次都重現** |
| C2 | `productivity…` 小頻道普遍勝出 | — | 7 小/6 勝,46.0× | 6/4 ✓ | 5/5 ✓ | 5/4 ✓ | **3 次都重現** |
| C3 | `study tips backed by science` 0 勝出 | — | 9/0 | 8/0 ✓ | 7/0 ✓ | 7/0 ✓ | **3 次都重現** |
| C4 | 「that actually work」≫「backed by science」 | — | 6 vs 0 | 4−0=4 ✓ | 5−0=5 ✓ | 4−0=4 ✓ | **3 次都重現** |
| C5 | `how to remember what i read` 有小頻道勝出 | 5/4,最佳 27.0×,中位 1,009,627 | 最佳 12.3×,中位約 57 萬 | 6/4,12.4×,571,896 ✓ | 6/4,12.6×,575,187 ✓ | 5/4,12.7×,577,170 ✓ | **3 次都重現**(二元部分;強度見 §6) |
| C6 | 同組有 ESL 混淆 | 未提 | 4 勝裡 2 個 ESL | 4 勝裡 1 ESL ✓ | 1 ✓ | 1 ✓ | **3 次都重現**(二元部分;比例見 §6) |
| C7 | `is manifestation real` 勝出者是方法形狀 | 有勝出(rxchelle) | 1 勝,27,200→297,315 | 1 勝(P6),0 裁決 ✓ | 1 勝(P6),0 裁決 ✓ | **0 勝** ✗ | **部分重現(2/3)** |
| C8 | 兩個 manifest query 贏同一支(rxchelle 1,103,741) | 是 | 否,0 重疊 | 勝出交集 0 ✗ | 0 ✗ | 0 ✗ | **未重現** |
| C9 | `how to manifest` 有小頻道勝出 | 是 | 0 勝 | 3/2 ✓ | 3/2 ✓ | 3/2 ✓ | **3 次都重現**(與原報告一致、與總督導複驗不一致) |
| C10 | 方法贏、裁決不贏 | E 格 14 query/41 小/0 勝 | — | 裁決 3 小/0 勝;純方法+篩過 9 勝(列數,未去重)✓ | 裁決 1 小/0 勝;11 勝 ✓ | 裁決 3 小/0 勝;9 勝 ✓ | **3 次都重現**(裁決分母很小,見 caveat K5) |
| C11 | `productivity…` 勝出約一半是第一人稱 | — | 6 勝中至少 3 | 2/4 = 50% ✓ | 2/5 = **40%**(剛好踩線)✓ | 2/4 = 50% ✓ | **3 次都重現**(r2 踩線,見下) |
| — | `how to improve memory` | 從未量過 | — | 首次讀數,不判 | | | 見 §7 ④ |

**「部分重現」指名變號的那一筆**
- **C7**:讓 r3 變號的是 `fdwtHabUirM`(Trevor Emdon,27,200 訂閱,298,852 觀看,10.99×)。它三輪都判 win,名次 10 → 4 → **11**;r3 掉到第 11 名,前 10 就沒有勝出片。前 20 三輪都有它(前 20 勝出 1/2/1)。⚠️ 本條**同時受時間漂移影響**(r2→r3 相隔 1 天 6 小時),r3 的 0 勝不能讀成「原結論錯」:形狀本身(方法形狀的小頻道片在這個 query 勝出)三輪都在,變的是它在不在第 10 名以內。

**「未重現」附:如果它其實有重現,會長什麼樣**
- **C8**:會長成「同一個 videoId 在同一輪同時出現在 `how to manifest` 與 `is manifestation real` 的前 10 勝出列」,原報告指的是 rxchelle 那支 1,103,741 觀看的片。我找的就是這個形狀:三輪的前 10 勝出交集都是 0、前 50 勝出交集都是 0(報表 manifest 重疊表,程式正常結束 exit 0、status complete);rxchelle 不在任一輪任一 query 的前 50。另用原始 JSON 獨立查一次:
  範圍 = 三個 `r*.json` 全文(含 search/videos/channels 原始回應);指令 = `timeout 120 grep -i -c "rxchelle" r1_20260911T1830Z.json r2_20260914T0111Z.json r3_20260915T0734Z.json`;輸出三檔皆 `0`、退出碼 1(grep 零命中);未逾時;陽性對照 `grep -c "fdwtHabUirM" r3_20260915T0734Z.json` = 13、退出碼 0。
  兩個 query 前 10 本身只共用 1 支(Jaccard 0.053,三輪相同),而且那支不是勝出片。

**C11 踩線**:r2 的 40% 是 2/5,多出來的分母是 `h0FzoGEbMQA`(r2 第 8 名,r1/r3 第 11 名)。若 r2 前 10 再多一支非第一人稱的勝出片就會變號;這條「3 次都重現」是脆的。

### 6. 兩處分歧的直接回答

**(1) `how to remember what i read` 最佳 v/s:原報告 27.0× vs 總督導複驗 12.3×**
三輪讀數 12.4× / 12.6× / 12.7×,勝出觀看中位 571,896 / 575,187 / 577,170 ⇒ **與總督導複驗(12.3×、約 57 萬)一致,原報告的 27.0×、中位 1,009,627 三輪都未重現**。
如果 27.0× 其實有重現,會長成「前 10 裡有一支訂閱 <15 萬、v/s ≈27 的勝出片,且勝出觀看中位接近 100 萬」;三輪前 10 小頻道片的 v/s 最高就是 `nbxi7_I09fI` 那支 12.4–12.7×,沒有這個形狀。
⚠️ 這個差異**可能是儀器差異**(原報告是 HTML 排序、地區與個人化未知;本次是 API relevance + US + en),不是證明 27.0× 當時是算錯的。本次能說的只有:用官方 API 的這個取樣口徑,三個配額日都量不到 27.0×。

**(2) ESL 混淆**
存在,三輪都有:`mzQlJSn3Q80`(English With Ethan,標題含 Graded Reader,規則 O2、人工核對同意)三輪都是該 query 前 10 勝出片。但比例是 **4 勝裡 1 個 ESL**(三輪相同),不是總督導複驗的 4 勝裡 2 個。
拿掉 ESL 後該 query 前 10 勝出 = 3 / 3 / 3,**勝出仍在**;ESL 混淆會改變強度讀數(`how to improve memory` 見 §7 ④),不會讓 C5 變號。
總督導那一個多出來的 ESL 片,在本次三輪的前 10 勝出列裡找不到;可能是複驗用前 12、或儀器/時間差異,本次無法區分。

### 7. 問題 ①–⑤

**① `productivity methods that actually work` 勝出片中第一人稱佔幾支**
| 輪 | 勝出 | 規則第一人稱(P2) | 人工第一人稱 | 人工不確定 |
|---|---|---|---|---|
| r1 | 4 | 2(50%) | 2(50%) | 0 |
| r2 | 5 | 2(40%) | 2(40%) | 1(`h0FzoGEbMQA`;若判第一人稱則 3/5 = 60%) |
| r3 | 4 | 2(50%) | 2(50%) | 0 |
兩支第一人稱三輪都是同樣兩支(`NZD5IFpyDcE`、`sPYxSrsH04I`)。七個 query 全部勝出片的規則 vs 人工一致率與不一致清單見 §4(10/15;排除規則未分類 10/14)。

**② 拿掉 ESL / 其他需求後的勝出數(前 10)**
| query | r1 | r2 | r3 |
|---|---|---|---|
| productivity… | 4 | 5 | 4 |
| study tips… | 0 | 0 | 0 |
| how to remember what i read | 3 | 3 | 3 |
| how to manifest | 2 | 2 | 2 |
| is manifestation real | 1 | 1 | 0 |
| how to improve memory | 0 | 1 | 1 |
| dopamine detox | 1 | 2 | 1 |
規則口徑(勝出 − 規則命中另一需求)與人工補判後口徑**相同**:規則命中另一需求的只有 ESL 那 1 支(兩個 query 各算一次),其餘 O9 的 14 支人工補判皆為「無」。

**③ manifest 重疊;rxchelle 1,103,741 是否兩邊都出現**
| 輪 | 前 10 交集(Jaccard) | 前 50 交集(Jaccard) | 前 10 勝出交集 | 前 50 勝出交集 | rxchelle |
|---|---|---|---|---|---|
| r1 | 1(0.053) | 4(0.042) | 0 | 0 | 兩個 query 前 50 都沒有 |
| r2 | 1(0.053) | 3(0.031) | 0 | 0 | 同上 |
| r3 | 1(0.053) | 4(0.042) | 0 | 0 | 同上 |
**rxchelle 三輪都不在任一邊的前 50**(查法、範圍、退出碼、陽性對照見 §5 C8)。兩個 query 回的幾乎是兩組不同的片;原報告「兩邊贏同一支」本次未重現,與總督導複驗一致。

**④ `how to improve memory` 首次讀數**
- 前 10:r1 1 小/1 勝、r2 2/2、r3 2/2;前 50:14/7、13/7、14/8。
- 前 10 勝出:`mzQlJSn3Q80` English With Ethan(**ESL**,3.61–3.64×,三輪都在);`QbOrby9YFFI` Dr. Sikandar Adwani(19,000 訂閱,207,269–217,339 觀看,11.02–11.44×,r1 在第 18 名、r2/r3 第 9 名)。
- **拿掉 ESL 後:0 / 1 / 1**。r1 的「有勝出」**全靠 ESL 那一支**;r2/r3 多出來的那支是醫師背書的方法片(人工姿態:篩過的方法)。
- 首次讀數的讀法:這個 query 前 10 小頻道很少(1–2 支),前 50 則有 7–8 支勝出 ⇒ 需求在、但前 10 被大頻道佔住;非 ESL 的小頻道勝出片最佳約 11×。不判重現(沒有原值可比)。

**⑤ 姿態階梯 A–E 還成立嗎**(前 10、七個 query、每輪;姿態照規則;A=P6 純方法、B=P5 篩過的方法、C=P2 第一人稱實測、D/D'=P3 迷思清單、E=P4 裁決)
| 格 | 原報告 v/s 上界 | r1 小/勝,勝出最佳 | r2 | r3 | 讀法 |
|---|---|---|---|---|---|
| A 純方法 | 105.6× | 15/9,105.68× | 16/11,134.93× | 14/9,106.17× | **成立**;r2 的 134.93× 是 17 秒 Short(`h0FzoGEbMQA`),其餘兩輪上界與原值幾乎相同 |
| B 篩過的方法 | 46.0× | 9/0,— | 7/0,— | 7/0,— | **本口徑下無法重現這一格**:原報告的 B 是**按 query 措辭**(「…that actually work」)分,本次是**按標題**分;productivity 那組勝出片的標題幾乎都不含證據詞,落在 A/C。標題帶證據詞的小頻道片三輪都是 study tips 的低觀看片(最佳 54–56× 但觀看 8,048–8,330 <50,000),0 勝 |
| C 第一人稱實測 | 40.4× | 3/3,40.57× | 4/4,40.77× | 3/3,40.85× | **成立**,上界與原值幾乎相同(同一支 Cormac Taylor) |
| D / D' 迷思清單 | 26.5× / 5.5× | 0/0 | 0/0 | 0/0 | **不可判**:七個 query 前 10 沒有任何一支小頻道迷思清單片;本派工的 query 不含原報告 D 格的健康/心理迷思 query,**我沒有量這一格**,不是量到 0 |
| E 裁決 | 0(14 query/41 小/0 勝) | 3/0 | 1/0 | 3/0 | **方向成立**(三輪 0 勝),但分母 1–3,遠小於原報告的 41 |
| (未分類 P8) | — | 2/1,4.92× | 3/1,4.91× | 3/1,4.89× | `HTV1_gIfRDM`,人工補判不確定 |
結論:階梯的**兩端**(A 高、E 為 0)和 **C ≈40×** 三輪都在;**B 格在本口徑下量不到**,**D/D' 格本次沒量**。「A > B > C > D > E 的完整排序」本次**不能宣稱重現**,只能說 A、C、E 三格各自的讀數重現了。

### 8. Caveats(每條四件套:未量到什麼 / 量法 / 量到什麼就可以撤 / 撤掉之後還剩什麼不敢宣稱)

**K1 同日內的儀器噪音未測(空缺,不是零)**
- 未量到:同一配額日內、同工具同參數、相隔數小時抽兩次,前 10 與勝出判定會差多少。
- 量法:同一配額日內相隔 ≥2 小時各跑一輪 `ch3_remeasure.py`(同 commit、同參數),報七個 query 的前 10 交集 / Jaccard、各 query 勝出數差、邊界名次變動。
- 可撤條件:**我**跑完這一對、落盤、且結果寫進本文件後,這條才撤。(`95d134fb` 已否決「再抽兩輪」的額度,所以本次**不撤**。)
- 撤掉後仍不敢宣稱:其他日期、其他地區/語言參數、其他 query 的同日噪音;以及「日間差異 − 同日噪音 = 純時間漂移」這種相減(兩者不一定可加)。

**K2 三輪之間的差異不可歸因(r1/r2、r2/r3 都是)**
- 未量到:把「儀器噪音」和「搜尋結果真的換了」分開。
- 量法:先完成 K1 的同日對;日間差異明顯大於同日噪音的部分,才可以讀成時間漂移。
- 可撤條件:K1 撤掉之後,**我**把三輪差異和同日噪音並列算過並寫進本文件。
- 撤掉後仍不敢宣稱:漂移的**原因**(演算法改動、新片上架、觀看數成長改變排序)—— 這些本工具不量。

**K3 本次與原報告/總督導複驗之間的差異可能是儀器差異**
- 未量到:原 HTML 儀器與官方 API 在同一時間、同一 query 下的差異。
- 量法:唯一的量法是重建原 HTML 爬蟲同時跑,**違反 YouTube ToS III.E.6,不做**。
- 可撤條件:沒有合法量法 ⇒ 本條**不可撤**,永久保留;任何「原報告算錯了」的讀法都不成立。
- 撤掉後仍不敢宣稱:(不適用,不撤)。

**K4 姿態分類只看標題,且只有我一個人工標註者**
- 未量到:人工姿態欄的可靠度(第二位標註者的一致率),以及看影片內容後會不會改判。
- 量法:fresh-context 查證員在不看本文件人工欄的條件下,獨立標註 §4 同一批 15 支,算與我的人工欄一致率,並列不一致清單。
- 可撤條件:獨立標註落盤、**我**算完兩人一致率並寫進本文件。
- 撤掉後仍不敢宣稱:看內容(不只看標題)的姿態;以及本批 15 支以外勝出片的分類可靠度。

**K5 裁決格(E)與迷思清單格(D/D')分母太小或為零**
- 未量到:足夠母體下裁決/迷思形狀的小頻道勝出率;D/D' 本次完全沒量。
- 量法:另開一次事前登記,放入原報告 E 格與 D 格用過的 query,同工具同判準跑,報各格小頻道數與勝出數。
- 可撤條件:**我**量到 E 格前 10 小頻道累計 ≥30 支(原報告 41 的同量級)且勝出數寫進文件;D/D' 同樣各有讀數之後。
- 撤掉後仍不敢宣稱:英文 US 以外市場;以及「做裁決形狀一定不會贏」(撤得掉「這批沒贏」,撤不掉「永遠不會贏」)。

**K6 v/s 用的是抓取當天的訂閱數**
- 未量到:影片發布當時的訂閱數。
- 量法:官方 API 不提供歷史訂閱數 ⇒ 用合法管道**量不到**。
- 可撤條件:本條不可撤;偏誤方向已知(今天訂閱 ≥ 當時訂閱 ⇒ v/s 偏低 ⇒ 小頻道勝出判定偏保守)。
- 撤掉後仍不敢宣稱:(不適用,不撤)。

**K7 前 10 截斷對邊界片很敏感**
- 未量到:以前 10 為界的標記,在前 20 口徑下會不會翻。
- 量法:報表已印前 20 / 前 50 的 小/勝;C7 前 20 三輪都有勝出(1/2/1)、`QbOrby9YFFI` 與 `h0FzoGEbMQA` 在前 20 內三輪都在。
- 可撤條件:**我**把 C1–C11 用前 20 口徑逐條重判一次並寫進本文件(本次只做了上面這幾支邊界片,**沒有**逐條重判)。
- 撤掉後仍不敢宣稱:前 20 以外(使用者實際不太會滑到)的排序對真實分發的意義。

### 9. 限制(與最終回報的「限制」段同一份)
- 🔴 r1→r2 相隔 2 天 7 小時,差異**不可歸因**,只能當保守下界;分支 B 下 r2→r3 也相隔 1 天 6 小時,同樣不可歸因 ⇒ **不做任何儀器穩定度/漂移量的宣稱**。
- 本次量到的是日間變異。同日內的儀器噪音未測。
- 判準替換依據:commit `95d134fb`(本文件不修改、不抄錄該檔)。
- 原始資料保存到 2026-10-12,屆時照「資料保存」段分類處理;刪除後以 §2 指紋表核對。
