# 交棒檔 — wB:p1 第五棒(渲染前)

> 交棒理由:context 遠超 200K,而**渲染 + 影像層驗證是一段長工作**,
> 不要在快撞頂的時候開始(撞頂是靜默停擺,memory `usage-limit-silent-stall`)。
> 規格以 `docs/ops/2026-09-09_ch3_recurrence_test_spec.md` 為準;
> 判準以 `docs/ops/2026-09-09_ch3_criteria_revision.md` 為準(它**不覆蓋**登記檔,兩份一起讀)。
>
> **手上沒有只活在逐字稿裡的東西。**

---

## 〇、一句話狀態

**稿、事實、判準、發布路徑、量測基線全部通過三輪獨立驗證。
6 支影片至今未渲染。零對外動作。**

🔴 **不要把「三輪收斂」讀成快好了。**
三輪驗的全是稿與制度,**沒有一輪碰到影像**。下一步是一道**新閘門**,不是最後一哩。

---

## 一、下一棒的順序(不可換)

🔴 **直譯器不是 `python`。** 裸的 `python` 是系統 Python39,
**沒有 matplotlib / moviepy / soundfile / kokoro / imageio_ffmpeg** ——
第五棒照這份檔跑第一支就 `ModuleNotFoundError`,而且它在 TTS 跑完之後才炸,
留下一個**半成品的 `reels/<slug>/` 目錄**(5 個完整的 wav),
對下游是合法輸入。渲染線的直譯器是那個 venv:

```
PY=D:/carson-agent/youtube_channel/.venv/Scripts/python.exe
```
(`_renderq.sh` / `_farm1.ps1` / `_v5_0.sh` 三支都是這麼設的。)

```
cd D:\carson-agent\ch3_lab

# 0) 先確認閘門這套還是好的(三輪都靠它)
$PY gate_registry.py            # 應印「N 道閘門 … ✓」(09-10 起是 6 道)
$PY _control_gate_registry.py   # rc 必須 0

# 1) 渲染六支,一支約 3.5 分鐘
$PY make_reel.py --slug study_techniques
$PY make_reel.py --slug how_to_remember_what_you_read
$PY make_reel.py --slug focus_techniques
$PY make_reel.py --slug if_then_plans
$PY make_reel.py --slug learning_styles
$PY make_reel.py --slug pomodoro
#  🔴 每支都要看 rc。片長不在 35~50 秒會印 ⛔ 並回 1 —— 那是要**改稿重渲**。
#  🔴 **不准為了不重渲而放寬硬帶。**

# 2) 影像層驗證(見 §二)—— 這是新的一道閘門
# 3) 人工看過才標:$PY mark_verified.py <slug>
# 4) reel_gate 的 papers 分支陽性對照(見 §三)
# 5) 🔴 派 fresh-context 獨立驗證員,重點**全部在畫面上**
# 6) 發布(見 §四)
```

---

## 二、🔴 影像層:歷史事故清單是三輪裡最長的

1. **版面重疊** —— 已上線的片實測兩欄相撞 **22×10 畫素**,而逐元素驗四個邊**全綠**。
   🔴 **逐元素邊界檢查對「重疊」是結構性盲的**:每個元素各自都在安全區內,
   兩個合起來才撞。要驗的是元素**兩兩之間的交集**,不是各自出不出界。
2. **黑底黑字**。
3. **揭露時序偏移** —— 已上線的片畫面顯示 `r = 0.28` 而旁白正唸 `minus 0.05`,**六支中招**。

### 渲染前就知道的兩個風險

- `focus_techniques` 有一列**沒有數值**(Ariga & Lleras,原文只給 F 值,唸成百分比會超出原文範圍)。
  守衛讓它印文字不印數字 —— **那是對的,比硬湊一個數字誠實**。
  但**「三列只有兩個數字」的版面沒人看過**,而欄寬是從**有值的列**倒推的
  (`make_reel.py` 的 `vals … or ["x"]` 那段)⇒ **抽幀時特別看那一格。**
- `focus_techniques` **46 秒**、`how_to_remember_what_you_read` **47 秒**,硬帶 35~50,
  **兩支都貼上界**。估長是字數 ÷ 2.6,渲完會量實際值。

---

## 三、發布前還沒補的那一格陽性對照

`publish_shorts.reel_gate()` 的 `papers` 分支(要求**每一篇** DOI 都在說明欄裡、且至少三篇)
**還沒有做過陽性對照** —— 因為它要有真的 mp4 才跑得到。
⇒ 渲完之後:故意從某一支的說明欄刪掉一個 DOI,確認它會擋。**沒補之前不准發。**

唯讀、不連網的兩支可以先跑:
`$PY publish_shorts.py --list`、`$PY publish_shorts.py --dry-run`。

---

## 四、發布(三件會咬人的)

1. 🔴 **`publish_shorts.py` 沒有 `--privacy` 也沒有 `--flip`**,`privacyStatus` 寫死 `"public"`
   ⇒ **一發就是公開,沒有兩段式。** README 那句 `--flip public` 講的是長片線。
2. 🔴 **`--only` 必須同時帶 `--limit 6`**。`--limit` 預設 **2** 且切在 `--only` **之後**
   ⇒ 不帶只會發前 2 支,而按字母序**兩支都是 B 臂、E 臂 0 支**(沒有對照組的兩臂實驗)。
   ```
   $PY publish_shorts.py --only reel_study_techniques,reel_how_to_remember_what_you_read,reel_focus_techniques,reel_if_then_plans,reel_learning_styles,reel_pomodoro --limit 6
   ```
3. **配額**:專案 `881902283633`(ch2/ch3),不影響主頻道。6 支約 9,636~9,936。
   發布前跑一次 `$PY quota.py` 看即時值。

---

## 五、量測(判準檔已凍結,不要再動)

- **判準 A**:B 臂 4 支裡 ≥2 支 `engagedViews` ≥ **6**(= 既有 **57 支 public** 的 P90;
  全帳本 60 支的 P90 是 5，**採較難的那個**)
- **閘門 0**:至少 1 支 ≥ **10**(頻道史上單支最高)。不過就**不准對姿態下任何結論**
- **判準 B**:median(B)/median(E) ≥ 3;E 中位為 0 時改判 B 中位 ≥3 且 E 兩支皆 ≤1
- **判準 C**:發布後 14 天窗 `YT_SEARCH` views ≥ **122**(= 對照窗 61 × 2)

🔴 **讀數用 `$PY window_readout.py --start … --end … --measurement`**:
- 量測窗讀數**不得早於「窗結束日 + 4 天」**(`--measurement` 把這條升為硬閘門)
- 完整性判準是**資料視界**,**不是列數** —— 零觀看日根本不回列,
  用列數會把完整的窗判成不完整,而錯誤訊息會說「資料還沒進來」(**一個很有說服力的錯誤診斷**)

---

## 六、閘門這套怎麼用(第三棒的產物,別繞過它)

`gate_registry.py`:**規則的定義 = 它的對照腳本的 `CASES` 清單**,
而 docstring 裡的描述是**從 CASES 產生**的(`--sync`),不是人手寫的。

⇒ **要改規則,先改 CASES,再 `--sync`。** 直接改 docstring 會被 R3 偵測器擋下。
⇒ 四份對照:`_control_orphan` / `_control_prereg_title` / `_control_display_vs_facts`
  / `_control_gate_registry`,rc 都必須 0。

⚠️ **這套治不了的**:對照腳本自己的案例清單**會過期**
(memory `gate-blind-while-target-evolves`)。它需要定期用真案例證明它還抓得到。
**這件事沒有完結,不要讀成完結。**

---

## 七、常態排程:用內容查,不要用行號

```
grep -n "ch3_publish" youtube_channel/deploy/crontab.txt      # 三行都必須以 # 開頭
grep -n "ch3" youtube_channel/deploy/crontab.txt | grep -v "^[0-9]*:#"
```
後者應只回一行 `ch3_health.py`(唯讀健檢)。
⚠️ 這個檔**一天之內 blob 變了兩次**(別的 session 在檔尾加東西),
行號從 775~777 漂到 784~786。**照行號查的人會看到錯的三行然後回報「已確認」。**

---

## 八、還沒動、需要拍板的

1. 🔴 **規格 §0.3 那份轉抄進來的核准**(`drill regression 那支排進排程`)——
   **沒動,連準備都沒做**,等 Carson 本人回覆。
2. **`control` 欄位那個設計案**(每條 claim 申報對照組)——總督導**核准方向但擱置**,
   等第 5 項收尾後再議。
   🔴 **它擋不到 4c 那五條**(起源宣稱 / 引用頻率 / randomised / 全稱宣稱 / 主觀成本)
   —— 不要因為建了這道就以為那一類也蓋住了。**那五條目前只能靠人讀。**
3. 兩支**舊片**被粗關鍵詞掃到(`hungry_judges` / `sugar_hyperactivity`),
   **未查證,不要當缺陷回報**;值得有人用同一個視角讀一次舊片的稿,但那是另一件工作。
